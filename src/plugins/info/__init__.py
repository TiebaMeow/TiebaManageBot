from nonebot.plugin import PluginMetadata

from . import matchers
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="info",
    description="信息查询与导入",
    usage="",
    config=Config,
)
