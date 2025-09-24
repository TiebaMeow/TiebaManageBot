from __future__ import annotations

import textwrap
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import TYPE_CHECKING

from nonebot import get_driver
from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from aiotieba.api.get_comments._classdef import Comment, Post_c
    from aiotieba.api.get_posts._classdef import Post, Thread_p


driver = get_driver()


class ChromiumCache:
    # 将浏览器实例放入类属性中
    _p = None
    browser = None
    context = None

    @classmethod
    async def initialize(cls):
        if cls._p is None:
            cls._p = await async_playwright().start()
            cls.browser = await cls._p.chromium.launch(
                headless=True,
                args=[
                    "--allow-file-access-from-files"  # 允许加载本地文件
                ],
            )
            cls.context = await cls.browser.new_context()

    @classmethod
    async def close(cls):
        # 清理资源
        if cls.context:
            try:
                # 先关闭所有页面
                for page in cls.context.pages:
                    try:
                        await page.close()
                    except Exception:
                        pass
                await cls.context.close()
            except Exception:
                pass
            finally:
                cls.context = None
        if cls.browser:
            try:
                await cls.browser.close()
            except Exception:
                pass
            finally:
                cls.browser = None
        if cls._p:
            try:
                await cls._p.stop()
            except Exception:
                pass
            finally:
                cls._p = None


@driver.on_startup
async def init_chromium():
    try:
        await ChromiumCache.initialize()
        assert ChromiumCache.browser is not None
    except Exception:
        pass


@driver.on_shutdown
async def close_chromium():
    try:
        await ChromiumCache.close()
    except Exception:
        pass


async def text_to_image(text: str, font_size: int = 20) -> bytes:
    if ChromiumCache.context is None:
        await ChromiumCache.initialize()
    context = ChromiumCache.context
    assert context is not None

    wrapped_text = ""
    for line in text.split("\n"):
        wrapped_line = textwrap.fill(line, width=48)
        wrapped_text += wrapped_line + "\n"

    lines = wrapped_text.split("\n")[:-1]

    if not lines:
        return b""

    def add_indent(line):
        return "  " + line if (not line.startswith("  - ") and not line.endswith("吧：")) else line

    lines = list(map(add_indent, lines))
    line_str = "\n".join(lines)

    # 构建字体文件的绝对路径
    font_path = Path(__file__).parent.parent.parent / "static" / "font" / "NotoSansSC-Regular.ttf"
    font_url = font_path.as_uri()

    html_content = f"""
    <html>
        <head>
            <style>
                @font-face {{
                    font-family: "NotoSansSC";
                    src: url("{font_url}") format("truetype");
                    font-display: block;
                    unicode-range: U+4E00-9FFF, U+3400-4DBF, U+20000-2A6DF, U+2A700-2B73F, U+2B740-2B81F, U+2B820-2CEAF, U+F900-FAFF, U+2F800-2FA1F;
                }}
                body {{
                    font-family: "NotoSansSC", "Noto Sans CJK SC";
                    font-size: {font_size}px;
                    line-height: {font_size + 2}px;
                    margin: 0;
                    padding: 0;
                    font-variant-east-asian: normal;
                    font-feature-settings: "locl" 1;
                    text-rendering: optimizeLegibility;
                    -webkit-font-feature-settings: "locl" 1;
                    -moz-font-feature-settings: "locl" 1;
                    lang: zh-CN;
                }}
                pre {{
                    margin-left: 10px;
                    margin-top: 10px;
                    display: inline-block;
                    white-space: pre;
                    font-family: inherit;
                }}
            </style>
        </head>
        <body>
            <pre>{line_str}</pre>
        </body>
    </html>
    """  # noqa: E501

    page = await context.new_page()
    await page.set_content(html_content)

    pre_width = await page.evaluate("""() => {
        const pre = document.querySelector('pre');
        return pre.offsetWidth + 20; // 包含边距
    }""")
    pre_height = await page.evaluate("""() => {
        const pre = document.querySelector('pre');
        return pre.offsetHeight + 20;
    }""")

    await page.set_viewport_size({"width": pre_width, "height": pre_height})
    screenshot = await page.screenshot(type="jpeg", quality=75, path=None)
    await page.close()

    return screenshot


