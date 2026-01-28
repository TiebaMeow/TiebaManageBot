from __future__ import annotations

from typing import TYPE_CHECKING

from tiebameow.parser.rule_parser import RuleEngineParser
from tiebameow.schemas.rules import (
    Actions,
    BanAction,
    Condition,
    DeleteAction,
    FieldType,
    FunctionCall,
    LogicType,
    NotifyAction,
    OperatorType,
    ReviewRule,
    RuleGroup,
    TargetType,
)
from tiebameow.utils.time_utils import now_with_tz

from src.addons.interface.publisher import publisher
from src.db.crud.rules import (
    add_rule,
    delete_rule,
    get_existing_level_threshold_rule,
    get_existing_rule,
    get_existing_rules,
    get_max_forum_rule_id,
    get_rule_by_forum_rule_id,
    get_rule_by_name,
    get_rules,
)
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


async def add_keyword_config(fid: int, keyword: str, notify_type: str, uploader_id: int) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    actions = Actions()
    if notify_type in ("直接删除", "删除并通知", "删封并通知"):
        actions.delete = DeleteAction(enabled=True, params={"log": True})
    if notify_type in ("删封并通知"):
        actions.ban = BanAction(enabled=True, days=1)
    if notify_type in ("删除并通知", "删封并通知", "仅通知"):
        actions.notify = NotifyAction(enabled=True, template="default", params={"message": f"触发关键词：{keyword}"})
    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        uploader_id=uploader_id,
        target_type=TargetType.ALL,
        name=f"关键词：{keyword}",
        enabled=True,
        block=True,
        priority=10,
        trigger=Condition(field=FieldType.FULL_TEXT, operator=OperatorType.CONTAINS, value=keyword),
        actions=actions,
    )
    rule_id = await add_rule(rule)
    await publisher.publish_rule_update(rule_id, "ADD")


async def remove_keyword_config(fid: int, keyword: str) -> None:
    existing_rule = await get_existing_rule(
        fid,
        TargetType.ALL,
        Condition(field=FieldType.FULL_TEXT, operator=OperatorType.CONTAINS, value=keyword),
    )
    if existing_rule:
        await delete_rule(existing_rule.id)
        await publisher.publish_rule_update(existing_rule.id, "DELETE")


async def get_existing_users(fid: int, user_ids: list[int]) -> list[int]:
    rules = [Condition(field=FieldType.USER_ID, operator=OperatorType.EQ, value=user_id) for user_id in user_ids]
    existing_rules = await get_existing_rules(fid, TargetType.ALL, rules)
    return [int(rule.trigger.value) for rule in existing_rules]  # type: ignore


async def add_user_config(fid: int, user_id: int, user_display: str, notify_type: str, uploader_id: int) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    actions = Actions()
    if notify_type in ("删除并通知", "删封并通知"):
        actions.delete = DeleteAction(enabled=True, params={"log": True})
    if notify_type in ("删封并通知"):
        actions.ban = BanAction(enabled=True, days=1)
    if notify_type in ("删除并通知", "删封并通知", "仅通知"):
        actions.notify = NotifyAction(enabled=True, template="default", params={"message": f"监控用户：{user_display}"})
    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        uploader_id=uploader_id,
        target_type=TargetType.ALL,
        name=f"监控用户：{user_display}",
        enabled=True,
        block=True,
        priority=9,
        trigger=Condition(field=FieldType.USER_ID, operator=OperatorType.EQ, value=user_id),
        actions=actions,
    )
    rule_id = await add_rule(rule)
    await publisher.publish_rule_update(rule_id, "ADD")


async def remove_user_config(fid: int, user_id: int) -> None:
    existing_rule = await get_existing_rule(
        fid,
        TargetType.ALL,
        Condition(field=FieldType.USER_ID, operator=OperatorType.EQ, value=user_id),
    )
    if existing_rule:
        await delete_rule(existing_rule.id)
        await publisher.publish_rule_update(existing_rule.id, "DELETE")


async def get_existing_ats(fid: int, user_ids: list[int]) -> list[int]:
    rules = [Condition(field=FieldType.ATS, operator=OperatorType.CONTAINS, value=user_id) for user_id in user_ids]
    existing_rules = await get_existing_rules(fid, TargetType.ALL, rules)
    return [int(rule.trigger.value) for rule in existing_rules]  # type: ignore


