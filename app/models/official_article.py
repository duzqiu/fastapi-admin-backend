"""Official article domain: admin-managed external articles."""

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.member_media import resolve_avatar_url
from app.core.utils import generate_post_no, utcnow
from app.db.base import Base
from app.models.member import Member
from app.models.mixins import PKMixin, TimestampMixin

#: 官号文章在「帖子」接口里的 id 偏移：id = OFFSET + article.id
ARTICLE_ID_OFFSET = 1_000_000_000


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetimes, stored as UTC-naive on SQLite."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=dialect.name != "sqlite"))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class OfficialArticleStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class OfficialArticle(PKMixin, TimestampMixin, Base):
    __tablename__ = "article_official_info"
    __table_args__ = (Index("ix_article_official_info_status_published", "status", "published_at"),)

    article_no: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False, default=generate_post_no)
    member_id: Mapped[Optional[int]] = mapped_column(ForeignKey("member_account_info.id", ondelete="SET NULL"), nullable=True, index=True)
    publisher_snapshot: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_urls: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    crawled_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    board: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OfficialArticleStatus.PENDING.value, index=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    member: Mapped[Optional[Member]] = relationship("Member", lazy="joined")

    @property
    def publisher(self) -> str:
        return self.member.display_name if self.member is not None else self.publisher_snapshot

    @property
    def user_id(self) -> str:
        """发布人的「用户 ID」（member_no）——后台列表 / 详情展示用。"""
        return self.member.member_no if self.member is not None else ""

    def __repr__(self) -> str:
        return f"<OfficialArticle id={self.id} article_no={self.article_no!r} status={self.status}>"


class OfficialArticleLike(PKMixin, TimestampMixin, Base):
    """会员 × 官号文章 的点赞关系（一条 = 点过一次）。"""

    __tablename__ = "article_official_like"
    __table_args__ = (
        UniqueConstraint("member_id", "article_id", name="uq_article_official_like"),
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("article_official_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class OfficialArticleFavorite(PKMixin, TimestampMixin, Base):
    """会员 × 官号文章 的收藏关系。"""

    __tablename__ = "article_official_favorite"
    __table_args__ = (
        UniqueConstraint("member_id", "article_id", name="uq_article_official_favorite"),
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("article_official_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class OfficialArticleComment(PKMixin, TimestampMixin, Base):
    """官号文章评论：与帖子评论同构（发出即待审核，后台通过后前台可见）。

    字段刻意和 `PostComment` 对齐（`article_id` 之外还提供 `post_id` /
    `post_title` / `post_no` 属性），这样前台与后台都能直接复用同一套出参
    `PostCommentOut`。
    """

    __tablename__ = "article_official_comment"
    __table_args__ = (
        Index(
            "ix_article_official_comment_article_status",
            "article_id",
            "status",
            "created_at",
        ),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("article_official_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属官号文章",
    )
    member_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="评论人",
    )
    publisher: Mapped[str] = mapped_column(
        String(50), default="", comment="评论人昵称（发评论时的快照）"
    )
    content: Mapped[str] = mapped_column(Text, default="", comment="评论内容")
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
        comment="审核状态：pending / approved / rejected",
    )

    member: Mapped[Optional["Member"]] = relationship(  # noqa: F821
        "Member", lazy="joined"
    )
    article: Mapped["OfficialArticle"] = relationship("OfficialArticle", lazy="joined")

    @property
    def post_id(self) -> int:
        """对外统一成「帖子 id」：带文章偏移，与列表里的一致。"""
        return ARTICLE_ID_OFFSET + int(self.article_id)

    @property
    def post_title(self) -> str:
        return self.article.title if self.article else ""

    @property
    def post_no(self) -> str:
        return self.article.article_no if self.article else ""

    @property
    def publisher_avatar(self) -> str:
        if self.member is None:
            return ""
        url = resolve_avatar_url(self.member.id, self.member.avatar)
        return "" if url.lower().split("?")[0].endswith(".svg") else url

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<OfficialArticleComment id={self.id} "
            f"article_id={self.article_id} status={self.status}>"
        )
