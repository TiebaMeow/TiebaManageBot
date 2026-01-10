from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from tiebameow.schemas.rules import Action  # noqa: TC002

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class MatchedRule(BaseModel):
    id: int
    name: str
    priority: int
    actions: list[Action]


class ReviewResultPayload(BaseModel):
    matched_rules: list[MatchedRule]
    object_type: str
    target_data: dict[str, Any]
    timestamp: float


class Consumer:
    def __init__(
        self,
        redis_url: str,
        group: str = "executor_group",
        stream_key: str = "reviewer:actions:stream",
    ):
        self.redis_client = Redis.from_url(redis_url, decode_responses=True)
        self.group = group
        self.stream_key = stream_key

    async def __aenter__(self) -> Consumer:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.redis_client.close()

    async def create_group(self) -> None:
        try:
            await self.redis_client.xgroup_create(
                self.stream_key,
                self.group,
                id="0",
                mkstream=True,
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                pass
            raise

    async def consume(self, count: int = 1, block: int = 2000) -> AsyncGenerator[tuple[str, ReviewResultPayload], None]:
        try:
            while True:
                streams = {self.stream_key: ">"}
                messages = await self.redis_client.xreadgroup(
                    groupname=self.group,
                    consumername="consumer-1",
                    streams=cast("dict", streams),
                    count=count,
                    block=block,
                )
                if not messages:
                    continue

                for _, entries in messages:
                    for message_id, message_data in entries:
                        try:
                            # Parse payload
                            raw_data = message_data.get("data")
                            if not raw_data:
                                continue

                            payload_dict = json.loads(raw_data)
                            payload = ReviewResultPayload(**payload_dict)
                            yield message_id, payload
                        except (json.JSONDecodeError, ValueError, TypeError) as e:
                            print(f"Failed to parse message {message_id}: {e}")
                            continue
        finally:
            pass
