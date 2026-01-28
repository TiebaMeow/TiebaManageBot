from __future__ import annotations

from nonebot import on_message, on_notice
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, NoticeEvent, permission
from nonebot.rule import Rule
from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO
from tiebameow.serializer import deserialize

from src.common.cache import ClientCache, get_review_notify_payload
from src.common.service import (
    ban_user,
    delete_post,
    delete_thread,
    generate_checkout_msg,
)
from src.db.crud import get_group
from src.utils import rule_moderator, rule_reaction, rule_reply, rule_signed

DELETE_KEYWORDS = {"删除", "删贴", "删帖"}
BAN_KEYWORDS = {"封禁"}
CHECKOUT_KEYWORDS = {"查成分", "成分"}
ALL_KEYWORDS = DELETE_KEYWORDS | BAN_KEYWORDS | CHECKOUT_KEYWORDS


async def rule_review_notify_keyword(event: GroupMessageEvent) -> bool:
    text = event.get_plaintext().strip()
    return text in ALL_KEYWORDS


async def rule_review_notify_target(event: GroupMessageEvent) -> bool:
    if not event.reply:
        return False
    payload = await get_review_notify_payload(event.reply.real_id)
    return bool(payload)


review_notify_cmd = on_message(
    rule=Rule(rule_reply, rule_signed, rule_moderator, rule_review_notify_keyword, rule_review_notify_target),
    permission=permission.GROUP,
    priority=9,
    block=True,
)


@review_notify_cmd.handle()
async def handle_review_notify_reply(event: GroupMessageEvent):
    assert event.reply is not None
    text = event.get_plaintext().strip()
    payload = await get_review_notify_payload(event.reply.real_id)
    if not payload:
        return

    if payload.get("group_id") != event.group_id:
        return

    group_info = await get_group(event.group_id)
    if payload.get("fid") != group_info.fid:
        return

    object_type = payload.get("object_type")
    object_data = payload.get("object_data")
    if object_type not in ("thread", "post", "comment"):
        return
    if not isinstance(object_data, dict):
        return

    try:
        object_dto = deserialize(object_type, object_data)
    except Exception:
        return

    if text in DELETE_KEYWORDS:
        client = await ClientCache.get_bawu_client(event.group_id)
        if isinstance(object_dto, ThreadDTO):
            result, err = await delete_thread(client, group_info, object_dto.tid, event.user_id)
        elif isinstance(object_dto, PostDTO):
            result, err = await delete_post(client, group_info, object_dto.tid, object_dto.pid, event.user_id)
        elif isinstance(object_dto, CommentDTO):
            result, err = await delete_post(client, group_info, object_dto.tid, object_dto.cid, event.user_id)
        else:
            result, err = False, ""
        await review_notify_cmd.finish("删贴成功。" if result else f"删贴失败：{err}。")

    if text in BAN_KEYWORDS:
        client = await ClientCache.get_bawu_client(event.group_id)
        result, err = await ban_user(client, group_info, object_dto.author_id, days=1, uploader_id=event.user_id)
        await review_notify_cmd.finish("封禁成功（1天）。" if result else f"封禁失败：{err}。")

    if text in CHECKOUT_KEYWORDS:
        client = await ClientCache.get_bawu_client(event.group_id)
        checkout_msg, checkout_img = await generate_checkout_msg(client, object_dto.author_id)
        await review_notify_cmd.finish(message=MessageSegment.text(checkout_msg) + MessageSegment.image(checkout_img))


review_notify_reaction = on_notice(
    rule=Rule(rule_signed, rule_moderator, rule_reaction),
    permission=permission.GROUP,
    priority=9,
    block=True,
)


@review_notify_reaction.handle()
async def handle_review_notify_reaction(event: NoticeEvent):
    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)
    message_id = getattr(event, "message_id", None)
    likes = getattr(event, "likes", None)

    if any(v is None for v in (group_id, user_id, message_id, likes)):
        return
    assert group_id is not None
    assert user_id is not None
    assert message_id is not None
    assert likes is not None

    emoji_id = likes[0]["emoji_id"] if isinstance(likes, list) and len(likes) > 0 else None
    if emoji_id not in (10068, 128074):
        return

    payload = await get_review_notify_payload(message_id)
    if not payload:
        return

    if payload.get("group_id") != group_id:
        return

    object_type = payload.get("object_type")
    object_data = payload.get("object_data")
    if object_type not in ("thread", "post", "comment"):
        return
    if not isinstance(object_data, dict):
        return

    try:
        object_dto = deserialize(object_type, object_data)
    except Exception:
        return

    client = await ClientCache.get_bawu_client(group_id)
    if emoji_id == 10068:
        checkout_msg, checkout_img = await generate_checkout_msg(client, object_dto.author_id)
        await review_notify_reaction.finish(
            message=MessageSegment.text(checkout_msg) + MessageSegment.image(checkout_img)
        )
    elif emoji_id == 128074:
        if isinstance(object_dto, ThreadDTO):
            result, err = await delete_thread(client, await get_group(group_id), object_dto.tid, user_id)
        elif isinstance(object_dto, PostDTO):
            result, err = await delete_post(client, await get_group(group_id), object_dto.tid, object_dto.pid, user_id)
        elif isinstance(object_dto, CommentDTO):
            result, err = await delete_post(client, await get_group(group_id), object_dto.tid, object_dto.cid, user_id)
        else:
            result, err = False, ""
        await review_notify_reaction.finish("删贴成功。" if result else f"删贴失败：{err}。")
