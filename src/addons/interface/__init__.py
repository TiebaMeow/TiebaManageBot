from nonebot import get_driver, get_plugin_config
from redis.asyncio import Redis

from src.common.cache import close_redis_pool, get_redis, init_redis_pool

from .config import Config
from .session import close_addon_db, get_addon_session, init_addon_db

__all__ = [
    "init_addon_db",
    "close_addon_db",
    "get_addon_session",
    "get_redis_client",
]

driver = get_driver()
plugin_config = get_plugin_config(Config)


@driver.on_startup
async def init_interface():
    await init_addon_db(str(plugin_config.database_url))
    init_redis_pool(str(plugin_config.redis_url))


@driver.on_shutdown
async def close_interface():
    await close_addon_db()
    await close_redis_pool()


async def get_redis_client() -> Redis:
    return get_redis()
