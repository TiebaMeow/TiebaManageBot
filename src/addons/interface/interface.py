from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

# import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# from .models import Base
# from src.utils.deserialization import deserialize

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class Interface:
    db_engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    @classmethod
    async def start(cls, db_url: str) -> None:
        cls.db_engine = create_async_engine(db_url, echo=False, future=True)
        cls.sessionmaker = async_sessionmaker(cls.db_engine, class_=AsyncSession, expire_on_commit=False)
        # async with cls.db_engine.begin() as conn:
        #     await conn.run_sync(Base.metadata.create_all)

    @classmethod
    async def stop(cls) -> None:
        await cls.db_engine.dispose()
        del cls.db_engine
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
