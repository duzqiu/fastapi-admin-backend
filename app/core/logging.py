"""日志配置模块。"""

import logging
import sys

from app.core.config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("app")


def setup_logging() -> None:
    """初始化根日志器（重复调用不会重复添加 handler）。"""
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())

    if any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)

    # 降低三方库日志噪音
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
