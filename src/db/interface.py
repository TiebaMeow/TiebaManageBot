from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class DBInterface:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    @classmethod
    async def start(cls, db_url: str):
        cls.engine = create_async_engine(db_url, echo=False, future=True)
        cls.sessionmaker = async_sessionmaker(cls.engine, class_=AsyncSession, expire_on_commit=False)
        async with cls.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @classmethod
    async def stop(cls) -> None:
        await cls.engine.dispose()
        del cls.engine
        del cls.sessionmaker

    @classmethod
    @asynccontextmanager
    async def get_session(cls) -> AsyncGenerator[AsyncSession, None]:
        async with cls.sessionmaker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
