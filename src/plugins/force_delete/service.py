from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import MessageSegment
from tiebameow.client.tieba_client import AiotiebaError, ErrorHandler

from src.common.cache import (
    ClientCache,
    add_force_delete_record,
    get_all_force_delete_records,
    remove_force_delete_record,
    update_force_delete_record,
)

from .config import config

if TYPE_CHECKING:
    from src.common.cache.force_delete import TaskInfo
    from src.db import GroupInfo

# 内存中维护的活动任务列表
# Key: tid, Value: TaskInfo (包含 attempts)
_active_tasks: dict[int, TaskInfo] = {}
_worker_task: asyncio.Task | None = None
_lock = asyncio.Lock()


async def check_thread_status(group_info: GroupInfo, tid: int) -> str:
    """
    检查贴子是否已存在

    :Returns: 错误信息，空字符串表示存在
    """
    try:
        client = await ClientCache.get_bawu_client(group_info.group_id)
        posts = await client.get_posts(tid)
        if posts.thread.tid == 0:
            return "获取帖子状态失败，可能已被删除"
        else:
            return ""
    except Exception:
        return "获取帖子状态失败，可能已被删除"


async def add_task(group_info: GroupInfo, message_id: int, bot_id: str, tid: int, operator_id: int) -> str:
    """添加任务"""
    async with _lock:
        if tid in _active_tasks:
            return "该贴子已在强制删除队列中。"

        expire_time = time.time() + (config.force_delete_max_duration * 60)
        info: TaskInfo = {
            "bot_id": bot_id,
            "message_id": message_id,
            "group_id": group_info.group_id,
            "fid": group_info.fid,
            "operator_id": operator_id,
            "expire_time": expire_time,
            "attempts": 0,
        }

        # 1. 写入持久化缓存
        await add_force_delete_record(tid, info)
        # 2. 更新内存
        _active_tasks[tid] = info

    # 确保 Worker 运行
    _ensure_worker_running()

    return f"已启动强制删帖任务 tid={tid}，将在后台持续尝试删除{config.force_delete_max_duration}分钟。"


async def cancel_task(tid: int) -> str:
    """取消任务"""
    async with _lock:
        if tid in _active_tasks:
            del _active_tasks[tid]
            await remove_force_delete_record(tid)
            return f"已取消对贴子 tid={tid} 的强制删除任务。"

    # 尝试清理持久化缓存（防止僵尸记录）
    await remove_force_delete_record(tid)
    return f"未找到贴子 tid={tid} 的进行中任务。"


def get_task_info(tid: int) -> str:
    """查询任务状态"""
    if tid in _active_tasks:
        attempts = _active_tasks[tid]["attempts"]
        return (
            f"进行中，已尝试删除 {attempts} 次，"
            f"持续到 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_active_tasks[tid]['expire_time']))}。"
        )
    return "无进行中任务"


async def restore_tasks():
    """系统启动时恢复未完成的任务"""
    global _active_tasks
    tasks = await get_all_force_delete_records()
    now = time.time()
    count = 0

    async with _lock:
        for tid, info in tasks.items():
            if info["expire_time"] > now:
                _active_tasks[tid] = info
                count += 1
            else:
                # 清理过期任务
                await remove_force_delete_record(tid)

    if count > 0:
        logger.info(f"[ForceDelete] 已恢复 {count} 个强制删帖任务")
        _ensure_worker_running()


def _ensure_worker_running():
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


async def send_feedback(task_info: TaskInfo, message: str):
    """发送反馈消息到群组"""
    try:
        bot = get_bot(task_info["bot_id"])
        await bot.send_group_msg(
            group_id=task_info["group_id"],
            message=MessageSegment.reply(task_info["message_id"]) + MessageSegment.text(message),
        )
    except Exception as e:
        logger.error(f"[ForceDelete] 发送反馈消息失败: {e}")


ALLOW_CODES = set(ErrorHandler.RETRIABLE_CODES)
ALLOW_CODES.add(224009)


async def _worker_loop():
    """单任务循环执行器"""
    logger.debug("[ForceDelete] Worker 启动")

    while True:
        try:
            # 1. 控制 RPS
            sleep_time = 1.0 / max(1, config.force_delete_rps)
            await asyncio.sleep(sleep_time)

            async with _lock:
                if not _active_tasks:
                    continue

                # 获取当前时间用于检查过期
                now = time.time()
                tids_to_remove = []

                # 简单轮询：这里每次循环只取一个任务执行
                # 为了简单起见，这里将其转换为列表取第一个，或者可以维护一个队列
                # 考虑到 active_tasks 可能变化，转 list 虽然有开销但在任务量不大时可接受
                # 更好的方式可能是使用 cycle iterator，但在 dict 变化时可能会有问题

                # 这里采用：随机选一个或者按顺序选一个（dict顺序）
                # 实际每次只处理一个任务
                current_tid = next(iter(_active_tasks))
                task_info = _active_tasks[current_tid]

                # 检查是否过期
                if now > task_info["expire_time"]:
                    logger.info(f"[ForceDelete] 任务超时: tid={current_tid}")
                    tids_to_remove.append(current_tid)
                else:
                    # 执行删除逻辑需要释放锁，避免阻塞 add/cancel
                    pass

            # 移除过期任务
            if tids_to_remove:
                async with _lock:
                    for tid in tids_to_remove:
                        if tid in _active_tasks:
                            del _active_tasks[tid]
                            await remove_force_delete_record(tid)
                            await send_feedback(
                                task_info,
                                f"强制删帖任务已超时，未能成功删除贴子 {tid}。",
                            )
                continue

            # 执行删除
            try:
                client = await ClientCache.get_bawu_client(task_info["group_id"])
                try:
                    success = await client.del_thread(task_info["fid"], current_tid)
                except AiotiebaError as e:
                    success = False
                    if e.code == 300000 or not e.code not in ALLOW_CODES:
                        if e.code == 300000:
                            e.msg = "权限不足"
                        logger.warning(f"[ForceDelete] 删除失败 (tid={current_tid}): {e}")
                        await send_feedback(
                            task_info,
                            f"强制删帖任务删除贴子 {current_tid} 时发生错误: {e}: {e.msg}，已终止任务。",
                        )
                        async with _lock:
                            await remove_force_delete_record(current_tid)

                            if current_tid in _active_tasks:
                                del _active_tasks[current_tid]

                # 更新尝试次数
                task_info["attempts"] += 1
                # 只要任务还在 active_tasks 中，就更新缓存（为了重启后能看到次数）
                if task_info["attempts"] % 10 == 0:
                    await update_force_delete_record(current_tid, task_info["attempts"])

                if success:
                    logger.info(f"[ForceDelete] 删帖成功: tid={current_tid}")
                    async with _lock:
                        if current_tid in _active_tasks:
                            del _active_tasks[current_tid]
                            await remove_force_delete_record(current_tid)
                            await send_feedback(
                                task_info,
                                f"强制删帖任务已成功删除贴子 {current_tid}。",
                            )
            except Exception as e:
                logger.error(f"[ForceDelete] 删除任务异常 (tid={current_tid}): {e}")

            # 将当前任务移动到字典末尾，实现简单的 Round-Robin
            async with _lock:
                if current_tid in _active_tasks:
                    # pop and re-insert to move to end (Python 3.7+ dicts are ordered)
                    val = _active_tasks.pop(current_tid)
                    _active_tasks[current_tid] = val

        except asyncio.CancelledError:
            logger.info("[ForceDelete] Worker 停止")
            break
        except Exception as e:
            logger.error(f"[ForceDelete] Worker 异常: {e}")
            await asyncio.sleep(1)
