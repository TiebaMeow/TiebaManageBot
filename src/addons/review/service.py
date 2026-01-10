from __future__ import annotations

from typing import TYPE_CHECKING

from tiebameow.parser.rule_parser import RuleEngineParser
from tiebameow.schemas.rules import Action, ActionType, Condition, FieldType, OperatorType, ReviewRule, TargetType

from src.db.crud.rules import add_rule, get_existing_rules, get_max_forum_rule_id, get_rules
from src.utils.renderer import text_to_image

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

parser = RuleEngineParser()


async def get_review_rule_strs(fid: int) -> AsyncGenerator[bytes, None]:
    batch_list: list[str] = []
    page = 1
    async for rule in get_rules(fid):
        rule_str = (
            f"ID：{rule.forum_rule_id}\n"
            f"名称：{rule.name}\n"
            f"触发条件：{parser.dump_rule(rule.trigger, mode='cnl')}\n"
            f"执行操作：{parser.dump_actions(rule.actions, mode='cnl')}\n"
            f"状态：{'启用' if rule.enabled else '禁用'}\n"
        )
        batch_list.append(rule_str)
        if len(batch_list) >= 10:
            text = "\n".join(batch_list)
            image = await text_to_image(text, header="审查规则列表", footer=f"第 {page} 页")
            yield image
            batch_list = []
            page += 1
    if batch_list:
        text = "\n".join(batch_list)
        image = await text_to_image(text, header="审查规则列表", footer=f"第 {page} 页")
        yield image


async def get_existing_keywords(fid: int, keywords: list[str]) -> list[str]:
    rules = [
        Condition(field=FieldType.FULL_TEXT, operator=OperatorType.CONTAINS, value=keyword) for keyword in keywords
    ]
    existing_rules = await get_existing_rules(fid, TargetType.ALL, rules)
    return [rule.trigger.value for rule in existing_rules]  # type: ignore


async def add_keyword_config(fid: int, keyword: str, notify_type: str) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    action_list = []
    if notify_type in ("删除并通知", "删封并通知"):
        action_list.append(Action(type=ActionType.DELETE, params={}))
    if notify_type in ("删封并通知"):
        action_list.append(Action(type=ActionType.BAN, params={"days": 1}))
    if notify_type in ("删除并通知", "删封并通知", "仅通知"):
        action_list.append(Action(type=ActionType.NOTIFY, params={"message": f"触发关键词：{keyword}"}))
    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        target_type=TargetType.ALL,
        name=f"关键词：{keyword}",
        enabled=True,
        priority=50,
        trigger=Condition(field=FieldType.FULL_TEXT, operator=OperatorType.CONTAINS, value=keyword),
        actions=action_list,
    )
    await add_rule(rule)


async def get_existing_users(fid: int, user_ids: list[int]) -> list[int]:
    rules = [Condition(field=FieldType.USER_ID, operator=OperatorType.EQ, value=user_id) for user_id in user_ids]
    existing_rules = await get_existing_rules(fid, TargetType.ALL, rules)
    return [int(rule.trigger.value) for rule in existing_rules]  # type: ignore


async def add_user_config(fid: int, user_id: int, user_display: str, notify_type: str) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    action_list = []
    if notify_type in ("删除并通知", "删封并通知"):
        action_list.append(Action(type=ActionType.DELETE, params={}))
    if notify_type in ("删封并通知"):
        action_list.append(Action(type=ActionType.BAN, params={"days": 1}))
    if notify_type in ("删除并通知", "删封并通知", "仅通知"):
        action_list.append(Action(type=ActionType.NOTIFY, params={"message": f"监控用户：{user_display}"}))
    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        target_type=TargetType.ALL,
        name=f"监控用户：{user_display}",
        enabled=True,
        priority=50,
        trigger=Condition(field=FieldType.USER_ID, operator=OperatorType.EQ, value=user_id),
        actions=action_list,
    )
    await add_rule(rule)
