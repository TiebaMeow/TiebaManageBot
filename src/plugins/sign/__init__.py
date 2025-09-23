from arclet.alconna import Alconna, Args, MultiVar
from nonebot import on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    FriendRequestEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
    permission,
)
from nonebot.params import Received
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_alconna import AlconnaQuery, Arparma, At, Field, Match, Query, UniMessage, on_alconna

from logger import log
from src.common import Client
from src.db import GroupCache, GroupInfo
from src.utils import (
    get_user_name,
    rule_admin,
    rule_master,
    rule_member,
    rule_owner,
    rule_signed,
)

__plugin_meta__ = PluginMetadata(
    name="sign",
    description="注册相关",
    usage="",
)

sign_alc = Alconna(
    "sign",
    Args["tieba_name_str", str, Field(completion=lambda: "请输入贴吧名")],
)

sign_cmd = on_alconna(
    command=sign_alc,
    aliases={"注册", "初始化"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_owner),
    permission=permission.GROUP,
    priority=3,
    block=True,
)


@sign_cmd.handle()
async def handle_sign(event: GroupMessageEvent, tieba_name_str: Match[str]):
    if (group_info := await GroupCache.get(event.group_id)) is not None:
        await sign_cmd.finish(f"本群已被初始化为{group_info.fname}吧管理群，如需更改请使用重置指令")
    tieba_name = tieba_name_str.result.removesuffix("吧")
    async with Client() as client:
        fid = await client.get_fid(tieba_name)
    if fid == 0:
        await sign_cmd.finish(f"贴吧 {tieba_name}吧 不存在，请检查拼写")
    assert event.sender.user_id is not None  # for pylance
    group_info = GroupInfo(group_id=event.group_id, master=event.sender.user_id, fid=int(fid), fname=tieba_name)
    try:
        await GroupCache.add(group_info)
        log.info(f"群聊 {event.group_id} 初始化成功")
    except Exception as e:
        log.info(f"群聊 {event.group_id} 初始化失败：{e}")
        await sign_cmd.finish("初始化失败，请联系bot管理员。")
    else:
        await sign_cmd.finish(
            "初始化成功，吧主权限已自动分配给群主，请根据用户手册完善其他信息。\n"
            "初始化完成后，视为您理解并同意使用手册中的用户协议内容。\n"
            "如果您不同意或未来撤回同意，请使用 /重置 指令。"
        )


master_alc = Alconna(
    "master",
    Args["master_user", At, Field(completion=lambda: "请艾特吧主")],
)

