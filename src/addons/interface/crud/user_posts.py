from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Literal, NamedTuple

from sqlalchemy import func, literal, select, union_all
from tiebameow.models.orm import Comment, Post, Thread

from src.addons.interface.session import get_addon_session


class UserHistoryItem(NamedTuple):
    type: Literal["thread", "post", "comment"]
    id: int
    fid: int
    title: str
    text: str
    create_time: datetime


class UserStats(NamedTuple):
    fid: int
    thread_count: int
    post_count: int
    comment_count: int


async def get_user_history_mixed(
    user_id: int,
    fids: list[int] | None = None,
    page: int = 1,
    limit: int = 20,
) -> list[UserHistoryItem]:
    """
    获取用户在所有/指定吧的混合历史记录 (主题帖、回复、楼中楼)
    """

    q_thread = select(
        literal("thread").label("type"),
        Thread.tid.label("id"),
        Thread.fid,
        Thread.title.label("title"),
        Thread.text.label("text"),
        Thread.create_time,
    ).where(Thread.author_id == user_id)

    q_post = (
        select(
            literal("post").label("type"),
            Post.pid.label("id"),
            Post.fid,
            Thread.title.label("title"),
            Post.text.label("text"),
            Post.create_time,
        )
        .select_from(Post)
        .join(Thread, Post.tid == Thread.tid)
        .where(Post.author_id == user_id)
    )

    q_comment = (
        select(
            literal("comment").label("type"),
            Comment.cid.label("id"),
            Comment.fid,
            Thread.title.label("title"),
            Comment.text.label("text"),
            Comment.create_time,
        )
        .select_from(Comment)
        .join(Thread, Comment.tid == Thread.tid)
        .where(Comment.author_id == user_id)
    )

    if fids:
        q_thread = q_thread.where(Thread.fid.in_(fids))
        q_post = q_post.where(Post.fid.in_(fids))
        q_comment = q_comment.where(Comment.fid.in_(fids))

    combined_query = union_all(q_thread, q_post, q_comment).subquery()

    stmt = select(combined_query).order_by(combined_query.c.create_time.desc()).offset((page - 1) * limit).limit(limit)

    async with get_addon_session() as session:
        result = await session.execute(stmt)

        return [
            UserHistoryItem(
                type=row.type,
                id=row.id,
                fid=row.fid,
                title=row.title,
                text=row.text or "",
                create_time=row.create_time,
            )
            for row in result.all()
        ]


async def get_user_stats(user_id: int) -> list[UserStats]:
    """
    获取用户在各吧的发言统计 (主题帖、回复、楼中楼数量)
    """
    async with get_addon_session() as session:
        # 1. 统计 Thread
        stmt_thread = select(Thread.fid, func.count(Thread.tid)).where(Thread.author_id == user_id).group_by(Thread.fid)
        # 2. 统计 Post
        stmt_post = select(Post.fid, func.count(Post.pid)).where(Post.author_id == user_id).group_by(Post.fid)
        # 3. 统计 Comment
        stmt_comment = (
            select(Comment.fid, func.count(Comment.cid)).where(Comment.author_id == user_id).group_by(Comment.fid)
        )

        res_thread = (await session.execute(stmt_thread)).all()
        res_post = (await session.execute(stmt_post)).all()
        res_comment = (await session.execute(stmt_comment)).all()

        from collections import defaultdict

        stats = defaultdict(lambda: {"thread": 0, "post": 0, "comment": 0})

        for fid, count in res_thread:
            stats[fid]["thread"] = count
        for fid, count in res_post:
            stats[fid]["post"] = count
        for fid, count in res_comment:
            stats[fid]["comment"] = count

        return [
            UserStats(
                fid=fid,
                thread_count=data["thread"],
                post_count=data["post"],
                comment_count=data["comment"],
            )
            for fid, data in stats.items()
        ]
