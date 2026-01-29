import base64

from arclet.alconna import Alconna
from nonebot import get_bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.rule import Rule
from nonebot_plugin_alconna import on_alconna

from src.db.crud import get_group
from src.utils import rule_admin, rule_moderator, rule_signed

from .service import REPORT_SUB_KEY, build_daily_report, update_group_args

daily_report_sub_alc = Alconna("daily_report_sub")

daily_report_sub_cmd = on_alconna(
    command=daily_report_sub_alc,
    aliases={"订阅日报"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


daily_report_unsub_alc = Alconna("daily_report_unsub")

daily_report_unsub_cmd = on_alconna(
    command=daily_report_unsub_alc,
    aliases={"退订日报"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


daily_report_push_alc = Alconna("daily_report_push")

daily_report_push_cmd = on_alconna(
    command=daily_report_push_alc,
    aliases={"日报"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@daily_report_sub_cmd.handle()
async def daily_report_sub_handle(event: GroupMessageEvent):
    await update_group_args(event.group_id, REPORT_SUB_KEY, True)
    await daily_report_sub_cmd.finish("已订阅日报，将在每日0点推送到本群。")


@daily_report_unsub_cmd.handle()
async def daily_report_unsub_handle(event: GroupMessageEvent):
    await update_group_args(event.group_id, REPORT_SUB_KEY, False)
    await daily_report_unsub_cmd.finish("已退订日报。")


@daily_report_push_cmd.handle()
async def daily_report_push_handle(event: GroupMessageEvent):
    bot = get_bot()
    group_info = await get_group(event.group_id)
    header, images = await build_daily_report(group_info)
    messages = [{"type": "text", "data": {"text": header}}]
    for img in images:
        img_b64 = base64.b64encode(img).decode()
        messages.append({"type": "image", "data": {"file": f"base64://{img_b64}"}})
    await bot.call_api("send_group_msg", group_id=event.group_id, message=messages)
