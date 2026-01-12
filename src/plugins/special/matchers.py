from typing import TYPE_CHECKING, Literal

from arclet.alconna import Alconna, Args, MultiVar
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, permission
from nonebot.params import Received
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot_plugin_alconna import AlconnaQuery, Field, Match, Query, on_alconna

from logger import log
from src.common.cache import ClientCache, get_tieba_name, tieba_uid2user_info_cached
from src.db.crud import associated, autoban, group, image
from src.db.models import GroupInfo, ImgDataModel, TextDataModel
from src.utils import (
    handle_tieba_uid,
    handle_tieba_uids,
    require_slave_BDUSS,
    rule_admin,
    rule_master,
    rule_moderator,
    rule_signed,
)

from . import service

if TYPE_CHECKING:
    from aiotieba.typing import UserInfo

clear_posts_alc = Alconna(
    "clear_posts",
    Args["mode", Literal["方式1", "方式2"], "方式1"],
    Args["tieba_uids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

clear_posts_cmd = on_alconna(
    command=clear_posts_alc,
    aliases={"删发言"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@clear_posts_cmd.handle()
@require_slave_BDUSS
async def clear_posts_handle(
    event: GroupMessageEvent, mode: Match[str], tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("tieba_uids", ())
):
    group_info = await group.get_group(event.group_id)

    tieba_uids = [await handle_tieba_uid(tieba_id) for tieba_id in tieba_uid_strs.result]
    if 0 in tieba_uids:
        await clear_posts_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    client = await ClientCache.get_bawu_client(group_info.group_id)
    user_infos = [await tieba_uid2user_info_cached(client, tieba_uid) for tieba_uid in tieba_uids]
    user_ids = [user_info.user_id for user_info in user_infos]
    nicknames = [user_info.nick_name for user_info in user_infos]
    if mode.result == "方式1":
        confirm = await clear_posts_cmd.prompt(
            f"即将使用方式1（遍历用户发贴历史）清理用户 {'，'.join(nicknames)} 在本吧的所有发言。\n"
            "确认请回复“确认”，取消请回复任意内容。"
        )
        if not confirm or confirm.extract_plain_text() != "确认":
            await clear_posts_cmd.finish("操作已取消。")
        await clear_posts_cmd.send("已创建清理任务。")
        for user_id in user_ids:
            if user_id == (await client.get_self_info()).user_id:
                break
            posts_deleted, threads_deleted = await service.del_posts_from_user_posts(client, group_info.fid, user_id)
            user_info = await client.get_user_info(user_id)
            await associated.add_associated_data(
                user_info,
                group_info,
                text_data=[
                    TextDataModel(uploader_id=event.user_id, fid=group_info.fid, text="[自动添加]清空发言（方式1）")
                ],
            )
            await clear_posts_cmd.send(
                f"用户 {user_info.nick_name}({user_info.tieba_uid}) 在本吧的发言清理完成，"
                f"共删除 {posts_deleted} 条回复和 {threads_deleted} 个主题贴。"
            )
    elif mode.result == "方式2":
        await clear_posts_cmd.finish("方式2暂未实现。")
    else:
        await clear_posts_cmd.finish("参数错误，请检查输入。")


add_autoban_alc = Alconna(
    "add_autoban",
    Args["tieba_uids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

add_autoban_cmd = on_alconna(
    command=add_autoban_alc,
    aliases={"循封", "添加循封"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_autoban_cmd.handle()
@require_slave_BDUSS
async def add_autoban_handle(
    event: GroupMessageEvent, state: T_State, tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("tieba_uids", ())
):
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await add_autoban_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    group_info = await group.get_group(event.group_id)
    state["group_info"] = group_info

    client = await ClientCache.get_client()
    user_infos = [await tieba_uid2user_info_cached(client, tieba_uid) for tieba_uid in tieba_uids]

    state["user_infos"] = user_infos
    state["text_reasons"] = []
    state["img_reasons"] = []
    state["pending_imgs"] = []
    current_user = user_infos[0]
    state["current_user"] = current_user

    is_banned, ban_reason = await autoban.get_ban_status(group_info.fid, current_user.user_id)
    if ban_reason is None:
        await add_autoban_cmd.send(
            f"请输入用户 {current_user.nick_name}({current_user.tieba_uid}) 的循封原因。\n"
            f"输入“确认”以结束，或输入“取消”取消后续操作。"
        )
    elif is_banned == "banned":
        await add_autoban_cmd.send(f"用户 {current_user.nick_name}({current_user.tieba_uid}) 已在循封列表中。")
        user_infos.remove(current_user)
        if not user_infos:
            await add_autoban_cmd.finish("处理完成。")
        current_user = user_infos[0]
        state["current_user"] = current_user
    elif is_banned == "unbanned":
        unban_time_str = ban_reason.unban_time.strftime("%Y-%m-%d %H:%M:%S") if ban_reason.unban_time else "未知时间"
        unban_operator_id = ban_reason.unban_operator_id
        state["text_reasons"] = ban_reason.text_reason
        state["img_reasons"] = ban_reason.img_reason
        await add_autoban_cmd.send(
            f"用户 {current_user.nick_name}({current_user.tieba_uid}) "
            f"已于 {unban_time_str} 解除循封，操作人id：{unban_operator_id}，继续操作将继承已有信息。\n"
            f"请输入循封原因，输入“确认”以结束，或输入“取消”取消操作。"
        )
    else:
        await add_autoban_cmd.send(
            f"请输入用户 {current_user.nick_name}({current_user.tieba_uid}) 的循封原因。\n"
            f"输入“确认”以结束，或输入“取消”取消后续操作。"
        )


@add_autoban_cmd.receive("input")
async def add_autoban_input(state: T_State, input_: GroupMessageEvent = Received("input")):
    group_info: GroupInfo = state["group_info"]
    user_infos: list[UserInfo] = state["user_infos"]
    current_user: UserInfo | None = state.get("current_user", None)
    if current_user is None and user_infos:
        current_user = user_infos[0]
        state["current_user"] = current_user
        is_banned, ban_reason = await autoban.get_ban_status(group_info.fid, current_user.user_id)
        if ban_reason is None:
            await add_autoban_cmd.reject(
                f"请输入用户 {current_user.nick_name}({current_user.tieba_uid}) 的循封原因。\n"
                f"输入“确认”以结束，或输入“取消”取消操作。"
            )
        elif is_banned == "banned":
            await add_autoban_cmd.send(f"用户 {current_user.nick_name}({current_user.tieba_uid}) 已在循封列表中。")
            user_infos.remove(current_user)
            if not user_infos:
                await add_autoban_cmd.finish("处理完成。")
            current_user = user_infos[0]
            state["current_user"] = current_user
        elif is_banned == "unbanned":
            unban_time_str = (
                ban_reason.unban_time.strftime("%Y-%m-%d %H:%M:%S") if ban_reason.unban_time else "未知时间"
            )
            unban_operator_id = ban_reason.unban_operator_id
            state["text_reasons"] = ban_reason.text_reason
            state["img_reasons"] = ban_reason.img_reason
            await add_autoban_cmd.reject(
                f"用户 {current_user.nick_name}({current_user.tieba_uid}) 已于 {unban_time_str} 解除循封，"
                f"操作人id：{unban_operator_id}，继续操作将继承已有信息。\n"
                f"请输入循封原因，输入“确认”以结束，或输入“取消”取消操作。"
            )
        await add_autoban_cmd.reject(
            f"请输入用户 {current_user.nick_name}({current_user.tieba_uid}) 的循封原因。\n"
            f"输入“确认”以结束，或输入“取消”取消操作。"
        )
    if current_user is None:
        await add_autoban_cmd.finish("处理完成。")

    text_reasons: list[TextDataModel] = state["text_reasons"]
    img_reasons: list[ImgDataModel] = state["img_reasons"]
    pending_imgs: list[dict] = state.setdefault("pending_imgs", [])

    msg = input_.message
    if msg.extract_plain_text() == "确认":
        state["current_user"] = None

        client = await ClientCache.get_bawu_client(group_info.group_id)
        db_success, tieba_success = await service.add_ban_and_block(
            client, group_info.fid, group_info.group_id, current_user, input_.user_id, text_reasons, img_reasons
        )

        if not db_success:
            await add_autoban_cmd.send(f"用户 {current_user.nick_name}({current_user.tieba_uid}) 添加至循封列表失败。")
        else:
            await add_autoban_cmd.send(f"已将用户 {current_user.nick_name}({current_user.tieba_uid}) 添加至循封列表。")
            await associated.add_associated_data(
                current_user,
                group_info,
                text_data=[TextDataModel(uploader_id=input_.user_id, fid=group_info.fid, text="[自动添加]循封")],
            )
            if not tieba_success:
                log.warning(
                    f"Failed to block user {current_user.nick_name}({current_user.tieba_uid}) in "
                    f"{await get_tieba_name(group_info.fid)}"
                )
                await add_autoban_cmd.send(
                    f"用户 {current_user.nick_name}({current_user.tieba_uid}) "
                    "数据库操作成功，贴吧封禁失败，请考虑手动添加封禁。"
                )

        if pending_imgs:
            new_img_reasons, failed_count = await service.process_ban_images(
                group_info.fid, input_.user_id, current_user.user_id, pending_imgs, img_reasons
            )
            if failed_count > 0:
                await add_autoban_cmd.send(f"{failed_count} 张图片下载失败，已跳过。")

        user_infos.remove(current_user)
        state["pending_imgs"] = []
        if not user_infos:
            await add_autoban_cmd.finish("处理完成。")
        else:
            current_user = user_infos[0]
            state["current_user"] = current_user
            await add_autoban_cmd.reject(
                f"请输入用户 {current_user.nick_name}({current_user.tieba_uid}) 的循封原因。\n"
                f"输入“确认”以结束，或输入“取消”取消操作。"
            )
    elif msg.extract_plain_text() == "取消":
        await add_autoban_cmd.finish("操作已取消。")

    try:
        new_text_reasons, new_pending_imgs = service.parse_ban_reason_input(msg, input_.user_id, group_info.fid)
    except ValueError as e:
        await add_autoban_cmd.reject(str(e))

    text_reasons.extend(new_text_reasons)
    pending_imgs.extend(new_pending_imgs)

    if len(text_reasons) >= 10:
        text_reasons[:] = text_reasons[:10]
        await add_autoban_cmd.send("文字数量已达上限，请确认操作。")
    if len(img_reasons) + len(pending_imgs) >= 10:
        allowed = 10 - len(img_reasons)
        if allowed < 0:
            allowed = 0
        if len(pending_imgs) > allowed:
            pending_imgs[:] = pending_imgs[:allowed]
        await add_autoban_cmd.send("图片数量已达上限，请确认操作。")
    await add_autoban_cmd.reject()


remove_autoban_alc = Alconna(
    "remove_autoban",
    Args["tieba_uids", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

remove_autoban_cmd = on_alconna(
    command=remove_autoban_alc,
    aliases={"解除循封"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@remove_autoban_cmd.handle()
@require_slave_BDUSS
async def remove_autoban_handle(
    event: GroupMessageEvent, tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("tieba_uids", ())
):
    group_info = await group.get_group(event.group_id)
    assert group_info is not None  # for pylance
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await remove_autoban_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    client = await ClientCache.get_bawu_client(group_info.group_id)
    user_infos = [await tieba_uid2user_info_cached(client, tieba_uid) for tieba_uid in tieba_uids]
    success, failure = await service.remove_autoban_users(client, group_info, event.user_id, user_infos)

    await remove_autoban_cmd.send(f"处理完成，成功解除循封 {len(success)} 人，失败 {len(failure)} 人。")
    if failure:
        failure_str = "\n".join([f"{nick_name}({tieba_uid})：{reason}" for nick_name, tieba_uid, reason in failure])
        await remove_autoban_cmd.send(f"以下用户解除循封失败：\n{failure_str}")
    await remove_autoban_cmd.finish()


delete_ban_reason_alc = Alconna(
    "delete_ban_reason",
    Args["tieba_uid_str", str, Field(completion=lambda: "请输入贴吧ID。")],
)

delete_ban_reason_cmd = on_alconna(
    command=delete_ban_reason_alc,
    aliases={"删除循封原因"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@delete_ban_reason_cmd.handle()
async def delete_ban_reason_handle(event: GroupMessageEvent, state: T_State, tieba_uid_str: Match[str]):
    group_info = await group.get_group(event.group_id)
    tieba_uid = await handle_tieba_uid(tieba_uid_str.result)
    if tieba_uid is None:
        await delete_ban_reason_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    client = await ClientCache.get_client()
    user_info = await tieba_uid2user_info_cached(client, tieba_uid)

    is_banned, ban_reason = await autoban.get_ban_status(group_info.fid, user_info.user_id)
    if is_banned == "not":
        await delete_ban_reason_cmd.finish(f"用户 {user_info.nick_name}({user_info.tieba_uid}) 不在循封列表中。")

    assert ban_reason is not None  # for pylance
    state["group_info"] = group_info
    state["user_info"] = user_info
    if not ban_reason.text_reason and not ban_reason.img_reason:
        await delete_ban_reason_cmd.finish(f"用户 {user_info.nick_name}({user_info.tieba_uid}) 的循封原因为空。")

    state["ban_reason"] = ban_reason
    text_reasons = list(enumerate(ban_reason.text_reason, start=1))
    state["text_reasons"] = list(text_reasons)
    text_reasons_list = [f"{i}. {text.text}" for i, text in text_reasons]
    img_enum_start = len(text_reasons) + 1
    img_reasons = list(enumerate(ban_reason.img_reason, start=img_enum_start))
    state["img_reasons"] = list(img_reasons)
    img_reasons_list = []

    for i, img in img_reasons:
        img_data = await image.get_image_data(img.image_id)
        if img_data is None:
            img_reasons_list.append(MessageSegment.text(f"{i}. 图片数据获取失败" + f"注释：{img.note}"))
        else:
            img_reasons_list.append(f"{i}. " + MessageSegment.image(img_data) + f"注释：{img.note}")
    await delete_ban_reason_cmd.send(
        f"用户 {user_info.nick_name}({user_info.tieba_uid}) 的循封原因：\n" + "\n".join(text_reasons_list)
    )

    if img_reasons_list:
        img_msg = MessageSegment.text("\n").join(img_reasons_list)
        await delete_ban_reason_cmd.send(img_msg)
    await delete_ban_reason_cmd.send(
        "请输入需要删除的条目序号，多个序号以空格分隔。输入“全部”以清空条目，“取消”以取消操作。"
    )


@delete_ban_reason_cmd.receive("input")
async def delete_ban_reason_input(state: T_State, input_: GroupMessageEvent = Received("input")):
    plain_text = input_.message.extract_plain_text()
    if plain_text == "取消":
        await delete_ban_reason_cmd.finish("操作已取消。")
    group_info = state["group_info"]
    user_info = state["user_info"]
    if plain_text == "全部":
        result = await autoban.update_ban_reason(group_info.fid, user_info.user_id, text_reason=[], img_reason=[])
        if result:
            await delete_ban_reason_cmd.finish("操作完成。")
        else:
            await delete_ban_reason_cmd.finish("数据库操作失败。")
    ids = plain_text.split()
    try:
        ids = list(map(int, ids))
    except Exception:
        await delete_ban_reason_cmd.reject("参数错误，请检查并重新输入。输入“取消”以取消操作。")

    text_reasons: list[tuple[int, TextDataModel]] = state["text_reasons"]
    img_reasons: list[tuple[int, ImgDataModel]] = state["img_reasons"]
    if any(_id < 0 or _id > len(text_reasons) + len(img_reasons) for _id in ids):
        await delete_ban_reason_cmd.reject("参数错误，请检查并重新输入。输入“取消”以取消操作。")

    result = await service.delete_ban_reasons(group_info.fid, user_info.user_id, ids, text_reasons, img_reasons)

    if result:
        await delete_ban_reason_cmd.finish("操作完成。")
    else:
        await delete_ban_reason_cmd.finish("数据库操作失败。")


add_ban_reason_alc = Alconna(
    "add_ban_reason",
    Args["tieba_uid_str", str, Field(completion=lambda: "请输入贴吧ID。")],
)

add_ban_reason_cmd = on_alconna(
    command=add_ban_reason_alc,
    aliases={"添加循封原因"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@add_ban_reason_cmd.handle()
async def add_ban_reason_handle(event: GroupMessageEvent, state: T_State, tieba_uid_str: Match[str]):
    group_info = await group.get_group(event.group_id)
    tieba_uid = await handle_tieba_uid(tieba_uid_str.result)
    if tieba_uid is None:
        await add_ban_reason_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    client = await ClientCache.get_client()
    user_info = await tieba_uid2user_info_cached(client, tieba_uid)
    is_banned, ban_reason = await autoban.get_ban_status(group_info.fid, user_info.user_id)
    if is_banned == "not":
        await add_ban_reason_cmd.finish(f"用户 {user_info.nick_name}({user_info.tieba_uid}) 不在循封列表中。")

    assert ban_reason is not None  # for pylance
    state["ban_reason"] = ban_reason
    state["group_info"] = group_info
    state["user_info"] = user_info
    state["text_reasons"] = ban_reason.text_reason
    state["img_reasons"] = ban_reason.img_reason
    state["pending_imgs"] = []
    await add_ban_reason_cmd.send("请输入循封或解除循封原因，输入“确认”以结束，或输入“取消”取消操作。")


@add_ban_reason_cmd.receive("input")
async def add_ban_reason_input(state: T_State, input_: GroupMessageEvent = Received("input")):
    group_info = state["group_info"]
    user_info = state["user_info"]
    text_reasons = state["text_reasons"]
    img_reasons = state["img_reasons"]
    pending_imgs = state.setdefault("pending_imgs", [])
    msg = input_.message
    if msg.extract_plain_text() == "确认":
        state["current_user"] = None
        result = await autoban.update_ban_reason(
            group_info.fid, user_info.user_id, text_reason=text_reasons, img_reason=img_reasons
        )
        if not result:
            await add_ban_reason_cmd.finish("数据库操作失败。")

        if pending_imgs:
            new_img_reasons, failed_count = await service.process_ban_images(
                group_info.fid, input_.user_id, user_info.user_id, pending_imgs, img_reasons
            )
            if failed_count > 0:
                await add_ban_reason_cmd.send(f"{failed_count} 张图片下载失败，已跳过。")

        await add_ban_reason_cmd.finish("操作完成。")
    elif msg.extract_plain_text() == "取消":
        await add_ban_reason_cmd.finish("操作已取消。")

    try:
        new_text_reasons, new_pending_imgs = service.parse_ban_reason_input(msg, input_.user_id, group_info.fid)
    except ValueError as e:
        await add_ban_reason_cmd.reject(str(e))

    text_reasons.extend(new_text_reasons)
    pending_imgs.extend(new_pending_imgs)

    if len(text_reasons) >= 10:
        text_reasons[:] = text_reasons[:10]
        await add_ban_reason_cmd.send("文字数量已达上限，请确认操作。")
    if len(img_reasons) + len(pending_imgs) >= 10:
        allowed = 10 - len(img_reasons)
        if allowed < 0:
            allowed = 0
        if len(pending_imgs) > allowed:
            pending_imgs[:] = pending_imgs[:allowed]
        await add_ban_reason_cmd.send("图片数量已达上限，请确认操作。")
    await add_ban_reason_cmd.reject()


get_ban_reason_alc = Alconna(
    "get_ban_reason",
    Args["tieba_uid_str", str, Field(completion=lambda: "请输入贴吧ID。")],
)

get_ban_reason_cmd = on_alconna(
    command=get_ban_reason_alc,
    aliases={"循封原因", "循封状态"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_moderator),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@get_ban_reason_cmd.handle()
async def get_ban_reason_handle(event: GroupMessageEvent, tieba_uid_str: Match[str]):
    group_info = await group.get_group(event.group_id)
    tieba_uid = await handle_tieba_uid(tieba_uid_str.result)
    if tieba_uid is None:
        await get_ban_reason_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")

    client = await ClientCache.get_client()
    user_info = await tieba_uid2user_info_cached(client, tieba_uid)
    is_banned, ban_reason = await autoban.get_ban_status(group_info.fid, user_info.user_id)
    if is_banned == "not":
        await get_ban_reason_cmd.finish(f"用户 {user_info.nick_name}({user_info.tieba_uid}) 不在循封列表中。")

    assert ban_reason is not None  # for pylance
    if is_banned == "unbanned":
        unban_time_str = ban_reason.unban_time.strftime("%Y-%m-%d %H:%M:%S") if ban_reason.unban_time else "未知时间"
        unban_operator_id = ban_reason.unban_operator_id
        await get_ban_reason_cmd.send(
            f"用户 {user_info.nick_name}({user_info.tieba_uid}) 已于 {unban_time_str} 解除循封，"
            f"操作人id：{unban_operator_id}。"
        )
    text_reasons = list(enumerate(ban_reason.text_reason, start=1))
    text_reasons_list = [f"{i}. {text.text}" for i, text in text_reasons]
    img_enum_start = len(text_reasons) + 1
    img_reasons = list(enumerate(ban_reason.img_reason, start=img_enum_start))
    img_reasons_list = []
    for i, img in img_reasons:
        img_data = await image.get_image_data(img.image_id)
        if img_data is None:
            img_reasons_list.append(MessageSegment.text(f"{i}. 图片数据获取失败") + f"注释：{img.note}")
        else:
            img_reasons_list.append(f"{i}. " + MessageSegment.image(img_data) + f"注释：{img.note}")
    await get_ban_reason_cmd.send(
        f"用户 {user_info.nick_name}({user_info.tieba_uid}) 的循封原因：\n" + "\n".join(text_reasons_list)
    )
    if img_reasons_list:
        img_msg = MessageSegment.text("\n").join(img_reasons_list)
        await get_ban_reason_cmd.send(img_msg)
    await get_ban_reason_cmd.finish()
