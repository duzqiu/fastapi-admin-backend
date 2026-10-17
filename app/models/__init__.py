"""ORM 模型层。

新增模型后必须在此导出，否则 `Base.metadata` 中不会注册该表，
建表与迁移都不会生效。
"""

from app.models.countdown import COUNTDOWN_CYCLE_LABELS, Countdown, CountdownCycle
from app.models.dish import Dish, DishCategory, DishSpec, DishStatus, DishTag, dish_tag_links
from app.models.dish_order import ORDER_TRANSITIONS, DishOrder, DishOrderItem, OrderStatus
from app.models.email_code import EmailCode, EmailScene
from app.models.member import Member, MemberGender
from app.models.resume import (
    EDUCATION_DEGREE_LABELS,
    RESUME_GENDER_LABELS,
    SKILL_TAG_SEPARATOR,
    EducationDegree,
    ResumeEducation,
    ResumeEvaluation,
    ResumeGender,
    ResumePersonalInfo,
    ResumeProject,
    ResumeSkillTag,
    ResumeWork,
    join_skill_tags,
    split_skill_tags,
)
from app.models.user import User, UserRole

__all__ = [
    "Countdown",
    "CountdownCycle",
    "COUNTDOWN_CYCLE_LABELS",
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
    "ResumePersonalInfo",
    "ResumeEducation",
    "ResumeWork",
    "ResumeProject",
    "ResumeEvaluation",
    "ResumeSkillTag",
    "SKILL_TAG_SEPARATOR",
    "split_skill_tags",
    "join_skill_tags",
    "ResumeGender",
    "RESUME_GENDER_LABELS",
    "EducationDegree",
    "EDUCATION_DEGREE_LABELS",
    "User",
    "UserRole",
]
