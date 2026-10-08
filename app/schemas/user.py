"""用户相关 Pydantic 模型（接口出入参定义）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole
from app.schemas.common import ORMBaseModel


class UserBase(BaseModel):
    """用户公共字段。"""

    username: str = Field(..., min_length=3, max_length=50, description="登录名")
    email: EmailStr = Field(..., description="邮箱")
    nickname: str = Field(default="", max_length=50, description="昵称")
    role: UserRole = Field(default=UserRole.USER, description="角色")
    is_active: bool = Field(default=True, description="是否启用")


class UserCreate(UserBase):
    """创建用户入参。"""

    password: str = Field(..., min_length=6, max_length=64, description="密码")

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if value.isdigit() or value.isalpha():
            raise ValueError("密码需要同时包含字母和数字")
        return value


class UserUpdate(BaseModel):
    """更新用户入参（全部可选，未传字段不修改）。"""

    email: Optional[EmailStr] = None
    nickname: Optional[str] = Field(default=None, max_length=50)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserStatusUpdate(BaseModel):
    """启用 / 禁用用户。"""

    is_active: bool = Field(..., description="是否启用")


class UserPasswordReset(BaseModel):
    """管理员重置密码。"""

    new_password: str = Field(..., min_length=6, max_length=64)


class PasswordChange(BaseModel):
    """用户自助修改密码。"""

    old_password: str = Field(..., min_length=6, max_length=64)
    new_password: str = Field(..., min_length=6, max_length=64)


class UserOut(ORMBaseModel):
    """用户出参（绝不返回密码哈希）。"""

    id: int
    username: str
    email: str
    nickname: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserSimple(ORMBaseModel):
    """用户精简信息。"""

    id: int
    username: str
    nickname: str
