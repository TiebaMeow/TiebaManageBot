from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from .interface import DBInterface
from .models import SHANGHAI_TZ, BanList, BanStatus, ImgDataModel, TextDataModel, now_with_tz

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

__all__ = ["AutoBanList"]


class AutoBanList:
    @staticmethod
    async def add_ban(fid: int, group_id: int, ban_list: BanList) -> bool:
        async with DBInterface.get_session() as session:
            ban_status = await session.get(BanStatus, fid)
            if not ban_status:
                ban_status = BanStatus(fid=fid, group_id=group_id)
                session.add(ban_status)
                await session.flush()
            session.add(ban_list)
            try:
                await session.commit()
                return True
            except Exception as e:
                print(e)
                await session.rollback()
                return False

    @staticmethod
    async def unban(fid: int, operator: int, user_id: int) -> bool:
        async with DBInterface.get_session() as session:
            ban_status = await session.get(BanStatus, fid)
            if not ban_status:
                return False
            ban_list = await session.execute(select(BanList).where(BanList.fid == fid, BanList.user_id == user_id))
            ban_list = ban_list.scalar_one_or_none()
            if not ban_list or not ban_list.enable:
                return False
            ban_list.enable = False
            ban_list.unban_time = now_with_tz()
            ban_list.unban_operator_id = operator
            try:
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False

    @staticmethod
    async def ban_status(fid: int, user_id: int) -> tuple[Literal["not", "banned", "unbanned"], BanList | None]:
        async with DBInterface.get_session() as session:
            ban_list = await session.execute(select(BanList).where(BanList.fid == fid, BanList.user_id == user_id))
            ban_list = ban_list.scalar_one_or_none()
        if not ban_list:
            return "not", None
        if ban_list.enable:
            return "banned", ban_list
        else:
            return "unbanned", ban_list

    @staticmethod
    async def update_ban_reason(
        fid: int,
        user_id: int,
        *,
        text_reason: list[TextDataModel] | None = None,
        img_reason: list[ImgDataModel] | None = None,
    ) -> bool:
        async with DBInterface.get_session() as session:
            ban_list = await session.execute(select(BanList).where(BanList.fid == fid, BanList.user_id == user_id))
            ban_list = ban_list.scalar_one_or_none()
            if not ban_list:
                return False
            if text_reason is not None:
                ban_list.text_reason = text_reason
            if img_reason is not None:
                ban_list.img_reason = img_reason
            try:
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False

    @staticmethod
    async def get_autoban() -> list[BanStatus]:
        async with DBInterface.get_session() as session:
            ban_statuses = await session.execute(
                select(BanStatus).where(
                    BanStatus.last_autoban < datetime.now(SHANGHAI_TZ) - timedelta(days=3),
                )
            )
            return list(ban_statuses.scalars().all())

    @staticmethod
    async def get_autoban_lists(fid: int) -> AsyncGenerator[int, None]:
        async with DBInterface.get_session() as session:
            ban_lists = await session.stream(
                select(BanList.user_id).where(BanList.enable.is_(True), BanList.fid == fid)
            )
            async for ban_list in ban_lists.scalars():
                yield ban_list

    @staticmethod
    async def update_autoban(fid: int, group_id: int) -> bool:
        async with DBInterface.get_session() as session:
            ban_status = await session.get(BanStatus, fid)
            if not ban_status:
                ban_status = BanStatus(fid=fid, group_id=group_id)
                session.add(ban_status)
                await session.flush()
            ban_status.last_autoban = now_with_tz()
            try:
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False
