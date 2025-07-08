import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from src.db import close_chromium, init_chromium, init_db

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)


@driver.on_startup
async def startup():
    await init_db()
    await init_chromium()


@driver.on_shutdown
async def shutdown():
    await close_chromium()


nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
