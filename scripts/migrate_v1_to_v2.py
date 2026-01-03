import asyncio
import sys
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Add project root to sys.path
project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

# Import old models
from src.db import models as old_models

# Import new models
from src.db import models_v2 as new_models

# Configuration
OLD_DB_PATH = project_root / "data" / "tiebabot.db"
OLD_DB_URL = f"sqlite+aiosqlite:///{OLD_DB_PATH.as_posix()}"

# Default to a new SQLite file for testing, user can change this to PG
# Example PG URL: "postgresql+asyncpg://user:password@localhost/dbname"
# NEW_DB_PATH = project_root / "data" / "tiebabot_v2.db"
# NEW_DB_URL = f"sqlite+aiosqlite:///{NEW_DB_PATH.as_posix()}"
NEW_DB_URL = "postgresql+asyncpg://admin:123456@localhost/tieba_test"  # Change as needed


async def reset_postgres_sequences(session):
    """重置 Postgres 的自增序列到当前最大 ID"""
    # 获取所有表名
    tables = [
        "images",
        "ban_list",
        "associated_list",
    ]

    print("Resetting PostgreSQL sequences...")
    for table in tables:
        try:
            # PostgreSQL 特有语法: setval
            # 假设主键名为 id
            sql = text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 0) + 1, false) FROM {table};"
            )
            await session.execute(sql)
        except Exception as e:
            print(f"Skipping sequence reset for {table} (might not be PG or table empty): {e}")
    await session.commit()


async def migrate():
    print(f"Migrating from {OLD_DB_URL} to {NEW_DB_URL}")

    # Setup engines
    old_engine = create_async_engine(OLD_DB_URL, echo=False)
    new_engine = create_async_engine(NEW_DB_URL, echo=False)

    OldSession = async_sessionmaker(old_engine, expire_on_commit=False)  # noqa: N806
    NewSession = async_sessionmaker(new_engine, expire_on_commit=False)  # noqa: N806

    # Create tables in new DB
    async with new_engine.begin() as conn:
        await conn.run_sync(new_models.Base.metadata.create_all)

    async with OldSession() as old_session, NewSession() as new_session:
        # 1. Migrate Images (Direct copy)
        print("Migrating Images...")
        result = await old_session.execute(select(old_models.Image))
        old_images = result.scalars().all()
        for old_img in old_images:
            new_img = new_models.Image(id=old_img.id, img=old_img.img, last_update=old_img.last_update)
            new_session.add(new_img)
        await new_session.commit()

        # 2. Migrate GroupInfo
        print("Migrating GroupInfo...")
        result = await old_session.execute(select(old_models.GroupInfo))
        old_groups = result.scalars().all()
        for old_group in old_groups:
            admins = list(dict.fromkeys(old_group.admins or []))
            moderators = list(dict.fromkeys(old_group.moderators or []))
            new_group = new_models.GroupInfo(
                group_id=old_group.group_id,
                master=old_group.master,
                admins=admins,
                moderators=moderators,
                fid=old_group.fid,
                fname=old_group.fname,
                master_bduss=old_group.master_bduss,
                slave_bduss=old_group.slave_bduss,
                slave_stoken=old_group.slave_stoken,
                group_args=old_group.group_args,
                last_update=old_group.last_update,
            )
            new_session.add(new_group)
        await new_session.commit()

        # 3. Migrate BanStatus (Direct copy)
        print("Migrating BanStatus...")
        result = await old_session.execute(select(old_models.BanStatus))
        old_statuses = result.scalars().all()
        for old_status in old_statuses:
            new_status = new_models.BanStatus(
                fid=old_status.fid,
                group_id=old_status.group_id,
                last_autoban=old_status.last_autoban,
                last_update=old_status.last_update,
            )
            new_session.add(new_status)
        await new_session.commit()

        # 4. Migrate ReviewConfig (Direct copy)
        print("Migrating ReviewConfig...")
        result = await old_session.execute(select(old_models.ReviewConfig))
        old_configs = result.scalars().all()
        for old_config in old_configs:
            new_config = new_models.ReviewConfig(
                fid=old_config.fid,
                group_id=old_config.group_id,
                rule_type=old_config.rule_type,
                notify_type=old_config.notify_type,
                rule_content=old_config.rule_content,
                last_update=old_config.last_update,
            )
            new_session.add(new_config)
        await new_session.commit()

        # 5. Migrate BanList
        print("Migrating BanList...")
        result = await old_session.execute(select(old_models.BanList))
        old_bans = result.scalars().all()
        for old_ban in old_bans:
            text_reason = [
                new_models.TextDataModel(
                    uploader_id=r.uploader_id,
                    fid=r.fid,
                    upload_time=r.upload_time,
                    text=r.text,
                )
                for r in (old_ban.text_reason or [])
            ]
            img_reason = [
                new_models.ImgDataModel(
                    uploader_id=r.uploader_id,
                    fid=r.fid,
                    upload_time=r.upload_time,
                    image_id=r.image_id,
                    note=r.note,
                )
                for r in (old_ban.img_reason or [])
            ]
            new_ban = new_models.BanList(
                id=old_ban.id,
                fid=old_ban.fid,
                user_id=old_ban.user_id,
                portrait="",
                ban_time=old_ban.ban_time,
                operator_id=old_ban.operator_id,
                enable=old_ban.enable,
                unban_time=old_ban.unban_time,
                unban_operator_id=old_ban.unban_operator_id,
                text_reason=text_reason,
                img_reason=img_reason,
                last_update=old_ban.last_update,
            )
            new_session.add(new_ban)
        await new_session.commit()

        # 6. Migrate AssociatedData
        print("Migrating AssociatedData...")
        result = await old_session.execute(select(old_models.AssociatedData))
        old_assocs = result.scalars().all()
        for old_assoc in old_assocs:
            text_data = [
                new_models.TextDataModel(
                    uploader_id=r.uploader_id,
                    fid=r.fid,
                    upload_time=r.upload_time,
                    text=r.text,
                )
                for r in (old_assoc.text_data or [])
            ]
            img_data = [
                new_models.ImgDataModel(
                    uploader_id=r.uploader_id,
                    fid=r.fid,
                    upload_time=r.upload_time,
                    image_id=r.image_id,
                    note=r.note,
                )
                for r in (old_assoc.img_data or [])
            ]
            new_assoc = new_models.AssociatedList(
                id=old_assoc.id,
                user_id=old_assoc.user_id,
                fid=old_assoc.fid,
                tieba_uid=old_assoc.tieba_uid,
                portrait=old_assoc.portrait,
                user_name=list(dict.fromkeys(old_assoc.user_name or [])),
                nicknames=list(dict.fromkeys(old_assoc.nicknames or [])),
                creater_id=old_assoc.creater_id,
                is_public=old_assoc.is_public,
                text_data=text_data,
                img_data=img_data,
                last_update=old_assoc.last_update,
            )
            new_session.add(new_assoc)
        await new_session.commit()

    if "postgresql" in NEW_DB_URL:
        async with NewSession() as session:
            await reset_postgres_sequences(session)

    print("Migration completed successfully!")
    await old_engine.dispose()
    await new_engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
