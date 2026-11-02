"""接口层（Controller）：只做参数接收、依赖声明与响应组装。"""

from app.api.v1.endpoints import (
    auth,
    member_auth,
    member_profile,
    members,
    official_articles,
    resume,
    resume_public,
    system,
    users,
)

__all__ = [
    "auth",
    "member_auth",
    "member_profile",
    "members",
    "official_articles",
    "resume",
    "resume_public",
    "system",
    "users",
]
