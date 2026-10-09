"""点菜订单 ORM 模型。

设计说明：
- 订单创建时对菜品与套餐的库存做扣减、销量做累加（服务层负责）；
- 订单取消时按明细原样回滚；
- 明细中保存菜品名 / 套餐名 / 单价快照，避免菜品改名或删除后历史订单失真。

表名规范：`一级功能_二级功能_功能`
    dish_order_info  ->  菜品_订单_信息（订单主表）
    dish_order_item  ->  菜品_订单_明细
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class OrderStatus(str, enum.Enum):
    """订单状态。"""

    PENDING = "pending"        # 待接单
    CONFIRMED = "confirmed"    # 已接单 / 制作中
    COMPLETED = "completed"    # 已完成
    CANCELLED = "cancelled"    # 已取消

    @classmethod
    def values(cls) -> List[str]:
        return [item.value for item in cls]


# 允许的状态流转（终态不可再变更）
ORDER_TRANSITIONS = {
    OrderStatus.PENDING.value: {OrderStatus.CONFIRMED.value, OrderStatus.CANCELLED.value},
    OrderStatus.CONFIRMED.value: {OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value},
    OrderStatus.COMPLETED.value: set(),
    OrderStatus.CANCELLED.value: set(),
}


class DishOrder(PKMixin, TimestampMixin, Base):
    """点菜订单主表。"""

    __tablename__ = "dish_order_info"
    __table_args__ = (Index("ix_dish_order_info_status_created", "status", "created_at"),)

    order_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False, comment="订单号"
    )
    member_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="下单会员（扫码点菜可不登录，故允许为空）",
    )
    table_no: Mapped[str] = mapped_column(String(20), default="", comment="桌号")
    status: Mapped[str] = mapped_column(
        String(20), default=OrderStatus.PENDING.value, index=True, comment="订单状态"
    )
    total_quantity: Mapped[int] = mapped_column(Integer, default=0, comment="总份数")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), comment="订单总金额（元）"
    )
    remark: Mapped[str] = mapped_column(String(200), default="", comment="备注")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    member: Mapped[Optional["Member"]] = relationship(  # noqa: F821
        "Member", lazy="joined"
    )
    items: Mapped[List["DishOrderItem"]] = relationship(
        "DishOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def member_name(self) -> str:
        if not self.member:
            return ""
        return self.member.display_name

    @property
    def item_summary(self) -> str:
        """明细摘要，例如「宫保鸡丁 ×2、麻婆豆腐 ×1」，供列表直接展示。

        明细使用 lazy="selectin" 加载，列表查询不会产生 N+1。
        """
        if not self.items:
            return ""
        return "、".join(f"{item.dish_name} ×{item.quantity}" for item in self.items)

    @property
    def item_kinds(self) -> int:
        """明细中的菜品种类数。"""
        return len(self.items or [])

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<DishOrder id={self.id} no={self.order_no!r} status={self.status!r}>"


class DishOrderItem(PKMixin, Base):
    """订单明细（保存下单时的快照）。"""

    __tablename__ = "dish_order_item"

    order_id: Mapped[int] = mapped_column(
        ForeignKey("dish_order_info.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dish_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dish_base_info.id", ondelete="SET NULL"), nullable=True, index=True
    )
    spec_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dish_base_spec.id", ondelete="SET NULL"), nullable=True, index=True
    )

    dish_name: Mapped[str] = mapped_column(String(100), default="", comment="菜品名快照")
    spec_name: Mapped[str] = mapped_column(String(50), default="", comment="套餐名快照")
    image: Mapped[str] = mapped_column(String(255), default="", comment="菜品图片快照")
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), comment="成交单价快照"
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, comment="数量")
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), comment="小计金额"
    )

    order: Mapped["DishOrder"] = relationship("DishOrder", back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<DishOrderItem {self.dish_name!r} x{self.quantity}>"
