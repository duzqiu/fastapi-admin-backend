"""数据库引擎与会话管理。

对外暴露：
    - engine      : SQLAlchemy 引擎（全局单例）
    - SessionLocal: 会话工厂
    - get_db()    : FastAPI 依赖注入使用的会话生成器
"""

from pathlib import Path
from typing import Any, Dict, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.core.config import settings


def _prepare_sqlite_dir(database_url: str) -> None:
    """SQLite 使用文件存储时，确保父目录存在。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    db_path = database_url[len(prefix):]
    if db_path in (":memory:", ""):
        return
    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str | None = None, echo: bool | None = None):
    """根据 URL 构建引擎，自动适配不同数据库所需的连接参数。"""
    url = database_url or settings.DATABASE_URL
    _prepare_sqlite_dir(url)

    kwargs: Dict[str, Any] = {
        "echo": settings.SQL_ECHO if echo is None else echo,
        "future": True,
        "pool_pre_ping": True,
    }

    if url.startswith("sqlite"):
        # SQLite 需要允许跨线程使用（FastAPI 默认在线程池中执行同步依赖）
        kwargs["connect_args"] = {"check_same_thread": False}
        # 内存库必须复用同一个连接，文件库则无需连接池
        kwargs["poolclass"] = StaticPool if ":memory:" in url else NullPool
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_recycle"] = 3600

    return create_engine(url, **kwargs)


engine = build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个会话，请求结束后自动关闭。

    仓储层只 `flush` 不 `commit`，事务边界由服务层控制；
    若请求过程中出现异常，会话关闭时会自动回滚未提交的改动。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
