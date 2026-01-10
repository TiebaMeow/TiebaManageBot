from arclet.alconna import Alconna, Args, MultiVar
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, permission
from nonebot.rule import Rule
from nonebot_plugin_alconna import AlconnaQuery, Field, Query, on_alconna

from src.common import ClientCache
from src.db.crud.group import get_group
from src.utils import (
    handle_tieba_uids,
    rule_admin,
    rule_signed,
)

from . import service

query_rule_alc = Alconna("query_rule")

query_rule_cmd = on_alconna(
    command=query_rule_alc,
    aliases={"规则列表", "规则查询"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@query_rule_cmd.handle()
async def query_rule_handle(event: GroupMessageEvent):
    group_info = await get_group(event.group_id)
    first_send = False
    page = 1
    buffer: bytes | None = None
    async for image in service.get_review_rule_strs(group_info.fid):
        if not first_send:
            first_send = True
            await query_rule_cmd.send("以下是本吧的审查规则列表：")
            buffer = image
        else:
            if buffer is not None:
                img_seg = MessageSegment.image(buffer)
                suffix = MessageSegment.text(f"第 {page} 页，继续查询请输入“下一页”。")
                next_input = await query_rule_cmd.prompt(img_seg + suffix, timeout=60)
                if next_input is None or next_input.extract_plain_text().strip() != "下一页":
                    await query_rule_cmd.finish("已结束查询。")
            buffer = image
            page += 1
    if buffer is not None:
        img_seg = MessageSegment.image(buffer)
        suffix = MessageSegment.text(f"第 {page} 页，已无更多内容，结束查询。")
        await query_rule_cmd.finish(img_seg + suffix)
    if not first_send:
        await query_rule_cmd.finish("当前没有设置任何审查规则。")


add_keyword_alc = Alconna(
    "add_keyword",
    Args[
        "keywords", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个关键词，以空格分隔，支持正则表达式。")
    ],
)

add_keyword_cmd = on_alconna(
    command=add_keyword_alc,
    aliases={"添加关键词"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_keyword_cmd.handle()
async def add_keyword_handle(
    event: GroupMessageEvent,
    raw_keywords: Query[tuple[str, ...]] = AlconnaQuery("keywords", ()),
):
    group_info = await get_group(event.group_id)
    keywords = list(set(raw_keywords.result))

    existing_keywords = await service.get_existing_keywords(group_info.fid, keywords)

    if existing_keywords:
        await add_keyword_cmd.send(f"以下关键词已存在：{'，'.join(existing_keywords)}")

    new_keywords = set(keywords) - set(existing_keywords)
    batch_type = ""

    for keyword in new_keywords:
        if not batch_type:
            confirm = await add_keyword_cmd.prompt(
                f"请发送相应字母选择关键词“{keyword}”的处理方式" + "，发送相应大写字母批量设置所有关键词的处理方式：\n"
                if len(new_keywords) > 1
                else "：\n" + "：a. 直接删除\nb. 删除并通知\nc. 删封并通知\nd. 仅通知\n发送其他内容取消操作。",
                timeout=60,
            )
            if confirm is None:
                await add_keyword_cmd.finish("操作超时，已取消。")
            confirm_text = confirm.extract_plain_text().strip()
            if confirm_text in ("A", "B", "C", "D"):
                batch_type = confirm_text.lower()
                confirm_text = batch_type
        else:
            confirm_text = batch_type

        if confirm_text == "a":
            notify_type = "直接删除"
        elif confirm_text == "b":
            notify_type = "删除并通知"
        elif confirm_text == "c":
            notify_type = "删封并通知"
        elif confirm_text == "d":
            notify_type = "仅通知"
        else:
            await add_keyword_cmd.finish("操作已取消。")

        await service.add_keyword_config(group_info.fid, keyword, notify_type)

    if new_keywords:
        await add_keyword_cmd.finish(f"已成功添加关键词：{'，'.join(new_keywords)}")


add_user_alc = Alconna(
    "add_user",
    Args["users", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

add_user_cmd = on_alconna(
    command=add_user_alc,
    aliases={"添加监控用户"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_user_cmd.handle()
async def add_user_handle(
    event: GroupMessageEvent,
    tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("users", ()),
):
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await add_user_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    group_info = await get_group(event.group_id)

    raw_users = {}
    client = await ClientCache.get_client()
    for tieba_uid in tieba_uids:
        user_info = await client.tieba_uid2user_info(tieba_uid)
        raw_users[user_info.user_id] = f"{user_info.nick_name}({user_info.tieba_uid})"

    existing_users = await service.get_existing_users(group_info.fid, list(raw_users.keys()))

    if existing_users:
        existing_user_strs = [raw_users[user] for user in existing_users]
        await add_user_cmd.send(f"以下用户已存在：{'，'.join(existing_user_strs)}")

    new_users = set(raw_users.keys()) - set(existing_users)
    batch_type = ""

    for user in new_users:
        user_display = raw_users[user]
        if not batch_type:
            confirm = await add_user_cmd.prompt(
                f"请发送相应字母选择监控用户“{user_display}”的处理方式"
                + "，发送相应大写字母批量设置所有监控用户的处理方式：\n"
                if len(new_users) > 1
                else "：\n" + "：a. 直接删除\nb. 删除并通知\nc. 删封并通知\nd. 仅通知\n发送其他内容取消操作。",
                timeout=60,
            )
            if confirm is None:
                await add_user_cmd.finish("操作超时，已取消。")
            confirm_text = confirm.extract_plain_text().strip()
            if confirm_text in ("A", "B", "C", "D"):
                batch_type = confirm_text.lower()
                confirm_text = batch_type
        else:
            confirm_text = batch_type

        if confirm_text == "a":
            notify_type = "直接删除"
        elif confirm_text == "b":
            notify_type = "删除并通知"
        elif confirm_text == "c":
            notify_type = "删封并通知"
        elif confirm_text == "d":
            notify_type = "仅通知"
        else:
            await add_user_cmd.finish("操作已取消。")

        await service.add_user_config(group_info.fid, user, user_display, notify_type)

    if new_users:
        new_user_strs = [raw_users[user] for user in new_users]
        await add_user_cmd.finish(f"已成功添加监控用户：{'，'.join(new_user_strs)}")
