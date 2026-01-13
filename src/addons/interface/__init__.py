from nonebot import get_driver, get_plugin_config
from redis.asyncio import Redis

from .config import Config
from .session import close_addon_db, get_addon_session, init_addon_db

__all__ = [
    "init_addon_db",
    "close_addon_db",
    "get_addon_session",
]

driver = get_driver()
plugin_config = get_plugin_config(Config)


@driver.on_startup
async def init_interface():
    await init_addon_db(str(plugin_config.database_url))


@driver.on_shutdown
async def close_interface():
    await close_addon_db()


async def get_redis_client() -> Redis:
    """获取 Redis 客户端实例。

    Returns:
        Redis: 配置好的 Redis 异步客户端。
    """
    return Redis.from_url(str(plugin_config.redis_url), decode_responses=True)
