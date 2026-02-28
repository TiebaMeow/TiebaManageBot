import asyncio

from nonebot import get_driver

from logger import log

from . import matchers as matchers
from .consumer import Consumer

driver = get_driver()

_consumer = Consumer()

task: asyncio.Task | None = None


async def _run_consumer():
    async with _consumer:
        await _consumer.run()


@driver.on_bot_connect
async def start_consumer():
    global task
    if task is None:
        log.info("Starting executor consumer...")
        task = asyncio.create_task(_run_consumer())


@driver.on_shutdown
async def stop_consumer():
    log.info("Stopping executor consumer...")
    _consumer.stop()
    if task:
        await task
    log.info("Executor consumer stopped.")
