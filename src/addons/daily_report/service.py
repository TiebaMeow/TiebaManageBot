from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path, PosixPath
from typing import TYPE_CHECKING
from urllib.request import urlopen

import jieba_next as jieba
import matplotlib as mpl

# 必须在导入 pyplot 之前设置 backend，防止内存泄漏和 GUI 错误
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.figure import Figure
from sqlalchemy import func, literal, select, union_all
from tiebameow.models.orm import Comment, Post, Thread
from tiebameow.utils.time_utils import SHANGHAI_TZ, now_with_tz
from wordcloud import WordCloud

from logger import log
from src.addons.interface.session import get_addon_session
from src.common.cache import ClientCache, get_autoban_records
from src.db.crud import get_group, update_group

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.db.models import GroupInfo

mpl.use("Agg")

REPORT_SUB_KEY = "daily_report_sub"

BASE_DIR = Path(__file__).parents[3]
FONT_PATH = PosixPath(BASE_DIR / "static" / "font" / "NotoSansSC-Regular.ttf")
STOPWORDS_PATH = BASE_DIR / "data" / "stopwords" / "zh.txt"
STOPWORDS_URL = "https://raw.githubusercontent.com/goto456/stopwords/master/hit_stopwords.txt"
STOPWORDS_URL_FALLBACK = f"https://ghfast.top/{STOPWORDS_URL}"

font_manager.fontManager.addfont(str(FONT_PATH))
_FONT_NAME = font_manager.FontProperties(fname=FONT_PATH).get_name()
plt.rcParams["font.family"] = _FONT_NAME
plt.rcParams["axes.unicode_minus"] = False


@dataclass
class BawuOpsStats:
    labels: list[str]
    delete_counts: list[int]
    ban_counts: list[int]
    ban_excluded: int
    error: str | None = None


async def update_group_args(group_id: int, key: str, value: bool) -> None:
    group_info = await get_group(group_id)
    group_args = group_info.group_args
    group_args.update({key: value})
    await update_group(group_id, group_args=group_args)


_STOPWORDS_CACHE: set[str] | None = None


def _load_stopwords() -> set[str]:
    global _STOPWORDS_CACHE
    if _STOPWORDS_CACHE is not None:
        return _STOPWORDS_CACHE

    if not STOPWORDS_PATH.exists():
        STOPWORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        content = ""
        try:
            with urlopen(STOPWORDS_URL, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            log.warning(f"Failed to download stopwords: {exc}")
            try:
                with urlopen(STOPWORDS_URL_FALLBACK, timeout=10) as resp:
                    content = resp.read().decode("utf-8", errors="ignore")
            except Exception as fallback_exc:
                log.warning(f"Failed to download stopwords via proxy: {fallback_exc}")
                return set()
        if content:
            STOPWORDS_PATH.write_text(content, encoding="utf-8")

    _STOPWORDS_CACHE = {
        line.strip() for line in STOPWORDS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()
    }
    return _STOPWORDS_CACHE


def _fig_to_png(fig: Figure) -> bytes:
    buf = BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150)
    return buf.getvalue()


def _render_empty_image(text: str) -> bytes:
    fig = Figure(figsize=(6, 3))
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=16)
    return _fig_to_png(fig)


def _content_time_query(fid: int, start: datetime, end: datetime):
    q_thread = (
        select(Thread.create_time.label("ctime"))
        .where(Thread.fid == fid, Thread.create_time >= start, Thread.create_time < end)
        .subquery()
    )
    q_post = (
        select(Post.create_time.label("ctime"))
        .where(Post.fid == fid, Post.create_time >= start, Post.create_time < end)
        .subquery()
    )
    q_comment = (
        select(Comment.create_time.label("ctime"))
        .where(Comment.fid == fid, Comment.create_time >= start, Comment.create_time < end)
        .subquery()
    )
    return union_all(select(q_thread.c.ctime), select(q_post.c.ctime), select(q_comment.c.ctime)).subquery()


