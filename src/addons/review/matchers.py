from arclet.alconna import Alconna, Args, MultiVar
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.rule import Rule
from nonebot_plugin_alconna import AlconnaQuery, Field, Query, on_alconna

from src.addons.review import service
from src.common import ClientCache
from src.db.crud import group
from src.utils import (
    handle_tieba_uids,
    rule_admin,
    rule_signed,
)

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
    group_info = await group.get_group(event.group_id)
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
                else "：\n" + "：a. 直接删除\nb. 删除并通知\nc. 仅通知\n发送其他内容取消操作。",
                timeout=60,
            )
            if confirm is None:
                await add_keyword_cmd.finish("操作超时，已取消。")
            confirm_text = confirm.extract_plain_text().strip()
            if confirm_text in ("A", "B", "C"):
                batch_type = confirm_text.lower()
                confirm_text = batch_type
        else:
            confirm_text = batch_type

        if confirm_text == "a":
            notify_type = "直接删除"
        elif confirm_text == "b":
            notify_type = "删除并通知"
        elif confirm_text == "c":
            notify_type = "仅通知"
        else:
            await add_keyword_cmd.finish("操作已取消。")

        await service.add_keyword_config(group_info.fid, group_info.group_id, keyword, notify_type)

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

    group_info = await group.get_group(event.group_id)

    raw_users = {}
    client = await ClientCache.get_client()
    for tieba_uid in tieba_uids:
        user_info = await client.tieba_uid2user_info(tieba_uid)
        if user_info.user_id == 0:
            await add_user_cmd.send(f"暂时无法获取贴吧ID为 {tieba_uid} 的用户信息，请重试。")
            continue
        raw_users[str(user_info.user_id)] = f"{user_info.nick_name}({user_info.tieba_uid})"

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
                else "：\n" + "：a. 直接删除\nb. 删除并通知\nc. 仅通知\n发送其他内容取消操作。",
                timeout=60,
            )
            if confirm is None:
                await add_user_cmd.finish("操作超时，已取消。")
            confirm_text = confirm.extract_plain_text().strip()
            if confirm_text in ("A", "B", "C"):
                batch_type = confirm_text.lower()
                confirm_text = batch_type
        else:
            confirm_text = batch_type

        if confirm_text == "a":
            notify_type = "直接删除"
        elif confirm_text == "b":
            notify_type = "删除并通知"
        elif confirm_text == "c":
            notify_type = "仅通知"
        else:
            await add_user_cmd.finish("操作已取消。")

        await service.add_user_config(group_info.fid, group_info.group_id, user, notify_type)

    if new_users:
        new_user_strs = [raw_users[user] for user in new_users]
        await add_user_cmd.finish(f"已成功添加监控用户：{'，'.join(new_user_strs)}")
