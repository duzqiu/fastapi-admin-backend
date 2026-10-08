"""系统服务：健康检查、运行信息、首页统计。"""

import platform
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.member_repository import MemberRepository
from app.repositories.user_repository import UserRepository


class SystemService:
    """系统信息业务逻辑层。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.members = MemberRepository(db)

    def health(self) -> Dict[str, Any]:
        """健康检查：同时探测数据库连通性。"""
        try:
            self.db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # pragma: no cover - 仅在数据库不可用时触发
            db_ok = False

        return {
            "status": "ok" if db_ok else "degraded",
            "version": settings.VERSION,
            "database": "up" if db_ok else "down",
        }

    @staticmethod
    def _mask_url(url: str) -> str:
        """隐藏数据库连接串中的密码。"""
        if "@" not in url or "//" not in url:
            return url
        head, tail = url.split("//", 1)
        credentials, host = tail.split("@", 1)
        if ":" in credentials:
            user = credentials.split(":", 1)[0]
            credentials = f"{user}:***"
        return f"{head}//{credentials}@{host}"

    def info(self) -> Dict[str, Any]:
        """系统运行信息（用于排查环境问题）。"""
        return {
            "project_name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "debug": settings.DEBUG,
            "database_dialect": self.db.bind.dialect.name if self.db.bind else "unknown",
            "database_url_masked": self._mask_url(settings.DATABASE_URL),
            "python_version": platform.python_version(),
            "stats": {
                "users": self.users.count(),
                "members": self.members.count(),
            },
        }

    def dashboard(self) -> Dict[str, Any]:
        """后台首页统计卡片 + 最近注册会员。"""
        recent_members: List[Dict[str, Any]] = [
            {
                "id": item.id,
                "email": item.email,
                "nickname": item.nickname,
                "display_name": item.display_name,
                "avatar": item.avatar,
                "gender": item.gender,
                "is_active": item.is_active,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for item in self.members.recent(limit=5)
        ]

        member_total = self.members.count()
        member_active = self.members.count_active()

        return {
            "user_total": self.users.count(),
            "user_active": self.users.count_active(),
            "member_total": member_total,
            "member_active": member_active,
            "member_disabled": member_total - member_active,
            "member_new_7_days": self.members.count_registered_within_days(7),
            "recent_members": recent_members,
        }
