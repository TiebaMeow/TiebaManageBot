from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from nonebot import get_driver
from tiebameow.renderer import Renderer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiotieba.api.get_posts._classdef import Thread_p
    from aiotieba.typing import Post, Thread
    from tiebameow.models.dto import PostDTO, ThreadDTO, ThreadpDTO

driver = get_driver()


class RendererCache:
    _renderer: Renderer | None = None

    @classmethod
    async def initialize(cls) -> None:
        if cls._renderer is None:
            cls._renderer = Renderer()
            await cls._renderer.__aenter__()

    @classmethod
    async def close(cls) -> None:
        if cls._renderer is not None:
            await cls._renderer.__aexit__(None, None, None)
            cls._renderer = None

    @classmethod
    async def get_renderer(cls) -> Renderer:
        """
        获取 Renderer 实例。

        Returns:
            Renderer 实例
        """
        if cls._renderer is None:
            raise RuntimeError("Renderer is not initialized.")
        return cls._renderer


@driver.on_startup
async def on_startup() -> None:
    await RendererCache.initialize()


@driver.on_shutdown
async def on_shutdown() -> None:
    try:
        await RendererCache.close()
    except Exception:
        pass


async def render_thread(
    thread: Thread | Thread_p | ThreadDTO | ThreadpDTO,
    posts: Sequence[Post | PostDTO],
) -> bytes:
    """
    渲染主题贴详情图片。

    Args:
        thread: 主题贴对象
        posts: 主题贴下的回复列表

    Returns:
        主题贴详情图片 bytes
    """
    renderer = await RendererCache.get_renderer()
    return await renderer.render_thread_detail(thread, posts)


async def text_to_image(
    text: str,
    *,
    wrap: bool = True,
    wrap_width: int = 48,
    header: str = "",
    footer: str = "",
    simple_mode: bool = True,
) -> bytes:
    """
    将文本转换为图片。

    Args:
        text: 需要转换的文本内容
        wrap: 是否进行自动换行
        header: 图片顶部的标题文本
        footer: 图片底部的附加文本
        simple_mode: 是否使用简洁模式渲染图片

    Returns:
        图片的 bytes 内容
    """
    renderer = await RendererCache.get_renderer()

    final_str = text
    if wrap:
        wrapped_text = ""
        for line in text.split("\n"):
            wrapped_line = textwrap.fill(line, width=wrap_width)
            wrapped_text += wrapped_line + "\n"

        lines = wrapped_text.split("\n")[:-1]
        if not lines:
            return b""

        def add_indent(line):
            return "  " + line if (not line.startswith("  - ") and not line.endswith("吧：")) else line

        lines = list(map(add_indent, lines))
        final_str = "\n".join(lines)

    return await renderer.text_to_image(final_str, header=header, footer=footer, simple_mode=simple_mode)
