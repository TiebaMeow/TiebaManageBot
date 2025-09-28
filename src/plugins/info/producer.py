from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.db import TiebaNameCache
from src.utils import text_to_image

if TYPE_CHECKING:
    from src.common import Client


class AlwaysEqual:
    def __eq__(self, _):
        return True


class Producer:
    def __init__(self, client: Client, user_id: int, fids: list[int] | None):
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=100)
        self.buffer: list[dict[str, str]] = []
        self.user_id = user_id
        self.fids = fids or [AlwaysEqual()]
        self.client = client
        self.current_page = 1
        self.batch_size = 10 if fids else 4
        self.active = True
        self.lock = asyncio.Lock()
        self.cond = asyncio.Condition()
        self.producer_task = asyncio.create_task(self._producer())

    async def _fetch_batch(self) -> bool:
        """获取单个批次的数据"""
        tasks = [
            self.client.get_user_posts(self.user_id, pn=page, rn=50)
            for page in range(self.current_page, self.current_page + self.batch_size)
        ]
        results = await asyncio.gather(*tasks)
        has_empty = False
        for result in results:
            if not result.objs:
                has_empty = True
                break
            self.buffer.extend([
                {
                    "tieba_name": str(await TiebaNameCache.get(post.fid)) + "吧",
                    "post_content": "\n".join([("  - " + obj.contents.text.replace("\\n", " ")) for obj in post.objs]),
                }
                for post in result.objs
                if post.fid in self.fids
            ])
        return has_empty

    async def _generate_msg(self, posts: list[dict[str, str]]) -> bytes:
        """生成消息"""
        posts_str = "\n".join([f"{post['tieba_name']}：\n{post['post_content']}" for post in posts])
        return await text_to_image(posts_str)

    async def _producer(self):
        """生产者主循环"""
        while self.active:
            async with self.cond:
                await self.cond.wait_for(lambda: self.queue.qsize() < 4 or not self.active)
                if not self.active:
                    return
            has_empty = False
            if len(self.buffer) < 20:
                has_empty = await self._fetch_batch()
                self.current_page += self.batch_size
            else:
                await self.queue.put(await self._generate_msg(self.buffer[:20]))
                await asyncio.sleep(0)
                self.buffer = self.buffer[20:]
                continue
            if has_empty:
                if self.buffer:
                    await self.queue.put(await self._generate_msg(self.buffer[:20]))
                await self.queue.put(None)
                return

    async def get(self) -> bytes | None:
        """获取数据"""
        try:
            data = await self.queue.get()
            return data
        finally:
            async with self.lock:
                async with self.cond:
                    self.cond.notify_all()

    async def stop(self):
        """停止数据获取"""
        async with self.lock:
            if self.active:
                self.active = False
                async with self.cond:
                    self.cond.notify_all()
                await self.producer_task
