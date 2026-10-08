"""数据库暴力迁移脚本：SQLite -> PostgreSQL / MySQL（也支持任意两库互迁）。

原理：
    1. 用项目 ORM 元数据（Base.metadata）在目标库创建全部表结构；
    2. 反射源库表结构，按外键依赖顺序（sorted_tables）逐表读取数据；
    3. 分批写入目标库，过程中跳过源库不存在的列，兼容历史结构差异；
    4. 迁移完成后校验行数，并（PostgreSQL）重置自增序列，避免主键冲突。

用法示例：
    # 最常用：把本地 SQLite 全量迁移到 .env 中配置的目标库
    python scripts/migrate_database.py --target "postgresql+psycopg://user:pwd@127.0.0.1:5432/admin_db" --create-tables --truncate

    # 指定源库，并显式指定迁移哪些表
    python scripts/migrate_database.py --source "sqlite:///./data/app.db" --target "mysql+pymysql://root:pwd@127.0.0.1:3306/admin_db?charset=utf8mb4" --create-tables --truncate --tables users,articles

    # 只校验两个库的数据行数是否一致
    python scripts/migrate_database.py --target "..." --verify-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Sequence

from sqlalchemy import MetaData, Table, create_engine, func, insert, select
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import Article, User  # noqa: F401,E402  确保所有模型注册到 metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SQLite -> PostgreSQL / MySQL 数据迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        default="sqlite:///./data/app.db",
        help="源数据库 URL，默认 sqlite:///./data/app.db",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="目标数据库 URL，默认取 .env 中的 DATABASE_URL",
    )
    parser.add_argument("--create-tables", action="store_true", help="在目标库创建缺失的表结构")
    parser.add_argument("--truncate", action="store_true", help="迁移前清空目标表（危险，会删除数据）")
    parser.add_argument("--tables", default=None, help="只迁移指定表，逗号分隔，默认全部")
    parser.add_argument("--batch-size", type=int, default=500, help="批量写入条数，默认 500")
    parser.add_argument("--verify-only", action="store_true", help="只做行数校验，不写入任何数据")
    return parser


def make_engine(url: str) -> Engine:
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def ordered_tables(table_names: Sequence[str] | None = None) -> List[Table]:
    """按外键依赖顺序返回需要迁移的表。"""
    tables = list(Base.metadata.sorted_tables)
    if table_names:
        wanted = {name.strip() for name in table_names if name.strip()}
        tables = [table for table in tables if table.name in wanted]
    return tables


def truncate_target(engine: Engine, tables: Sequence[Table]) -> None:
    """按外键逆序清空目标表。"""
    with engine.begin() as conn:
        for table in reversed(tables):
            conn.execute(table.delete())
    print(f"[migrate] 已清空目标表: {', '.join(table.name for table in tables)}")


def migrate_table(
    source_engine: Engine,
    target_engine: Engine,
    table: Table,
    source_meta: MetaData,
    batch_size: int,
) -> int:
    """迁移单张表，返回迁移行数。"""
    if table.name not in source_meta.tables:
        print(f"[migrate] 跳过 {table.name}（源库不存在该表）")
        return 0

    source_table = source_meta.tables[table.name]
    # 只迁移双方都存在的列，兼容历史结构差异
    columns = [column.name for column in table.columns if column.name in source_table.columns]

    migrated = 0
    with source_engine.connect() as source_conn:
        result = source_conn.execute(select(*(source_table.c[name] for name in columns))).mappings()
        batch: List[Dict] = []
        for row in result:
            batch.append(dict(row))
            if len(batch) >= batch_size:
                with target_engine.begin() as target_conn:
                    target_conn.execute(insert(table), batch)
                migrated += len(batch)
                batch.clear()
        if batch:
            with target_engine.begin() as target_conn:
                target_conn.execute(insert(table), batch)
            migrated += len(batch)

    print(f"[migrate] {table.name:<16} 迁移 {migrated} 行")
    return migrated


def reset_sequences(engine: Engine, tables: Sequence[Table]) -> None:
    """PostgreSQL：迁移后重置自增序列，避免后续插入主键冲突。"""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        for table in tables:
            if "id" not in table.columns:
                continue
            conn.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:tbl, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table.name + "), 1), true)"
                ),
                {"tbl": table.name},
            )
    print("[migrate] 已重置 PostgreSQL 自增序列")


def verify(source_engine: Engine, target_engine: Engine, tables: Sequence[Table]) -> bool:
    """逐表比对行数。"""
    print("\n[migrate] 行数校验：")
    all_ok = True
    for table in tables:
        with source_engine.connect() as conn:
            source_count = conn.execute(select(func.count()).select_from(table)).scalar_one()
        with target_engine.connect() as conn:
            target_count = conn.execute(select(func.count()).select_from(table)).scalar_one()
        ok = source_count == target_count
        all_ok = all_ok and ok
        print(
            f"  {table.name:<16} 源库={source_count:<8} 目标库={target_count:<8} {'OK' if ok else '不一致 !!!'}"
        )
    return all_ok


def main() -> int:
    args = build_parser().parse_args()

    source_url = args.source
    target_url = args.target or settings.DATABASE_URL
    if source_url == target_url:
        print("[migrate] 源库与目标库相同，无需迁移")
        return 1

    print(f"[migrate] 源库  : {source_url}")
    print(f"[migrate] 目标库: {target_url}")

    source_engine = make_engine(source_url)
    target_engine = make_engine(target_url)
    tables = ordered_tables(args.tables.split(",") if args.tables else None)

    if args.verify_only:
        return 0 if verify(source_engine, target_engine, tables) else 1

    if args.create_tables:
        Base.metadata.create_all(bind=target_engine)
        print("[migrate] 目标库表结构已就绪")

    if args.truncate:
        truncate_target(target_engine, tables)

    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)

    total = 0
    for table in tables:
        total += migrate_table(source_engine, target_engine, table, source_meta, args.batch_size)

    reset_sequences(target_engine, tables)
    print(f"\n[migrate] 迁移完成，共写入 {total} 行")

    ok = verify(source_engine, target_engine, tables)
    print("\n[migrate] 结果:", "全部一致 ✅" if ok else "存在差异，请检查上表 ⚠️")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
