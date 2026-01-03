from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from aiotieba.enums import ReqUInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tiebameow.client import Client

project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

from src.db import models  # noqa: E402

DB_URL = "postgresql+asyncpg://admin:123456@localhost/tieba_test"


async def get_portrait(client: Client, user_id: int) -> str | None:
    """获取用户头像 portrait。

    Args:
        client (Client): Tiebameow 客户端实例。
        user_id (int): 用户 ID。

    Returns:
        str | None: 用户头像 portrait，获取失败时返回 None。
    """
    try:
        user_info = await client.get_user_info(user_id, require=ReqUInfo.PORTRAIT)
        if not user_info or not user_info.portrait:
            return None
        return user_info.portrait
    except Exception:
        print(f"Failed to get portrait for user_id {user_id}")
        return None


async def fill_banlist_portraits(db_url: str, *, commit_every: int = 200, limit: int | None = None) -> None:
    engine = create_async_engine(db_url, echo=False)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    updated = 0
    scanned = 0
    failed = 0

    async with Client(try_ws=True) as client:
        async with sessionmaker() as session:
            stmt = select(models.BanList).where((models.BanList.portrait == "") | (models.BanList.portrait.is_(None)))
            if limit is not None:
                stmt = stmt.limit(limit)

            stream = await session.stream_scalars(stmt)
            async for row in stream:
                scanned += 1
                portrait = await get_portrait(client, row.user_id)
                if portrait:
                    row.portrait = portrait
                    updated += 1
                else:
                    failed += 1

                if scanned % commit_every == 0:
                    await session.commit()
                    print(f"Progress: scanned={scanned}, updated={updated}, failed={failed}")

            await session.commit()

    await engine.dispose()
    print(f"Done: scanned={scanned}, updated={updated}, failed={failed}")


def main() -> None:
    asyncio.run(fill_banlist_portraits(DB_URL))


if __name__ == "__main__":
    main()
