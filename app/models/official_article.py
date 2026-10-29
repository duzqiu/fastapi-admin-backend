"""Official article domain: admin-managed external articles."""

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils import generate_post_no, utcnow
from app.db.base import Base
from app.models.member import Member
from app.models.mixins import PKMixin, TimestampMixin


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

    def __repr__(self) -> str:
        return f"<OfficialArticle id={self.id} article_no={self.article_no!r} status={self.status}>"
