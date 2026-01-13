import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    def __init__(self, capacity: int, default_ttl: int = 60):
        self.capacity = capacity
        self.default_ttl = default_ttl
        self.cache = OrderedDict()

    def get(self, key: str) -> Any | None:
        if key not in self.cache:
            return None

        value, expire_time = self.cache[key]
        if time.time() > expire_time:
            self.cache.pop(key)
            return None

        self.cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if ttl is None:
            ttl = self.default_ttl

        if key in self.cache:
            self.cache.move_to_end(key)

        self.cache[key] = (value, time.time() + ttl)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