def _format_time(t: int) -> str:
    return datetime.fromtimestamp(int(t)).strftime("%Y-%m-%d %H:%M")


def _first_nonempty(*vals, default=None):
    for v in vals:
        if v:
            return v
    return default


def _extract_images(obj: Post_c | Thread_p | Post) -> list[str]:
    imgs: list[str] = []
    medias = obj.contents.imgs
    for m in medias:
        src = _first_nonempty(
            m.src,
            m.big_src,
            m.origin_src,
            default=None,
        )
        if src:
            imgs.append(src)
    return imgs


async def _screenshot_html(html_content: str, width: int = 720, jpeg_quality: int = 80) -> bytes:
    if ChromiumCache.context is None:
        await ChromiumCache.initialize()
    context = ChromiumCache.context
    assert context is not None
    page = await context.new_page()
    try:
        await page.set_viewport_size({"width": width, "height": 100})
        await page.set_content(html_content, wait_until="networkidle")
        # 等字体可用
        try:
            await page.evaluate("document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()")
        except Exception:
            pass
        img = await page.screenshot(full_page=True, type="jpeg", quality=jpeg_quality)
        return img
    finally:
        try:
            await page.close()
        except Exception:
            pass


def _base_styles(font_size: int) -> str:
    font_path = Path(__file__).parent.parent.parent / "static" / "font" / "NotoSansSC-Regular.ttf"
    font_url = font_path.as_uri()
    return f"""
        <style>
            @font-face {{
                font-family: 'NotoSansSC';
                src: url('{font_url}') format('truetype');
                font-display: swap;
            }}
            :root {{
                --bg: #ffffff;
                --card: #ffffff;
                --text: #111;
                --subtext: #5f6368;
                --divider: #eee;
                --accent: #0b57d0;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                padding: 16px;
                background: var(--bg);
                font-family: "NotoSansSC", "Noto Sans CJK SC";
                color: var(--text);
                font-size: {font_size}px;
                line-height: {font_size + 6}px;
                -webkit-font-smoothing: antialiased;
                font-variant-east-asian: normal;
                font-feature-settings: "locl" 1;
                text-rendering: optimizeLegibility;
                -webkit-font-feature-settings: "locl" 1;
                -moz-font-feature-settings: "locl" 1;
                lang: zh-CN;
            }}
            .card {{
                width: 100%;
                max-width: 680px;
                margin: 0 auto;
                background: var(--card);
                border: 1px solid var(--divider);
                border-radius: 14px;
                box-shadow: 0 1px 3px rgba(0,0,0,.05);
                overflow: hidden;
            }}
            .header {{ display:flex; gap:12px; padding: 14px 16px 4px 16px; align-items:center; }}
            .avatar {{ width:40px; height:40px; border-radius:50%; background:#ddd; flex: 0 0 auto; }}
            .meta {{ display:flex; flex-direction:column; gap:2px; min-width:0; }}
            .nick {{
                font-weight:600;
                font-size:{font_size + 2}px;
                white-space:nowrap;
                overflow:hidden;
                text-overflow:ellipsis;
            }}
            .sub {{ color: var(--subtext); font-size:{max(font_size - 2, 12)}px; }}
            .right {{
                margin-left:auto;
                color: var(--subtext);
                font-size:{max(font_size - 2, 12)}px;
            }}
            .title {{
                padding: 4px 16px 0 16px;
                font-size:{font_size + 4}px;
                font-weight:700;
                line-height:{font_size + 10}px;
            }}
            .content {{ padding: 8px 16px; white-space:pre-wrap; word-break:break-word; }}
            .gallery {{ display:grid; gap:6px; padding: 0 16px 8px 16px; grid-template-columns: repeat(3, 1fr); }}
            .img {{
                width:100%;
                aspect-ratio:1/1;
                object-fit:cover;
                border-radius:8px;
                border:1px solid var(--divider);
                background:#f3f3f3;
            }}
            .footer {{
                display:flex;
                gap:18px;
                border-top:1px solid var(--divider);
                padding: 8px 16px;
                color:var(--subtext);
                font-size:{max(font_size - 2, 12)}px;
            }}
            .badge {{ display:inline-flex; align-items:center; gap:6px; }}
            .hot-replies {{ border-top: 1px solid var(--divider); padding: 8px 0; }}
            .hot-title {{
                padding: 0 16px 6px 16px;
                color: var(--subtext);
                font-weight:600;
                font-size:{max(font_size - 1, 12)}px;
            }}
            .reply {{ padding: 6px 0; border-top: 1px solid var(--divider); }}
            .comments {{ border-top: 1px solid var(--divider); padding: 8px 0; }}
            .comment {{ display:flex; gap:10px; padding: 6px 16px; }}
            .c-avatar {{ width:26px; height:26px; border-radius:50%; background:#ddd; flex: 0 0 auto; }}
            .c-body {{ display:flex; flex-direction:column; gap:2px; min-width:0; }}
            .c-nick {{
                font-weight:600;
                font-size:{max(font_size - 1, 12)}px;
                white-space:nowrap;
                overflow:hidden;
                text-overflow:ellipsis;
            }}
            .c-text {{ color:#333; white-space:pre-wrap; word-break:break-word; }}
        </style>
        """


