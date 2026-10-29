"""官号文章评论的读写（与帖子评论 `PostCommentRepository` 平行）。"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import func, or_, select

from app.models.member import Member
from app.models.official_article import (
    OfficialArticle,
    OfficialArticleComment,
    OfficialArticleStatus,
)
from app.models.post import CommentStatus
from app.repositories.base import BaseRepository


class OfficialArticleCommentRepository(BaseRepository[OfficialArticleComment]):
    """文章评论：前台按文章取已通过，后台按条件筛选 + 审核。"""

    def __init__(self, db) -> None:
        super().__init__(OfficialArticleComment, db)

    def list_by_article(
        self, article_id: int, *, offset: int = 0, limit: int = 20
    ) -> Tuple[List[OfficialArticleComment], int]:
        """某篇文章下**已通过**的评论，最新的在前。"""
        conditions = [
            OfficialArticleComment.article_id == article_id,
            OfficialArticleComment.status == CommentStatus.APPROVED.value,
        ]
        return self.list(
            conditions=conditions,
            order_by=(
                OfficialArticleComment.created_at.desc(),
                OfficialArticleComment.id.desc(),
            ),
            offset=offset,
            limit=limit,
        )

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        article_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[OfficialArticleComment], int]:
        """后台评论管理：按内容 / 评论人 / 文章编号筛选。"""
        conditions: List[Any] = []
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    OfficialArticleComment.content.like(like),
                    OfficialArticleComment.publisher.like(like),
                    OfficialArticleComment.member.has(Member.nickname.like(like)),
                    OfficialArticleComment.article.has(
                        OfficialArticle.article_no.like(like)
                    ),
                )
            )
        if status:
            conditions.append(OfficialArticleComment.status == status)
        if article_id is not None:
            conditions.append(OfficialArticleComment.article_id == article_id)
        return self.list(
            conditions=conditions,
            order_by=(
                OfficialArticleComment.created_at.desc(),
                OfficialArticleComment.id.desc(),
            ),
            offset=offset,
            limit=limit,
        )

    def count_received(self, member_id: int) -> int:
        """某会员名下所有文章的「已通过」评论总数。"""
        stmt = (
            select(func.count())
            .select_from(OfficialArticleComment)
            .join(OfficialArticle, OfficialArticleComment.article_id == OfficialArticle.id)
            .where(
                OfficialArticle.member_id == member_id,
                OfficialArticleComment.status == CommentStatus.APPROVED.value,
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    def list_articles_with_comments(
        self, member_id: int, *, offset: int = 0, limit: int = 10
    ) -> Tuple[List[Tuple[int, int]], int]:
        """我名下「收到过已通过评论」的文章：[(article_id, 评论数)], 评论多的在前。"""
        counts = (
            select(
                OfficialArticleComment.article_id.label("article_id"),
                func.count().label("total"),
            )
            .join(OfficialArticle, OfficialArticleComment.article_id == OfficialArticle.id)
            .where(
                OfficialArticle.member_id == member_id,
                OfficialArticle.status == OfficialArticleStatus.APPROVED.value,
                OfficialArticleComment.status == CommentStatus.APPROVED.value,
            )
            .group_by(OfficialArticleComment.article_id)
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
