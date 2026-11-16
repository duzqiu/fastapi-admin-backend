"""drop legacy article_hot_list_info.tabs and add is_active

Revision ID: a1c5e9d7b204
Revises: 4d2a8f6c1b90
Create Date: 2026-11-16 15:30:00.000000+08:00

热搜榜单表两处调整：

1. `tabs` 是笔误，已由 `tags` 取代。当前库为空，直接**删除旧列** `tabs`，
   保留 / 新建 `tags`（与爬虫 item、接口字段一致）。
2. 新增 `is_active`：爬虫每轮抓完后把「本轮没再出现」的条目置为 false，
   前台接口只返回 true 的条目；记录不删除，后台仍可查询 / 重新启用。

正常部署不需要手工执行：`app/db/schema_sync.py` 的 `sync_dropped_columns()` /
`sync_missing_columns()` 会在容器启动时自动完成同样的改动。
本迁移用于需要版本化记录或手工管理数据库的场景。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a1c5e9d7b204"
down_revision: Union[str, None] = "4d2a8f6c1b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "article_hot_list_info"
INDEX = "ix_article_hot_list_info_is_active"


def _columns() -> set:
    inspector = inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade() -> None:
    columns = _columns()
    if not columns:  # 全新库：create_all 会按新模型建表
        return

    # 先删历史笔误列，再保证新列存在。
    if "tabs" in columns:
        op.drop_column(TABLE, "tabs")

    if "tags" not in columns:
        op.add_column(
            TABLE,
            sa.Column(
                "tags",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
                comment='徽标文字，如 ["热"]、["新"]；没有徽标为 []',
            ),
        )

    if "is_active" not in columns:
        op.add_column(
            TABLE,
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
                comment="是否启用：False 表示该条已不在最新榜单中",
            ),
        )
        op.create_index(INDEX, TABLE, ["is_active"])


def downgrade() -> None:
    columns = _columns()
    if not columns:
        return

    if "is_active" in columns:
        op.drop_index(INDEX, table_name=TABLE)
        op.drop_column(TABLE, "is_active")

    if "tags" in columns:
        op.drop_column(TABLE, "tags")

    if "tabs" not in columns:
        op.add_column(
            TABLE,
            sa.Column(
                "tabs",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
                comment='徽标文字，如 ["热"]、["新"]；没有徽标为 []',
            ),
        )
