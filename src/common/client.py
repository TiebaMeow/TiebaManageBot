from __future__ import annotations

import asyncio
from functools import wraps
from typing import TYPE_CHECKING, Any

import aiotieba as tb
from aiotieba.exception import HTTPStatusError, TiebaServerError
from cashews import Cache
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_exponential_jitter

from logger import log

if TYPE_CHECKING:
    from aiotieba.api.get_user_contents._classdef import UserPostss, UserThreads


class NeedRetryError(Exception):
    pass


cache = Cache()
cache.setup("mem://")


def with_ensure(func):
    @wraps(func)
    async def wrapper(self: Client, *args, **kwargs) -> Any:
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
                    NeedRetryError,
                )),
                reraise=True,
            ):
                with attempt:
                    ret = await func(self, *args, **kwargs)
                    # async with self.semaphore:
                    #     ret = await func(self, *args, **kwargs)

                    err = getattr(ret, "err", None)
                    if err is not None:
                        if isinstance(err, (HTTPStatusError, TiebaServerError)):
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
                                300000,
                                1989005,
                                2210002,
                                28113295,
                            }:
                                raise err
                        else:
                            log.exception(f"{func.__name__} returned error: {err}")
                    return ret
        except Exception as e:
            log.exception(f"{func.__name__}: {e}")
            return await func(self, *args, **kwargs)
            # async with self.semaphore:
            #     return await func(self, *args, **kwargs)

    return wrapper


class Client(tb.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._semaphore = asyncio.Semaphore(10)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    async def __aenter__(self) -> Client:
        await super().__aenter__()
        return self

    async def __aexit__(self, exc_type=None, exc_val=None, exc_tb=None):
        await super().__aexit__(exc_type, exc_val, exc_tb)

    @with_ensure
    async def get_posts(self, *args, **kwargs):
        return await super().get_posts(*args, **kwargs)

    @with_ensure
    async def get_user_info(self, *args, **kwargs):
        return await super().get_user_info(*args, **kwargs)

    @with_ensure
    async def del_thread(self, *args, **kwargs):
        return await super().del_thread(*args, **kwargs)

    @with_ensure
    async def del_post(self, *args, **kwargs):
        return await super().del_post(*args, **kwargs)

    @with_ensure
    async def tieba_uid2user_info(self, *args, **kwargs):
        ret = await super().tieba_uid2user_info(*args, **kwargs)
        if ret.user_id == 0:
            raise NeedRetryError("tieba_uid2user_info returned user_id 0")
        return ret

    @with_ensure
    async def add_bawu_blacklist(self, *args, **kwargs):
        return await super().add_bawu_blacklist(*args, **kwargs)

    @with_ensure
    async def del_bawu_blacklist(self, *args, **kwargs):
        return await super().del_bawu_blacklist(*args, **kwargs)

    @with_ensure
    async def block(self, *args, **kwargs):
        return await super().block(*args, **kwargs)

    @with_ensure
    async def unblock(self, *args, **kwargs):
        return await super().unblock(*args, **kwargs)

    @with_ensure
    async def good(self, *args, **kwargs):
        return await super().good(*args, **kwargs)

    @with_ensure
    async def ungood(self, *args, **kwargs):
        return await super().ungood(*args, **kwargs)

    @with_ensure
    async def top(self, *args, **kwargs):
        return await super().top(*args, **kwargs)

    @with_ensure
    async def untop(self, *args, **kwargs):
        return await super().untop(*args, **kwargs)

    @with_ensure
    async def get_self_info(self, *args, **kwargs):
        return await super().get_self_info(*args, **kwargs)

    @with_ensure
    async def get_user_threads(self, *args, **kwargs):
        return await super().get_user_threads(*args, **kwargs)

    @with_ensure
    async def get_threads(self, *args, **kwargs):
        return await super().get_threads(*args, **kwargs)

    @with_ensure
    async def get_comments(self, *args, **kwargs):
        return await super().get_comments(*args, **kwargs)

    @with_ensure
    async def get_fid(self, *args, **kwargs):
        return await super().get_fid(*args, **kwargs)


@cache(ttl=180, key="get_user_threads_cached:{user_id}:{pn}")
async def get_user_threads_cached(client: Client, user_id: int, pn: int) -> UserThreads:
    return await client.get_user_threads(user_id, pn=pn)


@cache(ttl=180, key="get_user_posts_cached:{user_id}:{pn}:{rn}")
async def get_user_posts_cached(client: Client, user_id: int, pn: int, rn: int) -> UserPostss:
    return await client.get_user_posts(user_id, pn=pn, rn=rn)
