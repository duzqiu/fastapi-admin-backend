"""add article_official_info

Revision ID: 7e4a9c1d2b6f
Revises: b1f4c7d29e83
Create Date: 2026-10-29 13:55:00.000000+08:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "7e4a9c1d2b6f"
down_revision: Union[str, None] = "b1f4c7d29e83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "article_official_info"
EXPECTED_COLUMNS = {
    "id",
    "created_at",
    "updated_at",
    "article_no",
    "member_id",
    "publisher_snapshot",
    "url",
    "title",
    "content",
    "image_urls",
    "source",
    "published_at",
    "crawled_at",
    "board",
    "rank",
    "status",
    "view_count",
}
EXPECTED_INDEXES = {
    "ix_article_official_info_article_no",
    "ix_article_official_info_member_id",
    "ix_article_official_info_title",
    "ix_article_official_info_source",
    "ix_article_official_info_published_at",
    "ix_article_official_info_board",
    "ix_article_official_info_rank",
    "ix_article_official_info_status",
    "ix_article_official_info_view_count",
    "ix_article_official_info_status_published",
}


def _startup_table_matches(inspector) -> bool:
    """Accept startup-created tables only when their shape is recognizable."""
    columns = inspector.get_columns(TABLE_NAME)
    if {column["name"] for column in columns} != EXPECTED_COLUMNS:
        return False
    if {index["name"] for index in inspector.get_indexes(TABLE_NAME)} != EXPECTED_INDEXES:
        return False
    return True


def upgrade() -> None:
    """Create the official article table and its indexes.

    Application startup calls ``create_all()`` before Alembic may be run.  If
    that has already created this table, leave the schema untouched and let
    Alembic record this revision as applied.  New databases still receive the
    complete table from this migration.
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE_NAME):
        if _startup_table_matches(inspector):
            return
        raise RuntimeError(
            f"{TABLE_NAME} already exists but does not match the expected schema; "
            "refusing to silently mark this migration applied"
        )

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column("article_no", sa.String(length=12), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("publisher_snapshot", sa.String(length=50), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_urls", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("board", sa.String(length=100), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"], ["member_account_info.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_article_official_info_article_no",
        TABLE_NAME,
        ["article_no"],
        unique=True,
    )
    op.create_index("ix_article_official_info_member_id", TABLE_NAME, ["member_id"])
    op.create_index("ix_article_official_info_title", TABLE_NAME, ["title"])
    op.create_index("ix_article_official_info_source", TABLE_NAME, ["source"])
    op.create_index("ix_article_official_info_published_at", TABLE_NAME, ["published_at"])
    op.create_index("ix_article_official_info_board", TABLE_NAME, ["board"])
    op.create_index("ix_article_official_info_rank", TABLE_NAME, ["rank"])
    op.create_index("ix_article_official_info_status", TABLE_NAME, ["status"])
    op.create_index("ix_article_official_info_view_count", TABLE_NAME, ["view_count"])
    op.create_index(
        "ix_article_official_info_status_published",
        TABLE_NAME,
        ["status", "published_at"],
    )


def downgrade() -> None:
    """Drop the official article table and all migration-owned indexes."""
    for index_name in (
        "ix_article_official_info_status_published",
        "ix_article_official_info_view_count",
        "ix_article_official_info_status",
        "ix_article_official_info_rank",
        "ix_article_official_info_board",
        "ix_article_official_info_published_at",
        "ix_article_official_info_source",
        "ix_article_official_info_title",
        "ix_article_official_info_member_id",
        "ix_article_official_info_article_no",
    ):
        op.drop_index(index_name, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
