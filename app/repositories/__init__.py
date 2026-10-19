"""仓储层（数据访问层 / DAO）。

约定：
- 只包含与数据库交互的代码，不出现业务判断；
- 只 flush 不 commit，事务由服务层统一提交；
- 服务层不得直接使用 SQLAlchemy 语句，必须通过仓储访问数据。
"""

from app.repositories.base import BaseRepository
from app.repositories.countdown_repository import CountdownRepository
from app.repositories.dish_order_repository import DishOrderRepository
from app.repositories.dish_repository import (
    DishCategoryRepository,
    DishRepository,
    DishSpecRepository,
    DishTagRepository,
)
from app.repositories.email_code_repository import EmailCodeRepository
from app.repositories.member_repository import MemberRepository
from app.repositories.post_repository import PostRepository
from app.repositories.resume_repository import (
    ResumeEducationRepository,
    ResumeEvaluationRepository,
    ResumePersonalInfoRepository,
    ResumeProjectRepository,
    ResumeWorkRepository,
)
from app.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "CountdownRepository",
    "DishCategoryRepository",
    "DishOrderRepository",
    "DishRepository",
    "DishSpecRepository",
    "DishTagRepository",
    "EmailCodeRepository",
    "MemberRepository",
    "PostRepository",
    "ResumePersonalInfoRepository",
    "ResumeEducationRepository",
    "ResumeWorkRepository",
    "ResumeProjectRepository",
    "ResumeEvaluationRepository",
    "UserRepository",
]
