from pathlib import Path

from loguru import logger

# 创建日志目录
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 移除默认的 logger 配置
# logger.remove()

# 添加自定义日志配置
logger.add(
    LOG_DIR / "tiebabot.log",
    rotation="1 month",
    retention=None,
    compression=None,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {module}:{function} | {message}",
    filter=lambda record: record["extra"].get("name") == "app_log",
)

# 定义一个全局的 logger 实例
log = logger.bind(name="app_log")
