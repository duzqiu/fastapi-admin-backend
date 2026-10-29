"""官号文章的点赞 / 收藏：与帖子同一套接口，靠偏移 id 区分。"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models import Member

ARTICLES = "/api/v1/official-articles"
POSTS = "/api/v1/posts"
OFFSET = 1_000_000_000


@pytest.fixture
def publisher(testing_session_local):
    with testing_session_local() as db:
        member = Member(
            member_no=f"8{uuid.uuid4().int % 10**9:09d}",
            email=f"official-inter-{uuid.uuid4().hex[:8]}@example.com",
            nickname="官号作者",
            hashed_password="not-used-in-this-test",
            is_active=True,
        )
        db.add(member)
        db.commit()
        return member.id


def approved_article(client, headers, publisher_id) -> dict:
    payload = {
        "member_id": publisher_id,
        "url": f"https://news.example.com/{uuid.uuid4().hex}",
        "title": f"可互动的官号文章-{uuid.uuid4().hex[:6]}",
        "content": "正文",
        "image_urls": [],
        "source": "来源",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }
    created = client.post(ARTICLES, headers=headers, json=payload).json()
    client.patch(
        f"{ARTICLES}/{created['id']}/status",
        headers=headers,
        json={"status": "approved"},
    )
    return created


def test_article_like_and_unlike(client, auth_headers, publisher):
    from tests.test_post import _register_member

    article = approved_article(client, auth_headers, publisher)
    offset_id = OFFSET + article["id"]
    _member_id, member = _register_member(client)

    liked = client.post(f"{POSTS}/{offset_id}/like", headers=member)
    assert liked.status_code == 200, liked.text
    body = liked.json()
    assert body["kind"] == "article"
    assert body["is_liked"] is True
    assert body["like_count"] == 1

    # 幂等：再点一次不会变成 2
    again = client.post(f"{POSTS}/{offset_id}/like", headers=member).json()
    assert again["like_count"] == 1

    # 列表里也能看到今天的赞数
    latest = client.get(f"{POSTS}/latest", params={"page": 1, "page_size": 50}).json()
    item = next(i for i in latest["items"] if i["kind"] == "article" and i["article_id"] == article["id"])
    assert item["like_count"] == 1

    removed = client.delete(f"{POSTS}/{offset_id}/like", headers=member)
    assert removed.status_code == 200, removed.text
    assert removed.json()["like_count"] == 0


def test_article_favorite_appears_in_favorites_list(client, auth_headers, publisher):
    from tests.test_post import _register_member

    article = approved_article(client, auth_headers, publisher)
    offset_id = OFFSET + article["id"]
    _member_id, member = _register_member(client)

    favorited = client.post(f"{POSTS}/{offset_id}/favorite", headers=member)
    assert favorited.status_code == 200, favorited.text
    body = favorited.json()
    assert body["is_favorited"] is True
    assert body["favorite_count"] == 1

    favorites = client.get(
        f"{POSTS}/favorites", headers=member, params={"page": 1, "page_size": 20}
    )
    assert favorites.status_code == 200, favorites.text
    items = favorites.json()["items"]
    assert any(
        item["kind"] == "article" and item["article_id"] == article["id"]
        for item in items
    )

    removed = client.delete(f"{POSTS}/{offset_id}/favorite", headers=member)
    assert removed.status_code == 200, removed.text
    assert removed.json()["favorite_count"] == 0

    after = client.get(
        f"{POSTS}/favorites", headers=member, params={"page": 1, "page_size": 20}
    ).json()["items"]
    assert all(
        not (item["kind"] == "article" and item["article_id"] == article["id"])
        for item in after
    )


def test_article_detail_reflects_member_state(client, auth_headers, publisher):
    from tests.test_post import _register_member

    article = approved_article(client, auth_headers, publisher)
    offset_id = OFFSET + article["id"]
    _member_id, member = _register_member(client)

    client.post(f"{POSTS}/{offset_id}/like", headers=member)
    client.post(f"{POSTS}/{offset_id}/favorite", headers=member)

    detail = client.get(f"{POSTS}/detail/{offset_id}", headers=member).json()
    assert detail["is_liked"] is True and detail["is_favorited"] is True

    anonymous = client.get(f"{POSTS}/detail/{offset_id}").json()
    assert anonymous["is_liked"] is False and anonymous["is_favorited"] is False
    assert anonymous["like_count"] == 1
