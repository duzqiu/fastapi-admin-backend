"""文章管理（帖子）测试：用户发帖默认待审核、后台筛选与审核。

覆盖点：
- 发帖一律进「待审核」，出参带发布人 / 标题 / 正文 / 图片 / 发布时间；
- 后台列表需要管理员身份，支持状态与关键词筛选；
- 审核只能改为「已通过」或「已拒绝」，允许改判；
- 详情 / 删除。
"""

import re
import uuid

from app.core.config import settings

API = f"{settings.API_V1_PREFIX}/posts"


def _register_member(client) -> tuple[int, dict]:
    """注册并登录一个会员，返回 (会员 id, 带令牌的请求头)。"""
    email = f"post-author-{uuid.uuid4().hex[:8]}@example.com"
    password = "tests1234"
    api = settings.API_V1_PREFIX

    code = client.post(
        f"{api}/member/auth/send-code", json={"email": email, "scene": "register"}
    ).json()["debug_code"]
    client.post(
        f"{api}/member/auth/register",
        json={
            "email": email,
            "code": code,
            "password": password,
            "confirm_password": password,
        },
    )
    token = client.post(
        f"{api}/member/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    member_id = client.get(f"{api}/member/auth/me", headers=headers).json()["id"]
    return member_id, headers


def create_post(client, **overrides) -> dict:
    payload = {
        "publisher": "测试发布人",
        "title": "测试帖子标题",
        "content": "这是正文内容",
        "images": ["/api/v1/static/posts/a.png", "/api/v1/static/posts/b.png"],
    }
    payload.update(overrides)
    response = client.post(API, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ==================== 用户发帖 ====================
def test_create_post_defaults_to_pending(client):
    """发帖默认「待审核」，字段完整回显。"""
    body = create_post(client)

    assert body["status"] == "pending"
    assert body["status_text"] == "待审核"
    assert body["publisher"] == "测试发布人"
    assert body["title"] == "测试帖子标题"
    assert body["content"] == "这是正文内容"
    assert len(body["images"]) == 2
    assert body["published_at"]
    assert body["member_id"] is None


def test_create_post_without_images(client):
    """图片可以为空。"""
    body = create_post(client, images=[])
    assert body["images"] == []


def test_create_post_generates_12_digit_post_no(client):
    """帖子 ID 是 12 位随机数字，与自增主键相互独立。"""
    body = create_post(client)
    assert re.fullmatch(r"\d{12}", body["post_no"]), body["post_no"]
    assert body["post_no"] != str(body["id"])


def test_post_no_is_unique(client):
    """两次发帖的编号不会重复。"""
    first = create_post(client)
    second = create_post(client)
    assert first["post_no"] != second["post_no"]


# ==================== 图片上传 ====================
# 1x1 透明 PNG
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def test_upload_image_returns_static_url(client):
    """上传图片：只落盘并返回可直接访问的地址。"""
    response = client.post(f"{API}/images", files={"file": ("p.png", _PNG, "image/png")})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["url"].startswith(f"{settings.upload_url_prefix}/posts/")
    assert body["size"] == len(_PNG)
    assert (settings.upload_dir / "posts" / body["filename"]).is_file()
    # 静态目录直出，地址能取回原图
    assert client.get(body["url"]).content == _PNG


def test_upload_image_rejects_non_image(client):
    """非图片内容按业务错误 400 返回。"""
    response = client.post(
        f"{API}/images", files={"file": ("p.png", b"not-an-image", "image/png")}
    )
    assert response.status_code == 400


def test_create_post_with_uploaded_image(client):
    """典型流程：先传图拿 url，再随发帖一起提交。"""
    uploaded = client.post(
        f"{API}/images", files={"file": ("p.png", _PNG, "image/png")}
    ).json()

    body = create_post(client, images=[uploaded["url"]])
    assert body["images"] == [uploaded["url"]]
    assert body["status"] == "pending"


def test_create_post_publisher_falls_back(client):
    """发布人留空时记为「匿名用户」。"""
    body = create_post(client, publisher="")
    assert body["publisher"] == "匿名用户"


def test_create_post_requires_title(client):
    """标题为空 -> 422。"""
    response = client.post(API, json={"publisher": "某人", "title": "   "})
    assert response.status_code == 422


def test_create_post_rejects_too_many_images(client):
    """图片最多 9 张。"""
    response = client.post(
        API, json={"title": "图太多", "images": [f"/a/{i}.png" for i in range(10)]}
    )
    assert response.status_code == 422


# ==================== 按会员查已发布（C 端「我的帖子」）====================
def test_member_posts_only_approved(client, auth_headers):
    """只出审核通过的帖子，待审核的不出现。"""
    member_id, member = _register_member(client)

    approved = client.post(
        API, headers=member, json={"title": "已通过的帖子", "content": "a"}
    ).json()
    pending = client.post(
        API, headers=member, json={"title": "待审核的帖子", "content": "b"}
    ).json()
    client.patch(
        f"{API}/{approved['id']}/status", headers=auth_headers, json={"status": "approved"}
    )

    body = client.get(f"{API}/by-member/{member_id}").json()
    ids = [item["post_no"] for item in body["items"]]
    assert approved["post_no"] in ids
    assert pending["post_no"] not in ids
    assert all(item["status"] == "approved" for item in body["items"])


def test_member_posts_newest_first(client, auth_headers):
    """按发布时间倒序，最新的在前。"""
    member_id, member = _register_member(client)
    older = client.post(API, headers=member, json={"title": "先发的"}).json()
    newer = client.post(API, headers=member, json={"title": "后发的"}).json()
    for post in (older, newer):
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    titles = [item["title"] for item in client.get(f"{API}/by-member/{member_id}").json()["items"]]
    assert titles.index("后发的") < titles.index("先发的")


def test_member_posts_isolated_between_members(client, auth_headers):
    """别人的帖子不会混进来。"""
    first_id, first = _register_member(client)
    second_id, second = _register_member(client)

    mine = client.post(API, headers=first, json={"title": "第一个人的帖子"}).json()
    client.post(API, headers=second, json={"title": "第二个人的帖子"})
    client.patch(
        f"{API}/{mine['id']}/status", headers=auth_headers, json={"status": "approved"}
    )

    body = client.get(f"{API}/by-member/{first_id}").json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "第一个人的帖子"
    assert client.get(f"{API}/by-member/{second_id}").json()["total"] == 0


def test_member_posts_unknown_member_is_empty(client):
    """查不存在的会员：返回空列表而不是报错。"""
    body = client.get(f"{API}/by-member/999999").json()
    assert body["total"] == 0
    assert body["items"] == []


# ==================== 后台列表 ====================
def test_list_requires_admin(client):
    """未登录不能看帖子列表。"""
    assert client.get(API).status_code == 401


def test_list_returns_newest_first(client, auth_headers):
    create_post(client, title="先发的")
    create_post(client, title="后发的")

    body = client.get(API, headers=auth_headers).json()
    assert body["total"] >= 2
    titles = [item["title"] for item in body["items"]]
    assert titles.index("后发的") < titles.index("先发的")
    assert body["page"] == 1


def test_list_filter_by_status(client, auth_headers):
    approved = create_post(client, title="会被通过的帖子")
    client.patch(
        f"{API}/{approved['id']}/status", headers=auth_headers, json={"status": "approved"}
    )

    pending = client.get(API, headers=auth_headers, params={"status": "pending"}).json()
    assert pending["items"]
    assert all(item["status"] == "pending" for item in pending["items"])

    done = client.get(API, headers=auth_headers, params={"status": "approved"}).json()
    assert any(item["id"] == approved["id"] for item in done["items"])


def test_search_by_post_no(client, auth_headers):
    """关键词搜索支持帖子 ID（12 位编号）。"""
    target = create_post(client, title="按编号搜的帖子")
    create_post(client, title="干扰项")

    body = client.get(
        API, headers=auth_headers, params={"keyword": target["post_no"]}
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == target["id"]


def test_list_search_by_keyword(client, auth_headers):
    create_post(client, title="独一无二的关键词标题")

    body = client.get(
        API, headers=auth_headers, params={"keyword": "独一无二的关键词"}
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "独一无二的关键词标题"


# ==================== 审核 ====================
def test_audit_approve_then_reject(client, auth_headers):
    post = create_post(client)

    approved = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["status_text"] == "已通过"

    # 允许改判
    rejected = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "rejected"}
    )
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["status_text"] == "已拒绝"


def test_audit_cannot_go_back_to_pending(client, auth_headers):
    """审核只能改成已通过 / 已拒绝，不能退回待审核。"""
    post = create_post(client)
    response = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "pending"}
    )
    assert response.status_code == 400
    assert "已通过" in response.text


def test_audit_unknown_status(client, auth_headers):
    post = create_post(client)
    response = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "unknown"}
    )
    assert response.status_code == 422


def test_audit_missing_post(client, auth_headers):
    response = client.patch(
        f"{API}/999999/status", headers=auth_headers, json={"status": "approved"}
    )
    assert response.status_code == 404


# ==================== 详情 / 删除 ====================
def test_get_post_detail(client, auth_headers):
    post = create_post(client)
    response = client.get(f"{API}/{post['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == post["id"]


def test_delete_post(client, auth_headers):
    post = create_post(client)
    assert client.delete(f"{API}/{post['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"{API}/{post['id']}", headers=auth_headers).status_code == 404