master_cmd = on_alconna(
    command=master_alc,
    aliases={"设置吧主"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=3,
    block=True,
)


@master_cmd.handle()
async def handle_master(bot: Bot, event: GroupMessageEvent, master_user: Match[At]):
    master_user_id = int(master_user.result.target)
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    if group_info.master == master_user_id:
        await master_cmd.finish("你已经是吧主啦，无需重复设置。")
    await GroupCache.update(event.group_id, master=master_user_id)
    master_username = await get_user_name(bot, event.group_id, master_user_id)
    await master_cmd.finish(
        f"成功设置吧主权限账号为：{master_username}({master_user_id})，原吧主权限账号已变更为普通权限，请注意设置"
    )


reset_alc = Alconna(
    "reset",
)

reset_cmd = on_alconna(
    command=reset_alc,
    aliases={"重置"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=3,
    block=True,
)


@reset_cmd.handle()
async def handle_reset(bot: Bot, event: GroupMessageEvent):
    await reset_cmd.send(
        "重置操作将删除本群的权限设置、BDUSS等配置信息，循封名单、关联信息将会保留，"
        "如果管理群或贴吧改变可联系bot管理员操作转移或导出。\n\n"
        "请认真阅读以上说明，确定重置请发送“确定”，取消请发送任意内容。"
    )


@reset_cmd.receive("confirm")
async def handle_reset_confirm(confirm: GroupMessageEvent = Received("confirm")):
    if confirm.get_plaintext() != "确定":
        await reset_cmd.finish("操作已取消。")
    await GroupCache.delete(confirm.group_id)
    await reset_cmd.finish("重置成功，如需继续使用请重新初始化。")


set_admin_alc = Alconna(
    "set_admin",
    Args["admin_users", MultiVar(At, "+"), Field(completion=lambda: "请艾特一个或多个需要添加的admin权限账号")],
)

set_admin_cmd = on_alconna(
    command=set_admin_alc,
    aliases={"添加管理员"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@set_admin_cmd.handle()
async def handle_set_admin(
    bot: Bot, event: GroupMessageEvent, admin_users: Query[tuple[At, ...]] = AlconnaQuery("admin_users", ())
):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    succeed = []
    failed = []
    users = [int(admin_user.target) for admin_user in admin_users.result]
    users = list(set(users))
    for admin_user_id in users:
        if admin_user_id in group_info.admins:
            failed.append((
                await get_user_name(bot, event.group_id, admin_user_id),
                admin_user_id,
                "已位于admin权限组中",
            ))
        elif admin_user_id == group_info.master:
            failed.append((await get_user_name(bot, event.group_id, admin_user_id), admin_user_id, "已拥有吧主权限"))
        elif admin_user_id in group_info.moderators:
            group_info.moderators.remove(admin_user_id)
            group_info.admins.append(admin_user_id)
            succeed.append((
                await get_user_name(bot, event.group_id, admin_user_id),
                admin_user_id,
                "已从moderator权限组提升至admin权限组",
            ))
        else:
            group_info.admins.append(admin_user_id)
            succeed.append((
                await get_user_name(bot, event.group_id, admin_user_id),
                admin_user_id,
                "已添加至admin权限组",
            ))
    try:
        await GroupCache.update(event.group_id, admins=group_info.admins, moderators=group_info.moderators)
    except Exception as e:
        log.info(f"群聊 {event.group_id} 添加admin权限失败：{e}")
        await set_admin_cmd.finish("操作失败，请联系bot管理员。")
    succeed_str = (
        "\n以下账号操作成功：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in succeed])
        if succeed
        else ""
    )
    failed_str = (
        "\n以下账号操作失败：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in failed])
        if failed
        else ""
    )
    await set_admin_cmd.finish(f"添加admin权限操作完成。{succeed_str}{failed_str}")


remove_admin_alc = Alconna(
    "remove_admin",
    Args[
        "admin_users",
        MultiVar(str, "+"),
        Field(
            completion=lambda: "请输入一个或多个（以空格分隔）需要移除的admin权限账号。"
            "考虑到特殊情况，本操作不支持通过艾特进行。"
        ),
    ],
)

remove_admin_cmd = on_alconna(
    command=remove_admin_alc,
    aliases={"移除管理员"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@remove_admin_cmd.handle()
async def handle_remove_admin(
    bot: Bot, event: GroupMessageEvent, admin_users: Query[tuple[str, ...]] = AlconnaQuery("admin_users", ())
):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    succeed = []
    failed = []
    try:
        users = [int(admin_user) for admin_user in admin_users.result]
    except ValueError:
        await remove_admin_cmd.finish("无效的账号，请检查输入。")
    for admin_user_id in users:
        if admin_user_id not in group_info.admins:
            failed.append((await get_user_name(bot, event.group_id, admin_user_id), admin_user_id))
        else:
            group_info.admins.remove(admin_user_id)
            succeed.append((await get_user_name(bot, event.group_id, admin_user_id), admin_user_id))
    try:
        await GroupCache.update(event.group_id, admins=group_info.admins)
    except Exception as e:
        log.info(f"群聊 {event.group_id} 移除admin权限失败：{e}")
        await remove_admin_cmd.finish("操作失败，请联系bot管理员。")
    succeed_str = (
        "\n以下账号操作成功：" + ", ".join([f"{name}({user_id})" for name, user_id in succeed]) if succeed else ""
    )
    failed_str = (
        "\n以下账号操作失败：" + ", ".join([f"{name}({user_id})" for name, user_id in failed]) if failed else ""
    )
    await remove_admin_cmd.finish(f"移除admin权限操作完成。{succeed_str}{failed_str}")


set_moderator_alc = Alconna(
    "set_moderator",
    Args["moderator_users", MultiVar(At, "+"), Field(completion=lambda: "请艾特一个或多个需要添加的moderator权限账号")],
)

set_moderator_cmd = on_alconna(
    command=set_moderator_alc,
    aliases={"添加吧务"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@set_moderator_cmd.handle()
async def handle_set_moderator(
    bot: Bot, event: GroupMessageEvent, moderator_users: Query[tuple[At, ...]] = AlconnaQuery("moderator_users", ())
):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    succeed = []
    failed = []
    try:
        users = [int(moderator_user.target) for moderator_user in moderator_users.result]
    except ValueError:
        await set_moderator_cmd.finish("无效的账号，请检查输入。")
    for moderator_user_id in users:
        if moderator_user_id in group_info.moderators:
            failed.append((
                await get_user_name(bot, event.group_id, moderator_user_id),
                moderator_user_id,
                "已位于moderator权限组中",
            ))
        elif moderator_user_id == group_info.master:
            failed.append((
                await get_user_name(bot, event.group_id, moderator_user_id),
                moderator_user_id,
                "已拥有吧主权限",
            ))
        elif moderator_user_id in group_info.admins:
            group_info.admins.remove(moderator_user_id)
            group_info.moderators.append(moderator_user_id)
            succeed.append((
                await get_user_name(bot, event.group_id, moderator_user_id),
                moderator_user_id,
                "已从admin权限组降级至moderator权限组",
            ))
        else:
            group_info.moderators.append(moderator_user_id)
            succeed.append((
                await get_user_name(bot, event.group_id, moderator_user_id),
                moderator_user_id,
                "已添加至moderator权限组",
            ))
    try:
        await GroupCache.update(event.group_id, admins=group_info.admins, moderators=group_info.moderators)
    except Exception as e:
        log.info(f"群聊 {event.group_id} 添加moderator权限失败：{e}")
        await set_moderator_cmd.finish("操作失败，请联系bot管理员。")
    succeed_str = (
        "\n以下账号操作成功：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in succeed])
        if succeed
        else ""
    )
    failed_str = (
        "\n以下账号操作失败：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in failed])
        if failed
        else ""
    )
    await set_moderator_cmd.finish(f"添加moderator权限操作完成。{succeed_str}{failed_str}")


remove_moderator_alc = Alconna(
    "remove_moderator",
    Args[
        "moderator_users",
        MultiVar(str, "+"),
        Field(
            completion=lambda: "请输入一个或多个（以空格分隔）需要移除的moderator权限账号。"
            "考虑到特殊情况，本操作不支持通过艾特进行。"
        ),
    ],
)

remove_moderator_cmd = on_alconna(
    command=remove_moderator_alc,
    aliases={"移除吧务"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_master),
    permission=permission.GROUP,
    priority=4,
    block=True,
)


@remove_moderator_cmd.handle()
async def handle_remove_moderator(
    bot: Bot, event: GroupMessageEvent, moderator_users: Query[tuple[At, ...]] = AlconnaQuery("moderator_users", ())
):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None  # for pylance
    succeed = []
    failed = []
    try:
        users = [int(moderator_user.target) for moderator_user in moderator_users.result]
    except ValueError:
        await remove_moderator_cmd.finish("无效的账号，请检查输入。")
    for moderator_user_id in users:
        if moderator_user_id not in group_info.moderators:
            failed.append((await get_user_name(bot, event.group_id, moderator_user_id), moderator_user_id))
        else:
            group_info.moderators.remove(moderator_user_id)
            succeed.append((await get_user_name(bot, event.group_id, moderator_user_id), moderator_user_id))
    try:
        await GroupCache.update(event.group_id, moderators=group_info.moderators)
    except Exception as e:
        log.info(f"群聊 {event.group_id} 移除moderator权限失败：{e}")
        await remove_moderator_cmd.finish("操作失败，请联系bot管理员。")
    succeed_str = (
        "\n以下账号操作成功：" + ", ".join([f"{name}({user_id})" for name, user_id in succeed]) if succeed else ""
    )
    failed_str = (
        "\n以下账号操作失败：" + ", ".join([f"{name}({user_id})" for name, user_id in failed]) if failed else ""
    )
    await remove_moderator_cmd.finish(f"移除moderator权限操作完成。{succeed_str}{failed_str}")


set_BDUSS_alc = Alconna(  # noqa: N816
    "set_BDUSS",
    Args["group_id_str", str, Field(completion=lambda: "请输入群号")],
)

set_BDUSS_cmd = on_alconna(  # noqa: N816
    command=set_BDUSS_alc,
    aliases={"设置BDUSS", "删除BDUSS", "设置STOKEN", "删除STOKEN"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    permission=permission.PRIVATE,
    priority=3,
    block=True,
)


@set_BDUSS_cmd.handle()
async def handle_set_BDUSS(  # noqa: N802
    event: PrivateMessageEvent,
    group_id_str: Match[str],
    args: Arparma,
):
    try:
        group_id = int(group_id_str.result.strip())
    except ValueError:
        await set_BDUSS_cmd.finish("无效的群号，请检查输入。")
    group_info = await GroupCache.get(group_id)
    if group_info is None:
        await set_BDUSS_cmd.finish("该群未初始化或群号错误，请检查输入。")
    if event.sender.user_id not in [group_info.master, *group_info.admins, *group_info.moderators]:
        await set_BDUSS_cmd.finish("您没有该群的吧主、admin或moderator权限。")
    cmd = args.context["$shortcut.regex_match"].group()[1:]
    if "设置" in cmd:
        msg: UniMessage | None = await set_BDUSS_cmd.prompt(f"请输入{cmd[2:]}")
        if not msg:
            await set_BDUSS_cmd.finish("无效的输入。")
        value = str(msg).strip()
        if "BDUSS" in cmd:
            async with Client(value) as client:
                if not await client.get_self_info():
                    await set_BDUSS_cmd.finish("BDUSS无效，请检查输入。")
            if event.sender.user_id == group_info.master:
                await GroupCache.update(group_id, master_BDUSS=value)
                await set_BDUSS_cmd.finish("吧主BDUSS设置成功。")
            else:
                await GroupCache.update(group_id, slave_BDUSS=value)
                await set_BDUSS_cmd.finish("吧务BDUSS设置成功。")
        else:
            await GroupCache.update(group_id, slave_STOKEN=value)
            await set_BDUSS_cmd.finish("吧务STOKEN设置成功。")
    elif "删除" in cmd:
        if "BDUSS" in cmd:
            if event.sender.user_id == group_info.master:
                await GroupCache.update(group_id, master_BDUSS="")
                await set_BDUSS_cmd.finish("吧主BDUSS删除成功。")
            else:
                await GroupCache.update(group_id, slave_BDUSS="")
                await set_BDUSS_cmd.finish("吧务BDUSS删除成功。")
        else:
            await GroupCache.update(group_id, slave_STOKEN="")
            await set_BDUSS_cmd.finish("吧务STOKEN删除成功。")


friend_request = on_request(
    rule=Rule(rule_member),
    priority=2,
    block=True,
)


@friend_request.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    await event.approve(bot)
