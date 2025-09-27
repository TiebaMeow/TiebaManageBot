from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import BLOB, JSON
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

__all__ = [
    "Base",
    "now_with_tz",
    "TextDataModel",
    "ImgDataModel",
    "GroupInfo",
    "Images",
    "BanStatus",
    "BanList",
    "AssociatedData",
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


class PydanticList[T: BaseModel](TypeDecorator):
    """JSON column that stores a list of Pydantic models."""

    impl = JSON
    cache_ok = True

    def __init__(self, model_type: type[T] = BaseModel, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model_type = model_type

    def process_bind_param(self, value: list[T] | None, dialect) -> list[dict[str, Any]]:
        if value is None:
            return []
        return [item.model_dump(mode="json") for item in value]

    def process_result_value(self, value: list[dict[str, Any]] | None, dialect) -> list[T]:
        if value is None:
            return []
        model_type = self._model_type
        return [model_type(**item) for item in value]

    @property
    def python_type(self) -> type[list[T]]:
        return list[T]


def pydantic_list_column(model_type: type[BaseModel]):
    return MutableList.as_mutable(PydanticList(model_type))


class TextDataModel(BaseModel):
    uploader_id: int
    fid: int
    upload_time: datetime
    text: str

    @field_validator("upload_time", mode="before")
    @classmethod
    def _ensure_upload_time(cls, value: datetime | str | None) -> datetime:
        return _ensure_datetime(value)


class ImgDataModel(BaseModel):
    """Lightweight representation of an image record stored in JSON columns."""

    uploader_id: int
    fid: int
    upload_time: datetime
    image_id: int
    note: str = ""

    @field_validator("upload_time", mode="before")
    @classmethod
    def _ensure_upload_time(cls, value: datetime | str | None) -> datetime:
        return _ensure_datetime(value)


class GroupInfo(TimestampMixin, Base):
    __tablename__ = "group_info"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    master: Mapped[int] = mapped_column(BigInteger, nullable=False)
    admins: Mapped[list[int]] = mapped_column(MutableList.as_mutable(JSON), default=list, nullable=False)
    moderators: Mapped[list[int]] = mapped_column(MutableList.as_mutable(JSON), default=list, nullable=False)
    fid: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    fname: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    master_bduss: Mapped[str] = mapped_column("master_bduss", Text, default="", nullable=False)
    slave_bduss: Mapped[str] = mapped_column("slave_bduss", Text, default="", nullable=False)
    slave_stoken: Mapped[str] = mapped_column("slave_stoken", Text, default="", nullable=False)
    group_args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Images(TimestampMixin, Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    img: Mapped[bytes] = mapped_column(BLOB, nullable=False)


class BanStatus(TimestampMixin, Base):
    __tablename__ = "ban_status"

    fid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_autoban: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz, nullable=False)


class BanList(TimestampMixin, Base):
    __tablename__ = "ban_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fid: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
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


class AssociatedData(TimestampMixin, Base):
    __tablename__ = "associated_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tieba_uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    portrait: Mapped[str] = mapped_column(String(255), nullable=False)
    user_name: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    nicknames: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
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
        UniqueConstraint("user_id", "fid", name="uq_associated_data_user_fid"),
        Index("ix_associated_data_tieba_uid_fid", "tieba_uid", "fid"),
    )


def _ensure_datetime(value: datetime | str | None) -> datetime:
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
