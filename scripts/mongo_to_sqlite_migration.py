"""Mongo → SQLite 迁移脚本"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete

from logger import log
from src.db import close_sqlite_db, get_sqlite_session, init_db, init_sqlite_db
from src.db.models import (
    AssociatedData as SQLAssociatedData,
)
from src.db.models import (
    BanList as SQLBanList,
)
from src.db.models import (
    BanReason as SQLBanReason,
)
from src.db.models import (
    GroupInfo as SQLGroupInfo,
)
from src.db.models import (
    ImageDocument as SQLImageDocument,
)
from src.db.models import (
    ImgDataModel,
    TextDataModel,
    serialize_img_data,
    serialize_text_data,
)
from src.db.modules import AssociatedData, AssociatedDataContent, BanList, GroupInfo, ImageDocument

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


async def _reset_sqlite_tables(session: AsyncSession) -> None:
    """Remove existing rows so the migration can run on a clean slate."""

    await session.execute(delete(SQLBanReason))
    await session.execute(delete(SQLBanList))
    await session.execute(delete(SQLAssociatedData))
    await session.execute(delete(SQLGroupInfo))
    await session.execute(delete(SQLImageDocument))


async def _migrate_image_documents(session: AsyncSession) -> dict[str, int]:
    """Copy all Mongo image documents and return an ObjectId → integer ID map."""

    image_map: dict[str, int] = {}
    mongo_images: list[ImageDocument] = await ImageDocument.find_all().to_list()

    for image in mongo_images:
        sql_image = SQLImageDocument(img=image.img, last_update=image.last_update)
        session.add(sql_image)
        await session.flush()
        image_map[str(image.id)] = sql_image.id

    log.info("Migrated %s image documents", len(image_map))
    return image_map


def _convert_text_payloads(text_items: Iterable[TextDataModel | Any]) -> list[dict[str, Any]]:
    models = [
        item
        if isinstance(item, TextDataModel)
        else TextDataModel(
            uploader_id=int(item.uploader_id),
            fid=int(item.fid),
            upload_time=item.upload_time,
            text=str(item.text),
        )
        for item in text_items
    ]
    return serialize_text_data(models)


def _convert_img_payloads(
    img_items: Iterable[Any],
    image_map: dict[str, int],
) -> list[dict[str, Any]]:
    models: list[ImgDataModel] = []
    for item in img_items:
        image_id_str = item.image_id
        mapped = image_map.get(str(image_id_str))
        if mapped is None:
            raise KeyError(f"Unmapped image ObjectId: {image_id_str}")
        models.append(
            ImgDataModel(
                uploader_id=int(item.uploader_id),
                fid=int(item.fid),
                upload_time=item.upload_time,
                image_id=mapped,
                note=str(getattr(item, "note", "")),
            )
        )
    return serialize_img_data(models)


async def _migrate_group_info(session: AsyncSession) -> None:
    mongo_groups: list[GroupInfo] = await GroupInfo.find_all().to_list()
    for group in mongo_groups:
        sql_group = SQLGroupInfo(
            group_id=group.group_id,
            master=group.master,
            admins=list(group.admins),
            moderators=list(group.moderators),
            fid=group.fid,
            fname=group.fname,
            master_bduss=group.master_BDUSS,
            slave_bduss=group.slave_BDUSS,
            slave_stoken=group.slave_STOKEN,
            is_public=group.is_public,
            appeal_sub=group.appeal_sub,
            appeal_autodeny=group.appeal_autodeny,
            last_update=group.last_update,
        )
        session.add(sql_group)
    log.info("Migrated %s group info records", len(mongo_groups))


async def _migrate_ban_lists(session: AsyncSession, image_map: dict[str, int]) -> None:
    mongo_banlists: list[BanList] = await BanList.find_all().to_list()
    for banlist in mongo_banlists:
        sql_banlist = SQLBanList(
            group_id=banlist.group_id,
            fid=banlist.fid,
            last_autoban=banlist.last_autoban,
            last_update=banlist.last_update,
        )
        session.add(sql_banlist)
        await session.flush()

        for user_id, reason in banlist.ban_list.items():
            text_payloads = _convert_text_payloads(reason.text_reason)
            img_payloads = _convert_img_payloads(reason.img_reason, image_map)
            sql_reason = SQLBanReason(
                ban_list_id=sql_banlist.id,
                user_id=int(user_id),
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

    log.info("Migrated %s ban list records", len(mongo_banlists))


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
            user_name=list(assoc.user_name),
            nicknames=list(assoc.nicknames),
            creater_id=assoc.creater_id,
            is_public=bool(assoc.is_public),
            text_data=text_payloads,
            img_data=img_payloads,
            last_update=assoc.last_update,
        )
        session.add(sql_assoc)

    log.info("Migrated %s associated data records", len(mongo_associated))


async def migrate() -> None:
    await init_db()
    await init_sqlite_db()

    async for session in get_sqlite_session():
        async with session.begin():
            await _reset_sqlite_tables(session)
            image_map = await _migrate_image_documents(session)
            await _migrate_group_info(session)
            await _migrate_ban_lists(session, image_map)
            await _migrate_associated_data(session, image_map)
        break

    await close_sqlite_db()
    log.info("Mongo → SQLite migration completed successfully.")


async def main() -> None:
    await migrate()


if __name__ == "__main__":
    asyncio.run(main())
