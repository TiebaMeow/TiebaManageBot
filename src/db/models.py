from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, TypeEngine

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect

__all__ = [
    "Base",
    "now_with_tz",
    "TextDataModel",
    "ImgDataModel",
    "GroupInfo",
    "Image",
    "BanStatus",
    "BanList",
    "AssociatedList",
]

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_with_tz() -> datetime:
    return datetime.now(SHANGHAI_TZ)


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base class for all SQLAlchemy models."""


class TimestampMixin:
    last_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        onupdate=now_with_tz,
        nullable=False,
    )


def json_type():
    """返回适配 sqlite/pg 的 JSON 类型实例。"""

    return JSON().with_variant(JSONB, "postgresql")


class PydanticList[T: BaseModel](TypeDecorator[list[T]]):
    """用于存储 Pydantic 模型列表的 JSON/JSONB 列类型。"""

    impl = JSON
    cache_ok = True

    def __init__(self, model_type: type[T] = BaseModel, *args: object, **kwargs: object):
        super().__init__(*args, **kwargs)
        self.adapter: TypeAdapter[T] = TypeAdapter(model_type)

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[T] | None, dialect: Dialect) -> list[dict[str, Any]]:
        if value is None:
            return []
        return [self.adapter.dump_python(item, mode="json") for item in value]

    def process_result_value(self, value: list[dict[str, Any]] | None, dialect: Dialect) -> list[T]:
        if value is None:
            return []

        result: list[T] = []
        for item in value:
            try:
                result.append(self.adapter.validate_python(item))
            except ValidationError as exc:
                raise exc
        return result

    @property
    def python_type(self) -> type[list[T]]:  # type: ignore[override]
        return list[T]


def pydantic_list_column(model_type: type[BaseModel]):
    """创建“可变 + Pydantic 列表”列类型，使对列表的原地修改触发 UPDATE。"""

    return MutableList.as_mutable(PydanticList(model_type))


def _ensure_datetime(value: datetime | str | None) -> datetime:
    """将来自 DB/JSON 的时间值规范为带Asia/Shanghai时区的 datetime。"""

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            dt = datetime.fromtimestamp(0, tz=SHANGHAI_TZ)
        else:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=SHANGHAI_TZ)
    else:
        dt = datetime.fromtimestamp(0, tz=SHANGHAI_TZ)

    return dt.astimezone(SHANGHAI_TZ)


class TextDataModel(BaseModel):
    """文本数据模型。

    Attributes:
        uploader_id (int): 上传者 QQ。
        fid (int): 贴吧 Forum ID。
        upload_time (datetime): 上传时间（默认当前上海时区时间）。
        text (str): 文本内容。
    """

    uploader_id: int
    fid: int
    upload_time: datetime = Field(default_factory=now_with_tz)
    text: str

    @field_validator("upload_time", mode="before")
    @classmethod
    def _ensure_upload_time(cls, value: datetime | str | None) -> datetime:
        return _ensure_datetime(value)


class ImgDataModel(BaseModel):
    """图片数据模型。

    Attributes:
        uploader_id (int): 上传者 QQ。
        fid (int): 贴吧 Forum ID。
        upload_time (datetime): 上传时间（默认当前上海时区时间）。
        image_id (int): 图片表主键。
        note (str): 图片注释（可选）。
    """

    uploader_id: int
    fid: int
    upload_time: datetime = Field(default_factory=now_with_tz)
    image_id: int
    note: str = ""

    @field_validator("upload_time", mode="before")
    @classmethod
    def _ensure_upload_time(cls, value: datetime | str | None) -> datetime:
        return _ensure_datetime(value)


class GroupInfo(TimestampMixin, Base):
    """群信息模型。

    存储吧务群的配置信息、绑定的贴吧信息以及管理员/吧务设置。

    Attributes:
        group_id (int): 群组 ID（主键）。
        master (int): 群主 QQ 号。
        admins (list[int]): 管理员 QQ 列表。
        moderators (list[int]): 吧务 QQ 列表。
        fid (int): 贴吧 Forum ID。
        fname (str): 贴吧名称。
        master_bduss (str): 吧主 BDUSS。
        slave_bduss (str): 吧务 BDUSS。
        slave_stoken (str): 吧务 STOKEN。
        group_args (dict[str, Any]): 吧务群配置参数 (JSON)。
        last_update (datetime): 最后更新时间。
    """

    __tablename__ = "group_info"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    master: Mapped[int] = mapped_column(BigInteger, nullable=False)
    admins: Mapped[list[int]] = mapped_column(MutableList.as_mutable(json_type()), default=list, nullable=False)
    moderators: Mapped[list[int]] = mapped_column(MutableList.as_mutable(json_type()), default=list, nullable=False)
    fid: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    fname: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    master_bduss: Mapped[str] = mapped_column("master_bduss", Text, default="", nullable=False)
    slave_bduss: Mapped[str] = mapped_column("slave_bduss", Text, default="", nullable=False)
    slave_stoken: Mapped[str] = mapped_column("slave_stoken", Text, default="", nullable=False)
    group_args: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.admins is None:
            self.admins = []
        if self.moderators is None:
            self.moderators = []
        if self.group_args is None:
            self.group_args = {}


class Image(TimestampMixin, Base):
    """图片存储模型。

    存储图片数据，用于封禁原因或关联数据。

    Attributes:
        id (int): 图片 ID (自增主键)。
        img (bytes): 图片二进制数据。
        last_update (datetime): 最后更新时间。
    """

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    img: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class BanStatus(TimestampMixin, Base):
    """循封机运行状态模型。

    记录每个贴吧群组的循封机运行状态。

    Attributes:
        fid (int): 贴吧 Forum ID (主键)。
        group_id (int): 关联的群组 ID。
        last_autoban (datetime): 上次循封任务执行时间。
        last_update (datetime): 最后更新时间。
    """

    __tablename__ = "ban_status"

    fid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_autoban: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz, nullable=False)


class BanList(TimestampMixin, Base):
    """循封名单模型。

    存储循封用户及其封禁详情。

    Attributes:
        id (int): 循封记录 ID (主键)。
        fid (int): 贴吧 Forum ID。
        user_id (int): 被封禁用户 ID。
        ban_time (datetime): 封禁时间。
        operator_id (int): 操作人 ID。
        enable (bool): 是否启用循封。
        unban_time (datetime | None): 解封时间。
        unban_operator_id (int | None): 解封操作人 ID。
        text_reason (list[TextDataModel]): 文本原因列表（按顺序展示/删除）。
        img_reason (list[ImgDataModel]): 图片原因列表（按顺序展示/删除）。
        last_update (datetime): 最后更新时间。
    """

    __tablename__ = "ban_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fid: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    portrait: Mapped[str] = mapped_column(String(255), nullable=False)
    ban_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz, nullable=False)
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unban_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unban_operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    text_reason: Mapped[list[TextDataModel]] = mapped_column(
        pydantic_list_column(TextDataModel),
        default=list,
        nullable=False,
    )
    img_reason: Mapped[list[ImgDataModel]] = mapped_column(
        pydantic_list_column(ImgDataModel),
        default=list,
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("fid", "user_id", name="uq_ban_list_fid_user"),)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.text_reason is None:
            self.text_reason = []
        if self.img_reason is None:
            self.img_reason = []


class AssociatedList(TimestampMixin, Base):
    """关联信息模型。
    存储用户的曾用名与关联信息，包括bot的自动处理记录。

    Attributes:
        id (int): 关联数据 ID (自增主键)。
        user_id (int): 用户 ID。
        fid (int): 贴吧 Forum ID。
        tieba_uid (int): 贴吧 UID。
        portrait (str): 用户头像 portrait。
        user_name (list[str]): 曾用用户名列表。
        nicknames (list[str]): 曾用昵称列表。
        creater_id (int): 创建者 ID。
        is_public (bool): 是否公开。
        text_data (list[TextDataModel]): 文字关联记录列表。
        img_data (list[ImgDataModel]): 图片关联记录列表。
        last_update (datetime): 最后更新时间。
    """

    __tablename__ = "associated_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tieba_uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    portrait: Mapped[str] = mapped_column(String(255), nullable=False)
    user_name: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_type()), default=list, nullable=False)
    nicknames: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_type()), default=list, nullable=False)
    creater_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    text_data: Mapped[list[TextDataModel]] = mapped_column(
        pydantic_list_column(TextDataModel),
        default=list,
        nullable=False,
    )
    img_data: Mapped[list[ImgDataModel]] = mapped_column(
        pydantic_list_column(ImgDataModel),
        default=list,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "fid", name="uq_associated_list_user_fid"),
        Index("ix_associated_list_tieba_uid_fid", "tieba_uid", "fid"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.text_data is None:
            self.text_data = []
        if self.img_data is None:
            self.img_data = []
        if self.user_name is None:
            self.user_name = []
        if self.nicknames is None:
            self.nicknames = []
