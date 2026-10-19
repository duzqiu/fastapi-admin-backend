"""文章管理仓储：所有针对 article_post_info / article_post_favorite 的查询都集中在这里。"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.post import Post, PostFavorite, PostStatus
from app.repositories.base import BaseRepository


class PostRepository(BaseRepository[Post]):
    """帖子数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(Post, db)

    def post_no_taken(self, post_no: str) -> bool:
        """判断帖子编号是否已被占用（发帖时用于生成不重复编号）。"""
        return self.exists(post_no=post_no)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        publisher: Optional[str] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[Post], int]:
        """按条件分页搜索帖子（按发布时间倒序，最新的在前）。"""
        conditions: List[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    # 帖子 ID 也参与搜索：用户/客服报 12 位编号就能直接定位
                    Post.post_no.like(like),
                    Post.title.like(like),
                    Post.content.like(like),
                    Post.publisher.like(like),
                )
            )
        if status:
            conditions.append(Post.status == status)
        if publisher:
            conditions.append(Post.publisher.like(f"%{publisher.strip()}%"))

        return self.list(
            conditions=conditions,
            order_by=(Post.published_at.desc(), Post.id.desc()),
            offset=offset,
            limit=limit,
        )

    def list_published(self, *, offset: int = 0, limit: int = 10) -> Tuple[List[Post], int]:
        """所有「已通过」的帖子，按发布时间倒序（首页「最新」用）。"""
        return self.list(
            conditions=[Post.status == PostStatus.APPROVED.value],
            order_by=(Post.published_at.desc(), Post.id.desc()),
            offset=offset,
            limit=limit,
        )

    def list_for_member(
        self,
        member_id: int,
        *,
        statuses: Tuple[str, ...] = (
            PostStatus.APPROVED.value,
            PostStatus.REJECTED.value,
        ),
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[Post], int]:
        """会员自己的帖子（默认「已通过 + 已拒绝」），按发布时间倒序。

        已拒绝的也要出现在「我的帖子」里，用户才能看到状态、修改后重新提交。
        """
        return self.list(
            conditions=[
                Post.member_id == member_id,
                Post.status.in_(statuses),
            ],
            order_by=(Post.published_at.desc(), Post.id.desc()),
            offset=offset,
            limit=limit,
        )


class PostFavoriteRepository(BaseRepository[PostFavorite]):
    """帖子收藏的数据访问对象：`会员 × 帖子` 的关系表。"""

    def __init__(self, db: Session) -> None:
        super().__init__(PostFavorite, db)

    def find(self, member_id: int, post_id: int) -> Optional[PostFavorite]:
        """某会员对某帖子的收藏记录；没收藏返回 None。"""
        return self.get_by(member_id=member_id, post_id=post_id)

    def favorited_post_ids(self, member_id: int, post_ids: list[int]) -> set[int]:
        """这批帖子里，该会员收藏了哪些（列表页一次性标状态，避免逐条查）。"""
        if not post_ids:
            return set()
        stmt = select(PostFavorite.post_id).where(
            PostFavorite.member_id == member_id,
            PostFavorite.post_id.in_(list(post_ids)),
        )
        return set(self.db.execute(stmt).scalars().all())

    def count_for(self, post_id: int) -> int:
        """某条帖子被收藏了多少次。"""
        stmt = (
            select(func.count())
            .select_from(PostFavorite)
            .where(PostFavorite.post_id == post_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def counts_for(self, post_ids: list[int]) -> dict[int, int]:
        """批量取收藏数（列表页用，避免逐条 count）。"""
        if not post_ids:
            return {}
        stmt = (
            select(PostFavorite.post_id, func.count())
            .where(PostFavorite.post_id.in_(list(post_ids)))
            .group_by(PostFavorite.post_id)
        )
        return {row[0]: int(row[1]) for row in self.db.execute(stmt).all()}

    def list_posts(
        self,
        member_id: int,
        *,
        statuses: Tuple[str, ...] = (PostStatus.APPROVED.value,),
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[Post], int]:
        """该会员收藏的帖子，按收藏时间倒序（最近收藏的在前）。

        只出指定状态的帖子：收藏后被拒 / 被删的内容不再出现在「我的收藏」里。
        """
        conditions = [
            PostFavorite.member_id == member_id,
            Post.status.in_(statuses),
        ]

        count_stmt = (
            select(func.count())
            .select_from(Post)
            .join(PostFavorite, PostFavorite.post_id == Post.id)
            .where(*conditions)
        )
        stmt = (
            select(Post)
            .join(PostFavorite, PostFavorite.post_id == Post.id)
            .where(*conditions)
            .order_by(PostFavorite.created_at.desc(), PostFavorite.id.desc())
            .offset(offset)
            .limit(limit)
        )

        total = int(self.db.execute(count_stmt).scalar_one())
        items = list(self.db.execute(stmt).scalars().unique().all())
        return items, total
