from nonebot import get_driver
from nonebot.plugin import PluginMetadata

from . import matchers, service

__plugin_meta__ = PluginMetadata(
    name="bawu",
    description="常规吧务管理项",
    usage="",
)


driver = get_driver()


@driver.on_startup
async def _():
    # 恢复未完成的强制删帖任务
    await service.restore_force_delete_tasks()


@driver.on_shutdown
async def _():
    # 保存当前的强制删帖任务
    await service.save_active_force_delete_tasks()
