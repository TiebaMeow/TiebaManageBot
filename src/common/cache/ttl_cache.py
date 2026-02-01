import asyncio
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    def __init__(self, capacity: int, default_ttl: int = 60, cleanup_interval: int = 600):
        self.capacity = capacity
        self.default_ttl = default_ttl
        self.cleanup_interval = cleanup_interval
        self.cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(self.cleanup_interval)
            async with self._lock:
                current_time = time.time()
                keys_to_remove = [key for key, (_, expire_time) in self.cache.items() if current_time > expire_time]
                for key in keys_to_remove:
                    self.cache.pop(key, None)

    def _ensure_cleanup_running(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = loop.create_task(self._cleanup_loop())

    async def get(self, key: str) -> Any | None:
        self._ensure_cleanup_running()
        async with self._lock:
            if key not in self.cache:
                return None

            value, expire_time = self.cache[key]
            if time.time() > expire_time:
                self.cache.pop(key)
                return None

            self.cache.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._ensure_cleanup_running()
        if ttl is None:
            ttl = self.default_ttl

        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)

            self.cache[key] = (value, time.time() + ttl)
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    async def clear(self):
        async with self._lock:
            self.cache.clear()

    async def close(self):
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._cleanup_task = None
