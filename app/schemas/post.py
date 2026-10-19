"""文章管理（帖子）相关 Pydantic 模型。"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field, field_validator

from app.models.post import PostStatus
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


class PostStatusUpdate(BaseModel):
    """审核入参。"""

    status: PostStatus = Field(..., description="审核结果：approved（已通过）/ rejected（已拒绝）")


class PostOut(ORMBaseModel):
    """帖子出参。"""

    id: int
    post_no: str = Field(default="", description="帖子编号（12 位随机数字，对外展示的帖子 ID）")
    publisher: str
    member_id: Optional[int] = None
    title: str
    content: str
    images: List[str] = Field(default_factory=list)
    published_at: datetime
    status: str
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
