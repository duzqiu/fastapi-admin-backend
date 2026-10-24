"""启动时的「补列」同步：把 ORM 里已定义、而库里还没有的列补出来。

**为什么需要它**：`Base.metadata.create_all()` **只建表、不改表** —— 老库升级到新代码后，
模型里新增的列不会自动补上，一查就报 `column xxx does not exist`（PostgreSQL）/
`no such column`（SQLite）。容器部署时（`docker compose up -d --build`）没人会去手工跑迁移，
于是服务启动即崩。这里在 `init_db()` 里做一次**只加列**的同步作为兜底：
拉代码、重建镜像、重启，直接可用，不需要执行任何命令。

**边界（有意为止，别越界）**：
- 只 `ADD COLUMN`：各数据库都支持、对已有数据无破坏；已存在的列原样不动；
- 字符串列**只放宽长度**（`sync_column_types`）：库里比模型短时才 `ALTER ... TYPE`，
  只放宽不放窄、不改别的类型、不删列、不动索引与约束、不做数据回填；
  其它类型变更仍然必须走 Alembic（见 README 第十一节）；
- NOT NULL 的新列靠列上的 Python 默认值（`default=`）或类型推断出一个字面量默认值填旧行；
  实在找不到就退化成可空列并打警告，宁可少一个约束，也不让服务起不来。

同步结果会写日志，可在 `docker compose logs backend` 里确认到底补了哪些列、放宽了哪些长度。
"""

from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Numeric,
    String,
    Time,
    inspect,
    text,
)
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import logger
from app.db.base import Base
from app.db.session import engine as default_engine


def _default_literal(column, dialect: Dialect) -> Optional[str]:
    """给 NOT NULL 的新列找一个能写进 DDL 的字面量默认值（已有行要能落进去）。

    优先级：列上写的 Python 默认值 → 按列类型给一个「空值」→ 给不出来返回 None。
    """
    # 1) 模型里 `default=...` 写的标量（callable 不能进 DDL，只能放弃这条路）
    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        processor = column.type.literal_processor(dialect)
        if processor is not None:
            try:
                return processor(default.arg)
            except (TypeError, ValueError):  # pragma: no cover - 类型对不上就当没有
                pass

    # 2) 按列类型兜底
    column_type = column.type
    if isinstance(column_type, Enum) and column_type.enums:
        # 枚举列取第一个可选值：直接给空串会撞上 PG 的 CHECK 约束
        processor = column_type.literal_processor(dialect)
        if processor is not None:
            try:
                return processor(column_type.enums[0])
            except (TypeError, ValueError):  # pragma: no cover - 同上
                pass
    if isinstance(column_type, Boolean):
        processor = column_type.literal_processor(dialect)
        return processor(False) if processor else None
    if isinstance(column_type, (Integer, Numeric, Float)):
        return "0"
    if isinstance(column_type, String):
        return "''"
    if isinstance(column_type, DateTime):
        return "CURRENT_TIMESTAMP"
    if isinstance(column_type, Date):
        return "CURRENT_DATE"
    if isinstance(column_type, Time):
        return "CURRENT_TIME"
    return None


def _add_column_sql(table_name: str, column, dialect: Dialect) -> str:
    """拼一条 `ALTER TABLE ... ADD COLUMN ...`（NOT NULL 时带上默认值）。"""
    statement = (
        f"ALTER TABLE {table_name} ADD COLUMN "
        f"{column.name} {column.type.compile(dialect=dialect)}"
    )
    if column.nullable:
        return statement

    literal = _default_literal(column, dialect)
    if literal is None:
        logger.warning(
            "列 %s.%s 是 NOT NULL 但找不到可用的默认值，已按可空列补上；"
            "需要非空约束请改用 Alembic 迁移（见 README 第十一节）",
            table_name,
            column.name,
        )
        return statement
    return f"{statement} NOT NULL DEFAULT {literal}"


def sync_missing_columns(bind: Optional[Engine] = None) -> List[str]:
    """补齐所有「ORM 有、库里没有」的列，返回补出来的列名（`表名.列名`）。

    - 表本身还不存在时跳过：`create_all()` 会按当前模型一次性建出来，不归这里管；
    - 每条 `ADD COLUMN` 单独提交；多 worker 同时启动时另一个进程可能已经补过，
      这种「重复列」错误吞掉继续 —— 结构最终一致即可。
    """
    engine = bind if bind is not None else default_engine
    dialect = engine.dialect
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: List[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            statement = _add_column_sql(table.name, column, dialect)
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql(statement)
            except SQLAlchemyError as error:
                logger.warning(
                    "补列失败（多半是并发启动时另一个进程已经补过）：%s -> %s",
                    statement,
                    error,
                )
                continue
            added.append(f"{table.name}.{column.name}")

    if added:
        logger.info("数据库结构已自动补齐 %d 个缺失的列：%s", len(added), "、".join(added))
    return added


def _current_length(engine: Engine, table_name: str, column_name: str) -> Optional[int]:
    """查库里某个字符串列的当前长度上限（MySQL / PostgreSQL 都走 information_schema）。"""
    query = (
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    )
    params = {"table": table_name, "column": column_name}
    if engine.dialect.name == "postgresql":
        # PG 里同名表可能分布在多个 schema，只看当前 schema
        query += " AND table_schema = current_schema()"

    with engine.connect() as connection:
        row = connection.execute(text(query), params).first()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _widen_column_sql(table_name: str, column, dialect: Dialect) -> str:
    """拼一条「放宽字符串列长度」的 DDL。"""
    type_sql = column.type.compile(dialect=dialect)
    if dialect.name == "postgresql":
        return f"ALTER TABLE {table_name} ALTER COLUMN {column.name} TYPE {type_sql}"
    if dialect.name == "mysql":
        null_sql = "NOT NULL" if not column.nullable else "NULL"
        return (
            f"ALTER TABLE {table_name} MODIFY COLUMN {column.name} {type_sql} {null_sql}"
        )
    return ""


def sync_column_types(bind: Optional[Engine] = None) -> List[str]:
    """把长度不够的字符串列放宽到 ORM 里定义的长度，返回处理过的列。

    只处理「库里比模型短」的情况（例如会员编号 6 → 10 位）：

    - 只放宽、不放窄，已有数据原样保留，老用户的 6 位编号不会被动；
    - 只动 `String(n)` 这一种情况，别的类型变更请走 Alembic；
    - SQLite 跳过：它的 `VARCHAR(n)` 不强制长度，改了也没意义；
    - 每条 DDL 单独提交，失败只警告不打断启动（并发启动时另一个进程可能已改过）。
    """
    engine = bind if bind is not None else default_engine
    dialect = engine.dialect
    if dialect.name == "sqlite":
        return []

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    widened: List[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in present:
                continue
            if not isinstance(column.type, String) or column.type.length is None:
                continue

            current = _current_length(engine, table.name, column.name)
            if current is None or current >= column.type.length:
                continue

            statement = _widen_column_sql(table.name, column, dialect)
            if not statement:
                continue
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql(statement)
            except SQLAlchemyError as error:
                logger.warning("放宽列长度失败：%s -> %s", statement, error)
                continue

            widened.append(f"{table.name}.{column.name}({current}->{column.type.length})")

    if widened:
        logger.info(
            "数据库已自动放宽 %d 个字符串列的长度：%s", len(widened), "、".join(widened)
        )
    return widened


__all__ = ["sync_missing_columns", "sync_column_types"]
