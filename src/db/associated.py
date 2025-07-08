from aiotieba.typing import UserInfo

from .modules import AssociatedData, AssociatedDataContent, GroupInfo, ImgData, TextData

__all__ = ["Associated"]


class Associated:
    @staticmethod
    async def add_data(
        user_info: UserInfo,
        group_info: GroupInfo,
        text_data: list[TextData] | None = None,
        img_data: list[ImgData] | None = None,
    ) -> bool:
        associated_data = await AssociatedData.find_one(
            AssociatedData.tieba_uid == user_info.tieba_uid, AssociatedData.fid == group_info.fid
        )
        if not associated_data:
            associated_data = AssociatedData(
                tieba_uid=user_info.tieba_uid,
                user_id=user_info.user_id,
                portrait=user_info.portrait,
                fid=group_info.fid,
                creater_id=group_info.master,
                data=AssociatedDataContent(tieba_uid=user_info.tieba_uid),
            )
        if user_info.user_name not in associated_data.user_name:
            associated_data.user_name.append(user_info.user_name)
        if user_info.nick_name not in associated_data.nicknames:
            associated_data.nicknames.append(user_info.nick_name)
        if text_data:
            associated_data.data.text_data.extend(text_data)
        if img_data:
            associated_data.data.img_data.extend(img_data)
        try:
            await associated_data.save()
            return True
        except BaseException:
            return False

    @staticmethod
    async def get_data(tieba_uid: int, fid: int) -> AssociatedData | None:
        return await AssociatedData.find_one(AssociatedData.tieba_uid == tieba_uid, AssociatedData.fid == fid)

    @staticmethod
    async def get_public_data(tieba_uid: int) -> list[AssociatedData]:
        return await AssociatedData.find(AssociatedData.tieba_uid == tieba_uid, AssociatedData.is_public == 1).to_list()

    @staticmethod
    async def query_data(**filters) -> list[AssociatedData]:
        return await AssociatedData.find(filters).to_list()

    @staticmethod
    async def set_data(tieba_uid: int, fid: int, data: AssociatedDataContent) -> bool:
        associated_data = await AssociatedData.find_one(
            AssociatedData.tieba_uid == tieba_uid, AssociatedData.fid == fid
        )
        if associated_data:
            associated_data.data = data
            try:
                await associated_data.save()
                return True
            except BaseException:
                return False
        return False
