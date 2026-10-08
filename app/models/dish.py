"""点菜菜单域 ORM 模型：分类、标签、菜品、套餐规格。

模型关系：
    DishCategory 1 ── n Dish n ── n DishTag（多对多）
                          │
                          1
                          │
                          n
                       DishSpec（套餐 / 规格，承载价格、库存、销量与售卖规则）
"""

import enum
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class DishStatus(str, enum.Enum):
    """菜品售卖状态。"""

    ON_SALE = "on_sale"        # 在售
    OFF_SHELF = "off_shelf"    # 已下架
    SOLD_OUT = "sold_out"      # 已售罄


# 菜品与标签的多对多关联表
dish_tag_links = Table(
    "dish_tag_links",
    Base.metadata,
    Column("dish_id", ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("dish_tags.id", ondelete="CASCADE"), primary_key=True),
)


class DishCategory(PKMixin, TimestampMixin, Base):
    """菜品分类。"""

    __tablename__ = "dish_categories"

    name: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="分类名称"
    )
    description: Mapped[str] = mapped_column(String(200), default="", comment="分类描述")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值，越小越靠前")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")

    dishes: Mapped[List["Dish"]] = relationship("Dish", back_populates="category")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<DishCategory id={self.id} name={self.name!r}>"


class DishTag(PKMixin, TimestampMixin, Base):
    """菜品标签（招牌、新品、微辣……），一个菜品可以有多个标签。

    `is_active` 与分类的同名字段语义一致：停用后不再出现在 C 端菜单的标签列表中，
    后台仍可正常查看、编辑并继续挂在菜品上（不影响历史数据）。
    """

    __tablename__ = "dish_tags"

    name: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False, comment="标签名称"
    )
    color: Mapped[str] = mapped_column(
        String(20), default="", comment="标签颜色：Element Plus 语义色或 #RRGGBB"
    )
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")

    dishes: Mapped[List["Dish"]] = relationship(
        "Dish", secondary=dish_tag_links, back_populates="tags"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<DishTag id={self.id} name={self.name!r}>"


class Dish(PKMixin, TimestampMixin, Base):
    """菜品（菜单上的一道菜）。"""

    __tablename__ = "dishes"
    __table_args__ = (Index("ix_dishes_status_sort", "status", "sort"),)

    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False, comment="菜名")
    description: Mapped[str] = mapped_column(Text, default="", comment="菜品描述")
    image: Mapped[str] = mapped_column(String(255), default="", comment="菜品图片地址")
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), comment="基础价格（元）"
    )
    stock: Mapped[int] = mapped_column(Integer, default=0, comment="菜品总库存（份）")
    sold_count: Mapped[int] = mapped_column(Integer, default=0, comment="累计已售份数")
    unit: Mapped[str] = mapped_column(String(10), default="份", comment="计量单位")
    status: Mapped[str] = mapped_column(
        String(20), default=DishStatus.ON_SALE.value, index=True, comment="售卖状态"
    )
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否推荐")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值")

    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dish_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属分类",
    )
    category: Mapped[Optional["DishCategory"]] = relationship(
        "DishCategory", back_populates="dishes", lazy="joined"
    )
    tags: Mapped[List["DishTag"]] = relationship(
        "DishTag", secondary=dish_tag_links, back_populates="dishes", lazy="selectin"
    )
    specs: Mapped[List["DishSpec"]] = relationship(
        "DishSpec",
        back_populates="dish",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="DishSpec.sort",
    )

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else ""

    @property
    def tag_names(self) -> List[str]:
        return [tag.name for tag in self.tags]

    @property
    def spec_count(self) -> int:
        return len(self.specs or [])

    @property
    def is_available(self) -> bool:
        """是否可被下单：在售且仍有库存。"""
        return self.status == DishStatus.ON_SALE.value and self.stock > 0

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Dish id={self.id} name={self.name!r}>"


class DishSpec(PKMixin, TimestampMixin, Base):
    """菜品套餐 / 规格。

    每个菜品可以有多个可售套餐（单点、单人套餐、双人套餐……），
    价格、库存、销量与售卖规则都挂在套餐上。
    """

    __tablename__ = "dish_specs"

    dish_id: Mapped[int] = mapped_column(
        ForeignKey("dishes.id", ondelete="CASCADE"), index=True, nullable=False, comment="所属菜品"
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="套餐 / 规格名称")
    description: Mapped[str] = mapped_column(String(200), default="", comment="套餐说明")
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), comment="套餐价格（元）"
    )
    stock: Mapped[int] = mapped_column(Integer, default=0, comment="套餐库存（份）")
    sold_count: Mapped[int] = mapped_column(Integer, default=0, comment="套餐累计已售份数")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否默认选中")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可售")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值")

    # ---------- 售卖规则 ----------
    min_quantity: Mapped[int] = mapped_column(Integer, default=1, comment="起购份数")
    max_quantity_per_order: Mapped[int] = mapped_column(
        Integer, default=0, comment="每单限购份数，0 表示不限"
    )
    daily_limit: Mapped[int] = mapped_column(Integer, default=0, comment="每日限量份数，0 表示不限")
    sold_today: Mapped[int] = mapped_column(Integer, default=0, comment="今日已售（下单时按日期自动重置）")
    sold_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="sold_today 对应日期")
    serve_start_time: Mapped[str] = mapped_column(
        String(5), default="", comment="供应开始时间 HH:MM，空表示不限制"
    )
    serve_end_time: Mapped[str] = mapped_column(
        String(5), default="", comment="供应结束时间 HH:MM，空表示不限制"
    )

    dish: Mapped["Dish"] = relationship("Dish", back_populates="specs")

    @property
    def serve_time_text(self) -> str:
        """供应时段展示文案。"""
        if not self.serve_start_time or not self.serve_end_time:
            return "全天供应"
        return f"{self.serve_start_time} - {self.serve_end_time}"

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<DishSpec id={self.id} name={self.name!r} price={self.price}>"
