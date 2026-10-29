"""文章管理服务：用户发帖、后台列表与审核。

事务边界：仓储只 flush，commit 统一在本层执行。
"""

import random
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.exceptions import BusinessError, ForbiddenError, NotFoundError
from app.core.logging import logger
from app.core.storage import save_image
from app.core.utils import generate_post_no, utcnow
from app.models.member import Member
from app.models.official_article import OfficialArticle, OfficialArticleStatus
from app.models.message import MessageType
from app.models.post import CommentStatus, Post, PostComment, PostStatus
from app.repositories.member_repository import MemberFollowRepository
from app.models.official_article import ARTICLE_ID_OFFSET
from app.services.article_feed import (
    article_id_from,
    article_out,
    comment_sort_key,
    is_article_id,
    like_sort_key,
    merge_feed,
    published_sort_key,
    view_sort_key,
)
from app.services.message_service import MessageService
from app.repositories.official_article_interaction_repository import (
    ArticleFavoriteRepository,
    ArticleLikeRepository,
)
from app.repositories.official_article_comment_repository import (
    OfficialArticleCommentRepository,
)
from app.repositories.official_article_repository import OfficialArticleRepository
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


def _ts(value) -> float:
    """时间 → 时间戳（naive 视为 UTC），用于跨表按时间混排。"""
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


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
        self.articles = OfficialArticleRepository(db)
        self.article_likes = ArticleLikeRepository(db)
        self.article_favorites = ArticleFavoriteRepository(db)
        self.article_comments = OfficialArticleCommentRepository(db)
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
        # 发布人昵称实时取会员当前昵称（库里 publisher 是发帖时的快照）
        self._refresh_post_publishers(posts)

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

    def _refresh_post_publishers(self, posts: List[Post]) -> None:
        """发布人昵称实时取会员当前昵称（库里 publisher 是发帖时的快照）。

        后台列表 / 详情也要看到新昵称，所以这里独立成一个可复用的方法；
        用 `set_committed_value` 只改内存，不标记脏、不写库。
        """
        for post in posts:
            if post.member is not None and post.member.display_name:
                set_committed_value(post, "publisher", post.member.display_name)

    def get_post(self, post_id: int) -> Post:
        post = self.get_or_404(post_id)
        self._refresh_post_publishers([post])
        return post

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
        items, total = self.posts.search(
            keyword=keyword,
            status=status_value,
            publisher=publisher,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        self._refresh_post_publishers(items)
        return items, total

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
        offset = (page - 1) * page_size
        fetch = offset + page_size
        items, total = self.posts.list_published(offset=0, limit=fetch)
        self._mark_interactions(items, viewer)
        # 官号文章也算「最新」的一部分：按发布时间一起排
        articles, article_total = self.articles.public_page(offset=0, limit=fetch)
        merged = merge_feed(
            posts=items,
            article_items=self._article_dicts(articles, viewer),
            sort_key=published_sort_key,
        )
        return merged[offset : offset + page_size], total + article_total

    def get_public_post(
        self, post_id: int, *, viewer: Optional[Member] = None
    ) -> Post:
        """公开的详情（App 从列表 / 消息点进来用）：只出已通过的内容。

        `post_id` 带文章偏移时按官号文章返回（字段形状与帖子一致）。
        """
        if is_article_id(post_id):
            return self._public_article(article_id_from(post_id), viewer)

        post = self.get_or_404(post_id)
        if post.status != PostStatus.APPROVED.value:
            raise NotFoundError(f"帖子不存在: id={post_id}")
        self._mark_interactions([post], viewer)
        return post

    def get_member_post(self, post_id: int, member: Member) -> Post:
        """作者本人查看自己的帖子（**不限状态**）。

        用于「未通过审核」的消息点进来直接改稿：公开详情只出已通过的，
        走这里才能拿到被拒绝的动态内容与图片。
        """
        post = self.get_or_404(post_id)
        if post.member_id != member.id:
            raise ForbiddenError("只能查看自己发布的动态")
        self._mark_interactions([post], member)
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
        offset = (page - 1) * page_size
        fetch = offset + page_size
        items, total = self.posts.list_published_by_authors(
            author_ids,
            offset=0,
            limit=fetch,
        )
        self._mark_interactions(items, viewer)
        # 关注的人发的官号文章也一起出现
        articles, article_total = self.articles.public_page(
            member_ids=author_ids, offset=0, limit=fetch
        )
        merged = merge_feed(
            posts=items,
            article_items=self._article_dicts(articles, viewer),
            sort_key=published_sort_key,
        )
        return merged[offset : offset + page_size], total + article_total

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
        offset = (page - 1) * page_size
        fetch = offset + page_size
        items, total = self.posts.list_hot(offset=0, limit=fetch)
        self._mark_interactions(items, viewer)
        # 官号文章按访问量一起排
        articles, article_total = self.articles.public_hot_page(offset=0, limit=fetch)
        merged = merge_feed(
            posts=items,
            article_items=self._article_dicts(articles, viewer),
            sort_key=view_sort_key,
        )
        return merged[offset : offset + page_size], total + article_total

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
        articles = self.articles.public_since(since=since, limit=self.RECOMMEND_POOL_SIZE)
        # 帖子和官号文章放在同一个池子里抽样，推荐位两种内容都会出现
        merged = merge_feed(
            posts=pool,
            article_items=self._article_dicts(articles, viewer),
            sort_key=published_sort_key,
        )
        picked = random.sample(merged, min(size, len(merged)))
        self._mark_interactions([item for item in picked if not isinstance(item, dict)], viewer)
        return picked

    def _article_dicts(
        self,
        articles: List,
        viewer: Optional[Member] = None,
        *,
        comment_counts: Optional[dict] = None,
    ) -> List[dict]:
        """把官号文章批量转成帖子出参字典，并补上点赞 / 收藏的数量与状态。"""
        if not articles:
            return []
        ids = [int(article.id) for article in articles]
        like_counts = self.article_likes.counts_for(ids)
        favorite_counts = self.article_favorites.counts_for(ids)
        liked = (
            self.article_likes.marked_article_ids(viewer.id, ids)
            if viewer is not None
            else set()
        )
        favorited = (
            self.article_favorites.marked_article_ids(viewer.id, ids)
            if viewer is not None
            else set()
        )
        counts = comment_counts or {}
        return [
            article_out(
                article,
                like_count=like_counts.get(int(article.id), 0),
                favorite_count=favorite_counts.get(int(article.id), 0),
                is_liked=int(article.id) in liked,
                is_favorited=int(article.id) in favorited,
                comment_count=counts.get(int(article.id), 0),
            )
            for article in articles
        ]

    def _article_or_404(self, article_id: int):
        article = self.articles.get_public(article_id)
        if article is None:
            raise NotFoundError(f"官方文章不存在: id={article_id}")
        return article

    def _public_article(
        self, article_id: int, viewer: Optional[Member] = None
    ) -> dict:
        """官号文章详情：转成帖子出参形状返回（带点赞 / 收藏状态）。"""
        return self._article_dicts([self._article_or_404(article_id)], viewer)[0]

    def record_view(self, post_id: int):
        """记录一次访问（详情页打开时调用），返回带最新 `view_count` 的内容。"""
        if is_article_id(post_id):
            article_id = article_id_from(post_id)
            self.articles.increment_view(article_id)
            self.db.commit()
            return self._public_article(article_id)

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
        offset = (page - 1) * page_size
        fetch = offset + page_size
        items, total = self.posts.list_for_member(
            member_id,
            statuses=self.OWNER_STATUSES if include_hidden else self.PUBLIC_STATUSES,
            offset=0 if not include_hidden else offset,
            limit=fetch if not include_hidden else page_size,
        )
        self._mark_interactions(items, viewer)
        if include_hidden:
            # 「我的发布」只管自己的动态，官号文章在后台管理，这里不混进来
            return items, total
        # 作者主页：这个人的官号文章也一起列出来
        articles, article_total = self.articles.public_page(
            member_id=member_id, offset=0, limit=fetch
        )
        merged = merge_feed(
            posts=items,
            article_items=self._article_dicts(articles, viewer),
            sort_key=published_sort_key,
        )
        return merged[offset : offset + page_size], total + article_total

    # ------------------------- 收藏 -------------------------
    def _favorite_article(self, article_id: int, member: Member) -> dict:
        """收藏官号文章（幂等）。"""
        article = self._article_or_404(article_id)
        if self.article_favorites.find(member.id, article.id) is None:
            self.article_favorites.create(member_id=member.id, article_id=article.id)
            self.db.commit()
        return self._article_dicts([article], member)[0]

    def _unfavorite_article(self, article_id: int, member: Member) -> dict:
        article = self._article_or_404(article_id)
        favorite = self.article_favorites.find(member.id, article.id)
        if favorite is not None:
            self.article_favorites.delete(favorite)
            self.db.commit()
        return self._article_dicts([article], member)[0]

    def favorite(self, post_id: int, member: Member) -> Post:
        """收藏帖子 / 官号文章（幂等）。

        只允许收藏审核通过的内容 —— 待审核 / 已拒绝的对外并不存在，
        收藏了也没有意义。官号文章用带偏移的 id 调用，内部转成文章收藏。
        """
        if is_article_id(post_id):
            return self._favorite_article(article_id_from(post_id), member)

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
        if is_article_id(post_id):
            return self._unfavorite_article(article_id_from(post_id), member)

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
        """给帖子 / 官号文章点赞（幂等）：重复点赞不会多出记录。"""
        if is_article_id(post_id):
            return self._like_article(article_id_from(post_id), member)

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
                    f"{member.display_name} 赞了你的动态",
                    post.title,
                    post_id=post.id,
                    actor=member,
                )

        post.is_liked = True
        post.like_count = self.likes.count_for(post.id)
        return post

    def _like_article(self, article_id: int, member: Member) -> dict:
        """给官号文章点赞，首次点赞给发布人发通知。"""
        article = self._article_or_404(article_id)
        if self.article_likes.find(member.id, article.id) is None:
            self.article_likes.create(member_id=member.id, article_id=article.id)
            self.db.commit()
            if article.member_id and article.member_id != member.id:
                self._push_message(
                    article.member_id,
                    MessageType.LIKE,
                    f"{member.display_name} 赞了你的文章",
                    article.title,
                    post_id=None,
                    actor=member,
                )
        return self._article_dicts([article], member)[0]

    def _unlike_article(self, article_id: int, member: Member) -> dict:
        article = self._article_or_404(article_id)
        like = self.article_likes.find(member.id, article.id)
        if like is not None:
            self.article_likes.delete(like)
            self.db.commit()
        return self._article_dicts([article], member)[0]

    def unlike(self, post_id: int, member: Member) -> Post:
        """取消点赞（幂等）：本来就没点过也返回成功。"""
        if is_article_id(post_id):
            return self._unlike_article(article_id_from(post_id), member)

        post = self.get_or_404(post_id)

        like = self.likes.find(member.id, post.id)
        if like is not None:
            self.likes.delete(like)
            self.db.commit()

        post.is_liked = False
        post.like_count = self.likes.count_for(post.id)
        return post

    def received_likes(self, member_id: int) -> int:
        """某会员的获赞总数：自己所有帖子 + 官号文章被点赞的次数合计。"""
        return self.likes.count_received(member_id) + self.article_likes.count_received(
            member_id
        )

    def list_received_like_posts(
        self,
        member_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """「获赞的帖子」列表：我发布的帖子 + 官号文章，按获赞数倒序。"""
        offset = (page - 1) * page_size
        fetch = offset + page_size
        items, total = self.likes.list_posts_with_received_likes(
            member_id,
            offset=0,
            limit=fetch,
        )
        self._mark_interactions(items, viewer)
        # 官号文章收到的赞也一并列出
        article_rows, article_total = self.article_likes.list_articles_with_likes(
            member_id, offset=0, limit=fetch
        )
        article_counts = {article_id: count for article_id, count in article_rows}
        articles = (
            self.articles.all(
                conditions=[
                    OfficialArticle.id.in_(list(article_counts)),
                    OfficialArticle.status == OfficialArticleStatus.APPROVED.value,
                ]
            )
            if article_counts
            else []
        )
        merged = merge_feed(
            posts=items,
            article_items=self._article_dicts(articles, viewer),
            sort_key=like_sort_key,
        )
        return merged[offset : offset + page_size], total + article_total

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
        offset = (page - 1) * page_size
        fetch = offset + page_size
        # 帖子收藏 + 文章收藏，按「收藏时间」混排
        post_rows, post_total = self.favorites.list_favorited_entries(
            member_id,
            statuses=self.PUBLIC_STATUSES,
            offset=0,
            limit=fetch,
        )
        article_rows, article_total = self.article_favorites.list_favorited_entries(
            member_id, offset=0, limit=fetch
        )
        entries = [(_ts(created), "post", post_id) for post_id, created in post_rows]
        entries += [(_ts(created), "article", article_id) for article_id, created in article_rows]
        entries.sort(key=lambda row: row[0], reverse=True)
        page_rows = entries[offset : offset + page_size]

        post_ids = [row[2] for row in page_rows if row[1] == "post"]
        article_ids = [row[2] for row in page_rows if row[1] == "article"]
        posts = (
            self.posts.all(
                conditions=[
                    Post.id.in_(post_ids),
                    Post.status == PostStatus.APPROVED.value,
                ]
            )
            if post_ids
            else []
        )
        articles = (
            self.articles.all(
                conditions=[
                    OfficialArticle.id.in_(article_ids),
                    OfficialArticle.status == OfficialArticleStatus.APPROVED.value,
                ]
            )
            if article_ids
            else []
        )
        self._mark_interactions(posts, viewer)
        article_items = {
            item["article_id"]: item for item in self._article_dicts(articles, viewer)
        }
        post_map = {int(post.id): post for post in posts}

        result: List = []
        for _created, kind, row_id in page_rows:
            if kind == "post" and row_id in post_map:
                result.append(post_map[row_id])
            elif kind == "article" and row_id in article_items:
                result.append(article_items[row_id])
        return result, post_total + article_total

    # ------------------------- 评论 -------------------------
    def get_comment_or_404(self, comment_id: int) -> PostComment:
        item = self.comments.get(comment_id)
        if item is None:
            raise NotFoundError(f"评论不存在: id={comment_id}")
        return item

    def create_comment(
        self, post_id: int, payload: PostCommentCreate, member: Member
    ) -> PostComment:
        """发表评论：默认「待审核」，后台通过后前台才展示。

        `post_id` 带文章偏移时，评论挂在官号文章下（功能与帖子完全一致）。
        """
        if is_article_id(post_id):
            return self._create_article_comment(article_id_from(post_id), payload, member)

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

    def _article_comment_out(self, item) -> dict:
        """文章评论出参：`id` / `post_id` 都带偏移，与帖子评论同一套 id 空间。"""
        return {
            "id": ARTICLE_ID_OFFSET + int(item.id),
            "post_id": ARTICLE_ID_OFFSET + int(item.article_id),
            "post_title": item.post_title,
            "post_no": item.post_no,
            "member_id": item.member_id,
            "publisher": (
                item.member.display_name
                if item.member is not None and item.member.display_name
                else item.publisher
            ),
            "publisher_avatar": item.publisher_avatar,
            "content": item.content,
            "status": item.status,
            "created_at": item.created_at,
        }

    def _create_article_comment(self, article_id: int, payload, member: Member) -> dict:
        """在官号文章下发评论（默认待审核）。"""
        article = self._article_or_404(article_id)
        item = self.article_comments.create(
            article_id=article.id,
            member_id=member.id,
            publisher=member.display_name,
            content=payload.content,
            status=CommentStatus.PENDING.value,
        )
        self.db.commit()
        self.db.refresh(item)
        return self._article_comment_out(item)

    def list_comments(
        self, post_id: int, *, page: int = 1, page_size: int = 20
    ):
        """某条帖子 / 官号文章下**已通过**的评论，最新的在前。"""
        if is_article_id(post_id):
            article = self._article_or_404(article_id_from(post_id))
            items, total = self.article_comments.list_by_article(
                article.id,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return [self._article_comment_out(item) for item in items], total

        self.get_or_404(post_id)
        items, total = self.comments.list_by_post(
            post_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        self._refresh_comment_publishers(items)
        return items, total

    def _refresh_comment_publishers(self, items: List[PostComment]) -> None:
        """评论人昵称实时取会员当前昵称（库里存的是发评论时的快照）。

        和帖子一样用 `set_committed_value`：只改内存里的出参值，不标记脏、不写库。
        """
        for item in items:
            if item.member is not None and item.member.display_name:
                set_committed_value(item, "publisher", item.member.display_name)

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
        offset = (page - 1) * page_size
        fetch = offset + page_size

        # post_id 传的是「带偏移的文章 id」时，只查这篇文章的评论
        only_article = post_id is not None and is_article_id(post_id)

        post_items: List = []
        post_total = 0
        if not only_article:
            post_items, post_total = self.comments.search(
                keyword=keyword,
                status=status_value,
                post_id=post_id,
                offset=0,
                limit=fetch,
            )

        article_items, article_total = self.article_comments.search(
            keyword=keyword,
            status=status_value,
            article_id=article_id_from(post_id) if only_article else None,
            offset=0,
            limit=fetch,
        )

        # 两边的评论按时间倒序混排（后台列表一页能看到全部内容）
        merged = sorted(
            list(post_items)
            + [self._article_comment_out(item) for item in article_items],
            key=lambda item: (
                item.created_at if not isinstance(item, dict) else item["created_at"],
                item.id if not isinstance(item, dict) else item["id"],
            ),
            reverse=True,
        )
        page_items = merged[offset : offset + page_size]
        post_side = [item for item in page_items if not isinstance(item, dict)]
        self._refresh_comment_publishers(post_side)
        return page_items, post_total + article_total

    def audit_comment(self, comment_id: int, status: CommentStatus) -> PostComment:
        """审核评论：待审核 → 已通过 / 已拒绝，结果是终态。

        带文章偏移的 id 走官号文章评论（同一套审核规则）。
        """
        if is_article_id(comment_id):
            return self._audit_article_comment(article_id_from(comment_id), status)

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

        # 通过后才通知动态作者「有人评论了你的动态」——
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
                f"{item.publisher or '有人'} 评论了你的动态",
                item.content,
                post_id=item.post_id,
                from_member_id=item.member_id,
                from_nickname=item.publisher or "",
            )
        return item

    def _audit_article_comment(self, comment_id: int, status: CommentStatus):
        """审核官号文章下的评论，规则与帖子评论一致。"""
        item = self.article_comments.get(comment_id)
        if item is None:
            raise NotFoundError(f"评论不存在: id={comment_id}")
        if item.status != CommentStatus.PENDING.value:
            raise BusinessError("该评论已审核，结果不可更改")

        item.status = status.value
        self.db.commit()
        self.db.refresh(item)

        approved = status is CommentStatus.APPROVED
        offset_post_id = item.post_id

        # 审核结果通知评论人（点进去就是这篇文章的详情）
        if item.member_id:
            self._push_message(
                item.member_id,
                MessageType.COMMENT_AUDIT,
                "评论已通过审核" if approved else "评论未通过审核",
                item.content,
                post_id=offset_post_id,
            )

        # 通过后才通知文章发布人「有人评论了你的文章」
        article = item.article
        if (
            approved
            and article is not None
            and article.member_id
            and article.member_id != item.member_id
        ):
            self._push_message(
                article.member_id,
                MessageType.COMMENT,
                f"{item.publisher or '有人'} 评论了你的文章",
                item.content,
                post_id=offset_post_id,
                actor=item.member,
            )
        return self._article_comment_out(item)

    def delete_comment(self, comment_id: int) -> None:
        """删除评论（后台）。"""
        if is_article_id(comment_id):
            article_comment = self.article_comments.get(article_id_from(comment_id))
            if article_comment is None:
                raise NotFoundError(f"评论不存在: id={comment_id}")
            self.article_comments.delete(article_comment)
            self.db.commit()
            return

        item = self.get_comment_or_404(comment_id)
        self.comments.delete(item)
        self.db.commit()

    def received_comments(self, member_id: int) -> int:
        """某会员的被评论总数：帖子 + 官号文章收到的已通过评论合计。"""
        return self.comments.count_received(
            member_id
        ) + self.article_comments.count_received(member_id)

    def list_commented_posts(
        self,
        member_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
        viewer: Optional[Member] = None,
    ) -> Tuple[List[Post], int]:
        """「被评论的帖子」列表：我发布的帖子 + 官号文章，按评论数倒序。"""
        offset = (page - 1) * page_size
        fetch = offset + page_size
        items, total = self.comments.list_posts_with_comments(
            member_id,
            offset=0,
            limit=fetch,
        )
        self._mark_interactions(items, viewer)
        # 官号文章收到的评论也一并列出
        article_rows, article_total = self.article_comments.list_articles_with_comments(
            member_id, offset=0, limit=fetch
        )
        comment_counts = {article_id: count for article_id, count in article_rows}
        articles = (
            self.articles.all(
                conditions=[
                    OfficialArticle.id.in_(list(comment_counts)),
                    OfficialArticle.status == OfficialArticleStatus.APPROVED.value,
                ]
            )
            if comment_counts
            else []
        )
        merged = merge_feed(
            posts=items,
            article_items=self._article_dicts(
                articles, viewer, comment_counts=comment_counts
            ),
            sort_key=comment_sort_key,
        )
        return merged[offset : offset + page_size], total + article_total

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
                "动态已通过审核"
                if status is PostStatus.APPROVED
                else "动态未通过审核",
                post.title,
                post_id=post.id,
            )
        # 出参里的发布人也用最新昵称
        self._refresh_post_publishers([post])
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
