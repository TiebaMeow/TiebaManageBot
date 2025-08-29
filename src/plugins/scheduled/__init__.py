import time
from datetime import datetime
from typing import Literal

from arclet.alconna import Alconna, Args, Arparma
from nonebot import get_bot, get_plugin_config, require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_apscheduler import scheduler

from logger import log
from src.common import Client
from src.db import (
    AppealCache,
    Associated,
    AutoBanList,
    GroupCache,
    TextData,
    TiebaNameCache,
)
from src.utils import (
    require_slave_BDUSS,
    rule_admin,
    rule_moderator,
    rule_reply,
    rule_signed,
)

from .config import Config

require("nonebot_plugin_apscheduler")

require("nonebot_plugin_alconna")


__plugin_meta__ = PluginMetadata(
    name="scheduled",
    description="启动项与计划任务",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)


@scheduler.scheduled_job("cron", day="*", hour=4, minute=56, second=23)
async def autoban():
    log.info("Autoban task started.")
    banlists = await AutoBanList.get_ban_lists()
    for banlist in banlists:
        group_info = await GroupCache.get(banlist.group_id)
        assert group_info is not None  # for pylance
        if banlist.last_autoban and (datetime.now() - banlist.last_autoban).days < 3:
            continue
        failed = []
        log.info(f"Ready to autoban in {group_info.fname}")
        async with Client(group_info.slave_BDUSS, try_ws=True) as client:
            for user_id, ban_reason in banlist.ban_list.items():
                if ban_reason.enable:
                    result = await client.block(group_info.fid, user_id, day=10, reason="违规")
                    if not result:
                        failed.append(user_id)
        await AutoBanList.update_autoban(group_info.group_id, group_info.fid)
        if failed:
            log.warning(f"Failed to ban users: {', '.join(map(str, failed))} in {TiebaNameCache.get(group_info.fid)}")
    log.info("Autoban task finished.")


