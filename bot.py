import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from src.common import ClientCache
from src.db import init_db

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)


@driver.on_startup
async def startup():
    await init_db()


@driver.on_shutdown
async def shutdown():
    await ClientCache.stop()


nonebot.load_from_toml("pyproject.toml")

config = driver.config
review_enabled = getattr(config, "enable_addons", False)
if review_enabled:
    nonebot.load_plugins("src/addons")

if __name__ == "__main__":
    nonebot.run()
