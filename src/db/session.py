from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import nonebot
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from tiebameow.models.orm import RuleBase

from logger import log

from .models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

project_root = Path(__file__).resolve().parents[2]
data_dir = project_root / "data"
data_dir.mkdir(parents=True, exist_ok=True)

db_path = data_dir / "tiebabot.db"
db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"


async def init_db() -> None:
    global _engine, _sessionmaker, db_url

    # 尝试从配置中读取 PostgreSQL 连接信息
    try:
        config = nonebot.get_driver().config
        pg_host = getattr(config, "pg_host", None)
        if pg_host:
            pg_port = getattr(config, "pg_port", 5432)
            pg_user = getattr(config, "pg_username", None)
            pg_password = getattr(config, "pg_password", None)
            pg_db = getattr(config, "pg_db", None)

            if pg_user and pg_password and pg_db:
                pg_url = f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
                try:
                    engine = create_async_engine(pg_url, echo=False, future=True)
                    async with engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                        enable_addons = getattr(config, "enable_addons", False)
                        if enable_addons:
                            await conn.run_sync(RuleBase.metadata.create_all)
                    _engine = engine
                    db_url = pg_url
                    log.info(f"Connected to PostgreSQL: {pg_host}:{pg_port}/{pg_db}")
                except Exception as e:
                    log.warning(f"Failed to connect to PostgreSQL: {e}. Fallback to SQLite.")
                    if _engine:
                        await _engine.dispose()
                    _engine = None
    except Exception as e:
        log.warning(f"Error reading config or initializing PG: {e}. Fallback to SQLite.")

    if _engine is None:
        _engine = create_async_engine(db_url, echo=False, future=True)
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info(f"Connected to SQLite: {db_path}")
    else:
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def close_db() -> None:
    global _engine, _sessionmaker
    if _engine:
        await _engine.dispose()
        _engine = None
    _sessionmaker = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if _sessionmaker is None:
        raise RuntimeError("Database is not initialized. Call init_db first.")
    async with _sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
