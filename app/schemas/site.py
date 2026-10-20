"""个人网站设置相关 Pydantic 模型。"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SiteWelcomeOut(BaseModel):
    title: str = Field(..., description="首页主标题")
    subtitle: str = Field(..., description="首页副标题")
    blessing: str = Field(..., description="品牌名下方的祝福语")


class SiteWelcomeUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    subtitle: str = Field(..., min_length=1, max_length=300)
    blessing: str = Field(default="", max_length=300)

    @field_validator("title", "subtitle")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("blessing")
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return (value or "").strip()


class AboutPasswordVerifyIn(BaseModel):
    password: str = Field(..., min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("密码不能为空")
        return value


class AboutPasswordVerifyOut(BaseModel):
    ok: bool = True
    message: str = "密码正确"


class AboutPasswordStatusOut(BaseModel):
    configured: bool = Field(..., description="是否已经设置访问密码")
    enabled: bool = Field(..., description="是否启用访问密码")
    password: str = Field(default="", description="当前密码明文，仅后台回显用")


class AboutAccessOut(BaseModel):
    password_enabled: bool = Field(..., description="关于我是否需要密码")


class AboutPasswordUpdate(BaseModel):
    enabled: bool = Field(default=True, description="是否启用访问密码")
    password: Optional[str] = Field(
        default=None,
        min_length=4,
        max_length=64,
        description="新密码，4-64 个字符，支持中文；不传表示保持原密码",
    )

    @field_validator("password", mode="before")
    @classmethod
    def _empty_to_none(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


__all__ = [
    "SiteWelcomeOut",
    "SiteWelcomeUpdate",
    "AboutPasswordVerifyIn",
    "AboutPasswordVerifyOut",
    "AboutPasswordStatusOut",
    "AboutAccessOut",
    "AboutPasswordUpdate",
]
