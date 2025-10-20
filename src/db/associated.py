from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from .interface import DBInterface
from .models import AssociatedData, GroupInfo, ImgDataModel, TextDataModel

if TYPE_CHECKING:
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid
    from aiotieba.typing import UserInfo

__all__ = ["Associated"]


class Associated:
    @staticmethod
    async def add_data(
        user_info: UserInfo | UserInfo_TUid,
        group_info: GroupInfo,
        text_data: list[TextDataModel] | None = None,
        img_data: list[ImgDataModel] | None = None,
    ) -> bool:
        async with DBInterface.get_session() as session:
            stmt = select(AssociatedData).where(
                AssociatedData.user_id == user_info.user_id,
                AssociatedData.fid == group_info.fid,
            )
            result = await session.execute(stmt)
            associated_data = result.scalar_one_or_none()

            if not associated_data:
                associated_data = AssociatedData(
                    user_id=user_info.user_id,
                    fid=group_info.fid,
                    tieba_uid=user_info.tieba_uid,
                    portrait=user_info.portrait,
                    creater_id=group_info.master,
                )
                session.add(associated_data)

            if associated_data.user_name is None:
                associated_data.user_name = []

            if associated_data.nicknames is None:
                associated_data.nicknames = []

            if user_info.user_name and user_info.user_name not in associated_data.user_name:
                associated_data.user_name = [*associated_data.user_name, user_info.user_name]

            if user_info.nick_name and user_info.nick_name not in associated_data.nicknames:
                associated_data.nicknames = [*associated_data.nicknames, user_info.nick_name]

            if text_data:
                associated_data.text_data = [*associated_data.text_data, *text_data]

            if img_data:
                associated_data.img_data = [*associated_data.img_data, *img_data]

            try:
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False

    @staticmethod
    async def get_data(user_id: int, fid: int) -> AssociatedData | None:
        async with DBInterface.get_session() as session:
            associated_data = await session.execute(
                select(AssociatedData).where(AssociatedData.user_id == user_id, AssociatedData.fid == fid)
            )
            return associated_data.scalar_one_or_none()

    @staticmethod
    async def get_public_data(user_id: int) -> list[AssociatedData]:
        async with DBInterface.get_session() as session:
            associated_data = await session.execute(
                select(AssociatedData).where(AssociatedData.user_id == user_id, AssociatedData.is_public.is_(True))
            )
            return list(associated_data.scalars().all())

    @staticmethod
    async def set_data(user_id: int, fid: int, text_data: list[TextDataModel], img_data: list[ImgDataModel]) -> bool:
        async with DBInterface.get_session() as session:
            associated_data = await session.execute(
                select(AssociatedData).where(AssociatedData.user_id == user_id, AssociatedData.fid == fid)
            )
            associated_data = associated_data.scalar_one_or_none()
            if associated_data:
                associated_data.text_data = text_data
                associated_data.img_data = img_data
                try:
                    await session.commit()
                    return True
                except Exception:
                    return False
        return False
