from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    # 执行任务的最长时间（分钟）
    force_delete_max_duration: int = 120
    # 每秒尝试删除的次数（整数）
    force_delete_rps: int = 4


config = get_plugin_config(Config)
