"""文章管理仓储：所有针对 article_post_info / article_post_favorite 的查询都集中在这里。"""

from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.post import Post, PostFavorite, PostLike, PostStatus
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

    def list_hot(self, *, offset: int = 0, limit: int = 10) -> Tuple[List[Post], int]:
        """所有「已通过」的帖子，按访问量倒序（访问量相同再按发布时间倒序）。"""
        return self.list(
            conditions=[Post.status == PostStatus.APPROVED.value],
            order_by=(
                Post.view_count.desc(),
                Post.published_at.desc(),
                Post.id.desc(),
            ),
            offset=offset,
            limit=limit,
        )

    def list_published_since(
        self, *, since: datetime, limit: int = 200
    ) -> List[Post]:
        """某个时间点之后发布的「已通过」帖子（推荐随机抽取的候选集）。

        不做随机排序：`random()` / `rand()` 各家数据库写法不一样，
        这里按发布时间倒序取一批候选，交给服务层用 Python 随机抽样。
        """
        items, _ = self.list(
            conditions=[
                Post.status == PostStatus.APPROVED.value,
                Post.published_at >= since,
            ],
            order_by=(Post.published_at.desc(), Post.id.desc()),
            offset=0,
            limit=limit,
        )
        return items

    def increment_view(self, post_id: int) -> int:
        """访问量 +1，返回最新值。

        用 SQL 侧自增（`view_count = view_count + 1`）而不是「读出来加一再写回」，
        并发打开详情页时不会互相覆盖。
        """
        self.db.execute(
            update(Post).where(Post.id == post_id).values(view_count=Post.view_count + 1)
        )
        value = self.db.execute(
            select(Post.view_count).where(Post.id == post_id)
        ).scalar_one()
        return int(value)

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


class PostLikeRepository(BaseRepository[PostLike]):
    """帖子点赞的数据访问对象：`会员 × 帖子` 的关系表。"""

    def __init__(self, db: Session) -> None:
        super().__init__(PostLike, db)

    def find(self, member_id: int, post_id: int) -> Optional[PostLike]:
        """某会员对某帖子的点赞记录；没点过返回 None。"""
        return self.get_by(member_id=member_id, post_id=post_id)

    def liked_post_ids(self, member_id: int, post_ids: list[int]) -> set[int]:
        """这批帖子里，该会员点过赞的（列表页一次性标状态）。"""
        if not post_ids:
            return set()
        stmt = select(PostLike.post_id).where(
            PostLike.member_id == member_id,
            PostLike.post_id.in_(list(post_ids)),
        )
        return set(self.db.execute(stmt).scalars().all())

    def count_for(self, post_id: int) -> int:
        """某条帖子被点了多少个赞。"""
        stmt = (
            select(func.count())
            .select_from(PostLike)
            .where(PostLike.post_id == post_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def counts_for(self, post_ids: list[int]) -> dict[int, int]:
        """批量取点赞数（列表页用，避免逐条 count）。"""
        if not post_ids:
            return {}
        stmt = (
            select(PostLike.post_id, func.count())
            .where(PostLike.post_id.in_(list(post_ids)))
            .group_by(PostLike.post_id)
        )
        return {row[0]: int(row[1]) for row in self.db.execute(stmt).all()}

    def list_posts_with_received_likes(
        self, member_id: int, *, offset: int = 0, limit: int = 10
    ) -> Tuple[List[Post], int]:
        """某会员「被点赞过」的帖子：自己发布的、至少收到一个赞的，按获赞数倒序。

        用相关子查询算每条帖子的点赞数再排序，避免 GROUP BY 在不同数据库上的差异。
        """
        like_count = (
            select(func.count(PostLike.id))
            .where(PostLike.post_id == Post.id)
            .correlate(Post)
            .scalar_subquery()
        )
        conditions = [Post.member_id == member_id, like_count > 0]

        count_stmt = select(func.count()).select_from(Post).where(*conditions)
        stmt = (
            select(Post)
            .where(*conditions)
            .order_by(like_count.desc(), Post.published_at.desc(), Post.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = int(self.db.execute(count_stmt).scalar_one())
        items = list(self.db.execute(stmt).scalars().unique().all())
        return items, total

    def count_received(self, member_id: int) -> int:
        """某会员「收到」的赞总数：他自己所有帖子被点赞的次数合计。

        不看帖子状态：待审核 / 已拒绝的帖子也可能被别人点过赞，一并算进去。
        """
        stmt = (
            select(func.count())
            .select_from(PostLike)
            .join(Post, Post.id == PostLike.post_id)
            .where(Post.member_id == member_id)
        )
        return int(self.db.execute(stmt).scalar_one())
