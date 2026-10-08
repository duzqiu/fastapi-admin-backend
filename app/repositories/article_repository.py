"""文章仓储：所有针对 articles 表的 SQL 查询都集中在这里。"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.article import Article, ArticleStatus
from app.repositories.base import BaseRepository


class ArticleRepository(BaseRepository[Article]):
    """文章数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(Article, db)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        author_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 10,
        order_by: Optional[Any] = None,
    ) -> Tuple[List[Article], int]:
        """按条件分页搜索文章。"""
        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(Article.title.like(like), Article.summary.like(like), Article.tags.like(like))
            )
        if status:
            conditions.append(Article.status == status)
        if author_id is not None:
            conditions.append(Article.author_id == author_id)

        return self.list(
            conditions=conditions,
            order_by=order_by if order_by is not None else Article.id.desc(),
            offset=offset,
            limit=limit,
        )

    def count_by_status(self, status: str) -> int:
        return self.count(conditions=[Article.status == status])

    def total_views(self) -> int:
        return self.sum(Article.views)

    def recent(self, limit: int = 5) -> List[Article]:
        stmt = select(Article).order_by(Article.updated_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().unique().all())

    def published_count(self) -> int:
        return self.count_by_status(ArticleStatus.PUBLISHED.value)

    def increase_views(self, article: Article) -> Article:
        article.views = (article.views or 0) + 1
        self.db.add(article)
        self.db.flush()
        return article
