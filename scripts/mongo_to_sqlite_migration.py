"""Mongo → SQLite 迁移脚本"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import asyncio
import base64
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from beanie import init_beanie
from pydantic import BaseModel
from pymongo import AsyncMongoClient
from sqlalchemy import delete

from src.db import DBInterface
from src.db.models import (
    AssociatedData as SQLAssociatedData,
)
from src.db.models import BanList as SQLBanList
from src.db.models import BanStatus as SQLBanStatus
from src.db.models import GroupInfo as SQLGroupInfo
from src.db.models import Image as SQLImages
from src.db.models import ImgDataModel, TextDataModel
from src.db.modules import (
    AssociatedData,
    AssociatedDataContent,
    BanList,
    GroupInfo,
    ImageDocument,
    ImgData,
    TextData,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


async def init_mongo():
    try:
        client = AsyncMongoClient(host="mongodb://localhost:27017")
        await init_beanie(
            database=client.tiebabot,
            document_models=[
                GroupInfo,
                AssociatedData,
                BanList,
                ImageDocument,
            ],
        )
    except Exception as e:
        print(f"Failed to connect to the database: {e}")
        raise e


async def _reset_sqlite_tables(session: AsyncSession) -> None:
    """Remove existing rows so the migration can run on a clean slate."""

    await session.execute(delete(SQLBanList))
    await session.execute(delete(SQLBanStatus))
    await session.execute(delete(SQLAssociatedData))
    await session.execute(delete(SQLGroupInfo))
    await session.execute(delete(SQLImages))


async def _migrate_image_documents(session: AsyncSession) -> dict[str, int]:
    """Copy all Mongo image documents and return an ObjectId → integer ID map."""

    image_map: dict[str, int] = {}
    mongo_images: list[ImageDocument] = await ImageDocument.find_all().to_list()

    for image in mongo_images:
        img_blob = base64.b64decode(image.img)
        sql_image = SQLImages(img=img_blob)
        session.add(sql_image)
        await session.flush()
        image_map[str(image.id)] = sql_image.id

    print(f"Migrated {len(image_map)} image documents")
    return image_map


def _coerce_model_list[ModelT: BaseModel](
    model_type: type[ModelT], entries: Iterable[ModelT | Mapping[str, Any]]
) -> list[ModelT]:
    result: list[ModelT] = []
    for entry in entries:
        if isinstance(entry, model_type):
            result.append(entry)
            continue
        if isinstance(entry, Mapping):
            result.append(model_type.model_validate(dict(entry)))
            continue
        raise TypeError(f"Unsupported entry type for {model_type.__name__}: {type(entry)!r}")
    return result


def serialize_text_data(entries: Iterable[Mapping[str, Any]]) -> list[TextDataModel]:
    return _coerce_model_list(TextDataModel, entries)


def serialize_img_data(entries: Iterable[Mapping[str, Any]]) -> list[ImgDataModel]:
    return _coerce_model_list(ImgDataModel, entries)


def _convert_text_payloads(text_items: Iterable[TextData]) -> list[TextDataModel]:
    return serialize_text_data([item.model_dump(mode="python") for item in text_items])


def _convert_img_payloads(
    img_items: Iterable[ImgData],
    image_map: dict[str, int],
) -> list[ImgDataModel]:
    payloads: list[dict[str, Any]] = []
    for item in img_items:
        mapped = image_map.get(str(item.image_id))
        if mapped is None:
            raise KeyError(f"Unmapped image ObjectId: {item.image_id}")
        data = item.model_dump(mode="python")
        data["image_id"] = mapped
        payloads.append(data)
    return serialize_img_data(payloads)


async def _migrate_group_info(session: AsyncSession) -> None:
    mongo_groups: list[GroupInfo] = await GroupInfo.find_all().to_list()
    for group in mongo_groups:
        sql_group = SQLGroupInfo(
            group_id=group.group_id,
            master=group.master,
            admins=group.admins,
            moderators=group.moderators,
            fid=group.fid,
            fname=group.fname,
            master_bduss=group.master_BDUSS,
            slave_bduss=group.slave_BDUSS,
            slave_stoken=group.slave_STOKEN,
            group_args={
                "appeal_sub": group.appeal_sub,
                "appeal_autodeny": group.appeal_autodeny,
                "autoban": True,
                "is_public": group.is_public,
            },
            last_update=group.last_update,
        )
        session.add(sql_group)
    print(f"Migrated {len(mongo_groups)} group info records")


async def _migrate_ban_lists(session: AsyncSession, image_map: dict[str, int]) -> None:
    mongo_banlists: list[BanList] = await BanList.find_all().to_list()
    for banlist in mongo_banlists:
        sql_banstatus = SQLBanStatus(
            fid=banlist.fid,
            group_id=banlist.group_id,
            last_autoban=banlist.last_autoban,
            last_update=banlist.last_update,
        )
        session.add(sql_banstatus)
        await session.flush()

        for user_id, reason in banlist.ban_list.items():
            text_payloads = _convert_text_payloads(reason.text_reason)
            img_payloads = _convert_img_payloads(reason.img_reason, image_map)
            sql_reason = SQLBanList(
                fid=sql_banstatus.fid,
                user_id=user_id,
                ban_time=reason.ban_time,
                operator_id=reason.operator_id,
                enable=reason.enable,
                unban_time=reason.unban_time,
                unban_operator_id=reason.unban_operator_id,
                text_reason=text_payloads,
                img_reason=img_payloads,
                last_update=banlist.last_update,
            )
            session.add(sql_reason)

    print(f"Migrated {len(mongo_banlists)} ban list records")


async def _migrate_associated_data(session: AsyncSession, image_map: dict[str, int]) -> None:
    mongo_associated: list[AssociatedData] = await AssociatedData.find_all().to_list()
    for assoc in mongo_associated:
        content: AssociatedDataContent = assoc.data
        text_payloads = _convert_text_payloads(content.text_data)
        img_payloads = _convert_img_payloads(content.img_data, image_map)

        sql_assoc = SQLAssociatedData(
            user_id=assoc.user_id,
            fid=assoc.fid,
            tieba_uid=assoc.tieba_uid,
            portrait=assoc.portrait,
            user_name=assoc.user_name,
            nicknames=assoc.nicknames,
            creater_id=assoc.creater_id,
            is_public=bool(assoc.is_public),
            text_data=text_payloads,
            img_data=img_payloads,
            last_update=assoc.last_update,
        )
        session.add(sql_assoc)

    print(f"Migrated {len(mongo_associated)} associated data records")


async def migrate() -> None:
    await init_mongo()
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = (data_dir / "tiebabot.db").resolve()
    print(f"Using SQLite database at: {db_path.as_posix()}")
    await DBInterface.start(f"sqlite+aiosqlite:///{db_path.as_posix()}")

    async with DBInterface.get_session() as session:
        async with session.begin():
            await _reset_sqlite_tables(session)
            image_map = await _migrate_image_documents(session)
            await _migrate_group_info(session)
            await _migrate_ban_lists(session, image_map)
            await _migrate_associated_data(session, image_map)

    await DBInterface.stop()
    print("Mongo → SQLite migration completed successfully.")


async def main() -> None:
    await migrate()


if __name__ == "__main__":
    asyncio.run(main())
