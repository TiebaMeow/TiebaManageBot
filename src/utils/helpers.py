from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.common.cache import ClientCache

if TYPE_CHECKING:
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid
    from nonebot.adapters import Bot
    from tiebameow.client import Client


async def get_user_name(bot: Bot, group_id: int, user_id: int) -> str | None:
    try:
        username = (await bot.call_api("get_group_member_info", group_id=group_id, user_id=user_id)).get("card_new", "")
        if not username:
            username = (await bot.call_api("get_stranger_info", user_id=user_id)).get("nickname", "")
    except Exception:
        return None
    else:
        return username


async def get_tieba_user_info(tieba_uid: int, client: Client) -> UserInfo_TUid:
    user_info = await client.tieba_uid2user_info(tieba_uid)
    return user_info


async def handle_tieba_uid(tieba_uid_str: str, client: Client | None = None) -> int:
    if tieba_uid_str.startswith("tb."):
        if client is None:
            client = await ClientCache.get_client()
            user_info = await client.get_user_info(tieba_uid_str)
        else:
            user_info = await client.get_user_info(tieba_uid_str)
        if user_info:
            return user_info.tieba_uid
        else:
            return 0
    if tieba_uid_str.isdigit():
        return int(tieba_uid_str)
    match = re.search(r"#(\d+)#", tieba_uid_str)
    if match:
        return int(match.group(1))
    else:
        return 0


async def handle_tieba_uids(tieba_uid_strs: tuple[str, ...]) -> list[int]:
    client = await ClientCache.get_client()
    results = [await handle_tieba_uid(uid_str, client) for uid_str in tieba_uid_strs]
    return results


def handle_thread_url(thread_url: str) -> int:
    if thread_url.isdigit():
        return int(thread_url)
    match = re.search(r"tieba.baidu.com/p/(\d+)", thread_url)
    if match:
        return int(match.group(1))
    else:
        return 0


def handle_thread_urls(thread_urls: tuple[str, ...]) -> list[int]:
    return [handle_thread_url(url) for url in thread_urls][:30]


def handle_post_url(post_url: str) -> tuple[int, int]:
    match = re.search(r"tieba.baidu.com/p/(\d+)\?.*post_id=(\d+)", post_url)
    if match:
        return int(match.group(1)), int(match.group(2))
    else:
        return 0, 0


def handle_post_urls(post_urls: tuple[str, ...]) -> list[tuple[int, int]]:
    return [handle_post_url(url) for url in post_urls][:30]
