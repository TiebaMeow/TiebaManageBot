from arclet.alconna import Alconna, Args, MultiVar
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageSegment,
    permission,
)
from nonebot.rule import Rule
from nonebot_plugin_alconna import (
    AlconnaMatcher,
    AlconnaQuery,
    Field,
    Match,
    Query,
    UniMessage,
    on_alconna,
)

from src.addons.interface.crud.user_posts import get_user_stats
from src.common.cache import ClientCache, get_tieba_name, tieba_uid2user_info_cached
from src.db.crud import get_group
from src.utils import (
    handle_tieba_uid,
    rule_signed,
    text_to_image,
)

from .producer import DBProducer

check_posts_plus_alc = Alconna(
    "check_posts_plus",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入待查询用户贴吧ID。")],
    Args["tieba_names", MultiVar(str, "*")],
)

check_posts_plus_cmd = on_alconna(
    command=check_posts_plus_alc,
    aliases={"查发言s", "查发贴s"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=6,
    block=True,
)


@check_posts_plus_cmd.handle()
async def handle_check_posts_plus(
    event: GroupMessageEvent,
    tieba_id_str: Match[str],
    tieba_names: Query[tuple[str, ...]] = AlconnaQuery("tieba_names", ()),
):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await check_posts_plus_cmd.finish("贴吧ID格式错误，请检查输入。")

    group_info = await get_group(event.group_id)

    client = await ClientCache.get_client()
    fids = []
    if tieba_names.result:
        for tieba_name in tieba_names.result:
            if tieba_name == "本吧":
                fids.append(group_info.fid)
            else:
                tieba_name = tieba_name.removesuffix("吧")
                if fid := await client.get_fid(tieba_name):
                    fids.append(fid)

    user_info = await tieba_uid2user_info_cached(client, tieba_id)
    if user_info.user_id == 0:
        await check_posts_plus_cmd.finish("用户信息获取失败，请稍后重试。")

    producer = DBProducer(user_info, fids)
    await consumer(producer, check_posts_plus_cmd)


async def consumer(producer: DBProducer, check_posts_cmd: type[AlconnaMatcher]):
    specific_posts = await producer.get()
    if specific_posts is None:
        if producer.fids is not None:
            await check_posts_cmd.send("未能查询到该用户在指定吧的历史发言。")
        else:
            await check_posts_cmd.send("未能查询到该用户历史发言。")
        await producer.stop()
        return
    display_pn = 1
    while True:
        next_specific_posts = await producer.get()
        specific_posts_img = MessageSegment.image(specific_posts)
        if next_specific_posts is None:
            specific_posts_suffix = MessageSegment.text(f"第 {display_pn} 页，已无更多内容，结束查询。")
            await check_posts_cmd.send(specific_posts_img + specific_posts_suffix)
            return
        specific_posts_suffix = MessageSegment.text(f"第 {display_pn} 页，继续查询请输入“下一页”。")
        next_input = await check_posts_cmd.prompt(specific_posts_img + specific_posts_suffix, timeout=60, block=False)
        if next_input != UniMessage("下一页"):
            await producer.stop()
            await check_posts_cmd.send("已结束查询。")
            return
        specific_posts = next_specific_posts
        display_pn += 1


post_stats_alc = Alconna(
    "post_stats",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入待查询用户贴吧ID。")],
)

post_stats_cmd = on_alconna(
    command=post_stats_alc,
    aliases={"发言统计"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=6,
    block=True,
)


@post_stats_cmd.handle()
async def handle_post_stats(
    tieba_id_str: Match[str],
):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await post_stats_cmd.finish("贴吧ID格式错误，请检查输入。")

    client = await ClientCache.get_client()
    user_info = await tieba_uid2user_info_cached(client, tieba_id)

    if user_info.user_id == 0:
        await post_stats_cmd.finish("未能获取用户信息。")

    stats = await get_user_stats(user_info.user_id)
    if not stats:
        await post_stats_cmd.finish("数据库中不存在该用户发言记录。")

    stats.sort(key=lambda x: x.thread_count + x.post_count + x.comment_count, reverse=True)

    lines = [f"用户 {user_info.user_name} ({user_info.user_id}) 的发言统计："]
    for i, s in enumerate(stats, 1):
        tieba_name = await get_tieba_name(s.fid) or str(s.fid)
        total = s.thread_count + s.post_count + s.comment_count
        lines.append(
            f"#{i} {tieba_name}: {total}条"
            f" （主题贴：{s.thread_count} / 回复：{s.post_count} / 楼中楼：{s.comment_count}）"
        )

    content = "\n".join(lines)
    header = f"用户 {user_info.user_name} ({user_info.user_id}) 发言统计"
    img = await text_to_image(content, header=header, wrap=False)
    await post_stats_cmd.finish(MessageSegment.image(img))
