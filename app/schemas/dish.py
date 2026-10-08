"""点菜菜单域 DTO：分类、标签、菜品、套餐规格。"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.dish import DishStatus
from app.schemas.common import ORMBaseModel

# "HH:MM" 格式校验
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


# ==================== 分类 ====================
class DishCategoryCreate(BaseModel):
    """创建分类。"""

    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    sort: int = Field(default=0, ge=0)
    is_active: bool = True


class DishCategoryUpdate(BaseModel):
    """更新分类。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)
    sort: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class DishCategoryOut(ORMBaseModel):
    """分类出参。"""

    id: int
    name: str
    description: str
    sort: int
    is_active: bool
    dish_count: int = 0
    created_at: datetime
    updated_at: datetime


# ==================== 标签 ====================
class DishTagCreate(BaseModel):
    """创建标签。"""

    name: str = Field(..., min_length=1, max_length=30)
    color: str = Field(default="", max_length=20, description="Element Plus 语义色或 #RRGGBB")
    sort: int = Field(default=0, ge=0)
    is_active: bool = Field(default=True, description="是否启用")


class DishTagUpdate(BaseModel):
    """更新标签。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=30)
    color: Optional[str] = Field(default=None, max_length=20)
    sort: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = Field(default=None, description="是否启用")


class DishTagOut(ORMBaseModel):
    """标签出参。"""

    id: int
    name: str
    color: str
    sort: int
    is_active: bool = True
    dish_count: int = 0
    created_at: datetime


# ==================== 套餐 / 规格 ====================
class DishSpecBase(BaseModel):
    """套餐公共字段（承载价格、库存、销量与售卖规则）。"""

    name: str = Field(..., min_length=1, max_length=50, description="套餐名称，如「单人套餐」")
    description: str = Field(default="", max_length=200)
    price: float = Field(..., ge=0, description="套餐价格（元）")
    stock: int = Field(default=0, ge=0, description="套餐库存")
    is_default: bool = Field(default=False, description="是否默认选中")
    is_active: bool = Field(default=True, description="是否可售")
    sort: int = Field(default=0, ge=0)

    # 售卖规则
    min_quantity: int = Field(default=1, ge=1, description="起购份数")
    max_quantity_per_order: int = Field(default=0, ge=0, description="每单限购，0 表示不限")
    daily_limit: int = Field(default=0, ge=0, description="每日限量，0 表示不限")
    serve_start_time: str = Field(default="", description="供应开始时间 HH:MM，空表示不限")
    serve_end_time: str = Field(default="", description="供应结束时间 HH:MM，空表示不限")

    @field_validator("serve_start_time", "serve_end_time")
    @classmethod
    def check_time(cls, value: str) -> str:
        import re

        if value in ("", None):
            return ""
        if not re.match(TIME_PATTERN, value):
            raise ValueError("时间格式应为 HH:MM（例如 10:00）")
        return value

    @field_validator("serve_end_time")
    @classmethod
    def check_time_range(cls, value: str, info) -> str:
        start = info.data.get("serve_start_time")
        if bool(start) != bool(value):
            raise ValueError("供应开始与结束时间需要同时填写或同时留空")
        return value


class DishSpecCreate(DishSpecBase):
    """新增套餐。"""


class DishSpecUpdate(BaseModel):
    """更新套餐（全部可选）。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)
    price: Optional[float] = Field(default=None, ge=0)
    stock: Optional[int] = Field(default=None, ge=0)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    sort: Optional[int] = Field(default=None, ge=0)
    min_quantity: Optional[int] = Field(default=None, ge=1)
    max_quantity_per_order: Optional[int] = Field(default=None, ge=0)
    daily_limit: Optional[int] = Field(default=None, ge=0)
    serve_start_time: Optional[str] = None
    serve_end_time: Optional[str] = None

    @field_validator("serve_start_time", "serve_end_time")
    @classmethod
    def check_time(cls, value: Optional[str]) -> Optional[str]:
        import re

        if value in (None, ""):
            return value
        if not re.match(TIME_PATTERN, value):
            raise ValueError("时间格式应为 HH:MM（例如 10:00）")
        return value


