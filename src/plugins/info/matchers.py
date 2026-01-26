import asyncio
from typing import TYPE_CHECKING

from arclet.alconna import Alconna, Args, MultiVar
from nonebot import get_plugin_config, on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageSegment,
    permission,
)
from nonebot.params import Received
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
from tarina import lang

from src.common.cache import ClientCache, tieba_uid2user_info_cached
from src.db import ImgDataModel, TextDataModel
from src.db.crud import (
    add_associated_data,
    download_and_save_img,
    get_associated_data,
    get_group,
    get_image_data,
)
from src.utils import (
    handle_post_url,
    handle_thread_url,
    handle_tieba_uid,
    require_slave_bduss,
    require_stoken,
    rule_moderator,
    rule_signed,
)

from . import service
from .config import Config
from .producer import Producer

if TYPE_CHECKING:
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid

    from src.db.models import GroupInfo

lang.set("alconna", "completion.node", "请继续输入以下参数：", "zh_CN")
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
async def checkout_handle(event: GroupMessageEvent, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await checkout_cmd.finish("贴吧ID格式错误，请检查输入。")
    await checkout_cmd.send("正在查询...")

    client = await ClientCache.get_bawu_client(event.group_id)
    base_content, image_content = await service.generate_checkout_msg(client, tieba_id, plugin_config.checkout_tieba)
    if not base_content:
        await checkout_cmd.finish("用户信息获取失败，请稍后重试。")

    await checkout_cmd.finish(message=MessageSegment.text(base_content) + MessageSegment.image(image_content))


async def consumer(producer: Producer, check_posts_cmd: type[AlconnaMatcher]):
    specific_posts = await producer.get()
    if specific_posts is None:
        if producer.fids is not None:
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
        if not fids:
            await check_posts_cmd.finish("未查询到指定贴吧，请检查输入。")

    user_info = await tieba_uid2user_info_cached(client, tieba_id)
    if user_info.user_id == 0:
        await check_posts_cmd.finish("用户信息获取失败，请稍后重试。")

    await check_posts_cmd.send("正在查询...")
    consumer_task = asyncio.create_task(consumer(Producer(client, user_info, fids), check_posts_cmd))
    await consumer_task

    await check_posts_cmd.finish()


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

    client = await ClientCache.get_client()
    user_info = await tieba_uid2user_info_cached(client, tieba_id)
    if user_info.user_id == 0:
        await add_associate_data_cmd.finish("用户信息获取失败，请稍后重试。")
    group_info = await get_group(event.group_id)
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
    user_info: UserInfo_TUid = state["user_info"]
    group_info: GroupInfo = state["group_info"]
    text_reasons: list[TextDataModel] = state["text_reasons"]
    img_reasons: list[ImgDataModel] = state["img_reasons"]
    text_buffer: list[str] = []
    img_buffer: list[ImgDataModel] = []
    msg = info.message
    if msg.only(MessageSegment.text("确认")):
        result = await add_associated_data(user_info, group_info, text_reasons, img_reasons)
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
            img_data = await download_and_save_img(url=seg.data["url"], uploader_id=info.user_id, fid=group_info.fid)
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
    text_reasons.extend(TextDataModel(uploader_id=info.user_id, fid=group_info.fid, text=text) for text in text_buffer)
    img_reasons.extend(list(img_buffer))
    if len(text_reasons) >= 10:
        text_reasons[:] = text_reasons[:10]
        await add_associate_data_cmd.send("文字数量已达上限，请确认操作。")
    if len(img_reasons) >= 10:
        img_reasons[:] = img_reasons[:10]
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
    group_info = await get_group(event.group_id)
    state["group_info"] = group_info

    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await get_associate_data_cmd.finish("贴吧ID格式错误，请检查输入。")

    client = await ClientCache.get_client()
    user_info = await tieba_uid2user_info_cached(client, tieba_id)
    if user_info.user_id == 0:
        await get_associate_data_cmd.finish("用户信息获取失败，请稍后重试。")
    state["user_info"] = user_info

    associated_data = await get_associated_data(user_info.user_id, group_info.fid)
    if not associated_data:
        await get_associate_data_cmd.finish("未查询到该用户的关联信息。")
    state["associated_data"] = associated_data

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
        img_data = await get_image_data(img.image_id)
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

    result = await service.delete_associated_data(user_info, group_info, ids, delete.user_id, text_datas, img_datas)
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
@require_slave_bduss
async def get_last_replier_handle(event: GroupMessageEvent, thread_url: Match[str]):
    thread_id = handle_thread_url(thread_url.result)
    if not thread_id:
        await get_last_replier_cmd.finish("无法解析链接，请检查输入。")
    group_info = await get_group(event.group_id)

    client = await ClientCache.get_client()
    user_info_dict, msg = await service.get_last_replier(client, group_info.fname, thread_id)
    if user_info_dict:
        await get_last_replier_cmd.send(msg)
        checkout_msg, checkout_img = await service.generate_checkout_msg(
            client, user_info_dict["tieba_uid"], plugin_config.checkout_tieba
        )
        await get_last_replier_cmd.finish(
            message=MessageSegment.text(checkout_msg) + MessageSegment.image(checkout_img)
        )
    else:
        await get_last_replier_cmd.finish(msg)


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
@require_stoken
async def check_ban_handle(event: GroupMessageEvent, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await check_ban_cmd.finish("贴吧ID格式错误，请检查输入。")
    await check_ban_cmd.send("正在查询...")
    group_info = await get_group(event.group_id)

    client = await ClientCache.get_stoken_client(event.group_id)
    msg, logs = await service.get_ban_logs(client, group_info.fid, tieba_id)

    if msg:
        await check_ban_cmd.finish(msg)
    await check_ban_cmd.send("\n".join(logs))


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
@require_stoken
async def check_delete_handle(event: GroupMessageEvent, tieba_id_str: Match[str]):
    tieba_id = await handle_tieba_uid(tieba_id_str.result)
    if not tieba_id:
        await check_delete_cmd.finish("贴吧ID格式错误，请检查输入。")
    await check_delete_cmd.send("正在查询...")
    group_info = await get_group(event.group_id)

    client = await ClientCache.get_stoken_client(event.group_id)
    msg, logs = await service.get_delete_logs(client, group_info.fid, tieba_id)

    if msg:
        await check_delete_cmd.finish(msg)
    await check_delete_cmd.send("\n".join(logs))


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
        client = await ClientCache.get_client()
        img_bytes = await service.get_thread_preview(client, tid, pid)
        if img_bytes:
            await tieba_url_message.finish(MessageSegment.image(img_bytes))

    # 仅主题贴
    tid = handle_thread_url(event.raw_message)
    if not tid:
        return
    client = await ClientCache.get_client()
    img_bytes = await service.get_thread_preview(client, tid)
    if img_bytes:
        await tieba_url_message.finish(MessageSegment.image(img_bytes))
