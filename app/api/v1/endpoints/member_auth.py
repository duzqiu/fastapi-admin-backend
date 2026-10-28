"""用户中心（会员）认证接口：验证码、注册、登录、重置密码。

前缀 `/member/auth`，全部为公开接口。
"""

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import get_client_ip, get_current_member, get_member_auth_service
from app.models.member import Member
from app.schemas.auth import Token
from app.schemas.common import MessageResponse
from app.schemas.email import SendCodeRequest, SendCodeResponse
from app.schemas.member import (
    MemberCheckEmailRequest,
    MemberCheckEmailResponse,
    MemberLogin,
    MemberOut,
    MemberRefresh,
    MemberRegister,
    MemberResetPassword,
    MemberVerifyRegisterCode,
    MemberVerifyResetCode,
)
from app.services.member_auth_service import MemberAuthService

router = APIRouter(prefix="/member/auth", tags=["前端-用户中心-认证"])


@router.post(
    "/check-email", response_model=MemberCheckEmailResponse, summary="检查会员邮箱是否存在"
)
def check_email(
    payload: MemberCheckEmailRequest,
    service: MemberAuthService = Depends(get_member_auth_service),
) -> MemberCheckEmailResponse:
    """公开只读查询，仅返回邮箱是否已注册，不发送验证码。"""
    return MemberCheckEmailResponse(exists=service.check_email(str(payload.email)))


@router.post("/send-code", response_model=SendCodeResponse, summary="发送邮箱验证码")
def send_code(
    payload: SendCodeRequest,
    request: Request,
    service: MemberAuthService = Depends(get_member_auth_service),
) -> SendCodeResponse:
    """场景说明：

    - `register`：注册，要求邮箱未被注册
    - `reset_password`：重置密码，要求邮箱已注册

    未配置 SMTP（`MAIL_ENABLED=false`）时不会真实发信，验证码会写入服务端日志；
    开启 `EMAIL_CODE_DEBUG_RETURN` 且 DEBUG=true 时会在响应 `debug_code` 中回显，便于本地联调。
    """
    data = service.send_code(payload.email, payload.scene, get_client_ip(request))
    return SendCodeResponse(**data)


@router.post(
    "/register",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="邮箱验证码注册",
)
def register(
    payload: MemberRegister,
    request: Request,
    service: MemberAuthService = Depends(get_member_auth_service),
) -> Member:
    """注册成功后邮箱即视为已验证，并自动生成默认昵称、使用默认头像（均可在个人中心修改）。"""
    member = service.register(payload, get_client_ip(request))
    return member


@router.post("/login", response_model=Token, summary="邮箱密码登录")
def login(payload: MemberLogin, service: MemberAuthService = Depends(get_member_auth_service)) -> Token:
    """返回 `scope=member` 的令牌，仅能访问用户中心接口。"""
    return Token(**service.login(str(payload.email), payload.password))


@router.post("/token", response_model=Token, summary="OAuth2 表单登录（Swagger 调试用）")
def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    service: MemberAuthService = Depends(get_member_auth_service),
) -> Token:
    """username 字段填写注册邮箱。"""
    return Token(**service.login(form_data.username, form_data.password))


@router.post("/refresh", response_model=Token, summary="刷新会员令牌")
def refresh(payload: MemberRefresh, service: MemberAuthService = Depends(get_member_auth_service)) -> Token:
    return Token(**service.refresh(payload.refresh_token))


@router.post(
    "/verify-register-code", response_model=MessageResponse, summary="验证注册邮箱验证码"
)
def verify_register_code(
    payload: MemberVerifyRegisterCode,
    service: MemberAuthService = Depends(get_member_auth_service),
) -> MessageResponse:
    """仅验证注册验证码，不消耗验证码；注册时仍需提交邮箱、验证码和密码。"""
    service.verify_register_code(str(payload.email), payload.code)
    return MessageResponse(message="验证码验证成功")


@router.post(
    "/verify-reset-code", response_model=MessageResponse, summary="验证重置密码验证码"
)
def verify_reset_code(
    payload: MemberVerifyResetCode,
    service: MemberAuthService = Depends(get_member_auth_service),
) -> MessageResponse:
    """仅验证验证码，不消耗验证码；重置密码时仍需提交邮箱、验证码和新密码。"""
    service.verify_reset_code(str(payload.email), payload.code)
    return MessageResponse(message="验证码验证成功")


@router.post("/reset-password", response_model=MessageResponse, summary="忘记密码（验证码重置）")
def reset_password(
    payload: MemberResetPassword,
    service: MemberAuthService = Depends(get_member_auth_service),
) -> MessageResponse:
    """入参 `confirm_password` 需与 `new_password` 一致。"""
    service.reset_password(payload)
    return MessageResponse(message="密码重置成功，请使用新密码登录")


@router.get("/me", response_model=MemberOut, summary="获取当前登录会员")
def read_me(current_member: Member = Depends(get_current_member)) -> Member:
    return current_member


@router.post("/logout", response_model=MessageResponse, summary="退出登录")
def logout(_: Member = Depends(get_current_member)) -> MessageResponse:
    """无状态 JWT：客户端清除本地令牌即可。"""
    return MessageResponse(message="已退出登录")
