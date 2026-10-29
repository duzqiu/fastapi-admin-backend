"""Persistence operations for official articles."""

from typing import Any, List, Optional, Tuple

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models.member import Member
from app.models.official_article import OfficialArticle, OfficialArticleStatus
from app.repositories.base import BaseRepository


class OfficialArticleRepository(BaseRepository[OfficialArticle]):
    def __init__(self, db: Session) -> None:
        super().__init__(OfficialArticle, db)

    def article_no_taken(self, article_no: str) -> bool:
        return self.exists(article_no=article_no)

    def search(self, *, keyword: Optional[str] = None, status: Optional[str] = None,
               member_id: Optional[int] = None, source: Optional[str] = None,
               offset: int = 0, limit: int = 10) -> Tuple[List[OfficialArticle], int]:
        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(or_(OfficialArticle.article_no.like(like), OfficialArticle.title.like(like), OfficialArticle.content.like(like), OfficialArticle.source.like(like), OfficialArticle.publisher_snapshot.like(like), OfficialArticle.member.has(Member.nickname.like(like))))
        if status:
            conditions.append(OfficialArticle.status == status)
        if member_id is not None:
            conditions.append(OfficialArticle.member_id == member_id)
        if source:
            conditions.append(OfficialArticle.source.like(f"%{source.strip()}%"))
        return self.list(conditions=conditions, order_by=(OfficialArticle.published_at.desc(), OfficialArticle.id.desc()), offset=offset, limit=limit)

    def get_public(self, article_id: int) -> Optional[OfficialArticle]:
        stmt = select(OfficialArticle).where(OfficialArticle.id == article_id, OfficialArticle.status == OfficialArticleStatus.APPROVED.value)
        return self.db.execute(stmt).scalars().first()

    def increment_view(self, article_id: int) -> int:
        self.db.execute(update(OfficialArticle).where(OfficialArticle.id == article_id).values(view_count=OfficialArticle.view_count + 1))
        value = self.db.execute(select(OfficialArticle.view_count).where(OfficialArticle.id == article_id)).scalar_one()
        return int(value)
