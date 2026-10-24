"""用户中心注册用户 ORM 模型。

表名规范：`一级功能_二级功能_功能`
    member_account_info         ->  用户中心_账号_信息（本模型）
    member_account_email_code   ->  用户中心_账号_邮箱验证码
    system_auth_admin_user      ->  系统_认证_后台账号（见 app/models/user.py）

为什么要拆成两张表：后台账号与用户中心注册用户的字段、生命周期、令牌作用域
完全不同，分开建模可避免用户中心令牌越权访问后台接口。
"""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
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

    __tablename__ = "member_account_info"
    __table_args__ = (
        Index("ix_member_account_info_active_created", "is_active", "created_at"),
    )

    # ---------- 注册与登录 ----------
    member_no: Mapped[str] = mapped_column(
        String(10),
        unique=True,
        index=True,
        nullable=False,
        # 新注册是 10 位；历史数据仍是 6 位，保持原样不再改写
        comment="会员编号（注册时随机生成的 10 位唯一 ID）",
    )
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
    background: Mapped[str] = mapped_column(String(255), default="", comment="背景图地址")
    gender: Mapped[str] = mapped_column(
        String(10), default=MemberGender.UNKNOWN.value, index=True, comment="性别"
    )
    birthday: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="生日")
    phone: Mapped[str] = mapped_column(String(20), default="", comment="手机号")
    bio: Mapped[str] = mapped_column(String(255), default="", comment="个人简介")
    region: Mapped[str] = mapped_column(String(64), default="", comment="地区")

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


class MemberFollow(PKMixin, TimestampMixin, Base):
    """会员之间的关注关系：`关注者 × 被关注者`。

    表名：`member_account_follow`
    同一对会员只会有一条记录（重复关注幂等）；不能关注自己（服务层拦截）。
    """

    __tablename__ = "member_account_follow"
    __table_args__ = (
        UniqueConstraint(
            "follower_id",
            "following_id",
            name="uq_member_account_follow_follower_following",
        ),
        Index("ix_member_account_follow_follower_created", "follower_id", "created_at"),
        Index(
            "ix_member_account_follow_following_created", "following_id", "created_at"
        ),
    )

    follower_id: Mapped[int] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关注发起人（会员）",
    )
    following_id: Mapped[int] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="被关注的人（会员）",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<MemberFollow {self.follower_id}->{self.following_id}>"
