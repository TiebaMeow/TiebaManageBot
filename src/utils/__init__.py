import re
import textwrap
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path
from typing import Literal

from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import FriendRequestEvent, GroupMessageEvent
from nonebot_plugin_alconna import AlconnaMatcher

from src.common import Client
from src.db import ChromiumCache, GroupCache


async def rule_owner(bot: Bot, event: GroupMessageEvent) -> bool:
    group_member_list: list = await bot.call_api("get_group_member_list", group_id=event.group_id)
    return any(item["role"] == "owner" and item["user_id"] == event.sender.user_id for item in group_member_list)


async def is_master(user_id: int, group_id: int) -> bool:
    group_info = await GroupCache.get(group_id)
    if group_info is None:
        return False
    return user_id == group_info.master


async def is_admin(user_id: int, group_id: int) -> bool:
    group_info = await GroupCache.get(group_id)
    if group_info is None:
        return False
    return user_id in group_info.admins or await is_master(user_id, group_id)


async def is_moderator(user_id: int, group_id: int) -> bool:
    group_info = await GroupCache.get(group_id)
    if group_info is None:
        return False
    return user_id in group_info.moderators or await is_admin(user_id, group_id)


async def rule_reply(event: GroupMessageEvent) -> bool:
    return bool(event.reply)


async def rule_master(event: GroupMessageEvent) -> bool:
    if not event.sender.user_id:
        return False
    return await is_master(event.sender.user_id, event.group_id)


async def rule_admin(event: GroupMessageEvent) -> bool:
    if not event.sender.user_id:
        return False
    return await is_admin(event.sender.user_id, event.group_id)


async def rule_moderator(event: GroupMessageEvent) -> bool:
    if not event.sender.user_id:
        return False
    return await is_moderator(event.sender.user_id, event.group_id)


async def rule_signed(event: GroupMessageEvent) -> bool:
    group_info = await GroupCache.get(event.group_id)
    return group_info is not None


async def rule_member(event: FriendRequestEvent) -> bool:
    user_id = event.user_id
    group_infos = await GroupCache.all()
    for group_info in group_infos:
        if user_id in group_info.admins or user_id in group_info.moderators or user_id == group_info.master:
            return True
    return False


