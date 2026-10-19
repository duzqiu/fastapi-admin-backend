"""add article_post_favorite

帖子收藏：`article_post_favorite`（会员 × 帖子），同一会员对同一帖子只留一条。

Revision ID: b1f4c7d29e83
Revises: 9c2f1d4ab7e3
Create Date: 2026-10-19 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1f4c7d29e83"
down_revision: Union[str, None] = "9c2f1d4ab7e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新建收藏关系表。

    新建表本身 `create_all()` 在启动时也会建；这条迁移是给走 Alembic 的库用的，
    两边保持同一套结构。
    """
    op.create_table(
        "article_post_favorite",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("member_id", sa.Integer(), nullable=False, comment="收藏人（会员）"),
        sa.Column("post_id", sa.Integer(), nullable=False, comment="被收藏的帖子"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(
            ["member_id"], ["member_account_info.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["article_post_info.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "member_id",
            "post_id",
            name="uq_article_post_favorite_member_post",
        ),
    )
    op.create_index(
        "ix_article_post_favorite_member_id",
        "article_post_favorite",
        ["member_id"],
    )
    op.create_index(
        "ix_article_post_favorite_post_id",
        "article_post_favorite",
        ["post_id"],
    )
    op.create_index(
        "ix_article_post_favorite_member_created",
        "article_post_favorite",
        ["member_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_article_post_favorite_member_created",
        table_name="article_post_favorite",
    )
    op.drop_index(
        "ix_article_post_favorite_post_id", table_name="article_post_favorite"
    )
    op.drop_index(
        "ix_article_post_favorite_member_id", table_name="article_post_favorite"
    )
    op.drop_table("article_post_favorite")
