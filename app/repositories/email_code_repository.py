"""邮箱验证码仓储。"""

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.email_code import EmailCode
from app.repositories.base import BaseRepository


class EmailCodeRepository(BaseRepository[EmailCode]):
    """验证码数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(EmailCode, db)

    def latest(self, email: str, scene: str) -> Optional[EmailCode]:
        """取该邮箱 + 场景下最近一次发送的记录。"""
        stmt = (
            select(EmailCode)
            .where(EmailCode.email == email.lower(), EmailCode.scene == scene)
            .order_by(EmailCode.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def latest_usable(self, email: str, scene: str) -> Optional[EmailCode]:
        """取最近一条「未使用且未过期」的验证码记录。"""
        stmt = (
            select(EmailCode)
            .where(
                EmailCode.email == email.lower(),
                EmailCode.scene == scene,
                EmailCode.used_at.is_(None),
            )
            .order_by(EmailCode.id.desc())
            .limit(1)
        )
        record = self.db.execute(stmt).scalars().first()
        return record if record and record.is_usable() else None

    def invalidate(self, email: str, scene: str) -> None:
        """把该邮箱 + 场景下所有未使用的验证码一次性作废。"""
        from app.core.utils import utcnow

        self.db.execute(
            update(EmailCode)
            .where(
                EmailCode.email == email.lower(),
                EmailCode.scene == scene,
                EmailCode.used_at.is_(None),
            )
            .values(used_at=utcnow())
        )
        self.db.flush()
