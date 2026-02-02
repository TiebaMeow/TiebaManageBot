from arclet.alconna import Alconna, Args
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, permission
from nonebot.rule import Rule
from nonebot_plugin_alconna import Field, Match, on_alconna

from src.db.crud import get_group
from src.utils import (
    handle_thread_url,
    require_slave_bduss,
    rule_moderator,
    rule_signed,
)

from . import service

# 1. 删锁/保护/热门帖
force_del_alc = Alconna(
    "force_del",
    Args["thread_url", str, Field(completion=lambda: "请输入贴子链接")],
)

force_del_cmd = on_alconna(
    command=force_del_alc,
    aliases={"删锁帖", "删保护帖", "删热门帖"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@force_del_cmd.handle()
@require_slave_bduss
async def force_del_handle(bot: Bot, event: GroupMessageEvent, thread_url: Match[str]):
    group_info = await get_group(event.group_id)
    tid = handle_thread_url(thread_url.result)

    if tid == 0:
        await force_del_cmd.finish("无效的贴子链接。")

    if err_msg := await service.check_thread_status(group_info, tid):
        await force_del_cmd.finish(f"删帖任务添加失败: {err_msg}")

    msg = await service.add_task(group_info, event.message_id, bot_id=bot.self_id, tid=tid, operator_id=event.user_id)
    await force_del_cmd.finish(msg)


# 2. 取消任务
cancel_force_del_alc = Alconna(
    "cancel_force_del",
    Args["thread_url", str, Field(completion=lambda: "请输入贴子链接")],
)

cancel_force_del_cmd = on_alconna(
    command=cancel_force_del_alc,
    aliases={"取消删锁帖", "取消删保护帖", "取消删热门帖"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@cancel_force_del_cmd.handle()
async def cancel_force_del_handle(thread_url: Match[str]):
    tid = handle_thread_url(thread_url.result)
    if tid == 0:
        await cancel_force_del_cmd.finish("无效的贴子链接。")

    msg = await service.cancel_task(tid)
    await cancel_force_del_cmd.finish(msg)


# 3. 查询任务
query_force_del_alc = Alconna(
    "query_force_del",
    Args["thread_url", str, Field(completion=lambda: "请输入贴子链接")],
)

query_force_del_cmd = on_alconna(
    command=query_force_del_alc,
    aliases={"查询删锁帖", "查询删保护帖", "查询删热门帖"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@query_force_del_cmd.handle()
async def query_force_del_handle(thread_url: Match[str]):
    tid = handle_thread_url(thread_url.result)
    status = service.get_task_info(tid)
    await query_force_del_cmd.finish(f"贴子 {tid} 的状态：{status}")
