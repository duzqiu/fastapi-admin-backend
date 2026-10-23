"""文章管理服务：用户发帖、后台列表与审核。

事务边界：仓储只 flush，commit 统一在本层执行。
"""

import random
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ForbiddenError, NotFoundError
from app.core.storage import save_image
from app.core.utils import generate_post_no, utcnow
from app.models.member import Member
from app.models.post import Post, PostStatus
from app.repositories.post_repository import (
    PostFavoriteRepository,
    PostLikeRepository,
    PostRepository,
)
from app.schemas.post import PostCreate, PostUpdate

# 审核状态的中文文案（报错信息里用，避免再引一次 schema）
_STATUS_TEXT = {
    PostStatus.PENDING.value: "待审核",
    PostStatus.APPROVED.value: "已通过",
    PostStatus.REJECTED.value: "已拒绝",
}


class PostService:
    """帖子业务逻辑层。"""

    # 帖子编号查重重试次数（12 位编号空间下几乎用不到第二次）
    POST_NO_MAX_ATTEMPTS = 10

    # 他人可见：只出「已通过」，未过审的内容不对外暴露
    PUBLIC_STATUSES = (PostStatus.APPROVED.value,)

    # 作者本人可见：三种状态都返回 —— 待审核的能确认「已提交」，
    # 已拒绝的能看到原因入口（改完重提），不然改完就凭空消失了
    OWNER_STATUSES = (
        PostStatus.PENDING.value,
        PostStatus.APPROVED.value,
        PostStatus.REJECTED.value,
    )

    def __init__(self, db: Session) -> None:
        self.db = db
        self.posts = PostRepository(db)
        self.favorites = PostFavoriteRepository(db)
        self.likes = PostLikeRepository(db)

    def _mark_interactions(self, posts: List[Post], member: Optional[Member]) -> None:
        """给帖子标上「是否已点赞 / 收藏」和「被点赞 / 收藏次数」。

        这四个都是出参字段，不落库：
        - `is_liked` / `is_favorited` 按查看者算，未登录一律 False；
        - `like_count` / `favorite_count` 是全体会员的总数。
        都用一次 `IN (...)` 批量查询取回，列表页不会因此多出 N 次查询。
        """
        ids = [post.id for post in posts if post.id]
        like_counts = self.likes.counts_for(ids)
        favorite_counts = self.favorites.counts_for(ids)
        liked = (
            self.likes.liked_post_ids(member.id, ids)
            if member is not None and ids
            else set()
        )
        favorited = (
            self.favorites.favorited_post_ids(member.id, ids)
            if member is not None and ids
            else set()
        )
        for post in posts:
            post.like_count = like_counts.get(post.id, 0)
            post.is_liked = post.id in liked
            post.favorite_count = favorite_counts.get(post.id, 0)
            post.is_favorited = post.id in favorited

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

    def list_latest(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """全部已发布（审核通过）的帖子，按发布时间倒序。

        `viewer` 只是用来标「我有没有收藏过」，不影响返回哪些帖子。
        """
        items, total = self.posts.list_published(
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        self._mark_interactions(items, viewer)
        return items, total

    def list_hot(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """首页「热门」：全部已通过的帖子，按访问量倒序。

        `viewer` 只用来标「我有没有收藏过」，不影响返回哪些帖子。
        """
        items, total = self.posts.list_hot(
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        self._mark_interactions(items, viewer)
        return items, total

    # 推荐位：近一年内随机抽若干条
    RECOMMEND_SIZE = 10
    RECOMMEND_WINDOW_DAYS = 365
    # 候选池上限：先取最近这一批，再从里面随机抽，避免全表随机排序
    RECOMMEND_POOL_SIZE = 200

    def list_recommend(
        self,
        *,
        size: int = RECOMMEND_SIZE,
        viewer: Optional[Member] = None,
    ) -> List[Post]:
        """首页「推荐」：近一年内发布的已通过帖子，随机取 `size` 条。

        池子按发布时间倒序取最近 `RECOMMEND_POOL_SIZE` 条，再用 Python 抽样：
        比 `ORDER BY random()` 更容易跨数据库（随机函数各家写法不同），
        帖子量不大时也够用。
        """
        since = utcnow() - timedelta(days=self.RECOMMEND_WINDOW_DAYS)
        pool = self.posts.list_published_since(since=since, limit=self.RECOMMEND_POOL_SIZE)
        picked = random.sample(pool, min(size, len(pool)))
        self._mark_interactions(picked, viewer)
        return picked

    def record_view(self, post_id: int) -> Post:
        """记录一次访问（详情页打开时调用），返回带最新 `view_count` 的帖子。"""
        post = self.get_or_404(post_id)
        self.posts.increment_view(post.id)
        self.db.commit()
        self.db.refresh(post)
        return post

    def list_member_posts(
        self,
        member_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
        include_hidden: bool = False,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """会员的帖子列表，最新的在前。

        - `include_hidden=True`（作者本人）：待审核 / 已通过 / 已拒绝全返回，
          用户才能看到审核结果、并修改被拒绝的帖子；
        - 否则（访客）：只返回已通过的，未过审内容不对外暴露；
        - `viewer`：当前查看者，用来标「我有没有收藏过」（未登录为 None）。
        """
        items, total = self.posts.list_for_member(
            member_id,
            statuses=self.OWNER_STATUSES if include_hidden else self.PUBLIC_STATUSES,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        self._mark_interactions(items, viewer)
        return items, total

    # ------------------------- 收藏 -------------------------
    def favorite(self, post_id: int, member: Member) -> Post:
        """收藏帖子（幂等）：重复收藏不会报错，也不会多出记录。

        只允许收藏审核通过的帖子 —— 待审核 / 已拒绝的内容对外并不存在，
        收藏了也没有意义。
        """
        post = self.get_or_404(post_id)
        if post.status != PostStatus.APPROVED.value:
            raise BusinessError("只能收藏审核通过的帖子")

        if self.favorites.find(member.id, post.id) is None:
            self.favorites.create(member_id=member.id, post_id=post.id)
            self.db.commit()

        post.is_favorited = True
        post.favorite_count = self.favorites.count_for(post.id)
        return post

    def unfavorite(self, post_id: int, member: Member) -> Post:
        """取消收藏（幂等）：本来就没收藏也返回成功。"""
        post = self.get_or_404(post_id)

        favorite = self.favorites.find(member.id, post.id)
        if favorite is not None:
            self.favorites.delete(favorite)
            self.db.commit()

        post.is_favorited = False
        post.favorite_count = self.favorites.count_for(post.id)
        return post

    # ------------------------- 点赞 -------------------------
    def like(self, post_id: int, member: Member) -> Post:
        """给帖子点赞（幂等）：重复点赞不会报错，也不会多出记录。

        和收藏一样，只允许给审核通过的帖子点赞。
        """
        post = self.get_or_404(post_id)
        if post.status != PostStatus.APPROVED.value:
            raise BusinessError("只能给审核通过的帖子点赞")

        if self.likes.find(member.id, post.id) is None:
            self.likes.create(member_id=member.id, post_id=post.id)
            self.db.commit()

        post.is_liked = True
        post.like_count = self.likes.count_for(post.id)
        return post

    def unlike(self, post_id: int, member: Member) -> Post:
        """取消点赞（幂等）：本来就没点过也返回成功。"""
        post = self.get_or_404(post_id)

        like = self.likes.find(member.id, post.id)
        if like is not None:
            self.likes.delete(like)
            self.db.commit()

        post.is_liked = False
        post.like_count = self.likes.count_for(post.id)
        return post

    def received_likes(self, member_id: int) -> int:
        """某会员的获赞总数：自己所有帖子被点赞的次数合计。"""
        return self.likes.count_received(member_id)

    def list_received_like_posts(
        self,
        member_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """「获赞的帖子」列表：我发布的、收到过赞的帖子，按获赞数倒序。"""
        items, total = self.likes.list_posts_with_received_likes(
            member_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        self._mark_interactions(items, viewer)
        return items, total

    def list_favorites(
        self,
        member_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """当前会员收藏的帖子，最近收藏的在前。

        只出已通过审核的：收藏后来被拒 / 被删的帖子不再出现在「我的收藏」里。
        `viewer` 用来标「是否已点赞 / 收藏」并带出两者的计数（默认就是本人）。
        """
        items, total = self.favorites.list_posts(
            member_id,
            statuses=self.PUBLIC_STATUSES,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        self._mark_interactions(items, viewer)
        return items, total

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
        """审核：只有「待审核」的帖子能审，结论一旦给出就不能再改。

        已通过 / 已拒绝都是终态：改判会让审核失去意义，也会绕过「作者修改后
        重新提交」这条唯一的翻案路径。
        """
        if status is not PostStatus.APPROVED and status is not PostStatus.REJECTED:
            raise BusinessError("审核只能改为「已通过」或「已拒绝」")

        post = self.get_or_404(post_id)
        if post.status != PostStatus.PENDING.value:
            current = _STATUS_TEXT.get(post.status, post.status)
            raise BusinessError(
                f"帖子当前是「{current}」，审核结果不可再更改"
                "（被拒绝的需作者修改后重新提交）"
            )

        self.posts.update(post, status=status.value)
        self.db.commit()
        self.db.refresh(post)
        return post

    def resubmit(self, post_id: int, payload: PostUpdate, member: Member) -> Post:
        """被拒绝的帖子：作者修改内容后重新提交，状态回到「待审核」。

        只有作者本人、且当前是「已拒绝」才允许 —— 已通过的帖子改动后必须重审，
        走这条路会让「已通过」被绕过，所以直接拒绝。
        """
        post = self.get_or_404(post_id)

        if post.member_id != member.id:
            raise ForbiddenError("只能修改自己发布的帖子")
        if post.status != PostStatus.REJECTED.value:
            raise BusinessError("只有被拒绝的帖子可以修改后重新提交")

        changes = payload.model_dump(exclude_unset=True, exclude_none=True)
        changes["status"] = PostStatus.PENDING.value
        self.posts.update(post, **changes)
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
