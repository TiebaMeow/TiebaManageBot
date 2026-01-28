from __future__ import annotations

import abc
import base64
import json
from typing import Any, Literal

from pydantic import BaseModel
from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO  # noqa: TC002
from tiebameow.schemas.rules import ReviewRule  # noqa: TC002

from src.common.cache import ClientCache
from src.utils.renderer import render_content


class ReviewResultPayload(BaseModel):
    fid: int
    matched_rule_ids: list[int]
    object_type: Literal["thread", "post", "comment"]
    object_data: dict[str, Any]
    function_call_results: dict[str, Any]
    timestamp: float


class Template(abc.ABC):
    def __init__(
        self,
        rule: ReviewRule,
        dto: ThreadDTO | PostDTO | CommentDTO,
        function_call_results: dict[str, Any],
        deleted: tuple[bool, str],
        banned: tuple[bool, str],
    ):
        self.rule = rule
        self.dto = dto
        self.deleted = deleted
        self.banned = banned
        self.function_call_results = function_call_results

    @abc.abstractmethod
    async def message(self) -> list[dict[str, str]]:
        pass


class DefaultTemplate(Template):
    def __init__(
        self,
        rule: ReviewRule,
        dto: ThreadDTO | PostDTO | CommentDTO,
        function_call_results: dict[str, Any],
        deleted: tuple[bool, str],
        banned: tuple[bool, str],
    ):
        super().__init__(rule, dto, function_call_results, deleted, banned)

    async def message(self) -> list[dict[str, str]]:
        client = await ClientCache.get_client()
        base_message_str = f"⚠️规则触发通知\n规则名称：{self.rule.name}\n"
        content_type = "主题贴"
        if isinstance(self.dto, PostDTO):
            content_type = "回复"
        elif isinstance(self.dto, CommentDTO):
            content_type = "楼中楼"
            if self.dto.floor == 0:
                try:
                    comments = await client.get_comments(self.dto.tid, self.dto.pid, is_comment=True)
                    for comment in comments:
                        if comment.pid == self.dto.cid:
                            self.dto.floor = comment.floor
                            break
                except Exception:
                    pass
        base_message_str += f"触发对象类型：{content_type}"
        base_message = {"type": "text", "data": {"text": base_message_str}}

        content_img = await render_content(self.dto)
        img_b64 = base64.b64encode(content_img).decode()
        image_message = {"type": "image", "data": {"file": f"base64://{img_b64}"}}

        suffix_message_str = ""
        if self.rule.actions.delete.enabled:
            delete_status = "删除 成功" if self.deleted[0] else f"删除 失败: {self.deleted[1]}"
            suffix_message_str += f"执行操作：{delete_status}\n"
        if self.rule.actions.ban.enabled:
            ban_status = (
                f"封禁{self.rule.actions.ban.days}天 成功"
                if self.banned[0]
                else f"封禁{self.rule.actions.ban.days}天 失败: {self.banned[1]}"
            )
            suffix_message_str += f"执行操作：{ban_status}\n"

        user_info = await client.get_user_info(self.dto.author_id)
        suffix_message_str += f"用户：{user_info.show_name} ({user_info.tieba_uid})\n"
        suffix_message_str += f"https://tieba.baidu.com/p/{self.dto.tid}"
        if isinstance(self.dto, PostDTO):
            suffix_message_str += f"?pid={self.dto.pid}#{self.dto.pid}"
        elif isinstance(self.dto, CommentDTO):
            suffix_message_str += f"?pid={self.dto.pid}#{self.dto.cid}"

        suffix_message = {
            "type": "text",
            "data": {"text": suffix_message_str},
        }

        return [base_message, image_message, suffix_message]


class AIReviewTemplate(Template):
    def __init__(
        self,
        rule: ReviewRule,
        dto: ThreadDTO | PostDTO | CommentDTO,
        function_call_results: dict[str, Any],
        deleted: tuple[bool, str],
        banned: tuple[bool, str],
    ):
        super().__init__(rule, dto, function_call_results, deleted, banned)

    async def message(self) -> list[dict[str, str]]:
        client = await ClientCache.get_client()
        base_message_str = f"⚠️AI审查触发通知\n规则名称：{self.rule.name}\n"
        content_type = "主题贴"
        if isinstance(self.dto, PostDTO):
            content_type = "回复"
        elif isinstance(self.dto, CommentDTO):
            content_type = "楼中楼"
            if self.dto.floor == 0:
                try:
                    comments = await client.get_comments(self.dto.tid, self.dto.pid, is_comment=True)
                    for comment in comments:
                        if comment.pid == self.dto.cid:
                            self.dto.floor = comment.floor
                            break
                except Exception:
                    pass
        base_message_str += f"触发对象类型：{content_type}"
        base_message = {"type": "text", "data": {"text": base_message_str}}

        content_img = await render_content(self.dto)
        img_b64 = base64.b64encode(content_img).decode()
        image_message = {"type": "image", "data": {"file": f"base64://{img_b64}"}}

        suffix_message_str = ""
        ai_result = self.function_call_results.get("ai_review", {})
        if isinstance(ai_result, str):
            try:
                ai_result = json.loads(ai_result)
            except Exception:
                ai_result = {}
        if ai_result and ai_result.get("violation", False):
            category = ai_result.get("category", "")
            reason = ai_result.get("reason", "")
            confidence = ai_result.get("confidence", 0)
            suffix_message_str += f"AI审查输出：[{category}]{reason}\n置信度：{confidence}\n"
        if self.rule.actions.delete.enabled:
            delete_status = "删除 成功" if self.deleted[0] else f"删除 失败: {self.deleted[1]}"
            suffix_message_str += f"执行操作：{delete_status}\n"
        if self.rule.actions.ban.enabled:
            ban_status = (
                f"封禁{self.rule.actions.ban.days}天 成功"
                if self.banned[0]
                else f"封禁{self.rule.actions.ban.days}天 失败: {self.banned[1]}"
            )
            suffix_message_str += f"执行操作：{ban_status}\n"

        user_info = await client.get_user_info(self.dto.author_id)
        suffix_message_str += f"用户：{user_info.show_name} ({user_info.tieba_uid})\n"
        suffix_message_str += f"链接：https://tieba.baidu.com/p/{self.dto.tid}"
        if isinstance(self.dto, PostDTO):
            suffix_message_str += f"?pid={self.dto.pid}#{self.dto.pid}"
        elif isinstance(self.dto, CommentDTO):
            suffix_message_str += f"?pid={self.dto.pid}#{self.dto.cid}"

        suffix_message = {
            "type": "text",
            "data": {"text": suffix_message_str},
        }

        return [base_message, image_message, suffix_message]
