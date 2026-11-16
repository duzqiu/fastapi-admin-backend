"""add unique index on article_hot_list_info (source, name)

Revision ID: b7f2c1d4e6a9
Revises: a1c5e9d7b204
Create Date: 2026-11-16 16:25:00.000000+08:00

给热搜榜单加 `(source, name)` 唯一索引：

- 爬虫改成 `INSERT ... ON CONFLICT (source, name) DO UPDATE`，由数据库保证
  同一渠道同一标题只有一行，多实例并发也不会重复；
- 建索引前若表里已经有重复 `(source, name)`，`CREATE UNIQUE INDEX` 会失败，
  需要先人工去重；当前库为空，不存在这个问题。

正常部署不需要手工执行：`app/db/schema_sync.py` 的 `sync_missing_indexes()`
会在容器启动时按模型自动补出这个索引。
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "b7f2c1d4e6a9"
down_revision: Union[str, None] = "a1c5e9d7b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "article_hot_list_info"
INDEX = "ux_article_hot_list_info_source_name"


def _indexes() -> set:
    inspector = inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    if INDEX in _indexes():
        return
    op.create_index(INDEX, TABLE, ["source", "name"], unique=True)


def downgrade() -> None:
    if INDEX not in _indexes():
        return
    op.drop_index(INDEX, table_name=TABLE)
