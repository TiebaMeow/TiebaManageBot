from __future__ import annotations

from asyncio import Semaphore
from typing import TYPE_CHECKING

from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid
from tiebameow.client import Client

if TYPE_CHECKING:
    from aiotieba.api.get_user_contents._classdef import UserPostss, UserThreads


from src.db.crud import get_group

from .disk_cache import disk_cache
from .ttl_cache import TTLCache

in_memory_cache = TTLCache(capacity=1000, default_ttl=300)


class ClientCache:
    """
    贴吧客户端缓存

    提供匿名客户端、吧务账号客户端、含stoken的吧务账号客户端和吧主账号客户端的缓存和管理功能。

    Attributes:
        _client (Client | None): 匿名客户端实例。
        _bawu_clients (dict[int, Client] | None): 各群吧务账号客户端缓存。
        _stoken_clients (dict[int, Client] | None): 各群含stoken的吧务账号客户端缓存。
        _master_clients (dict[int, Client] | None): 各群吧主账号客户端缓存。
        _semaphore (Semaphore | None): 控制并发请求的信号量。
    """

    _client: Client | None = None
    _bawu_clients: dict[int, Client] | None = None
    _stoken_clients: dict[int, Client] | None = None
    _master_clients: dict[int, Client] | None = None
    _semaphore: Semaphore | None = None

    @classmethod
    async def get_client(cls) -> Client:
        """获取匿名客户端实例。"""
        if not cls._client:
            cls._client = Client(try_ws=True)
            await cls._client.__aenter__()
        return cls._client

    @classmethod
    async def get_bawu_client(cls, group_id: int) -> Client:
        """获取吧务账号客户端实例。"""
        if cls._bawu_clients is None:
            cls._bawu_clients = {}
        if cls._semaphore is None:
            cls._semaphore = Semaphore(10)

        if group_id in cls._bawu_clients:
            return cls._bawu_clients[group_id]

        group = await get_group(group_id)
        if not group:
            raise ValueError("No group found")

        client = Client(
            group.slave_bduss,
            semaphore=cls._semaphore,
            retry_attempts=5,
        )
        await client.__aenter__()
        cls._bawu_clients[group_id] = client

        return client

    @classmethod
    async def get_stoken_client(cls, group_id: int) -> Client:
        """获取含stoken的吧务账号客户端实例。"""
        if cls._stoken_clients is None:
            cls._stoken_clients = {}
        if cls._semaphore is None:
            cls._semaphore = Semaphore(10)

        if group_id in cls._stoken_clients:
            return cls._stoken_clients[group_id]

        group = await get_group(group_id)
        if not group:
            raise ValueError("No group found")

        client = Client(
            group.slave_bduss,
            group.slave_stoken,
            semaphore=cls._semaphore,
            retry_attempts=5,
        )
        await client.__aenter__()
        cls._stoken_clients[group_id] = client
        return client

    @classmethod
    async def get_master_client(cls, group_id: int) -> Client:
        """获取吧主账号客户端实例。"""
        if cls._master_clients is None:
            cls._master_clients = {}
        if cls._semaphore is None:
            cls._semaphore = Semaphore(10)

        if group_id in cls._master_clients:
            return cls._master_clients[group_id]

        group = await get_group(group_id)
        if not group:
            raise ValueError("No group found")

        client = Client(
            group.master_bduss,
            semaphore=cls._semaphore,
            retry_attempts=5,
        )
        await client.__aenter__()
        cls._master_clients[group_id] = client

        return client

    @classmethod
    async def refresh_client(cls, group_id: int):
        """刷新指定群的客户端实例。"""
        if cls._bawu_clients and group_id in cls._bawu_clients:
            await cls._bawu_clients[group_id].__aexit__()
            del cls._bawu_clients[group_id]

        if cls._stoken_clients and group_id in cls._stoken_clients:
            await cls._stoken_clients[group_id].__aexit__()
            del cls._stoken_clients[group_id]

        if cls._master_clients and group_id in cls._master_clients:
            await cls._master_clients[group_id].__aexit__()
            del cls._master_clients[group_id]

    @classmethod
    async def stop(cls):
        """关闭并清理所有客户端实例。"""
        if cls._client is not None:
            await cls._client.__aexit__()
            cls._client = None

        if cls._bawu_clients is not None:
            for client in cls._bawu_clients.values():
                await client.__aexit__()
            cls._bawu_clients = None

        if cls._stoken_clients is not None:
            for client in cls._stoken_clients.values():
                await client.__aexit__()
            cls._stoken_clients = None

        if cls._master_clients is not None:
            for client in cls._master_clients.values():
                await client.__aexit__()
            cls._master_clients = None

        await in_memory_cache.close()


async def tieba_uid2user_info_cached(client: Client, tieba_uid: int) -> UserInfo_TUid:
    key = f"tieba_uid2user_info_cached:{tieba_uid}"
    if ret := await in_memory_cache.get(key):
        return ret
    try:
        ret = await client.tieba_uid2user_info(tieba_uid)
    except Exception:
        return UserInfo_TUid()
    await in_memory_cache.set(key, ret, ttl=300)
    return ret


async def get_user_threads_cached(client: Client, user_id: int, pn: int) -> UserThreads:
    key = f"get_user_threads_cached:{user_id}:{pn}"
    if ret := await in_memory_cache.get(key):
        return ret
    ret = await client.get_user_threads(user_id, pn=pn)
    await in_memory_cache.set(key, ret, ttl=180)
    return ret


async def get_user_posts_cached(client: Client, user_id: int, pn: int, rn: int) -> UserPostss:
    key = f"get_user_posts_cached:{user_id}:{pn}:{rn}"
    if ret := await in_memory_cache.get(key):
        return ret
    ret = await client.get_user_posts(user_id, pn=pn, rn=rn)
    await in_memory_cache.set(key, ret, ttl=180)
    return ret


async def get_tieba_name(fid: int) -> str:
    key = f"tb:fid:{fid}"
    if name := await disk_cache.get(key):
        return name

    err_key = f"tb:err:{fid}"
    if await disk_cache.exists(err_key):
        return ""

    client = await ClientCache.get_client()
    name = await client.get_fname(fid)

    if name:
        await disk_cache.set(key, name)
    else:
        await disk_cache.set(err_key, 1, expire=5)

    return name
