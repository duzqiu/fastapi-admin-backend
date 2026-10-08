"""认证接口。"""

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import get_auth_service, get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, Token
from app.schemas.common import MessageResponse
from app.schemas.user import PasswordChange, UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=Token, summary="账号密码登录")
def login(payload: LoginRequest, service: AuthService = Depends(get_auth_service)) -> Token:
    """JSON 方式登录，前端后台管理系统使用此接口。"""
    return Token(**service.login(payload.username, payload.password))


@router.post("/token", response_model=Token, summary="OAuth2 表单登录（Swagger 调试用）")
def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
) -> Token:
    """标准 OAuth2 密码模式，供 Swagger UI 的 Authorize 按钮调用。"""
    return Token(**service.login(form_data.username, form_data.password))


@router.post("/refresh", response_model=Token, summary="刷新令牌")
def refresh(payload: RefreshRequest, service: AuthService = Depends(get_auth_service)) -> Token:
    """使用 refresh_token 换取新的令牌对。"""
    return Token(**service.refresh(payload.refresh_token))


@router.get("/me", response_model=UserOut, summary="获取当前登录用户")
def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password", response_model=MessageResponse, summary="修改当前用户密码")
def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    service.change_password(current_user, payload.old_password, payload.new_password)
    return MessageResponse(message="密码修改成功，请使用新密码重新登录")


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="退出登录",
)
def logout(_: User = Depends(get_current_user)) -> MessageResponse:
    """无状态 JWT：服务端仅做形式上的登出，前端清除本地令牌即可。"""
    return MessageResponse(message="已退出登录")
