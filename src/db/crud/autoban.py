from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from src.db.models import BanList, BanStatus, ImgDataModel, TextDataModel, now_with_tz
from src.db.session import get_session


async def add_ban(fid: int, group_id: int, ban_list: BanList) -> bool:
    async with get_session() as session:
        ban_status = await session.get(BanStatus, fid)
        if not ban_status:
            ban_status = BanStatus(fid=fid, group_id=group_id)
            session.add(ban_status)
            await session.flush()

        stmt = insert(BanList).values(
            fid=ban_list.fid,
            user_id=ban_list.user_id,
            ban_time=now_with_tz(),
            operator_id=ban_list.operator_id,
            enable=True,
            unban_time=getattr(ban_list, "unban_time", None),
            unban_operator_id=getattr(ban_list, "unban_operator_id", None),
            text_reason=ban_list.text_reason,
            img_reason=ban_list.img_reason,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["fid", "user_id"],
            set_={
                "ban_time": stmt.excluded.ban_time,
                "operator_id": stmt.excluded.operator_id,
                "enable": stmt.excluded.enable,
                "unban_time": stmt.excluded.unban_time,
                "unban_operator_id": stmt.excluded.unban_operator_id,
                "text_reason": stmt.excluded.text_reason,
                "img_reason": stmt.excluded.img_reason,
                "last_update": now_with_tz(),
            },
        )
        await session.execute(stmt)

        try:
            await session.commit()
            return True
        except Exception as e:
            print(e)
            await session.rollback()
            return False


async def unban(fid: int, operator: int, user_id: int) -> bool:
    async with get_session() as session:
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


async def get_ban_status(fid: int, user_id: int) -> tuple[Literal["not", "banned", "unbanned"], BanList | None]:
    async with get_session() as session:
        ban_list = await session.execute(select(BanList).where(BanList.fid == fid, BanList.user_id == user_id))
        ban_list = ban_list.scalar_one_or_none()
    if not ban_list:
        return "not", None
    if ban_list.enable:
        return "banned", ban_list
    else:
        return "unbanned", ban_list


async def update_ban_reason(
    fid: int,
    user_id: int,
    *,
    text_reason: list[TextDataModel] | None = None,
    img_reason: list[ImgDataModel] | None = None,
) -> bool:
    async with get_session() as session:
        ban_list = await session.execute(select(BanList).where(BanList.fid == fid, BanList.user_id == user_id))
        ban_list = ban_list.scalar_one_or_none()
        if not ban_list:
            return False

        if text_reason:
            ban_list.text_reason = [*ban_list.text_reason, *text_reason]
        if img_reason:
            ban_list.img_reason = [*ban_list.img_reason, *img_reason]

        try:
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False


async def get_autoban() -> list[BanStatus]:
    async with get_session() as session:
        ban_statuses = await session.execute(
            select(BanStatus).where(
                BanStatus.last_autoban < now_with_tz() - timedelta(days=3),
            )
        )
        return list(ban_statuses.scalars().all())


async def get_autoban_lists(fid: int) -> AsyncGenerator[int, None]:
    async with get_session() as session:
        ban_lists = await session.stream(select(BanList.user_id).where(BanList.enable.is_(True), BanList.fid == fid))
        async for ban_list in ban_lists.scalars():
            yield ban_list


async def update_autoban(fid: int, group_id: int) -> bool:
    async with get_session() as session:
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
