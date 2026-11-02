"""删除已下线功能遗留的数据库表。

后台「菜品管理」与「待办事项（倒数日）」在 2026-11 下线，对应 8 张表由模型层移除。
`Base.metadata.create_all()` 只建表、不删表，所以老库里这些表会一直留着。
为了让「拉代码 → 重启」就能完成清理、不必手工执行迁移，启动时会调用这里：

    dish_order_item / dish_order_info / dish_base_spec / dish_base_tag_relation /
    dish_base_info / dish_base_category / dish_base_tag / countdown_base_info

**只删除固定白名单内的表**，其它表一律不碰；按子表 → 主表的顺序删除，
以兼容 PostgreSQL / MySQL 的外键约束。可通过 `DROP_LEGACY_TABLES=false` 关闭。

注意：删除不可恢复。需要保留历史数据时，请先备份，或在执行前把该开关设为 false。
"""

from typing import Iterable, List, Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.logging import logger
from app.db.session import engine as default_engine


#: 删除顺序：先子表，后主表（被外键引用的表最后删）
LEGACY_TABLES: tuple[str, ...] = (
    "dish_order_item",
    "dish_order_info",
    "dish_base_spec",
    "dish_base_tag_relation",
    "dish_base_info",
    "dish_base_category",
    "dish_base_tag",
    "countdown_base_info",
)


def drop_legacy_tables(
    engine: Optional[Engine] = None,
    tables: Iterable[str] = LEGACY_TABLES,
) -> List[str]:
    """删除白名单中存在的老表，返回实际删除的表名（不存在则跳过）。"""
    if not settings.DROP_LEGACY_TABLES:
        logger.info("DROP_LEGACY_TABLES=false，跳过老表清理")
        return []

    target = engine or default_engine
    existing = set(inspect(target).get_table_names())
    quoted = target.dialect.identifier_preparer.quote

    dropped: List[str] = []
    with target.begin() as connection:
        for table_name in tables:
            if table_name not in existing:
                continue
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {quoted(table_name)}")
            dropped.append(table_name)

    if dropped:
        logger.info("已删除下线功能遗留的数据表: %s", ", ".join(dropped))
    return dropped
