"""SQLAlchemy 声明式基类。

所有 ORM 模型都继承 `Base`，Alembic 自动生成迁移脚本时依赖 `Base.metadata`。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全局唯一的声明式基类。"""

    pass
