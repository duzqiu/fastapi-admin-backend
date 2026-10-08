"""Alembic 运行环境。

设计要点：
- 数据库连接串复用项目配置（settings.DATABASE_URL），避免两处维护；
- target_metadata 指向项目 Base.metadata，实现自动比对 ORM 与数据库结构；
- 支持离线（--sql）与在线两种迁移模式。
"""

import sys
from logging.config import dictConfig
from pathlib import Path

from alembic import context

# 把项目根目录加入 sys.path，保证可以 import app.*
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import build_engine  # noqa: E402
from app.models import Article, User  # noqa: F401,E402  确保模型都已注册

config = context.config
target_metadata = Base.metadata

dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"}
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "default"},
        },
        "root": {"handlers": ["console"], "level": "INFO"},
    }
)


def get_url() -> str:
    """优先级：-x db_url 参数 > 项目配置。"""
    return context.get_x_argument(as_dictionary=True).get("db_url") or settings.DATABASE_URL


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连接数据库。"""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=get_url().startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接对数据库执行迁移。"""
    engine = build_engine(get_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite 不支持 ALTER COLUMN，需要 batch 模式改写表
            render_as_batch=get_url().startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
