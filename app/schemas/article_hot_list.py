"""热搜榜单（文章板块）DTO。

分三类：

- `HotListItemOut`：条目出参，后台列表 / 详情与前台榜单共用；
- `HotListBoardOut` / `HotListSourceOut`：前台「按渠道出榜」与「可用渠道」；
- `HotListItemUpdate`：后台编辑入参（只允许改内容字段，且支持逐字段更新）。
"""

from datetime import datetime
from typing import Annotated, Any, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.common import ORMBaseModel

#: 渠道名：必填、非空白
SourceText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]
#: 条目标题：必填、非空白
NameText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
#: 热度 / 排名：原始文本，允许为空（清空时传 null 或空串）
HeatText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]
RankText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
#: 单个徽标文字
TagText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]

#: 一个条目最多多少个徽标
MAX_TAGS = 20

_TAG_SEPARATORS = (",", "，", ";", "；", "、", "|")


def split_tags(value: Any) -> Any:
    """标签归一化：数组原样返回；字符串按中英文逗号 / 分号 / 顿号拆开。

    爬虫写的是数组，手工调接口时写 `"热,新"` 更顺手，两种都认。
    """
    if not isinstance(value, str):
        return value
    text = value
    for separator in _TAG_SEPARATORS:
        text = text.replace(separator, ",")
    return [piece.strip() for piece in text.split(",") if piece.strip()]


def normalize_tags(value: Any) -> List[str]:
    """统一成「去重、去空、截断到 MAX_TAGS」的字符串数组。"""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    tags: List[str] = []
    for item in items:
        tag = str(item).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


class HotListItemOut(ORMBaseModel):
    """热搜榜单条目出参（全部字段，后台表格直接铺）。"""

    id: int
    source: str
    name: str
    heat: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    rank: Optional[str] = None
    is_active: bool = Field(default=True, description="是否启用；False 表示已不在最新榜单中")
    created_at: datetime
    updated_at: datetime

    @field_validator("heat", "rank", mode="before")
    @classmethod
    def coerce_text(cls, value: Any) -> Any:
        """外部写入的可能是数字，统一按文本输出。"""
        return None if value is None else str(value)

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_tags(cls, value: Any) -> List[str]:
        """老数据可能是 NULL 或分号串，兜底成数组，避免整页 500。"""
        return normalize_tags(split_tags(value))


class HotListBoardOut(BaseModel):
    """一个渠道的榜单：`count` 是该渠道**启用中**的条数，`items` 受 `limit` 限制。"""

    source: str = Field(..., description="渠道")
    count: int = Field(..., ge=0, description="该渠道启用中的条目数")
    items: List[HotListItemOut] = Field(
        default_factory=list, description="热搜榜单条目（按入库顺序，即抓取到的排序）"
    )


class HotListSourceOut(BaseModel):
    """可用渠道 + 该渠道启用中的条目数（前台画渠道页签用）。"""

    source: str = Field(..., description="渠道")
    count: int = Field(..., ge=0, description="该渠道启用中的条目数")


class HotListItemUpdate(BaseModel):
    """后台编辑热搜榜单条目：想改哪个字段就传哪个字段（PUT 但是按字段合并）。"""

    model_config = ConfigDict(extra="forbid")

    source: Optional[SourceText] = None
    name: Optional[NameText] = None
    heat: Optional[HeatText] = None
    tags: Optional[List[TagText]] = Field(default=None, max_length=MAX_TAGS)
    rank: Optional[RankText] = None
    is_active: Optional[bool] = Field(
        default=None, description="是否启用：false 表示该条已不在最新榜单中"
    )

    @field_validator("heat", "rank", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        """空串 / 全空白当作「清空该字段」，落库为 NULL。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tab_list(cls, value: Any) -> Any:
        if value is None:
            return None
        tags = normalize_tags(split_tags(value))
        if len(tags) > MAX_TAGS:
            raise ValueError(f"标签最多 {MAX_TAGS} 个")
        if any(len(tag) > 20 for tag in tags):
            raise ValueError("单个标签最多 20 字")
        return tags

    @model_validator(mode="after")
    def reject_null_required(self) -> "HotListItemUpdate":
        """`source` / `name` 是必填列：显式传 null 直接拒绝（不传表示不改）。"""
        for field, label in (("source", "渠道"), ("name", "标题")):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{label}不能为空")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("启用状态不能为空")
        return self
