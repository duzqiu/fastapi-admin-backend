"""启动时的结构同步：补列、补索引，并清理已登记的历史废弃列。

**为什么需要它**：`Base.metadata.create_all()` **只建表、不改表** —— 老库升级到新代码后，
模型里新增的列不会自动补上，一查就报 `column xxx does not exist`（PostgreSQL）/
`no such column`（SQLite）。容器部署时（`docker compose up -d --build`）没人会去手工跑迁移，
于是服务启动即崩。这里在 `init_db()` 里做一次结构兜底：
拉代码、重建镜像、重启，直接可用，不需要执行任何命令。

**边界（有意为止，别越界）**：
- `ADD COLUMN`：各数据库都支持、对已有数据无破坏；已存在的列原样不动；
- 字符串列**只放宽长度**（`sync_column_types`）：库里比模型短时才 `ALTER ... TYPE`，
  只放宽不放窄、不改别的类型；
- `COLUMN_DROPS` 里登记过的废弃列会**直接删除**（删列丢数据，登记前确认环境允许）；
- NOT NULL 的新列靠列上的 Python 默认值（`default=`）或类型推断出一个字面量默认值填旧行；
  实在找不到就退化成可空列并打警告，宁可少一个约束，也不让服务起不来。

同步结果会写日志，可在 `docker compose logs backend` 里确认到底补了 / 删了哪些列。
"""

from typing import List, Optional

from sqlalchemy import (
    JSON,
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


#: 已登记的历史废弃列：(表名, 旧列名)。
#: 这些列是早期笔误 / 已废弃字段，升级时直接从库里删掉；新列由模型补列逻辑建出。
#: 只放确定不再使用的列，删列前请确认该环境的数据可以丢弃。
COLUMN_DROPS = (
    # 热搜榜单：tabs 是笔误，已由 tags 取代（当前数据库为空，直接删列）。
    ("article_hot_list_info", "tabs"),
)


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
    if isinstance(column_type, JSON):
        # 空数组；PG / SQLite 直接可用，MySQL 8.0.13+ 亦支持该字面量默认值
        return "'[]'"
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


def sync_dropped_columns(bind: Optional[Engine] = None) -> List[str]:
    """删除已废弃的历史列，返回删掉的 `表.列名`。

    `CREATE TABLE` 不会改已有表，Alembic 又要求手工执行，容器里只重建镜像时
    没人跑迁移；所以对确定不再使用的列做一次兜底清理：

    - 只处理下面 `COLUMN_DROPS` 里登记过的列，不猜、不扫描全库；
    - 表或列不存在时跳过（新库没有这些历史列）；
    - 删列会丢该列数据，登记前请确认对应环境允许丢弃。
    """
    engine = bind if bind is not None else default_engine
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dropped: List[str] = []

    for table_name, column_name in COLUMN_DROPS:
        if table_name not in existing_tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name not in columns:
            continue

        statement = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(statement)
        except SQLAlchemyError as error:
            logger.warning("删除历史列失败：%s -> %s", statement, error)
            continue
        dropped.append(f"{table_name}.{column_name}")
        # 删完刷新一次，避免同表后续判断用到过期快照
        inspector = inspect(engine)

    if dropped:
        logger.info("数据库已删除 %d 个废弃列：%s", len(dropped), "、".join(dropped))
    return dropped


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
                # 某些方言不接受该默认值（如旧版 MySQL 的 JSON 默认值）：
                # 退一步用可空列补上，保证服务能起来，约束后续走 Alembic。
                if " NOT NULL DEFAULT " not in statement:
                    continue
                nullable = (
                    f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
                    f"{column.type.compile(dialect=dialect)}"
                )
                try:
                    with engine.begin() as connection:
                        connection.exec_driver_sql(nullable)
                except SQLAlchemyError as retry_error:
                    logger.warning("退化为可空列仍然失败：%s -> %s", nullable, retry_error)
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


def sync_missing_indexes(bind: Optional[Engine] = None) -> List[str]:
    """补齐「模型里定义了、库里还没有」的索引，返回补出来的索引名。

    `create_all()` 对已存在的表同样不会补索引，新加的 `is_active` 这类过滤列
    在老库上就会缺索引。这里按名称比对，缺什么建什么：

    - 只建 `Index(...)`，不处理唯一约束 / 外键；
    - 单条失败只警告，不打断启动（并发启动时另一个进程可能已经建过）。
    """
    engine = bind if bind is not None else default_engine
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    created: List[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if not index.name or index.name in present:
                continue
            try:
                index.create(bind=engine, checkfirst=True)
            except SQLAlchemyError as error:
                logger.warning("补索引失败：%s -> %s", index.name, error)
                continue
            created.append(index.name)

    if created:
        logger.info("数据库已自动补齐 %d 个索引：%s", len(created), "、".join(created))
    return created


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


__all__ = [
    "sync_dropped_columns",
    "sync_missing_columns",
    "sync_missing_indexes",
    "sync_column_types",
]
