"""站内消息测试：互动事件写入通知、未读数、已读。"""

import uuid

from app.core.config import settings

API = settings.API_V1_PREFIX
POSTS = f"{API}/posts"
MEMBERS = f"{API}/members"
COMMENTS = f"{API}/comments"
MESSAGES = f"{API}/messages"


def _register_member(client) -> tuple[int, dict, str]:
    email = f"msg-{uuid.uuid4().hex[:8]}@example.com"
    password = "tests1234"

    code = client.post(
        f"{API}/member/auth/send-code", json={"email": email, "scene": "register"}
    ).json()["debug_code"]
    client.post(
        f"{API}/member/auth/register",
        json={
            "email": email,
            "code": code,
            "password": password,
            "confirm_password": password,
        },
    )
    token = client.post(
        f"{API}/member/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get(f"{API}/member/auth/me", headers=headers).json()
    return me["id"], headers, me["nickname"]


def _approved_post(client, auth_headers, author_headers, title="消息-帖子") -> dict:
    post = client.post(POSTS, headers=author_headers, json={"title": title}).json()
    client.patch(
        f"{POSTS}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    return post


def _messages(client, headers) -> list[dict]:
    body = client.get(MESSAGES, headers=headers)
    assert body.status_code == 200, body.text
    return body.json()["items"]


def test_follow_creates_message(client, auth_headers):
    """关注后对方收到通知；未读数 / 单条已读 / 全部已读都生效。"""
    author_id, author, author_name = _register_member(client)
    fan_id, fan, fan_name = _register_member(client)

    client.post(f"{MEMBERS}/{author_id}/follow", headers=fan)

    items = _messages(client, author)
    assert items and items[0]["type"] == "follow"
    assert items[0]["title"] == f"{fan_name} 关注了你"
    assert items[0]["is_read"] is False

    unread = client.get(f"{MESSAGES}/unread-count", headers=author)
    assert unread.json()["unread_count"] >= 1

    first_id = items[0]["id"]
    assert (
        client.post(f"{MESSAGES}/{first_id}/read", headers=author).status_code == 200
    )
    assert client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"] == 0

    # 换一个人再关注一次，用「全部已读」清掉（同一人重复关注是幂等的，不会重复通知）
    third_id, third, _ = _register_member(client)
    client.post(f"{MEMBERS}/{author_id}/follow", headers=third)
    assert client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"] >= 1
    assert client.post(f"{MESSAGES}/read-all", headers=author).status_code == 200
    assert client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"] == 0

    # 未登录拿不到
    assert client.get(MESSAGES).status_code == 401


def test_like_and_comment_create_messages(client, auth_headers):
    """点赞 / 评论都会通知作者；自己赞自己不产生消息。"""
    author_id, author, _ = _register_member(client)
    fan_id, fan, fan_name = _register_member(client)
    post = _approved_post(client, auth_headers, author)

    client.post(f"{POSTS}/{post['id']}/like", headers=fan)
    comment = client.post(
        f"{POSTS}/{post['id']}/comments", headers=fan, json={"content": "写得好"}
    ).json()

    types = [item["type"] for item in _messages(client, author)]
    assert "like" in types
    # 评论还没审核通过：此时不该有「评论了你的帖子」的通知
    assert "comment" not in types

    # 后台审核通过后才通知作者
    client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    picked = {item["type"]: item for item in _messages(client, author)}
    assert "comment" in picked
    assert picked["like"]["post_id"] == post["id"]
    assert fan_name in picked["comment"]["title"]

    # 自己赞自己的帖子：不该多出消息
    before = client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"]
    client.post(f"{POSTS}/{post['id']}/like", headers=author)
    after = client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"]
    assert after == before


def test_audit_results_create_messages(client, auth_headers):
    """帖子 / 评论审核结果会通知作者与评论人。"""
    author_id, author, _ = _register_member(client)
    fan_id, fan, _ = _register_member(client)

    post = _approved_post(client, auth_headers, author, title="待审核的帖子")
    comment = client.post(
        f"{POSTS}/{post['id']}/comments", headers=fan, json={"content": "待审评论"}
    ).json()

    audited = client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    assert audited.status_code == 200, audited.text

    commenter_types = [item["type"] for item in _messages(client, fan)]
    assert "comment_audit" in commenter_types

    # 帖子审核：新建一条待审核帖子再通过
    pending = client.post(POSTS, headers=author, json={"title": "第二条"}).json()
    client.patch(
        f"{POSTS}/{pending['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    author_types = [item["type"] for item in _messages(client, author)]
    assert "post_audit" in author_types
