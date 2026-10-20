"""个人网站展示设置（单例）。

目前只有两类配置：
- 首页欢迎语：主标题 / 副标题 / 祝福语；
- 「关于我」访问密码：只存 bcrypt 哈希，不保存明文。
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin

DEFAULT_WELCOME_TITLE = "测试工程师（AI + Python）"
DEFAULT_WELCOME_SUBTITLE = "功能测试 · 自动化测试 · 接口测试 · 性能测试 · AI 辅助测试"
DEFAULT_WELCOME_BLESSING = "愿你今天也有好心情。"
DEFAULT_ABOUT_PASSWORD = "123456"


class SiteSetting(PKMixin, TimestampMixin, Base):
    """站点设置单例；业务上固定使用 id=1 这一行。"""

    __tablename__ = "site_setting"

    welcome_title: Mapped[str] = mapped_column(
        String(200),
        default=DEFAULT_WELCOME_TITLE,
        comment="首页主标题",
    )
    welcome_subtitle: Mapped[str] = mapped_column(
        String(300),
        default=DEFAULT_WELCOME_SUBTITLE,
        comment="首页副标题",
    )
    welcome_blessing: Mapped[str] = mapped_column(
        String(300),
        default=DEFAULT_WELCOME_BLESSING,
        comment="品牌名下方的祝福语",
    )
    about_password_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="是否启用「关于我」访问密码",
    )
    about_password_hash: Mapped[str] = mapped_column(
        String(255),
        default="",
        comment="「关于我」访问密码的 bcrypt 哈希",
    )
    about_password_text: Mapped[str] = mapped_column(
        String(64),
        default="",
        comment="访问密码明文，仅用于后台回显；校验仍走哈希",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<SiteSetting id={self.id} title={self.welcome_title!r}>"


__all__ = [
    "SiteSetting",
    "DEFAULT_WELCOME_TITLE",
    "DEFAULT_WELCOME_SUBTITLE",
    "DEFAULT_WELCOME_BLESSING",
    "DEFAULT_ABOUT_PASSWORD",
]
