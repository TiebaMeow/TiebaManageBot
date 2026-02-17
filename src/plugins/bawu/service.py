from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from aiotieba import PostSortType
from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import MessageSegment
from tiebameow.client.tieba_client import AiotiebaError, ErrorHandler, UnretriableApiError

from src.common import tieba_uid2user_info_cached
from src.common.cache import (
    ClientCache,
    add_force_delete_record,
    get_all_force_delete_records,
    remove_force_delete_record,
    save_force_delete_records,
)
from src.db import TextDataModel
from src.db.crud import add_associated_data

from .config import config

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tiebameow.client import Client

    from src.common.cache.force_delete import TaskInfo
    from src.db import GroupInfo


async def delete_threads(
    client: Client, group_info: GroupInfo, tids: Iterable[int], uploader_id: int
) -> tuple[list[int], list[int], list[int]]:
    """
    删贴并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tids: 要删除的贴子ID列表
        uploader_id: 执行删除操作的用户ID

    Returns:
        (succeeded_tids, failed_tids, protected_tids)
    """
    succeeded = []
    failed = []
    protected = []
    for tid in tids:
        posts = await client.get_posts(tid)
        user_info = await client.get_user_info(posts.thread.author_id)

        if posts.thread.type == 40:
            # 视频贴，需要调用del_post接口删除
            del_coro = client.del_post(group_info.fid, tid, posts.thread.pid)
        else:
            del_coro = client.del_thread(group_info.fid, tid)

        try:
            result = await del_coro
            if result:
                succeeded.append(tid)
                await add_associated_data(
                    user_info,
                    group_info,
                    text_data=[
                        TextDataModel(
                            uploader_id=uploader_id,
                            fid=group_info.fid,
                            text=f"[自动添加]删贴\n标题：{posts.thread.title}\n{posts.thread.text}",
                        )
                    ],
                )
            else:
                failed.append(tid)

        except UnretriableApiError as e:
            if e.code == 224009:
                # 贴子受保护无法删除
                protected.append(tid)
            else:
                failed.append(tid)

    return succeeded, failed, protected


