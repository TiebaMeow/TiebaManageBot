from collections.abc import AsyncGenerator
from pathlib import Path

from beanie import init_beanie
from pymongo import AsyncMongoClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from logger import log

from .associated import Associated
from .autoban import AutoBanList
from .cache import AppealCache, GroupCache, TiebaNameCache
from .image_utils import ImageUtils
from .models import Base
from .modules import (
    ApiUser,
    AssociatedData,
    AssociatedDataContent,
    BanList,
    BanReason,
    GroupInfo,
    ImageDocument,
    ImgData,
    TextData,
)

__all__ = [
    "init_db",
    "init_sqlite_db",
    "close_sqlite_db",
    "get_sqlite_session",
]

SQLITE_ENGINE: AsyncEngine | None = None
SQLITE_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = None
DEFAULT_SQLITE_FILENAME = "tiebabot.db"


async def init_db():
    try:
        client = AsyncMongoClient(host="mongodb://localhost:27017")
        await init_beanie(
            database=client.tiebabot,
            document_models=[
                ApiUser,
                GroupInfo,
                AssociatedData,
                BanList,
                ImageDocument,
            ],
        )
    except Exception as e:
        log.error(f"Failed to connect to the database: {e}")
        raise e
    else:
        await GroupCache.load_data()
        log.info("Database connection established successfully.")


def _resolve_sqlite_path(db_path: Path | None) -> Path:
    if db_path is not None:
        return db_path.resolve()
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return (data_dir / DEFAULT_SQLITE_FILENAME).resolve()


async def init_sqlite_db(db_path: Path | None = None, *, echo: bool = False) -> AsyncEngine:
    """Initialise the SQLite engine and create tables if needed."""

    global SQLITE_ENGINE, SQLITE_SESSION_FACTORY

    if SQLITE_ENGINE is not None:
        return SQLITE_ENGINE

    target_path = _resolve_sqlite_path(db_path)
    database_url = f"sqlite+aiosqlite:///{target_path.as_posix()}"
    engine = create_async_engine(database_url, echo=echo, future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SQLITE_ENGINE = engine
    SQLITE_SESSION_FACTORY = async_sessionmaker(engine, expire_on_commit=False)
    log.info("SQLite database initialised at %s", target_path)
    return engine


async def close_sqlite_db() -> None:
    """Dispose of the SQLite engine and session factory."""

    global SQLITE_ENGINE, SQLITE_SESSION_FACTORY

    if SQLITE_ENGINE is not None:
        await SQLITE_ENGINE.dispose()
        SQLITE_ENGINE = None

    SQLITE_SESSION_FACTORY = None


async def get_sqlite_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession``; requires ``init_sqlite_db`` to be called first."""

    if SQLITE_SESSION_FACTORY is None:
        raise RuntimeError("SQLite database has not been initialised. Call init_sqlite_db() first.")

    async with SQLITE_SESSION_FACTORY() as session:
        yield session
