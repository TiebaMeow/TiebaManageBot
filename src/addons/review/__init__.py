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
from sqlalchemy import exists, select

from logger import log
from src.common import Client
from src.db import (
    Associated,
    AutoBanList,
    BanList,
    DBInterface,
    GroupCache,
    GroupInfo,
    ImageUtils,
    ReviewConfig,
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


add_keyword_alc = Alconna(
    "add_keyword",
    Args[
        "keywords", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个关键词，以空格分隔，支持正则表达式。")
    ],
)

add_keyword_cmd = on_alconna(
    command=add_keyword_alc,
    aliases={"添加关键词"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_keyword_cmd.handle()
async def add_keyword_handle(
    bot: Bot,
    event: GroupMessageEvent,
    state: T_State,
    raw_keywords: Query[tuple[str, ...]] = AlconnaQuery("keywords", ()),
):
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None
    keywords = list(set(raw_keywords.result))
    async with DBInterface.get_session() as session:
        existing_keywords = await session.execute(
            select(ReviewConfig.rule_content).where(
                ReviewConfig.fid == group_info.fid,
                ReviewConfig.rule_type == "关键词",
                ReviewConfig.rule_content.in_(keywords),
            )
        )
        existing_keywords = list(existing_keywords.scalars().all())
        if existing_keywords:
            await add_keyword_cmd.send(f"以下关键词已存在：{'，'.join(existing_keywords)}")
        new_keywords = set(keywords) - set(existing_keywords)
        batch_type = ""
        for keyword in new_keywords:
            if not batch_type:
                confirm = await add_keyword_cmd.prompt(
                    f"请发送相应字母选择关键词“{keyword}”的处理方式"
                    + "，发送相应大写字母批量设置所有关键词的处理方式：\n"
                    if len(new_keywords) > 1
                    else "：\n" + "：a. 直接删除\nb. 删除并通知\nc. 仅通知\n发送其他内容取消操作。",
                    timeout=60,
                )
                if confirm is None:
                    await add_keyword_cmd.finish("操作超时，已取消。")
                confirm_text = confirm.extract_plain_text().strip()
                if confirm_text in ["A", "B", "C"]:
                    batch_type = confirm_text.lower()
                    confirm_text = batch_type
            else:
                confirm_text = batch_type
            if confirm_text == "a":
                notify_type = "直接删除"
            elif confirm_text == "b":
                notify_type = "删除并通知"
            elif confirm_text == "c":
                notify_type = "仅通知"
            else:
                await add_keyword_cmd.finish("操作已取消。")
            config = ReviewConfig(
                fid=group_info.fid,
                group_id=group_info.group_id,
                rule_type="keyword",
                notify_type=notify_type,
                rule_content=keyword,
            )
            session.add(config)
            await session.commit()

    if new_keywords:
        await add_keyword_cmd.finish(f"已成功添加关键词：{'，'.join(new_keywords)}")


add_user_alc = Alconna(
    "add_user",
    Args["users", MultiVar(str, "+"), Field(completion=lambda: "请输入一个或多个贴吧ID，以空格分隔。")],
)

add_user_cmd = on_alconna(
    command=add_user_alc,
    aliases={"添加监控用户"},
    comp_config={"lite": True},
    use_cmd_start=True,
    use_cmd_sep=True,
    rule=Rule(rule_signed, rule_admin),
    permission=permission.GROUP,
    priority=5,
    block=True,
)


@add_user_cmd.handle()
async def add_user_handle(
    bot: Bot,
    event: GroupMessageEvent,
    state: T_State,
    tieba_uid_strs: Query[tuple[str, ...]] = AlconnaQuery("users", ()),
):
    tieba_uids = await handle_tieba_uids(tieba_uid_strs.result)
    if 0 in tieba_uids:
        await add_user_cmd.finish("参数中包含无法解析的贴吧ID，请检查输入。")
    group_info = await GroupCache.get(event.group_id)
    assert group_info is not None
    raw_users = {}
    async with Client(try_ws=True) as client:
        for tieba_uid in tieba_uids:
            user_info = await client.tieba_uid2user_info(tieba_uid)
            if user_info.user_id == 0:
                await add_user_cmd.send(f"暂时无法获取贴吧ID为 {tieba_uid} 的用户信息，请重试。")
                continue
            raw_users[str(user_info.user_id)] = f"{user_info.nick_name}({user_info.tieba_uid})"
    async with DBInterface.get_session() as session:
        existing_users = await session.execute(
            select(ReviewConfig.rule_content).where(
                ReviewConfig.fid == group_info.fid,
                ReviewConfig.rule_type == "监控用户",
                ReviewConfig.rule_content.in_(raw_users.keys()),
            )
        )
        existing_users = list(existing_users.scalars().all())
        if existing_users:
            existing_user_strs = [raw_users[user] for user in existing_users]
            await add_user_cmd.send(f"以下用户已存在：{'，'.join(existing_user_strs)}")
        new_users = set(raw_users.keys()) - set(existing_users)
        batch_type = ""
        for user in new_users:
            if not batch_type:
                confirm = await add_user_cmd.prompt(
                    f"请发送相应字母选择监控用户“{user}”的处理方式"
                    + "，发送相应大写字母批量设置所有监控用户的处理方式：\n"
                    if len(new_users) > 1
                    else "：\n" + "：a. 直接删除\nb. 删除并通知\nc. 仅通知\n发送其他内容取消操作。",
                    timeout=60,
                )
                if confirm is None:
                    await add_user_cmd.finish("操作超时，已取消。")
                confirm_text = confirm.extract_plain_text().strip()
                if confirm_text in ["A", "B", "C"]:
                    batch_type = confirm_text.lower()
                    confirm_text = batch_type
            else:
                confirm_text = batch_type
            if confirm_text == "a":
                notify_type = "直接删除"
            elif confirm_text == "b":
                notify_type = "删除并通知"
            elif confirm_text == "c":
                notify_type = "仅通知"
            else:
                await add_user_cmd.finish("操作已取消。")
            config = ReviewConfig(
                fid=group_info.fid,
                group_id=group_info.group_id,
                rule_type="监控用户",
                notify_type=notify_type,
                rule_content=user,
            )
            session.add(config)
            await session.commit()

    if new_users:
        await add_user_cmd.finish(f"已成功添加监控用户：{'，'.join(new_users)}")
