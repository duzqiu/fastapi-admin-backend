"""关注功能测试：关注关系、关注列表、关注动态与出参里的 is_following。"""

import uuid

from app.core.config import settings

API = settings.API_V1_PREFIX
POSTS = f"{API}/posts"
MEMBERS = f"{API}/members"


def _register_member(client) -> tuple[int, dict, str]:
    """注册并登录一个会员，返回 (会员 id, 请求头, 昵称)。"""
    email = f"follow-{uuid.uuid4().hex[:8]}@example.com"
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


def _approved_post(client, auth_headers, headers, title: str) -> dict:
    post = client.post(POSTS, headers=headers, json={"title": title}).json()
    client.patch(
        f"{POSTS}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    return post


def test_follow_and_unfollow(client, auth_headers):
    """关注 / 取消关注：幂等，不能关注自己。"""
    me_id, me, _ = _register_member(client)
    other_id, other, _ = _register_member(client)

    first = client.post(f"{MEMBERS}/{other_id}/follow", headers=me)
    assert first.status_code == 200, first.text
    # 重复关注不报错
    assert client.post(f"{MEMBERS}/{other_id}/follow", headers=me).status_code == 200

    assert client.post(f"{MEMBERS}/{me_id}/follow", headers=me).status_code == 400
    assert client.post(f"{MEMBERS}/999999/follow", headers=me).status_code == 404
    assert client.post(f"{MEMBERS}/{other_id}/follow").status_code == 401

    removed = client.delete(f"{MEMBERS}/{other_id}/follow", headers=me)
    assert removed.status_code == 200, removed.text
    # 再取消一次也返回成功
    assert client.delete(f"{MEMBERS}/{other_id}/follow", headers=me).status_code == 200


def test_following_list(client, auth_headers):
    """我的关注列表：只出关注过的人，最近关注的在前。"""
    me_id, me, _ = _register_member(client)
    first_id, _, first_name = _register_member(client)
    second_id, _, second_name = _register_member(client)

    client.post(f"{MEMBERS}/{first_id}/follow", headers=me)
    client.post(f"{MEMBERS}/{second_id}/follow", headers=me)

    body = client.get(f"{MEMBERS}/me/following", headers=me)
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["total"] == 2
    names = [item["nickname"] for item in data["items"]]
    assert names == [second_name, first_name]
    assert all(item["is_following"] is True for item in data["items"])

    # 未登录拿不到
    assert client.get(f"{MEMBERS}/me/following").status_code == 401


def test_following_posts_feed(client, auth_headers):
    """关注动态：只出关注的人已通过的帖子。"""
    me_id, me, _ = _register_member(client)
    author_id, author, _ = _register_member(client)
    stranger_id, stranger, _ = _register_member(client)

    followed_post = _approved_post(client, auth_headers, author, "关注的作者发的")
    stranger_post = _approved_post(client, auth_headers, stranger, "没关注的人发的")
    pending_post = client.post(
        POSTS, headers=author, json={"title": "关注的作者-待审核"}
    ).json()

    client.post(f"{MEMBERS}/{author_id}/follow", headers=me)

    body = client.get(f"{POSTS}/following", headers=me)
    assert body.status_code == 200, body.text
    data = body.json()
    ids = [item["id"] for item in data["items"]]
    assert followed_post["id"] in ids
    assert stranger_post["id"] not in ids
    assert pending_post["id"] not in ids
    assert all(item["status"] == "approved" for item in data["items"])
    assert all(item["is_following"] is True for item in data["items"])

    # 未登录拿不到
    assert client.get(f"{POSTS}/following").status_code == 401


def test_post_and_public_profile_carry_is_following(client, auth_headers):
    """帖子出参与作者公开资料都会带 is_following（按查看者）。"""
    me_id, me, _ = _register_member(client)
    author_id, author, _ = _register_member(client)
    post = _approved_post(client, auth_headers, author, "关注状态-帖子")

    before = client.get(f"{POSTS}/latest", headers=me).json()["items"]
    item = next(entry for entry in before if entry["id"] == post["id"])
    assert item["is_following"] is False

    client.post(f"{MEMBERS}/{author_id}/follow", headers=me)

    after = client.get(f"{POSTS}/latest", headers=me).json()["items"]
    item = next(entry for entry in after if entry["id"] == post["id"])
    assert item["is_following"] is True

    profile = client.get(f"{MEMBERS}/{author_id}/public", headers=me).json()
    assert profile["is_following"] is True
    guest = client.get(f"{MEMBERS}/{author_id}/public").json()
    assert guest["is_following"] is False
