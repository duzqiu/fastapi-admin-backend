"""个人网站设置业务逻辑：首页欢迎语与「关于我」访问密码。"""

from typing import Optional

from sqlalchemy.orm import Session

from app.core.site_password import hash_site_password, verify_site_password
from app.models.site_setting import (
    DEFAULT_ABOUT_PASSWORD,
    DEFAULT_WELCOME_BLESSING,
    DEFAULT_WELCOME_SUBTITLE,
    DEFAULT_WELCOME_TITLE,
    SiteSetting,
)
from app.repositories.site_repository import SiteSettingRepository
from app.schemas.site import SiteWelcomeOut, SiteWelcomeUpdate


class SiteService:
    """站点设置只有一行（id=1），所有读写都围绕它。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = SiteSettingRepository(db)

    def get_setting(self) -> SiteSetting:
        """取设置单例；老库还没有这行时自动补一行默认值。"""
        item = self.settings.get(1)
        if item is not None:
            # 老数据只有哈希、没有明文：如果还是默认密码，就补一份明文供后台回显
            if (
                not item.about_password_text
                and item.about_password_hash
                and verify_site_password(
                    DEFAULT_ABOUT_PASSWORD,
                    item.about_password_hash,
                )
            ):
                self.settings.update(
                    item,
                    about_password_text=DEFAULT_ABOUT_PASSWORD,
                )
                self.db.commit()
                self.db.refresh(item)
            return item

        item = self.settings.create(
            id=1,
            welcome_title=DEFAULT_WELCOME_TITLE,
            welcome_subtitle=DEFAULT_WELCOME_SUBTITLE,
            welcome_blessing=DEFAULT_WELCOME_BLESSING,
            about_password_enabled=True,
            about_password_hash=hash_site_password(DEFAULT_ABOUT_PASSWORD),
            about_password_text=DEFAULT_ABOUT_PASSWORD,
        )
        self.db.commit()
        self.db.refresh(item)
        return item

    def get_welcome(self) -> SiteWelcomeOut:
        item = self.get_setting()
        return SiteWelcomeOut(
            title=item.welcome_title,
            subtitle=item.welcome_subtitle,
            blessing=item.welcome_blessing,
        )

    def update_welcome(self, payload: SiteWelcomeUpdate) -> SiteWelcomeOut:
        item = self.get_setting()
        self.settings.update(
            item,
            welcome_title=payload.title.strip(),
            welcome_subtitle=payload.subtitle.strip(),
            welcome_blessing=payload.blessing.strip(),
        )
        self.db.commit()
        self.db.refresh(item)
        return SiteWelcomeOut(
            title=item.welcome_title,
            subtitle=item.welcome_subtitle,
            blessing=item.welcome_blessing,
        )

    def verify_about_password(self, password: str) -> bool:
        item = self.get_setting()
        if not item.about_password_enabled:
            return True
        if not item.about_password_hash:
            return False
        return verify_site_password(password, item.about_password_hash)

    def about_password_configured(self) -> bool:
        return bool(self.get_setting().about_password_hash)

    def about_password_enabled(self) -> bool:
        return bool(self.get_setting().about_password_enabled)

    def about_password_text(self) -> str:
        """后台回显用；旧数据可能为空。"""
        return self.get_setting().about_password_text or ""

    def update_about_password(
        self,
        *,
        enabled: bool,
        password: Optional[str] = None,
    ) -> None:
        item = self.get_setting()
        values = {"about_password_enabled": enabled}
        if password:
            values["about_password_hash"] = hash_site_password(password)
            values["about_password_text"] = password
        self.settings.update(item, **values)
        self.db.commit()
        self.db.refresh(item)


__all__ = ["SiteService"]
