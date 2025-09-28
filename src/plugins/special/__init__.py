import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from arclet.alconna import Alconna, Args, MultiVar
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, permission
from nonebot.params import Received
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot_plugin_alconna import AlconnaQuery, Field, Match, Query, UniMessage, on_alconna

from logger import log
from src.common import Client
from src.db import (
    Associated,
    AutoBanList,
    BanList,
    GroupCache,
    GroupInfo,
    ImageUtils,
    TextDataModel,
    TiebaNameCache,
)
from src.utils import (
    handle_tieba_uid,
    handle_tieba_uids,
    require_slave_BDUSS,
    rule_admin,
    rule_master,
    rule_moderator,
    rule_signed,
)

if TYPE_CHECKING:
    from aiotieba.typing import UserInfo

    from db.models import ImgDataModel

__plugin_meta__ = PluginMetadata(
    name="special",
    description="",
    usage="",
)

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


async def del_posts_from_user_posts(client: Client, fid: int, user_id: int) -> tuple[int, int]:
    self_info = await client.get_self_info()
    self_id = self_info.user_id
    posts_deleted = 0
    threads_deleted = 0
    current_page = 1
    batch_size = 10
    has_empty = False
    while not has_empty:
        tasks = [
            client.get_user_posts(user_id, pn=page, rn=50) for page in range(current_page, current_page + batch_size)
        ]
        results = await asyncio.gather(*tasks)
        for result in results:
            if not result.objs:
                has_empty = True
                break
            for posts in result.objs:
                for post in posts.objs:
                    if post.author_id == self_id:  # 保险栓
                        break
                    if post.fid == fid:
                        if await client.del_post(fid, tid=post.tid, pid=post.pid):
                            posts_deleted += 1
        current_page += batch_size
    current_page = 1
    has_empty = False
    while not has_empty:
        tasks = [client.get_user_threads(user_id, pn=page) for page in range(current_page, current_page + batch_size)]
        results = await asyncio.gather(*tasks)
        for result in results:
            if not result.objs:
                has_empty = True
                break
            for thread in result.objs:
                if thread.user.user_id == self_id:  # 保险栓
                    break
                if thread.fid == fid:
                    if await client.del_thread(fid, tid=thread.tid):
                        threads_deleted += 1
        current_page += batch_size
    return posts_deleted, threads_deleted


async def del_posts_from_main_page(client: Client, fid: int, user_ids: list[int]) -> tuple[int, int]:
    posts_deleted = 0
    threads_deleted = 0
    threads_current_page = 1
    threads_max_page = 100
    batch_size = 10
    threads_has_empty = False
    while not threads_has_empty:
        tasks = [
            client.get_threads(fid, pn=page, rn=100)
            for page in range(threads_current_page, threads_current_page + batch_size)
        ]
        threads_results = await asyncio.gather(*tasks)
        for threads_result in threads_results:
            if not threads_result.objs:
                threads_has_empty = True
                break
            for thread in threads_result.objs:
                if thread.user.user_id in user_ids:
                    if await client.del_thread(fid, tid=thread.tid):
                        threads_deleted += 1
                posts_current_page = 1
                posts_has_empty = False
                while not posts_has_empty:
                    tasks = [
                        client.get_posts(thread.tid, pn=page)
                        for page in range(posts_current_page, posts_current_page + batch_size)
                    ]
                    posts_results = await asyncio.gather(*tasks)
                    for posts_result in posts_results:
                        if not posts_result.objs:
                            posts_has_empty = True
                            break
                        for post in posts_result.objs:
                            if post.author_id in user_ids:
                                if await client.del_post(fid, tid=thread.tid, pid=post.pid):
                                    posts_deleted += 1
                            if not post.reply_num > 0:
                                continue
                            comments_current_page = 1
                            comments_has_empty = False
                            while not comments_has_empty:
                                tasks = [
                                    client.get_comments(thread.tid, post.pid, pn=page)
                                    for page in range(comments_current_page, comments_current_page + batch_size)
                                ]
                                comments_results = await asyncio.gather(*tasks)
                                for comments_result in comments_results:
                                    if not comments_result.objs:
                                        comments_has_empty = True
                                        break
                                    for comment in comments_result.objs:
                                        if comment.author_id in user_ids:
                                            if await client.del_post(fid, tid=thread.tid, pid=comment.pid):
                                                posts_deleted += 1
                                comments_current_page += batch_size
                    posts_current_page += batch_size
        threads_current_page += batch_size
        if threads_current_page > threads_max_page:
            break
    return posts_deleted, threads_deleted


