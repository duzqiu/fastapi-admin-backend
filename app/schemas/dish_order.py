"""点菜订单 DTO。"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.dish_order import OrderStatus
from app.schemas.common import ORMBaseModel


class OrderItemCreate(BaseModel):
    """下单明细入参。"""

    dish_id: int = Field(..., gt=0, description="菜品 ID")
    spec_id: Optional[int] = Field(default=None, gt=0, description="套餐 ID，菜品有套餐时必填")
    quantity: int = Field(..., ge=1, le=999, description="数量")


class OrderCreate(BaseModel):
    """提交订单入参。"""

    items: List[OrderItemCreate] = Field(..., min_length=1, description="菜品明细")
    table_no: str = Field(default="", max_length=20, description="桌号")
    remark: str = Field(default="", max_length=200, description="备注")

    @field_validator("items")
    @classmethod
    def deduplicate(cls, value: List[OrderItemCreate]) -> List[OrderItemCreate]:
        """同一菜品 + 套餐合并数量，避免重复提交绕过限购校验。"""
        merged: dict = {}
        for item in value:
            key = (item.dish_id, item.spec_id)
            if key in merged:
                merged[key].quantity += item.quantity
            else:
                merged[key] = item.model_copy()
        return list(merged.values())


class OrderItemOut(ORMBaseModel):
    """订单明细出参。"""

    id: int
    dish_id: Optional[int] = None
    spec_id: Optional[int] = None
    dish_name: str
    spec_name: str
    image: str
    price: float
    quantity: int
    amount: float


class OrderListItem(ORMBaseModel):
    """订单列表项。"""

    id: int
    order_no: str
    member_id: Optional[int] = None
    member_name: str = ""
    table_no: str
    status: str
    # 商品明细摘要：列表里不必再点开详情就能看到点了什么
    item_summary: str = ""
    item_kinds: int = 0
    total_quantity: int
    total_amount: float
    remark: str
    created_at: datetime


class OrderOut(OrderListItem):
    """订单详情。"""

    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    updated_at: datetime
    items: List[OrderItemOut] = Field(default_factory=list)


class OrderStatusUpdate(BaseModel):
    """后台修改订单状态。"""

    status: OrderStatus


class OrderStatsOut(BaseModel):
    """订单统计。"""

    total: int = 0
    pending: int = 0
    confirmed: int = 0
    completed: int = 0
    cancelled: int = 0
    today_orders: int = 0
    today_amount: float = 0
    today_quantity: int = 0
