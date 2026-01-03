from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.db.crud import associated, autoban, image
from src.db.models import BanList, GroupInfo, ImgDataModel, TextDataModel

if TYPE_CHECKING:
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid
    from aiotieba.typing import UserInfo
    from nonebot.adapters.onebot.v11 import Message
    from tiebameow.client import Client


async def del_posts_from_user_posts(client: Client, fid: int, user_id: int) -> tuple[int, int]:
    """
    通过遍历用户发贴历史删除用户在指定吧的所有主题贴和回复。

    Args:
        client: 已登录的 Tieba Client 实例。
        fid: 指定贴吧的 fid。
        user_id: 目标用户 user_id。

    Returns:
        tuple: (posts_deleted, threads_deleted)
    """
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


async def add_ban_and_block(
    client: Client, fid: int, group_id: int, user: UserInfo, operator_id: int, text_reasons: list, img_reasons: list
) -> tuple[bool, bool]:
    """
    将用户加入循封列表并在贴吧封禁。

    Args:
        client: 已登录的 Tieba Client 实例。
        fid: 贴吧 fid。
        group_id: 群组 ID。
        user: 目标用户信息。
        operator_id: 操作者 ID。
        text_reasons: 文本原因列表。
        img_reasons: 图片原因列表。

    Returns:
        tuple: (db_success, tieba_success)
    """
    ban_reason = BanList(
        fid=fid,
        user_id=user.user_id,
        portrait=user.portrait,
        operator_id=operator_id,
        text_reason=text_reasons,
        img_reason=img_reasons,
    )
    db_success = await autoban.add_ban(fid, group_id, ban_reason)

    tieba_success = False
    if db_success:
        tieba_success = await client.block(fid, user.portrait, day=10)

    return db_success, bool(tieba_success)


async def process_ban_images(
    fid: int, uploader_id: int, user_id: int, pending_imgs: list[dict[str, str]], current_img_reasons: list
) -> tuple[list[ImgDataModel], int]:
    """
    下载并保存待处理的封禁图片，并更新数据库中的封禁原因列表。

    Args:
        fid: 贴吧 fid。
        uploader_id: 上传者 ID。
        user_id: 目标用户 ID。
        pending_imgs: 待处理的图片信息列表。
        current_img_reasons: 当前的图片原因列表。

    Returns:
        tuple: (new_img_reasons, failed_count)
    """
    new_img_reasons = []
    failed_count = 0

    for img_info in pending_imgs:
        img_data = await image.download_and_save_img(
            url=img_info["url"], uploader_id=uploader_id, fid=fid, note=img_info["note"]
        )
        if isinstance(img_data, int):
            failed_count += 1
        else:
            new_img_reasons.append(img_data)

    if new_img_reasons:
        current_img_reasons.extend(new_img_reasons)
        await autoban.update_ban_reason(fid, user_id, img_reason=current_img_reasons)

    return new_img_reasons, failed_count


async def unban_and_unblock(client: Client, fid: int, operator_id: int, user_id: int) -> tuple[bool, bool]:
    """
    将用户从循封列表中移除并在贴吧解除封禁。

    Args:
        client: 已登录的 Tieba Client 实例。
        fid: 贴吧 fid。
        operator_id: 操作者 ID。
        user_id: 目标用户 ID。
    Returns:
        tuple: (db_success, tieba_success)
    """
    db_success = await autoban.unban(fid, operator_id, user_id)
    tieba_success = False
    if db_success:
        tieba_success = await client.unblock(fid, user_id)
    return db_success, bool(tieba_success)


