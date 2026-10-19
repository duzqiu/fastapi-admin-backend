"""文章管理服务：用户发帖、后台列表与审核。

事务边界：仓储只 flush，commit 统一在本层执行。
"""

from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, NotFoundError
from app.core.storage import save_image
from app.core.utils import generate_post_no, utcnow
from app.models.member import Member
from app.models.post import Post, PostStatus
from app.repositories.post_repository import PostRepository
from app.schemas.post import PostCreate


class PostService:
    """帖子业务逻辑层。"""

    # 帖子编号查重重试次数（12 位编号空间下几乎用不到第二次）
    POST_NO_MAX_ATTEMPTS = 10

    def __init__(self, db: Session) -> None:
        self.db = db
        self.posts = PostRepository(db)

    def _generate_post_no(self) -> str:
        """生成一个未被占用的 12 位随机帖子编号。

        数据库层面还有唯一索引兜底，即使极端并发下撞号也不会写入重复编号。
        """
        for _ in range(self.POST_NO_MAX_ATTEMPTS):
            candidate = generate_post_no()
            if not self.posts.post_no_taken(candidate):
                return candidate
        raise BusinessError("帖子编号生成失败，请稍后重试")

    # ------------------------- 查询 -------------------------
    def get_or_404(self, post_id: int) -> Post:
        post = self.posts.get(post_id)
        if post is None:
            raise NotFoundError(f"帖子不存在: id={post_id}")
        return post

    def get_post(self, post_id: int) -> Post:
        return self.get_or_404(post_id)

    def list_posts(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        status: Optional[Union[str, PostStatus]] = None,
        publisher: Optional[str] = None,
    ) -> Tuple[List[Post], int]:
        status_value = status.value if isinstance(status, PostStatus) else status
        return self.posts.search(
            keyword=keyword,
            status=status_value,
            publisher=publisher,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def list_member_posts(
        self, member_id: int, *, page: int = 1, page_size: int = 10
    ) -> Tuple[List[Post], int]:
        """某个会员对外展示的帖子：只出「已通过」的，最新的在前。"""
        return self.posts.list_published_by_member(
            member_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    # ------------------------- 写入 -------------------------
    def create_post(self, payload: PostCreate, member: Optional[Member] = None) -> Post:
        """用户发帖：无论谁发、内容如何，进来一律是「待审核」。"""
        publisher = payload.publisher or (member.nickname if member else "") or "匿名用户"
        post = self.posts.create(
            post_no=self._generate_post_no(),
            publisher=publisher[:50],
            member_id=member.id if member else None,
            title=payload.title,
            content=payload.content,
            images=list(payload.images or []),
            published_at=payload.published_at or utcnow(),
            status=PostStatus.PENDING.value,
        )
        self.db.commit()
        self.db.refresh(post)
        return post

    def audit(self, post_id: int, status: PostStatus) -> Post:
        """审核：只能改为「已通过」或「已拒绝」，允许在两者之间改判。"""
        if status is not PostStatus.APPROVED and status is not PostStatus.REJECTED:
            raise BusinessError("审核只能改为「已通过」或「已拒绝」")

        post = self.get_or_404(post_id)
        self.posts.update(post, status=status.value)
        self.db.commit()
        self.db.refresh(post)
        return post

    def upload_image(self, upload: UploadFile) -> Dict[str, Any]:
        """保存帖子图片，返回 `{url, filename, size}`。

        只落盘、不绑定：发帖时把返回的 `url` 放进 `images` 一起提交。
        """
        return save_image(upload, subdir="posts", prefix="post")

    def delete_post(self, post_id: int) -> None:
        post = self.get_or_404(post_id)
        self.posts.delete(post)
        self.db.commit()
