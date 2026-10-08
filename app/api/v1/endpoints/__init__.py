"""接口层（Controller）：只做参数接收、依赖声明与响应组装。"""

from app.api.v1.endpoints import (
    articles,
    auth,
    dish_orders,
    dishes,
    member_auth,
    member_profile,
    members,
    menu,
    system,
    users,
)

__all__ = [
    "articles",
    "auth",
    "dish_orders",
    "dishes",
    "member_auth",
    "member_profile",
    "members",
    "menu",
    "system",
    "users",
]
