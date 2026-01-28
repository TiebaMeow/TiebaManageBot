from arclet.alconna import Alconna, Args, MultiVar
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, permission
from nonebot.rule import Rule
from nonebot_plugin_alconna import AlconnaQuery, Field, Query, on_alconna

from src.common import ClientCache, tieba_uid2user_info_cached
from src.db.crud.group import get_group
from src.utils import handle_tieba_uids, rule_admin, rule_signed

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
        suffix = MessageSegment.text(f"第 {page} 页，已无更多内容。")
        await query_rule_cmd.finish(img_seg + suffix)
    if not first_send:
        await query_rule_cmd.finish("当前没有设置任何审查规则。")


add_keyword_alc = Alconna(
    "add_keyword_rule",
    Args["keywords", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个关键词，以空格分隔。")],
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
            confirm_text = f"请发送相应字母选择关键词“{keyword}”的处理方式"
            if len(new_keywords) > 1:
                confirm_text += "，发送相应大写字母批量设置所有关键词的处理方式"
            confirm_text += "：\na. 直接删除\nb. 删除并通知\nc. 删封并通知\nd. 仅通知\n发送其他内容取消操作。"
            confirm = await add_keyword_cmd.prompt(confirm_text, timeout=60)
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

        await service.add_keyword_config(group_info.fid, keyword, notify_type, event.user_id)

    if new_keywords:
        await add_keyword_cmd.finish(f"已成功添加关键词：{'，'.join(new_keywords)}")


del_keyword_alc = Alconna(
    "del_keyword_rule",
    Args["keywords", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个关键词，以空格分隔。")],
)

del_keyword_cmd = on_alconna(
    command=del_keyword_alc,
    aliases={"删除关键词"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_keyword_cmd.handle()
async def del_keyword_handle(
    event: GroupMessageEvent,
    raw_keywords: Query[tuple[str, ...]] = AlconnaQuery("keywords", ()),
):
    group_info = await get_group(event.group_id)
    keywords = list(set(raw_keywords.result))

    existing_keywords = await service.get_existing_keywords(group_info.fid, keywords)

    if not existing_keywords:
        await del_keyword_cmd.finish("所提供的关键词均不存在。")

    for keyword in existing_keywords:
        await service.remove_keyword_config(group_info.fid, keyword)

    await del_keyword_cmd.finish(f"已成功删除关键词：{'，'.join(existing_keywords)}")


add_user_alc = Alconna(
    "add_user_rule",
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

    raw_users: dict[int, str] = {}
    client = await ClientCache.get_client()
    for tieba_uid in tieba_uids:
        user_info = await tieba_uid2user_info_cached(client, tieba_uid)
        if user_info.user_id == 0:
            await add_user_cmd.finish("用户信息获取失败，请稍后重试。")
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
            confirm_text = f"请发送相应字母选择监控用户 {user_display} 的处理方式"
            if len(new_users) > 1:
                confirm_text += "，发送相应大写字母批量设置所有监控用户的处理方式"
            confirm_text += "：\na. 直接删除\nb. 删除并通知\nc. 删封并通知\nd. 仅通知\n发送其他内容取消操作。"
            confirm = await add_user_cmd.prompt(confirm_text, timeout=60)
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

        await service.add_user_config(group_info.fid, user, user_display, notify_type, event.user_id)

    if new_users:
        new_user_strs = [raw_users[user] for user in new_users]
        await add_user_cmd.finish(f"已成功添加监控用户：{'，'.join(new_user_strs)}")


del_user_alc = Alconna(
    "del_user_rule",
    Args["users", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

del_user_cmd = on_alconna(
    command=del_user_alc,
    aliases={"删除监控用户"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_user_cmd.handle()
async def del_user_handle(
    event: GroupMessageEvent,
    tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("users", ()),
):
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await del_user_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    group_info = await get_group(event.group_id)

    raw_users: dict[int, str] = {}
    client = await ClientCache.get_client()
    for tieba_uid in tieba_uids:
        user_info = await tieba_uid2user_info_cached(client, tieba_uid)
        if user_info.user_id == 0:
            await del_user_cmd.finish("用户信息获取失败，请稍后重试。")
        raw_users[user_info.user_id] = f"{user_info.nick_name}({user_info.tieba_uid})"

    existing_users = await service.get_existing_users(group_info.fid, list(raw_users.keys()))

    if not existing_users:
        await del_user_cmd.finish("所提供的用户均不存在。")

    for user in existing_users:
        await service.remove_user_config(group_info.fid, user)

    existing_user_strs = [raw_users[user] for user in existing_users]
    await del_user_cmd.finish(f"已成功删除监控用户：{'，'.join(existing_user_strs)}")


add_at_alc = Alconna(
    "add_at_rule",
    Args["users", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

add_at_cmd = on_alconna(
    command=add_at_alc,
    aliases={"添加监控艾特"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_at_cmd.handle()
async def add_at_handle(
    event: GroupMessageEvent,
    tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("users", ()),
):
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await add_at_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    group_info = await get_group(event.group_id)

    raw_users: dict[int, str] = {}
    client = await ClientCache.get_client()
    for tieba_uid in tieba_uids:
        user_info = await tieba_uid2user_info_cached(client, tieba_uid)
        if user_info.user_id == 0:
            await add_at_cmd.finish("用户信息获取失败，请稍后重试。")
        raw_users[user_info.user_id] = f"{user_info.nick_name}({user_info.tieba_uid})"

    existing_users = await service.get_existing_ats(group_info.fid, list(raw_users.keys()))
    if existing_users:
        existing_user_strs = [raw_users[user] for user in existing_users]
        await add_at_cmd.send(f"以下用户已存在：{'，'.join(existing_user_strs)}")

    new_users = set(raw_users.keys()) - set(existing_users)
    for user in new_users:
        user_display = raw_users[user]
        await service.add_at_config(group_info.fid, user, user_display, event.user_id)

    if new_users:
        new_user_strs = [raw_users[user] for user in new_users]
        await add_at_cmd.finish(f"已成功添加监控用户：{'，'.join(new_user_strs)}")


del_at_alc = Alconna(
    "del_at_rule",
    Args["users", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

del_at_cmd = on_alconna(
    command=del_at_alc,
    aliases={"删除监控艾特"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_at_cmd.handle()
async def del_at_handle(
    event: GroupMessageEvent,
    tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("users", ()),
):
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await del_at_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    group_info = await get_group(event.group_id)

    raw_users: dict[int, str] = {}
    client = await ClientCache.get_client()
    for tieba_uid in tieba_uids:
        user_info = await tieba_uid2user_info_cached(client, tieba_uid)
        if user_info.user_id == 0:
            await del_at_cmd.finish("用户信息获取失败，请稍后重试。")
        raw_users[user_info.user_id] = f"{user_info.nick_name}({user_info.tieba_uid})"

    existing_users = await service.get_existing_ats(group_info.fid, list(raw_users.keys()))

    if not existing_users:
        await del_at_cmd.finish("所提供的用户均不存在。")

    for user in existing_users:
        await service.remove_at_config(group_info.fid, user)

    existing_user_strs = [raw_users[user] for user in existing_users]
    await del_at_cmd.finish(f"已成功删除监控艾特：{'，'.join(existing_user_strs)}")


set_level_threshold_alc = Alconna(
    "set_level_threshold",
    Args["level", int, Field(completion=lambda: "请输入等级墙数值（整数）。")],
)


set_level_threshold_cmd = on_alconna(
    command=set_level_threshold_alc,
    aliases={"设置等级墙"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@set_level_threshold_cmd.handle()
async def set_level_threshold_handle(
    event: GroupMessageEvent,
    level: Query[int] = AlconnaQuery("level", 0),
):
    group_info = await get_group(event.group_id)
    existing_threshold = await service.get_existing_level_threshold(group_info.fid)
    if existing_threshold is not None:
        await set_level_threshold_cmd.finish(f"当前已存在 {existing_threshold} 级等级墙。")

    if level.result <= 0 or level.result > 17:
        await set_level_threshold_cmd.finish("等级墙数值应在 1 到 17 之间。")

    confirm = await set_level_threshold_cmd.prompt(
        f"请确认是否设置等级墙为 {level.result} 级？"
        "等级墙将立即生效，bot 将自动删除所有低于该等级的用户的主题贴、回复、楼中楼。\n"
        "发送“确认”以继续，发送其他内容取消操作。",
        timeout=60,
    )
    if confirm is None or confirm.extract_plain_text().strip() != "确认":
        await set_level_threshold_cmd.finish("操作已取消。")
    await service.set_level_threshold(group_info.fid, level.result, event.user_id)
    await set_level_threshold_cmd.finish(f"已将等级墙设置为 {level.result} 级。")


del_level_threshold_cmd = on_alconna(
    command="del_level_threshold",
    aliases={"删除等级墙"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_level_threshold_cmd.handle()
async def del_level_threshold_handle(
    event: GroupMessageEvent,
):
    group_info = await get_group(event.group_id)
    existing_threshold = await service.get_existing_level_threshold(group_info.fid)
    if existing_threshold is None:
        await del_level_threshold_cmd.finish("当前不存在等级墙。")

    await service.remove_level_threshold(group_info.fid)
    await del_level_threshold_cmd.finish(f"已删除 {existing_threshold} 级等级墙。")


add_ai_review_alc = Alconna("add_ai_review_rule")

add_ai_review_cmd = on_alconna(
    command=add_ai_review_alc,
    aliases={"添加AI审查"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_ai_review_cmd.handle()
async def add_ai_review_handle(event: GroupMessageEvent):
    group_info = await get_group(event.group_id)

    resp = await add_ai_review_cmd.prompt(
        "请输入AI审查的 system_prompt，输入“默认”使用默认的 system_prompt，输入“取消”以取消操作：", timeout=60
    )
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_ai_review_cmd.finish("已取消。")

    system_prompt = (
        "你是百度贴吧的一名专业内容审核助手。请仔细审查以下用户发布的贴子或回复内容，判断其是否违反社区规范。\n"
        "主要违规类型包括：攻击歧视、恶意辱骂、带节奏、滑坡唱衰、垃圾广告、违法犯罪等。\n"
        "请严格只输出标准的 JSON 字符串，不要包含 Markdown 代码块（如 ```json）或其他无关文字。\n"
        "输出格式要求：\n"
        "{\n"
        '  "violation": <Boolean>, // true 表示违规，false 表示合规\n'
        '  "category": "<String>", // 违规类型（如"攻击歧视"、"广告"），若无违规填"none"\n'
        '  "reason": "<String>",   // 简要的判断理由\n'
        '  "confidence": <Float>   // 置信度 (0.0 - 1.0)\n'
        "}"
    )
    text = resp.extract_plain_text().strip()
    if text and text != "默认":
        system_prompt = text

    resp = await add_ai_review_cmd.prompt(
        '请输入AI返回内容中预期包含的标记字符串，输入“默认”使用默认的“"violation": true”，输入“取消”以取消操作：',
        timeout=60,
    )
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_ai_review_cmd.finish("已取消。")
    marker = resp.extract_plain_text().strip()
    if not marker or marker == "默认":
        marker = '"violation": true'

    await service.add_ai_review_config(group_info.fid, system_prompt, marker, event.user_id)
    await add_ai_review_cmd.finish("已成功添加AI审查规则。")


del_ai_review_alc = Alconna("del_ai_review_rule")

del_ai_review_cmd = on_alconna(
    command=del_ai_review_alc,
    aliases={"删除AI审查"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_ai_review_cmd.handle()
async def del_ai_review_handle(event: GroupMessageEvent):
    group_info = await get_group(event.group_id)
    await service.remove_ai_review_config(group_info.fid)
    await del_ai_review_cmd.finish("已删除AI审查规则。")


del_rule_alc = Alconna(
    "del_rule",
    Args[
        "rules",
        MultiVar(str, "+"),
        Field(completion=lambda: "请输入一个或多个规则ID，以空格分隔。输入“all”删除所有规则。"),
    ],
)

del_rule_cmd = on_alconna(
    command=del_rule_alc,
    aliases={"删除规则", "移除规则"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_rule_cmd.handle()
async def del_rule_handle(
    event: GroupMessageEvent,
    raw_rules: Query[tuple[str, ...]] = AlconnaQuery("rules", ()),
):
    group_info = await get_group(event.group_id)
    rules_input = list(set(raw_rules.result))

    if "all" in rules_input:
        confirm = await del_rule_cmd.prompt(
            "您即将删除本吧【所有】审查规则。\n请发送“确认”以继续，发送其他内容取消操作。",
            timeout=60,
        )
        if confirm is None or confirm.extract_plain_text().strip() != "确认":
            await del_rule_cmd.finish("操作已取消。")

        count = await service.remove_all_rules(group_info.fid)
        await del_rule_cmd.finish(f"已成功删除本吧所有 {count} 条审查规则。")

    success_ids = []
    fail_ids = []

    for rule_id_str in rules_input:
        try:
            rule_id = int(rule_id_str)
            if await service.remove_rule_by_id(group_info.fid, rule_id):
                success_ids.append(rule_id_str)
            else:
                fail_ids.append(rule_id_str)
        except ValueError:
            fail_ids.append(rule_id_str)

    msg = ""
    if success_ids:
        msg += f"已删除规则 ID：{'，'.join(success_ids)}\n"
    if fail_ids:
        msg += f"删除失败（不存在或格式错误）：{'，'.join(fail_ids)}"

    await del_rule_cmd.finish(msg.strip())


add_rule_alc = Alconna("add_rule")

add_rule_cmd = on_alconna(
    command=add_rule_alc,
    aliases={"添加规则"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_rule_cmd.handle()
async def add_rule_handle(event: GroupMessageEvent):
    group_info = await get_group(event.group_id)

    resp = await add_rule_cmd.prompt("请输入规则名称：", timeout=60)
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_rule_cmd.finish("已取消。")
    name = resp.extract_plain_text().strip()

    resp = await add_rule_cmd.prompt("请输入触发条件 (CNL/DSL)：", timeout=60)
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_rule_cmd.finish("已取消。")
    try:
        trigger = service.parser.parse_rule(resp.extract_plain_text())
    except Exception as e:
        await add_rule_cmd.finish(f"解析触发条件失败：{e}")

    resp = await add_rule_cmd.prompt("请输入执行动作 (CNL/DSL)：", timeout=60)
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_rule_cmd.finish("已取消。")
    try:
        actions = service.parser.parse_actions(resp.extract_plain_text())
    except Exception as e:
        await add_rule_cmd.finish(f"解析执行动作失败：{e}")

    resp = await add_rule_cmd.prompt("请输入优先级 (1-20之间的整数)：", timeout=60)
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_rule_cmd.finish("已取消。")
    try:
        priority = int(resp.extract_plain_text().strip())
    except ValueError:
        await add_rule_cmd.finish("优先级应为整数。")
    if priority < 1 or priority > 20:
        await add_rule_cmd.finish("优先级应在 1 到 20 之间。")

    resp = await add_rule_cmd.prompt("触发该规则是否阻断后续规则？(是/否，默认 是)：", timeout=60)
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_rule_cmd.finish("已取消。")
    else:
        block_text = resp.extract_plain_text().strip().lower()
        block = block_text not in ("n", "no", "false", "0", "否")

    resp = await add_rule_cmd.prompt("请输入规则生效范围 (主题贴/回复/楼中楼/全部，默认 全部)：", timeout=60)
    if resp is None or resp.extract_plain_text().strip() == "取消":
        await add_rule_cmd.finish("已取消。")
    target_text = resp.extract_plain_text().strip()
    if target_text in ("主题贴", "thread"):
        target_type = service.TargetType.THREAD
    elif target_text in ("回复", "post"):
        target_type = service.TargetType.POST
    elif target_text in ("楼中楼", "comment"):
        target_type = service.TargetType.COMMENT
    else:
        target_type = service.TargetType.ALL

    await service.add_custom_rule(
        group_info.fid,
        name,
        trigger,
        actions,
        priority,
        block,
        event.user_id,
        target_type,
    )
    await add_rule_cmd.finish(f"规则 {name} 添加成功。")