async def delete_posts(
    client: Client, group_info: GroupInfo, tid: int, floors: Iterable[str], uploader_id: int
) -> tuple[list[int], list[str], str]:
    """
    删回复（楼层）并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tid: 贴子ID
        floors: 要删除的楼层列表
        uploader_id: 执行删除操作的用户ID

    Returns:
        (succeeded_pids, failed_floors, error_message)
    """
    succeeded = []
    failed = []
    floor_list = []

    thread_info = await client.get_posts(tid, pn=1, rn=10, sort=PostSortType.DESC)
    if not thread_info.objs:
        return [], [], "获取贴子信息失败，请检查输入。"

    floor_num = thread_info.objs[0].floor
    for floor in floors:
        if not floor.isdigit() or int(floor) > floor_num or int(floor) < 2:
            failed.append(floor)
            continue
        floor_list.append(int(floor))

    if not floor_list:
        return [], failed, "没有有效的楼层输入，请检查输入。"

    for pni in range(floor_num // 30 + 1):
        batch_posts = await client.get_posts(tid, pn=pni + 1, rn=30, sort=PostSortType.ASC)
        for post in batch_posts.objs:
            if post.floor in floor_list:
                if not await client.del_post(group_info.fid, post.tid, post.pid):
                    failed.append(str(post.floor))
                    continue
                succeeded.append(post.pid)
                user_info = await client.get_user_info(post.author_id)
                await add_associated_data(
                    user_info,
                    group_info,
                    text_data=[
                        TextDataModel(
                            uploader_id=uploader_id,
                            fid=group_info.fid,
                            text=f"[自动添加]删回复\n原贴：{post.tid}\n内容：{post.text}",
                        )
                    ],
                )
    return succeeded, failed, ""


async def blacklist_users(
    client: Client, group_info: GroupInfo, uids: Iterable[int], uploader_id: int, blacklist: bool = True
) -> tuple[list[int], list[int]]:
    """
    拉黑/取消拉黑用户并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        uids: 要拉黑/取消拉黑的贴吧UID列表
        uploader_id: 执行操作的用户ID
        blacklist: 是否为拉黑操作，默认为 True（拉黑）

    Returns:
        (succeeded_uids, failed_uids)
    """
    succeeded = []
    failed = []
    for tieba_uid in uids:
        user_info = await tieba_uid2user_info_cached(client, tieba_uid)
        if user_info.user_id == 0:
            failed.append(tieba_uid)
            continue
        result = (
            await client.add_bawu_blacklist(group_info.fid, user_info.user_id)
            if blacklist
            else await client.del_bawu_blacklist(group_info.fid, user_info.user_id)
        )
        if result:
            succeeded.append(tieba_uid)
            await add_associated_data(
                user_info,
                group_info,
                text_data=[
                    TextDataModel(
                        uploader_id=uploader_id,
                        fid=group_info.fid,
                        text=f"[自动添加]{'拉黑' if blacklist else '取消拉黑'}",
                    )
                ],
            )
        else:
            failed.append(tieba_uid)
    return succeeded, failed


async def ban_users(
    client: Client, group_info: GroupInfo, uids: Iterable[int], days: int, uploader_id: int
) -> tuple[list[int], list[int]]:
    """
    封禁用户并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        uids: 要封禁的贴吧UID列表
        days: 封禁天数
        uploader_id: 执行操作的用户ID

    Returns:
        (succeeded_uids, failed_uids)
    """
    succeeded = []
    failed = []
    for tieba_uid in uids:
        user_info = await tieba_uid2user_info_cached(client, tieba_uid)
        if user_info.user_id == 0:
            failed.append(tieba_uid)
            continue
        if await client.block(group_info.fid, user_info.portrait, day=days):
            succeeded.append(tieba_uid)
            await add_associated_data(
                user_info,
                group_info,
                text_data=[
                    TextDataModel(uploader_id=uploader_id, fid=group_info.fid, text=f"[自动添加]封禁\n封禁天数：{days}")
                ],
            )
        else:
            failed.append(tieba_uid)
    return succeeded, failed


async def unban_users(
    client: Client, group_info: GroupInfo, uids: list[int], uploader_id: int
) -> tuple[list[int], list[int]]:
    """
    解除封禁用户并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        uids: 要解除封禁的贴吧UID列表
        uploader_id: 执行操作的用户ID

    Returns: (succeeded_uids, failed_uids)
    """
    succeeded = []
    failed = []
    for tieba_uid in uids:
        user_info = await tieba_uid2user_info_cached(client, tieba_uid)
        if user_info.user_id == 0:
            failed.append(tieba_uid)
            continue
        if await client.unblock(group_info.fid, user_info.user_id):
            succeeded.append(tieba_uid)
            await add_associated_data(
                user_info,
                group_info,
                text_data=[TextDataModel(uploader_id=uploader_id, fid=group_info.fid, text="[自动添加]解除封禁")],
            )
        else:
            failed.append(tieba_uid)
    return succeeded, failed


async def thread_action(client: Client, group_info: GroupInfo, tid: int, action: str) -> tuple[bool, str]:
    """
    以吧主权限对贴子执行操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tid: 贴子ID
        action: 操作名称（加精、取消加精、置顶、取消置顶、会员置顶、取消会员置顶、推荐上首页）

    Returns:
        (success, message)
    """
    match action:
        case "加精":
            if await client.good(group_info.fid, tid):
                return True, "加精成功。"
            return False, "加精失败。"
        case "取消加精":
            if await client.ungood(group_info.fid, tid):
                return True, "已取消加精。"
            return False, "取消加精失败。"
        case "置顶":
            if await client.top(group_info.fid, tid):
                return True, "已置顶。"
            return False, "置顶失败。"
        case "取消置顶":
            if await client.untop(group_info.fid, tid):
                return True, "已取消置顶。"
            return False, "取消置顶失败。"
        case "会员置顶":
            if await client.top(group_info.fid, tid, is_vip=True):
                return True, "已会员置顶。"
            return False, "会员置顶失败。"
        case "取消会员置顶":
            if await client.untop(group_info.fid, tid, is_vip=True):
                return True, "已取消会员置顶。"
            return False, "取消会员置顶失败。"
        case "推荐上首页":
            times_left = await client.get_recom_status(group_info.fid)
            if times_left.total_recom_num - times_left.used_recom_num <= 0:
                return False, "推荐上首页失败，本月推荐配额已用完。"
            if await client.recommend(group_info.fid, tid):
                return (
                    True,
                    f"已推荐上首页，本月配额使用情况："
                    f"{times_left.total_recom_num - times_left.used_recom_num}/{times_left.total_recom_num}",
                )
            return False, "推荐上首页失败。"
        case _:
            return False, "未知命令。"


async def move_thread(client: Client, group_info: GroupInfo, tid: int, tab_names: tuple[str, ...]) -> tuple[bool, str]:
    """
    移动贴子到另一个分区。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tid: 贴子ID
        tab_names: 分区名称元组，单个名称表示目标分区，两个名称表示从第一个分区移动到第二个分区

    Returns:
        (success, message)
    """
    tab_info = await client.get_tab_map(group_info.fname)
    tab_map = tab_info.map
    for name in tab_names:
        if name not in tab_map:
            return False, "分区名称错误，请检查输入。"

    from_tab_id = 0 if len(tab_names) == 1 else tab_map.get(tab_names[0], 0)
    to_tab_id = tab_map.get(tab_names[-1], 0)

    if await client.move(group_info.fid, tid, to_tab_id=to_tab_id, from_tab_id=from_tab_id):
        return True, "移贴成功。"
    return False, "移贴失败。"


# 内存中维护的活动任务列表
# Key: tid, Value: TaskInfo (包含 attempts)
_active_force_delete_tasks: dict[str, TaskInfo] = {}
_force_delete_worker_task: asyncio.Task | None = None
_force_delete_lock = asyncio.Lock()


def get_force_delete_task_id(group_id: int, tid: int) -> str:
    return f"{group_id}_{tid}"


async def check_thread_status(group_info: GroupInfo, tid: int) -> str:
    """
    检查帖子是否已存在

    Returns:
        str: 错误信息，空字符串表示存在
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


async def add_force_delete_task(
    group_info: GroupInfo, message_id: int, bot_id: str, tid: int, operator_id: int
) -> tuple[bool, str]:
    """
    添加强制删帖任务

    Args:
        group_info: 群GroupInfo
        message_id: 触发命令的消息 ID
        bot_id: 负责执行任务的机器人 ID
        tid: 贴子ID
        operator_id: 操作者的 ID

    Returns:
        tuple[bool, str]: 返回任务是否成功添加和提示信息
    """
    async with _force_delete_lock:
        task_id = get_force_delete_task_id(group_info.group_id, tid)
        if task_id in _active_force_delete_tasks:
            return False, "该帖子已在强制删除队列中。"

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
        _active_force_delete_tasks[task_id] = info

    # 确保 Worker 运行
    _ensure_force_delete_worker_running()

    return (
        True,
        f"已启动强制删帖任务，将在后台持续尝试删除{config.force_delete_max_duration}分钟。",
    )


async def remove_force_delete_task(task_id: str) -> bool:
    """移除任务"""
    async with _force_delete_lock:
        if task_id in _active_force_delete_tasks:
            del _active_force_delete_tasks[task_id]
            await remove_force_delete_record(task_id)
            return True

    return False


async def cancel_force_delete_task(group_id: int, tid: int) -> str:
    """取消任务"""
    task_id = get_force_delete_task_id(group_id, tid)
    if await remove_force_delete_task(task_id):
        return f"已取消对帖子 tid={tid} 的强制删除任务。"
    else:
        await remove_force_delete_record(task_id)
        return f"未找到帖子 tid={tid} 的进行中任务。"


def get_force_delete_task_info(group_id: int, tid: int) -> str:
    """查询任务状态"""
    task_id = get_force_delete_task_id(group_id, tid)
    if task_id in _active_force_delete_tasks:
        attempts = _active_force_delete_tasks[task_id]["attempts"]
        expire_time_str = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(_active_force_delete_tasks[task_id]["expire_time"])
        )
        return f"进行中，已尝试删除 {attempts} 次，持续到 {expire_time_str}。"
    return "无进行中任务"


async def restore_force_delete_tasks():
    """系统启动时恢复未完成的任务"""
    global _active_force_delete_tasks
    tasks = await get_all_force_delete_records()
    now = time.time()
    count = 0

    async with _force_delete_lock:
        for task_id, info in tasks.items():
            if info["expire_time"] > now:
                _active_force_delete_tasks[task_id] = info
                count += 1
            else:
                # 清理过期任务
                await remove_force_delete_record(task_id)

    if count > 0:
        logger.info(f"[ForceDelete] 已恢复 {count} 个强制删帖任务")
        _ensure_force_delete_worker_running()


async def save_active_force_delete_tasks():
    """系统关闭时保存当前的活动任务"""
    async with _force_delete_lock:
        await save_force_delete_records(_active_force_delete_tasks)

    if _force_delete_worker_task and not _force_delete_worker_task.done():
        _force_delete_worker_task.cancel()
        try:
            await _force_delete_worker_task
        except asyncio.CancelledError:
            pass


def _ensure_force_delete_worker_running():
    global _force_delete_worker_task
    if _force_delete_worker_task is None or _force_delete_worker_task.done():
        _force_delete_worker_task = asyncio.create_task(_force_delete_worker_loop())


async def send_force_delete_feedback(task_info: TaskInfo, message: str) -> bool:
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


FORCE_DELETE_ALLOW_CODES = frozenset((*ErrorHandler.RETRIABLE_CODES, 224009, 302)) - {300000}


async def _force_delete_worker_loop():
    """单任务循环执行器"""

    logger.debug("[ForceDelete] Worker 启动")

    while _active_force_delete_tasks:
        try:
            for task_id, task_info in _active_force_delete_tasks.copy().items():
                if task_id not in _active_force_delete_tasks:
                    continue

                thread_id = task_info["thread_id"]

                now = time.time()
                sleep_until = 1.0 / max(1, config.force_delete_rps) + now
                try:
                    if now > task_info["expire_time"]:
                        logger.info(f"[ForceDelete] 任务超时: tid={thread_id}")
                        await remove_force_delete_task(task_id)
                        await send_force_delete_feedback(
                            task_info,
                            f"强制删帖任务已超时，未能成功删除帖子 tid={thread_id}。",
                        )
                        continue

                    task_info["attempts"] += 1
                    client = await ClientCache.get_bawu_client(task_info["group_id"])
                    success = await client.del_thread(task_info["fid"], thread_id)

                    if success:
                        logger.info(f"[ForceDelete] 删帖成功: tid={thread_id}")
                        await remove_force_delete_task(task_id)
                        await send_force_delete_feedback(
                            task_info,
                            f"强制删帖任务已成功删除帖子 tid={thread_id}。",
                        )
                except AiotiebaError as e:
                    if e.code not in FORCE_DELETE_ALLOW_CODES:
                        if e.code == 300000:
                            e.msg = "权限不足"
                        logger.warning(f"[ForceDelete] 删除失败 tid={thread_id}: {e}")
                        await remove_force_delete_task(task_id)
                        await send_force_delete_feedback(
                            task_info,
                            f"强制删帖任务删除帖子 tid={thread_id} 失败: {e}，已终止任务。",
                        )
                except Exception as e:
                    logger.error(f"[ForceDelete] 删除任务异常 tid={thread_id}: {e}")
                    await remove_force_delete_task(task_id)
                    await send_force_delete_feedback(
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
