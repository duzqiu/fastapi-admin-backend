"""文章管理域 ORM 模型：用户发布的帖子（后台审核）。

表名规范：`一级功能_二级功能_功能`
    article_post_info  ->  文章_帖子_信息

状态流转：用户发帖一律进「待审核」，后台审核后变为「已通过」或「已拒绝」。
"""

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import generate_post_no, utcnow
from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class PostStatus(str, enum.Enum):
    """帖子审核状态。"""

    PENDING = "pending"    # 待审核（用户发帖后的默认状态）
    APPROVED = "approved"  # 已通过
    REJECTED = "rejected"  # 已拒绝


class Post(PKMixin, TimestampMixin, Base):
    """用户发布的帖子。"""

    __tablename__ = "article_post_info"
    __table_args__ = (
        Index("ix_article_post_info_status_published", "status", "published_at"),
    )

    # 对外展示的帖子 ID：12 位随机数字，与自增主键分开（主键不对外暴露）
    post_no: Mapped[str] = mapped_column(
        String(12),
        unique=True,
        index=True,
        default=generate_post_no,
        comment="帖子编号（12 位随机数字）",
    )
    publisher: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="发布人"
    )
    member_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="发布会员（匿名发帖为空）",
    )
    title: Mapped[str] = mapped_column(String(200), index=True, nullable=False, comment="标题")
    content: Mapped[str] = mapped_column(Text, default="", comment="正文")
    images: Mapped[List[str]] = mapped_column(JSON, default=list, comment="图片地址列表")
    published_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, index=True, comment="发布时间"
    )
    status: Mapped[str] = mapped_column(
        String(20), default=PostStatus.PENDING.value, index=True, comment="审核状态"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Post id={self.id} title={self.title!r} status={self.status}>"
