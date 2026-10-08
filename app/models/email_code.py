"""邮箱验证码 ORM 模型（用户中心：注册 / 重置密码 / 换绑邮箱）。"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import utcnow
from app.db.base import Base
from app.models.mixins import PKMixin


class EmailScene(str, enum.Enum):
    """验证码使用场景。"""

    REGISTER = "register"
    RESET_PASSWORD = "reset_password"
    CHANGE_EMAIL = "change_email"
    CHANGE_PASSWORD = "change_password"


class EmailCode(PKMixin, Base):
    """邮箱验证码表。"""

    __tablename__ = "email_codes"
    __table_args__ = (Index("ix_email_codes_lookup", "email", "scene", "created_at"),)

    email: Mapped[str] = mapped_column(String(120), nullable=False, index=True, comment="目标邮箱")
    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="验证码")
    scene: Mapped[str] = mapped_column(String(30), nullable=False, index=True, comment="使用场景")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="过期时间")
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="使用时间（为空表示未使用）"
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, comment="校验失败次数")
    request_ip: Mapped[str] = mapped_column(String(64), default="", comment="请求 IP")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, comment="发送时间"
    )

    def is_expired(self) -> bool:
        return utcnow() > self.expires_at

    def is_usable(self) -> bool:
        return self.used_at is None and not self.is_expired()

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<EmailCode {self.email} {self.scene} used={self.used_at is not None}>"