def _content_level_query(fid: int, start: datetime, end: datetime):
    q_thread = (
        select(
            Thread.author_id.label("author_id"),
            Thread.author_level.label("level"),
        )
        .where(Thread.fid == fid, Thread.create_time >= start, Thread.create_time < end)
        .subquery()
    )
    q_post = (
        select(
            Post.author_id.label("author_id"),
            Post.author_level.label("level"),
        )
        .where(Post.fid == fid, Post.create_time >= start, Post.create_time < end)
        .subquery()
    )
    q_comment = (
        select(
            Comment.author_id.label("author_id"),
            Comment.author_level.label("level"),
        )
        .where(Comment.fid == fid, Comment.create_time >= start, Comment.create_time < end)
        .subquery()
    )
    return union_all(
        select(q_thread.c.author_id, q_thread.c.level),
        select(q_post.c.author_id, q_post.c.level),
        select(q_comment.c.author_id, q_comment.c.level),
    ).subquery()


def _content_text_query(fid: int, start: datetime, end: datetime):
    q_thread = select(
        Thread.create_time.label("ctime"),
        func.concat(func.coalesce(Thread.title, ""), literal(" "), func.coalesce(Thread.text, "")).label("text"),
    ).where(Thread.fid == fid, Thread.create_time >= start, Thread.create_time < end)
    q_post = select(
        Post.create_time.label("ctime"),
        func.coalesce(Post.text, "").label("text"),
    ).where(Post.fid == fid, Post.create_time >= start, Post.create_time < end)
    q_comment = select(
        Comment.create_time.label("ctime"),
        func.coalesce(Comment.text, "").label("text"),
    ).where(Comment.fid == fid, Comment.create_time >= start, Comment.create_time < end)
    return union_all(q_thread, q_post, q_comment).subquery()


async def _get_time_counts(fid: int, start: datetime, end: datetime, unit: str) -> dict[datetime, int]:
    content = _content_time_query(fid, start, end)
    bucket = func.date_trunc(unit, content.c.ctime).label("bucket")
    stmt = select(bucket, func.count().label("count")).group_by(bucket).order_by(bucket)
    async with get_addon_session() as session:
        result = await session.execute(stmt)
    counts: dict[datetime, int] = {}
    for row in result.all():
        if not row.bucket:
            continue
        dt = row.bucket.astimezone(SHANGHAI_TZ)
        counts[dt] = int(row._mapping["count"])
    return counts


async def _get_level_counts(fid: int, start: datetime, end: datetime) -> tuple[dict[int, int], dict[int, int]]:
    content = _content_level_query(fid, start, end)

    stmt_all = (
        select(content.c.level, func.count().label("count"))
        .where(content.c.level.isnot(None))
        .group_by(content.c.level)
    )

    sub_users = (
        select(content.c.author_id, func.max(content.c.level).label("level"))
        .where(content.c.author_id.isnot(None))
        .group_by(content.c.author_id)
        .subquery()
    )
    stmt_users = (
        select(sub_users.c.level, func.count().label("count"))
        .where(sub_users.c.level.isnot(None))
        .group_by(sub_users.c.level)
    )

    async with get_addon_session() as session:
        result_all = await session.execute(stmt_all)
        result_users = await session.execute(stmt_users)

    total_counts = {int(level): int(count) for level, count in result_all.all() if level is not None}
    user_counts = {int(level): int(count) for level, count in result_users.all() if level is not None}
    return total_counts, user_counts


def _normalize_levels(*level_maps: dict[int, int]) -> list[int]:
    levels = set()
    for level_map in level_maps:
        levels.update(level_map.keys())
    if not levels:
        return []
    return sorted(levels)


def _plot_hourly_counts(labels: list[str], last_counts: list[int], prev_counts: list[int]) -> bytes:
    fig = Figure(figsize=(10, 4))
    ax = fig.add_subplot(111)
    ax.plot(labels, last_counts, marker="o", linewidth=2, label="最近24小时")
    ax.plot(labels, prev_counts, marker="o", linewidth=2, label="上一轮24小时")
    ax.set_title("24小时发贴量（对比）")
    ax.set_xlabel("小时")
    ax.set_ylabel("发贴量")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    return _fig_to_png(fig)


