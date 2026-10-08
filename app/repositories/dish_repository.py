"""点菜菜单域仓储：分类、标签、菜品、套餐规格。"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.dish import (
    Dish,
    DishCategory,
    DishSpec,
    DishStatus,
    DishTag,
    dish_tag_links,
)
from app.repositories.base import BaseRepository


class DishCategoryRepository(BaseRepository[DishCategory]):
    """分类数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(DishCategory, db)

    def list_all(self, *, only_active: bool = False) -> List[DishCategory]:
        conditions = [DishCategory.is_active.is_(True)] if only_active else []
        return self.all_ordered(conditions=conditions)

    def all_ordered(self, *, conditions: Optional[Sequence[Any]] = None) -> List[DishCategory]:
        stmt = select(DishCategory)
        for condition in conditions or []:
            stmt = stmt.where(condition)
        stmt = stmt.order_by(DishCategory.sort.asc(), DishCategory.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def name_taken(self, name: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(DishCategory.id).where(DishCategory.name == name)
        if exclude_id is not None:
            stmt = stmt.where(DishCategory.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def dish_count_map(self) -> Dict[int, int]:
        """每个分类下的菜品数量。"""
        stmt = (
            select(Dish.category_id, func.count(Dish.id))
            .where(Dish.category_id.is_not(None))
            .group_by(Dish.category_id)
        )
        return {row[0]: int(row[1]) for row in self.db.execute(stmt).all()}


class DishTagRepository(BaseRepository[DishTag]):
    """标签数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(DishTag, db)

    def all_ordered(self) -> List[DishTag]:
        stmt = select(DishTag).order_by(DishTag.sort.asc(), DishTag.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def name_taken(self, name: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(DishTag.id).where(DishTag.name == name)
        if exclude_id is not None:
            stmt = stmt.where(DishTag.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def list_by_ids(self, tag_ids: Sequence[int]) -> List[DishTag]:
        if not tag_ids:
            return []
        stmt = select(DishTag).where(DishTag.id.in_(list(tag_ids)))
        return list(self.db.execute(stmt).scalars().all())

    def dish_count_map(self) -> Dict[int, int]:
        stmt = select(dish_tag_links.c.tag_id, func.count(dish_tag_links.c.dish_id)).group_by(
            dish_tag_links.c.tag_id
        )
        return {row[0]: int(row[1]) for row in self.db.execute(stmt).all()}


class DishSpecRepository(BaseRepository[DishSpec]):
    """套餐 / 规格数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(DishSpec, db)

    def list_by_dish(self, dish_id: int) -> List[DishSpec]:
        stmt = (
            select(DishSpec)
            .where(DishSpec.dish_id == dish_id)
            .order_by(DishSpec.sort.asc(), DishSpec.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_of_dish(self, dish_id: int, spec_id: int) -> Optional[DishSpec]:
        stmt = select(DishSpec).where(DishSpec.id == spec_id, DishSpec.dish_id == dish_id)
        return self.db.execute(stmt).scalars().first()

    def clear_default(self, dish_id: int, exclude_id: Optional[int] = None) -> None:
        """把该菜品下其它套餐的「默认」标记取消。"""
        stmt = select(DishSpec).where(DishSpec.dish_id == dish_id, DishSpec.is_default.is_(True))
        if exclude_id is not None:
            stmt = stmt.where(DishSpec.id != exclude_id)
        for spec in self.db.execute(stmt).scalars().all():
            spec.is_default = False
            self.db.add(spec)
        self.db.flush()


class DishRepository(BaseRepository[Dish]):
    """菜品数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(Dish, db)

    def get_with_relations(self, dish_id: int) -> Optional[Dish]:
        stmt = (
            select(Dish)
            .where(Dish.id == dish_id)
            .options(selectinload(Dish.tags), selectinload(Dish.specs))
        )
        return self.db.execute(stmt).scalars().unique().first()

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        category_id: Optional[int] = None,
        tag_id: Optional[int] = None,
        status: Optional[str] = None,
        is_recommended: Optional[bool] = None,
        only_available: bool = False,
        low_stock_below: Optional[int] = None,
        offset: int = 0,
        limit: int = 10,
        order_by: Optional[Any] = None,
    ) -> Tuple[List[Dish], int]:
        """按条件分页搜索菜品。"""
        stmt = select(Dish).options(selectinload(Dish.tags), selectinload(Dish.specs))
        count_stmt = select(func.count(func.distinct(Dish.id))).select_from(Dish)

        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(or_(Dish.name.like(like), Dish.description.like(like)))
        if category_id is not None:
            conditions.append(Dish.category_id == category_id)
        if status:
            conditions.append(Dish.status == status)
        if is_recommended is not None:
            conditions.append(Dish.is_recommended.is_(is_recommended))
        if only_available:
            conditions.append(Dish.status == DishStatus.ON_SALE.value)
            conditions.append(Dish.stock > 0)
        if low_stock_below is not None:
            conditions.append(Dish.stock < low_stock_below)

        for condition in conditions:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        if tag_id is not None:
            tag_condition = Dish.id.in_(
                select(dish_tag_links.c.dish_id).where(dish_tag_links.c.tag_id == tag_id)
            )
            stmt = stmt.where(tag_condition)
            count_stmt = count_stmt.where(tag_condition)

        total = int(self.db.execute(count_stmt).scalar_one())

        stmt = stmt.order_by(order_by if order_by is not None else Dish.sort.asc(), Dish.id.desc())
        stmt = stmt.offset(offset).limit(limit)
        items = list(self.db.execute(stmt).scalars().unique().all())
        return items, total

    # ------------------------- 统计 -------------------------
    def count_by_status(self, status: str) -> int:
        return self.count(conditions=[Dish.status == status])

    def count_low_stock(self, threshold: int = 10) -> int:
        return self.count(conditions=[Dish.stock < threshold])

    def total_sold(self) -> int:
        return self.sum(Dish.sold_count)

    def top_selling(self, limit: int = 5) -> List[Dish]:
        stmt = (
            select(Dish).order_by(Dish.sold_count.desc(), Dish.id.asc()).limit(limit)
        )
        return list(self.db.execute(stmt).scalars().unique().all())
