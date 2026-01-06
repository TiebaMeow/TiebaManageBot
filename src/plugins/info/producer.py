from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.common import get_user_posts_cached
from src.common.cache import get_tieba_name
from src.utils import text_to_image

if TYPE_CHECKING:
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid
    from tiebameow.client import Client


class Producer:
    def __init__(self, client: Client, user_info: UserInfo_TUid, fids: list[int] | None):
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=4)
        self.buffer: list[dict[str, str]] = []
        self.user_info = user_info
        self.fids = set(fids) if fids else None
        self.client = client
        self.current_page = 1
        self.batch_size = 10 if fids else 4
        self.producer_task = asyncio.create_task(self._producer())

    async def _fetch_batch(self) -> bool:
        """获取单个批次的数据"""
        tasks = [
            get_user_posts_cached(self.client, self.user_info.user_id, pn=page, rn=50)
            for page in range(self.current_page, self.current_page + self.batch_size)
        ]
        results = await asyncio.gather(*tasks)
        has_empty = False
        new_items = []

        for result in results:
            if not result.objs:
                has_empty = True
                break

            for post in result.objs:
                if self.fids is not None and post.fid not in self.fids:
                    continue

                tieba_name = str(await get_tieba_name(post.fid)) + "吧"
                post_content = "\n".join([("  - " + obj.contents.text.replace("\\n", " ")) for obj in post.objs])

                new_items.append({
                    "tieba_name": tieba_name,
                    "post_content": post_content,
                })

        self.buffer.extend(new_items)
        return has_empty

    async def _generate_msg(self, posts: list[dict[str, str]], page: int) -> bytes:
        """生成消息"""
        posts_str = "\n".join([f"{post['tieba_name']}：\n{post['post_content']}" for post in posts])
        return await text_to_image(
            posts_str,
            header=f"用户 {self.user_info.show_name}({self.user_info.tieba_uid}) 的回复历史",
            footer=f"第 {page} 页",
        )

    async def _producer(self):
        """生产者主循环"""
        try:
            while True:
                if len(self.buffer) < 20:
                    has_empty = await self._fetch_batch()
                    self.current_page += self.batch_size

                    if has_empty:
                        while self.buffer:
                            chunk = self.buffer[:20]
                            self.buffer = self.buffer[20:]
                            await self.queue.put(await self._generate_msg(chunk, self.current_page))
                        await self.queue.put(None)
                        return
                else:
                    chunk = self.buffer[:20]
                    self.buffer = self.buffer[20:]
                    await self.queue.put(await self._generate_msg(chunk, self.current_page))

        except asyncio.CancelledError:
            pass
        except Exception:
            await self.queue.put(None)

    async def get(self) -> bytes | None:
        """获取数据"""
        return await self.queue.get()

    async def stop(self):
        """停止数据获取"""
        if not self.producer_task.done():
            self.producer_task.cancel()
            try:
                await self.producer_task
            except asyncio.CancelledError:
                pass
