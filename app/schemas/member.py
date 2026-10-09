"""用户中心（会员）相关 Pydantic 模型。"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.member import MemberGender
from app.schemas.common import ORMBaseModel

# 密码强度：6-64 位且同时包含字母和数字
PASSWORD_MIN = 6
PASSWORD_MAX = 64


def _validate_password(value: str) -> str:
    if len(value) < PASSWORD_MIN or len(value) > PASSWORD_MAX:
        raise ValueError(f"密码长度需为 {PASSWORD_MIN}-{PASSWORD_MAX} 位")
    if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
        raise ValueError("密码需同时包含字母和数字")
    return value


def _validate_password_match(password: str, confirm_password: str) -> None:
    """校验「密码」与「确认密码」一致（用于注册、重置密码等场景）。"""
    if password != confirm_password:
        raise ValueError("两次输入的密码不一致")


# ==================== 认证相关 ====================
class MemberRegister(BaseModel):
    """会员注册入参（邮箱验证码方式）。

    注册成功后系统自动生成默认昵称与默认头像，可在个人中心自行修改。
    """

    email: EmailStr = Field(..., description="注册邮箱")
    code: str = Field(..., min_length=4, max_length=10, description="邮箱验证码")
    password: str = Field(..., min_length=PASSWORD_MIN, max_length=PASSWORD_MAX, description="密码")
    confirm_password: str = Field(
        ..., min_length=PASSWORD_MIN, max_length=PASSWORD_MAX, description="确认密码，需与密码一致"
    )

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return _validate_password(value)

    @model_validator(mode="after")
    def check_password_match(self) -> "MemberRegister":
        _validate_password_match(self.password, self.confirm_password)
        return self


class MemberLogin(BaseModel):
    """会员登录入参。"""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX)


class MemberResetPassword(BaseModel):
    """通过邮箱验证码重置密码。"""

    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    confirm_password: str = Field(
        ..., min_length=PASSWORD_MIN, max_length=PASSWORD_MAX, description="确认密码，需与新密码一致"
    )

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return _validate_password(value)

    @model_validator(mode="after")
    def check_password_match(self) -> "MemberResetPassword":
        _validate_password_match(self.new_password, self.confirm_password)
        return self


class MemberChangePassword(BaseModel):
    """登录状态下修改密码：邮箱验证码 + 新密码 + 确认密码。

    验证码由 `POST /member/send-code` 发送到当前登录账号的邮箱。
    """

    code: str = Field(..., min_length=4, max_length=10, description="邮箱验证码")
    new_password: str = Field(..., min_length=PASSWORD_MIN, max_length=PASSWORD_MAX, description="新密码")
    confirm_password: str = Field(
        ..., min_length=PASSWORD_MIN, max_length=PASSWORD_MAX, description="确认密码，需与新密码一致"
    )

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return _validate_password(value)

    @model_validator(mode="after")
    def check_password_match(self) -> "MemberChangePassword":
        _validate_password_match(self.new_password, self.confirm_password)
        return self


class MemberRefresh(BaseModel):
    """刷新会员令牌。"""

    refresh_token: str


# ==================== 资料相关 ====================
class MemberProfileUpdate(BaseModel):
    """会员自助修改资料（全部可选）。"""

    nickname: Optional[str] = Field(default=None, min_length=1, max_length=50)
    avatar: Optional[str] = Field(default=None, max_length=255)
    gender: Optional[MemberGender] = None
    birthday: Optional[date] = None
    phone: Optional[str] = Field(default=None, max_length=20)
    bio: Optional[str] = Field(default=None, max_length=255)

    @field_validator("birthday")
    @classmethod
    def check_birthday(cls, value: Optional[date]) -> Optional[date]:
        if value is None:
            return value
        if value > date.today():
            raise ValueError("生日不能晚于今天")
        if value.year < 1900:
            raise ValueError("生日不合法")
        return value

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return value
        cleaned = value.strip()
        if not cleaned.replace("-", "").replace("+", "").isdigit():
            raise ValueError("手机号只能包含数字")
        return cleaned


class MemberAdminUpdate(MemberProfileUpdate):
    """后台管理员修改会员资料（额外支持启用/禁用）。"""

    is_active: Optional[bool] = None


class MemberPasswordReset(BaseModel):
    """后台管理员重置会员密码。"""

    new_password: str = Field(..., min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return _validate_password(value)


class MemberStatusUpdate(BaseModel):
    """启用 / 禁用会员。"""

    is_active: bool


# ==================== 出参 ====================
class MemberOut(ORMBaseModel):
    """会员详情出参（绝不返回密码哈希）。"""

    id: int
    member_no: str = Field(default="", description="会员编号（注册时随机生成的 6 位唯一 ID）")
    email: str
    nickname: str
    display_name: str = ""
    avatar: str
    gender: str
    birthday: Optional[date] = None
    age: Optional[int] = None
    phone: str
    bio: str
    is_active: bool
    email_verified: bool
    email_verified_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MemberListItem(ORMBaseModel):
    """会员列表项。"""

    id: int
    member_no: str = ""
    email: str
    nickname: str
    display_name: str = ""
    avatar: str
    gender: str
    birthday: Optional[date] = None
    is_active: bool
    email_verified: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


class MemberStatsOut(BaseModel):
    """会员统计。"""

    total: int = 0
    active: int = 0
    disabled: int = 0
    verified: int = 0
    new_in_7_days: int = 0
    gender_distribution: dict = Field(default_factory=dict)


class AvatarUploadOut(BaseModel):
    """头像上传结果。"""

    url: str = Field(..., description="可直接访问的头像地址")
    filename: str
    size: int = Field(..., description="文件大小（字节）")
