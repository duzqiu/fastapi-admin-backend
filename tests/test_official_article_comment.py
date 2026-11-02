"""官号文章评论：与帖子评论同一套流程（待审核 → 后台通过 → 前台可见）。"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models import Member

ARTICLES = "/api/v1/official-articles"
POSTS = "/api/v1/posts"
COMMENTS = "/api/v1/comments"
OFFSET = 1_000_000_000


def _member_number(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().int % 10**9:09d}"


@pytest.fixture
def publisher(testing_session_local):
    with testing_session_local() as db:
        member = Member(
            member_no=_member_number("7"),
            email=f"official-comment-{uuid.uuid4().hex[:8]}@example.com",
            nickname="官号评论作者",
            hashed_password="not-used-in-this-test",
            is_active=True,
        )
        db.add(member)
        db.commit()
        return member.id


def approved_article(client, headers, publisher_id, *, title=None) -> dict:
    created = client.post(
        ARTICLES,
        headers=headers,
        json={
            "member_id": publisher_id,
            "url": f"https://news.example.com/{uuid.uuid4().hex}",
            "title": title or f"可评论文章-{uuid.uuid4().hex[:6]}",
            "content": "正文",
            "image_urls": [],
            "source": "来源",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        },
    ).json()
    client.patch(
        f"{ARTICLES}/{created['id']}/status",
        headers=headers,
        json={"status": "approved"},
    )
    return created


def test_article_comment_flow(client, auth_headers, publisher):
    """发评论 → 前台看不到 → 后台可见（带文章信息）→ 通过 → 前台可见。"""
    from tests.test_post import _register_member

    article = approved_article(client, auth_headers, publisher)
    offset_id = OFFSET + article["id"]
    _member_id, member = _register_member(client)

    created = client.post(
        f"{POSTS}/{offset_id}/comments", headers=member, json={"content": "文章评论"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["post_id"] == offset_id
    assert body["post_title"] == article["title"]
    assert body["status"] == "pending"

    assert client.get(f"{POSTS}/{offset_id}/comments").json()["total"] == 0

    admin_list = client.get(COMMENTS, headers=auth_headers).json()["items"]
    target = next(item for item in admin_list if item["content"] == "文章评论")
    assert target["post_id"] == offset_id
    assert target["post_no"] == article["article_no"]

    audited = client.patch(
        f"{COMMENTS}/{target['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    assert audited.status_code == 200, audited.text

    approved_list = client.get(f"{POSTS}/{offset_id}/comments").json()
    assert approved_list["total"] == 1
    assert approved_list["items"][0]["content"] == "文章评论"


def test_article_counts_in_member_lists(client, auth_headers, publisher):
    """被评论数 / 被评论列表 / 获赞列表都要包含官号文章。"""
    from tests.test_post import _register_member

    author_id, author = _register_member(client)
    article = approved_article(
        client, auth_headers, author_id, title="自己的官号文章"
    )
    offset_id = OFFSET + article["id"]

    _fan_id, fan = _register_member(client)
    comment = client.post(
        f"{POSTS}/{offset_id}/comments", headers=fan, json={"content": "来自粉丝"}
    ).json()
    client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    client.post(f"{POSTS}/{offset_id}/like", headers=fan)

    counts = client.get(f"{POSTS}/received-comments", headers=author).json()
    assert counts["received_comment_count"] == 1

    received_likes = client.get(f"{POSTS}/received-likes", headers=author).json()
    assert received_likes["received_like_count"] == 1

    commented = client.get(f"{POSTS}/commented-posts", headers=author).json()
    assert any(
        item["kind"] == "article" and item["article_id"] == article["id"]
        for item in commented["items"]
    )
    assert commented["items"][0]["comment_count"] == 1

    liked = client.get(f"{POSTS}/received-likes/posts", headers=author).json()
    assert any(
        item["kind"] == "article" and item["article_id"] == article["id"]
        for item in liked["items"]
    )
