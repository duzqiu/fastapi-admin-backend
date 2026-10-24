"""文章管理域 ORM 模型：帖子（后台审核）、收藏、点赞与评论。

表名规范：`一级功能_二级功能_功能`
    article_post_info      ->  文章_帖子_信息
    article_post_favorite  ->  文章_帖子_收藏
    article_post_like      ->  文章_帖子_点赞
    article_post_comment   ->  文章_帖子_评论

状态流转：用户发帖 / 发评论一律进「待审核」，后台审核后变为「已通过」或「已拒绝」。
收藏 / 点赞都是「会员 × 帖子」的多对多关系，同一会员同一帖子只会有一条记录。
"""

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.member_media import resolve_avatar_url
from app.core.utils import generate_post_no, utcnow
from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class PostStatus(str, enum.Enum):
    """帖子审核状态。"""

    PENDING = "pending"    # 待审核（用户发帖后的默认状态）
    APPROVED = "approved"  # 已通过
    REJECTED = "rejected"  # 已拒绝


class CommentStatus(str, enum.Enum):
    """评论审核状态。"""

    PENDING = "pending"    # 待审核（发评论后的默认状态）
    APPROVED = "approved"  # 已通过（前台才展示）
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
    view_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        index=True,
        comment="访问量：详情页被打开的次数（「热门」按它倒序）",
    )

    # 发布会员（匿名发帖为空）：列表 / 详情要显示发布者头像，用 joined 一次查回来，
    # 不让每条帖子再多跑一次查询
    member: Mapped[Optional["Member"]] = relationship(  # noqa: F821
        "Member", lazy="joined"
    )

    @property
    def publisher_avatar(self) -> str:
        """发布者头像地址（和 `GET /member/profile` 的 `avatar_url` 同一套解析）。

        匿名发帖、或会员还没上传过头像时返回空串：默认头像是 SVG，客户端
        （Flutter 的 Image）渲染不了，交给前端用昵称首字兜底。
        """
        if self.member is None:
            return ""
        url = resolve_avatar_url(self.member.id, self.member.avatar)
        return "" if url.lower().split("?")[0].endswith(".svg") else url

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Post id={self.id} title={self.title!r} status={self.status}>"


class PostFavorite(PKMixin, TimestampMixin, Base):
    """会员收藏的帖子。

    `is_favorited` 是**按查看者**变化的字段，不落库：列表 / 详情出参时由服务层
    按当前登录会员临时标上（见 `PostService._mark_interactions`），所以这里只管关系表。
    """

    __tablename__ = "article_post_favorite"
    __table_args__ = (
        UniqueConstraint(
            "member_id",
            "post_id",
            name="uq_article_post_favorite_member_post",
        ),
        Index("ix_article_post_favorite_member_created", "member_id", "created_at"),
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="收藏人（会员）",
    )
    post_id: Mapped[int] = mapped_column(
        ForeignKey("article_post_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="被收藏的帖子",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<PostFavorite member_id={self.member_id} post_id={self.post_id}>"


class PostLike(PKMixin, TimestampMixin, Base):
    """会员给帖子点的赞。

    和收藏一样是「会员 × 帖子」的关系表：同一会员同一帖子只有一条记录，
    重复点赞幂等。帖子上的 `like_count` / `is_liked` 都是出参时临时算的，不落库。
    """

    __tablename__ = "article_post_like"
    __table_args__ = (
        UniqueConstraint(
            "member_id",
            "post_id",
            name="uq_article_post_like_member_post",
        ),
        Index("ix_article_post_like_post_created", "post_id", "created_at"),
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="点赞人（会员）",
    )
    post_id: Mapped[int] = mapped_column(
        ForeignKey("article_post_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="被点赞的帖子",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<PostLike member_id={self.member_id} post_id={self.post_id}>"


class PostComment(PKMixin, TimestampMixin, Base):
    """帖子评论：一条 = 某会员在某条帖子下的一条评论。

    和帖子一样有审核状态：用户发出后是「待审核」，后台审核为「已通过」后
    前台（App 详情页）才展示；「已拒绝」只在后台可见。
    """

    __tablename__ = "article_post_comment"
    __table_args__ = (
        Index(
            "ix_article_post_comment_post_status",
            "post_id",
            "status",
            "created_at",
        ),
    )

    post_id: Mapped[int] = mapped_column(
        ForeignKey("article_post_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属帖子",
    )
    member_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="评论人（未登录时代为空）",
    )
    publisher: Mapped[str] = mapped_column(
        String(50), default="", comment="评论人昵称（发评论时的快照）"
    )
    content: Mapped[str] = mapped_column(Text, default="", comment="评论内容")
    status: Mapped[str] = mapped_column(
        String(20),
        default=CommentStatus.PENDING.value,
        index=True,
        comment="审核状态：pending / approved / rejected",
    )

    # 评论人（一条评论最多关联一个会员）：列表要显示头像，用 joined 一次查回来
    member: Mapped[Optional["Member"]] = relationship(  # noqa: F821
        "Member", lazy="joined"
    )

    # 所属帖子：后台评论列表要显示帖子标题
    post: Mapped["Post"] = relationship("Post", lazy="joined")

    @property
    def post_title(self) -> str:
        """所属帖子标题（后台列表展示用）。"""
        return self.post.title if self.post else ""

    @property
    def post_no(self) -> str:
        """所属帖子编号（后台定位用）。"""
        return self.post.post_no if self.post else ""

    @property
    def publisher_avatar(self) -> str:
        """评论人头像地址（未登录 / 没上传头像时为空串，前端退回首字头像）。"""
        if self.member is None:
            return ""
        url = resolve_avatar_url(self.member.id, self.member.avatar)
        return "" if url.lower().split("?")[0].endswith(".svg") else url

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<PostComment id={self.id} post_id={self.post_id} status={self.status}>"
