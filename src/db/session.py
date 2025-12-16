from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

project_root = Path(__file__).resolve().parents[2]
data_dir = project_root / "data"
data_dir.mkdir(parents=True, exist_ok=True)

db_path = data_dir / "tiebabot.db"
db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"


async def init_db() -> None:
    global _engine, _sessionmaker
    _engine = create_async_engine(db_url, echo=False, future=True)
    _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
