"""通用 Pydantic 模型：分页、统一错误体。"""

from math import ceil
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMBaseModel(BaseModel):
    """支持从 ORM 对象直接序列化的基类。"""

    model_config = ConfigDict(from_attributes=True)


class PageResult(BaseModel, Generic[T]):
    """分页响应体。"""

    items: List[T] = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, description="总条数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=10, description="每页条数")
    pages: int = Field(default=0, description="总页数")

    @classmethod
    def create(cls, items: List[T], total: int, page: int, page_size: int) -> "PageResult[T]":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if page_size else 0,
        )


class MessageResponse(BaseModel):
    """简单消息响应。"""

    message: str = "ok"
    detail: Optional[str] = None


class UploadOut(BaseModel):
    """通用上传结果。"""

    url: str = Field(..., description="可直接访问的文件地址")
    filename: str
    size: int = Field(..., description="文件大小（字节）")
