from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from logger import log

from .associated import Associated
from .autoban import AutoBanList
from .cache import AppealCache, ChromiumCache, GroupCache, TiebaNameCache
from .image_utils import ImageUtils
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


async def init_db():
    try:
        client = AsyncIOMotorClient(host="mongodb://localhost:27017")
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


async def init_chromium():
    try:
        await ChromiumCache.initialize()
        assert ChromiumCache.browser is not None
    except Exception as e:
        log.error(f"Failed to initialize Chromium: {e}")
        raise e
    else:
        log.info("Chromium initialized successfully.")


async def close_chromium():
    try:
        await ChromiumCache.close()
    except Exception as e:
        log.error(f"Failed to close Chromium: {e}")
        raise e
    else:
        log.info("Chromium closed successfully.")