@scheduler.scheduled_job("interval", minutes=10)
async def appeal_push():
    group_infos = await GroupCache.all()
    for group_info in group_infos:
        if not group_info.slave_BDUSS or not group_info.appeal_sub:
            continue
        async with Client(group_info.slave_BDUSS, try_ws=True) as client:
            appeals = await client.get_unblock_appeals(group_info.fid, rn=20)
            cached_appeals = await AppealCache.get_appeals(group_info.group_id)
            for appeal in appeals.objs:
                user_info = await client.get_user_info(appeal.user_id)
                banlist = await AutoBanList.get_ban_list(group_info.group_id, group_info.fid)
                if banlist and user_info.user_id in banlist.ban_list:
                    await client.handle_unblock_appeals(
                        group_info.fid,
                        appeal_ids=[appeal.appeal_id],
                        refuse=True,
                    )
                    continue
                if group_info.appeal_autodeny:
                    if time.time() - appeal.appeal_time > 72000:
                        result = await client.handle_unblock_appeals(
                            group_info.fid,
                            appeal_ids=[appeal.appeal_id],
                            refuse=True,
                        )
                        bot = get_bot()
                        if result:
                            await Associated.add_data(
                                user_info,
                                group_info,
                                text_data=[
                                    TextData(uploader_id=0, fid=group_info.fid, text="[自动添加]超时自动拒绝申诉")
                                ],
                            )
                            await bot.call_api(
                                "send_group_msg",
                                **{
                                    "message": (
                                        f"由于即将超时，已自动拒绝用户"
                                        f"{user_info.nick_name}({user_info.tieba_uid})的封禁申诉。"
                                    ),
                                    "group_id": group_info.group_id,
                                },
                            )
                        if (appeal.appeal_id, user_info.user_id) in cached_appeals:
                            cached_appeals.remove((appeal.appeal_id, user_info.user_id))
                        continue
                if (appeal.appeal_id, user_info.user_id) not in cached_appeals:
                    punish_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(appeal.punish_time))
                    appeal_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(appeal.appeal_time))
                    msg = (
                        f"待处理的封禁申诉(appeal_id: {appeal.appeal_id})：\n"
                        f"用户：{user_info.nick_name}({user_info.tieba_uid})\n"
                        f"封禁开始时间：{punish_time}\n"
                        f"封禁天数：{appeal.punish_day}\n"
                        f"操作人：{appeal.op_name}\n"
                        f"申诉理由：{appeal.appeal_reason}\n"
                        f"申诉时间：{appeal_time}"
                    )
                    bot = get_bot()
                    try:
                        message_id = await bot.call_api(
                            "send_group_msg", **{"message": msg, "group_id": group_info.group_id}
                        )
                        message_id = message_id["message_id"]
                        assert isinstance(message_id, int)
                    except Exception:
                        log.error(f"Failed to push appeal message to {group_info.group_id}")
                    else:
                        await AppealCache.set_appeal_id(message_id, (appeal.appeal_id, user_info.user_id))
                        cached_appeals.append((appeal.appeal_id, user_info.user_id))
            await AppealCache.set_appeals(group_info.group_id, cached_appeals)


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
@require_slave_BDUSS
async def appeal_switch_handle(event: GroupMessageEvent, args: Arparma):
    try:
        cmd = args.context["$shortcut.regex_match"].group()[1:]
    except Exception:
        cmd = "状态"
    switch = args.query("switch")
    if switch == "开启":
        if cmd == "申诉推送":
            await GroupCache.update(event.group_id, appeal_sub=True)
        elif cmd == "自动拒绝申诉":
            await GroupCache.update(event.group_id, appeal_autodeny=True)
        await appeal_switch_cmd.finish(f"已开启{cmd}。")
    elif switch == "关闭":
        if cmd == "申诉推送":
            await GroupCache.update(event.group_id, appeal_sub=False)
        elif cmd == "自动拒绝申诉":
            await GroupCache.update(event.group_id, appeal_autodeny=False)
        await appeal_switch_cmd.finish(f"已关闭{cmd}。")
    else:
        group_info = await GroupCache.get(event.group_id)
        assert group_info is not None  # for pylance
        if cmd == "申诉推送":
            if group_info.appeal_sub:
                await appeal_switch_cmd.finish("当前已开启申诉推送。")
            else:
                await appeal_switch_cmd.finish("当前已关闭申诉推送。")
        elif cmd == "自动拒绝申诉":
            if group_info.appeal_autodeny:
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
@require_slave_BDUSS
async def deal_appeal_handle(event: GroupMessageEvent, reason: Match[str], args: Arparma):
    cmd = args.context["$shortcut.trigger"].split(" ")[0][1:]
    if reason.available:
        reason_str = reason.result
    else:
        reason_str = "无"
    assert event.reply is not None  # for pylance
    message_id = event.reply.real_id
    appeal_id, user_id = await AppealCache.get_appeal_id(message_id)
    if not appeal_id:
        await deal_appeal_cmd.finish("未找到对应的申诉。")
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    async with Client(group_info.slave_BDUSS, try_ws=True) as client:
        user_info = await client.get_user_info(user_id)
        if cmd in ["拒绝申诉", "驳回申诉", "拒绝", "驳回"]:
            result = await client.handle_unblock_appeals(group_info.fid, appeal_ids=[appeal_id], refuse=True)
            if result:
                await Associated.add_data(
                    user_info,
                    group_info,
                    text_data=[
                        TextData(
                            uploader_id=event.user_id,
                            fid=group_info.fid,
                            text=f"[自动添加]拒绝申诉，理由：{reason_str}",
                        )
                    ],
                )
                await AppealCache.del_appeal_id(appeal_id)
                await deal_appeal_cmd.finish("已拒绝申诉。")
            else:
                await deal_appeal_cmd.finish("拒绝申诉失败。")
        elif cmd in ["通过申诉", "通过"]:
            result = await client.handle_unblock_appeals(group_info.fid, appeal_ids=[appeal_id], refuse=False)
            if result:
                await Associated.add_data(
                    user_info,
                    group_info,
                    text_data=[
                        TextData(
                            uploader_id=event.user_id,
                            fid=group_info.fid,
                            text=f"[自动添加]通过申诉，理由：{reason_str}",
                        )
                    ],
                )
                await AppealCache.del_appeal_id(appeal_id)
                await deal_appeal_cmd.finish("已通过申诉。")
            else:
                await deal_appeal_cmd.finish("通过申诉失败。")
