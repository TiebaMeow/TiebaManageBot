from nonebot import get_driver, get_plugin_config

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
