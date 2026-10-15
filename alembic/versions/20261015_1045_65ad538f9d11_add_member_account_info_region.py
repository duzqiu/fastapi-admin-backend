"""add member_account_info region

会员资料新增「地区」字段（`region`）。

Revision ID: 65ad538f9d11
Revises: 
Create Date: 2026-10-15 10:45:43.962277+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65ad538f9d11'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 的 ADD COLUMN 要求 NOT NULL 列带上默认值（batch 模式下整表重建，已有行
    # 也要能落进去），所以①先借 server_default 把列加出来并回填空串，②再撤掉默认值
    # —— 与 ORM 侧保持一致（那边 `default=""` 是 Python 默认，不生成 DDL 默认值）。
    #
    # ⚠️ 这两步必须分成**两个** batch：写在一个 batch 里会被合并成一次建表，
    # 默认值在插入旧数据之前就被撤掉了，直接 NOT NULL 失败。
    with op.batch_alter_table('member_account_info', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'region',
                sa.String(length=64),
                nullable=False,
                server_default='',
                comment='地区',
            )
        )

    with op.batch_alter_table('member_account_info', schema=None) as batch_op:
        batch_op.alter_column('region', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('member_account_info', schema=None) as batch_op:
        batch_op.drop_column('region')
