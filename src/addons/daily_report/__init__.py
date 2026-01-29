from __future__ import annotations

import base64

from nonebot import get_bot
from nonebot.plugin import PluginMetadata
from nonebot_plugin_apscheduler import scheduler

from logger import log
from src.db.crud import get_all_groups

from . import matchers as matchers
from .service import REPORT_SUB_KEY, build_daily_report

__all__ = ["matchers"]

__plugin_meta__ = PluginMetadata(
    name="daily_report",
    description="吧内日报订阅",
    usage="",
)


@scheduler.scheduled_job("cron", day="*", hour=0, minute=0, second=0)
async def send_daily_report() -> None:
    group_infos = await get_all_groups()
    if not group_infos:
        return

    bot = get_bot()
    for group_info in group_infos:
        if not group_info.group_args.get(REPORT_SUB_KEY, False):
            continue
        try:
            header, images = await build_daily_report(group_info)
            messages = [{"type": "text", "data": {"text": header}}]
            for img in images:
                img_b64 = base64.b64encode(img).decode()
                messages.append({"type": "image", "data": {"file": f"base64://{img_b64}"}})
            await bot.call_api("send_group_msg", group_id=group_info.group_id, message=messages)
        except Exception as exc:
            log.error(f"Failed to send daily report for fid {group_info.fid}: {exc}")
