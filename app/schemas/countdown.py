"""倒数日相关 Pydantic 模型（接口出入参定义）。"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.countdown import CountdownCycle
from app.schemas.common import ORMBaseModel


class CountdownCreate(BaseModel):
    """创建倒数日入参。"""

    member_id: int = Field(..., description="归属用户 ID（用户中心会员）")
    title: str = Field(..., min_length=1, max_length=100, description="倒数日事项")
    cycle: CountdownCycle = Field(default=CountdownCycle.ONCE, description="重复周期")
    target_date: date = Field(..., description="目标日期")
    is_active: bool = Field(default=True, description="是否有效")
    remark: str = Field(default="", max_length=500, description="备注")


class CountdownUpdate(BaseModel):
    """更新倒数日入参（全部可选，未传字段不修改）。"""

    member_id: Optional[int] = Field(default=None, description="归属用户 ID（用户中心会员）")
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    cycle: Optional[CountdownCycle] = Field(default=None, description="重复周期")
    target_date: Optional[date] = Field(default=None, description="目标日期")
    is_active: Optional[bool] = Field(default=None, description="是否有效")
    remark: Optional[str] = Field(default=None, max_length=500)


class CountdownStatusUpdate(BaseModel):
    """启用 / 停用倒数日。"""

    is_active: bool = Field(..., description="是否有效")


class CountdownOut(ORMBaseModel):
    """倒数日出参。"""

    id: int
    member_id: int
    member_no: str = Field(default="", description="归属用户的用户ID（会员编号）")
    member_name: str = Field(default="", description="归属用户（昵称，无昵称时为邮箱前缀）")
    title: str
    cycle: str
    cycle_text: str = Field(default="", description="周期中文文案")
    target_date: date
    next_date: date = Field(..., description="周期内倒数日当天（按周期推算的下一次到达日期）")
    lunar_text: str = Field(default="", description="倒数日当天的农历，如 四月十五")
    lunar_festival: str = Field(default="", description="倒数日当天的节气或农历节日，无则为空")
    is_active: bool
    remark: str = ""
    days_left: int = Field(default=0, description="剩余天数，负数为已过期")
    created_at: datetime
    updated_at: datetime


class CountdownStatsOut(BaseModel):
    """倒数日概览统计。"""

    total: int = Field(default=0, description="倒数日总数")
    active: int = Field(default=0, description="有效数量")
    inactive: int = Field(default=0, description="已停用数量")


class CountdownSelfCreate(BaseModel):
    """会员新增自己的倒数日入参。

    不含 member_id：归属用户固定取当前登录会员，防止越权给他人建数据。
    """

    title: str = Field(..., min_length=1, max_length=100, description="倒数日事项")
    cycle: CountdownCycle = Field(default=CountdownCycle.ONCE, description="重复周期")
    target_date: date = Field(..., description="目标日期")
    is_active: bool = Field(default=True, description="是否有效")
    remark: str = Field(default="", max_length=500, description="备注")


class CountdownSelfUpdate(BaseModel):
    """会员修改自己的倒数日入参（全部可选，且不能修改归属用户）。"""

    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    cycle: Optional[CountdownCycle] = Field(default=None)
    target_date: Optional[date] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
    remark: Optional[str] = Field(default=None, max_length=500)
