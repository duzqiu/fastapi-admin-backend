"""启动时「自动补列」的测试（app/db/schema_sync.py）。

场景：库是旧版本建的，模型里后来新增了列 —— 直接查会报 `no such column`。
`init_db()` 里会自动把缺的列补上，所以「拉代码 → 重建镜像 → 起服务」就够了，
不需要任何人手工执行迁移命令。这里用独立的文件库验证，避免影响 conftest 的内存库。
"""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import app.db.init_db as init_db_module
from app.db.base import Base
from app.db.schema_sync import sync_missing_columns
from app.db.session import build_engine

TABLE = "member_account_info"


def _old_engine(tmp_path: Path, drop: list[str]):
    """造一个「建表时还没有 drop 里这些列」的老库，并塞一行旧数据。"""
    engine = build_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {TABLE} "
                "(member_no, email, hashed_password, email_verified, register_ip, nickname,"
                " avatar, background, gender, phone, bio, region, is_active,"
                " created_at, updated_at) "
                "VALUES ('000001', 'old@example.com', 'hashed', 0, '', '老用户', '',"
                " '/api/v1/uploads/backgrounds/1/old.png', 'unknown', '', '', '上海', 1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        for column in drop:
            connection.exec_driver_sql(f"ALTER TABLE {TABLE} DROP COLUMN {column}")
    return engine


def _columns(engine) -> set[str]:
    with engine.begin() as connection:
        rows = connection.exec_driver_sql(f"PRAGMA table_info({TABLE})")
        return {row[1] for row in rows}


def test_sync_adds_missing_column_and_keeps_old_rows(tmp_path):
    engine = _old_engine(tmp_path, ["background"])
    assert "background" not in _columns(engine)

    added = sync_missing_columns(engine)

    assert added == [f"{TABLE}.background"]
    assert "background" in _columns(engine)
    with engine.begin() as connection:
        row = connection.exec_driver_sql(f"SELECT nickname, background FROM {TABLE}").one()
    # 旧数据还在，且新列有默认值（NOT NULL 不会因为已有老行而失败）
    assert row.nickname == "老用户"
    assert row.background == ""


def test_sync_adds_several_missing_columns(tmp_path):
    engine = _old_engine(tmp_path, ["background", "region"])

    added = sync_missing_columns(engine)

    assert set(added) == {f"{TABLE}.background", f"{TABLE}.region"}
    assert {"background", "region"} <= _columns(engine)


def test_sync_is_noop_when_schema_is_up_to_date(tmp_path):
    """结构已一致时不该产生任何 DDL —— 每次启动都会跑一遍，必须安静。"""
    engine = build_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    Base.metadata.create_all(engine)
    before = _columns(engine)

    assert sync_missing_columns(engine) == []
    assert _columns(engine) == before


def test_sync_skips_tables_that_do_not_exist_yet(tmp_path):
    """空库：一张表都没有。建表是 create_all() 的事，这里既不该建表也不该报错。"""
    engine = build_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")

    assert sync_missing_columns(engine) == []


def test_init_db_heals_old_schema(tmp_path, monkeypatch):
    """端到端：老库跑一次 init_db()，缺的列被补上、后面的播种流程也不报错。"""
    engine = _old_engine(tmp_path, ["background"])
    monkeypatch.setattr(init_db_module, "engine", engine)
    monkeypatch.setattr(
        init_db_module,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    init_db_module.init_db()  # 补列之前这一步会直接抛 UndefinedColumn

    assert "background" in _columns(engine)
    with engine.begin() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT nickname, background FROM {TABLE}"
        ).all()
    # 表里已有数据，所以演示会员不会重复播种（`表为空时才写入`）；关键是老行没丢、能读出来
    assert len(rows) == 1
    assert rows[0].nickname == "老用户"
    assert rows[0].background == ""


def test_default_literal_falls_back_to_nullable_when_no_default():
    """造不出默认值的 NOT NULL 列退化成可空列，而不是让启动直接崩。"""
    from sqlalchemy import LargeBinary
    from sqlalchemy.schema import Column

    from app.db.schema_sync import _add_column_sql

    engine = build_engine("sqlite:///:memory:")
    column = Column("blob_col", LargeBinary, nullable=False)
    statement = _add_column_sql("t_anything", column, engine.dialect)

    assert "NOT NULL" not in statement
