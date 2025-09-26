from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
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
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "Base",
    "now_with_tz",
    "TextDataModel",
    "ImgDataModel",
    "AssociatedDataContentModel",
    "serialize_text_data",
    "deserialize_text_data",
    "serialize_img_data",
    "deserialize_img_data",
    "GroupInfo",
    "ImageDocument",
    "BanList",
    "BanReason",
    "AssociatedData",
]

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_with_tz() -> datetime:
    """Return the current time in the Shanghai timezone."""

    return datetime.now(SHANGHAI_TZ)


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base class for all SQLAlchemy models."""


class TimestampMixin:
    """Mixin providing an auto-updated ``last_update`` timestamp column."""

    last_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        onupdate=now_with_tz,
        nullable=False,
    )


class TextDataModel(BaseModel):
    """Lightweight representation of a text record stored in JSON columns."""

    uploader_id: int
    fid: int
    upload_time: datetime
    text: str


class ImgDataModel(BaseModel):
    """Lightweight representation of an image record stored in JSON columns."""

    uploader_id: int
    fid: int
    upload_time: datetime
    image_id: int
    note: str = ""


class AssociatedDataContentModel(BaseModel):
    """Container used for storing associated text and image data in JSON."""

    tieba_uid: int | None = None
    text_data: list[TextDataModel] = Field(default_factory=list)
    img_data: list[ImgDataModel] = Field(default_factory=list)


class GroupInfo(TimestampMixin, Base):
    __tablename__ = "group_info"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    master: Mapped[int] = mapped_column(BigInteger, nullable=False)
    admins: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    moderators: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    fid: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    fname: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    master_bduss: Mapped[str] = mapped_column("master_bduss", Text, default="", nullable=False)
    slave_bduss: Mapped[str] = mapped_column("slave_bduss", Text, default="", nullable=False)
    slave_stoken: Mapped[str] = mapped_column("slave_stoken", Text, default="", nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    appeal_sub: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    appeal_autodeny: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ImageDocument(TimestampMixin, Base):
    __tablename__ = "image_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    img: Mapped[str] = mapped_column(Text, nullable=False)


class BanList(TimestampMixin, Base):
    __tablename__ = "ban_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_autoban: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("group_id", "fid", name="uq_ban_lists_group_fid"),)


class BanReason(TimestampMixin, Base):
    __tablename__ = "ban_reasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ban_list_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ban_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False,
    )
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unban_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unban_operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    text_reason: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    img_reason: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    __table_args__ = (UniqueConstraint("ban_list_id", "user_id", name="uq_ban_reasons_list_user"),)


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
    text_data: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    img_data: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

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


def _serialize_datetime(value: datetime) -> str:
    return value.astimezone(SHANGHAI_TZ).isoformat()


def serialize_text_data(entries: Iterable[TextDataModel]) -> list[dict[str, Any]]:
    return [
        {
            "uploader_id": entry.uploader_id,
            "fid": entry.fid,
            "upload_time": _serialize_datetime(entry.upload_time),
            "text": entry.text,
        }
        for entry in entries
    ]


def deserialize_text_data(payloads: Sequence[dict[str, Any] | TextDataModel]) -> list[TextDataModel]:
    result: list[TextDataModel] = []
    for payload in payloads:
        if isinstance(payload, TextDataModel):
            result.append(payload)
            continue
        upload_time = _ensure_datetime(payload.get("upload_time"))
        result.append(
            TextDataModel(
                uploader_id=int(payload.get("uploader_id", 0)),
                fid=int(payload.get("fid", 0)),
                upload_time=upload_time,
                text=str(payload.get("text", "")),
            )
        )
    return result


def serialize_img_data(entries: Iterable[ImgDataModel]) -> list[dict[str, Any]]:
    return [
        {
            "uploader_id": entry.uploader_id,
            "fid": entry.fid,
            "upload_time": _serialize_datetime(entry.upload_time),
            "image_id": int(entry.image_id),
            "note": entry.note,
        }
        for entry in entries
    ]


def deserialize_img_data(payloads: Sequence[dict[str, Any] | ImgDataModel]) -> list[ImgDataModel]:
    result: list[ImgDataModel] = []
    for payload in payloads:
        if isinstance(payload, ImgDataModel):
            result.append(payload)
            continue
        upload_time = _ensure_datetime(payload.get("upload_time"))
        image_id_raw = payload.get("image_id", 0)
        try:
            image_id = int(image_id_raw)
        except (TypeError, ValueError):
            image_id = 0
        result.append(
            ImgDataModel(
                uploader_id=int(payload.get("uploader_id", 0)),
                fid=int(payload.get("fid", 0)),
                upload_time=upload_time,
                image_id=image_id,
                note=str(payload.get("note", "")),
            )
        )
    return result
