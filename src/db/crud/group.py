from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy import update as sa_update

from src.db.models import GroupInfo
from src.db.session import get_session

_GROUP_CACHE: dict[int, GroupInfo] = {}
_LOCK = asyncio.Lock()


async def load_groups() -> None:
    async with _LOCK:
        async with get_session() as session:
            result = await session.execute(select(GroupInfo))
            groups = result.scalars().all()
            _GROUP_CACHE.clear()
            _GROUP_CACHE.update({g.group_id: g for g in groups})


async def get_group(group_id: int) -> GroupInfo:
    if group_id in _GROUP_CACHE:
        return _GROUP_CACHE[group_id]

    async with _LOCK:
        if group_id in _GROUP_CACHE:
            return _GROUP_CACHE[group_id]

        async with get_session() as session:
            group = await session.get(GroupInfo, group_id)
            if not group:
                raise KeyError(f"群 {group_id} 不存在。")
            _GROUP_CACHE[group_id] = group
            return group


async def add_group(group: GroupInfo) -> None:
    async with _LOCK:
        async with get_session() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)
            _GROUP_CACHE[group.group_id] = group


async def update_group(group_id: int, **kwargs: Any) -> None:
    async with _LOCK:
        if group_id not in _GROUP_CACHE:
            async with get_session() as session:
                group = await session.get(GroupInfo, group_id)
                if not group:
                    raise KeyError(f"群 {group_id} 不存在。")
                _GROUP_CACHE[group_id] = group

        async with get_session() as session:
            stmt = sa_update(GroupInfo).where(GroupInfo.group_id == group_id).values(**kwargs)
            await session.execute(stmt)
            await session.commit()

            obj = _GROUP_CACHE[group_id]
            for k, v in kwargs.items():
                setattr(obj, k, v)


async def delete_group(group_id: int) -> None:
    async with _LOCK:
        if group_id in _GROUP_CACHE:
            del _GROUP_CACHE[group_id]

        async with get_session() as session:
            group = await session.get(GroupInfo, group_id)
            if group:
                await session.delete(group)
                await session.commit()
            else:
                raise KeyError(f"群 {group_id} 不存在。")


async def get_all_groups() -> list[GroupInfo]:
    if not _GROUP_CACHE:
        await load_groups()
    return list(_GROUP_CACHE.values())
