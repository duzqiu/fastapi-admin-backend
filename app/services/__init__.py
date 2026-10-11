"""服务层（业务逻辑层）。

约定：
- 承载全部业务规则与校验，是唯一允许开启/提交事务的层；
- 通过仓储访问数据，不直接编写 SQL；
- 抛出的异常必须是 app.core.exceptions 中的语义化异常。
"""

from app.services.auth_service import AuthService
from app.services.countdown_service import CountdownService
from app.services.dish_order_service import DishOrderService
from app.services.dish_service import DishService
from app.services.email_code_service import EmailCodeService
from app.services.member_auth_service import MemberAuthService
from app.services.member_service import MemberService
from app.services.system_service import SystemService
from app.services.user_service import UserService

__all__ = [
    "AuthService",
    "CountdownService",
    "DishOrderService",
    "DishService",
    "EmailCodeService",
    "MemberAuthService",
    "MemberService",
    "SystemService",
    "UserService",
]
