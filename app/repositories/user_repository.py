"""用户仓储：所有针对 users 表的 SQL 查询都集中在这里。"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """用户数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(User, db)

    def get_by_username(self, username: str) -> Optional[User]:
        return self.get_by(username=username)

    def get_by_email(self, email: str) -> Optional[User]:
        return self.get_by(email=email)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[User], int]:
        """按条件分页搜索用户。"""
        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(User.username.like(like), User.email.like(like), User.nickname.like(like))
            )
        if role:
            conditions.append(User.role == role)
        if is_active is not None:
            conditions.append(User.is_active == is_active)

        return self.list(
            conditions=conditions,
            order_by=User.id.desc(),
            offset=offset,
            limit=limit,
        )

    def count_by_role(self, role: str) -> int:
        return self.count(conditions=[User.role == role])

    def count_active(self) -> int:
        return self.count(conditions=[User.is_active.is_(True)])

    def username_taken(self, username: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(User.id).where(User.username == username)
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def email_taken(self, email: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(User.id).where(User.email == email)
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return self.db.execute(stmt).first() is not None
