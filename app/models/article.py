"""文章 ORM 模型（业务示例）。"""

import enum
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class ArticleStatus(str, enum.Enum):
    """文章状态枚举。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Article(PKMixin, TimestampMixin, Base):
    """文章表。"""

    __tablename__ = "articles"
    __table_args__ = (Index("ix_articles_status_created", "status", "created_at"),)

    title: Mapped[str] = mapped_column(String(200), index=True, nullable=False, comment="标题")
    summary: Mapped[str] = mapped_column(String(500), default="", comment="摘要")
    content: Mapped[str] = mapped_column(Text, default="", comment="正文")
    tags: Mapped[str] = mapped_column(String(200), default="", comment="标签，逗号分隔")
    status: Mapped[str] = mapped_column(
        String(20), default=ArticleStatus.DRAFT.value, index=True, comment="状态"
    )
    views: Mapped[int] = mapped_column(Integer, default=0, comment="浏览量")
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="作者ID"
    )

    author: Mapped[Optional["User"]] = relationship(  # noqa: F821
        "User", back_populates="articles", lazy="joined"
    )

    @property
    def author_name(self) -> str:
        return self.author.nickname or self.author.username if self.author else ""

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Article id={self.id} title={self.title!r}>"
