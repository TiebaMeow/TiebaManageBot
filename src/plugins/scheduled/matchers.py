from typing import Literal

from arclet.alconna import Alconna, Args, Arparma
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.rule import Rule
from nonebot_plugin_alconna import Match, on_alconna

from src.common.cache import get_appeal_id
from src.db.crud import get_group
from src.utils import (
    require_slave_bduss,
    rule_admin,
    rule_moderator,
    rule_reply,
    rule_signed,
)

from . import service

appeal_switch_alc = Alconna(
    "appeal_push",
    Args["switch", Literal["开启", "关闭", "状态"], "状态"],
)

appeal_switch_cmd = on_alconna(
    command=appeal_switch_alc,
    aliases={"申诉推送", "自动拒绝申诉"},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@appeal_switch_cmd.handle()
@require_slave_bduss
async def appeal_switch_handle(event: GroupMessageEvent, args: Arparma):
    try:
        cmd = args.context["$shortcut.regex_match"].group()[1:]
    except Exception:
        cmd = "状态"
    switch = args.query("switch")
    group_info = await get_group(event.group_id)

    if switch == "开启":
        if cmd == "申诉推送":
            await service.update_group_args(event.group_id, "appeal_sub", True)
        elif cmd == "自动拒绝申诉":
            await service.update_group_args(event.group_id, "appeal_autodeny", True)
        await appeal_switch_cmd.finish(f"已开启{cmd}。")
    elif switch == "关闭":
        if cmd == "申诉推送":
            await service.update_group_args(event.group_id, "appeal_sub", False)
        elif cmd == "自动拒绝申诉":
            await service.update_group_args(event.group_id, "appeal_autodeny", False)
        await appeal_switch_cmd.finish(f"已关闭{cmd}。")
    else:
        if cmd == "申诉推送":
            if group_info.group_args.get("appeal_sub", False):
                await appeal_switch_cmd.finish("当前已开启申诉推送。")
            else:
                await appeal_switch_cmd.finish("当前已关闭申诉推送。")
        elif cmd == "自动拒绝申诉":
            if group_info.group_args.get("appeal_autodeny", False):
                await appeal_switch_cmd.finish("当前已开启自动拒绝申诉。")
            else:
                await appeal_switch_cmd.finish("当前已关闭自动拒绝申诉。")


deal_appeal_alc = Alconna(
    "deal_appeal",
    Args["reason", str, ""],
)

deal_appeal_cmd = on_alconna(
    command=deal_appeal_alc,
    aliases={"拒绝申诉", "通过申诉", "驳回申诉", "拒绝", "通过", "驳回"},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_reply, rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=10,
    block=True,
)


@deal_appeal_cmd.handle()
@require_slave_bduss
async def deal_appeal_handle(event: GroupMessageEvent, reason: Match[str], args: Arparma):
    cmd = args.context["$shortcut.trigger"].split(" ")[0][1:]
    reason_str = reason.result if reason.available else "无"
    assert event.reply is not None
    message_id = event.reply.real_id
    appeal_id, user_id = await get_appeal_id(message_id)
    if not appeal_id:
        await deal_appeal_cmd.finish("未找到对应的申诉。")
    group_info = await get_group(event.group_id)

    refuse = cmd in ["拒绝申诉", "驳回申诉", "拒绝", "驳回"]
    success = await service.handle_appeal(group_info, appeal_id, user_id, refuse, reason_str, event.user_id)

    action = "拒绝" if refuse else "通过"
    if success:
        await deal_appeal_cmd.finish(f"已{action}申诉。")
    else:
        await deal_appeal_cmd.finish(f"{action}申诉失败。")
