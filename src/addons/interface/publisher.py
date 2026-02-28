from __future__ import annotations

import json
from typing import Literal

from nonebot import get_plugin_config

from logger import log
from src.common.cache import get_redis

from .config import Config

config = get_plugin_config(Config)


class EventPublisher:
    _instance: EventPublisher | None = None

    def __new__(cls) -> EventPublisher:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def redis(self):
        return get_redis()

    async def publish_rule_update(self, rule_id: int, event_type: Literal["ADD", "UPDATE", "DELETE"]) -> None:
        channel = config.redis_channel
        payload = {"rule_id": rule_id, "type": event_type}
        try:
            await self.redis.publish(channel, json.dumps(payload))
            log.info(f"Published rule update to {channel}: {payload}")
        except Exception as e:
            log.error(f"Failed to publish rule update: {e}")


publisher = EventPublisher()
