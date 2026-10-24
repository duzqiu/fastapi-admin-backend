"""通用工具函数。"""

import secrets
from datetime import date, datetime, time, timezone
from typing import Optional

# 会员编号长度（对外展示的短 ID）
# 新注册用户用 10 位；早期注册的老用户仍是 6 位，不做回溯修改
MEMBER_NO_LENGTH = 10
# 帖子编号长度（对外展示的长 ID）
POST_NO_LENGTH = 12


def generate_numeric_id(length: int) -> str:
    """生成指定长度的随机数字编号。

    首位不为 0，保证显示出来的位数固定（例如 10 位时范围是 1000000000-9999999999）。
    这里只负责「随机」，唯一性由服务层的查重重试 + 数据库唯一索引共同保证。
    """
    smallest = 10 ** (length - 1)
    return str(smallest + secrets.randbelow(9 * smallest))


def generate_member_no(length: int = MEMBER_NO_LENGTH) -> str:
    """会员编号（默认 10 位随机数字）。"""
    return generate_numeric_id(length)


def generate_post_no(length: int = POST_NO_LENGTH) -> str:
    """帖子编号（默认 12 位随机数字）。"""
    return generate_numeric_id(length)


def utcnow() -> datetime:
    """返回「无时区信息」的 UTC 时间。

    统一使用 naive UTC 时间可以避免 SQLite / PostgreSQL / MySQL
    三种数据库在时区处理上的差异。用于所有落库的时间戳。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    """服务器本地时间。

    仅用于与「营业时间」相关的业务规则（菜品供应时段、每日限量重置），
    这些规则按门店所在地的墙上时间判断，而不是 UTC。
    """
    return datetime.now()


def local_today() -> date:
    """服务器本地日期，用于每日限量的按天重置。"""
    return datetime.now().date()


def parse_hhmm(value: Optional[str]) -> Optional[time]:
    """把 "HH:MM" 解析为 time 对象；空值或非法值返回 None。"""
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def in_time_window(
    now: Optional[time], start: Optional[str], end: Optional[str]
) -> bool:
    """判断当前时间是否落在 [start, end] 内。

    - 起止都为空：全天不限
    - start <= end：常规时段
    - start > end：跨零点时段（如 22:00 - 02:00）
    """
    start_time = parse_hhmm(start)
    end_time = parse_hhmm(end)
    if start_time is None or end_time is None:
        return True
    current = now or local_now().time()
    if start_time <= end_time:
        return start_time <= current <= end_time
    return current >= start_time or current <= end_time