def parse_ban_reason_input(msg: Message, uploader_id: int, fid: int) -> tuple[list[TextDataModel], list[dict]]:
    """
    解析用户输入的封禁原因消息，提取文字和图片原因。

    Args:
        msg: 用户输入的消息。
        uploader_id: 上传者 ID。
        fid: 贴吧 fid。

    Raises:
        ValueError: 如果图片过大则抛出异常。

    Returns:
        tuple: (text_reasons, pending_imgs)
    """
    text_reasons = []
    pending_imgs = []
    text_buffer = []
    img_buffer = []

    for segment in msg:
        if segment.type == "text":
            if img_buffer:
                img_info = img_buffer.pop()
                img_info["note"] = segment.data["text"]
                pending_imgs.append(img_info)
            else:
                text_buffer.append(segment.data["text"])
        elif segment.type == "image":
            if int(segment.data.get("file_size", 0)) > 10 * 1024 * 1024:
                raise ValueError("图片过大，请尝试取消勾选“原图”。")
            img_info = {"url": segment.data["url"], "note": ""}
            if text_buffer:
                note = text_buffer.pop()
                img_info["note"] = note
                pending_imgs.append(img_info)
            else:
                img_buffer.append(img_info)

    text_reasons.extend([TextDataModel(uploader_id=uploader_id, fid=fid, text=text) for text in text_buffer])
    pending_imgs.extend(img_buffer)

    return text_reasons, pending_imgs


async def remove_autoban_users(
    client: Client, group_info: GroupInfo, operator_id: int, user_infos: list[UserInfo_TUid]
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """
    将用户从循封列表中移除并在贴吧解除封禁。

    Args:
        client: 已登录的 Tieba Client 实例。
        group_info: 群组信息。
        operator_id: 操作者 ID。
        user_infos: 目标用户信息列表。

    Returns:
        tuple: (success_list, failure_list)
    """
    success = []
    failure = []
    for user_info in user_infos:
        is_banned, ban_reason = await autoban.get_ban_status(group_info.fid, user_info.user_id)
        if ban_reason is None:
            failure.append((user_info.nick_name, user_info.tieba_uid, "不在循封列表中"))
        elif is_banned == "unbanned":
            unban_time_str = (
                ban_reason.unban_time.strftime("%Y-%m-%d %H:%M:%S") if ban_reason.unban_time else "未知时间"
            )
            unban_operator_id = ban_reason.unban_operator_id
            failure.append((
                user_info.nick_name,
                user_info.tieba_uid,
                f"已于 {unban_time_str} 解除循封，操作人id：{unban_operator_id}",
            ))
        elif is_banned == "banned":
            db_success, tieba_success = await unban_and_unblock(client, group_info.fid, operator_id, user_info.user_id)
            if db_success:
                if tieba_success:
                    success.append((user_info.nick_name, user_info.tieba_uid))
                else:
                    failure.append((
                        user_info.nick_name,
                        user_info.tieba_uid,
                        "数据库操作成功，贴吧操作失败，请考虑手动解除当前封禁",
                    ))
                await associated.add_associated_data(
                    user_info,
                    group_info,
                    text_data=[TextDataModel(uploader_id=operator_id, fid=group_info.fid, text="[自动添加]解除循封")],
                )
            else:
                failure.append((user_info.nick_name, user_info.tieba_uid, "数据库操作失败"))
    return success, failure


async def delete_ban_reasons(
    fid: int,
    user_id: int,
    delete_ids: list[int],
    text_reasons: list[tuple[int, TextDataModel]],
    img_reasons: list[tuple[int, ImgDataModel]],
) -> bool:
    """
    删除指定的循封原因。

    Args:
        fid: 贴吧 fid。
        user_id: 目标用户 ID。
        delete_ids: 要删除的循封原因 ID 列表。
        text_reasons: 当前的文本原因列表，包含索引和 TextDataModel。
        img_reasons: 当前的图片原因列表，包含索引和 ImgDataModel。

    Returns:
        bool: 更新循封原因是否成功。
    """
    for delete_id in delete_ids:
        text = next((text_reason for index, text_reason in text_reasons if index == delete_id), None)
        if text is not None:
            text_reasons[:] = [x for x in text_reasons if x[0] != delete_id]
            continue
        img = next((img_reason for index, img_reason in img_reasons if index == delete_id), None)
        if img is not None:
            await image.delete_image(img.image_id)
            img_reasons[:] = [x for x in img_reasons if x[0] != delete_id]
            continue

    text_reason_models = [text for _, text in text_reasons]
    img_reason_models = [img for _, img in img_reasons]
    return await autoban.update_ban_reason(fid, user_id, text_reason=text_reason_models, img_reason=img_reason_models)