def require_bduss(kind: Literal["slave", "master", "STOKEN"]):
    def decorator(func: Callable[..., Awaitable[object]]) -> Callable[..., Awaitable[object]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            event = kwargs.get("event") or next((a for a in args if isinstance(a, GroupMessageEvent)), None)
            matcher = kwargs.get("matcher") or next((a for a in args if isinstance(a, AlconnaMatcher)), None)

            if event is None or matcher is None:
                # 注入失败时不阻断流程
                return await func(*args, **kwargs)

            group_info = await GroupCache.get(event.group_id)
            if not group_info:
                await matcher.finish()
            assert group_info is not None  # for pylance
            if kind == "slave":
                kind_str = "吧务BDUSS"
                required = group_info.slave_BDUSS
            elif kind == "master":
                kind_str = "吧主BDUSS"
                required = group_info.master_BDUSS
            elif kind == "STOKEN":
                kind_str = "吧务STOKEN"
                required = group_info.slave_STOKEN

            if not required:
                await matcher.finish(f"未设置用于处理的{kind_str}。")

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_slave_BDUSS(func: Callable[..., Awaitable[object]] | None = None):  # noqa: N802
    decorator = require_bduss("slave")
    if func is None:
        return decorator
    return decorator(func)


def require_master_BDUSS(func: Callable[..., Awaitable[object]] | None = None):  # noqa: N802
    decorator = require_bduss("master")
    if func is None:
        return decorator
    return decorator(func)


def require_STOKEN(func: Callable[..., Awaitable[object]] | None = None):  # noqa: N802
    decorator = require_bduss("STOKEN")
    if func is None:
        return decorator
    return decorator(func)


async def get_user_name(bot: Bot, group_id: int, user_id: int) -> str | None:
    try:
        username = (await bot.call_api("get_group_member_info", group_id=group_id, user_id=user_id)).get("card_new", "")
        if not username:
            username = (await bot.call_api("get_stranger_info", user_id=user_id)).get("nickname", "")
    except Exception:
        return None
    else:
        return username


async def text_to_image(text: str, font_size: int = 20) -> bytes:
    if ChromiumCache.context is None:
        await ChromiumCache.initialize()
    context = ChromiumCache.context
    assert context is not None

    wrapped_text = ""
    for line in text.split("\n"):
        wrapped_line = textwrap.fill(line, width=48)
        wrapped_text += wrapped_line + "\n"

    lines = wrapped_text.split("\n")[:-1]

    if not lines:
        return b""

    def add_indent(line):
        return "  " + line if (not line.startswith("  - ") and not line.endswith("吧：")) else line

    lines = list(map(add_indent, lines))
    line_str = "\n".join(lines)

    # 构建字体文件的绝对路径
    font_path = Path(__file__).parent.parent.parent / "static" / "font" / "NotoSansSC-Regular.ttf"
    font_url = font_path.as_uri()

    html_content = f"""
    <html>
        <head>
            <style>
                @font-face {{
                    font-family: "NotoSansSC";
                    src: url("{font_url}") format("truetype");
                    font-display: block;
                    unicode-range: U+4E00-9FFF, U+3400-4DBF, U+20000-2A6DF, U+2A700-2B73F, U+2B740-2B81F, U+2B820-2CEAF, U+F900-FAFF, U+2F800-2FA1F;
                }}
                body {{
                    font-family: "NotoSansSC", "Noto Sans CJK SC";
                    font-size: {font_size}px;
                    line-height: {font_size + 2}px;
                    margin: 0;
                    padding: 0;
                    font-variant-east-asian: normal;
                    font-feature-settings: "locl" 1;
                    text-rendering: optimizeLegibility;
                    -webkit-font-feature-settings: "locl" 1;
                    -moz-font-feature-settings: "locl" 1;
                    lang: zh-CN;
                }}
                pre {{
                    margin-left: 10px;
                    margin-top: 10px;
                    display: inline-block;
                    white-space: pre;
                    font-family: inherit;
                }}
            </style>
        </head>
        <body>
            <pre>{line_str}</pre>
        </body>
    </html>
    """  # noqa: E501

    page = await context.new_page()
    await page.set_content(html_content)

    pre_width = await page.evaluate("""() => {
        const pre = document.querySelector('pre');
        return pre.offsetWidth + 20; // 包含边距
    }""")
    pre_height = await page.evaluate("""() => {
        const pre = document.querySelector('pre');
        return pre.offsetHeight + 20;
    }""")

    await page.set_viewport_size({"width": pre_width, "height": pre_height})
    screenshot = await page.screenshot(type="jpeg", quality=75, path=None)
    await page.close()

    return screenshot


async def get_tieba_user_info(tieba_uid: int, client: Client) -> UserInfo_TUid:
    user_info = await client.tieba_uid2user_info(tieba_uid)
    return user_info


async def handle_tieba_uid(tieba_uid_str: str, client: Client | None = None) -> int:
    if tieba_uid_str.startswith("tb."):
        if client is None:
            async with Client() as client:
                user_info = await client.get_user_info(tieba_uid_str)
        else:
            user_info = await client.get_user_info(tieba_uid_str)
        if user_info:
            return user_info.tieba_uid
        else:
            return 0
    if tieba_uid_str.isdigit():
        return int(tieba_uid_str)
    match = re.search(r"#(\d+)#", tieba_uid_str)
    if match:
        return int(match.group(1))
    else:
        return 0


async def handle_tieba_uids(tieba_uid_strs: tuple[str, ...]) -> list[int]:
    async with Client() as client:
        results = [await handle_tieba_uid(uid_str, client) for uid_str in tieba_uid_strs]
    return results


def handle_thread_url(thread_url: str) -> int:
    if thread_url.isdigit():
        return int(thread_url)
    match = re.search(r"tieba.baidu.com/p/(\d+)", thread_url)
    if match:
        return int(match.group(1))
    else:
        return 0


def handle_thread_urls(thread_urls: tuple[str, ...]) -> list[int]:
    return [handle_thread_url(url) for url in thread_urls][:30]


def handle_post_url(post_url: str) -> tuple[int, int]:
    match = re.search(r"tieba.baidu.com/p/(\d+)\?.+post_id=(\d+)", post_url)
    if match:
        return int(match.group(1)), int(match.group(2))
    else:
        return 0, 0


def handle_post_urls(post_urls: tuple[str, ...]) -> list[tuple[int, int]]:
    return [handle_post_url(url) for url in post_urls][:30]
