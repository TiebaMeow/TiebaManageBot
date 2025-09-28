import asyncio

from sqlalchemy import select
from sqlalchemy import update as _update

from src.common import Client

from .interface import DBInterface
from .models import GroupInfo

__all__ = ["GroupCache", "TiebaNameCache", "AppealCache"]


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
    _cache: dict[int, str] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get(cls, fid: int) -> str:
        async with cls._lock:
            name = cls._cache.get(fid)
            if name is None:
                name = await cls._fetch(fid)
                cls._cache[fid] = name
        return name

    @classmethod
    async def _fetch(cls, fid: int) -> str:
        async with Client() as client:
            return await client.get_fname(fid)


class AppealCache:
    _appeal_lists: dict[int, list[tuple[int, int]]] = {}
    _appeal_ids: dict[int, tuple[int, int]] = {}

    @classmethod
    async def get_appeals(cls, group_id: int) -> list[tuple[int, int]]:
        appeals = cls._appeal_lists.get(group_id)
        if appeals is None:
            appeals = []
            cls._appeal_lists[group_id] = appeals
        return appeals

    @classmethod
    async def set_appeals(cls, group_id: int, appeals: list[tuple[int, int]]):
        cls._appeal_lists[group_id] = appeals

    @classmethod
    async def get_appeal_id(cls, message_id: int) -> tuple[int, int]:
        appeal_info = cls._appeal_ids.get(message_id)
        if not appeal_info:
            return 0, 0
        return appeal_info

    @classmethod
    async def set_appeal_id(cls, message_id: int, appeal_info: tuple[int, int]):
        cls._appeal_ids[message_id] = appeal_info

    @classmethod
    async def del_appeal_id(cls, appeal_id: int):
        for message_id, appeal_info in list(cls._appeal_ids.items()):
            if appeal_info[0] == appeal_id:
                del cls._appeal_ids[message_id]
                break
