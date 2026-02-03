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
    save_force_delete_records,
)

from .config import config

if TYPE_CHECKING:
    from src.common.cache.force_delete import TaskInfo
    from src.db import GroupInfo

# 内存中维护的活动任务列表
# Key: tid, Value: TaskInfo (包含 attempts)
_active_tasks: dict[str, TaskInfo] = {}
_worker_task: asyncio.Task | None = None
_lock = asyncio.Lock()


def get_task_id(group_id: int, tid: int) -> str:
    return f"{group_id}_{tid}"


async def check_thread_status(group_info: GroupInfo, tid: int) -> str:
    """
    检查帖子是否已存在

    :Returns: 错误信息，空字符串表示存在
    """
    try:
        client = await ClientCache.get_bawu_client(group_info.group_id)
        posts = await client.get_posts(tid)
        if posts.thread.tid == 0:
            return "获取帖子状态失败，可能已被删除"
        else:
            return ""
    except AiotiebaError as e:
        return f"获取帖子状态失败，{e}"
    except TimeoutError:
        return "获取帖子状态时请求超时"
    except Exception as e:
        logger.warning(f"[ForceDelete] 检查帖子状态异常 tid={tid}: {e}")
        return f"获取帖子状态时发生错误: {e}"


async def add_task(group_info: GroupInfo, message_id: int, bot_id: str, tid: int, operator_id: int) -> str:
    """添加任务"""
    async with _lock:
        task_id = get_task_id(group_info.group_id, tid)
        if task_id in _active_tasks:
            return "该帖子已在强制删除队列中。"

        expire_time = time.time() + (config.force_delete_max_duration * 60)
        info: TaskInfo = {
            "bot_id": bot_id,
            "message_id": message_id,
            "group_id": group_info.group_id,
            "fid": group_info.fid,
            "operator_id": operator_id,
            "expire_time": expire_time,
            "attempts": 0,
            "thread_id": tid,
        }
        # 1. 写入持久化缓存
        await add_force_delete_record(task_id, info)
        # 2. 更新内存
        _active_tasks[task_id] = info

    # 确保 Worker 运行
    _ensure_worker_running()

    return f"已启动强制删帖任务 tid={tid}，将在后台持续尝试删除{config.force_delete_max_duration}分钟。"


async def remove_task(task_id: str) -> bool:
    """移除任务"""
    async with _lock:
        if task_id in _active_tasks:
            del _active_tasks[task_id]
            await remove_force_delete_record(task_id)
            return True

    return False


async def cancel_task(group_id: int, tid: int) -> str:
    """取消任务"""
    task_id = get_task_id(group_id, tid)
    if await remove_task(task_id):
        return f"已取消对帖子 tid={tid} 的强制删除任务。"
    else:
        await remove_force_delete_record(task_id)
        return f"未找到帖子 tid={tid} 的进行中任务。"


def get_task_info(group_id: int, tid: int) -> str:
    """查询任务状态"""
    task_id = get_task_id(group_id, tid)
    if task_id in _active_tasks:
        attempts = _active_tasks[task_id]["attempts"]
        return (
            f"进行中，已尝试删除 {attempts} 次，"
            f"持续到 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_active_tasks[task_id]['expire_time']))}。"
        )
    return "无进行中任务"


async def restore_tasks():
    """系统启动时恢复未完成的任务"""
    global _active_tasks
    tasks = await get_all_force_delete_records()
    now = time.time()
    count = 0

    async with _lock:
        for task_id, info in tasks.items():
            if info["expire_time"] > now:
                _active_tasks[task_id] = info
                count += 1
            else:
                # 清理过期任务
                await remove_force_delete_record(task_id)

    if count > 0:
        logger.info(f"[ForceDelete] 已恢复 {count} 个强制删帖任务")
        _ensure_worker_running()


async def save_active_tasks():
    """系统关闭时保存当前的活动任务"""
    async with _lock:
        await save_force_delete_records(_active_tasks)


def _ensure_worker_running():
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


async def send_feedback(task_info: TaskInfo, message: str) -> bool:
    """发送反馈消息到群组"""
    try:
        try:
            bot = get_bot(task_info["bot_id"])
        except KeyError:
            logger.error(f"[ForceDelete] 发送反馈消息失败: 机器人 {task_info['bot_id']} 未上线")
            return False

        await bot.send_group_msg(
            group_id=task_info["group_id"],
            message=MessageSegment.reply(task_info["message_id"]) + MessageSegment.text(message),
        )
        return True
    except Exception as e:
        logger.error(f"[ForceDelete] 发送反馈消息失败: {e}")
        return False


ALLOW_CODES = frozenset((*ErrorHandler.RETRIABLE_CODES, 224009)) - {300000}


async def _worker_loop():
    """单任务循环执行器"""

    logger.debug("[ForceDelete] Worker 启动")

    while _active_tasks:
        try:
            for task_id, task_info in _active_tasks.copy().items():
                if task_id not in _active_tasks:
                    continue

                thread_id = task_info["thread_id"]

                now = time.time()
                sleep_until = 1.0 / max(1, config.force_delete_rps) + now
                try:
                    if now > task_info["expire_time"]:
                        logger.info(f"[ForceDelete] 任务超时: tid={thread_id}")
                        await remove_task(task_id)
                        await send_feedback(
                            task_info,
                            f"强制删帖任务已超时，未能成功删除帖子 tid={thread_id}。",
                        )
                        continue

                    task_info["attempts"] += 1
                    client = await ClientCache.get_bawu_client(task_info["group_id"])
                    success = await client.del_thread(task_info["fid"], thread_id)

                    if success:
                        logger.info(f"[ForceDelete] 删帖成功: tid={thread_id}")
                        await remove_task(task_id)
                        await send_feedback(
                            task_info,
                            f"强制删帖任务已成功删除帖子 tid={thread_id}。",
                        )
                except AiotiebaError as e:
                    if e.code not in ALLOW_CODES:
                        if e.code == 300000:
                            e.msg = "权限不足"
                        logger.warning(f"[ForceDelete] 删除失败 tid={thread_id}: {e}")
                        await remove_task(task_id)
                        await send_feedback(
                            task_info,
                            f"强制删帖任务删除帖子 tid={thread_id} 失败: {e}，已终止任务。",
                        )
                except Exception as e:
                    logger.error(f"[ForceDelete] 删除任务异常 tid={thread_id}: {e}")
                    await remove_task(task_id)
                    await send_feedback(
                        task_info,
                        f"强制删帖任务删除帖子 tid={thread_id} 时发生错误: {e}，已终止任务。",
                    )

                await asyncio.sleep(max(0, sleep_until - time.time()))
        except asyncio.CancelledError:
            logger.info("[ForceDelete] Worker 停止，任务被取消")
            break
        except Exception as e:
            logger.error(f"[ForceDelete] Worker 异常: {e}")
            await asyncio.sleep(1)
    else:
        logger.info("[ForceDelete] Worker 停止，任务队列为空")
