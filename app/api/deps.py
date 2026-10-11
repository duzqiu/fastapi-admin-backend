"""FastAPI 依赖注入。

集中管理：数据库会话、当前用户/会员、权限校验、分页参数、各服务实例。
接口层只声明依赖，不自己 new 对象，方便单元测试时整体替换。

令牌作用域隔离：
- 后台账号（users）   -> scope = staff
- 用户中心会员（members）-> scope = member
两者互不通用，会员令牌无法访问后台接口，反之亦然。
"""

from typing import Optional

from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import TOKEN_SCOPE_MEMBER, TOKEN_SCOPE_STAFF, TOKEN_TYPE_ACCESS, decode_token
from app.db.session import get_db
from app.models.member import Member
from app.models.user import User, UserRole
from app.services.auth_service import AuthService
from app.services.countdown_service import CountdownService
from app.services.dish_order_service import DishOrderService
from app.services.dish_service import DishService
from app.services.email_code_service import EmailCodeService
from app.services.member_auth_service import MemberAuthService
from app.services.member_service import MemberService
from app.services.system_service import SystemService
from app.services.user_service import UserService

# 后台账号登录入口（Swagger Authorize 按钮使用）
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/token",
    auto_error=False,
)

# 用户中心登录入口
member_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/member/auth/token",
    auto_error=False,
)


class PageParams:
    """统一分页参数。"""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码，从 1 开始"),
        page_size: int = Query(
            settings.DEFAULT_PAGE_SIZE,
            ge=1,
            le=settings.MAX_PAGE_SIZE,
            description="每页条数",
        ),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_client_ip(request: Request) -> str:
    """取真实客户端 IP（兼容 Nginx 反向代理）。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


# ------------------------- 服务依赖 -------------------------
def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(db)


def get_system_service(db: Session = Depends(get_db)) -> SystemService:
    return SystemService(db)


def get_member_auth_service(db: Session = Depends(get_db)) -> MemberAuthService:
    return MemberAuthService(db)


def get_member_service(db: Session = Depends(get_db)) -> MemberService:
    return MemberService(db)


def get_email_code_service(db: Session = Depends(get_db)) -> EmailCodeService:
    return EmailCodeService(db)


def get_dish_service(db: Session = Depends(get_db)) -> DishService:
    return DishService(db)


def get_dish_order_service(db: Session = Depends(get_db)) -> DishOrderService:
    return DishOrderService(db)


def get_countdown_service(db: Session = Depends(get_db)) -> CountdownService:
    return CountdownService(db)


# ------------------------- 后台账号认证 / 鉴权 -------------------------
def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer Token 并返回当前登录的后台账号。"""
    if not token:
        raise UnauthorizedError("未提供身份凭证，请先登录")

    payload = decode_token(
        token, expected_type=TOKEN_TYPE_ACCESS, expected_scope=TOKEN_SCOPE_STAFF
    )
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise UnauthorizedError("用户不存在或已被删除")
    if not user.is_active:
        raise UnauthorizedError("账号已被禁用，请联系管理员")
    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """要求后台管理员角色。"""
    if current_user.role != UserRole.ADMIN.value:
        raise ForbiddenError("需要管理员权限")
    return current_user


def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """可选登录：未登录时返回 None（用于公开但可个性化的接口）。"""
    if not token:
        return None
    try:
        return get_current_user(token=token, db=db)
    except UnauthorizedError:
        return None


# ------------------------- 用户中心（会员）认证 -------------------------
def get_current_member(
    token: Optional[str] = Depends(member_oauth2_scheme),
    db: Session = Depends(get_db),
) -> Member:
    """解析 Bearer Token 并返回当前登录会员。"""
    if not token:
        raise UnauthorizedError("未提供身份凭证，请先登录")

    payload = decode_token(
        token, expected_type=TOKEN_TYPE_ACCESS, expected_scope=TOKEN_SCOPE_MEMBER
    )
    member = db.get(Member, int(payload["sub"]))
    if member is None:
        raise UnauthorizedError("会员不存在或已被删除")
    if not member.is_active:
        raise UnauthorizedError("账号已被禁用，请联系客服")
    return member


def get_optional_member(
    token: Optional[str] = Depends(member_oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[Member]:
    """可选会员登录：扫码点菜等场景允许匿名下单。"""
    if not token:
        return None
    try:
        return get_current_member(token=token, db=db)
    except UnauthorizedError:
        return None
