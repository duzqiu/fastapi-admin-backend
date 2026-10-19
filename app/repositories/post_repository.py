"""文章管理仓储：所有针对 article_post_info 表的查询都集中在这里。"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.post import Post, PostStatus
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

    def list_published_by_member(
        self, member_id: int, *, offset: int = 0, limit: int = 10
    ) -> Tuple[List[Post], int]:
        """某个会员**已发布**（审核通过）的帖子，按发布时间倒序。"""
        return self.list(
            conditions=[
                Post.member_id == member_id,
                Post.status == PostStatus.APPROVED.value,
            ],
            order_by=(Post.published_at.desc(), Post.id.desc()),
            offset=offset,
            limit=limit,
        )
