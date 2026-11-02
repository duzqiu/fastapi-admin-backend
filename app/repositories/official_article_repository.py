"""Persistence operations for official articles."""

from datetime import timezone
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
               member_id: Optional[int] = None, user_id: Optional[str] = None,
               source: Optional[str] = None,
               offset: int = 0, limit: int = 10) -> Tuple[List[OfficialArticle], int]:
        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(or_(OfficialArticle.article_no.like(like), OfficialArticle.title.like(like), OfficialArticle.content.like(like), OfficialArticle.source.like(like), OfficialArticle.publisher_snapshot.like(like), OfficialArticle.member.has(Member.nickname.like(like))))
        if status:
            conditions.append(OfficialArticle.status == status)
        if member_id is not None:
            conditions.append(OfficialArticle.member_id == member_id)
        if user_id:
            conditions.append(
                OfficialArticle.member.has(Member.member_no == user_id.strip())
            )
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

    # ------------------------- 前台列表（并入帖子流） -------------------------
    def public_page(
        self,
        *,
        member_id: Optional[int] = None,
        member_ids: Optional[List[int]] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[OfficialArticle], int]:
        """已通过的官号文章：按发布时间倒序，可按作者（单个或多个）筛选。"""
        conditions: List[Any] = [
            OfficialArticle.status == OfficialArticleStatus.APPROVED.value
        ]
        if member_id is not None:
            conditions.append(OfficialArticle.member_id == member_id)
        elif member_ids is not None:
            ids = sorted(int(value) for value in member_ids)
            if not ids:
                return [], 0
            conditions.append(OfficialArticle.member_id.in_(ids))
        return self.list(
            conditions=conditions,
            order_by=(OfficialArticle.published_at.desc(), OfficialArticle.id.desc()),
            offset=offset,
            limit=limit,
        )

    def public_hot_page(
        self,
        *,
        member_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[OfficialArticle], int]:
        """已通过的官号文章：按访问量倒序（首页「热门」）。"""
        conditions: List[Any] = [
            OfficialArticle.status == OfficialArticleStatus.APPROVED.value
        ]
        if member_id is not None:
            conditions.append(OfficialArticle.member_id == member_id)
        return self.list(
            conditions=conditions,
            order_by=(OfficialArticle.view_count.desc(), OfficialArticle.id.desc()),
            offset=offset,
            limit=limit,
        )

    def public_since(self, *, since, limit: int = 200) -> List[OfficialArticle]:
        """近一段时间内已通过的文章（首页「推荐」候选池）。"""
        # 帖子的 utcnow() 是 naive，文章列要求带时区，这里补齐
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        conditions: List[Any] = [
            OfficialArticle.status == OfficialArticleStatus.APPROVED.value,
            OfficialArticle.published_at >= since,
        ]
        items, _ = self.list(
            conditions=conditions,
            order_by=(OfficialArticle.published_at.desc(), OfficialArticle.id.desc()),
            offset=0,
            limit=limit,
        )
        return items