def _plot_daily_counts(labels: list[str], counts: list[int]) -> bytes:
    fig = Figure(figsize=(10, 4))
    ax = fig.add_subplot(111)
    ax.plot(labels, counts, marker="o", linewidth=2, color="#4e79a7")
    ax.set_title("近30天每日发贴量")
    ax.set_xlabel("日期")
    ax.set_ylabel("发贴量")
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    return _fig_to_png(fig)


def _plot_level_distribution(
    levels: list[int],
    total_counts: list[int],
    user_counts: list[int],
    title: str,
) -> bytes:
    fig = Figure(figsize=(10, 4))
    axes = fig.subplots(1, 2)
    axes[0].bar(levels, total_counts, color="#59a14f")
    axes[0].set_title(f"{title}（贴子）")
    axes[0].set_xlabel("等级")
    axes[0].set_ylabel("数量")
    axes[0].grid(True, axis="y", alpha=0.3)

    axes[1].bar(levels, user_counts, color="#edc949")
    axes[1].set_title(f"{title}（用户去重）")
    axes[1].set_xlabel("等级")
    axes[1].set_ylabel("用户数")
    axes[1].grid(True, axis="y", alpha=0.3)

    return _fig_to_png(fig)


def _plot_bawu_ops(stats: BawuOpsStats) -> bytes:
    fig = Figure(figsize=(10, 4))
    ax = fig.add_subplot(111)
    ax.plot(stats.labels, stats.delete_counts, marker="o", linewidth=2, label="删贴")
    ax.plot(stats.labels, stats.ban_counts, marker="o", linewidth=2, label="封禁")
    ax.set_title("近7天吧务操作量")
    ax.set_xlabel("日期")
    ax.set_ylabel("操作量")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    return _fig_to_png(fig)


def _tokenize_texts(texts: Iterable[str]) -> list[str]:
    stopwords = _load_stopwords()
    combined = "\n".join(texts)
    if len(combined) > 200000:
        combined = combined[:200000]

    tokens = []
    for token in jieba.lcut(combined, cut_all=False):
        token = token.strip()
        if not token or token in stopwords:
            continue
        if len(token) <= 1:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _render_wordcloud(tokens: list[str]) -> bytes:
    if not tokens:
        return _render_empty_image("无有效文本")
    wc = WordCloud(
        font_path=str(FONT_PATH),
        background_color="white",
        width=1200,
        height=800,
        max_words=200,
        collocations=False,
    )
    wc.generate(" ".join(tokens))
    image = wc.to_image()
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


