"""启动时自动清理下线功能遗留表的测试。"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.db import legacy_cleanup
from app.db.legacy_cleanup import LEGACY_TABLES, drop_legacy_tables


def _engine_with_legacy_tables() -> "object":
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        for table in LEGACY_TABLES:
            connection.execute(text(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE "member_account_info" (id INTEGER PRIMARY KEY)'))
    return engine


def test_drop_legacy_tables_removes_only_whitelist(monkeypatch):
    monkeypatch.setattr(legacy_cleanup.settings, "DROP_LEGACY_TABLES", True)
    engine = _engine_with_legacy_tables()

    dropped = drop_legacy_tables(engine)

    assert set(dropped) == set(LEGACY_TABLES)
    remaining = set(inspect(engine).get_table_names())
    assert remaining == {"member_account_info"}


def test_drop_legacy_tables_is_idempotent(monkeypatch):
    monkeypatch.setattr(legacy_cleanup.settings, "DROP_LEGACY_TABLES", True)
    engine = _engine_with_legacy_tables()

    assert drop_legacy_tables(engine)
    assert drop_legacy_tables(engine) == []


def test_drop_legacy_tables_can_be_disabled(monkeypatch):
    monkeypatch.setattr(legacy_cleanup.settings, "DROP_LEGACY_TABLES", False)
    engine = _engine_with_legacy_tables()

    assert drop_legacy_tables(engine) == []
    assert set(LEGACY_TABLES) <= set(inspect(engine).get_table_names())


def test_application_database_has_no_legacy_tables():
    """测试库（create_all 生成）不应再出现任何已下线的表。"""
    from app.db.session import engine

    names = set(inspect(engine).get_table_names())
    assert not names & set(LEGACY_TABLES)
