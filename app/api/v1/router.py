"""v1 版本路由聚合器。"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    countdowns,
    dish_orders,
    dishes,
    member_auth,
    member_countdowns,
    member_profile,
    members,
    menu,
    system,
    users,
)

api_router = APIRouter()

# 后台账号
api_router.include_router(auth.router)
api_router.include_router(users.router)

# 用户中心（会员）
api_router.include_router(member_auth.router)
api_router.include_router(member_profile.router)
api_router.include_router(member_countdowns.router)

# 点菜菜单（C 端）
api_router.include_router(menu.router)

# 后台业务
api_router.include_router(members.router)
api_router.include_router(dishes.router)
api_router.include_router(dishes.category_router)
api_router.include_router(dishes.tag_router)
api_router.include_router(dish_orders.router)

# 代办事项
api_router.include_router(countdowns.router)

api_router.include_router(system.router)
