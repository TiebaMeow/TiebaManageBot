from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

from logger import log
from src.common.cache import ClientCache, add_autoban_record, get_tieba_name, trim_autoban_records
from src.common.cache.appeal import del_appeal_id, get_appeals, set_appeal_id, set_appeals
from src.db import TextDataModel
from src.db.crud import (
    add_associated_data,
    get_autoban,
    get_autoban_lists,
    get_ban_status,
    get_group,
    update_autoban,
    update_group,
)
from src.db.models import now_with_tz

if TYPE_CHECKING:
    from aiotieba.api.get_unblock_appeals._classdef import Appeal
    from aiotieba.typing import UserInfo

    from src.db import GroupInfo


async def run_autoban() -> None:
    """
    执行循封任务。
    """
    log.info("Autoban task started.")
    forums = await get_autoban()
    for forum in forums:
        group_info = await get_group(forum.group_id)

        failed = []
        success_count = 0
        log.info(f"Ready to autoban in {group_info.fname}")
        client = await ClientCache.get_bawu_client(group_info.group_id)
        async for portrait in get_autoban_lists(forum.fid):
            try:
                result = await client.block(group_info.fid, portrait, day=10)
                if not result:
                    failed.append(portrait)
                else:
                    success_count += 1
            except Exception as e:
                log.error(f"Error autobanning user {portrait} in {group_info.fname}: {e}")
                failed.append(portrait)
        await update_autoban(group_info.fid, group_info.group_id)
        if success_count:
            await add_autoban_record(group_info.fid, success_count)
            await trim_autoban_records(group_info.fid, now_with_tz() - timedelta(days=10))
        if failed:
            log.warning(f"Failed to ban users: {', '.join(failed)} in {await get_tieba_name(group_info.fid)}")
    log.info("Autoban task finished.")


class AppealNotification(NamedTuple):
    auto_deny: list[AutoDenyNotification]
    new_appeal: list[NewAppealNotification]


class AutoDenyNotification(NamedTuple):
    group_id: int
    user_info: UserInfo


class NewAppealNotification(NamedTuple):
    group_id: int
    user_info: UserInfo
    appeal: Appeal


async def process_appeals_for_group(group_info: GroupInfo) -> AppealNotification:
    """
    处理指定贴吧群的封禁申诉。

    Args:
        group_info (GroupInfo): 贴吧群信息

    Returns:
        AppealNotification: 需要推送的申诉通知
    """
    notifications = AppealNotification(auto_deny=[], new_appeal=[])
    if not group_info.slave_bduss or not group_info.group_args.get("appeal_sub", False):
        return notifications

    client = await ClientCache.get_bawu_client(group_info.group_id)
    appeals = await client.get_unblock_appeals(group_info.fid, rn=20)
    cached_appeals = await get_appeals(group_info.group_id)

    for appeal in appeals.objs:
        user_info = await client.get_user_info(appeal.user_id)
        banlist, _ = await get_ban_status(group_info.fid, user_info.user_id)

        # 自动拒绝已循封用户的申诉
        if banlist == "banned":
            await client.handle_unblock_appeals(
                group_info.fid,
                appeal_ids=[appeal.appeal_id],
                refuse=True,
            )
            continue

        # 超时自动拒绝申诉
        if group_info.group_args.get("appeal_autodeny", False):
            if time.time() - appeal.appeal_time > 72000:
                result = await client.handle_unblock_appeals(
                    group_info.fid,
                    appeal_ids=[appeal.appeal_id],
                    refuse=True,
                )
                if result:
                    await add_associated_data(
                        user_info,
                        group_info,
                        text_data=[
                            TextDataModel(
                                uploader_id=0,
                                fid=group_info.fid,
                                text="[自动添加]超时自动拒绝申诉",
                            )
                        ],
                    )
                    notifications.auto_deny.append(
                        AutoDenyNotification(
                            group_id=group_info.group_id,
                            user_info=user_info,
                        )
                    )
                if (appeal.appeal_id, user_info.user_id) in cached_appeals:
                    cached_appeals.remove((appeal.appeal_id, user_info.user_id))
                continue

        # 推送新申诉
        if (appeal.appeal_id, user_info.user_id) not in cached_appeals:
            notifications.new_appeal.append(
                NewAppealNotification(
                    group_id=group_info.group_id,
                    user_info=user_info,
                    appeal=appeal,
                )
            )

    await set_appeals(group_info.group_id, cached_appeals)

    return notifications


async def update_appeal_cache(group_id: int, message_id: int, appeal_id: int, user_id: int):
    """
    更新申诉缓存。

    Args:
        group_id (int): 群聊ID
        message_id (int): 消息ID
        appeal_id (int): 申诉ID
        user_id (int): 用户ID
    """
    await set_appeal_id(message_id, (appeal_id, user_id))
    cached_appeals = await get_appeals(group_id)
    cached_appeals.append((appeal_id, user_id))
    await set_appeals(group_id, cached_appeals)


async def update_group_args(group_id: int, key: str, value: bool):
    """
    更新群聊参数。
    Args:
        group_id (int): 群聊ID
        key (str): 参数键
        value (bool): 参数值
    """
    group_info = await get_group(group_id)
    if group_info:
        group_args = group_info.group_args
        group_args.update({key: value})
        await update_group(group_id, group_args=group_args)


async def handle_appeal(
    group_info: GroupInfo, appeal_id: int, user_id: int, refuse: bool, reason: str, uploader_id: int
) -> bool:
    """
    处理封禁申诉。

    Args:
        group_info (GroupInfo): 群信息
        appeal_id (int): 申诉ID
        user_id (int): 用户ID
        refuse (bool): 是否拒绝申诉
        reason (str): 处理理由
        uploader_id (int): 操作人ID

    Returns:
        bool: 处理是否成功
    """
    client = await ClientCache.get_bawu_client(group_info.group_id)
    user_info = await client.get_user_info(user_id)
    result = await client.handle_unblock_appeals(group_info.fid, appeal_ids=[appeal_id], refuse=refuse)
    if result:
        action = "拒绝" if refuse else "通过"
        await add_associated_data(
            user_info,
            group_info,
            text_data=[
                TextDataModel(
                    uploader_id=uploader_id,
                    fid=group_info.fid,
                    text=f"[自动添加]{action}申诉，理由：{reason}",
                )
            ],
        )
        await del_appeal_id(appeal_id)
        return True
    return False
