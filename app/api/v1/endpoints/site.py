"""个人网站设置接口。

- 公开：首页欢迎语、关于我密码校验
- 后台：读取 / 修改欢迎语、设置关于我密码
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin, get_site_service
from app.core.exceptions import BusinessError
from app.schemas.site import (
    AboutPasswordStatusOut,
    AboutPasswordUpdate,
    AboutPasswordVerifyIn,
    AboutPasswordVerifyOut,
    SiteWelcomeOut,
    SiteWelcomeUpdate,
)
from app.services.site_service import SiteService

router = APIRouter(prefix="/site", tags=["前端-个人网站设置"])
admin_router = APIRouter(
    prefix="/site/admin",
    tags=["后台-个人网站-站点设置"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/welcome", response_model=SiteWelcomeOut, summary="首页欢迎语")
def public_welcome(service: SiteService = Depends(get_site_service)) -> SiteWelcomeOut:
    return service.get_welcome()


@router.post(
    "/about/verify",
    response_model=AboutPasswordVerifyOut,
    summary="校验「关于我」访问密码",
)
def verify_about_password(
    payload: AboutPasswordVerifyIn,
    service: SiteService = Depends(get_site_service),
) -> AboutPasswordVerifyOut:
    if not service.verify_about_password(payload.password):
        raise BusinessError("密码不正确")
    return AboutPasswordVerifyOut(ok=True, message="密码正确")


@admin_router.get(
    "/welcome",
    response_model=SiteWelcomeOut,
    summary="读取首页欢迎语",
)
def get_welcome(service: SiteService = Depends(get_site_service)) -> SiteWelcomeOut:
    return service.get_welcome()


@admin_router.put(
    "/welcome",
    response_model=SiteWelcomeOut,
    summary="更新首页欢迎语",
)
def update_welcome(
    payload: SiteWelcomeUpdate,
    service: SiteService = Depends(get_site_service),
) -> SiteWelcomeOut:
    return service.update_welcome(payload)


@admin_router.get(
    "/about-password",
    response_model=AboutPasswordStatusOut,
    summary="查看关于我密码状态",
)
def get_about_password_status(
    service: SiteService = Depends(get_site_service),
) -> AboutPasswordStatusOut:
    return AboutPasswordStatusOut(configured=service.about_password_configured())


@admin_router.put(
    "/about-password",
    response_model=AboutPasswordVerifyOut,
    summary="设置关于我访问密码",
)
def update_about_password(
    payload: AboutPasswordUpdate,
    service: SiteService = Depends(get_site_service),
) -> AboutPasswordVerifyOut:
    service.update_about_password(payload.password)
    return AboutPasswordVerifyOut(ok=True, message="密码已更新")


__all__ = ["router", "admin_router"]
