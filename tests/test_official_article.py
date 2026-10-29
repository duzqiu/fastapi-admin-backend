"""Official article administration, review boundaries and timezone round trips."""
from datetime import datetime, timezone
import uuid

import pytest

from app.core.security import create_access_token, TOKEN_SCOPE_MEMBER
from app.models import Member, User

API = "/api/v1/official-articles"


@pytest.fixture
def publisher(testing_session_local):
    with testing_session_local() as db:
        member = Member(
            member_no=uuid.uuid4().hex[:10],
            email=f"official-{uuid.uuid4().hex}@example.com",
            nickname="官号发布人",
            hashed_password="not-used-in-this-test",
            is_active=True,
        )
        db.add(member)
        db.commit()
        return member.id


def article_payload(publisher_id, **changes):
    payload = {
        "member_id": publisher_id,
        "url": "https://news.example.com/original/1",
        "title": f"官号文章-{uuid.uuid4().hex}",
        "content": "第一段正文\n第二段正文",
        "image_urls": ["https://img.example.com/a.jpg", "https://img.example.com/b.jpg"],
        "source": "新闻渠道",
        "published_at": "2026-10-29T12:30:00+08:00",
        "crawled_at": "2026-10-29T13:45:00+08:00",
        "board": "热点榜单",
        "rank": 2,
    }
    payload.update(changes)
    return payload


def create_article(client, headers, payload):
    response = client.post(API, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_article_roundtrip_fields_timezone_and_id(client, auth_headers, publisher):
    payload = article_payload(publisher)
    body = create_article(client, auth_headers, payload)
    assert isinstance(body["id"], int)
    assert len(body["article_no"]) == 12 and body["article_no"].isdigit()
    assert body["status"] == "pending"
    assert body["view_count"] == 0
    assert body["publisher"] == "官号发布人"
    for key in ("url", "title", "content", "image_urls", "source", "board", "rank", "member_id"):
        assert body[key] == payload[key]
    detail = client.get(f"{API}/{body['id']}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    for key in ("published_at", "crawled_at"):
        value = datetime.fromisoformat(detail.json()[key].replace("Z", "+00:00"))
        assert value.tzinfo is not None
        assert value == datetime.fromisoformat(payload[key]).astimezone(timezone.utc)
    items = client.get(API, headers=auth_headers, params={"keyword": body["article_no"]}).json()
    assert items["total"] == 1
    assert items["items"][0]["id"] == body["id"]


def test_article_auth_requires_admin_not_member_or_editor(client, auth_headers, publisher, testing_session_local):
    payload = article_payload(publisher)
    assert client.get(API).status_code == 401
    assert client.post(API, json=payload).status_code == 401
    member_headers = {"Authorization": f"Bearer {create_access_token(publisher, scope=TOKEN_SCOPE_MEMBER)}"}
    assert client.get(API, headers=member_headers).status_code == 401
    with testing_session_local() as db:
        editor = User(username=f"editor-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@example.com", nickname="编辑", role="editor", is_active=True, hashed_password="unused")
        db.add(editor)
        db.commit()
        token = create_access_token(editor.id)
    assert client.post(API, headers={"Authorization": f"Bearer {token}"}, json=payload).status_code == 403


@pytest.mark.parametrize("changes", [
    {"title": "   "}, {"content": "\n "}, {"source": " "},
    {"url": "javascript:alert(1)"}, {"url": "file:///etc/passwd"},
    {"image_urls": ["data:image/png;base64,aaaa"]},
    {"image_urls": ["https://img.example.com/a.jpg"] * 51},
    {"published_at": "2026-10-29T12:30:00"},
    {"crawled_at": "2026-10-29T12:30:00"},
    {"rank": 0}, {"rank": -1}, {"member_id": 0},
    {"status": "approved"}, {"view_count": 9000}, {"publisher": "伪造发布人"},
])
def test_article_rejects_invalid_or_readonly_fields(client, auth_headers, publisher, changes):
    response = client.post(API, headers=auth_headers, json=article_payload(publisher, **changes))
    assert response.status_code == 422, response.text


def test_missing_disabled_publishers_are_rejected(client, auth_headers, publisher, testing_session_local):
    response = client.post(API, headers=auth_headers, json=article_payload(2147483647))
    assert response.status_code in (400, 404), response.text
    with testing_session_local() as db:
        db.get(Member, publisher).is_active = False
        db.commit()
    response = client.post(API, headers=auth_headers, json=article_payload(publisher))
    assert response.status_code in (400, 403), response.text


def test_article_audit_edit_resubmit_clear_optional_and_delete(client, auth_headers, publisher):
    payload = article_payload(publisher)
    body = create_article(client, auth_headers, payload)
    article_id = body["id"]
    invalid = client.patch(f"{API}/{article_id}/status", headers=auth_headers, json={"status": "pending"})
    assert invalid.status_code in (400, 422), invalid.text
    response = client.patch(f"{API}/{article_id}/status", headers=auth_headers, json={"status": "rejected"})
    assert response.status_code == 200, response.text
    response = client.patch(f"{API}/{article_id}/status", headers=auth_headers, json={"status": "approved"})
    assert response.status_code == 400, response.text
    payload.update(title="修改后重新审核", board=None, rank=None, image_urls=[])
    response = client.put(f"{API}/{article_id}", headers=auth_headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["article_no"] == body["article_no"]
    assert response.json()["board"] is None and response.json()["rank"] is None
    assert response.json()["image_urls"] == []
    response = client.patch(f"{API}/{article_id}/status", headers=auth_headers, json={"status": "approved"})
    assert response.status_code == 200, response.text
    assert client.delete(f"{API}/{article_id}", headers=auth_headers).status_code == 200
    assert client.get(f"{API}/{article_id}", headers=auth_headers).status_code == 404


def test_article_filters_and_pagination(client, auth_headers, publisher):
    source = f"channel-{uuid.uuid4().hex}"
    one = create_article(client, auth_headers, article_payload(publisher, source=source))
    two = create_article(client, auth_headers, article_payload(publisher, source=source))
    client.patch(f"{API}/{two['id']}/status", headers=auth_headers, json={"status": "approved"})
    response = client.get(API, headers=auth_headers, params={"source": source, "member_id": publisher, "status": "pending", "page_size": 1})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == one["id"]


def test_public_view_only_approved_and_atomic_counter(client, auth_headers, publisher):
    article = create_article(client, auth_headers, article_payload(publisher))
    article_id = article["id"]
    assert client.get(f"{API}/detail/{article_id}").status_code == 404
    assert client.post(f"{API}/{article_id}/view").status_code == 404
    client.patch(f"{API}/{article_id}/status", headers=auth_headers, json={"status": "approved"})
    assert client.get(f"{API}/detail/{article_id}").status_code == 200
    for count in range(1, 4):
        response = client.post(f"{API}/{article_id}/view")
        assert response.status_code == 200, response.text
        assert response.json()["view_count"] == count
    assert client.get(f"{API}/{article_id}", headers=auth_headers).json()["view_count"] == 3


def test_official_articles_do_not_pollute_user_posts(client, auth_headers, publisher):
    article = create_article(client, auth_headers, article_payload(publisher))
    result = client.get("/api/v1/posts", headers=auth_headers, params={"keyword": article["title"]})
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 0
