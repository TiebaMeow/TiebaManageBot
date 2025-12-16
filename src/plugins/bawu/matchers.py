from typing import Literal

from arclet.alconna import Alconna, Args, Arparma, MultiVar
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.rule import Rule
from nonebot_plugin_alconna import AlconnaQuery, Field, Match, Query, on_alconna

from src.common import Client
from src.db.crud import get_group
from src.utils import (
    handle_thread_url,
    handle_thread_urls,
    handle_tieba_uids,
    require_master_BDUSS,
    require_slave_BDUSS,
    rule_admin,
    rule_master,
    rule_moderator,
    rule_signed,
)

from . import service

del_thread_alc = Alconna(
    "del_thread",
    Args[
        "thread_urls",
        MultiVar(str, "+"),
        Field(completion=lambda: "请输入一个或多个贴子链接，以空格分隔，最多支持30个链接。"),
    ],
)

del_thread_cmd = on_alconna(
    command=del_thread_alc,
    aliases={"删贴", "删帖"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_thread_cmd.handle()
@require_slave_BDUSS
async def del_thread_handle(
    event: GroupMessageEvent,
    thread_urls: Query[tuple[str, ...]] = AlconnaQuery("thread_urls", ()),
):
    group_info = await get_group(event.group_id)
    tids = handle_thread_urls(thread_urls.result)
    if 0 in tids:
        await del_thread_cmd.finish("参数中包含无法解析的链接，请检查输入。")

    async with Client(group_info.slave_bduss, try_ws=True) as client:
        succeeded, failed = await service.delete_threads(client, group_info, tids, event.user_id)

    succeeded_str = f"\n成功删除{len(succeeded)}个贴子。" if succeeded else ""
    failed_str = f"\n以下贴子删除失败：{', '.join('tid=' + str(tid) for tid in failed)}" if failed else ""
    await del_thread_cmd.finish(f"删贴操作完成。{succeeded_str}{failed_str}")


del_post_alc = Alconna(
    "del_post",
    Args["thread_url", str, Field(completion=lambda: "请输入贴子链接。")],
    Args["floors", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个楼层，以空格分隔。")],
)

del_post_cmd = on_alconna(
    command=del_post_alc,
    aliases={"删楼"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@del_post_cmd.handle()
@require_slave_BDUSS
async def del_post_handle(
    event: GroupMessageEvent,
    thread_url: Match[str],
    floors: Query[tuple[str, ...]] = AlconnaQuery("floors", ()),
):
    group_info = await get_group(event.group_id)
    tid = handle_thread_url(thread_url.result)
    if tid == 0:
        await del_post_cmd.finish("参数中包含无法解析的链接，请检查输入。")

    async with Client(group_info.slave_bduss, try_ws=True) as client:
        succeeded, failed, error = await service.delete_posts(
            client, group_info, tid, list(floors.result), event.user_id
        )

    if error:
        await del_post_cmd.finish(error)

    succeeded_str = f"\n成功删除{len(succeeded)}个回贴。" if succeeded else ""
    failed_str = f"\n以下楼层删除失败：{', '.join('post_id=' + str(pid) for pid in failed)}" if failed else ""
    await del_post_cmd.finish(f"删楼操作完成。{succeeded_str}{failed_str}")


blacklist_alc = Alconna(
    "blacklist",
    Args["user_ids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

blacklist_cmd = on_alconna(
    command=blacklist_alc,
    aliases={"拉黑", "取消拉黑"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@blacklist_cmd.handle()
@require_master_BDUSS
async def blacklist_handle(
    event: GroupMessageEvent, args: Arparma, user_ids: Query[tuple[str, ...]] = AlconnaQuery("user_ids", ())
):
    group_info = await get_group(event.group_id)
    cmd = args.context["$shortcut.regex_match"].group()[1:]
    is_blacklist = cmd == "拉黑"
    uids = await handle_tieba_uids(user_ids.result)
    if 0 in uids:
        await blacklist_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    async with Client(group_info.master_bduss, try_ws=True) as client:
        succeeded, failed = await service.blacklist_users(client, group_info, uids, event.user_id, is_blacklist)

    succeeded_str = f"\n成功{cmd}{len(succeeded)}个用户。" if succeeded else ""
    failed_str = f"\n以下用户{cmd}失败：{', '.join('tieba_uid=' + str(uid) for uid in failed)}" if failed else ""
    await blacklist_cmd.finish(f"{cmd}操作完成。{succeeded_str}{failed_str}")


ban_alc = Alconna(
    "ban",
    Args["days", Literal["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"], "1"],
    Args["user_ids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

ban_cmd = on_alconna(
    command=ban_alc,
    aliases={"封禁"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@ban_cmd.handle()
@require_slave_BDUSS
async def ban_handle(
    event: GroupMessageEvent,
    days: Match[Literal["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]],
    user_ids: Query[tuple[str, ...]] = AlconnaQuery("user_ids", ()),
):
    days_int = int(days.result)
    group_info = await get_group(event.group_id)
    uids = await handle_tieba_uids(user_ids.result)
    if 0 in uids:
        await ban_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    async with Client(group_info.slave_bduss, try_ws=True) as client:
        succeeded, failed = await service.ban_users(client, group_info, uids, days_int, event.user_id)

    succeeded_str = f"\n成功为{len(succeeded)}名用户添加{days_int}天封禁。" if succeeded else ""
    failed_str = f"\n以下用户封禁失败：{', '.join('tieba_uid=' + str(uid) for uid in failed)}" if failed else ""
    await ban_cmd.finish(f"封禁操作完成。{succeeded_str}{failed_str}")


unban_alc = Alconna(
    "unban",
    Args["user_ids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

unban_cmd = on_alconna(
    command=unban_alc,
    aliases={"解封"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@unban_cmd.handle()
@require_slave_BDUSS
async def unban_handle(event: GroupMessageEvent, user_ids: Query[tuple[str, ...]] = AlconnaQuery("user_ids", ())):
    group_info = await get_group(event.group_id)
    uids = await handle_tieba_uids(user_ids.result)
    if 0 in uids:
        await unban_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    async with Client(group_info.slave_bduss, try_ws=True) as client:
        succeeded, failed = await service.unban_users(client, group_info, uids, event.user_id)

    succeeded_str = f"\n成功为{len(succeeded)}个用户解除封禁。" if succeeded else ""
    failed_str = f"\n以下用户解封失败：{', '.join('tieba_uid=' + str(uid) for uid in failed)}" if failed else ""
    await unban_cmd.finish(f"解封操作完成。{succeeded_str}{failed_str}")


good_alc = Alconna(
    "good",
    Args["thread_url", str, Field(completion=lambda: "请输入贴子链接。")],
)

good_cmd = on_alconna(
    command=good_alc,
    aliases={"加精", "取消加精", "置顶", "取消置顶", "会员置顶", "取消会员置顶", "推荐上首页"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@good_cmd.handle()
@require_master_BDUSS
async def good_handle(event: GroupMessageEvent, thread_url: Match[str], args: Arparma):
    cmd = args.context["$shortcut.regex_match"].group()[1:]
    group_info = await get_group(event.group_id)
    tid = handle_thread_url(thread_url.result)
    if tid is None:
        await good_cmd.finish("无法解析链接，请检查输入。")

    async with Client(group_info.master_bduss, try_ws=True) as client:
        success, msg = await service.thread_action(client, group_info, tid, cmd)

    await good_cmd.finish(msg)


move_alc = Alconna(
    "move",
    Args["thread_url", str, Field(completion=lambda: "请输入贴子链接。")],
    Args[
        "tab_name",
        MultiVar(str, "+"),
        Field(
            completion=lambda: (
                "若原贴位于默认分区，请输入目标分区名称。"
                "若原贴位于非默认分区，请输入原贴分区名称与目标分区名称，以空格分隔。"
            )
        ),
    ],
)

move_cmd = on_alconna(
    command=move_alc,
    aliases={"移贴", "移帖"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@move_cmd.handle()
@require_master_BDUSS
async def move_handle(
    event: GroupMessageEvent, thread_url: Match[str], tab_name: Query[tuple[str, ...]] = AlconnaQuery("tab_name", ())
):
    group_info = await get_group(event.group_id)
    tid = handle_thread_url(thread_url.result)
    if tid is None:
        await move_cmd.finish("无法解析链接，请检查输入。")

    async with Client(group_info.master_bduss, try_ws=True) as client:
        success, msg = await service.move_thread(client, group_info, tid, tab_name.result)

    await move_cmd.finish(msg)
