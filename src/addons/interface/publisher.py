from __future__ import annotations

import json
from typing import Literal

from nonebot import get_plugin_config
from redis.asyncio import Redis

from logger import log

from .config import Config

config = get_plugin_config(Config)


class EventPublisher:
    _instance: EventPublisher | None = None
    _redis: Redis | None = None

    def __new__(cls) -> EventPublisher:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(
                str(config.redis_url),
                decode_responses=True,
            )
        return self._redis

    async def publish_rule_update(self, rule_id: int, event_type: Literal["ADD", "UPDATE", "DELETE"]) -> None:
        """发布规则更新事件

        Args:
            rule_id: 规则ID
        """
        channel = config.redis_channel
        payload = {"rule_id": rule_id, "type": event_type}
        try:
            await self.redis.publish(channel, json.dumps(payload))
            log.info(f"Published rule update to {channel}: {payload}")
        except Exception as e:
            log.error(f"Failed to publish rule update: {e}")


publisher = EventPublisher()
