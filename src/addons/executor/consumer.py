from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from redis.exceptions import ResponseError

from logger import log
from src.common.cache import get_redis

from .executor import Executor
from .template import ReviewResultPayload


class Consumer:
    def __init__(
        self,
        group: str = "executor_group",
        stream_key: str = "reviewer:actions:stream",
        batch_size: int = 10,
    ):
        self._redis_client = get_redis()
        self._group = group
        self._stream_key = stream_key
        self._batch_size = batch_size
        self._running = False
        self._recovery_task: asyncio.Task[None] | None = None
        self._executor = Executor()

    async def __aenter__(self) -> Consumer:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def run(self) -> None:
        """启动Worker。

        初始化消费者组，启动恢复任务，并进入主消费循环。
        """
        self._running = True
        await self._ensure_consumer_group()

        self._recovery_task = asyncio.create_task(self._recovery())
        log.info("Stream recovery task started for {}.", self._stream_key)

        log.info("Worker started. Listening on {}", self._stream_key)

        while self._running:
            try:
                streams = {self._stream_key: ">"}
                messages = await self._redis_client.xreadgroup(
                    groupname=self._group,
                    consumername="consumers-1",
                    streams=cast("dict", streams),  # type: ignore
                    count=self._batch_size,
                    block=2000,
                )

                if not messages:
                    continue

                tasks = []
                for _stream_name, entries in messages:
                    for message_id, message_data in entries:
                        tasks.append(self._process_message(message_id, message_data))

                if tasks:
                    await asyncio.gather(*tasks)

            except Exception as e:
                log.error("Error in worker loop: {}", e)
                await asyncio.sleep(1)

    def stop(self) -> None:
        """停止Worker。

        设置停止标志并取消后台任务。
        """
        self._running = False
        if self._recovery_task:
            self._recovery_task.cancel()

    async def _ensure_consumer_group(self) -> None:
        try:
            await self._redis_client.xgroup_create(
                self._stream_key,
                self._group,
                id="0",
                mkstream=True,
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise e

    async def _process_message(self, message_id: str, fields: dict[str, Any]) -> None:
        """处理单条消息。

        反序列化数据，执行动作，并确认消息。

        Args:
            message_id: 消息 ID。
            fields: 消息字段字典。
        """
        try:
            raw_data = fields.get("data")
            if not raw_data:
                log.warning("Message {} missing data field.", message_id)
                await self._ack(message_id)
                return

            payload_dict = json.loads(raw_data)
            payload = ReviewResultPayload.model_validate(payload_dict)

            # 处理 payload，执行相应动作
            await self._executor.execute(payload)

            # ACK
            await self._ack(message_id)

        except Exception as e:
            log.error("Failed to process message {}: {}", message_id, e)
            await self._ack(message_id)

    async def _ack(self, message_id: str) -> None:
        """确认消息已处理。

        Args:
            message_id: 消息 ID。
        """
        await self._redis_client.xack(self._stream_key, self._group, message_id)

    async def _recovery(self) -> None:
        """消息恢复。

        启动时扫描并认领长时间未处理的消息 (PEL)，防止消息丢失。
        """
        try:
            await asyncio.sleep(60)
            messages = await self._redis_client.xautoclaim(
                self._stream_key,
                self._group,
                "consumers-1",
                min_idle_time=60000,
                count=2000,
            )

            # messages 结构: (next_start_id, entries, [deleted_ids])
            # entries 是列表 [(message_id, fields), ...]
            if messages:
                entries = messages[1]
                if entries:
                    log.info("Recovered {} messages.", len(entries))
                    for message_id, fields in entries:
                        await self._process_message(message_id, fields)

        except asyncio.CancelledError:
            return

        except Exception as e:
            log.error("Error in recovery task: {}", e)
