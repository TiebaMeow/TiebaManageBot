from __future__ import annotations

from typing import TYPE_CHECKING

from logger import log
from src.common import Client
from src.db import GroupInfo
from src.db.crud import add_group, delete_group, get_group, update_group
from src.utils import get_user_name

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


async def init_group(group_id: int, user_id: int, tieba_name: str) -> str:
    """
    初始化群聊为贴吧管理群

    Args:
        group_id (int): 群号
        user_id (int): 用户QQ号
        tieba_name (str): 贴吧名称（不含“吧”字）

    Returns:
        str: 结果消息
    """
    try:
        group_info = await get_group(group_id)
        return f"本群已被初始化为{group_info.fname}吧管理群，如需更改请使用重置指令"
    except KeyError:
        pass

    async with Client() as client:
        fid = await client.get_fid(tieba_name)

    if fid == 0:
        return f"贴吧 {tieba_name}吧 不存在，请检查拼写"

    group_info = GroupInfo(group_id=group_id, master=user_id, fid=int(fid), fname=tieba_name)
    try:
        await add_group(group_info)
        log.info(f"群聊 {group_id} 初始化成功")
        return (
            "初始化成功，吧主权限已自动分配给群主，请根据用户手册完善其他信息。\n"
            "初始化完成后，视为您理解并同意使用手册中的用户协议内容。\n"
            "如果您不同意或未来撤回同意，请使用 /重置 指令。"
        )
    except Exception as e:
        log.info(f"群聊 {group_id} 初始化失败：{e}")
        return "初始化失败，请联系bot管理员。"


async def set_master(group_id: int, user_id: int, bot: Bot) -> str:
    """
    设置群聊的吧主权限账号

    Args:
        group_id (int): 群号
        user_id (int): 用户QQ号
        bot (Bot): 机器人实例

    Returns:
        str: 结果消息
    """
    group_info = await get_group(group_id)
    if group_info is None:
        return "本群尚未初始化"

    if group_info.master == user_id:
        return "你已经是吧主啦，无需重复设置。"

    await update_group(group_id, master=user_id)
    master_username = await get_user_name(bot, group_id, user_id)
    return f"成功设置吧主权限账号为：{master_username}({user_id})，原吧主权限账号已变更为普通权限，请注意设置"


async def reset_group(group_id: int) -> None:
    """
    重置群聊的配置信息
    """
    await delete_group(group_id)


