"""文章管理服务：用户发帖、后台列表与审核。

事务边界：仓储只 flush，commit 统一在本层执行。
"""

import random
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ForbiddenError, NotFoundError
from app.core.logging import logger
from app.core.storage import save_image
from app.core.utils import generate_post_no, utcnow
from app.models.member import Member
from app.models.message import MessageType
from app.models.post import CommentStatus, Post, PostComment, PostStatus
from app.repositories.member_repository import MemberFollowRepository
from app.services.message_service import MessageService
from app.repositories.post_repository import (
    PostCommentRepository,
    PostFavoriteRepository,
    PostLikeRepository,
    PostRepository,
)
from app.schemas.post import PostCommentCreate, PostCreate, PostUpdate

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
        self.comments = PostCommentRepository(db)
        self.follows = MemberFollowRepository(db)
        self.message_service = MessageService(db)

    def _push_message(
        self,
        recipient_id: Optional[int],
        msg_type: str,
        title: str,
        content: str = "",
        *,
        post_id: Optional[int] = None,
        actor: Optional[Member] = None,
        from_member_id: Optional[int] = None,
        from_nickname: str = "",
    ) -> None:
        """写站内通知的旁路：任何异常都不影响点赞 / 评论 / 审核主流程。"""
        try:
            self.message_service.push(
                recipient_id=recipient_id,
                msg_type=msg_type,
                title=title,
                content=content,
                post_id=post_id,
                from_member_id=(
                    from_member_id
                    if from_member_id is not None
                    else (actor.id if actor else None)
                ),
                from_nickname=(
                    from_nickname or (actor.display_name if actor else "")
                ),
            )
        except Exception:  # noqa: BLE001 - 通知失败不该影响业务
            logger.warning("写入站内消息失败: type=%s", msg_type, exc_info=True)

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
        # 评论数只算「已通过」的（前台看到的条数）
        comment_counts = self.comments.counts_for(ids)
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
        followed = self.follows.following_ids(member.id) if member is not None else set()
        for post in posts:
            post.like_count = like_counts.get(post.id, 0)
            post.is_liked = post.id in liked
            post.favorite_count = favorite_counts.get(post.id, 0)
            post.is_favorited = post.id in favorited
            post.comment_count = comment_counts.get(post.id, 0)
            # 匿名帖没有作者，恒为未关注
            post.is_following = bool(post.member_id) and post.member_id in followed

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

    def get_public_post(
        self, post_id: int, *, viewer: Optional[Member] = None
    ) -> Post:
        """公开的帖子详情（App 从消息点进来用）：只出已通过的。"""
        post = self.get_or_404(post_id)
        if post.status != PostStatus.APPROVED.value:
            raise NotFoundError(f"帖子不存在: id={post_id}")
        self._mark_interactions([post], viewer)
        return post

    def list_following_posts(
        self,
        member_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """「关注」页：我关注的人发布的已通过帖子，按发布时间倒序。"""
        author_ids = sorted(self.follows.following_ids(member_id))
        items, total = self.posts.list_published_by_authors(
            author_ids,
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
            # 首次点赞才通知作者；自己赞自己不打扰
            if post.member_id and post.member_id != member.id:
                self._push_message(
                    post.member_id,
                    MessageType.LIKE,
                    f"{member.display_name} 赞了你的帖子",
                    post.title,
                    post_id=post.id,
                    actor=member,
                )

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

    # ------------------------- 评论 -------------------------
    def get_comment_or_404(self, comment_id: int) -> PostComment:
        item = self.comments.get(comment_id)
        if item is None:
            raise NotFoundError(f"评论不存在: id={comment_id}")
        return item

    def create_comment(
        self, post_id: int, payload: PostCommentCreate, member: Member
    ) -> PostComment:
        """发表评论：默认「待审核」，后台通过后前台才展示。"""
        post = self.get_or_404(post_id)
        if post.status != PostStatus.APPROVED.value:
            raise BusinessError("只能在审核通过的帖子下评论")

        item = self.comments.create(
            post_id=post.id,
            member_id=member.id,
            publisher=member.display_name,
            content=payload.content,
            status=CommentStatus.PENDING.value,
        )
        self.db.commit()
        self.db.refresh(item)
        # 评论通知不在这里发：等后台审核通过、真正展示给作者时再发
        return item

    def list_comments(
        self, post_id: int, *, page: int = 1, page_size: int = 20
    ) -> Tuple[List[PostComment], int]:
        """某条帖子下**已通过**的评论（前台详情页用），最新的在前。"""
        self.get_or_404(post_id)
        return self.comments.list_by_post(
            post_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def list_all_comments(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        status: Optional[Union[str, CommentStatus]] = None,
        post_id: Optional[int] = None,
    ) -> Tuple[List[PostComment], int]:
        """后台评论管理：按状态 / 帖子 / 关键字筛选。"""
        status_value = status.value if isinstance(status, CommentStatus) else status
        return self.comments.search(
            keyword=keyword,
            status=status_value,
            post_id=post_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def audit_comment(self, comment_id: int, status: CommentStatus) -> PostComment:
        """审核评论：待审核 → 已通过 / 已拒绝，结果是终态。"""
        item = self.get_comment_or_404(comment_id)
        if item.status != CommentStatus.PENDING.value:
            raise BusinessError("该评论已审核，结果不可更改")

        item.status = status.value
        self.db.commit()
        self.db.refresh(item)

        approved = status is CommentStatus.APPROVED

        # 审核结果通知评论人
        if item.member_id:
            self._push_message(
                item.member_id,
                MessageType.COMMENT_AUDIT,
                "评论已通过审核" if approved else "评论未通过审核",
                item.content,
                post_id=item.post_id,
            )

        # 通过后才通知帖子作者「有人评论了你的帖子」——
        # 这时评论已经能在 App 里看到，通知点进去不会扑空
        post = item.post
        if (
            approved
            and post is not None
            and post.member_id
            and post.member_id != item.member_id
        ):
            self._push_message(
                post.member_id,
                MessageType.COMMENT,
                f"{item.publisher or '有人'} 评论了你的帖子",
                item.content,
                post_id=item.post_id,
                from_member_id=item.member_id,
                from_nickname=item.publisher or "",
            )
        return item

    def delete_comment(self, comment_id: int) -> None:
        """删除评论（后台）。"""
        item = self.get_comment_or_404(comment_id)
        self.comments.delete(item)
        self.db.commit()

    def received_comments(self, member_id: int) -> int:
        """某会员的被评论总数：自己所有帖子收到的已通过评论合计。"""
        return self.comments.count_received(member_id)

    def list_commented_posts(
        self,
        member_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """「被评论的帖子」列表：我发布的、收到过已通过评论的帖子，按评论数倒序。"""
        items, total = self.comments.list_posts_with_comments(
            member_id,
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

        # 审核结果通知作者
        if post.member_id:
            self._push_message(
                post.member_id,
                MessageType.POST_AUDIT,
                "帖子已通过审核"
                if status is PostStatus.APPROVED
                else "帖子未通过审核",
                post.title,
                post_id=post.id,
            )
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
