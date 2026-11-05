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

    def _supports_window_count(self) -> bool:
        """当前方言是否支持 `count(*) over()`（SQLite 3.25+ / PostgreSQL）。"""
        bind = self.db.get_bind()
        name = bind.dialect.name if bind is not None else ""
        # MySQL 要看版本（8.0+ 才支持窗口函数），这里走保守路径
        return name in ("sqlite", "postgresql")

    def list(
        self,
        *,
        conditions: Optional[Sequence[Any]] = None,
        order_by: Optional[Any] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ModelType], int]:
        """分页查询，返回 (数据列表, 总条数)。

        有数据时用窗口函数把 `count(*)` 和数据合成**一次**查询，省掉一次数据库往返；
        结果为空（拿不到窗口值）或不支持窗口函数的方言，退回「先 count 再取数据」。
        """
        conditions = list(conditions or [])

        def _filter(stmt: Select) -> Select:
            for condition in conditions:
                stmt = stmt.where(condition)
            return stmt

        def _ordered(stmt: Select) -> Select:
            if order_by is None:
                return stmt
            # 支持传入单个表达式或 (list/tuple) 多字段组合
            if isinstance(order_by, (list, tuple)):
                return stmt.order_by(*order_by)
            return stmt.order_by(order_by)

        if self._supports_window_count():
            stmt = _filter(
                select(self.model, func.count().over().label("total_count"))
            )
            stmt = _ordered(stmt).offset(offset).limit(limit)
            rows = self.db.execute(stmt).unique().all()
            if rows:
                return [row[0] for row in rows], int(rows[0][1])

        count_stmt = _filter(select(func.count()).select_from(self.model))
        total = int(self.db.execute(count_stmt).scalar_one())
        if self._supports_window_count():
            # 上面已经查过这一页，确实没有数据
            return [], total

        stmt = _ordered(_filter(select(self.model))).offset(offset).limit(limit)
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