async def render_thread_card(thread: Thread_p, posts: list[Post], font_size: int = 16) -> bytes:
    user = thread.user
    avatar = f"http://tb.himg.baidu.com/sys/portrait/item/{user.portrait}.jpg"
    nick = user.nick_name
    level = user.level
    time_str = _format_time(thread.create_time)
    title = thread.title
    text = html_escape("".join(frag.text for frag in thread.contents.texts[1:]))
    images = _extract_images(thread)
    # 统计
    share = thread.share_num
    like = thread.agree
    reply = thread.reply_num

    images_html = "".join([f"<img class='img' src='{html_escape(url)}'/>" for url in images[:9]])
    gallery_html = f"<div class='gallery'>{images_html}</div>" if images_html else ""

    # 热门回复（含楼中楼）
    replies_html_items = ""
    for rp in posts[:3]:
        ru = rp.user
        r_avatar = f"http://tb.himg.baidu.com/sys/portrait/item/{ru.portrait}.jpg"
        r_nick = ru.nick_name
        r_level = ru.level
        r_time = _format_time(rp.create_time)
        r_floor = rp.floor
        r_text = html_escape(rp.contents.text)
        r_images = _extract_images(rp)
        r_images_html = "".join([f"<img class='img' src='{html_escape(url)}'/>" for url in r_images[:9]])
        r_gallery_html = f"<div class='gallery'>{r_images_html}</div>" if r_images_html else ""

        # 楼中楼（取前三条）
        rc_html = ""
        for c in rp.comments[:3]:
            cu = c.user
            c_avatar = f"http://tb.himg.baidu.com/sys/portrait/item/{cu.portrait}.jpg"
            c_nick = cu.nick_name
            c_text = html_escape(c.contents.text)
            rc_html += (
                f"<div class='comment'>"
                f"<img class='c-avatar' src='{html_escape(c_avatar)}'/>"
                f"<div class='c-body'>"
                f"<div class='c-nick'>{html_escape(str(c_nick))}</div>"
                f"<div class='c-text'>{c_text}</div>"
                f"</div>"
                f"</div>"
            )
        r_comments_html = f"<div class='comments'>{rc_html}</div>" if rc_html else ""

        replies_html_items += (
            f"<section class='reply'>"
            f"<div class='header'>"
            f"<img class='avatar' src='{html_escape(r_avatar)}' />"
            f"<div class='meta'>"
            f"<div class='nick'>{html_escape(str(r_nick))}</div>"
            f"<div class='sub'>Lv.{html_escape(str(r_level))} · {html_escape(r_time)}</div>"
            f"</div>"
            f"<div class='right'>{html_escape(str(r_floor))}楼</div>"
            f"</div>"
            f"<div class='content'>{r_text}</div>"
            f"{r_gallery_html}"
            f"{r_comments_html}"
            f"</section>"
        )

    hot_replies_html = (
        f"<section class='hot-replies'><div class='hot-title'>热门回复</div>{replies_html_items}</section>"
        if replies_html_items
        else ""
    )

    html = f"""
        <html>
            <head>
                <meta charset='utf-8' />
                {_base_styles(font_size)}
            </head>
            <body>
                <article class="card">
                    <div class="header">
                        <img class="avatar" src="{html_escape(avatar)}" />
                        <div class="meta">
                            <div class="nick">{html_escape(str(nick))}</div>
                            <div class="sub">Lv.{html_escape(str(level))} · {html_escape(time_str)}</div>
                        </div>
                    </div>
                    {f'<div class="title">{html_escape(title)}</div>' if title else ""}
                    <div class="content">{text}</div>
                    {gallery_html}
                    <div class="footer">
                        <div class="badge">↪️ {html_escape(str(share))}</div>
                        <div class="badge">👍 {html_escape(str(like))}</div>
                        <div class="badge">💬 {html_escape(str(reply))}</div>
                    </div>
                    {hot_replies_html}
                </article>
            </body>
        </html>
        """
    return await _screenshot_html(html)