class DishSpecOut(ORMBaseModel):
    """套餐出参（含销量与规则）。"""

    id: int
    dish_id: int
    name: str
    description: str
    price: float
    stock: int
    sold_count: int
    sold_today: int
    is_default: bool
    is_active: bool
    sort: int
    min_quantity: int
    max_quantity_per_order: int
    daily_limit: int
    serve_start_time: str
    serve_end_time: str
    serve_time_text: str = ""
    created_at: datetime
    updated_at: datetime


# ==================== 菜品 ====================
class DishBase(BaseModel):
    """菜品公共字段。"""

    name: str = Field(..., min_length=1, max_length=100, description="菜名")
    description: str = Field(default="", max_length=2000)
    image: str = Field(default="", max_length=255, description="图片地址")
    price: float = Field(default=0, ge=0, description="基础价格（元）")
    stock: int = Field(default=0, ge=0, description="库存")
    unit: str = Field(default="份", max_length=10)
    status: DishStatus = Field(default=DishStatus.ON_SALE, description="售卖状态")
    is_recommended: bool = Field(default=False, description="是否推荐")
    sort: int = Field(default=0, ge=0)
    category_id: Optional[int] = Field(default=None, description="所属分类")
    tag_ids: List[int] = Field(default_factory=list, description="标签 ID 列表")


class DishCreate(DishBase):
    """创建菜品（可同时创建套餐，未传时自动生成一个「单点」默认套餐）。"""

    specs: List[DishSpecCreate] = Field(default_factory=list, description="套餐 / 规格列表")


class DishUpdate(BaseModel):
    """更新菜品（全部可选；tag_ids 传空数组表示清空标签）。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    image: Optional[str] = Field(default=None, max_length=255)
    price: Optional[float] = Field(default=None, ge=0)
    stock: Optional[int] = Field(default=None, ge=0)
    unit: Optional[str] = Field(default=None, max_length=10)
    status: Optional[DishStatus] = None
    is_recommended: Optional[bool] = None
    sort: Optional[int] = Field(default=None, ge=0)
    category_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None


class DishStatusUpdate(BaseModel):
    """上下架。"""

    status: DishStatus


class DishStockUpdate(BaseModel):
    """库存调整：mode=set 直接设置，mode=add 在原库存上增减（可为负）。"""

    quantity: int = Field(..., description="数量")
    mode: str = Field(default="set", pattern="^(set|add)$", description="set / add")


class DishListItem(ORMBaseModel):
    """菜品列表项。"""

    id: int
    name: str
    image: str
    price: float
    stock: int
    sold_count: int
    unit: str
    status: str
    is_recommended: bool
    sort: int
    category_id: Optional[int] = None
    category_name: str = ""
    tags: List[DishTagOut] = Field(default_factory=list)
    spec_count: int = 0
    is_available: bool = False
    created_at: datetime
    updated_at: datetime


class DishOut(DishListItem):
    """菜品详情（含描述与套餐列表）。"""

    description: str
    specs: List[DishSpecOut] = Field(default_factory=list)


class DishStatsOut(BaseModel):
    """菜品统计概览。"""

    total: int = 0
    on_sale: int = 0
    off_shelf: int = 0
    sold_out: int = 0
    low_stock: int = Field(default=0, description="库存低于阈值（默认 10）的菜品数")
    total_sold: int = Field(default=0, description="全部菜品累计销量")
    category_count: int = 0
    tag_count: int = 0
    top_selling: List[dict] = Field(default_factory=list, description="销量排行")


# ==================== 点菜（C 端） ====================
class MenuCategoryOut(DishCategoryOut):
    """点菜菜单中的分类（额外带可点菜品数量）。"""

    available_count: int = 0


class MenuDishItem(ORMBaseModel):
    """点菜菜单中的菜品条目（只暴露可售信息）。"""

    id: int
    name: str
    description: str
    image: str
    price: float
    stock: int
    sold_count: int
    unit: str
    is_recommended: bool
    category_id: Optional[int] = None
    category_name: str = ""
    tags: List[DishTagOut] = Field(default_factory=list)
    specs: List[DishSpecOut] = Field(default_factory=list)
    is_available: bool = False
