"""个人网站设置相关 Pydantic 模型。"""

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


class AboutPasswordUpdate(BaseModel):
    password: str = Field(
        ...,
        min_length=4,
        max_length=64,
        description="新密码，4-64 个字符，支持中文",
    )

    @field_validator("password")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("密码不能为空")
        return value


__all__ = [
    "SiteWelcomeOut",
    "SiteWelcomeUpdate",
    "AboutPasswordVerifyIn",
    "AboutPasswordVerifyOut",
    "AboutPasswordStatusOut",
    "AboutPasswordUpdate",
]
