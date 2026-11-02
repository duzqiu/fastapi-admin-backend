"""官号文章并入 App 列表：最新 / 热门 / 推荐 / 作者主页 / 详情。

收藏、获赞、被评论这些「帖子互动」列表仍然是纯帖子（文章不参与互动）。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Member

ARTICLES = "/api/v1/official-articles"
POSTS = "/api/v1/posts"
ARTICLE_ID_OFFSET = 1_000_000_000


@pytest.fixture
def publisher(testing_session_local):
    """官号发布人：直接建一个会员，避免走注册验证码流程。"""
    with testing_session_local() as db:
        member = Member(
            member_no=f"9{uuid.uuid4().int % 10**9:09d}",
            email=f"official-feed-{uuid.uuid4().hex[:8]}@example.com",
            nickname="官号发布人",
            hashed_password="not-used-in-this-test",
            is_active=True,
        )
        db.add(member)
        db.commit()
        return member.id


def make_article(client, headers, publisher_id, *, title=None, published_at=None):
    payload = {
        "member_id": publisher_id,
        "url": f"https://news.example.com/{uuid.uuid4().hex}",
        "title": title or f"官号文章-{uuid.uuid4().hex[:6]}",
        "content": "第一段正文\n第二段正文",
        "image_urls": ["https://img.example.com/a.jpg"],
        "source": "新闻渠道",
        "published_at": (
            published_at or datetime.now(timezone.utc)
        ).isoformat(),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "board": "热点",
        "rank": 1,
    }
    created = client.post(ARTICLES, headers=headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    audited = client.patch(
        f"{ARTICLES}/{body['id']}/status",
        headers=headers,
        json={"status": "approved"},
    )
    assert audited.status_code == 200, audited.text
    return body


def make_post(client, headers, *, title=None):
    post = client.post(POSTS, headers=headers, json={"title": title or "普通动态"}).json()
    client.patch(
        f"{POSTS}/{post['id']}/status", headers=headers, json={"status": "approved"}
    )
    return post


def _items(client, path, **params):
    response = client.get(path, params=params or None)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_latest_merges_articles(client, auth_headers, publisher):
    """最新：普通帖子与官号文章混排；文章带 kind / 偏移 id。"""
    article = make_article(client, auth_headers, publisher, title="最新里的官号文章")
    make_post(client, auth_headers, title="最新里的普通动态")

    items = _items(client, f"{POSTS}/latest", page=1, page_size=20)
    kinds = {item["kind"] for item in items}
    assert {"post", "article"} <= kinds

    merged = next(item for item in items if item["kind"] == "article")
    assert merged["article_id"] == article["id"]
    assert merged["id"] == ARTICLE_ID_OFFSET + article["id"]
    assert merged["title"] == "最新里的官号文章"
    assert merged["post_no"] == article["article_no"]
    assert merged["images"] == article["image_urls"]
    assert merged["like_count"] == 0 and merged["comment_count"] == 0


def test_hot_and_recommend_include_articles(client, auth_headers, publisher):
    make_article(client, auth_headers, publisher, title="热门官号文章")
    make_post(client, auth_headers, title="热门普通动态")

    hot = _items(client, f"{POSTS}/hot", page=1, page_size=20)
    assert "article" in {item["kind"] for item in hot}

    # 推荐接口直接返回列表（不是分页结构）
    recommend_response = client.get(f"{POSTS}/recommend")
    assert recommend_response.status_code == 200, recommend_response.text
    recommend = recommend_response.json()
    assert "article" in {item["kind"] for item in recommend}


def test_by_member_includes_own_articles(client, auth_headers, publisher):
    article = make_article(client, auth_headers, publisher, title="作者主页官号文章")
    items = _items(client, f"{POSTS}/by-member/{publisher}", page=1, page_size=20)
    assert any(
        item["kind"] == "article" and item["article_id"] == article["id"]
        for item in items
    )


def test_article_detail_and_view_by_offset_id(client, auth_headers, publisher):
    article = make_article(client, auth_headers, publisher, title="可打开的官号文章")
    offset_id = ARTICLE_ID_OFFSET + article["id"]

    detail = client.get(f"{POSTS}/detail/{offset_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["kind"] == "article" and body["article_id"] == article["id"]
    assert body["article_url"] == article["url"]

    viewed = client.post(f"{POSTS}/{offset_id}/view")
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["view_count"] >= 1


def test_favorites_stay_posts_only(client, auth_headers, publisher):
    """收藏列表仍然只有收藏过的帖子：官号文章不参与收藏。"""
    from tests.test_post import _register_member

    _member_id, member_headers = _register_member(client)
    post = client.post(
        POSTS, headers=member_headers, json={"title": "可收藏动态"}
    ).json()
    client.patch(
        f"{POSTS}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    client.post(f"{POSTS}/{post['id']}/favorite", headers=member_headers)

    make_article(client, auth_headers, publisher, title="不该出现在收藏里的文章")

    response = client.get(
        f"{POSTS}/favorites",
        headers=member_headers,
        params={"page": 1, "page_size": 20},
    )
    assert response.status_code == 200, response.text
    favorites = response.json()["items"]
    assert favorites and all(item["kind"] == "post" for item in favorites)
