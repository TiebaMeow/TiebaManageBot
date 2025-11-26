import asyncio
from pathlib import Path

from cashews import Cache
from sqlalchemy import select
from sqlalchemy import update as _update

from src.common import Client

from .interface import DBInterface
from .models import GroupInfo

__all__ = ["GroupCache", "TiebaNameCache", "AppealCache"]

CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


tiebaname_cache = Cache()
tiebaname_cache.setup(f"disk://?directory={CACHE_DIR.resolve().as_posix()}/tieba_name_cache&shards=0")
appeal_cache = Cache()
appeal_cache.setup(f"disk://?directory={CACHE_DIR.resolve().as_posix()}/appeal_cache&shards=0")


class GroupCache:
    _cache: dict[int, GroupInfo] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def load_data(cls):
        async with cls._lock:
            async with DBInterface.get_session() as session:
                docs = await session.execute(select(GroupInfo))
                docs = docs.scalars().all()
                cls._cache = {doc.group_id: doc for doc in docs}

    @classmethod
    async def get(cls, group_id: int) -> GroupInfo | None:
        async with cls._lock:
            obj = cls._cache.get(group_id)
            if obj is None:
                async with DBInterface.get_session() as session:
                    obj = await session.execute(select(GroupInfo).where(GroupInfo.group_id == group_id))
                    obj = obj.scalar_one_or_none()
                    if obj:
                        cls._cache[obj.group_id] = obj
        return obj

    @classmethod
    async def add(cls, obj: GroupInfo) -> None:
        async with cls._lock:
            async with DBInterface.get_session() as session:
                session.add(obj)
                await session.commit()
            cls._cache[obj.group_id] = obj

    @classmethod
    async def update(cls, group_id: int, **kwargs) -> None:
        async with cls._lock:
            if group_id not in cls._cache:
                raise KeyError(f"群 {group_id} 不存在。")
            obj = cls._cache[group_id]
            async with DBInterface.get_session() as session:
                await session.execute(_update(GroupInfo).where(GroupInfo.group_id == group_id).values(**kwargs))
                await session.commit()
            for key, value in kwargs.items():
                setattr(obj, key, value)
            cls._cache[group_id] = obj

    @classmethod
    async def delete(cls, group_id: int) -> None:
        async with cls._lock:
            if group_id not in cls._cache:
                raise KeyError(f"群 {group_id} 不存在。")
            obj = cls._cache.pop(group_id)
            async with DBInterface.get_session() as session:
                await session.delete(obj)
                await session.commit()

    @classmethod
    async def all(cls) -> list[GroupInfo]:
        async with cls._lock:
            return list(cls._cache.values())

    @classmethod
    async def reload(cls):
        await cls.load_data()


class TiebaNameCache:
    @classmethod
    async def get(cls, fid: int) -> str:
        key = f"fid:{fid}"
        if name := await tiebaname_cache.get(key):
            return name

        err_key = f"err:{fid}"
        if await tiebaname_cache.exists(err_key):
            return ""

        name = await cls._fetch(fid)
        if name:
            await tiebaname_cache.set(key, name)
        else:
            await tiebaname_cache.set(err_key, 1, expire=5)
        return name

    @staticmethod
    async def _fetch(fid: int) -> str:
        async with Client() as client:
            return await client.get_fname(fid)


class AppealCache:
    @staticmethod
    async def get_appeals(group_id: int) -> list[tuple[int, int]]:
        key = f"group:{group_id}"
        appeals = await appeal_cache.get(key)
        if appeals is None:
            appeals = []
            await appeal_cache.set(key, appeals, expire="2d")
        return appeals

    @staticmethod
    async def set_appeals(group_id: int, appeals: list[tuple[int, int]]):
        key = f"group:{group_id}"
        await appeal_cache.set(key, appeals, expire="2d")

    @staticmethod
    async def get_appeal_id(message_id: int) -> tuple[int, int]:
        key = f"msg:{message_id}"
        appeal_info = await appeal_cache.get(key)
        if not appeal_info:
            return 0, 0
        return appeal_info

    @staticmethod
    async def set_appeal_id(message_id: int, appeal_info: tuple[int, int]):
        key = f"msg:{message_id}"
        await appeal_cache.set(key, appeal_info, expire="2d")
        rev_key = f"rev:{appeal_info[0]}"
        await appeal_cache.set(rev_key, message_id, expire="2d")

    @staticmethod
    async def del_appeal_id(appeal_id: int):
        rev_key = f"rev:{appeal_id}"
        message_id = await appeal_cache.get(rev_key)
        if message_id:
            await appeal_cache.delete(f"msg:{message_id}")
            await appeal_cache.delete(rev_key)
