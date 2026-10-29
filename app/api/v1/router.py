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
    member_public,
    members,
    menu,
    messages,
    official_articles,
    posts,
    resume,
    resume_public,
    site,
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

# 用户中心（会员）- 对外公开资料（帖子作者主页用，无需登录）
api_router.include_router(member_public.router)

# 点菜菜单（C 端）
api_router.include_router(menu.router)

# 后台业务
api_router.include_router(members.router)
api_router.include_router(dishes.router)
api_router.include_router(dishes.category_router)
api_router.include_router(dishes.tag_router)
api_router.include_router(dish_orders.router)

# 文章管理（用户发帖 + 后台审核）
api_router.include_router(posts.public_router)
api_router.include_router(posts.router)
api_router.include_router(posts.comment_router)
api_router.include_router(official_articles.public_router)
api_router.include_router(official_articles.router)
api_router.include_router(messages.router)

# 代办事项
api_router.include_router(countdowns.router)

# 个人网站-简历信息（独立类目：六组接口自成一体，不与其它域关联；组内按个人信息 / 公司经历分层绑定）
api_router.include_router(resume.personal_router)
api_router.include_router(resume.education_router)
api_router.include_router(resume.work_router)
api_router.include_router(resume.project_router)
api_router.include_router(resume.evaluation_router)
api_router.include_router(resume.skill_tag_router)

# 个人网站-简历信息对外接口（前台展示端用：无需登录、只出启用数据）
api_router.include_router(resume_public.router)

# 个人网站设置（欢迎语 / 关于我密码）
api_router.include_router(site.router)
api_router.include_router(site.admin_router)

api_router.include_router(system.router)