async def add_at_config(fid: int, user_id: int, user_display: str, uploader_id: int) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    actions = Actions(
        notify=NotifyAction(enabled=True, template="default", params={"message": f"艾特吧务：{user_display}"})
    )
    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        uploader_id=uploader_id,
        target_type=TargetType.ALL,
        name=f"艾特吧务：{user_display}",
        enabled=True,
        block=True,
        priority=8,
        trigger=Condition(field=FieldType.ATS, operator=OperatorType.CONTAINS, value=user_id),
        actions=actions,
    )
    rule_id = await add_rule(rule)
    await publisher.publish_rule_update(rule_id, "ADD")


async def remove_at_config(fid: int, user_id: int) -> None:
    existing_rule = await get_existing_rule(
        fid,
        TargetType.ALL,
        Condition(field=FieldType.ATS, operator=OperatorType.CONTAINS, value=user_id),
    )
    if existing_rule:
        await delete_rule(existing_rule.id)
        await publisher.publish_rule_update(existing_rule.id, "DELETE")


async def get_existing_level_threshold(fid: int) -> int | None:
    existing_rule = await get_existing_level_threshold_rule(fid)
    if existing_rule:
        for condition in existing_rule.trigger.conditions:  # type: ignore
            if (
                isinstance(condition, Condition)
                and condition.field == FieldType.LEVEL
                and condition.operator == OperatorType.LT
            ):
                return int(condition.value)
    return None


async def set_level_threshold(fid: int, level: int, uploader_id: int) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    actions = Actions(delete=DeleteAction(enabled=True))
    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        uploader_id=uploader_id,
        target_type=TargetType.ALL,
        name=f"等级墙：{level} 级",
        enabled=True,
        block=True,
        priority=4,
        trigger=RuleGroup(
            logic=LogicType.AND,
            conditions=[
                Condition(field=FieldType.LEVEL, operator=OperatorType.LT, value=level),
                Condition(field=FieldType.LEVEL, operator=OperatorType.GT, value=0),
                Condition(field=FieldType.CREATE_TIME, operator=OperatorType.GT, value=now_with_tz()),
            ],
        ),
        actions=actions,
    )
    rule_id = await add_rule(rule)
    await publisher.publish_rule_update(rule_id, "ADD")


async def remove_level_threshold(fid: int) -> None:
    existing_rule = await get_existing_level_threshold_rule(fid)
    if existing_rule:
        await delete_rule(existing_rule.id)
        await publisher.publish_rule_update(existing_rule.id, "DELETE")


async def add_ai_review_config(fid: int, system_prompt: str, marker: str, uploader_id: int) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    actions = Actions(
        notify=NotifyAction(
            enabled=True,
            template="default",
            params={"template": "ai_review"},
        )
    )

    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        uploader_id=uploader_id,
        target_type=TargetType.THREAD,
        name="AI审查",
        enabled=True,
        block=False,
        priority=20,
        trigger=Condition(
            field=FunctionCall(name="ai_review", kwargs={"system_prompt": system_prompt}),
            operator=OperatorType.CONTAINS,
            value=marker,
        ),
        actions=actions,
    )
    rule_id = await add_rule(rule)
    await publisher.publish_rule_update(rule_id, "ADD")


async def remove_ai_review_config(fid: int) -> None:
    existing_rule = await get_rule_by_name(fid, "AI审查")
    if existing_rule:
        await delete_rule(existing_rule.id)
        await publisher.publish_rule_update(existing_rule.id, "DELETE")


async def remove_rule_by_id(fid: int, forum_rule_id: int) -> bool:
    rule = await get_rule_by_forum_rule_id(fid, forum_rule_id)
    if rule:
        await delete_rule(rule.id)
        await publisher.publish_rule_update(rule.id, "DELETE")
        return True
    return False


async def remove_all_rules(fid: int) -> int:
    count = 0
    all_rules = [r async for r in get_rules(fid)]
    for rule in all_rules:
        await delete_rule(rule.id)
        await publisher.publish_rule_update(rule.id, "DELETE")
        count += 1
    return count


async def add_custom_rule(
    fid: int,
    name: str,
    trigger: RuleGroup | Condition,
    actions: Actions,
    priority: int,
    block: bool,
    uploader_id: int,
    target_type: TargetType = TargetType.ALL,
) -> None:
    max_forum_rule_id = await get_max_forum_rule_id(fid)
    rule = ReviewRule(
        id=0,
        fid=fid,
        forum_rule_id=max_forum_rule_id + 1,
        uploader_id=uploader_id,
        target_type=target_type,
        name=name,
        enabled=True,
        block=block,
        priority=priority,
        trigger=trigger,
        actions=actions,
    )
    rule_id = await add_rule(rule)
    await publisher.publish_rule_update(rule_id, "ADD")
