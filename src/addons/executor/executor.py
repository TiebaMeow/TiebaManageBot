from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot import get_bot
from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO
from tiebameow.parser.rule_parser import RuleEngineParser
from tiebameow.serializer import deserialize

from src.common.cache import ClientCache, set_review_notify_payload
from src.common.service import ban_user, delete_post_no_record, delete_thread_no_record
from src.db.crud import get_group_by_fid, get_rule

from .template import AIReviewTemplate, DefaultTemplate, ReviewResultPayload

if TYPE_CHECKING:
    from tiebameow.schemas.rules import ReviewRule

    from src.db.models import GroupInfo

    from .template import ReviewResultPayload


class Executor:
    def __init__(self):
        self.rule_parser = RuleEngineParser()

    async def execute(self, payload: ReviewResultPayload) -> None:
        """执行给定的 ReviewResultPayload。

        Args:
            payload: 要执行的 ReviewResultPayload 实例。
        """
        group_info = await get_group_by_fid(payload.fid)
        object_dto = deserialize(payload.object_type, payload.object_data)

        deleted = False
        banned = False
        notified = False
        for rule_id in payload.matched_rule_ids:
            rule = await get_rule(rule_id)
            if not rule:
                continue

            rule = rule.to_rule_data()
            actions = rule.actions
            _deleted = False
            _banned = False
            if actions.delete.enabled and not deleted:
                _deleted = await self._handle_delete(group_info, object_dto)
                if _deleted:
                    deleted = True
            if actions.ban.enabled and not banned:
                days = rule.actions.ban.days
                _banned = await self._handle_ban(group_info, object_dto, days=days)
                if _banned:
                    banned = True
            if actions.notify.enabled:
                if notified and not (_deleted or _banned):
                    continue
                await self._handle_notify(
                    group_info, object_dto, rule, payload.function_call_results, _deleted, _banned, payload
                )
                notified = True

    async def _handle_delete(
        self,
        group_info: GroupInfo,
        object_dto: ThreadDTO | PostDTO | CommentDTO,
    ) -> bool:
        """处理删除操作。

        Args:
            object_data: 触发删除的对象数据。
            action: 删除操作的 Action 实例。
        """
        client = await ClientCache.get_bawu_client(group_info.group_id)
        if isinstance(object_dto, ThreadDTO):
            return await delete_thread_no_record(client, group_info.fid, object_dto.tid)
        elif isinstance(object_dto, PostDTO):
            return await delete_post_no_record(client, group_info.fid, object_dto.tid, object_dto.pid)
        elif isinstance(object_dto, CommentDTO):
            return await delete_post_no_record(client, group_info.fid, object_dto.tid, object_dto.cid)

    async def _handle_ban(
        self,
        group_info: GroupInfo,
        object_dto: ThreadDTO | PostDTO | CommentDTO,
        days: int = 1,
    ) -> bool:
        """处理封禁操作。

        Args:
            object_data: 触发封禁的对象数据。
            action: 封禁操作的 Action 实例。
        """
        client = await ClientCache.get_bawu_client(group_info.group_id)
        return await ban_user(client, group_info, object_dto.author_id, days=days, uploader_id=0)

    async def _handle_notify(
        self,
        group_info: GroupInfo,
        object_dto: ThreadDTO | PostDTO | CommentDTO,
        rule: ReviewRule,
        function_call_results: dict[str, Any],
        deleted: bool,
        banned: bool,
        payload: ReviewResultPayload,
    ) -> None:
        """处理通知操作。

        Args:
            object_data: 触发通知的对象数据。
            action: 通知操作的 Action 实例。
        """
        bot = get_bot()
        notify_config = rule.actions.notify
        template_name = notify_config.template or "default"
        if template_name == "ai_review":
            template = AIReviewTemplate(
                rule=rule, dto=object_dto, function_call_results=function_call_results, deleted=deleted, banned=banned
            )
        else:
            template = DefaultTemplate(
                rule=rule, dto=object_dto, function_call_results=function_call_results, deleted=deleted, banned=banned
            )
        messages = await template.message()
        resp = await bot.call_api("send_group_msg", group_id=group_info.group_id, message=messages)
        message_id = resp.get("message_id") if isinstance(resp, dict) else None
        if message_id:
            await set_review_notify_payload(
                int(message_id),
                {
                    "group_id": group_info.group_id,
                    "fid": payload.fid,
                    "object_type": payload.object_type,
                    "object_data": payload.object_data,
                },
            )
