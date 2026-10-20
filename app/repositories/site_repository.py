"""个人网站设置仓储（单例，固定 id=1）。"""

from sqlalchemy.orm import Session

from app.models.site_setting import SiteSetting
from app.repositories.base import BaseRepository


class SiteSettingRepository(BaseRepository[SiteSetting]):
    def __init__(self, db: Session) -> None:
        super().__init__(SiteSetting, db)


__all__ = ["SiteSettingRepository"]