async def set_admin(
    group_id: int, users: list[int], bot: Bot
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """
    设置群聊的admin权限账号

    Args:
        group_id (int): 群号
        users (list[int]): 用户QQ号列表
        bot (Bot): 机器人实例

    Returns:
        tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]: 成功和失败的用户列表，包含用户名、用户QQ号和原因
    """
    group_info = await get_group(group_id)
    if group_info is None:
        raise ValueError("Group not initialized")

    succeeded = []
    failed = []

    users = list(set(users))

    for admin_user_id in users:
        user_name = await get_user_name(bot, group_id, admin_user_id)
        if admin_user_id in group_info.admins:
            failed.append((user_name, admin_user_id, "已位于admin权限组中"))
        elif admin_user_id == group_info.master:
            failed.append((user_name, admin_user_id, "已拥有吧主权限"))
        elif admin_user_id in group_info.moderators:
            group_info.moderators.remove(admin_user_id)
            group_info.admins.append(admin_user_id)
            succeeded.append((user_name, admin_user_id, "已从moderator权限组提升至admin权限组"))
        else:
            group_info.admins.append(admin_user_id)
            succeeded.append((user_name, admin_user_id, "已添加至admin权限组"))

    try:
        await update_group(group_id, admins=group_info.admins, moderators=group_info.moderators)
    except Exception as e:
        log.info(f"群聊 {group_id} 添加admin权限失败：{e}")
        raise e

    return succeeded, failed


async def remove_admin(
    group_id: int, users: list[int], bot: Bot
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """
    移除群聊的admin权限账号

    Args:
        group_id (int): 群号
        users (list[int]): 用户QQ号列表
        bot (Bot): 机器人实例

    Returns:
        tuple[list[tuple[str, int]], list[tuple[str, int]]]: 成功和失败的用户列表，包含用户名和用户QQ号
    """
    group_info = await get_group(group_id)
    if group_info is None:
        raise ValueError("Group not initialized")

    succeeded = []
    failed = []

    for admin_user_id in users:
        user_name = await get_user_name(bot, group_id, admin_user_id)
        if admin_user_id not in group_info.admins:
            failed.append((user_name, admin_user_id))
        else:
            group_info.admins.remove(admin_user_id)
            succeeded.append((user_name, admin_user_id))

    try:
        await update_group(group_id, admins=group_info.admins)
    except Exception as e:
        log.info(f"群聊 {group_id} 移除admin权限失败：{e}")
        raise e

    return succeeded, failed


async def set_moderator(
    group_id: int, users: list[int], bot: Bot
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """
    设置群聊的moderator权限账号

    Args:
        group_id (int): 群号
        users (list[int]): 用户QQ号列表
        bot (Bot): 机器人实例

    Returns:
        tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]: 成功和失败的用户列表，包含用户名、用户QQ号和原因
    """
    group_info = await get_group(group_id)
    if group_info is None:
        raise ValueError("Group not initialized")

    succeeded = []
    failed = []

    users = list(set(users))

    for moderator_user_id in users:
        user_name = await get_user_name(bot, group_id, moderator_user_id)
        if moderator_user_id in group_info.moderators:
            failed.append((user_name, moderator_user_id, "已位于moderator权限组中"))
        elif moderator_user_id == group_info.master:
            failed.append((user_name, moderator_user_id, "已拥有吧主权限"))
        elif moderator_user_id in group_info.admins:
            group_info.admins.remove(moderator_user_id)
            group_info.moderators.append(moderator_user_id)
            succeeded.append((user_name, moderator_user_id, "已从admin权限组降级至moderator权限组"))
        else:
            group_info.moderators.append(moderator_user_id)
            succeeded.append((user_name, moderator_user_id, "已添加至moderator权限组"))

    try:
        await update_group(group_id, admins=group_info.admins, moderators=group_info.moderators)
    except Exception as e:
        log.info(f"群聊 {group_id} 添加moderator权限失败：{e}")
        raise e

    return succeeded, failed


async def remove_moderator(
    group_id: int, users: list[int], bot: Bot
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """
    移除群聊的moderator权限账号

    Args:
        group_id (int): 群号
        users (list[int]): 用户QQ号列表
        bot (Bot): 机器人实例

    Returns:
        tuple[list[tuple[str, int]], list[tuple[str, int]]]: 成功和失败的用户列表，包含用户名和用户QQ号
    """
    group_info = await get_group(group_id)
    if group_info is None:
        raise ValueError("Group not initialized")

    succeeded = []
    failed = []

    for moderator_user_id in users:
        user_name = await get_user_name(bot, group_id, moderator_user_id)
        if moderator_user_id not in group_info.moderators:
            failed.append((user_name, moderator_user_id))
        else:
            group_info.moderators.remove(moderator_user_id)
            succeeded.append((user_name, moderator_user_id))

    try:
        await update_group(group_id, moderators=group_info.moderators)
    except Exception as e:
        log.info(f"群聊 {group_id} 移除moderator权限失败：{e}")
        raise e

    return succeeded, failed


async def set_bduss(group_id: int, user_id: int | None, cmd: str, value: str | None = None) -> str:
    """
    设置群聊的BDUSS或STOKEN

    Args:
        group_id (int): 群号
        user_id (int | None): 用户QQ号
        cmd (str): 命令字符串
        value (str | None, optional): BDUSS或STOKEN的值. Defaults to None.

    Returns:
        str: 操作结果消息
    """
    group_info = await get_group(group_id)
    if group_info is None:
        return "该群未初始化或群号错误，请检查输入。"

    if user_id not in [group_info.master, *group_info.admins, *group_info.moderators]:
        return "您没有该群的吧主、admin或moderator权限。"

    if "设置" in cmd:
        if not value:
            return "无效的输入。"

        if "BDUSS" in cmd:
            async with Client(value) as client:
                if not await client.get_self_info():
                    return "BDUSS无效，请检查输入。"

            if user_id == group_info.master:
                await update_group(group_id, master_BDUSS=value)
                return "吧主BDUSS设置成功。"
            else:
                await update_group(group_id, slave_BDUSS=value)
                return "吧务BDUSS设置成功。"
        else:
            await update_group(group_id, slave_STOKEN=value)
            return "吧务STOKEN设置成功。"

    elif "删除" in cmd:
        if "BDUSS" in cmd:
            if user_id == group_info.master:
                await update_group(group_id, master_BDUSS="")
                return "吧主BDUSS删除成功。"
            else:
                await update_group(group_id, slave_BDUSS="")
                return "吧务BDUSS删除成功。"
        else:
            await update_group(group_id, slave_STOKEN="")
            return "吧务STOKEN删除成功。"

    return "未知指令"
