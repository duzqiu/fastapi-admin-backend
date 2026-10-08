"""安全模块：密码哈希与 JWT 令牌。

只依赖 bcrypt 与 PyJWT，不引入 passlib（避免 Python 3.13 的 `crypt` 兼容问题）。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.utils import utcnow

# bcrypt 只处理前 72 字节，超长密码需要先截断
_BCRYPT_MAX_BYTES = 72

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# 令牌作用域：后台账号与前台会员使用两套互不通用的令牌
TOKEN_SCOPE_STAFF = "staff"
TOKEN_SCOPE_MEMBER = "member"


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """生成密码哈希。"""
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(_encode(plain_password), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _create_token(
    subject: str | int,
    token_type: str,
    expires_minutes: int,
    scope: str = TOKEN_SCOPE_STAFF,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    now = utcnow()
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(
    subject: str | int,
    extra: Optional[Dict[str, Any]] = None,
    scope: str = TOKEN_SCOPE_STAFF,
) -> str:
    return _create_token(
        subject, TOKEN_TYPE_ACCESS, settings.ACCESS_TOKEN_EXPIRE_MINUTES, scope, extra
    )


def create_refresh_token(subject: str | int, scope: str = TOKEN_SCOPE_STAFF) -> str:
    return _create_token(
        subject, TOKEN_TYPE_REFRESH, settings.REFRESH_TOKEN_EXPIRE_MINUTES, scope
    )


def decode_token(
    token: str,
    expected_type: Optional[str] = None,
    expected_scope: Optional[str] = None,
) -> Dict[str, Any]:
    """解析并校验 JWT，失败时抛出 401 业务异常。"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("登录状态已过期，请重新登录", code=40101) from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("无效的身份凭证", code=40102) from exc

    if expected_type and payload.get("type") != expected_type:
        raise UnauthorizedError("令牌类型不正确", code=40103)
    if expected_scope and payload.get("scope") != expected_scope:
        raise UnauthorizedError("令牌使用范围不正确", code=40104)
    return payload
