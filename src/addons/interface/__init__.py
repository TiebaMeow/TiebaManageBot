from nonebot import get_driver, get_plugin_config

from .config import Config
from .interface import Interface

driver = get_driver()
plugin_config = get_plugin_config(Config)


@driver.on_startup
async def init_interface():
    await Interface.start(str(plugin_config.database_url))
