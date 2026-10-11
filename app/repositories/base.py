"""通用仓储基类。

设计原则：
1. 仓储层只负责「和数据库打交道」，不写任何业务规则；
2. 只做 `flush` 不做 `commit`，事务边界交给服务层，保证多步操作可原子提交；
3. 上层不接触 SQLAlchemy 的 Query/Select，替换存储实现时只改这一层。
"""

from typing import Any, Generic, List, Optional, Sequence, Tuple, Type, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """封装最常用的增删改查能力，子类只需声明 `model`。"""

    def __init__(self, model: Type[ModelType], db: Session) -> None:
        self.model = model
        self.db = db

    # ------------------------- 查询 -------------------------
    def get(self, obj_id: int) -> Optional[ModelType]:
        """按主键查询。"""
        return self.db.get(self.model, obj_id)

    def get_by(self, **filters: Any) -> Optional[ModelType]:
        """按任意字段等值查询单条记录。"""
        stmt = select(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        return self.db.execute(stmt).scalars().first()

    def exists(self, **filters: Any) -> bool:
        """判断记录是否存在。"""
        stmt = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        return bool(self.db.execute(stmt).scalar_one())

    def list(
        self,
        *,
        conditions: Optional[Sequence[Any]] = None,
        order_by: Optional[Any] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ModelType], int]:
        """分页查询，返回 (数据列表, 总条数)。"""
        conditions = list(conditions or [])

        count_stmt = select(func.count()).select_from(self.model)
        stmt: Select = select(self.model)
        for condition in conditions:
            count_stmt = count_stmt.where(condition)
            stmt = stmt.where(condition)

        total = int(self.db.execute(count_stmt).scalar_one())

        if order_by is not None:
            # 支持传入单个表达式或 (list/tuple) 多字段组合
            if isinstance(order_by, (list, tuple)):
                stmt = stmt.order_by(*order_by)
            else:
                stmt = stmt.order_by(order_by)
        stmt = stmt.offset(offset).limit(limit)
        items = list(self.db.execute(stmt).scalars().unique().all())
        return items, total

    def all(self, *, conditions: Optional[Sequence[Any]] = None) -> List[ModelType]:
        """查询全部符合条件的记录（数据量大时慎用）。"""
        stmt: Select = select(self.model)
        for condition in conditions or []:
            stmt = stmt.where(condition)
        return list(self.db.execute(stmt).scalars().unique().all())

    def count(self, *, conditions: Optional[Sequence[Any]] = None) -> int:
        """统计条数。"""
        stmt = select(func.count()).select_from(self.model)
        for condition in conditions or []:
            stmt = stmt.where(condition)
        return int(self.db.execute(stmt).scalar_one())

    def sum(self, column: Any, *, conditions: Optional[Sequence[Any]] = None) -> int:
        """对某列求和（空值返回 0）。"""
        stmt = select(func.coalesce(func.sum(column), 0)).select_from(self.model)
        for condition in conditions or []:
            stmt = stmt.where(condition)
        return int(self.db.execute(stmt).scalar_one() or 0)

    # ------------------------- 写入 -------------------------
    def create(self, **values: Any) -> ModelType:
        """新增记录（flush 后返回带主键的对象，未提交）。"""
        obj = self.model(**values)
        self.db.add(obj)
        self.db.flush()
        return obj

    def update(self, obj: ModelType, **values: Any) -> ModelType:
        """更新记录，值为 None 的字段会被忽略。"""
        for field, value in values.items():
            if value is not None:
                setattr(obj, field, value)
        self.db.add(obj)
        self.db.flush()
        return obj

    def delete(self, obj: ModelType) -> None:
        """删除记录。"""
        self.db.delete(obj)
        self.db.flush()
