"""用户 ORM 模型。"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class UserRole(str, enum.Enum):
    """用户角色枚举。"""

    ADMIN = "admin"
    EDITOR = "editor"
    USER = "user"


class User(PKMixin, TimestampMixin, Base):
    """系统用户表。"""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="登录名"
    )
    email: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False, comment="邮箱"
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    nickname: Mapped[str] = mapped_column(String(50), default="", comment="昵称")
    role: Mapped[str] = mapped_column(
        String(20), default=UserRole.USER.value, index=True, comment="角色"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, comment="是否启用"
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="最后登录时间"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<User id={self.id} username={self.username!r}>"


__all__ = ["User", "UserRole"]
