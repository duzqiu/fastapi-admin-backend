"""文章管理（帖子）相关 Pydantic 模型。"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field, field_validator

from app.models.post import CommentStatus, PostStatus
from app.schemas.common import ORMBaseModel


class PostCreate(BaseModel):
    """用户发帖入参。

    `publisher` 留空时取登录会员的昵称（未登录则记为「匿名用户」），
    所以客户端可以不传。发表后统一进「待审核」。
    """

    publisher: str = Field(default="", max_length=50, description="发布人")
    title: str = Field(..., min_length=1, max_length=200, description="标题")
    content: str = Field(default="", max_length=20000, description="正文")
    images: List[str] = Field(
        default_factory=list, max_length=9, description="图片地址列表（最多 9 张）"
    )
    published_at: Optional[datetime] = Field(default=None, description="发布时间，缺省为当前时间")

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        """先去掉首尾空白再校验长度，避免「全是空格」的标题混过去。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("publisher", "content")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class PostUpdate(BaseModel):
    """被拒绝后修改并重新提交的入参。

    只允许改内容；`status` 由服务端重置为「待审核」，客户端改不了，
    否则等于绕过审核。
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, max_length=20000)
    images: Optional[List[str]] = Field(default=None, max_length=9)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("content")
    @classmethod
    def strip_content(cls, value):
        return value.strip() if isinstance(value, str) else value


class PostStatusUpdate(BaseModel):
    """审核入参。"""

    status: PostStatus = Field(..., description="审核结果：approved（已通过）/ rejected（已拒绝）")


class PostOut(ORMBaseModel):
    """帖子出参。"""

    id: int
    post_no: str = Field(default="", description="帖子编号（12 位随机数字，对外展示的帖子 ID）")
    kind: str = Field(
        default="post", description="内容类型：post=用户动态，article=官号文章"
    )
    article_id: Optional[int] = Field(
        default=None, description="官号文章 ID（kind=article 时有值）"
    )
    article_url: str = Field(
        default="", description="官号文章原文链接（kind=article 时有值）"
    )
    article_source: str = Field(
        default="", description="官号文章来源（kind=article 时有值）"
    )
    publisher: str
    publisher_avatar: str = Field(
        default="", description="发布者头像地址（匿名发帖或未设置头像时为空）"
    )
    member_id: Optional[int] = None
    is_following: bool = Field(
        default=False,
        description="当前登录会员是否已关注作者（未登录 / 匿名帖恒为 false）",
    )
    title: str
    content: str
    images: List[str] = Field(default_factory=list)
    published_at: datetime
    status: str
    view_count: int = Field(default=0, description="访问量：详情页被打开的次数")
    is_liked: bool = Field(
        default=False,
        description="当前登录会员是否已点赞（未登录恒为 false）",
    )
    like_count: int = Field(default=0, description="被点赞次数（全体会员）")
    comment_count: int = Field(default=0, description="已通过审核的评论数")
    is_favorited: bool = Field(
        default=False,
        description="当前登录会员是否已收藏（未登录恒为 false）",
    )
    favorite_count: int = Field(default=0, description="被收藏次数（全体会员）")
    created_at: datetime
    updated_at: datetime

    @field_validator("images", mode="before")
    @classmethod
    def ensure_images(cls, value):
        """空值统一成空列表，避免出参校验失败。"""
        return value or []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_text(self) -> str:
        """审核状态的中文文案，前端可直接展示。"""
        labels = {
            PostStatus.PENDING.value: "待审核",
            PostStatus.APPROVED.value: "已通过",
            PostStatus.REJECTED.value: "已拒绝",
        }
        return labels.get(self.status, self.status)


class PostReceivedLikesOut(BaseModel):
    """当前会员的获赞汇总：自己所有帖子被点赞的次数合计。"""

    received_like_count: int = Field(
        default=0, description="获赞总数（所有帖子合计，含待审核 / 已拒绝）"
    )


# ------------------------- 评论 -------------------------
class PostReceivedCommentsOut(BaseModel):
    """当前会员的被评论汇总：自己所有帖子收到的（已通过）评论数。"""

    received_comment_count: int = Field(
        default=0, description="被评论总数（只算已通过审核的评论）"
    )


class PostCommentCreate(BaseModel):
    """发表评论入参。"""

    content: str = Field(..., min_length=1, max_length=500, description="评论内容")

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        """去掉首尾空白再校验，避免「全是空格」的评论混过去。"""
        return value.strip()


class PostCommentStatusUpdate(BaseModel):
    """评论审核入参。"""

    status: CommentStatus = Field(
        ..., description="审核结果：approved（已通过）/ rejected（已拒绝）"
    )

    @field_validator("status")
    @classmethod
    def check_status(cls, value: CommentStatus) -> CommentStatus:
        if value not in (CommentStatus.APPROVED, CommentStatus.REJECTED):
            raise ValueError("审核结果只能是 approved 或 rejected")
        return value


class PostCommentOut(ORMBaseModel):
    """评论出参（前台展示与后台管理共用）。"""

    id: int
    post_id: int
    post_title: str = Field(default="", description="所属帖子标题")
    post_no: str = Field(default="", description="所属帖子编号")
    member_id: Optional[int] = None
    publisher: str = ""
    publisher_avatar: str = Field(
        default="", description="评论人头像地址（未上传时为空串）"
    )
    content: str
    status: str
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_text(self) -> str:
        """审核状态的中文文案。"""
        labels = {
            CommentStatus.PENDING.value: "待审核",
            CommentStatus.APPROVED.value: "已通过",
            CommentStatus.REJECTED.value: "已拒绝",
        }
        return labels.get(self.status, self.status)
