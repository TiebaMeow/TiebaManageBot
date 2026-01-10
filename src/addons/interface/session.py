from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from nonebot import get_driver
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

driver = get_driver()

_addon_engine: AsyncEngine | None = None
_addon_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def init_addon_db(addon_db_url: str) -> None:
    global _addon_engine, _addon_sessionmaker

    try:
        engine = create_async_engine(addon_db_url, echo=False, future=True)
        _addon_engine = engine
    except Exception as e:
        raise RuntimeError(f"Failed to create database engine: {e}") from e

    if _addon_engine is not None:
        _addon_sessionmaker = async_sessionmaker(_addon_engine, class_=AsyncSession, expire_on_commit=False)


async def close_addon_db() -> None:
    global _addon_engine, _addon_sessionmaker

    if _addon_engine is not None:
        await _addon_engine.dispose()
        _addon_engine = None
    _addon_sessionmaker = None


@asynccontextmanager
async def get_addon_session() -> AsyncGenerator[AsyncSession, None]:
    if _addon_sessionmaker is None:
        raise RuntimeError("Addon database is not initialized. Call init_addon_db first.")
    async with _addon_sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
