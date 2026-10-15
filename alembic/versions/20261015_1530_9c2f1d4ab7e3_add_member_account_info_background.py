"""add member_account_info.background

背景图：与头像同一套规则，按会员 ID 存（`data/uploads/backgrounds/{会员ID}/`）。

Revision ID: 9c2f1d4ab7e3
Revises: 65ad538f9d11
Create Date: 2026-10-15 15:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c2f1d4ab7e3"
down_revision: Union[str, None] = "65ad538f9d11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给已有库加 `background` 列。

    ⚠️ SQLite 加 NOT NULL 列必须分**两个** batch：
    第一个 batch 带 `server_default=''` 把列建出来并拷旧数据，
    第二个 batch 再把默认值撤掉。合在一个 batch 里会被合并成一次建表，
    拷旧行时默认值已经被撤掉 -> `NOT NULL constraint failed`。
    """
    with op.batch_alter_table("member_account_info") as batch_op:
        batch_op.add_column(
            sa.Column("background", sa.String(255), nullable=False, server_default="")
        )
    with op.batch_alter_table("member_account_info") as batch_op:
        batch_op.alter_column("background", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("member_account_info") as batch_op:
        batch_op.drop_column("background")
