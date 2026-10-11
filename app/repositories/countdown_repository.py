"""倒数日仓储：所有针对 countdown_base_info 表的查询都集中在这里。"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.countdown import Countdown
from app.repositories.base import BaseRepository


class CountdownRepository(BaseRepository[Countdown]):
    """倒数日数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(Countdown, db)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        member_id: Optional[int] = None,
        cycle: Optional[str] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[Countdown], int]:
        """按条件分页搜索倒数日（按 ID 正序排列）。"""
        conditions: List[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(or_(Countdown.title.like(like), Countdown.remark.like(like)))
        if member_id:
            conditions.append(Countdown.member_id == member_id)
        if cycle:
            conditions.append(Countdown.cycle == cycle)
        if is_active is not None:
            conditions.append(Countdown.is_active.is_(is_active))

        return self.list(
            conditions=conditions,
            order_by=Countdown.id.asc(),
            offset=offset,
            limit=limit,
        )

    def count_active(self) -> int:
        """有效倒数日数量。"""
        return self.count(conditions=[Countdown.is_active.is_(True)])

    def count_all(self) -> int:
        """全部倒数日数量。"""
        return self.count()
