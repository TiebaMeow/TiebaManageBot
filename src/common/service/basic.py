from __future__ import annotations

import asyncio
import operator
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

import httpx
import nonebot

from src.common.cache import get_tieba_name, get_user_posts_cached, get_user_threads_cached
from src.db import TextDataModel
from src.db.crud import add_associated_data
from src.utils import text_to_image

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from aiotieba.api.get_user_contents._classdef import UserPostss, UserThreads
    from tiebameow.client import Client

    from src.db import GroupInfo

config = nonebot.get_driver().config
enable_addons = getattr(config, "enable_addons", False)


async def generate_checkout_msg(
    client: Client, uid: int | str, checkout_tieba_config: str | None = None
) -> tuple[str, bytes]:
    """
    生成查成分消息内容。

    Args:
        client: 已初始化的 Client 实例
        uid: 要查询的用户的 user_id 或 portrait
        checkout_tieba_config: 通过第三方接口查询的贴吧名称配置

    Returns:
        (base_content, image_content)
    """
    user_info = await client.get_user_info(uid)
    nick_name_old = await client.get_nickname_old(user_info.user_id)

    user_tieba_obj = await client.get_follow_forums(user_info.user_id)
    if user_tieba_obj.objs:
        user_tieba = [
            {"tieba_name": forum.fname, "experience": forum.exp, "level": forum.level} for forum in user_tieba_obj.objs
        ]
    else:
        checkout_tieba = checkout_tieba_config
        if not checkout_tieba:
            checkout_tieba = (
                "原神,原神内鬼,崩坏三,崩坏3rd,崩坏星穹铁道,星穹铁道内鬼,mihoyo,新mihoyo,尘白禁区,ml游戏,有男不玩ml,"
                "千年之旅,有男偷玩,二游笑话,dinner笑话,三度笑话,明日方舟,明日方舟内鬼,明日方舟dl,明日方舟pl,淋日方舟,"
                "血狼破军,快乐雪花,半壁江山雪之下,碧蓝航线,碧蓝航线2,异色格,赤色中轴,少女前线,少女前线2,少女前线r,"
                "蔚蓝档案,碧蓝档案,碧蓝档案吐槽,鸣潮,鸣潮内鬼,旧鸣潮内鬼,新鸣潮内鬼,鸣潮爆料,北落野,灵魂潮汐,无期迷途"
            )
        try:
            async with httpx.AsyncClient(verify=False, timeout=5) as session:
                resp = await session.get(
                    f"https://tb.anova.me/getLevel?fname={quote_plus(checkout_tieba)}&uid={user_info.tieba_uid}"
                )
                resp.raise_for_status()
                resp_json = resp.json()
            user_tieba = [
                {
                    "tieba_name": item["fname"],
                    "experience": item["exp"],
                    "level": item["level"],
                }
                for item in resp_json.get("result", [])
            ]
            user_tieba = sorted(user_tieba, key=operator.itemgetter("experience"), reverse=True)
        except Exception:
            user_tieba = []

    user_posts_count = {}

    tasks = [get_user_threads_cached(client, user_info.user_id, page) for page in range(1, 51)]
    results_t: Sequence[UserThreads] = await asyncio.gather(*tasks, return_exceptions=False)
    for result in results_t:
        if result and result.objs:
            for thread in result.objs:
                if thread.fid in user_posts_count:
                    user_posts_count[thread.fid] += 1
                else:
                    user_posts_count[thread.fid] = 1

    tasks = [get_user_posts_cached(client, user_info.user_id, page, rn=50) for page in range(1, 51)]
    results_p: Sequence[UserPostss] = await asyncio.gather(*tasks, return_exceptions=False)
    for result in results_p:
        if result and result.objs:
            for post in result.objs:
                if post.fid in user_posts_count:
                    user_posts_count[post.fid] += 1
                else:
                    user_posts_count[post.fid] = 1

    if not user_posts_count and enable_addons:
        from src.addons.interface import crud

        user_stats = await crud.user_posts.get_user_stats(user_info.user_id)
        for stat in user_stats:
            if stat.thread_count + stat.post_count + stat.comment_count > 0:
                user_posts_count[stat.fid] = stat.thread_count + stat.post_count + stat.comment_count

    sorted_posts_count = sorted(user_posts_count.items(), key=operator.itemgetter(1), reverse=True)
    sorted_posts_count = sorted_posts_count[:30]

    final_posts_count = [
        {"tieba_name": str(await get_tieba_name(item[0])), "count": item[1]} for item in sorted_posts_count
    ]

    user_posts_count_str = "\n".join([f"  - {item['tieba_name']}：{item['count']}" for item in final_posts_count])
    user_tieba_str = "\n".join([
        f"  - {forum['tieba_name']}：{forum['experience']}经验值，等级{forum['level']}" for forum in user_tieba
    ])
    user_info_str = (
        f"昵称：{user_info.nick_name_new}\n"
        f"旧版昵称：{nick_name_old}\n"
        f"用户名：{user_info.user_name}\n"
        f"贴吧ID：{user_info.tieba_uid}\n"
        f"user_id：{user_info.user_id}\n"
        f"portrait：{user_info.portrait}\n"
        f"吧龄：{user_info.age}年"
    )

    base_content = f"基本信息：\n{user_info_str}"
    image_content = await text_to_image(
        f"用户 {user_info.show_name}({user_info.tieba_uid}) 关注的贴吧：\n{user_tieba_str}\n\n"
        f"近期发贴的吧：\n{user_posts_count_str}"
    )

    return base_content, image_content


