from __future__ import annotations

import asyncio
from functools import wraps
from inspect import iscoroutinefunction as awaitable
from typing import TYPE_CHECKING, Any

import aiotieba as tb
from aiotieba.exception import HTTPStatusError, TiebaServerError
from cashews import Cache
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_exponential_jitter

from logger import log

if TYPE_CHECKING:
    from aiotieba.api.get_user_contents._classdef import UserPostss, UserThreads

cache = Cache()
cache.setup("mem://")


class Client(tb.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rl_wrapper_cache: dict[str, Any] = {}

    def __getattribute__(self, name: str) -> Any:
        _oget = object.__getattribute__
        attr = _oget(self, name) if name not in {"__dict__", "__class__"} else super().__getattribute__(name)

        if name.startswith("_"):
            return attr

        is_coro = awaitable(attr) or (hasattr(attr, "__func__") and awaitable(attr.__func__))
        if not is_coro:
            return attr

        wrapper_cache = _oget(self, "_rl_wrapper_cache") if "_rl_wrapper_cache" in _oget(self, "__dict__") else None
        if isinstance(wrapper_cache, dict) and name in wrapper_cache:
            return wrapper_cache[name]

        @wraps(attr)
        async def retry_wrapper(*args, **kwargs) -> Any:
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(3),
                    wait=wait_exponential_jitter(initial=0.5, max=3.0),
                    retry=retry_if_exception_type((
                        asyncio.TimeoutError,
                        ConnectionError,
                        OSError,
                        HTTPStatusError,
                        TiebaServerError,
                    )),
                    reraise=True,
                ):
                    with attempt:
                        ret = await attr(*args, **kwargs)
                        err = getattr(ret, "err", None)
                        if err and isinstance(err, (HTTPStatusError, TiebaServerError)):
                            code = getattr(err, "code", None)
                            if code is not None and code in {
                                -65536,
                                11,
                                77,
                                408,
                                429,
                                4011,
                                110001,
                                220034,
                                230871,
                                1989005,
                                2210002,
                                28113295,
                            }:
                                raise err
                        return ret
            except Exception as e:
                log.exception(f"{name}: {e}")
                return await attr(*args, **kwargs)

        if isinstance(wrapper_cache, dict):
            wrapper_cache[name] = retry_wrapper
        return retry_wrapper

    async def __aenter__(self) -> Client:
        await super().__aenter__()
        return self

    async def __aexit__(self, exc_type=None, exc_val=None, exc_tb=None):
        await super().__aexit__(exc_type, exc_val, exc_tb)


@cache(ttl=180, key="get_user_threads_cached:{user_id}:{pn}")
async def get_user_threads_cached(client: Client, user_id: int, pn: int) -> UserThreads:
    return await client.get_user_threads(user_id, pn=pn)


@cache(ttl=180, key="get_user_posts_cached:{user_id}:{pn}:{rn}")
async def get_user_posts_cached(client: Client, user_id: int, pn: int, rn: int) -> UserPostss:
    return await client.get_user_posts(user_id, pn=pn, rn=rn)
