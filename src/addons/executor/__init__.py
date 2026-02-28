import asyncio

from nonebot import get_driver

from logger import log

from . import matchers as matchers
from .consumer import Consumer

driver = get_driver()

_consumer: Consumer | None = None

executor_task: asyncio.Task | None = None


async def __run_consumer():
    if _consumer is None:
        raise RuntimeError("Consumer not initialized")
    async with _consumer:
        await _consumer.run()


@driver.on_bot_connect
async def start_consumer():
    global executor_task, _consumer
    if executor_task is None:
        log.info("Starting executor consumer...")
        _consumer = Consumer()
        executor_task = asyncio.create_task(__run_consumer())


@driver.on_shutdown
async def stop_consumer():
    log.info("Stopping executor consumer...")
    if _consumer:
        _consumer.stop()
    if executor_task:
        await executor_task
    log.info("Executor consumer stopped.")
