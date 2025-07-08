from datetime import datetime
from typing import Literal

from aiotieba.typing import UserInfo

from .modules import BanList, BanReason

__all__ = ["AutoBanList"]


class AutoBanList:
    @staticmethod
    async def add_ban(group_id: int, fid: int, operator: int, user_info: UserInfo, ban_reason: BanReason) -> bool:
        ban_list = await BanList.find_one(BanList.group_id == group_id, BanList.fid == fid)
        if not ban_list:
            ban_list = BanList(group_id=group_id, fid=fid)
        ban_list.ban_list[user_info.user_id] = ban_reason
        try:
            await ban_list.save()
            return True
        except BaseException:
            return False

    @staticmethod
    async def unban(group_id: int, fid: int, operator: int, user_info: UserInfo) -> bool:
        ban_list = await BanList.find_one(BanList.group_id == group_id, BanList.fid == fid)
        if not ban_list or user_info.user_id not in ban_list.ban_list:
            return False
        ban_list.ban_list[user_info.user_id].enable = False
        ban_list.ban_list[user_info.user_id].unban_time = datetime.now().astimezone()
        ban_list.ban_list[user_info.user_id].unban_operator_id = operator
        try:
            await ban_list.save()
        except BaseException:
            return False
        return True

    @staticmethod
    async def ban_status(
        group_id: int, fid: int, user_id: int
    ) -> tuple[Literal["not", "banned", "unbanned"], BanReason | None]:
        ban_list = await BanList.find_one(BanList.group_id == group_id, BanList.fid == fid)
        if not ban_list:
            return "not", None
        if user_id in ban_list.ban_list:
            if ban_list.ban_list[user_id].enable:
                return "banned", ban_list.ban_list[user_id]
            else:
                return "unbanned", ban_list.ban_list[user_id]
        return "not", None

    @staticmethod
    async def get_ban_list(group_id: int, fid: int) -> BanList | None:
        return await BanList.find_one(BanList.group_id == group_id, BanList.fid == fid)

    @staticmethod
    async def get_ban_lists() -> list[BanList]:
        return await BanList.all().to_list()

    @staticmethod
    async def update_ban_reason(group_id: int, fid: int, user_info: UserInfo, ban_reason: BanReason) -> bool:
        ban_list = await BanList.find_one(BanList.group_id == group_id, BanList.fid == fid)
        if not ban_list or user_info.user_id not in ban_list.ban_list:
            return False
        ban_list.ban_list[user_info.user_id] = ban_reason
        try:
            await ban_list.save()
        except BaseException:
            return False
        return True

    @staticmethod
    async def update_autoban(group_id: int, fid: int) -> bool:
        banlist = await BanList.find_one(BanList.group_id == group_id, BanList.fid == fid)
        if banlist:
            banlist.last_autoban = datetime.now()
            await banlist.save()
            return True
        return False
