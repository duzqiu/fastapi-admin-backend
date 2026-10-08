"""会员（用户中心注册用户）ORM 模型。

为什么单独建表而不是复用 `users`：
- `users` 是后台账号（B 端，由管理员创建、带角色权限）；
- `members` 是用户中心自助注册的 C 端用户（邮箱注册、无后台权限）；
- 两者生命周期、字段、令牌作用域完全不同，分开可避免会员令牌越权访问后台接口。
"""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class MemberGender(str, enum.Enum):
    """性别枚举。"""

    UNKNOWN = "unknown"
    MALE = "male"
    FEMALE = "female"


class Member(PKMixin, TimestampMixin, Base):
    """用户中心会员表。"""

    __tablename__ = "members"
    __table_args__ = (Index("ix_members_active_created", "is_active", "created_at"),)

    # ---------- 注册与登录 ----------
    email: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False, comment="注册邮箱（登录账号）"
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, comment="邮箱是否已验证"
    )
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="邮箱验证时间"
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="最后登录时间"
    )
    register_ip: Mapped[str] = mapped_column(String(64), default="", comment="注册 IP")

    # ---------- 个人资料 ----------
    nickname: Mapped[str] = mapped_column(String(50), default="", index=True, comment="昵称")
    avatar: Mapped[str] = mapped_column(String(255), default="", comment="头像地址")
    gender: Mapped[str] = mapped_column(
        String(10), default=MemberGender.UNKNOWN.value, index=True, comment="性别"
    )
    birthday: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="生日")
    phone: Mapped[str] = mapped_column(String(20), default="", comment="手机号")
    bio: Mapped[str] = mapped_column(String(255), default="", comment="个人简介")

    # ---------- 状态 ----------
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, comment="是否启用"
    )

    @property
    def display_name(self) -> str:
        """展示名：优先昵称，其次邮箱前缀。"""
        return self.nickname or self.email.split("@")[0]

    @property
    def age(self) -> Optional[int]:
        """根据生日推算年龄。"""
        if not self.birthday:
            return None
        today = date.today()
        return today.year - self.birthday.year - (
            (today.month, today.day) < (self.birthday.month, self.birthday.day)
        )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Member id={self.id} email={self.email!r}>"
