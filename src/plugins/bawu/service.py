from __future__ import annotations

from typing import TYPE_CHECKING

from aiotieba import PostSortType

from src.common import tieba_uid2user_info_cached
from src.db import GroupInfo, TextDataModel
from src.db.crud import add_associated_data

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tiebameow.client import Client


async def delete_threads(
    client: Client, group_info: GroupInfo, tids: Iterable[int], uploader_id: int
) -> tuple[list[int], list[int]]:
    """
    删贴并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tids: 要删除的贴子ID列表
        uploader_id: 执行删除操作的用户ID

    Returns:
        (succeeded_tids, failed_tids)
    """
    succeeded = []
    failed = []
    for tid in tids:
        posts = await client.get_posts(tid)
        user_info = await client.get_user_info(posts.thread.author_id)
        if await client.del_thread(group_info.fid, tid):
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
    return succeeded, failed


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