@clear_posts_cmd.handle()
@require_slave_BDUSS
async def clear_posts_handle(
    event: GroupMessageEvent, mode: Match[str], tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("tieba_uids", ())
):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tieba_uids = [await handle_tieba_uid(tieba_id) for tieba_id in tieba_uid_strs.result]
    if 0 in tieba_uids:
        await clear_posts_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    async with Client(group_info.slave_bduss, try_ws=True) as client:
        user_infos = [await client.tieba_uid2user_info(tieba_uid) for tieba_uid in tieba_uids]
        user_ids = [user_info.user_id for user_info in user_infos]
        nicknames = [user_info.nick_name for user_info in user_infos]
        if mode.result == "方式1":
            confirm = await clear_posts_cmd.prompt(
                f"即将使用方式1（遍历用户发贴历史）清理用户 {'，'.join(nicknames)} 在本吧的所有发言。\n"
                "确认请回复“确认”，取消请回复任意内容。"
            )
            if confirm != UniMessage("确认"):
                await clear_posts_cmd.finish("操作已取消。")
            await clear_posts_cmd.send("已创建清理任务。")
            for user_id in user_ids:
                if user_id == (await client.get_self_info()).user_id:
                    break
                posts_deleted, threads_deleted = await del_posts_from_user_posts(client, group_info.fid, user_id)
                user_info = await client.get_user_info(user_id)
                await Associated.add_data(
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
            # one = await clear_posts_cmd.prompt("方式2暂未实现，扣1催更")
            # if one == UniMessage("1"):
            #     await clear_posts_cmd.finish("催更成功！")
            # else:
            #     await clear_posts_cmd.finish()
            # confirm = await clear_posts_cmd.prompt(
            #     f"即将使用方式2（遍历本吧首页贴子）清理用户 {'，'.join(nicknames)} 在本吧的所有发言。\n"
            #     "请注意，该方式相较于方式1更慢，且最多可以遍历吧内前100页贴子，建议仅当用户隐藏其回贴列表时使用。\n"
            #     "确认请回复“确认”，取消请回复任意内容。"
            # )
            # if confirm != UniMessage("确认"):
            #     await clear_posts_cmd.finish("操作已取消。")
            # await clear_posts_cmd.send("已创建清理任务。")
            # posts_deleted, threads_deleted = await del_posts_from_main_page(client, group_info.fid, user_ids)
            # await Associated.add_data(
            #     user_info,
            #     group_info,
            #     text_data=[
            #         TextData(uploader_id=event.user_id, fid=group_info.fid, text="[自动添加]清空发言（方式2）")
            #     ],
            # )
            # await clear_posts_cmd.send(
            #     f"用户 {'，'.join(nicknames)} 在本吧的发言清理完成，"
            #     f"共删除 {posts_deleted} 条回复和 {threads_deleted} 个主题贴。"
            # )
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    state["group_info"] = group_info
    async with Client(try_ws=True) as client:
        user_infos = [await client.tieba_uid2user_info(tieba_uid) for tieba_uid in tieba_uids]
    state["user_infos"] = user_infos
    state["text_reasons"] = []
    state["img_reasons"] = []
    current_user = user_infos[0]
    state["current_user"] = current_user
    # await add_autoban_cmd.send(
    #     "单条消息支持文字、图片或文字+图片格式，"
    #     "若为文字+图片格式则文字将自动添加为该消息内临近图片的注释，不计入文字段数限制。"
    #     "图片最大支持10MB，最多支持10段文字和10张图片，任一格式溢出时将截断并自动确认操作。"
    #     "支持确认后再补充和修改循封原因。"
    # )
    is_banned, ban_reason = await AutoBanList.ban_status(group_info.fid, current_user.user_id)
    if is_banned == "banned":
        await add_autoban_cmd.send(f"用户 {current_user.nick_name}({current_user.tieba_uid}) 已在循封列表中。")
        user_infos.remove(current_user)
        if not user_infos:
            await add_autoban_cmd.finish("处理完成。")
        current_user = user_infos[0]
        state["current_user"] = current_user
    elif is_banned == "unbanned":
        assert ban_reason is not None  # for pylance
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
        is_banned, ban_reason = await AutoBanList.ban_status(group_info.fid, current_user.user_id)
        if is_banned == "banned":
            await add_autoban_cmd.send(f"用户 {current_user.nick_name}({current_user.tieba_uid}) 已在循封列表中。")
            user_infos.remove(current_user)
            if not user_infos:
                await add_autoban_cmd.finish("处理完成。")
            current_user = user_infos[0]
            state["current_user"] = current_user
        elif is_banned == "unbanned":
            assert ban_reason is not None  # for pylance
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
    text_reasons = state["text_reasons"]
    img_reasons = state["img_reasons"]
    msg = input_.message
    if msg.extract_plain_text() == "确认":
        state["current_user"] = None
        ban_reason = BanList(
            fid=group_info.fid,
            user_id=current_user.user_id,
            operator_id=input_.user_id,
            text_reason=text_reasons,
            img_reason=img_reasons,
        )
        result = await AutoBanList.add_ban(group_info.fid, group_info.group_id, ban_reason)
        if not result:
            await add_autoban_cmd.send(f"用户 {current_user.nick_name}({current_user.tieba_uid}) 添加至循封列表失败。")
        else:
            await add_autoban_cmd.send(f"已将用户 {current_user.nick_name}({current_user.tieba_uid}) 添加至循封列表。")
            await Associated.add_data(
                current_user,
                group_info,
                text_data=[TextDataModel(uploader_id=input_.user_id, fid=group_info.fid, text="[自动添加]循封")],
            )
        async with Client(group_info.slave_bduss, try_ws=True) as client:
            if not await client.block(group_info.fid, current_user.user_id, day=10, reason="违规"):
                log.warning(
                    f"Failed to block user {current_user.nick_name}({current_user.tieba_uid}) in "
                    f"{TiebaNameCache.get(group_info.fid)}"
                )
                # await add_autoban_cmd.send(f"用户 {current_user.nick_name}({current_user.tieba_uid}) 封禁操作失败。")
        user_infos.remove(current_user)
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
    text_buffer = []
    img_buffer = []
    for segment in msg:
        if segment.type == "text":
            if img_buffer:
                img_reason = img_buffer.pop()
                img_reason.note = segment.data["text"]
                img_reasons.append(img_reason)
            else:
                text_buffer.append(segment.data["text"])
        elif segment.type == "image":
            img_data = await ImageUtils.download_and_save_img(
                url=segment.data["url"], uploader_id=input_.user_id, fid=group_info.fid
            )
            if img_data == -1:
                await add_autoban_cmd.reject("图片下载失败，请尝试重新发送。")
            elif img_data == -2:
                await add_autoban_cmd.reject("图片过大，请尝试取消勾选“原图”。")
            img_reason = img_data
            if text_buffer:
                note = text_buffer.pop()
                img_reason.note = note
                img_reasons.append(img_reason)
            else:
                img_buffer.append(img_reason)
    for text in text_buffer:
        text_reasons.append(TextDataModel(uploader_id=input_.user_id, fid=group_info.fid, text=text))
    for img in img_buffer:
        img_reasons.append(img)
    if len(text_reasons) >= 10:
        text_reasons = text_reasons[:10]
        await add_autoban_cmd.send("文字数量已达上限，请确认操作。")
    if len(img_reasons) >= 10:
        img_reasons = img_reasons[:10]
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await remove_autoban_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    success = []
    failure = []
    async with Client(group_info.slave_bduss, try_ws=True) as client:
        user_infos = [await client.tieba_uid2user_info(tieba_uid) for tieba_uid in tieba_uids]
        for user_info in user_infos:
            is_banned, ban_reason = await AutoBanList.ban_status(group_info.fid, user_info.user_id)
            match is_banned:
                case "not":
                    failure.append((user_info.nick_name, user_info.tieba_uid, "不在循封列表中"))
                case "unbanned":
                    assert ban_reason is not None  # for pylance
                    unban_time_str = (
                        ban_reason.unban_time.strftime("%Y-%m-%d %H:%M:%S") if ban_reason.unban_time else "未知时间"
                    )
                    unban_operator_id = ban_reason.unban_operator_id
                    failure.append((
                        user_info.nick_name,
                        user_info.tieba_uid,
                        f"已于 {unban_time_str} 解除循封，操作人id：{unban_operator_id}",
                    ))
                case "banned":
                    if await AutoBanList.unban(group_info.fid, event.user_id, user_info.user_id):
                        if await client.unblock(group_info.fid, user_info.user_id):
                            success.append((user_info.nick_name, user_info.tieba_uid))
                        else:
                            failure.append((
                                user_info.nick_name,
                                user_info.tieba_uid,
                                "数据库操作成功，贴吧操作失败，请考虑手动解除当前封禁",
                            ))
                        await Associated.add_data(
                            user_info,
                            group_info,
                            text_data=[
                                TextDataModel(uploader_id=event.user_id, fid=group_info.fid, text="[自动添加]解除循封")
                            ],
                        )
                    else:
                        failure.append((user_info.nick_name, user_info.tieba_uid, "数据库操作失败"))
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tieba_uid = await handle_tieba_uid(tieba_uid_str.result)
    if tieba_uid is None:
        await delete_ban_reason_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    async with Client(try_ws=True) as client:
        user_info = await client.tieba_uid2user_info(tieba_uid)
    is_banned, ban_reason = await AutoBanList.ban_status(group_info.fid, user_info.user_id)
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
        img_data = await ImageUtils.get_image_data(img.image_id)
        if img_data is None:
            img_reasons_list.append(MessageSegment.text(f"{i}. 图片数据获取失败" + f"注释：{img.note}"))
        else:
            img_reasons_list.append(f"{i}. " + MessageSegment.image(img_data) + f"注释：{img.note}")
    # img_reasons_list = [
    #     f"{i}. " + MessageSegment.image(f"base64://{await ImageUtils.get_image_data(img)}") + f"注释：{img.note}"
    #     for i, img in img_reasons
    # ]
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
        result = await AutoBanList.update_ban_reason(group_info.fid, user_info.user_id, text_reason=[], img_reason=[])
        if result:
            await delete_ban_reason_cmd.finish("操作完成。")
        else:
            await delete_ban_reason_cmd.finish("数据库操作失败。")
    ids = plain_text.split()
    try:
        ids = list(map(int, ids))
    except Exception:
        await delete_ban_reason_cmd.reject("参数错误，请检查并重新输入。输入“取消”以取消操作。")
    group_info = state["group_info"]
    user_info = state["user_info"]
    text_reasons: list[tuple[int, TextDataModel]] = state["text_reasons"]
    img_reasons: list[tuple[int, ImgDataModel]] = state["img_reasons"]
    if any(_id < 0 or _id > len(text_reasons) + len(img_reasons) for _id in ids):
        await delete_ban_reason_cmd.reject("参数错误，请检查并重新输入。输入“取消”以取消操作。")
    for delete_id in ids:
        text = next((text_reason for index, text_reason in text_reasons if index == delete_id), None)
        if text is not None:
            text_reasons = list(filter(lambda x: x[0] != delete_id, text_reasons))
            continue
        img = next((img_reason for index, img_reason in img_reasons if index == delete_id), None)
        if img is not None:
            await ImageUtils.delete_image(img.image_id)
            img_reasons = list(filter(lambda x: x[0] != delete_id, img_reasons))
            continue
    text_reason = [text for _, text in text_reasons]
    img_reason = [img for _, img in img_reasons]
    result = await AutoBanList.update_ban_reason(
        group_info.fid, user_info.user_id, text_reason=text_reason, img_reason=img_reason
    )
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tieba_uid = await handle_tieba_uid(tieba_uid_str.result)
    if tieba_uid is None:
        await add_ban_reason_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    async with Client(try_ws=True) as client:
        user_info = await client.tieba_uid2user_info(tieba_uid)
    is_banned, ban_reason = await AutoBanList.ban_status(group_info.fid, user_info.user_id)
    if is_banned == "not":
        await add_ban_reason_cmd.finish(f"用户 {user_info.nick_name}({user_info.tieba_uid}) 不在循封列表中。")
    assert ban_reason is not None  # for pylance
    state["ban_reason"] = ban_reason
    state["group_info"] = group_info
    state["user_info"] = user_info
    state["text_reasons"] = ban_reason.text_reason
    state["img_reasons"] = ban_reason.img_reason
    await add_ban_reason_cmd.send("请输入循封或解除循封原因，输入“确认”以结束，或输入“取消”取消操作。")


@add_ban_reason_cmd.receive("input")
async def add_ban_reason_input(state: T_State, input_: GroupMessageEvent = Received("input")):
    group_info = state["group_info"]
    user_info = state["user_info"]
    text_reasons = state["text_reasons"]
    img_reasons = state["img_reasons"]
    text_buffer = []
    img_buffer = []
    msg = input_.message
    if msg.extract_plain_text() == "确认":
        state["current_user"] = None
        result = await AutoBanList.update_ban_reason(
            group_info.fid, user_info.user_id, text_reason=text_reasons, img_reason=img_reasons
        )
        if not result:
            await add_ban_reason_cmd.finish("数据库操作失败。")
        await add_ban_reason_cmd.finish("操作完成。")
    elif msg.extract_plain_text() == "取消":
        await add_ban_reason_cmd.finish("操作已取消。")
    for segment in msg:
        if segment.type == "text":
            if img_buffer:
                img_reason = img_buffer.pop()
                img_reason.note = segment.data["text"]
                img_reasons.append(img_reason)
            else:
                text_buffer.append(segment.data["text"])
        elif segment.type == "image":
            img_data = await ImageUtils.download_and_save_img(
                url=segment.data["url"], uploader_id=input_.user_id, fid=group_info.fid
            )
            if img_data == -1:
                await add_ban_reason_cmd.reject("图片下载失败，请尝试重新发送。")
            elif img_data == -2:
                await add_ban_reason_cmd.reject("图片过大，请尝试取消勾选“原图”。")
            img_reason = img_data
            if text_buffer:
                note = text_buffer.pop()
                img_reason.note = note
                img_reasons.append(img_reason)
            else:
                img_buffer.append(img_reason)
    for text in text_buffer:
        text_reasons.append(TextDataModel(uploader_id=input_.user_id, fid=group_info.fid, text=text))
    for img in img_buffer:
        img_reasons.append(img)
    if len(text_reasons) >= 10:
        text_reasons = text_reasons[:10]
        await add_ban_reason_cmd.send("文字数量已达上限，请确认操作。")
    if len(img_reasons) >= 10:
        img_reasons = img_reasons[:10]
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
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    tieba_uid = await handle_tieba_uid(tieba_uid_str.result)
    if tieba_uid is None:
        await get_ban_reason_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    async with Client(try_ws=True) as client:
        user_info = await client.tieba_uid2user_info(tieba_uid)
    is_banned, ban_reason = await AutoBanList.ban_status(group_info.fid, user_info.user_id)
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
        img_data = await ImageUtils.get_image_data(img.image_id)
        if img_data is None:
            # img_reasons_list.append(f"{i}. 图片数据获取失败" + f"注释：{img.note}")
            img_reasons_list.append(MessageSegment.text(f"{i}. 图片数据获取失败") + f"注释：{img.note}")
        else:
            img_reasons_list.append(f"{i}. " + MessageSegment.image(img_data) + f"注释：{img.note}")
    # img_reasons_list = [
    #     f"{i}. " + MessageSegment.image(f"base64://{await ImageUtils.get_image_data(img)}") + f"注释：{img.note}"
    #     for i, img in img_reasons
    # ]
    await get_ban_reason_cmd.send(
        f"用户 {user_info.nick_name}({user_info.tieba_uid}) 的循封原因：\n" + "\n".join(text_reasons_list)
    )
    if img_reasons_list:
        img_msg = MessageSegment.text("\n").join(img_reasons_list)
        await get_ban_reason_cmd.send(img_msg)
    await get_ban_reason_cmd.finish()
