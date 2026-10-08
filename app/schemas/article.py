"""文章相关 Pydantic 模型。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.article import ArticleStatus
from app.schemas.common import ORMBaseModel


class ArticleBase(BaseModel):
    """文章公共字段。"""

    title: str = Field(..., min_length=1, max_length=200, description="标题")
    summary: str = Field(default="", max_length=500, description="摘要")
    content: str = Field(default="", description="正文")
    tags: str = Field(default="", max_length=200, description="标签，逗号分隔")
    status: ArticleStatus = Field(default=ArticleStatus.DRAFT, description="状态")

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: str) -> str:
        items = [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
        return ",".join(dict.fromkeys(items))


class ArticleCreate(ArticleBase):
    """创建文章入参。"""


class ArticleUpdate(BaseModel):
    """更新文章入参（全部可选）。"""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=500)
    content: Optional[str] = None
    tags: Optional[str] = Field(default=None, max_length=200)
    status: Optional[ArticleStatus] = None


class ArticleStatusUpdate(BaseModel):
    """修改文章状态。"""

    status: ArticleStatus


class ArticleOut(ORMBaseModel):
    """文章出参。"""

    id: int
    title: str
    summary: str
    content: str
    tags: str
    status: str
    views: int
    author_id: Optional[int] = None
    author_name: str = ""
    created_at: datetime
    updated_at: datetime


class ArticleListItem(ORMBaseModel):
    """文章列表项（不含正文，减小响应体积）。"""

    id: int
    title: str
    summary: str
    tags: str
    status: str
    views: int
    author_id: Optional[int] = None
    author_name: str = ""
    created_at: datetime
    updated_at: datetime
