from typing import Literal

from aiotieba import PostSortType
from arclet.alconna import Alconna, Args, Arparma, MultiVar
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_alconna import AlconnaQuery, Field, Match, Query, on_alconna

from logger import log
from src.common import Client
from src.db import Associated, GroupCache, TextDataModel
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

__plugin_meta__ = PluginMetadata(
    name="bawu",
    description="常规吧务管理项",
    usage="",
)

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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tids = handle_thread_urls(thread_urls.result)
    if 0 in tids:
        await del_thread_cmd.finish("参数中包含无法解析的链接，请检查输入。")
    succeeded = []
    failed = []
    async with Client(group_info.slave_bduss, try_ws=True) as client:
        for tid in tids:
            posts = await client.get_posts(tid)
            user_info = await client.get_user_info(posts.thread.author_id)
            if await client.del_thread(group_info.fid, tid):
                succeeded.append(tid)
                await Associated.add_data(
                    user_info,
                    group_info,
                    text_data=[
                        TextDataModel(
                            uploader_id=event.user_id,
                            fid=group_info.fid,
                            text=f"[自动添加]删贴\n标题：{posts.thread.title}\n{posts.thread.text}",
                        )
                    ],
                )
            else:
                failed.append(tid)
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tid = handle_thread_url(thread_url.result)
    if tid == 0:
        await del_post_cmd.finish("参数中包含无法解析的链接，请检查输入。")
    succeeded = []
    failed = []
    floor_list = []
    async with Client(group_info.slave_bduss, try_ws=True) as client:
        thread_info = await client.get_posts(tid, pn=1, rn=10, sort=PostSortType.DESC)
        if not thread_info.objs:
            await del_post_cmd.finish("获取贴子信息失败，请检查输入。")
        floor_num = thread_info.objs[0].floor
        for floor in floors.result:
            if not floor.isdigit() or int(floor) > floor_num or int(floor) < 2:
                failed.append(floor)
                continue
            floor_list.append(int(floor))
        if not floor_list:
            await del_post_cmd.finish("没有有效的楼层输入，请检查输入。")
        for pni in range(floor_num // 30 + 1):
            batch_posts = await client.get_posts(tid, pn=pni + 1, rn=30, sort=PostSortType.ASC)
            for post in batch_posts.objs:
                if post.floor in floor_list:
                    if not await client.del_post(group_info.fid, post.tid, post.pid):
                        failed.append(post.floor)
                        continue
                    succeeded.append(post.pid)
                    user_info = await client.get_user_info(post.author_id)
                    await Associated.add_data(
                        user_info,
                        group_info,
                        text_data=[
                            TextDataModel(
                                uploader_id=event.user_id,
                                fid=group_info.fid,
                                text=f"[自动添加]删回复\n原贴：{post.tid}\n内容：{post.text}",
                            )
                        ],
                    )
    succeeded_str = f"\n成功删除{len(succeeded)}个回贴。" if succeeded else ""
    failed_str = f"\n以下楼层删除失败：{', '.join('post_id=' + str(pid) for pid in failed)}" if failed else ""
    await del_post_cmd.finish(f"删楼操作完成。{succeeded_str}{failed_str}")


blacklist_alc = Alconna(
    "blacklist",
    Args["user_ids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

blacklist_cmd = on_alconna(
    command=blacklist_alc,
    aliases={"拉黑"},
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
async def blacklist_handle(event: GroupMessageEvent, user_ids: Query[tuple[str, ...]] = AlconnaQuery("user_ids", ())):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    uids = await handle_tieba_uids(user_ids.result)
    if 0 in uids:
        await blacklist_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    succeeded = []
    failed = []
    async with Client(group_info.master_bduss, try_ws=True) as client:
        for tieba_uid in uids:
            user_info = await client.tieba_uid2user_info(tieba_uid)
            if await client.add_bawu_blacklist(group_info.fid, user_info.user_id):
                succeeded.append(tieba_uid)
                await Associated.add_data(
                    user_info,
                    group_info,
                    text_data=[TextDataModel(uploader_id=event.user_id, fid=group_info.fid, text="[自动添加]拉黑")],
                )
            else:
                failed.append(tieba_uid)
    succeeded_str = f"\n成功拉黑{len(succeeded)}个用户。" if succeeded else ""
    failed_str = f"\n以下用户拉黑失败：{', '.join('tieba_uid=' + str(uid) for uid in failed)}" if failed else ""
    await blacklist_cmd.finish(f"拉黑操作完成。{succeeded_str}{failed_str}")


unblacklist_alc = Alconna(
    "unblacklist",
    Args["user_ids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

unblacklist_cmd = on_alconna(
    command=unblacklist_alc,
    aliases={"取消拉黑"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@unblacklist_cmd.handle()
@require_master_BDUSS
async def unblacklist_handle(event: GroupMessageEvent, user_ids: Query[tuple[str, ...]] = AlconnaQuery("user_ids", ())):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    uids = await handle_tieba_uids(user_ids.result)
    if 0 in uids:
        await unblacklist_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    succeeded = []
    failed = []
    async with Client(group_info.master_bduss, try_ws=True) as client:
        for tieba_uid in uids:
            user_info = await client.tieba_uid2user_info(tieba_uid)
            if await client.del_bawu_blacklist(group_info.fid, user_info.user_id):
                succeeded.append(tieba_uid)
                await Associated.add_data(
                    user_info,
                    group_info,
                    text_data=[TextDataModel(uploader_id=event.user_id, fid=group_info.fid, text="[自动添加]取消拉黑")],
                )
            else:
                failed.append(tieba_uid)
    succeeded_str = f"\n成功取消拉黑{len(succeeded)}个用户。" if succeeded else ""
    failed_str = f"\n以下用户取消拉黑失败：{', '.join('tieba_uid=' + str(uid) for uid in failed)}" if failed else ""
    await unblacklist_cmd.finish(f"取消拉黑操作完成。{succeeded_str}{failed_str}")


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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    uids = await handle_tieba_uids(user_ids.result)
    if 0 in uids:
        await ban_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    succeeded = []
    failed = []
    async with Client(group_info.slave_bduss, try_ws=True) as client:
        for tieba_uid in uids:
            user_info = await client.tieba_uid2user_info(tieba_uid)
            if await client.block(group_info.fid, user_info.user_id, day=days_int):
                succeeded.append(tieba_uid)
                await Associated.add_data(
                    user_info,
                    group_info,
                    text_data=[
                        TextDataModel(
                            uploader_id=event.user_id, fid=group_info.fid, text=f"[自动添加]封禁\n封禁天数：{days}"
                        )
                    ],
                )
            else:
                failed.append(tieba_uid)
    succeeded_str = f"\n成功为{len(succeeded)}名用户添加{days}天封禁。" if succeeded else ""
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    uids = await handle_tieba_uids(user_ids.result)
    if 0 in uids:
        await unban_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    succeeded = []
    failed = []
    async with Client(group_info.slave_bduss, try_ws=True) as client:
        for tieba_uid in uids:
            user_info = await client.tieba_uid2user_info(tieba_uid)
            if await client.unblock(group_info.fid, user_info.user_id):
                succeeded.append(tieba_uid)
                await Associated.add_data(
                    user_info,
                    group_info,
                    text_data=[TextDataModel(uploader_id=event.user_id, fid=group_info.fid, text="[自动添加]解除封禁")],
                )
            else:
                failed.append(tieba_uid)
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tid = handle_thread_url(thread_url.result)
    if tid is None:
        await good_cmd.finish("无法解析链接，请检查输入。")
    async with Client(group_info.master_bduss, try_ws=True) as client:
        match cmd:
            case "加精":
                if await client.good(group_info.fid, tid):
                    await good_cmd.finish("加精成功。")
                else:
                    await good_cmd.finish("加精失败。")
            case "取消加精":
                if await client.ungood(group_info.fid, tid):
                    await good_cmd.finish("已取消加精。")
                else:
                    await good_cmd.finish("取消加精失败。")
            case "置顶":
                if await client.top(group_info.fid, tid):
                    await good_cmd.finish("已置顶。")
                else:
                    await good_cmd.finish("置顶失败。")
            case "取消置顶":
                if await client.untop(group_info.fid, tid):
                    await good_cmd.finish("已取消置顶。")
                else:
                    await good_cmd.finish("取消置顶失败。")
            case "会员置顶":
                if await client.top(group_info.fid, tid, is_vip=True):
                    await good_cmd.finish("已会员置顶。")
                else:
                    await good_cmd.finish("会员置顶失败。")
            case "取消会员置顶":
                if await client.untop(group_info.fid, tid, is_vip=True):
                    await good_cmd.finish("已取消会员置顶。")
                else:
                    await good_cmd.finish("取消会员置顶失败。")
            case "推荐上首页":
                times_left = await client.get_recom_status(group_info.fid)
                if times_left.total_recom_num - times_left.used_recom_num <= 0:
                    await good_cmd.finish("推荐上首页失败，本月推荐配额已用完。")
                if await client.recommend(group_info.fid, tid):
                    await good_cmd.finish(
                        f"已推荐上首页，本月配额使用情况：\
                        {times_left.total_recom_num - times_left.used_recom_num}/{times_left.total_recom_num}"
                    )
                else:
                    await good_cmd.finish("推荐上首页失败。")
            case _:
                await good_cmd.finish("未知命令，命令与参数间请通过空格分隔。")


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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tid = handle_thread_url(thread_url.result)
    if tid is None:
        await move_cmd.finish("无法解析链接，请检查输入。")
    async with Client(group_info.master_bduss, try_ws=True) as client:
        tab_info = await client.get_tab_map(group_info.fname)
        tab_map = tab_info.map
        for name in tab_name.result:
            if name not in tab_map:
                await move_cmd.finish("分区名称错误，请检查输入。")
        from_tab_id = 0 if len(tab_name.result) == 1 else tab_map.get(tab_name.result[0], 0)
        to_tab_id = tab_map.get(tab_name.result[-1], 0)
        if await client.move(group_info.fid, tid, to_tab_id=to_tab_id, from_tab_id=from_tab_id):
            await move_cmd.finish("移贴成功。")
        else:
            await move_cmd.finish("移贴失败。")
