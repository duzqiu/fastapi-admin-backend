"""倒数日 ORM 模型。

表名规范：`一级功能_二级功能_功能`
    countdown_base_info  ->  倒数日_基础_信息

周期说明：
- 一次性（once）：以 target_date 为准，过期后剩余天数为负；
- 周期性（每天/每周/每月/每年）：按 target_date 推算「下一次到达的日期」，
  剩余天数永远 >= 0，到达当天为 0。
"""

import enum
from datetime import date, timedelta
from typing import Dict

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import local_today
from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class CountdownCycle(str, enum.Enum):
    """倒数日重复周期。"""

    ONCE = "once"  # 一次性
    DAILY = "daily"  # 每天
    WEEKLY = "weekly"  # 每周
    MONTHLY = "monthly"  # 每月
    YEARLY = "yearly"  # 每年


#: 周期取值 -> 中文文案（接口出参的 cycle_text 与前端下拉共用）
COUNTDOWN_CYCLE_LABELS: Dict[str, str] = {
    CountdownCycle.ONCE.value: "一次性",
    CountdownCycle.DAILY.value: "每天",
    CountdownCycle.WEEKLY.value: "每周",
    CountdownCycle.MONTHLY.value: "每月",
    CountdownCycle.YEARLY.value: "每年",
}


def _days_in_month(year: int, month: int) -> int:
    """返回指定年月的天数（处理 2 月与大小月）。"""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _safe_date(year: int, month: int, day: int) -> date:
    """构造日期，目标日在该月不存在时回退到当月最后一天（如 2 月 29 日落在平年）。"""
    return date(year, month, min(day, _days_in_month(year, month)))


class Countdown(PKMixin, TimestampMixin, Base):
    """倒数日表：一条代办事项的目标日期与重复周期。"""

    __tablename__ = "countdown_base_info"
    __table_args__ = (Index("ix_countdown_base_info_active_date", "is_active", "target_date"),)

    member_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属用户（用户中心会员，非后台账号）",
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="倒数日事项")
    cycle: Mapped[str] = mapped_column(
        String(20), default=CountdownCycle.ONCE.value, index=True, comment="重复周期"
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="目标日期")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, comment="是否有效")
    remark: Mapped[str] = mapped_column(String(500), default="", comment="备注")

    # ------------------------- 派生属性（不落库） -------------------------
    @property
    def next_date(self) -> date:
        """下一次到达的日期：按周期从 target_date 推算。"""
        today = local_today()

        if self.cycle == CountdownCycle.DAILY.value:
            return today

        if self.cycle == CountdownCycle.WEEKLY.value:
            # 目标日已过去时，取下一个同星期几（负数取模在 Python 中仍为正）
            gap = (self.target_date - today).days
            return today + timedelta(days=gap % 7)

        if self.cycle == CountdownCycle.MONTHLY.value:
            current = _safe_date(today.year, today.month, self.target_date.day)
            if current < today:
                year = today.year + today.month // 12
                month = today.month % 12 + 1
                current = _safe_date(year, month, self.target_date.day)
            return current

        if self.cycle == CountdownCycle.YEARLY.value:
            day = self.target_date.day
            current = _safe_date(today.year, self.target_date.month, day)
            if current < today:
                current = _safe_date(today.year + 1, self.target_date.month, day)
            return current

        return self.target_date

    @property
    def days_left(self) -> int:
        """距离下一次到达还剩几天；一次性事项过期后为负数。"""
        return (self.next_date - local_today()).days

    @property
    def cycle_text(self) -> str:
        """周期中文文案。"""
        return COUNTDOWN_CYCLE_LABELS.get(self.cycle, self.cycle)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Countdown id={self.id} title={self.title!r} target={self.target_date}>"


__all__ = ["Countdown", "CountdownCycle", "COUNTDOWN_CYCLE_LABELS"]
