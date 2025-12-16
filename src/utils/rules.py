from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import FriendRequestEvent, GroupMessageEvent

from src.db.crud import get_all_groups, get_group


async def rule_owner(bot: Bot, event: GroupMessageEvent) -> bool:
    group_member_list: list = await bot.call_api("get_group_member_list", group_id=event.group_id)
    return any(item["role"] == "owner" and item["user_id"] == event.sender.user_id for item in group_member_list)


async def is_master(user_id: int, group_id: int) -> bool:
    try:
        group_info = await get_group(group_id)
    except KeyError:
        return False
    return user_id == group_info.master


async def is_admin(user_id: int, group_id: int) -> bool:
    try:
        group_info = await get_group(group_id)
    except KeyError:
        return False
    return user_id in group_info.admins or await is_master(user_id, group_id)


async def is_moderator(user_id: int, group_id: int) -> bool:
    try:
        group_info = await get_group(group_id)
    except KeyError:
        return False
    return user_id in group_info.moderators or await is_admin(user_id, group_id)


async def rule_reply(event: GroupMessageEvent) -> bool:
    return bool(event.reply)


async def rule_master(event: GroupMessageEvent) -> bool:
    if not event.sender.user_id:
        return False
    return await is_master(event.sender.user_id, event.group_id)


async def rule_admin(event: GroupMessageEvent) -> bool:
    if not event.sender.user_id:
        return False
    return await is_admin(event.sender.user_id, event.group_id)


async def rule_moderator(event: GroupMessageEvent) -> bool:
    if not event.sender.user_id:
        return False
    return await is_moderator(event.sender.user_id, event.group_id)


async def rule_signed(event: GroupMessageEvent) -> bool:
    try:
        _ = await get_group(event.group_id)
        return True
    except KeyError:
        return False


async def rule_member(event: FriendRequestEvent) -> bool:
    user_id = event.user_id
    group_infos = await get_all_groups()
    for group_info in group_infos:
        if user_id in group_info.admins or user_id in group_info.moderators or user_id == group_info.master:
            return True
    return False