async def delete_thread(client: Client, group_info: GroupInfo, tid: int, uploader_id: int) -> bool:
    """
    删贴并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tid: 贴子ID
        uploader_id: 执行删除操作的用户ID

    Returns:
        是否删除成功
    """
    context = await client.get_posts(tid, rn=1)
    if await client.del_thread(group_info.fid, tid):
        user_info = await client.get_user_info(context.thread.author_id)
        await add_associated_data(
            user_info,
            group_info,
            text_data=[
                TextDataModel(
                    uploader_id=uploader_id,
                    fid=group_info.fid,
                    text=f"[自动添加]删贴\n标题：{context.thread.title}\n内容：{context.thread.text}",
                )
            ],
        )
        return True
    return False


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
        if await delete_thread(client, group_info, tid, uploader_id):
            succeeded.append(tid)
        else:
            failed.append(tid)
    return succeeded, failed


async def delete_post(client: Client, group_info: GroupInfo, tid: int, pid: int, uploader_id: int) -> bool:
    """
    删回复并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tid: 贴子ID
        pid: 回复ID
        uploader_id: 执行删除操作的用户ID

    Returns:
        是否删除成功
    """
    context = await client.get_comments(tid, pid)
    if await client.del_post(group_info.fid, tid, pid):
        user_info = await client.get_user_info(context.post.author_id)
        await add_associated_data(
            user_info,
            group_info,
            text_data=[
                TextDataModel(
                    uploader_id=uploader_id,
                    fid=group_info.fid,
                    text=f"[自动添加]删回复\n原贴标题：{context.thread.title}\n回复内容：{context.post.text}",
                )
            ],
        )
        return True
    return False


async def delete_posts(
    client: Client, group_info: GroupInfo, tid: int, pids: Iterable[int], uploader_id: int
) -> tuple[list[int], list[str], str]:
    """
    删回复并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        tid: 贴子ID
        pids: 要删除的回复ID列表
        uploader_id: 执行删除操作的用户ID

    Returns:
        (succeeded_pids, failed_pids, error_message)
    """
    succeeded = []
    failed = []

    for pid in pids:
        if await delete_post(client, group_info, tid, pid, uploader_id):
            succeeded.append(pid)
        else:
            failed.append(pid)
    return succeeded, failed, ""


async def ban_user(client: Client, group_info: GroupInfo, uid: int | str, days: int, uploader_id: int) -> bool:
    """
    封禁单个用户并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        uid: 要封禁的user_id或portrait
        days: 封禁天数
        uploader_id: 执行操作的用户ID

    Returns:
        是否封禁成功
    """
    user_info = await client.get_user_info(uid)
    if await client.block(group_info.fid, user_info.portrait, day=days):
        await add_associated_data(
            user_info,
            group_info,
            text_data=[
                TextDataModel(uploader_id=uploader_id, fid=group_info.fid, text=f"[自动添加]封禁\n封禁天数：{days}")
            ],
        )
        return True
    return False


async def ban_users(
    client: Client, group_info: GroupInfo, uids: Sequence[int | str], days: int, uploader_id: int
) -> tuple[list[int], list[int]]:
    """
    封禁用户并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        uids: 要封禁的user_id或portrait列表
        days: 封禁天数
        uploader_id: 执行操作的用户ID

    Returns:
        (succeeded_uids, failed_uids)
    """
    succeeded = []
    failed = []
    for uid in uids:
        if await ban_user(client, group_info, uid, days, uploader_id):
            succeeded.append(uid)
        else:
            failed.append(uid)
    return succeeded, failed


async def unban_user(client: Client, group_info: GroupInfo, uid: int | str, uploader_id: int) -> bool:
    """
    解除封禁单个用户并记录操作。

    Args:
        client: 已初始化的 Client 实例
        group_info: GroupInfo
        uid: 要解除封禁的user_id或portrait
        uploader_id: 执行操作的用户ID

    Returns:
        是否解除封禁成功
    """
    user_info = await client.get_user_info(uid)
    if await client.unblock(group_info.fid, user_info.user_id):
        await add_associated_data(
            user_info,
            group_info,
            text_data=[TextDataModel(uploader_id=uploader_id, fid=group_info.fid, text="[自动添加]解除封禁")],
        )
        return True
    return False


async def unban_users(
    client: Client, group_info: GroupInfo, uids: Sequence[int | str], uploader_id: int
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
    for uid in uids:
        if await unban_user(client, group_info, uid, uploader_id):
            succeeded.append(uid)
        else:
            failed.append(uid)
    return succeeded, failed
