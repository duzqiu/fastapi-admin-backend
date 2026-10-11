"""会员仓储：所有针对 members 表的 SQL 查询都集中在这里。"""

from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.models.member import Member
from app.repositories.base import BaseRepository


class MemberRepository(BaseRepository[Member]):
    """会员数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(Member, db)

    def get_by_email(self, email: str) -> Optional[Member]:
        return self.get_by(email=email.lower())

    def member_no_taken(self, member_no: str) -> bool:
        """判断会员编号是否已被占用（注册时用于生成不重复编号）。"""
        return self.exists(member_no=member_no)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        gender: Optional[str] = None,
        is_active: Optional[bool] = None,
        email_verified: Optional[bool] = None,
        registered_after: Optional[datetime] = None,
        registered_before: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[Member], int]:
        """按条件分页搜索会员（支持注册时间范围）。"""
        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    Member.member_no.like(like),
                    Member.email.like(like),
                    Member.nickname.like(like),
                    Member.phone.like(like),
                )
            )
        if gender:
            conditions.append(Member.gender == gender)
        if is_active is not None:
            conditions.append(Member.is_active == is_active)
        if email_verified is not None:
            conditions.append(Member.email_verified == email_verified)
        if registered_after is not None:
            conditions.append(Member.created_at >= registered_after)
        if registered_before is not None:
            conditions.append(Member.created_at <= registered_before)

        return self.list(
            conditions=conditions,
            order_by=Member.id.asc(),
            offset=offset,
            limit=limit,
        )

    def email_taken(self, email: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(Member.id).where(Member.email == email.lower())
        if exclude_id is not None:
            stmt = stmt.where(Member.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    # ------------------------- 统计 -------------------------
    def count_active(self) -> int:
        return self.count(conditions=[Member.is_active.is_(True)])

    def count_verified(self) -> int:
        return self.count(conditions=[Member.email_verified.is_(True)])

    def count_registered_within_days(self, days: int) -> int:
        since = utcnow() - timedelta(days=days)
        return self.count(conditions=[Member.created_at >= since])

    def count_by_gender(self) -> dict:
        stmt = select(Member.gender, func.count()).group_by(Member.gender)
        return {row[0]: int(row[1]) for row in self.db.execute(stmt).all()}

    def recent(self, limit: int = 5) -> List[Member]:
        stmt = select(Member).order_by(Member.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())