async def _get_bawu_ops_stats(group_id: int, fid: int, now: datetime) -> BawuOpsStats:
    labels = [(now - timedelta(days=7 - i)).strftime("%m-%d") for i in range(7)]
    delete_counts = [0] * 7
    ban_counts = [0] * 7
    ban_excluded = 0

    group_info = await get_group(group_id)
    if not group_info.slave_bduss:
        return BawuOpsStats(labels, delete_counts, ban_counts, ban_excluded, error="未配置吧务BDUSS")

    client = await ClientCache.get_stoken_client(group_id)
    since = now - timedelta(days=7)

    try:
        for i in range(7):
            day_start = (now - timedelta(days=7 - i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            user_logs = await client.get_bawu_userlogs(fid, pn=1, start_dt=day_start, end_dt=day_end, op_type=213)
            if user_logs.err:
                return BawuOpsStats(labels, delete_counts, ban_counts, ban_excluded, error="吧务日志拉取失败")
            ban_counts[i] = int(getattr(user_logs.page, "total_count", 0))

            post_logs = await client.get_bawu_postlogs(fid, pn=1, start_dt=day_start, end_dt=day_end, op_type=12)
            if post_logs.err:
                return BawuOpsStats(labels, delete_counts, ban_counts, ban_excluded, error="吧务日志拉取失败")
            delete_counts[i] = int(getattr(post_logs.page, "total_count", 0))
    except BaseException as exc:
        log.error(f"Failed to get bawu logs: {exc}")
        return BawuOpsStats(labels, delete_counts, ban_counts, ban_excluded, error="吧务日志拉取失败")

    autoban_records = await get_autoban_records(fid)
    exclude_by_day = [0] * 7
    for record in autoban_records:
        raw_time = record.get("time")
        try:
            record_time = datetime.fromisoformat(raw_time) if isinstance(raw_time, str) else None
        except Exception:
            record_time = None
        if not record_time or record_time < since:
            continue
        index = (now.date() - record_time.astimezone(SHANGHAI_TZ).date()).days
        if 1 <= index <= 7:
            exclude_by_day[7 - index] += int(record.get("count", 0))

    ban_excluded = sum(exclude_by_day)
    if ban_excluded:
        ban_counts = [max(0, ban_counts[i] - exclude_by_day[i]) for i in range(7)]

    return BawuOpsStats(labels, delete_counts, ban_counts, ban_excluded)


async def build_daily_report(group_info: GroupInfo) -> tuple[str, list[bytes]]:
    now = now_with_tz()

    end_hour = now.replace(minute=0, second=0, microsecond=0)
    start_48h = end_hour - timedelta(hours=48)
    counts_48h = await _get_time_counts(group_info.fid, start_48h, end_hour + timedelta(hours=1), "hour")

    hours_last = [end_hour - timedelta(hours=23 - i) for i in range(24)]
    hours_prev = [hour - timedelta(hours=24) for hour in hours_last]
    labels_hour = [hour.strftime("%m-%d %H") for hour in hours_last]
    last_counts = [counts_48h.get(hour, 0) for hour in hours_last]
    prev_counts = [counts_48h.get(hour, 0) for hour in hours_prev]

    end_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_30d = end_day - timedelta(days=29)
    counts_30d = await _get_time_counts(group_info.fid, start_30d, end_day + timedelta(days=1), "day")
    days_30 = [start_30d + timedelta(days=i) for i in range(30)]
    labels_day = [day.strftime("%m-%d") for day in days_30]
    daily_counts = [counts_30d.get(day, 0) for day in days_30]

    start_24h = now - timedelta(hours=24)
    levels_24h, users_24h = await _get_level_counts(group_info.fid, start_24h, now)
    start_7d = now - timedelta(days=7)
    levels_7d, users_7d = await _get_level_counts(group_info.fid, start_7d, now)

    levels_24 = _normalize_levels(levels_24h, users_24h)
    total_24 = [levels_24h.get(level, 0) for level in levels_24]
    users_24 = [users_24h.get(level, 0) for level in levels_24]

    levels_7 = _normalize_levels(levels_7d, users_7d)
    total_7 = [levels_7d.get(level, 0) for level in levels_7]
    users_7 = [users_7d.get(level, 0) for level in levels_7]

    images: list[bytes] = []
    images.extend((
        _plot_hourly_counts(labels_hour, last_counts, prev_counts),
        _plot_daily_counts(labels_day, daily_counts),
    ))

    if levels_24:
        images.append(_plot_level_distribution(levels_24, total_24, users_24, "近24小时等级分布"))
    else:
        images.append(_render_empty_image("近24小时无等级数据"))

    if levels_7:
        images.append(_plot_level_distribution(levels_7, total_7, users_7, "近7天等级分布"))
    else:
        images.append(_render_empty_image("近7天无等级数据"))

    bawu_stats = await _get_bawu_ops_stats(group_info.group_id, group_info.fid, now)
    images.append(_plot_bawu_ops(bawu_stats))

    content_query = _content_text_query(group_info.fid, start_24h, now)
    stmt_text = select(content_query.c.text).order_by(content_query.c.ctime.desc()).limit(5000)
    async with get_addon_session() as session:
        texts = [row.text for row in (await session.execute(stmt_text)).all() if row.text]

    tokens = _tokenize_texts(texts)
    images.append(_render_wordcloud(tokens))

    header = f"【本吧日报】{group_info.fname}吧\n统计时间：{now.strftime('%Y-%m-%d')}"
    if bawu_stats.error:
        header += f"\n吧务日志：{bawu_stats.error}"
    elif bawu_stats.ban_excluded:
        header += f"\n已排除循封封禁量：{bawu_stats.ban_excluded}"

    return header, images
