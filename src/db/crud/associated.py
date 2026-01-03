from typing import TYPE_CHECKING

from sqlalchemy import select

from src.db.models import AssociatedList, GroupInfo, ImgDataModel, TextDataModel
from src.db.session import get_session

if TYPE_CHECKING:
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid
    from aiotieba.typing import UserInfo


async def add_associated_data(
    user_info: "UserInfo | UserInfo_TUid",
    group_info: GroupInfo,
    text_data: list[TextDataModel] | None = None,
    img_data: list[ImgDataModel] | None = None,
) -> bool:
    async with get_session() as session:
        stmt = select(AssociatedList).where(
            AssociatedList.user_id == user_info.user_id,
            AssociatedList.fid == group_info.fid,
        )
        result = await session.execute(stmt)
        associated_data = result.scalar_one_or_none()

        if not associated_data:
            associated_data = AssociatedList(
                user_id=user_info.user_id,
                fid=group_info.fid,
                tieba_uid=user_info.tieba_uid,
                portrait=user_info.portrait,
                creater_id=group_info.master,
            )
            session.add(associated_data)

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


async def get_associated_data(user_id: int, fid: int) -> AssociatedList | None:
    async with get_session() as session:
        associated_data = await session.execute(
            select(AssociatedList).where(AssociatedList.user_id == user_id, AssociatedList.fid == fid)
        )
        return associated_data.scalar_one_or_none()


async def get_public_associated_data(user_id: int) -> list[AssociatedList]:
    async with get_session() as session:
        associated_data = await session.execute(
            select(AssociatedList).where(AssociatedList.user_id == user_id, AssociatedList.is_public.is_(True))
        )
        return list(associated_data.scalars().all())


async def set_associated_data(
    user_id: int, fid: int, text_data: list[TextDataModel], img_data: list[ImgDataModel]
) -> bool:
    async with get_session() as session:
        associated_data = await session.execute(
            select(AssociatedList).where(AssociatedList.user_id == user_id, AssociatedList.fid == fid)
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
