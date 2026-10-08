"""ORM 模型公共 Mixin。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import utcnow


class PKMixin:
    """自增主键。"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")


class TimestampMixin:
    """创建时间 / 更新时间。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False, comment="更新时间"
    )
