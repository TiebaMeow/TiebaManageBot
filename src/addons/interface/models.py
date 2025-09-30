"""数据模型定义模块。

该模块定义了所有与贴吧数据相关的SQLAlchemy ORM模型和Pydantic验证模型，
包括论坛、用户、主题贴、回复、楼中楼等实体，以及各种内容片段的数据模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import BIGINT, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, foreign, mapped_column, relationship

from .schemas import Fragment

if TYPE_CHECKING:
    import aiotieba.typing as aiotieba

    AiotiebaType = aiotieba.Thread | aiotieba.Post | aiotieba.Comment


__all__ = [
    "ForumModel",
    "UserModel",
    "ThreadModel",
    "PostModel",
    "CommentModel",
    "Fragment",
]


class Base(DeclarativeBase):
    pass


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_with_tz():
    """返回带时区的当前时间。

    Returns:
        datetime: 上海时区的当前时间。
    """
    return datetime.now(SHANGHAI_TZ)


class ForumModel(Base):
    """贴吧信息数据模型。

    Attributes:
        fid: 论坛ID，主键。
        fname: 论坛名称，建立索引用于快速查询。
        threads: 该论坛下的所有帖子，与Thread模型的反向关系。
    """

    __tablename__ = "forum"

    fid: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    fname: Mapped[str] = mapped_column(String(255), index=True)

    threads: Mapped[list[ThreadModel]] = relationship(
        "ThreadModel",
        back_populates="forum",
        primaryjoin=lambda: ForumModel.fid == foreign(ThreadModel.fid),
    )


class UserModel(Base):
    """用户数据模型。

    Attributes:
        user_id: 用户user_id，主键。
        portrait: 用户portrait。
        user_name: 用户名。
        nick_name: 用户昵称。
        threads: 该用户发布的所有帖子，与Thread模型的反向关系。
        posts: 该用户发布的所有回复，与Post模型的反向关系。
        comments: 该用户发布的所有评论，与Comment模型的反向关系。
    """

    __tablename__ = "user"

    user_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    portrait: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    user_name: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    nick_name: Mapped[str] = mapped_column(String(255), nullable=True, index=True)

    threads: Mapped[list[ThreadModel]] = relationship(
        "ThreadModel",
        back_populates="author",
        primaryjoin=lambda: UserModel.user_id == foreign(ThreadModel.author_id),
    )
    posts: Mapped[list[PostModel]] = relationship(
        "PostModel",
        back_populates="author",
        primaryjoin=lambda: UserModel.user_id == foreign(PostModel.author_id),
    )
    comments: Mapped[list[CommentModel]] = relationship(
        "CommentModel",
        back_populates="author",
        primaryjoin=lambda: UserModel.user_id == foreign(CommentModel.author_id),
    )


class ThreadModel(Base):
    """主题贴数据模型。

    Attributes:
        tid: 主题贴tid，与create_time组成复合主键。
        create_time: 主题贴创建时间，带时区信息，与tid组成复合主键。
        title: 主题贴标题内容。
        text: 主题贴的纯文本内容。
        contents: 正文内容碎片列表，以JSONB格式存储。
        last_time: 最后回复时间，以秒为单位的10位时间戳。
        reply_num: 回复数。
        author_level: 作者在主题贴所在吧的等级。
        scrape_time: 数据抓取时间。
        fid: 所属贴吧fid，外键关联到Forum表。
        author_id: 作者user_id，外键关联到User表。
        forum: 所属贴吧对象，与Forum模型的关系。
        author: 作者用户对象，与User模型的关系。
        posts: 该贴子下的所有回复，与Post模型的反向关系。
    """

    __tablename__ = "thread"
    __table_args__ = (
        Index("idx_thread_forum_ctime", "fid", "create_time"),
        Index("idx_thread_forum_ltime", "fid", "last_time"),
        Index("idx_thread_author_time", "author_id", "create_time"),
        Index("idx_thread_author_forum_time", "author_id", "fid", "create_time"),
    )

    tid: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    create_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    contents: Mapped[list[Fragment] | None] = mapped_column(JSONB, nullable=True)
    last_time: Mapped[int] = mapped_column(BIGINT)
    reply_num: Mapped[int] = mapped_column(Integer)
    author_level: Mapped[int] = mapped_column(Integer)
    scrape_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz)

    fid: Mapped[int] = mapped_column(BIGINT, index=True)
    author_id: Mapped[int] = mapped_column(BIGINT, index=True)

    forum: Mapped[ForumModel] = relationship(
        "ForumModel",
        back_populates="threads",
        primaryjoin=lambda: foreign(ThreadModel.fid) == ForumModel.fid,
    )
    author: Mapped[UserModel] = relationship(
        "UserModel",
        back_populates="threads",
        primaryjoin=lambda: foreign(ThreadModel.author_id) == UserModel.user_id,
    )
    posts: Mapped[list[PostModel]] = relationship(
        "PostModel",
        back_populates="thread",
        primaryjoin=lambda: ThreadModel.tid == foreign(PostModel.tid),
    )


class PostModel(Base):
    """回复数据模型。

    Attributes:
        pid: 回复pid，与create_time组成复合主键。
        create_time: 回复创建时间，带时区信息，与pid组成复合主键。
        text: 回复的纯文本内容。
        contents: 回复的正文内容碎片列表，以JSONB格式存储。
        floor: 楼层号。
        reply_num: 该回复下的楼中楼数量。
        author_level: 作者在主题贴所在吧的等级。
        scrape_time: 数据抓取时间。
        tid: 所属贴子tid，外键关联到Thread表。
        author_id: 作者user_id，外键关联到User表。
        thread: 所属主题贴对象，与Thread模型的关系。
        author: 作者用户对象，与User模型的关系。
        comments: 该回复下的所有楼中楼，与Comment模型的反向关系。
    """

    __tablename__ = "post"
    __table_args__ = (
        Index("idx_post_thread_time", "tid", "create_time"),
        Index("idx_post_author_time", "author_id", "create_time"),
    )

    pid: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    create_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    contents: Mapped[list[Fragment] | None] = mapped_column(JSONB, nullable=True)
    floor: Mapped[int] = mapped_column(Integer)
    reply_num: Mapped[int] = mapped_column(Integer)
    author_level: Mapped[int] = mapped_column(Integer)
    scrape_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz)

    tid: Mapped[int] = mapped_column(BIGINT, index=True)
    author_id: Mapped[int] = mapped_column(BIGINT, index=True)

    thread: Mapped[ThreadModel] = relationship(
        "ThreadModel",
        back_populates="posts",
        primaryjoin=lambda: foreign(PostModel.tid) == ThreadModel.tid,
    )
    author: Mapped[UserModel] = relationship(
        "UserModel",
        back_populates="posts",
        primaryjoin=lambda: foreign(PostModel.author_id) == UserModel.user_id,
    )
    comments: Mapped[list[CommentModel]] = relationship(
        "CommentModel",
        back_populates="post",
        primaryjoin=lambda: PostModel.pid == foreign(CommentModel.pid),
    )


class CommentModel(Base):
    """楼中楼数据模型。

    Attributes:
        cid: 楼中楼pid，存储为cid以区分，与create_time组成复合主键。
        create_time: 楼中楼创建时间，带时区信息，与cid组成复合主键。
        text: 楼中楼的纯文本内容。
        contents: 楼中楼的正文内容碎片列表，以JSONB格式存储。
        author_level: 作者在主题贴所在吧的等级。
        reply_to_id: 被回复者的user_id，可为空。
        scrape_time: 数据抓取时间。
        pid: 所属回复ID，外键关联到Post表。
        author_id: 作者user_id，外键关联到User表。
        post: 所属回复对象，与Post模型的关系。
        author: 作者用户对象，与User模型的关系。
    """

    __tablename__ = "comment"
    __table_args__ = (
        Index("idx_comment_post_time", "pid", "create_time"),
        Index("idx_comment_author_time", "author_id", "create_time"),
    )

    cid: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    create_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    contents: Mapped[list[Fragment] | None] = mapped_column(JSONB, nullable=True)
    author_level: Mapped[int] = mapped_column(Integer)
    reply_to_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    scrape_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz)

    pid: Mapped[int] = mapped_column(BIGINT, index=True)
    author_id: Mapped[int] = mapped_column(BIGINT, index=True)

    post: Mapped[PostModel] = relationship(
        "PostModel",
        back_populates="comments",
        primaryjoin=lambda: foreign(CommentModel.pid) == PostModel.pid,
    )
    author: Mapped[UserModel] = relationship(
        "UserModel",
        back_populates="comments",
        primaryjoin=lambda: foreign(CommentModel.author_id) == UserModel.user_id,
    )
