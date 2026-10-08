"""认证相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """JSON 方式登录入参（同时兼容 OAuth2 表单方式）。"""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=64)


class Token(BaseModel):
    """令牌响应。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="access_token 有效期（秒）")


class RefreshRequest(BaseModel):
    """刷新令牌入参。"""

    refresh_token: str
