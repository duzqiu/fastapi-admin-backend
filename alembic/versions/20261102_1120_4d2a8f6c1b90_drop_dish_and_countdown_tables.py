"""drop dish, dish order and countdown tables

Revision ID: 4d2a8f6c1b90
Revises: 7e4a9c1d2b6f
Create Date: 2026-11-02 11:20:00.000000+08:00

后台「菜品管理」与「待办事项（倒数日）」已下线，对应的 8 张表一并删除：

    dish_order_item
    dish_order_info
    dish_base_spec
    dish_base_tag_relation
    dish_base_info
    dish_base_category
    dish_base_tag
    countdown_base_info

注意：upgrade 会**删除这些表及其中全部数据**，执行前请先备份。
downgrade 只重建空表结构，不恢复数据。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "4d2a8f6c1b90"
down_revision: Union[str, None] = "7e4a9c1d2b6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 删除顺序：先删子表，再删被引用的主表
DROP_ORDER = (
    "dish_order_item",
    "dish_order_info",
    "dish_base_spec",
    "dish_base_tag_relation",
    "dish_base_info",
    "dish_base_category",
    "dish_base_tag",
    "countdown_base_info",
)


def upgrade() -> None:
    """删除点菜/订单/倒数日相关的全部表（表不存在时跳过）。"""
    inspector = inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in DROP_ORDER:
        if table_name in existing:
            op.drop_table(table_name)


def downgrade() -> None:
    """重建空表结构（不恢复数据），以便回滚后应用仍可启动。"""
    inspector = inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    # ---------- 倒数日 ----------
    if "countdown_base_info" not in existing:
        op.create_table(
            "countdown_base_info",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("member_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=100), nullable=False),
            sa.Column("cycle", sa.String(length=20), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("remark", sa.String(length=500), nullable=False),
            sa.ForeignKeyConstraint(
                ["member_id"], ["member_account_info.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_countdown_base_info_member_id", "countdown_base_info", ["member_id"])
        op.create_index("ix_countdown_base_info_cycle", "countdown_base_info", ["cycle"])
        op.create_index("ix_countdown_base_info_target_date", "countdown_base_info", ["target_date"])
        op.create_index("ix_countdown_base_info_is_active", "countdown_base_info", ["is_active"])
        op.create_index(
            "ix_countdown_base_info_active_date",
            "countdown_base_info",
            ["is_active", "target_date"],
        )

    # ---------- 菜品分类 / 标签 ----------
    if "dish_base_category" not in existing:
        op.create_table(
            "dish_base_category",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("description", sa.String(length=200), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dish_base_category_name", "dish_base_category", ["name"], unique=True)

    if "dish_base_tag" not in existing:
        op.create_table(
            "dish_base_tag",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("name", sa.String(length=30), nullable=False),
            sa.Column("color", sa.String(length=20), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dish_base_tag_name", "dish_base_tag", ["name"], unique=True)

    # ---------- 菜品 ----------
    if "dish_base_info" not in existing:
        op.create_table(
            "dish_base_info",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("image", sa.String(length=255), nullable=False),
            sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("stock", sa.Integer(), nullable=False),
            sa.Column("sold_count", sa.Integer(), nullable=False),
            sa.Column("unit", sa.String(length=10), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("is_recommended", sa.Boolean(), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["category_id"], ["dish_base_category.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dish_base_info_name", "dish_base_info", ["name"])
        op.create_index("ix_dish_base_info_status", "dish_base_info", ["status"])
        op.create_index("ix_dish_base_info_category_id", "dish_base_info", ["category_id"])
        op.create_index("ix_dish_base_info_status_sort", "dish_base_info", ["status", "sort"])

    if "dish_base_spec" not in existing:
        op.create_table(
            "dish_base_spec",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("dish_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("description", sa.String(length=200), nullable=False),
            sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("stock", sa.Integer(), nullable=False),
            sa.Column("sold_count", sa.Integer(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False),
            sa.Column("min_quantity", sa.Integer(), nullable=False),
            sa.Column("max_quantity_per_order", sa.Integer(), nullable=False),
            sa.Column("daily_limit", sa.Integer(), nullable=False),
            sa.Column("sold_today", sa.Integer(), nullable=False),
            sa.Column("sold_date", sa.Date(), nullable=True),
            sa.Column("serve_start_time", sa.String(length=5), nullable=False),
            sa.Column("serve_end_time", sa.String(length=5), nullable=False),
            sa.ForeignKeyConstraint(["dish_id"], ["dish_base_info.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dish_base_spec_dish_id", "dish_base_spec", ["dish_id"])

    if "dish_base_tag_relation" not in existing:
        op.create_table(
            "dish_base_tag_relation",
            sa.Column("dish_id", sa.Integer(), nullable=False),
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["dish_id"], ["dish_base_info.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tag_id"], ["dish_base_tag.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("dish_id", "tag_id"),
        )

    # ---------- 订单 ----------
    if "dish_order_info" not in existing:
        op.create_table(
            "dish_order_info",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("order_no", sa.String(length=32), nullable=False),
            sa.Column("member_id", sa.Integer(), nullable=True),
            sa.Column("table_no", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("total_quantity", sa.Integer(), nullable=False),
            sa.Column("total_amount", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("remark", sa.String(length=200), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["member_id"], ["member_account_info.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dish_order_info_order_no", "dish_order_info", ["order_no"], unique=True)
        op.create_index("ix_dish_order_info_member_id", "dish_order_info", ["member_id"])
        op.create_index("ix_dish_order_info_status", "dish_order_info", ["status"])
        op.create_index(
            "ix_dish_order_info_status_created", "dish_order_info", ["status", "created_at"]
        )

    if "dish_order_item" not in existing:
        op.create_table(
            "dish_order_item",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=False),
            sa.Column("dish_id", sa.Integer(), nullable=True),
            sa.Column("spec_id", sa.Integer(), nullable=True),
            sa.Column("dish_name", sa.String(length=100), nullable=False),
            sa.Column("spec_name", sa.String(length=50), nullable=False),
            sa.Column("image", sa.String(length=255), nullable=False),
            sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.ForeignKeyConstraint(["order_id"], ["dish_order_info.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dish_id"], ["dish_base_info.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["spec_id"], ["dish_base_spec.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dish_order_item_order_id", "dish_order_item", ["order_id"])
        op.create_index("ix_dish_order_item_dish_id", "dish_order_item", ["dish_id"])
        op.create_index("ix_dish_order_item_spec_id", "dish_order_item", ["spec_id"])
