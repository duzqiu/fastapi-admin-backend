"""帖子评论测试：发表默认待审核、前台只出已通过、后台审核与删除。"""

import uuid

from app.core.config import settings

API = settings.API_V1_PREFIX
POSTS = f"{API}/posts"
COMMENTS = f"{API}/comments"


def _register_member(client) -> tuple[int, dict]:
    email = f"comment-{uuid.uuid4().hex[:8]}@example.com"
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
    return me["id"], headers


def _approved_post(client, auth_headers, member_headers) -> dict:
    post = client.post(POSTS, headers=member_headers, json={"title": "评论-帖子"}).json()
    client.patch(
        f"{POSTS}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    return post


def test_create_comment_defaults_to_pending(client, auth_headers):
    """发表评论：默认待审核，回显评论人与内容。"""
    member_id, member = _register_member(client)
    post = _approved_post(client, auth_headers, member)

    response = client.post(
        f"{POSTS}/{post['id']}/comments", headers=member, json={"content": "  第一条评论  "}
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "pending"
    assert data["status_text"] == "待审核"
    assert data["content"] == "第一条评论"
    assert data["publisher"]
    assert data["post_id"] == post["id"]

    # 未登录不能评论
    assert client.post(f"{POSTS}/{post['id']}/comments", json={"content": "x"}).status_code == 401


def test_comment_only_on_approved_post(client, auth_headers):
    """待审核的帖子不能评论。"""
    member_id, member = _register_member(client)
    post = client.post(POSTS, headers=member, json={"title": "待审帖子"}).json()
    response = client.post(
        f"{POSTS}/{post['id']}/comments", headers=member, json={"content": "x"}
    )
    assert response.status_code == 400


def test_public_comment_list_only_approved(client, auth_headers):
    """前台评论列表只出已通过的，PostOut.comment_count 也只算已通过。"""
    member_id, member = _register_member(client)
    post = _approved_post(client, auth_headers, member)

    approved = client.post(
        f"{POSTS}/{post['id']}/comments", headers=member, json={"content": "通过的评论"}
    ).json()
    pending = client.post(
        f"{POSTS}/{post['id']}/comments", headers=member, json={"content": "待审核的评论"}
    ).json()
    client.patch(
        f"{COMMENTS}/{approved['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )

    body = client.get(f"{POSTS}/{post['id']}/comments")
    assert body.status_code == 200, body.text
    contents = [item["content"] for item in body.json()["items"]]
    assert contents == ["通过的评论"]

    latest = client.get(f"{POSTS}/latest").json()["items"]
    item = next(entry for entry in latest if entry["id"] == post["id"])
    assert item["comment_count"] == 1

    # 待审核的不在前台出现
    assert pending["content"] not in contents


def test_admin_comment_management(client, auth_headers):
    """后台评论列表 / 审核 / 删除。"""
    member_id, member = _register_member(client)
    post = _approved_post(client, auth_headers, member)
    comment = client.post(
        f"{POSTS}/{post['id']}/comments", headers=member, json={"content": "后台可见的评论"}
    ).json()

    listed = client.get(COMMENTS, headers=auth_headers, params={"status": "pending"})
    assert listed.status_code == 200, listed.text
    ids = [item["id"] for item in listed.json()["items"]]
    assert comment["id"] in ids
    assert listed.json()["items"][0]["post_title"] == "评论-帖子"
    # 后台展示的是对外的 12 位帖子编号，不是自增 ID
    assert listed.json()["items"][0]["post_no"] == post["post_no"]

    # 关键字搜索：评论内容 / 评论人 / 帖子编号都能命中
    searched = client.get(COMMENTS, headers=auth_headers, params={"keyword": "后台可见"})
    assert searched.json()["total"] >= 1
    by_post_no = client.get(
        COMMENTS, headers=auth_headers, params={"keyword": post["post_no"]}
    )
    assert by_post_no.status_code == 200, by_post_no.text
    assert comment["id"] in [item["id"] for item in by_post_no.json()["items"]]

    audited = client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    assert audited.status_code == 200, audited.text
    assert audited.json()["status"] == "approved"

    # 审核后是终态
    again = client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "rejected"},
    )
    assert again.status_code == 400

    # 删掉后前台也就没有了
    assert client.delete(f"{COMMENTS}/{comment['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"{POSTS}/{post['id']}/comments").json()["total"] == 0


def test_commented_posts_and_received_count(client, auth_headers):
    """我的-评论：只出有已通过评论的帖子（按评论数倒序），计数只算已通过。"""
    author_id, author = _register_member(client)
    fan_id, fan = _register_member(client)

    hot = _approved_post(client, auth_headers, author)
    cold = _approved_post(client, auth_headers, author)
    unused = _approved_post(client, auth_headers, author)

    first = client.post(
        f"{POSTS}/{hot['id']}/comments", headers=fan, json={"content": "评论一"}
    ).json()
    second = client.post(
        f"{POSTS}/{hot['id']}/comments", headers=fan, json={"content": "评论二"}
    ).json()
    # cold 只有一条待审核的评论：不算「被评论」
    client.post(f"{POSTS}/{cold['id']}/comments", headers=fan, json={"content": "待审评论"})
    for item in (first, second):
        client.patch(
            f"{COMMENTS}/{item['id']}/status",
            headers=auth_headers,
            json={"status": "approved"},
        )

    body = client.get(f"{POSTS}/commented-posts", headers=author)
    assert body.status_code == 200, body.text
    data = body.json()
    assert [entry["id"] for entry in data["items"]] == [hot["id"]]
    assert data["items"][0]["comment_count"] == 2

    count = client.get(f"{POSTS}/received-comments", headers=author)
    assert count.status_code == 200, count.text
    assert count.json()["received_comment_count"] == 2

    # 没发过帖的人 = 0；未登录两个接口都拿不到
    assert (
        client.get(f"{POSTS}/received-comments", headers=fan).json()[
            "received_comment_count"
        ]
        == 0
    )
    assert client.get(f"{POSTS}/commented-posts").status_code == 401
    assert client.get(f"{POSTS}/received-comments").status_code == 401


def test_admin_comment_requires_admin(client):
    """后台评论接口需要管理员令牌。"""
    assert client.get(COMMENTS).status_code == 401
