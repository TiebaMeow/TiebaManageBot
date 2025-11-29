import asyncio
import operator
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

import httpx
from aiotieba import ReqUInfo
from aiotieba.enums import PostSortType
from arclet.alconna import Alconna, Args, MultiVar
from bs4 import BeautifulSoup
from nonebot import get_driver, get_plugin_config, on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageSegment,
    permission,
)
from nonebot.message import handle_event
from nonebot.params import Received
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot_plugin_alconna import (
    AlconnaMatcher,
    AlconnaQuery,
    Field,
    Match,
    Query,
    UniMessage,
    on_alconna,
)

from logger import log
from src.common import Client, get_user_posts_cached, get_user_threads_cached
from src.db import Associated, GroupCache, ImageUtils, TextDataModel, TiebaNameCache
from src.utils import (
    handle_post_url,
    handle_thread_url,
    handle_tieba_uid,
    render_post_card,
    render_thread_card,
    require_slave_BDUSS,
    require_STOKEN,
    rule_moderator,
    rule_signed,
    text_to_image,
)

from .config import Config
from .producer import Producer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiotieba.api.get_user_contents._classdef import UserPostss, UserThreads


__plugin_meta__ = PluginMetadata(
    name="info",
    description="信息查询与导入",
    usage="",
    config=Config,
)

plugin_config = get_plugin_config(Config)

checkout_alc = Alconna(
    "checkout",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入待查询用户贴吧ID。")],
)

