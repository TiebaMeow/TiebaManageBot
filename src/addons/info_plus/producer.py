from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NamedTuple

from src.addons.interface.crud.user_posts import get_user_history_mixed
from src.common.cache import get_tieba_name
from src.utils import text_to_image

if TYPE_CHECKING:
    from aiotieba.api.tieba_uid2user_info._classdef import UserInfo_TUid


class UserHistoryItem(NamedTuple):
    tieba_name: str
    content: str
    create_time: str


class DBProducer:
    def __init__(self, user_info: UserInfo_TUid, fids: list[int] | None):
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=4)
        self.buffer: list[dict[str, str]] = []
        self.user_info = user_info
        self.fids = fids
        self.current_page = 1
        self.page_show = 1
        self.batch_size = 50
        self.producer_task = asyncio.create_task(self._producer())

    async def _fetch_batch(self) -> bool:
        """获取单个批次的数据"""
        items = await get_user_history_mixed(
            self.user_info.user_id, self.fids, page=self.current_page, limit=self.batch_size
        )

        has_empty = len(items) == 0
        new_items = []

        for item in items:
            tieba_name = str(await get_tieba_name(item.fid)) + "吧"

            content = item.text.replace("\n", " ").strip()
            # 截断防止内容过长
            # if len(content) > 100:
            #     content = content[:100] + "..."

            post_content = "  - "
            if item.type == "thread":
                post_content += f"发贴：{item.title} -> {content}"
            else:
                post_content += f"回复：{item.title} -> {content}"

            new_items.append({
                "tieba_name": tieba_name,
                "post_content": post_content,
                "create_time": item.create_time.strftime("%Y-%m-%d %H:%M"),
            })

        self.buffer.extend(new_items)
        return has_empty

    async def _generate_msg(self, posts: list[dict[str, str]], page: int) -> bytes:
        """生成消息"""
        lines = [f"{post['tieba_name']} ({post['create_time']})：\n{post['post_content']}" for post in posts]

        posts_str = "\n".join(lines)

        return await text_to_image(
            posts_str,
            header=f"用户 {self.user_info.show_name}({self.user_info.tieba_uid}) 的历史发言",
            footer=f"第 {page} 页",
        )

    async def _producer(self):
        """生产者主循环"""
        try:
            while True:
                if len(self.buffer) < 20:
                    has_empty = await self._fetch_batch()
                    self.current_page += 1

                    if has_empty:
                        while self.buffer:
                            chunk = self.buffer[:20]
                            self.buffer = self.buffer[20:]
                            await self.queue.put(await self._generate_msg(chunk, self.page_show))
                            self.page_show += 1
                        await self.queue.put(None)
                        return

                    continue
                else:
                    chunk = self.buffer[:20]
                    self.buffer = self.buffer[20:]
                    await self.queue.put(await self._generate_msg(chunk, self.page_show))
                    self.page_show += 1

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
