"""数据库初始化脚本。

用法：
    python scripts/init_db.py

作用：
    1. 根据 ORM 模型创建全部数据表（幂等）；
    2. 补齐「模型里已定义、库里还没有」的列（只加列，见 app/db/schema_sync.py）
       —— 老库升级到新代码后不用手工跑迁移；
    3. 创建初始管理员账号（来自 .env 的 FIRST_SUPERUSER_* 配置）；
    4. 写入演示用会员与菜品数据（表为空时才写入）。
"""

import sys
from pathlib import Path

# 允许直接执行 `python scripts/init_db.py`（把项目根目录加入 sys.path）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.db.init_db import init_db  # noqa: E402


def main() -> None:
    setup_logging()
    print(f"[init_db] 目标数据库: {settings.DATABASE_URL}")
    init_db()
    print("[init_db] 初始化完成")
    print(f"[init_db] 管理员账号: {settings.FIRST_SUPERUSER_USERNAME} / {settings.FIRST_SUPERUSER_PASSWORD}")


if __name__ == "__main__":
    main()
