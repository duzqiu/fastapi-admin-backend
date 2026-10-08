"""点菜订单服务：下单校验、库存与销量联动、订单状态流转。

核心规则：
1. 下单时校验菜品状态、库存、套餐规则（起购 / 限购 / 每日限量 / 供应时段）；
2. 校验通过后扣减「菜品库存」与「套餐库存」，并累加对应销量；
3. 取消订单时按明细原样回滚库存与销量；
4. 订单状态只能按 ORDER_TRANSITIONS 中的允许路径流转。
"""

import secrets
from datetime import datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ForbiddenError, NotFoundError
from app.core.utils import in_time_window, local_now, local_today, utcnow
from app.models.dish import Dish, DishSpec, DishStatus
from app.models.dish_order import ORDER_TRANSITIONS, DishOrder, DishOrderItem, OrderStatus
from app.models.member import Member
from app.repositories.dish_order_repository import DishOrderRepository
from app.repositories.dish_repository import DishRepository, DishSpecRepository
from app.schemas.dish_order import OrderCreate, OrderItemCreate

STATUS_LABELS = {
    OrderStatus.PENDING.value: "待接单",
    OrderStatus.CONFIRMED.value: "已接单",
    OrderStatus.COMPLETED.value: "已完成",
    OrderStatus.CANCELLED.value: "已取消",
}


def _money(value: Any) -> Decimal:
    """统一转成两位小数的 Decimal，避免浮点误差。"""
    return Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"))


