"""点菜订单仓储。"""

from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.dish_order import DishOrder, DishOrderItem, OrderStatus
from app.repositories.base import BaseRepository


class DishOrderRepository(BaseRepository[DishOrder]):
    """订单数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(DishOrder, db)

    def get_with_items(self, order_id: int) -> Optional[DishOrder]:
        stmt = (
            select(DishOrder)
            .where(DishOrder.id == order_id)
            .options(selectinload(DishOrder.items))
        )
        return self.db.execute(stmt).scalars().unique().first()

    def get_by_order_no(self, order_no: str) -> Optional[DishOrder]:
        return self.get_by(order_no=order_no)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        member_id: Optional[int] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[DishOrder], int]:
        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(or_(DishOrder.order_no.like(like), DishOrder.table_no.like(like)))
        if status:
            conditions.append(DishOrder.status == status)
        if member_id is not None:
            conditions.append(DishOrder.member_id == member_id)
        if created_after is not None:
            conditions.append(DishOrder.created_at >= created_after)
        if created_before is not None:
            conditions.append(DishOrder.created_at <= created_before)

        return self.list(
            conditions=conditions,
            order_by=DishOrder.id.desc(),
            offset=offset,
            limit=limit,
        )

    # ------------------------- 统计 -------------------------
    def count_by_status(self, status: str) -> int:
        return self.count(conditions=[DishOrder.status == status])

    def aggregate(self, *, conditions: Optional[Sequence[Any]] = None) -> Tuple[int, float, int]:
        """返回 (订单数, 金额合计, 份数合计)。"""
        stmt = select(
            func.count(DishOrder.id),
            func.coalesce(func.sum(DishOrder.total_amount), 0),
            func.coalesce(func.sum(DishOrder.total_quantity), 0),
        )
        for condition in conditions or []:
            stmt = stmt.where(condition)
        row = self.db.execute(stmt).one()
        return int(row[0]), float(row[1]), int(row[2])

    def aggregate_since(self, since: datetime) -> Tuple[int, float, int]:
        """统计某时间点之后的订单（排除已取消）。"""
        return self.aggregate(
            conditions=[DishOrder.created_at >= since, DishOrder.status != OrderStatus.CANCELLED.value]
        )

    def dish_sales(self, limit: int = 10) -> List[dict]:
        """按明细统计各菜品销量（排除已取消订单）。"""
        stmt = (
            select(
                DishOrderItem.dish_id,
                DishOrderItem.dish_name,
                func.sum(DishOrderItem.quantity).label("quantity"),
                func.sum(DishOrderItem.amount).label("amount"),
            )
            .join(DishOrder, DishOrder.id == DishOrderItem.order_id)
            .where(DishOrder.status != OrderStatus.CANCELLED.value)
            .group_by(DishOrderItem.dish_id, DishOrderItem.dish_name)
            .order_by(func.sum(DishOrderItem.quantity).desc())
            .limit(limit)
        )
        return [
            {
                "dish_id": row[0],
                "dish_name": row[1],
                "quantity": int(row[2] or 0),
                "amount": float(row[3] or 0),
            }
            for row in self.db.execute(stmt).all()
        ]
