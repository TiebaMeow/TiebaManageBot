from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Literal

from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher, current_matcher

from src.db.crud import get_group

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def require_bduss(kind: Literal["slave", "master", "STOKEN"]):
    def decorator(func: Callable[..., Awaitable[object]]) -> Callable[..., Awaitable[object]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            event = kwargs.get("event") or next((a for a in args if isinstance(a, GroupMessageEvent)), None)
            matcher = kwargs.get("matcher") or next((a for a in args if isinstance(a, Matcher)), None)

            if matcher is None:
                try:
                    matcher = current_matcher.get()
                except LookupError:
                    pass

            if event is None or matcher is None:
                # 注入失败时不阻断流程
                return await func(*args, **kwargs)

            try:
                group_info = await get_group(event.group_id)
            except KeyError:
                await matcher.finish()
                return await func(*args, **kwargs)

            required = ""
            kind_str = ""
            if kind == "slave":
                kind_str = "吧务BDUSS"
                required = group_info.slave_bduss
            elif kind == "master":
                kind_str = "吧主BDUSS"
                required = group_info.master_bduss
            elif kind == "STOKEN":
                kind_str = "吧务STOKEN"
                required = group_info.slave_stoken

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
