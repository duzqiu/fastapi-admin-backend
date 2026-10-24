"""会员仓储：所有针对 members 表的 SQL 查询都集中在这里。"""

from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.models.member import Member, MemberFollow
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


class MemberFollowRepository(BaseRepository[MemberFollow]):
    """会员关注关系的数据访问对象（`关注者 × 被关注者`）。"""

    def __init__(self, db: Session) -> None:
        super().__init__(MemberFollow, db)

    def find(self, follower_id: int, following_id: int) -> Optional[MemberFollow]:
        """关注记录；没关注返回 None。"""
        return self.get_by(follower_id=follower_id, following_id=following_id)

    def is_following(self, follower_id: Optional[int], following_id: Optional[int]) -> bool:
        """`follower_id` 是否关注了 `following_id`。"""
        if not follower_id or not following_id:
            return False
        return self.exists(follower_id=follower_id, following_id=following_id)

    def following_ids(self, follower_id: Optional[int]) -> set[int]:
        """该会员关注的所有人 ID（批量标 `is_following` 用）。"""
        if not follower_id:
            return set()
        stmt = select(MemberFollow.following_id).where(
            MemberFollow.follower_id == follower_id
        )
        return set(self.db.execute(stmt).scalars().all())

    def list_following_members(
        self, follower_id: int, *, offset: int = 0, limit: int = 10
    ) -> Tuple[List[Member], int]:
        """该会员关注的用户（最近关注的在前，只出启用的账号）。"""
        conditions = [
            MemberFollow.follower_id == follower_id,
            Member.is_active.is_(True),
        ]
        count_stmt = (
            select(func.count())
            .select_from(MemberFollow)
            .join(Member, Member.id == MemberFollow.following_id)
            .where(*conditions)
        )
        stmt = (
            select(Member)
            .join(MemberFollow, MemberFollow.following_id == Member.id)
            .where(*conditions)
            .order_by(MemberFollow.created_at.desc(), MemberFollow.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = int(self.db.execute(count_stmt).scalar_one())
        items = list(self.db.execute(stmt).scalars().unique().all())
        return items, total

    def count_following(self, follower_id: int) -> int:
        """该会员关注了多少人（只算启用账号）。"""
        stmt = (
            select(func.count())
            .select_from(MemberFollow)
            .join(Member, Member.id == MemberFollow.following_id)
            .where(
                MemberFollow.follower_id == follower_id,
                Member.is_active.is_(True),
            )
        )
        return int(self.db.execute(stmt).scalar_one())