checkout_cmd = on_alconna(
    command=checkout_alc,
    aliases={"查成分"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=6,
    block=True,
)


@checkout_cmd.handle()
@require_slave_BDUSS
async def checkout_handle(event: GroupMessageEvent, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await checkout_cmd.finish("贴吧ID格式错误，请检查输入。")
    await checkout_cmd.send("正在查询...")
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    async with Client(group_info.slave_bduss, try_ws=True) as client:
        user_info = await client.tieba_uid2user_info(tieba_id)
        nick_name_old_info = await client.get_user_info(user_info.user_id, require=ReqUInfo.BASIC)
        nick_name_old = nick_name_old_info.nick_name_old
        user_tieba = await client.get_follow_forums(user_info.user_id)
        if user_tieba.objs:
            user_tieba = [
                {"tieba_name": forum.fname, "experience": forum.exp, "level": forum.level} for forum in user_tieba.objs
            ]
        else:
            try:
                async with httpx.AsyncClient(verify=False, timeout=5) as session:
                    resp = await session.get(
                        f"https://tb.anova.me/getLevel?fname={quote_plus(plugin_config.checkout_tieba)}&uid={tieba_id}"
                    )
                    resp.raise_for_status()
                    resp_json = resp.json()
                user_tieba = [
                    {
                        "tieba_name": item["fname"],
                        "experience": item["exp"],
                        "level": item["level"],
                    }
                    for item in resp_json.get("result", [])
                ]
            except Exception:
                user_tieba = []

        user_posts_count = {}

        tasks = [get_user_threads_cached(client, user_info.user_id, page) for page in range(1, 51)]
        results_t: Sequence[UserThreads] = await asyncio.gather(*tasks, return_exceptions=False)
        for result in results_t:
            if result and result.objs:
                for thread in result.objs:
                    if thread.fid in user_posts_count:
                        user_posts_count[thread.fid] += 1
                    else:
                        user_posts_count[thread.fid] = 1

        tasks = [get_user_posts_cached(client, user_info.user_id, page, rn=50) for page in range(1, 51)]
        results_p: Sequence[UserPostss] = await asyncio.gather(*tasks, return_exceptions=False)
        for result in results_p:
            if result and result.objs:
                for post in result.objs:
                    if post.fid in user_posts_count:
                        user_posts_count[post.fid] += 1
                    else:
                        user_posts_count[post.fid] = 1
        user_posts_count = sorted(user_posts_count.items(), key=operator.itemgetter(1), reverse=True)
        user_posts_count = user_posts_count[:30]
        user_posts_count = [
            {"tieba_name": str(await TiebaNameCache.get(item[0])), "count": item[1]} for item in user_posts_count
        ]

    user_posts_count_str = "\n".join([f"  - {item['tieba_name']}：{item['count']}" for item in user_posts_count])
    user_tieba_str = "\n".join([
        f"  - {forum['tieba_name']}：{forum['experience']}经验值，等级{forum['level']}" for forum in user_tieba
    ])
    user_info_str = (
        f"昵称：{user_info.nick_name_new}\n"
        f"旧版昵称：{nick_name_old}\n"
        f"用户名：{user_info.user_name}\n"
        f"贴吧ID：{user_info.tieba_uid}\n"
        f"user_id：{user_info.user_id}\n"
        f"portrait：{user_info.portrait}\n"
        f"吧龄：{user_info.age}年"
    )
    base_content = f"基本信息：\n{user_info_str}"
    image_content = await text_to_image(
        f"{user_info.tieba_uid}关注的贴吧：\n{user_tieba_str}\n\n近期发贴的吧：\n{user_posts_count_str}"
    )

    await checkout_cmd.finish(message=MessageSegment.text(base_content) + MessageSegment.image(image_content))


async def get_all_posts(check_posts_cmd: AlconnaMatcher, tieba_id: int, client: Client):
    user_info = await client.tieba_uid2user_info(tieba_id)
    user_posts = await get_user_posts_cached(client, user_info.user_id, pn=1, rn=50)
    if not user_posts.objs:
        await check_posts_cmd.finish("未能查询到该用户发言，可能该用户已隐藏发言。")
    user_posts = [
        {
            "tieba_name": str(await TiebaNameCache.get(post.fid)) + "吧",
            "post_content": "\n".join([("  - " + obj.contents.text) for obj in post.objs]),
        }
        for post in user_posts.objs
    ]
    user_posts_str = "\n".join([f"{post['tieba_name']}：\n{post['post_content']}" for post in user_posts])
    page = 2
    while True:
        next_posts = await get_user_posts_cached(client, user_info.user_id, pn=page, rn=50)
        if not next_posts.objs:
            img = await text_to_image(user_posts_str)
            user_posts_img = MessageSegment.image(img)
            user_posts_suffix = MessageSegment.text("已无更多内容，结束查询。")
            await check_posts_cmd.finish(user_posts_img)
        next_posts = [
            {
                "tieba_name": str(await TiebaNameCache.get(post.fid)) + "吧",
                "post_content": "\n".join([("  - " + obj.contents.text) for obj in post.objs]),
            }
            for post in next_posts.objs
        ]
        img = await text_to_image(user_posts_str)
        user_posts_img = MessageSegment.image(img)
        user_posts_suffix = MessageSegment.text(f"第 {page - 1} 页，继续查询请输入“下一页”。")
        next_input = await check_posts_cmd.prompt(user_posts_img + user_posts_suffix, timeout=30, block=False)
        if next_input != UniMessage("下一页"):
            await check_posts_cmd.finish("已结束查询。")
        user_posts_str = "\n".join([f"{post['tieba_name']}：\n{post['post_content']}" for post in next_posts])
        page += 1


async def get_specific_posts(check_posts_cmd: AlconnaMatcher, tieba_id: int, fids: list[int], client: Client):
    user_info = await client.tieba_uid2user_info(tieba_id)
    pn = 1
    display_pn = 1
    next_specific_posts = []
    while True:
        if len(next_specific_posts) >= 20:
            slice_posts = next_specific_posts[:20]
            next_specific_posts = next_specific_posts[20:]
            slice_posts_str = "\n".join([f"{post['tieba_name']}：\n{post['post_content']}" for post in slice_posts])
            img = await text_to_image(slice_posts_str)
            slice_posts_img = MessageSegment.image(img)
            slice_posts_suffix = MessageSegment.text(f"第 {display_pn} 页，继续查询请输入“下一页”。")
            next_input = await check_posts_cmd.prompt(slice_posts_img + slice_posts_suffix, timeout=30, block=False)
            if next_input != UniMessage("下一页"):
                await check_posts_cmd.finish("已结束查询。")
                break
            display_pn += 1
            continue
        user_posts = await get_user_posts_cached(client, user_info.user_id, pn=pn, rn=50)
        if not user_posts.objs:
            if next_specific_posts:
                slice_posts_str = "\n".join([
                    f"{post['tieba_name']}：\n{post['post_content']}" for post in next_specific_posts
                ])
                img = await text_to_image(slice_posts_str)
                slice_posts_img = MessageSegment.image(img)
                slice_posts_suffix = MessageSegment.text(f"第 {display_pn} 页，已无更多内容，结束查询。")
                await check_posts_cmd.finish(slice_posts_img + slice_posts_suffix)
            else:
                await check_posts_cmd.finish("已无更多内容，结束查询。")
            break
        specific_posts = [
            {
                "tieba_name": str(await TiebaNameCache.get(post.fid)) + "吧",
                "post_content": "\n".join([("  - " + obj.contents.text) for obj in post.objs]),
            }
            for post in user_posts.objs
            if post.fid in fids
        ]
        next_specific_posts.extend(specific_posts)
        pn += 1


async def consumer(producer: Producer, check_posts_cmd: type[AlconnaMatcher]):
    specific_posts = await producer.get()
    if specific_posts is None:
        if isinstance(producer.fids[0], int):
            await check_posts_cmd.send("未能查询到该用户在指定吧的发言。")
        else:
            await check_posts_cmd.send("未能查询到该用户发言，可能该用户已隐藏发言。")
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


check_posts_alc = Alconna(
    "check_posts",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入待查询用户贴吧ID。")],
    Args["tieba_names", MultiVar(str, "*")],
)

check_posts_cmd = on_alconna(
    command=check_posts_alc,
    aliases={"查发言", "查发贴"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=6,
    block=True,
)


@check_posts_cmd.handle()
async def check_posts_handle(
    event: GroupMessageEvent,
    tieba_id_str: Match[str],
    tieba_names: Query[tuple[str, ...]] = AlconnaQuery("tieba_names", ()),
):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await check_posts_cmd.finish("贴吧ID格式错误，请检查输入。")
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    async with Client(try_ws=True) as client:
        fids = []
        if tieba_names.result:
            for tieba_name in tieba_names.result:
                if tieba_name == "本吧":
                    fids.append(group_info.fid)
                else:
                    tieba_name = tieba_name.removesuffix("吧")
                    if fid := await client.get_fid(tieba_name):
                        fids.append(fid)
            if not fids:
                await check_posts_cmd.finish("未查询到指定贴吧，请检查输入。")
        await check_posts_cmd.send("正在查询...")
        user_info = await client.tieba_uid2user_info(tieba_id)
        consumer_task = asyncio.create_task(consumer(Producer(client, user_info.user_id, fids), check_posts_cmd))
        await consumer_task
        await check_posts_cmd.finish()
        # await get_all_posts(check_posts_cmd, tieba_id, client)


add_associate_data_alc = Alconna(
    "add_data",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入用户贴吧ID。")],
)

add_associate_data_cmd = on_alconna(
    command=add_associate_data_alc,
    aliases={"添加信息"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=7,
    block=True,
)


@add_associate_data_cmd.handle()
async def add_associate_data_handle(event: GroupMessageEvent, state: T_State, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await add_associate_data_cmd.finish("贴吧ID格式错误，请检查输入。")
    async with Client(try_ws=True) as client:
        user_info = await client.tieba_uid2user_info(tieba_id)
    group_info = await GroupCache.get(event.group_id)
    state["user_info"] = user_info
    state["group_info"] = group_info
    state["text_reasons"] = []
    state["img_reasons"] = []
    await add_associate_data_cmd.send(
        f"请输入为用户 {user_info.nick_name}({user_info.tieba_uid}) 添加的关联信息。\n"
        "输入“确认”以结束，或输入“取消”取消操作。"
    )


@add_associate_data_cmd.receive("info")
async def add_associate_data_receive(state: T_State, info: GroupMessageEvent = Received("info")):
    user_info = state["user_info"]
    group_info = state["group_info"]
    text_reasons = state["text_reasons"]
    img_reasons = state["img_reasons"]
    text_buffer = []
    img_buffer = []
    msg = info.message
    if msg.only(MessageSegment.text("确认")):
        result = await Associated.add_data(user_info, group_info, text_data=text_reasons, img_data=img_reasons)
        if result:
            await add_associate_data_cmd.finish("添加成功。")
        else:
            await add_associate_data_cmd.finish("添加失败。")
    elif msg.only(MessageSegment.text("取消")):
        await add_associate_data_cmd.finish("操作已取消。")
    for seg in msg:
        if seg.type == "text":
            if img_buffer:
                img_reason = img_buffer.pop()
                img_reason.note = seg.data["text"]
                img_reasons.append(img_reason)
            else:
                text_buffer.append(seg.data["text"])
        elif seg.type == "image":
            if int(seg.data.get("file_size", 0)) > 10 * 1024 * 1024:
                await add_associate_data_cmd.reject("图片过大，请尝试取消勾选“原图”。")
            img_data = await ImageUtils.download_and_save_img(
                url=seg.data["url"], uploader_id=info.user_id, fid=group_info.fid
            )
            if img_data == -1:
                await add_associate_data_cmd.reject("图片下载失败，请尝试重新发送。")
            elif img_data == -2:
                await add_associate_data_cmd.reject("图片过大，请尝试取消勾选“原图”。")
            img_reason = img_data
            if text_buffer:
                img_reason.note = text_buffer.pop()
                img_reasons.append(img_reason)
            else:
                img_buffer.append(img_reason)
    for text in text_buffer:
        text_reasons.append(TextDataModel(uploader_id=info.user_id, fid=group_info.fid, text=text))
    for img in img_buffer:
        img_reasons.append(img)
    if len(text_reasons) >= 10:
        text_reasons = text_reasons[:10]
        await add_associate_data_cmd.send("文字数量已达上限，请确认操作。")
    if len(img_reasons) >= 10:
        img_reasons = img_reasons[:10]
        await add_associate_data_cmd.send("图片数量已达上限，请确认操作。")
    await add_associate_data_cmd.reject()


get_associate_data_alc = Alconna(
    "get_data",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入用户贴吧ID。")],
)

get_associate_data_cmd = on_alconna(
    command=get_associate_data_alc,
    aliases={"查信息"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=7,
    block=True,
)


@get_associate_data_cmd.handle()
async def get_associate_data_handle(event: GroupMessageEvent, state: T_State, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await get_associate_data_cmd.finish("贴吧ID格式错误，请检查输入。")
    async with Client(try_ws=True) as client:
        user_info = await client.tieba_uid2user_info(tieba_id)
    state["user_info"] = user_info
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    state["group_info"] = group_info
    associated_data = await Associated.get_data(user_info.user_id, group_info.fid)
    state["associated_data"] = associated_data
    if not associated_data:
        await get_associate_data_cmd.finish("未查询到该用户的关联信息。")
    text_datas = list(enumerate(associated_data.text_data, 1))
    state["text_datas"] = text_datas
    text_datas_list = [
        f"{index}. [{text_data.upload_time.strftime('%Y-%m-%d %H:%M:%S')}] {text_data.text}"
        for index, text_data in text_datas
    ]
    img_enum_start = len(text_datas_list) + 1
    img_datas = list(enumerate(associated_data.img_data, img_enum_start))
    state["img_datas"] = img_datas
    img_datas_list = []
    for index, img in img_datas:
        img_data = await ImageUtils.get_image_data(img.image_id)
        if not img_data:
            img_datas_list.append(
                MessageSegment.text(
                    f"{index}. [{img.upload_time.strftime('%Y-%m-%d %H:%M:%S')}] 图片获取失败" + f"注释：{img.note}"
                )
            )
            continue
        img_datas_list.append(
            f"{index}. [{img.upload_time.strftime('%Y-%m-%d %H:%M:%S')}]"
            + MessageSegment.image(img_data)
            + f"注释：{img.note}"
        )
    # img_datas_list = [
    #     f"{i}. [{img.upload_time.strftime('%Y-%m-%d %H:%M:%S')}]"
    #     + MessageSegment.image(f"base64://{await ImageUtils.get_image_data(img)}")
    #     + f"注释：{img.note}"
    #     for i, img in img_datas
    # ]
    await get_associate_data_cmd.send(
        f"查询到用户 {user_info.nick_name}({user_info.tieba_uid}) 的以下关联信息：\n" + "\n".join(text_datas_list)
    )
    if img_datas_list:
        img_msg = MessageSegment.text("\n").join(img_datas_list)
        await get_associate_data_cmd.send(img_msg)


@get_associate_data_cmd.receive("delete")
async def get_associate_data_delete(state: T_State, delete: GroupMessageEvent = Received("delete")):
    plain_text = delete.message.extract_plain_text()
    if not plain_text.startswith("/删除 "):
        await get_associate_data_cmd.finish()
    plain_text = plain_text[4:]
    try:
        ids = list(map(int, plain_text.split()))
    except Exception:
        await get_associate_data_cmd.reject("参数错误，请检查输入。")
    group_info = state["group_info"]
    user_info = state["user_info"]
    text_datas = state["text_datas"]
    img_datas = state["img_datas"]
    if any(_id < 0 or _id > len(text_datas) + len(img_datas) for _id in ids):
        await get_associate_data_cmd.reject("参数错误，请检查输入。")
    for delete_id in ids:
        text = next((text_data for index, text_data in text_datas if index == delete_id), None)
        if text:
            if text.uploader_id != delete.user_id and text.uploader_id != group_info.master:
                continue
            text_datas = list(filter(lambda x: x[0] != delete_id, text_datas))
            continue
        img = next((img_data for index, img_data in img_datas if index == delete_id), None)
        if img:
            if img.uploader_id != delete.user_id and img.uploader_id != group_info.master:
                continue
            img_datas = list(filter(lambda x: x[0] != delete_id, img_datas))
            continue
    text_datas = [text_data for _, text_data in text_datas]
    img_datas = [img_data for _, img_data in img_datas]
    result = await Associated.set_data(user_info.user_id, group_info.fid, text_datas, img_datas)
    if result:
        await get_associate_data_cmd.finish("删除成功。")
    else:
        await get_associate_data_cmd.finish("删除失败。")


get_last_replier_alc = Alconna(
    "get_last_replier",
    Args["thread_url", str, Field(completion=lambda: "请输入待查询贴子链接。")],
)

get_last_replier_cmd = on_alconna(
    command=get_last_replier_alc,
    aliases={"查挖坟"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed),
    permission=permission.GROUP,
    priority=7,
    block=True,
)


@get_last_replier_cmd.handle()
@require_slave_BDUSS
async def get_last_replier_handle(bot: Bot, event: GroupMessageEvent, thread_url: Match[str]):
    thread_id = handle_thread_url(thread_url.result)
    if not thread_id:
        await get_last_replier_cmd.finish("无法解析链接，请检查输入。")
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    async with Client(try_ws=True) as client:
        threads = await client.get_last_replyers(group_info.fname, rn=50)
        for thread in threads.objs:
            if thread.tid == thread_id:
                user_id = thread.last_replyer.user_id
                user_info = await client.get_user_info(user_id)
                await get_last_replier_cmd.send(
                    f"已查询到该贴最后回复者为 {user_info.nick_name}({user_info.tieba_uid})。"
                )
                driver = get_driver()
                new_event = GroupMessageEvent(
                    time=int(time.time()),
                    self_id=int(bot.self_id),
                    post_type="message",
                    sub_type="group",
                    user_id=event.user_id,
                    message_type="group",
                    message_id=0,
                    message=Message([MessageSegment.text(f"/查成分 {user_info.tieba_uid}")]),
                    original_message=Message([MessageSegment.text(f"/查成分 {user_info.tieba_uid}")]),
                    raw_message=f"/查成分 {user_info.tieba_uid}",
                    font=0,
                    sender=event.sender,
                    group_id=event.group_id,
                )
                driver.task_group.start_soon(handle_event, bot, new_event)
                await get_last_replier_cmd.finish()
        await get_last_replier_cmd.finish("未查询到该贴子。")


check_ban_alc = Alconna(
    "check_ban",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入待查询用户贴吧ID。")],
)

check_ban_cmd = on_alconna(
    command=check_ban_alc,
    aliases={"查封禁"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=6,
    block=True,
)


@check_ban_cmd.handle()
@require_STOKEN
async def check_ban_handle(event: GroupMessageEvent, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await check_ban_cmd.finish("贴吧ID格式错误，请检查输入。")
    await check_ban_cmd.send("正在查询...")
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    async with Client(group_info.slave_bduss, group_info.slave_stoken, try_ws=True) as client:
        user_info_tuid = await client.tieba_uid2user_info(tieba_id)
        user_info = await client.get_user_info(user_info_tuid.user_id, require=ReqUInfo.BASIC)
        search_value = user_info.user_name or user_info.nick_name_old
        if not search_value:
            await check_ban_cmd.finish("无法查询到该用户的用户名或旧版昵称。")
        ban_info = await client.get_bawu_userlogs(group_info.fid, search_value=search_value)
    if not ban_info.objs:
        await check_ban_cmd.finish(f"查询完毕，用户 {user_info.nick_name}({tieba_id}) 在本吧无封禁记录。")
    user_logs = []
    for info in ban_info.objs[:10]:
        ban_str = f"{info.op_time.strftime('%Y-%m-%d %H:%M')} - {info.op_type}"
        if info.op_type == "封禁":
            ban_str += f" - {info.op_duration}天"
        ban_str += f" - 操作人：{info.op_user_name}"
        user_logs.append(ban_str)
    await check_ban_cmd.send("\n".join(user_logs))


check_delete_alc = Alconna(
    "check_delete",
    Args["tieba_id_str", str, Field(completion=lambda: "请输入待查询用户贴吧ID。")],
)

check_delete_cmd = on_alconna(
    command=check_delete_alc,
    aliases={"查删贴", "查删帖"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=6,
    block=True,
)


@check_delete_cmd.handle()
@require_STOKEN
async def check_delete_handle(event: GroupMessageEvent, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await check_delete_cmd.finish("贴吧ID格式错误，请检查输入。")
    await check_delete_cmd.send("正在查询...")
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    async with Client(group_info.slave_bduss, group_info.slave_stoken, try_ws=True) as client:
        user_info_tuid = await client.tieba_uid2user_info(tieba_id)
        user_info = await client.get_user_info(user_info_tuid.user_id, require=ReqUInfo.BASIC)
        search_value = user_info.user_name or user_info.nick_name_old
        if not search_value:
            await check_delete_cmd.finish("无法查询到该用户的用户名或旧版昵称。")
        delete_info = await client.get_bawu_postlogs(group_info.fid, search_value=search_value)
    if not delete_info.objs:
        await check_delete_cmd.finish(f"查询完毕，用户 {user_info.nick_name}({tieba_id}) 在本吧无删贴记录。")
    user_logs = []
    last_info = list(filter(lambda x: x.op_time > datetime.now() - timedelta(days=30), delete_info.objs))
    if not last_info:
        await check_delete_cmd.finish(f"查询完毕，用户 {user_info.nick_name}({tieba_id}) 在本吧无30天内删贴记录。")
    last_info = last_info[:10]
    for info in last_info:
        delete_str = f"{info.op_time.strftime('%Y-%m-%d %H:%M')} - {info.op_type}"
        text = info.text or info.title
        if len(text) > 20:
            text = text[:20] + "……"
        delete_str += f" - {text}"
        delete_str += f" - 操作人：{info.op_user_name}"
        user_logs.append(delete_str)
    await check_delete_cmd.send("\n".join(user_logs))


async def has_tieba_url(event: GroupMessageEvent) -> bool:
    raw_message = event.raw_message
    if "tieba.baidu.com/p/" in raw_message and event.user_id not in plugin_config.ignore_users:
        return True
    return False


tieba_url_message = on_message(
    rule=Rule(has_tieba_url),
    permission=permission.GROUP,
    priority=14,
    block=False,
)


@tieba_url_message.handle()
async def tieba_url_message_handle(event: GroupMessageEvent):
    tid, pid = handle_post_url(event.raw_message)
    if tid and pid:
        async with Client(try_ws=True) as client:
            thread_info = await client.get_posts(tid)
            post_info = await client.get_comments(tid, pid)
            if thread_info.err or post_info.err:
                return
            img_bytes = await render_post_card(
                thread_info.thread,
                post_info.post,
                post_info.objs[:3],
            )
        await tieba_url_message.finish(MessageSegment.image(img_bytes))
    # 仅主题贴
    tid = handle_thread_url(event.raw_message)
    if not tid:
        return
    async with Client(try_ws=True) as client:
        thread_info = await client.get_posts(tid, with_comments=True)
        if thread_info.err:
            return
        thread = thread_info.thread
        posts = thread_info.objs

        # 处理包含1楼的情况
        if len(posts) > 0 and posts[0].floor == 1:
            del posts[0]
            if thread.reply_num > 0:
                thread.reply_num -= 1
        img_bytes = await render_thread_card(thread, posts[:3])
    await tieba_url_message.finish(MessageSegment.image(img_bytes))


# any_message = on_message(
#     priority=2,
#     block=True,
# )


# @any_message.handle()
# async def any_message_handle(bot: Bot, event: GroupMessageEvent):
#     pass
