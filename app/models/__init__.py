"""ORM 模型层。

新增模型后必须在此导出，否则 `Base.metadata` 中不会注册该表，
建表与迁移都不会生效。
"""

from app.models.dish import Dish, DishCategory, DishSpec, DishStatus, DishTag, dish_tag_links
from app.models.dish_order import ORDER_TRANSITIONS, DishOrder, DishOrderItem, OrderStatus
from app.models.email_code import EmailCode, EmailScene
from app.models.member import Member, MemberGender
from app.models.user import User, UserRole

__all__ = [
    "Dish",
    "DishCategory",
    "DishSpec",
    "DishStatus",
    "DishTag",
    "dish_tag_links",
    "DishOrder",
    "DishOrderItem",
    "OrderStatus",
    "ORDER_TRANSITIONS",
    "EmailCode",
    "EmailScene",
    "Member",
    "MemberGender",
    "User",
    "UserRole",
]
