import time

from nonebot import get_bot
from nonebot.plugin import PluginMetadata
from nonebot_plugin_apscheduler import scheduler

from logger import log
from src.db.crud.group import get_all_groups

from . import matchers, service

__plugin_meta__ = PluginMetadata(
    name="scheduled",
    description="启动项与计划任务",
    usage="",
)


@scheduler.scheduled_job("cron", day="*", hour=4, minute=56, second=23)
async def autoban():
    await service.run_autoban()


@scheduler.scheduled_job("interval", minutes=10)
async def appeal_push():
    group_infos = await get_all_groups()
    for group_info in group_infos:
        notifications = await service.process_appeals_for_group(group_info)
        if not notifications:
            continue

        bot = get_bot()
        for note in notifications.auto_deny:
            await bot.call_api(
                "send_group_msg",
                group_id=note.group_id,
                message=f"由于即将超时，已自动拒绝用户{note.user_info.nick_name}({note.user_info.tieba_uid})的封禁申诉。",
            )
        for note in notifications.new_appeal:
            appeal = note.appeal
            user_info = note.user_info
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
            try:
                resp = await bot.call_api("send_group_msg", group_id=note.group_id, message=msg)
                message_id = resp["message_id"]
                await service.update_appeal_cache(note.group_id, message_id, appeal.appeal_id, user_info.user_id)
            except Exception:
                log.error(f"Failed to push appeal message to {note.group_id}")