class DishOrderService:
    """订单业务逻辑。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.orders = DishOrderRepository(db)
        self.dishes = DishRepository(db)
        self.specs = DishSpecRepository(db)

    # ==================== 下单 ====================
    def _generate_order_no(self) -> str:
        for _ in range(5):
            order_no = f"D{local_now():%Y%m%d%H%M%S}{secrets.randbelow(10000):04d}"
            if self.orders.get_by_order_no(order_no) is None:
                return order_no
        return f"D{local_now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def _reset_daily_counter(spec: DishSpec) -> None:
        """每日限量按「本地日期」重置。"""
        today = local_today()
        if spec.sold_date != today:
            spec.sold_today = 0
            spec.sold_date = today

    def _check_spec_rules(self, dish: Dish, spec: DishSpec, quantity: int) -> None:
        """校验套餐的售卖规则。"""
        label = f"「{dish.name} · {spec.name}」"

        if quantity < spec.min_quantity:
            raise BusinessError(f"{label} 起购 {spec.min_quantity} 份")
        if spec.max_quantity_per_order and quantity > spec.max_quantity_per_order:
            raise BusinessError(f"{label} 每单最多购买 {spec.max_quantity_per_order} 份")

        self._reset_daily_counter(spec)
        if spec.daily_limit and spec.sold_today + quantity > spec.daily_limit:
            remaining = max(spec.daily_limit - spec.sold_today, 0)
            raise BusinessError(f"{label} 今日限量 {spec.daily_limit} 份，剩余 {remaining} 份")

        if not in_time_window(local_now().time(), spec.serve_start_time, spec.serve_end_time):
            raise BusinessError(
                f"{label} 仅在 {spec.serve_start_time}-{spec.serve_end_time} 供应"
            )

    def _prepare_item(self, item: OrderItemCreate) -> Dict[str, Any]:
        """校验单个明细并返回下单结果（含应扣减的库存与应累加的销量）。"""
        dish = self.dishes.get(item.dish_id)
        if dish is None:
            raise NotFoundError(f"菜品不存在: id={item.dish_id}")
        if dish.status != DishStatus.ON_SALE.value:
            raise BusinessError(f"「{dish.name}」当前不可点单")
        if dish.stock < item.quantity:
            raise BusinessError(f"「{dish.name}」库存不足，仅剩 {dish.stock} 份")

        active_specs = [spec for spec in dish.specs if spec.is_active]
        spec: Optional[DishSpec] = None

        if active_specs:
            if item.spec_id is None:
                raise BusinessError(f"「{dish.name}」需要选择套餐")
            spec = next((s for s in active_specs if s.id == item.spec_id), None)
            if spec is None:
                raise BusinessError(f"「{dish.name}」所选套餐不存在或已停售")
            self._check_spec_rules(dish, spec, item.quantity)
            if spec.stock < item.quantity:
                raise BusinessError(
                    f"「{dish.name} · {spec.name}」库存不足，仅剩 {spec.stock} 份"
                )
        elif item.spec_id is not None:
            raise BusinessError(f"「{dish.name}」暂无可选套餐，无需指定 spec_id")

        price = _money(spec.price if spec else dish.price)
        return {
            "dish": dish,
            "spec": spec,
            "price": price,
            "quantity": item.quantity,
            "amount": _money(price * item.quantity),
        }

    def submit_order(self, payload: OrderCreate, member: Optional[Member] = None) -> DishOrder:
        """提交订单：校验 → 扣库存 → 累加销量 → 落库。"""
        prepared = [self._prepare_item(item) for item in payload.items]

        total_quantity = sum(row["quantity"] for row in prepared)
        total_amount = _money(sum((row["amount"] for row in prepared), Decimal("0.00")))

        order = self.orders.create(
            order_no=self._generate_order_no(),
            member_id=member.id if member else None,
            table_no=payload.table_no.strip(),
            status=OrderStatus.PENDING.value,
            total_quantity=total_quantity,
            total_amount=total_amount,
            remark=payload.remark.strip(),
        )

        for row in prepared:
            dish: Dish = row["dish"]
            spec: Optional[DishSpec] = row["spec"]
            quantity: int = row["quantity"]

            # 扣减库存 + 累加销量
            dish.stock -= quantity
            dish.sold_count = (dish.sold_count or 0) + quantity
            if dish.stock == 0 and dish.status == DishStatus.ON_SALE.value:
                dish.status = DishStatus.SOLD_OUT.value
            self.db.add(dish)

            if spec is not None:
                spec.stock -= quantity
                spec.sold_count = (spec.sold_count or 0) + quantity
                self._reset_daily_counter(spec)
                spec.sold_today += quantity
                self.db.add(spec)

            self.db.add(
                DishOrderItem(
                    order_id=order.id,
                    dish_id=dish.id,
                    spec_id=spec.id if spec else None,
                    dish_name=dish.name,
                    spec_name=spec.name if spec else "",
                    image=dish.image,
                    price=row["price"],
                    quantity=quantity,
                    amount=row["amount"],
                )
            )

        self.db.commit()
        self.db.refresh(order)
        return self.get_order_or_404(order.id)

    # ==================== 查询 ====================
    def get_order_or_404(self, order_id: int) -> DishOrder:
        order = self.orders.get_with_items(order_id)
        if order is None:
            raise NotFoundError(f"订单不存在: id={order_id}")
        return order

    def list_my_orders(
        self,
        *,
        member_id: int,
        page: int = 1,
        page_size: int = 10,
        status: Optional[str] = None,
    ) -> Tuple[List[DishOrder], int]:
        return self.orders.search(
            member_id=member_id,
            status=status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def admin_list(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
    ) -> Tuple[List[DishOrder], int]:
        return self.orders.search(
            keyword=keyword,
            status=status,
            created_after=created_after,
            created_before=created_before,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    # ==================== 状态流转 ====================
    def _restore_stock(self, order: DishOrder) -> None:
        """回滚订单占用的库存与销量。"""
        today = local_today()
        for item in order.items:
            if item.dish_id:
                dish = self.dishes.get(item.dish_id)
                if dish is not None:
                    dish.stock = (dish.stock or 0) + item.quantity
                    dish.sold_count = max((dish.sold_count or 0) - item.quantity, 0)
                    # 售罄的菜品恢复在售
                    if dish.status == DishStatus.SOLD_OUT.value and dish.stock > 0:
                        dish.status = DishStatus.ON_SALE.value
                    self.db.add(dish)

            if item.spec_id:
                spec = self.specs.get(item.spec_id)
                if spec is not None:
                    spec.stock = (spec.stock or 0) + item.quantity
                    spec.sold_count = max((spec.sold_count or 0) - item.quantity, 0)
                    if spec.sold_date == today:
                        spec.sold_today = max((spec.sold_today or 0) - item.quantity, 0)
                    self.db.add(spec)

    def cancel_order(self, order_id: int, member_id: Optional[int] = None) -> DishOrder:
        """取消订单（会员只能取消自己的订单）。"""
        order = self.get_order_or_404(order_id)
        if member_id is not None and order.member_id != member_id:
            raise ForbiddenError("无权操作该订单")
        return self._change_status(order, OrderStatus.CANCELLED.value)

    def admin_update_status(self, order_id: int, status: str) -> DishOrder:
        """后台修改订单状态。"""
        order = self.get_order_or_404(order_id)
        return self._change_status(order, status)

    def _change_status(self, order: DishOrder, status: str) -> DishOrder:
        if status == order.status:
            raise BusinessError(f"订单已经是「{STATUS_LABELS.get(status, status)}」状态")

        allowed = ORDER_TRANSITIONS.get(order.status, set())
        if status not in allowed:
            raise BusinessError(
                f"「{STATUS_LABELS.get(order.status, order.status)}」不能变更为"
                f"「{STATUS_LABELS.get(status, status)}」"
            )

        if status == OrderStatus.CANCELLED.value:
            self._restore_stock(order)
            order.cancelled_at = utcnow()
        elif status == OrderStatus.CONFIRMED.value:
            order.confirmed_at = utcnow()
        elif status == OrderStatus.COMPLETED.value:
            order.completed_at = utcnow()

        order.status = status
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return self.get_order_or_404(order.id)

    def admin_delete(self, order_id: int) -> None:
        """删除订单（已取消的订单已回滚过库存，删除不会再回滚）。"""
        order = self.get_order_or_404(order_id)
        self.orders.delete(order)
        self.db.commit()

    # ==================== 统计 ====================
    @staticmethod
    def _today_start_utc() -> datetime:
        """本地「今天 00:00」对应的 UTC 时间（created_at 以 UTC 存储）。"""
        local_start = datetime.combine(local_today(), time.min)
        return utcnow() - (local_now() - local_start)

    def stats(self) -> Dict[str, Any]:
        """订单统计：各状态数量 + 今日经营数据 + 菜品销量排行。"""
        today_orders, today_amount, today_quantity = self.orders.aggregate_since(
            self._today_start_utc()
        )
        return {
            "total": self.orders.count(),
            "pending": self.orders.count_by_status(OrderStatus.PENDING.value),
            "confirmed": self.orders.count_by_status(OrderStatus.CONFIRMED.value),
            "completed": self.orders.count_by_status(OrderStatus.COMPLETED.value),
            "cancelled": self.orders.count_by_status(OrderStatus.CANCELLED.value),
            "today_orders": today_orders,
            "today_amount": today_amount,
            "today_quantity": today_quantity,
        }

    def dish_sales(self, limit: int = 10) -> List[Dict[str, Any]]:
        """按订单明细聚合的菜品销量排行。"""
        return self.orders.dish_sales(limit)
