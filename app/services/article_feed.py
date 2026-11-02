"""把「官号文章」并进帖子列表（首页最新 / 热门 / 推荐、关注、作者主页）。

官号文章存在独立表 `article_official_info`，字段和帖子不完全一样。为了让 App
不区分两种内容，这里统一映射成帖子出参（`PostOut`）的形状：

- `kind = "article"` 供前端区分（详情、点赞、收藏按钮据它处理）；
- `id` 加上固定偏移 `ARTICLE_ID_OFFSET`，避免与帖子 id 撞号；
  详情接口收到带偏移的 id 时反查文章（见 `is_article_id` / `article_id_from`）；
- 点赞 / 评论 / 收藏这些互动字段一律为 0 / false —— 官号文章不参与互动。
"""

from datetime import datetime, timezone
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

from app.core.member_media import resolve_avatar_url
from app.models.official_article import ARTICLE_ID_OFFSET as _MODEL_OFFSET

#: 文章 id 在帖子列表里的偏移：`id = ARTICLE_ID_OFFSET + article.id`
#: （定义在模型里，评论等其它模块也用同一个数）
ARTICLE_ID_OFFSET = _MODEL_OFFSET


def is_article_id(value: int) -> bool:
    """这个 id 是不是「官号文章」经偏移后的 id。"""
    return int(value) >= ARTICLE_ID_OFFSET


def article_id_from(value: int) -> int:
    """把带偏移的 id 还原成真实文章 id。"""
    return int(value) - ARTICLE_ID_OFFSET


def _timestamp(value: Optional[datetime]) -> float:
    """统一成时间戳（帖子存的是 naive UTC，文章是 aware）。"""
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def article_out(
    article: Any,
    *,
    like_count: int = 0,
    favorite_count: int = 0,
    comment_count: int = 0,
    is_liked: bool = False,
    is_favorited: bool = False,
) -> dict:
    """官号文章 → 帖子出参字典（对齐 `PostOut` 的字段）。

    点赞 / 收藏与帖子同构：官号文章也能被赞、被收藏，数量与「我有没有点过」
    由调用方批量查好传进来。
    """
    member = getattr(article, "member", None)
    avatar = ""
    if member is not None:
        url = resolve_avatar_url(member.id, member.avatar)
        avatar = "" if url.lower().split("?")[0].endswith(".svg") else url

    return {
        "id": ARTICLE_ID_OFFSET + int(article.id),
        "kind": "article",
        "article_id": int(article.id),
        "article_url": str(article.url or ""),
        "article_source": str(article.source or ""),
        "post_no": str(article.article_no or ""),
        "publisher": str(article.publisher or ""),
        "publisher_avatar": avatar,
        "member_id": article.member_id,
        "is_following": False,
        "title": str(article.title or ""),
        "content": str(article.content or ""),
        "images": list(article.image_urls or []),
        "published_at": article.published_at,
        "status": str(article.status or ""),
        "view_count": int(article.view_count or 0),
        "is_liked": bool(is_liked),
        "like_count": int(like_count),
        "comment_count": int(comment_count),
        "is_favorited": bool(is_favorited),
        "favorite_count": int(favorite_count),
        "created_at": article.created_at,
        "updated_at": article.updated_at,
    }


def merge_feed(
    *,
    posts: Sequence[Any],
    article_items: Iterable[dict],
    sort_key: Callable[[Any], Any],
    reverse: bool = True,
) -> List[Any]:
    """把帖子与官号文章（已转成字典）按 `sort_key` 合并成一个列表。"""
    entries: List[Any] = list(posts) + list(article_items)
    entries.sort(key=sort_key, reverse=reverse)
    return entries


def published_sort_key(item: Any) -> float:
    """按发布时间排序的 key（帖子对象与文章字典都适用）。"""
    if isinstance(item, dict):
        return _timestamp(item.get("published_at"))
    return _timestamp(getattr(item, "published_at", None))


def view_sort_key(item: Any) -> float:
    """按访问量排序的 key。"""
    if isinstance(item, dict):
        return float(item.get("view_count") or 0)
    return float(getattr(item, "view_count", 0) or 0)


def like_sort_key(item: Any) -> float:
    """按点赞数排序的 key（「获赞」列表用）。"""
    if isinstance(item, dict):
        return float(item.get("like_count") or 0)
    return float(getattr(item, "like_count", 0) or 0)


def comment_sort_key(item: Any) -> float:
    """按评论数排序的 key（「被评论」列表用）。"""
    if isinstance(item, dict):
        return float(item.get("comment_count") or 0)
    return float(getattr(item, "comment_count", 0) or 0)


def paginate(items: List[Any], *, offset: int, limit: int) -> Tuple[List[Any], int]:
    """从合并结果里取一页，返回 (当前页, 总数)。"""
    return items[offset : offset + limit], len(items)
