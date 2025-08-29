from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from beanie import Document, Indexed
from pydantic import BaseModel, Field

__all__ = [
    "ApiUser",
    "GroupInfo",
    "TextData",
    "ImgData",
    "BanReason",
    "BanList",
    "AssociatedDataContent",
    "AssociatedData",
]

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_with_tz():
    return datetime.now(SHANGHAI_TZ)


class ApiUser(Document):
    username: str
    hashed_password: str

    class Settings:
        name = "api_user"


class BaseDocument(Document):
    last_update: datetime = Field(default_factory=now_with_tz)

    class Settings:
        use_state_management = True
        state_management_replace_objects = True

    async def save(self, *args, **kwargs):
        self.last_update = datetime.now()
        return await super().save(*args, **kwargs)


class GroupInfo(BaseDocument):
    group_id: Annotated[int, Indexed(unique=True)] = Field(...)
    master: int = Field(...)
    admins: list[int] = Field(default_factory=list)
    moderators: list[int] = Field(default_factory=list)
    fid: Annotated[int, Indexed(unique=True)] = Field(...)
    fname: str = ""
    master_BDUSS: str = ""  # noqa: N815
    slave_BDUSS: str = ""  # noqa: N815
    slave_STOKEN: str = ""  # noqa: N815
    is_public: bool = False
    appeal_sub: bool = False
    appeal_autodeny: bool = False

    class Settings(BaseDocument.Settings):
        name = "group_info"
        collection = "group_info"


class TextData(BaseModel):
    uploader_id: int = Field(...)
    fid: int = Field(...)
    upload_time: datetime = Field(default_factory=now_with_tz)
    text: str = Field(...)


class ImageDocument(Document):
    img: str = Field(...)  # base64编码的图片

    class Settings:
        name = "images"
        collection = "images"


class ImgData(BaseModel):
    uploader_id: int = Field(...)
    fid: int = Field(...)
    upload_time: datetime = Field(default_factory=now_with_tz)
    image_id: str = Field(...)
    note: str = Field(...)


class BanReason(BaseModel):
    ban_time: datetime = Field(default_factory=now_with_tz)
    operator_id: int = Field(...)
    enable: bool = True
    unban_time: datetime | None = None
    unban_operator_id: int | None = None
    text_reason: list[TextData] = Field(default_factory=list)
    img_reason: list[ImgData] = Field(default_factory=list)


class BanList(BaseDocument):
    group_id: Annotated[int, Indexed(unique=True)] = Field(...)
    fid: Annotated[int, Indexed(unique=True)] = Field(...)
    ban_list: dict[int, BanReason] = Field(default_factory=dict)
    last_autoban: datetime = Field(default_factory=datetime.now)

    class Settings(BaseDocument.Settings):
        name = "ban_list"
        collection = "ban_list"


class AssociatedDataContent(BaseModel):
    tieba_uid: int = Field(...)
    text_data: list[TextData] = Field(default_factory=list)
    img_data: list[ImgData] = Field(default_factory=list)


class AssociatedData(BaseDocument):
    tieba_uid: Annotated[int, Indexed(unique=False)] = Field(...)
    user_id: int = Field(...)
    portrait: str = Field(...)
    user_name: list[str] = Field(default_factory=list)  # 包含曾用用户名
    nicknames: list[str] = Field(default_factory=list)  # 包含曾用昵称
    fid: int = Field(...)
    creater_id: int = Field(...)
    is_public: int = 0
    data: AssociatedDataContent = Field(...)

    class Settings(BaseDocument.Settings):
        name = "associated_data"
        collection = "associated_data"
        indexes = [
            "tieba_uid",
            ("tieba_uid", "fid"),
        ]
