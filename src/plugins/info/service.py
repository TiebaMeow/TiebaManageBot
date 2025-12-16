from __future__ import annotations

import asyncio
import operator
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

import httpx

from src.common import Client, get_user_posts_cached, get_user_threads_cached
from src.common.cache import get_tieba_name
from src.db.crud import set_associated_data
from src.utils import (
    render_post_card,
    render_thread_card,
    text_to_image,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiotieba.api.get_user_contents._classdef import UserPostss, UserThreads
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid

    from src.db import GroupInfo, ImgDataModel, TextDataModel


async def generate_checkout_msg(client: Client, tieba_id: int, checkout_tieba_config: str) -> tuple[str, bytes]:
    """
    生成查成分消息内容。

    Args:
        client: 已初始化的 Client 实例
        tieba_id: 贴吧UID
        checkout_tieba_config: 通过第三方接口查询的贴吧名称配置

    Returns:
        (base_content, image_content)
    """
    user_info = await client.tieba_uid2user_info(tieba_id)
    nick_name_old = await client.get_nickname_old(user_info.user_id)

    user_tieba_obj = await client.get_follow_forums(user_info.user_id)
    if user_tieba_obj.objs:
        user_tieba = [
            {"tieba_name": forum.fname, "experience": forum.exp, "level": forum.level} for forum in user_tieba_obj.objs
        ]
    else:
        try:
            async with httpx.AsyncClient(verify=False, timeout=5) as session:
                resp = await session.get(
                    f"https://tb.anova.me/getLevel?fname={quote_plus(checkout_tieba_config)}&uid={tieba_id}"
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
        f"{user_info.tieba_uid}关注的贴吧：\n{user_tieba_str}\n\n近期发贴的吧：\n{user_posts_count_str}"
    )

    return base_content, image_content


async def delete_associated_data(
    user_info: UserInfo_TUid,
    group_info: GroupInfo,
    ids: list[int],
    uploader_id: int,
    text_datas: list[tuple[int, TextDataModel]],
    img_datas: list[tuple[int, ImgDataModel]],
) -> bool:
    """
    删除关联数据。

    Args:
        user_info: 用户信息
        group_info: 贴吧信息
        ids: 需要删除的关联数据ID列表
        uploader_id: 操作者的用户ID
        text_datas: 带索引的当前用户的文本数据列表
        img_datas: 带索引的当前用户的图片数据列表

    Returns:
        是否成功删除关联数据
    """
    for delete_id in ids:
        text = next((text_data for index, text_data in text_datas if index == delete_id), None)
        if text:
            if text.uploader_id != uploader_id and text.uploader_id != group_info.master:
                continue
            text_datas = list(filter(lambda x: x[0] != delete_id, text_datas))
            continue
        img = next((img_data for index, img_data in img_datas if index == delete_id), None)
        if img:
            if img.uploader_id != uploader_id and img.uploader_id != group_info.master:
                continue
            img_datas = list(filter(lambda x: x[0] != delete_id, img_datas))
            continue

    text_datas_final = [text_data for _, text_data in text_datas]
    img_datas_final = [img_data for _, img_data in img_datas]
    return await set_associated_data(user_info.user_id, group_info.fid, text_datas_final, img_datas_final)


async def get_last_replier(client: Client, fname: str, tid: int) -> tuple[dict | None, str]:
    """
    获取帖子最后回复者信息。

    Args:
        client: 已初始化的 Client 实例
        fname: 贴吧名称
        tid: 帖子ID

    Returns:
        (user_info_dict, message)
    """
    threads = await client.get_last_replyers(fname, rn=50)
    for thread in threads.objs:
        if thread.tid == tid:
            user_id = thread.last_replyer.user_id
            user_info = await client.get_user_info(user_id)
            return {
                "nick_name": user_info.nick_name,
                "tieba_uid": user_info.tieba_uid,
            }, f"已查询到该贴最后回复者为 {user_info.nick_name}({user_info.tieba_uid})。"
    return None, "未查询到该贴子。"


async def get_ban_logs(client: Client, fid: int, tieba_id: int) -> tuple[str, list[str]]:
    """
    获取封禁记录。
    Args:
        client: 已初始化的 Client 实例
        fid: 本吧fid
        tieba_id: 贴吧UID

    Returns:
        (message, logs)
    """
    user_info = await client.tieba_uid2user_info(tieba_id)
    nick_name_old = await client.get_nickname_old(user_info.user_id)
    search_value = user_info.user_name or nick_name_old
    if not search_value:
        return "无法查询到该用户的用户名或旧版昵称。", []

    ban_info = await client.get_bawu_userlogs(fid, search_value=search_value)
    if ban_info.err:
        return f"查询用户 {user_info.nick_name}({tieba_id}) 封禁记录时发生错误。", []
    if not ban_info.objs:
        return f"查询完毕，用户 {user_info.nick_name}({tieba_id}) 在本吧无封禁记录。", []

    user_logs = []
    for info in ban_info.objs[:10]:
        ban_str = f"{info.op_time.strftime('%Y-%m-%d %H:%M')} - {info.op_type}"
        if info.op_type == "封禁":
            ban_str += f" - {info.op_duration}天"
        ban_str += f" - 操作人：{info.op_user_name}"
        user_logs.append(ban_str)

    return "", user_logs


async def get_delete_logs(client: Client, fid: int, tieba_id: int) -> tuple[str, list[str]]:
    """
    获取删贴记录。
    Args:
        client: 已初始化的 Client 实例
        fid: 本吧fid
        tieba_id: 贴吧UID

    Returns:
        (message, logs)
    """
    user_info = await client.tieba_uid2user_info(tieba_id)
    nick_name_old = await client.get_nickname_old(user_info.user_id)
    search_value = user_info.user_name or nick_name_old
    if not search_value:
        return "无法查询到该用户的用户名或旧版昵称。", []

    delete_info = await client.get_bawu_postlogs(fid, search_value=search_value)
    if delete_info.err:
        return f"查询用户 {user_info.nick_name}({tieba_id}) 删贴记录时发生错误。", []
    if not delete_info.objs:
        return f"查询完毕，用户 {user_info.nick_name}({tieba_id}) 在本吧无删贴记录。", []

    user_logs = []
    last_info = list(filter(lambda x: x.op_time > datetime.now() - timedelta(days=30), delete_info.objs))
    if not last_info:
        return f"查询完毕，用户 {user_info.nick_name}({tieba_id}) 在本吧无30天内删贴记录。", []

    last_info = last_info[:10]
    for info in last_info:
        delete_str = f"{info.op_time.strftime('%Y-%m-%d %H:%M')} - {info.op_type}"
        text = info.text or info.title
        if len(text) > 20:
            text = text[:20] + "……"
        delete_str += f" - {text}"
        delete_str += f" - 操作人：{info.op_user_name}"
        user_logs.append(delete_str)

    return "", user_logs


async def get_thread_preview(client: Client, tid: int, pid: int = 0) -> bytes | None:
    """
    渲染贴子预览图片。

    Args:
        client: 已初始化的 Client 实例
        tid: 主题贴tid
        pid: 回复pid，默认为0表示预览主题贴

    Returns:
        预览图片 bytes，获取失败时返回 None
    """
    if pid:
        thread_info = await client.get_posts(tid)
        post_info = await client.get_comments(tid, pid)
        if thread_info.err or post_info.err:
            return None
        return await render_post_card(
            thread_info.thread,
            post_info.post,
            post_info.objs[:3],
        )
    else:
        thread_info = await client.get_posts(tid, with_comments=True)
        if thread_info.err:
            return None
        thread = thread_info.thread
        posts = thread_info.objs

        # 处理包含1楼的情况
        if len(posts) > 0 and posts[0].floor == 1:
            del posts[0]
            if thread.reply_num > 0:
                thread.reply_num -= 1
        return await render_thread_card(thread, posts[:3])
