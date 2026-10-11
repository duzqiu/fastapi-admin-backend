"""系统相关接口：健康检查、运行信息、后台首页统计。"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin, get_current_user, get_system_service
from app.models.user import User
from app.schemas.system import DashboardStatsOut, HealthOut, SystemInfoOut
from app.services.system_service import SystemService

router = APIRouter(prefix="/system", tags=["后台-仪表盘-统计与系统信息"])


@router.get("/health", response_model=HealthOut, summary="健康检查（无需登录）")
def health(service: SystemService = Depends(get_system_service)) -> HealthOut:
    data = service.health()
    return HealthOut(status=data["status"], version=data["version"])


@router.get("/info", response_model=SystemInfoOut, summary="系统运行信息")
def info(
    service: SystemService = Depends(get_system_service),
    _=Depends(get_current_admin),
) -> SystemInfoOut:
    return SystemInfoOut(**service.info())


@router.get("/dashboard", response_model=DashboardStatsOut, summary="后台首页统计数据")
def dashboard(
    service: SystemService = Depends(get_system_service),
    _: User = Depends(get_current_user),
) -> DashboardStatsOut:
    """所有已登录用户都可以看统计概览，仅「系统信息」限制为管理员。"""
    return DashboardStatsOut(**service.dashboard())
