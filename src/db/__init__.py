from beanie import init_beanie
from pymongo import AsyncMongoClient

from logger import log

from .associated import Associated
from .autoban import AutoBanList
from .cache import AppealCache, GroupCache, TiebaNameCache
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
