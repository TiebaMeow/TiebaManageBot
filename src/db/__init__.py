from pathlib import Path

from logger import log

from .associated import Associated
from .autoban import AutoBanList
from .cache import AppealCache, GroupCache, TiebaNameCache
from .image_utils import ImageUtils
from .interface import DBInterface
from .models import (
    AssociatedData,
    BanList,
    BanStatus,
    Base,
    GroupInfo,
    Image,
    ImgDataModel,
    ReviewConfig,
    TextDataModel,
)

__all__ = [
    "DBInterface",
    "Base",
    "GroupInfo",
    "Image",
    "BanStatus",
    "BanList",
    "AssociatedData",
    "TextDataModel",
    "ImgDataModel",
    "ImageUtils",
    "ReviewConfig",
    "GroupCache",
    "TiebaNameCache",
    "Associated",
    "AutoBanList",
    "AppealCache",
    "init_db",
]


async def init_db():
    try:
        project_root = Path(__file__).resolve().parents[2]
        data_dir = project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = (data_dir / "tiebabot.db").resolve()
        await DBInterface.start(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    except Exception as e:
        log.error(f"Failed to connect to the database: {e}")
        raise e
    else:
        await GroupCache.load_data()
        log.info("Database connection established successfully.")
