from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, cast

import redis.asyncio as redis
from tiebameow.serializer import deserialize

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable

    from aiotieba.typing import Comment, Post, Thread


class Consumer:
    def __init__(
        self,
        redis_url: str,
        group: str,
        stream_suffixes: Iterable[str],
        stream_prefix: str = "scraper:tieba:events",
    ):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.group = group
        self.stream_prefix = stream_prefix
        self.streams = {f"{self.stream_prefix}:{suffix}": ">" for suffix in stream_suffixes}

    async def __aenter__(self) -> Consumer:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.redis_client.close()

    async def create_group(self) -> None:
        for stream in self.streams:
            try:
                await self.redis_client.xgroup_create(
                    stream,
                    self.group,
                    id="0",
                    mkstream=True,
                )
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

    async def consume(
        self, count: int = 1, block: int = 10000
    ) -> AsyncGenerator[tuple[Literal["thread", "post", "comment"], int, Thread | Post | Comment], None]:
        try:
            while True:
                message: list[tuple[str, list[tuple[str, dict[str, Any]]]]] | None = await self.redis_client.xreadgroup(
                    groupname=self.group,
                    consumername="consumer-1",
                    streams=cast("dict", self.streams),
                    count=count,
                    block=block,
                )
                if not message:
                    continue
                try:
                    _stream, entries = message[0]
                    _msg_id, fields = entries[0]
                    raw = fields.get("data")
                    if raw is None:
                        continue
                    data = json.loads(raw)
                    object_type = data.get("object_type")
                    object_id = data.get("object_id")
                    payload = data.get("payload")
                    obj = deserialize(object_type, payload)
                except Exception:
                    pass
                else:
                    yield object_type, object_id, obj
                    await self.redis_client.xack(_stream, self.group, _msg_id)
        finally:
            pass


async def test():
    async with Consumer(
        "redis://localhost:6379/0",
        "test-group",
        [
            "987654321:thread",
            "123456789:thread",
            "123456789:post",
            "123456789:comment",
        ],
    ) as consumer:
        await consumer.create_group()
        async for obj_type, obj_id, obj in consumer.consume():
            print(f"Received {obj_type} with ID {obj_id}: {obj}")
