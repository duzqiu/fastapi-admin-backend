"""官号文章的点赞 / 收藏关系读写（与帖子的 `PostLike` / `PostFavorite` 平行）。"""

from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.official_article import (
    OfficialArticle,
    OfficialArticleFavorite,
    OfficialArticleLike,
    OfficialArticleStatus,
)
from app.repositories.base import BaseRepository


class _ArticleInteractionRepository(BaseRepository):
    """点赞 / 收藏的公共实现：关系表都只有 `member_id + article_id`。"""

    model: Any

    def __init__(self, model: Any, db: Session) -> None:
        super().__init__(model, db)

    def find(self, member_id: int, article_id: int):
        """某会员对某篇文章的记录；没有返回 None。"""
        return self.get_by(member_id=member_id, article_id=article_id)

    def count_for(self, article_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.article_id == article_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def counts_for(self, article_ids: List[int]) -> Dict[int, int]:
        """批量取数量（列表页用，避免逐条 count）。"""
        if not article_ids:
            return {}
        stmt = (
            select(self.model.article_id, func.count())
            .where(self.model.article_id.in_(list(article_ids)))
            .group_by(self.model.article_id)
        )
        return {row[0]: int(row[1]) for row in self.db.execute(stmt).all()}

    def marked_article_ids(
        self, member_id: int, article_ids: List[int]
    ) -> Set[int]:
        """这批文章里，该会员标记过哪些（点赞 / 收藏各自判断）。"""
        if not article_ids:
            return set()
        stmt = select(self.model.article_id).where(
            self.model.member_id == member_id,
            self.model.article_id.in_(list(article_ids)),
        )
        return set(self.db.execute(stmt).scalars().all())


    def list_articles_with_likes(
        self, member_id: int, *, offset: int = 0, limit: int = 10
    ) -> Tuple[List[Tuple[int, int]], int]:
        """我名下「收到过赞」的文章：[(article_id, 赞数)]，赞多的在前。"""
        counts = (
            select(
                self.model.article_id.label("article_id"),
                func.count().label("total"),
            )
            .join(OfficialArticle, self.model.article_id == OfficialArticle.id)
            .where(
                OfficialArticle.member_id == member_id,
                OfficialArticle.status == OfficialArticleStatus.APPROVED.value,
            )
            .group_by(self.model.article_id)
            .subquery()
        )
        total = int(
            self.db.execute(select(func.count()).select_from(counts)).scalar_one()
        )
        stmt = (
            select(counts.c.article_id, counts.c.total)
            .order_by(counts.c.total.desc(), counts.c.article_id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = [(int(row[0]), int(row[1])) for row in self.db.execute(stmt).all()]
        return rows, total

    def count_received(self, member_id: int) -> int:
        """某会员名下所有官号文章收到的点赞 / 收藏总数。"""
        stmt = (
            select(func.count())
            .select_from(self.model)
            .join(OfficialArticle, self.model.article_id == OfficialArticle.id)
            .where(OfficialArticle.member_id == member_id)
        )
        return int(self.db.execute(stmt).scalar_one())


class ArticleLikeRepository(_ArticleInteractionRepository):
    """官号文章点赞。"""

    def __init__(self, db: Session) -> None:
        super().__init__(OfficialArticleLike, db)


class ArticleFavoriteRepository(_ArticleInteractionRepository):
    """官号文章收藏。"""

    def __init__(self, db: Session) -> None:
        super().__init__(OfficialArticleFavorite, db)

    def list_favorited_entries(
        self, member_id: int, *, offset: int = 0, limit: int = 10
    ) -> Tuple[List[Tuple[int, Any]], int]:
        """会员收藏的文章 id + 收藏时间，最近收藏的在前（只出已通过的）。"""
        conditions = [
            OfficialArticleFavorite.member_id == member_id,
            OfficialArticle.status == OfficialArticleStatus.APPROVED.value,
        ]
        count_stmt = (
            select(func.count())
            .select_from(OfficialArticleFavorite)
            .join(OfficialArticle, OfficialArticleFavorite.article_id == OfficialArticle.id)
        )
        stmt = select(
            OfficialArticleFavorite.article_id, OfficialArticleFavorite.created_at
        ).join(OfficialArticle, OfficialArticleFavorite.article_id == OfficialArticle.id)
        for condition in conditions:
            count_stmt = count_stmt.where(condition)
            stmt = stmt.where(condition)

        total = int(self.db.execute(count_stmt).scalar_one())
        stmt = (
            stmt.order_by(
                OfficialArticleFavorite.created_at.desc(),
                OfficialArticleFavorite.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        rows = [(int(row[0]), row[1]) for row in self.db.execute(stmt).all()]
        return rows, total
