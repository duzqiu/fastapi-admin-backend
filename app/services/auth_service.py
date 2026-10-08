"""认证服务：登录、刷新令牌、修改密码。"""

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessError, UnauthorizedError
from app.core.security import (
    TOKEN_SCOPE_STAFF,
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.utils import utcnow
from app.models.user import User
from app.repositories.user_repository import UserRepository


class AuthService:
    """处理与身份认证相关的业务逻辑。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    # ------------------------- 内部工具 -------------------------
    @staticmethod
    def _issue_tokens(user: User) -> dict:
        # 后台账号令牌固定使用 staff 作用域，避免被前台会员令牌混用
        return {
            "access_token": create_access_token(
                user.id, extra={"username": user.username}, scope=TOKEN_SCOPE_STAFF
            ),
            "refresh_token": create_refresh_token(user.id, scope=TOKEN_SCOPE_STAFF),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    def _get_active_user(self, username: str) -> User:
        user = self.users.get_by_username(username)
        if user is None:
            # 不区分「用户不存在」与「密码错误」，避免账号枚举
            raise UnauthorizedError("用户名或密码错误")
        if not user.is_active:
            raise UnauthorizedError("账号已被禁用，请联系管理员")
        return user

    # ------------------------- 业务方法 -------------------------
    def login(self, username: str, password: str) -> dict:
        """账号密码登录，返回令牌。"""
        user = self._get_active_user(username)
        if not verify_password(password, user.hashed_password):
            raise UnauthorizedError("用户名或密码错误")

        user.last_login_at = utcnow()
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return self._issue_tokens(user)

    def refresh(self, refresh_token: str) -> dict:
        """用 refresh_token 换取新的令牌对。"""
        payload = decode_token(
            refresh_token,
            expected_type=TOKEN_TYPE_REFRESH,
            expected_scope=TOKEN_SCOPE_STAFF,
        )
        user = self.users.get(int(payload["sub"]))
        if user is None:
            raise UnauthorizedError("用户不存在")
        if not user.is_active:
            raise UnauthorizedError("账号已被禁用，请联系管理员")
        return self._issue_tokens(user)

    def change_password(self, user: User, old_password: str, new_password: str) -> None:
        """当前登录用户自助修改密码。"""
        if not verify_password(old_password, user.hashed_password):
            raise BusinessError("原密码不正确")
        if old_password == new_password:
            raise BusinessError("新密码不能与原密码相同")

        user.hashed_password = hash_password(new_password)
        self.db.add(user)
        self.db.commit()
