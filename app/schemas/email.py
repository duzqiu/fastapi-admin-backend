"""邮箱验证码相关 Pydantic 模型。"""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.email_code import EmailScene


class SendCodeRequest(BaseModel):
    """发送邮箱验证码入参。"""

    email: EmailStr = Field(..., description="目标邮箱")
    scene: EmailScene = Field(
        default=EmailScene.REGISTER, description="场景：register / reset_password"
    )


class SendCodeResponse(BaseModel):
    """发送结果。

    未配置 SMTP 时 `sent` 为 false，验证码不会真实发出；
    开启 `EMAIL_CODE_DEBUG_RETURN`（默认）且 DEBUG=true 时，
    `debug_code` 会直接回显验证码，便于本地联调。
    """

    email: str
    scene: str
    sent: bool = Field(..., description="邮件是否真实投递成功")
    expires_in: int = Field(..., description="有效期（秒）")
    resend_after: int = Field(..., description="多少秒后可重新发送")
    debug_code: Optional[str] = Field(default=None, description="仅本地调试时回显")