async def render_post_card(thread: Thread_p, post: Post_c, comments: list[Comment], font_size: int = 16) -> bytes:
    t_title = thread.title
    user = post.user
    avatar = f"http://tb.himg.baidu.com/sys/portrait/item/{user.portrait}.jpg"
    nick = user.nick_name
    level = user.level
    floor = post.floor
    time_str = _format_time(post.create_time)
    text = html_escape(post.contents.text)
    images = _extract_images(post)

    images_html = "".join([f"<img class='img' src='{html_escape(url)}'/>" for url in images[:9]])
    gallery_html = f"<div class='gallery'>{images_html}</div>" if images_html else ""

    # 楼中楼
    c_html = ""
    for c in comments:
        cu = c.user
        c_avatar = f"http://tb.himg.baidu.com/sys/portrait/item/{cu.portrait}.jpg"
        c_nick = cu.nick_name
        c_text = html_escape(c.contents.text)
        c_html += (
            f"<div class='comment'>"
            f"<img class='c-avatar' src='{html_escape(c_avatar)}'/>"
            f"<div class='c-body'>"
            f"<div class='c-nick'>{html_escape(c_nick)}</div>"
            f"<div class='c-text'>{c_text}</div>"
            f"</div>"
            f"</div>"
        )
    comments_html = f"<div class='comments'>{c_html}</div>" if c_html else ""

    html = f"""
        <html>
            <head>
                <meta charset='utf-8' />
                {_base_styles(font_size)}
            </head>
            <body>
                <article class="card">
                    {f'<div class="title" style="padding-top:12px;">{html_escape(t_title)}</div>' if t_title else ""}
                    <div class="header">
                        <img class="avatar" src="{html_escape(avatar)}" />
                        <div class="meta">
                            <div class="nick">{html_escape(nick)}</div>
                            <div class="sub">Lv.{html_escape(str(level))} · {html_escape(time_str)}</div>
                        </div>
                        <div class="right">{html_escape(str(floor))}楼</div>
                    </div>
                    <div class="content">{text}</div>
                    {gallery_html}
                    {comments_html}
                </article>
            </body>
        </html>
        """
    return await _screenshot_html(html)
