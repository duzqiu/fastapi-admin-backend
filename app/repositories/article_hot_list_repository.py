"""热搜榜单条目的数据访问。

只做数据访问：不过滤业务规则、不 commit（事务边界在服务层）。
"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.article_hot_list import HotListItem
from app.repositories.base import BaseRepository


class HotListRepository(BaseRepository[HotListItem]):
    def __init__(self, db: Session) -> None:
        super().__init__(HotListItem, db)

    # ------------------------- 前台：按渠道出榜 -------------------------
    def board_page(
        self, source: str, *, offset: int = 0, limit: int = 50
    ) -> Tuple[List[HotListItem], int]:
        """某个渠道的榜单条目（按入库顺序）+ 该渠道的总条数。

        排序用 `id`：爬虫按页面从上到下写入，入库顺序就是页面展示顺序；
        而 `rank` 是原始文本（可能是「置顶」），没法直接按数值排。
        """
        return self.list(
            conditions=[HotListItem.source == source],
            order_by=(HotListItem.id.asc(),),
            offset=offset,
            limit=limit,
        )

    def source_counts(self) -> List[Tuple[str, int]]:
        """每个渠道各有多少条（渠道按字母序）。"""
        stmt = (
            select(HotListItem.source, func.count())
            .group_by(HotListItem.source)
            .order_by(HotListItem.source.asc())
        )
        return [(str(row[0]), int(row[1])) for row in self.db.execute(stmt).all()]

    # ------------------------- 后台：管理列表 -------------------------
    def search(
        self,
        *,
        keyword: Optional[str] = None,
        source: Optional[str] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[HotListItem], int]:
        """后台列表：关键词模糊搜（标题 / 渠道 / 热度 / 排名）+ 渠道精确筛选。"""
        conditions: List[Any] = []
        if keyword and keyword.strip():
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    HotListItem.name.like(like),
                    HotListItem.source.like(like),
                    HotListItem.heat.like(like),
                    HotListItem.rank.like(like),
                )
            )
        if source and source.strip():
            conditions.append(HotListItem.source == source.strip())
        return self.list(
            conditions=conditions,
            order_by=(HotListItem.source.asc(), HotListItem.id.asc()),
            offset=offset,
            limit=limit,
        )

    # ------------------------- 写入 -------------------------
    def apply(self, obj: HotListItem, values: dict) -> HotListItem:
        """按传入的键逐字段覆盖。

        与基类 `update()` 的区别：这里**显式传 None 也会生效**，
        否则 heat / rank 这种可空字段永远清不掉。
        """
        for field, value in values.items():
            setattr(obj, field, value)
        self.db.add(obj)
        self.db.flush()
        return obj
