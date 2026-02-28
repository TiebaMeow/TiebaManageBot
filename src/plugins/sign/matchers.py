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
from nonebot.rule import Rule
from nonebot_plugin_alconna import AlconnaQuery, Arparma, At, Field, Match, Query, UniMessage, on_alconna

from src.utils import (
    rule_master,
    rule_member,
    rule_owner,
    rule_signed,
)

from . import service

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
    tieba_name = tieba_name_str.result.removesuffix("吧")
    if not (user_id := event.sender.user_id):
        await sign_cmd.finish()
    msg = await service.init_group(event.group_id, user_id, tieba_name)
    await sign_cmd.finish(msg)


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
    msg = await service.set_master(event.group_id, master_user_id, bot)
    await master_cmd.finish(msg)


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
async def handle_reset():
    await reset_cmd.send(
        "重置操作将删除本群的权限设置、BDUSS等配置信息，循封名单、关联信息将会保留，"
        "如果管理群或贴吧改变可联系bot管理员操作转移或导出。\n\n"
        "请认真阅读以上说明，确定重置请发送“确定”，取消请发送任意内容。"
    )


@reset_cmd.receive("confirm")
async def handle_reset_confirm(confirm: GroupMessageEvent = Received("confirm")):
    if confirm.get_plaintext() != "确定":
        await reset_cmd.finish("操作已取消。")
    await service.reset_group(confirm.group_id)
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
    users = [int(admin_user.target) for admin_user in admin_users.result]
    try:
        succeeded, failed = await service.set_admin(event.group_id, users, bot)
    except Exception:
        await set_admin_cmd.finish("操作失败，请联系bot管理员。")

    succeeded_str = (
        "\n以下账号操作成功：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in succeeded])
        if succeeded
        else ""
    )
    failed_str = (
        "\n以下账号操作失败：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in failed])
        if failed
        else ""
    )
    await set_admin_cmd.finish(f"添加admin权限操作完成。{succeeded_str}{failed_str}")


remove_admin_alc = Alconna(
    "remove_admin",
    Args[
        "admin_users",
        MultiVar(str, "+"),
        Field(
            completion=lambda: (
                "请输入一个或多个（以空格分隔）需要移除的admin权限账号。考虑到特殊情况，本操作不支持通过艾特进行。"
            )
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
    try:
        users = [int(admin_user) for admin_user in admin_users.result]
    except ValueError:
        await remove_admin_cmd.finish("无效的账号，请检查输入。")

    try:
        succeeded, failed = await service.remove_admin(event.group_id, users, bot)
    except Exception:
        await remove_admin_cmd.finish("操作失败，请联系bot管理员。")

    succeed_str = (
        "\n以下账号操作成功：" + ", ".join([f"{name}({user_id})" for name, user_id in succeeded]) if succeeded else ""
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
    try:
        users = [int(moderator_user.target) for moderator_user in moderator_users.result]
    except ValueError:
        await set_moderator_cmd.finish("无效的账号，请检查输入。")

    try:
        succeeded, failed = await service.set_moderator(event.group_id, users, bot)
    except Exception:
        await set_moderator_cmd.finish("操作失败，请联系bot管理员。")

    succeeded_str = (
        "\n以下账号操作成功：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in succeeded])
        if succeeded
        else ""
    )
    failed_str = (
        "\n以下账号操作失败：\n" + "\n".join([f"{name}({user_id})：{reason}" for name, user_id, reason in failed])
        if failed
        else ""
    )
    await set_moderator_cmd.finish(f"添加moderator权限操作完成。{succeeded_str}{failed_str}")


remove_moderator_alc = Alconna(
    "remove_moderator",
    Args[
        "moderator_users",
        MultiVar(str, "+"),
        Field(
            completion=lambda: (
                "请输入一个或多个（以空格分隔）需要移除的moderator权限账号。考虑到特殊情况，本操作不支持通过艾特进行。"
            )
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
    try:
        users = [int(moderator_user.target) for moderator_user in moderator_users.result]
    except ValueError:
        await remove_moderator_cmd.finish("无效的账号，请检查输入。")

    try:
        succeeded, failed = await service.remove_moderator(event.group_id, users, bot)
    except Exception:
        await remove_moderator_cmd.finish("操作失败，请联系bot管理员。")

    succeeded_str = (
        "\n以下账号操作成功：" + ", ".join([f"{name}({user_id})" for name, user_id in succeeded]) if succeeded else ""
    )
    failed_str = (
        "\n以下账号操作失败：" + ", ".join([f"{name}({user_id})" for name, user_id in failed]) if failed else ""
    )
    await remove_moderator_cmd.finish(f"移除moderator权限操作完成。{succeeded_str}{failed_str}")


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

    cmd = args.context["$shortcut.regex_match"].group()[1:]
    value = None

    if "设置" in cmd:
        msg: UniMessage | None = await set_BDUSS_cmd.prompt(f"请输入{cmd[2:]}")
        if not msg:
            await set_BDUSS_cmd.finish("无效的输入。")
        value = str(msg).strip()

    final_msg = await service.set_bduss(group_id, event.sender.user_id, cmd, value)
    await set_BDUSS_cmd.finish(final_msg)


friend_request = on_request(
    rule=Rule(rule_member),
    priority=2,
    block=True,
)


@friend_request.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    await event.approve(bot)
