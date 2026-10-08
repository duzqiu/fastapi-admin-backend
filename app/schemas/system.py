"""系统信息相关 Pydantic 模型。"""

from typing import Dict

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    """健康检查响应。"""

    status: str = Field(default="ok", description="服务状态")
    version: str = Field(..., description="应用版本")


class SystemInfoOut(BaseModel):
    """系统运行信息。"""

    project_name: str
    version: str
    debug: bool
    database_dialect: str
    database_url_masked: str
    python_version: str
    stats: Dict[str, int] = Field(default_factory=dict, description="各表数据量")


class DashboardStatsOut(BaseModel):
    """后台首页统计卡片数据。"""

    # 后台账号
    user_total: int = 0
    user_active: int = 0
    # 用户中心会员
    member_total: int = 0
    member_active: int = 0
    member_disabled: int = 0
    member_new_7_days: int = 0

    recent_members: list = Field(default_factory=list, description="最近注册的会员")
