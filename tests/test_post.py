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


# ==================== 首页「最新」====================
def test_latest_needs_no_login_and_only_approved(client, auth_headers):
    """无需登录；只出审核通过的。"""
    client.post(API, json={"title": "最新-待审"})
    approved = client.post(API, json={"title": "最新-通过"}).json()
    rejected = client.post(API, json={"title": "最新-拒绝"}).json()
    client.patch(
        f"{API}/{approved['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    client.patch(
        f"{API}/{rejected['id']}/status", headers=auth_headers, json={"status": "rejected"}
    )

    response = client.get(f"{API}/latest")  # 故意不带任何令牌
    assert response.status_code == 200, response.text
    titles = [item["title"] for item in response.json()["items"]]
    assert "最新-通过" in titles
    assert "最新-待审" not in titles
    assert "最新-拒绝" not in titles


def test_latest_ordered_by_published_at_desc(client, auth_headers):
    """按发布时间倒序。"""
    older = client.post(
        API, json={"title": "最新-先", "published_at": "2026-10-01T08:00:00"}
    ).json()
    newer = client.post(
        API, json={"title": "最新-后", "published_at": "2026-10-19T08:00:00"}
    ).json()
    for post in (older, newer):
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    # 取大页：测试库是共享的，前面用例可能已经写了不少内容，
    # 官号文章也会并进「最新」，只取默认 10 条容易漏掉这两条
    items = client.get(f"{API}/latest", params={"page": 1, "page_size": 50}).json()["items"]
    titles = [item["title"] for item in items]
    assert titles.index("最新-后") < titles.index("最新-先")


def test_latest_pagination(client, auth_headers):
    """分页参数生效。"""
    for index in range(3):
        post = client.post(
            API,
            json={
                "title": f"最新-分页-{index}",
                "published_at": f"2026-10-1{index}T00:00:00",
            },
        ).json()
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    first = client.get(f"{API}/latest", params={"page": 1, "page_size": 2}).json()
    assert first["page"] == 1 and first["page_size"] == 2
    assert len(first["items"]) == 2
    assert first["total"] >= 3

    second = client.get(f"{API}/latest", params={"page": 2, "page_size": 2}).json()
    assert len(second["items"]) >= 1
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )


# ==================== 访问量 / 热门 ====================
def test_view_count_increases_on_each_view(client, auth_headers):
    """每次调 /view，访问量 +1，出参带最新值。"""
    post = create_post(client, title="访问量-帖子")
    client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    assert post["view_count"] == 0

    first = client.post(f"{API}/{post['id']}/view")
    assert first.status_code == 200, first.text
    assert first.json()["view_count"] == 1

    second = client.post(f"{API}/{post['id']}/view")
    assert second.json()["view_count"] == 2

    # 后台详情读到的也是累加后的值
    detail = client.get(f"{API}/{post['id']}", headers=auth_headers).json()
    assert detail["view_count"] == 2


def test_view_count_404_for_missing_post(client):
    """不存在的帖子不能计数。"""
    assert client.post(f"{API}/999999/view").status_code == 404


def test_hot_orders_by_view_count_desc(client, auth_headers):
    """热门按访问量倒序；待审核的不出现。"""
    low = create_post(client, title="热门-冷门")
    high = create_post(client, title="热门-爆款")
    pending = create_post(client, title="热门-待审")
    for post in (low, high):
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    for _ in range(3):
        client.post(f"{API}/{high['id']}/view")
    client.post(f"{API}/{low['id']}/view")

    body = client.get(f"{API}/hot").json()
    titles = [item["title"] for item in body["items"]]
    assert titles.index("热门-爆款") < titles.index("热门-冷门")
    assert "热门-待审" not in titles
    assert all(item["status"] == "approved" for item in body["items"])


def test_hot_pagination(client, auth_headers):
    """热门支持分页，page_size 生效且两页不重复。"""
    for index in range(3):
        post = create_post(client, title=f"热门-分页-{index}")
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    first = client.get(f"{API}/hot", params={"page": 1, "page_size": 2}).json()
    assert first["page"] == 1 and first["page_size"] == 2
    assert len(first["items"]) == 2
    assert first["total"] >= 3

    second = client.get(f"{API}/hot", params={"page": 2, "page_size": 2}).json()
    assert len(second["items"]) >= 1
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )


# ==================== 推荐（近一年随机 10 条）====================
def test_recommend_only_recent_approved(client, auth_headers):
    """推荐只出近一年内已通过的帖子。"""
    recent = create_post(
        client, title="推荐-近期", published_at="2026-10-01T00:00:00"
    )
    old = create_post(
        client, title="推荐-很久以前", published_at="2020-01-01T00:00:00"
    )
    pending = create_post(client, title="推荐-待审")
    for post in (recent, old):
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    response = client.get(f"{API}/recommend")
    assert response.status_code == 200, response.text
    items = response.json()
    titles = {item["title"] for item in items}
    # 随机抽样：只校验「不该出现的不出现」，不依赖某条一定被抽中
    assert "推荐-很久以前" not in titles
    assert "推荐-待审" not in titles
    assert len(items) <= 10
    assert all(item["status"] == "approved" for item in items)


def test_recommend_at_most_10_without_duplicates(client, auth_headers):
    """候选超过 10 条时只给 10 条，且不重复。"""
    for index in range(12):
        post = create_post(
            client, title=f"推荐-批量-{index}", published_at="2026-10-01T00:00:00"
        )
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    items = client.get(f"{API}/recommend").json()
    assert len(items) == 10
    assert len({item["id"] for item in items}) == 10


# ==================== 点赞 / 获赞总数 ====================
def test_like_and_unlike_post(client, auth_headers):
    """点赞 / 取消点赞：计数与 is_liked 回显，重复点赞幂等。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "点赞-帖子"}).json()
    client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )

    liked = client.post(f"{API}/{post['id']}/like", headers=member)
    assert liked.status_code == 200, liked.text
    assert liked.json()["is_liked"] is True
    assert liked.json()["like_count"] == 1

    # 重复点赞不会多出计数
    assert client.post(f"{API}/{post['id']}/like", headers=member).json()["like_count"] == 1
    # 未登录不能点赞
    assert client.post(f"{API}/{post['id']}/like").status_code == 401

    removed = client.delete(f"{API}/{post['id']}/like", headers=member)
    assert removed.status_code == 200, removed.text
    assert removed.json()["is_liked"] is False
    assert removed.json()["like_count"] == 0


def test_like_only_approved_post(client, auth_headers):
    """待审核 / 已拒绝的帖子不能点赞。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "待审不能赞"}).json()
    assert client.post(f"{API}/{post['id']}/like", headers=member).status_code == 400


def test_received_likes_total(client, auth_headers):
    """获赞总数 = 自己所有帖子收到的赞（含多篇帖子累加）。"""
    author_id, author = _register_member(client)
    fan_id, fan = _register_member(client)

    first = client.post(API, headers=author, json={"title": "获赞-第一篇"}).json()
    second = client.post(API, headers=author, json={"title": "获赞-第二篇"}).json()
    for post in (first, second):
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    client.post(f"{API}/{first['id']}/like", headers=fan)
    client.post(f"{API}/{second['id']}/like", headers=fan)

    body = client.get(f"{API}/received-likes", headers=author)
    assert body.status_code == 200, body.text
    assert body.json()["received_like_count"] == 2

    # 只点赞别人的帖子：自己的获赞是 0
    assert (
        client.get(f"{API}/received-likes", headers=fan).json()["received_like_count"] == 0
    )
    # 未登录拿不到
    assert client.get(f"{API}/received-likes").status_code == 401


def test_received_like_posts_list(client, auth_headers):
    """获赞列表：只出自己有赞的帖子，按获赞数倒序。"""
    author_id, author = _register_member(client)
    fan1_id, fan1 = _register_member(client)
    fan2_id, fan2 = _register_member(client)

    hot = client.post(API, headers=author, json={"title": "获赞列表-热门"}).json()
    cold = client.post(API, headers=author, json={"title": "获赞列表-冷门"}).json()
    unliked = client.post(API, headers=author, json={"title": "获赞列表-无人赞"}).json()
    for post in (hot, cold, unliked):
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        )

    client.post(f"{API}/{hot['id']}/like", headers=fan1)
    client.post(f"{API}/{hot['id']}/like", headers=fan2)
    client.post(f"{API}/{cold['id']}/like", headers=fan1)

    body = client.get(f"{API}/received-likes/posts", headers=author)
    assert body.status_code == 200, body.text
    data = body.json()
    titles = [item["title"] for item in data["items"]]
    assert titles == ["获赞列表-热门", "获赞列表-冷门"]
    assert data["items"][0]["like_count"] == 2
    assert data["items"][1]["like_count"] == 1
    assert "获赞列表-无人赞" not in titles

    # 没发过帖 / 没收到赞的会员看到空列表
    assert client.get(f"{API}/received-likes/posts", headers=fan1).json()["total"] == 0
    # 未登录拿不到
    assert client.get(f"{API}/received-likes/posts").status_code == 401


def test_latest_carries_like_info(client, auth_headers):
    """列表出参带 like_count / is_liked（按查看者区分）。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "带点赞数的帖子"}).json()
    client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    client.post(f"{API}/{post['id']}/like", headers=member)

    guest_items = client.get(f"{API}/latest").json()["items"]
    guest = next(item for item in guest_items if item["id"] == post["id"])
    assert guest["like_count"] == 1
    assert guest["is_liked"] is False

    mine_items = client.get(f"{API}/latest", headers=member).json()["items"]
    mine = next(item for item in mine_items if item["id"] == post["id"])
    assert mine["is_liked"] is True


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


def test_member_posts_include_rejected(client, auth_headers):
    """「我的帖子」要能看到被拒绝的，并带回状态文案。"""
    member_id, member = _register_member(client)

    approved = client.post(API, headers=member, json={"title": "通过的"}).json()
    rejected = client.post(API, headers=member, json={"title": "被拒的"}).json()
    for post, state in ((approved, "approved"), (rejected, "rejected")):
        client.patch(f"{API}/{post['id']}/status", headers=auth_headers, json={"status": state})

    body = client.get(f"{API}/by-member/{member_id}", headers=member).json()
    by_title = {item["title"]: item for item in body["items"]}
    assert set(by_title) == {"通过的", "被拒的"}
    assert by_title["被拒的"]["status"] == "rejected"
    assert by_title["被拒的"]["status_text"] == "已拒绝"


def test_member_posts_owner_sees_all_guest_sees_approved(client, auth_headers):
    """本人能看到三种状态；访客只看到已通过（未过审内容不对外暴露）。"""
    member_id, member = _register_member(client)
    for title, state in (("待审的", None), ("通过的", "approved"), ("被拒的", "rejected")):
        post = client.post(API, headers=member, json={"title": title}).json()
        if state:
            client.patch(
                f"{API}/{post['id']}/status", headers=auth_headers, json={"status": state}
            )

    mine = client.get(f"{API}/by-member/{member_id}", headers=member).json()
    assert {item["title"] for item in mine["items"]} == {"待审的", "通过的", "被拒的"}

    guest = client.get(f"{API}/by-member/{member_id}").json()
    assert {item["title"] for item in guest["items"]} == {"通过的"}


# ==================== 发布者头像 ====================
def test_anonymous_post_has_empty_publisher_avatar(client):
    """匿名发帖没有发布会员，头像为空串。"""
    body = create_post(client)
    assert body["publisher_avatar"] == ""


def test_post_returns_publisher_avatar(client, auth_headers):
    """列表 / 详情都带回发布者头像：取会员上传的那张，没上传时为空。"""
    member_id, member = _register_member(client)

    post = client.post(API, headers=member, json={"title": "带头像的帖子"}).json()
    # 还没上传过头像：默认头像是 svg，客户端渲染不了，这里给空串让前端退回首字头像
    assert post["publisher_avatar"] == ""

    uploaded = client.post(
        f"{settings.API_V1_PREFIX}/member/profile/avatar",
        headers=member,
        files={"file": ("a.png", _PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    avatar_url = uploaded.json()["url"]

    client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )

    detail = client.get(f"{API}/{post['id']}", headers=auth_headers).json()
    assert detail["publisher_avatar"] == avatar_url

    latest = client.get(f"{API}/latest").json()
    item = next(entry for entry in latest["items"] if entry["id"] == post["id"])
    assert item["publisher_avatar"] == avatar_url

    mine = client.get(f"{API}/by-member/{member_id}", headers=member).json()
    assert mine["items"][0]["publisher_avatar"] == avatar_url

    # 给的是可直接访问的地址，取回来就是刚上传的那张图
    assert client.get(item["publisher_avatar"]).content == _PNG


def test_resubmit_rejected_post(client, auth_headers):
    """被拒绝的帖子：作者改完重新提交 → 回到待审核。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "旧标题", "content": "旧正文"}).json()
    client.patch(f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "rejected"})

    response = client.patch(
        f"{API}/{post['id']}",
        headers=member,
        json={"title": "新标题", "content": "改过的正文", "images": ["/api/v1/static/posts/x.png"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "新标题"
    assert body["content"] == "改过的正文"
    assert body["images"] == ["/api/v1/static/posts/x.png"]
    assert body["status"] == "pending"
    assert body["status_text"] == "待审核"

    # 待审核状态下不能再改（也就不会出现「卡在待审核却一直重提」）
    again = client.patch(f"{API}/{post['id']}", headers=member, json={"title": "再改一次"})
    assert again.status_code == 400
    assert "被拒绝" in again.text


def test_resubmit_after_reject_can_be_audited_again(client, auth_headers):
    """被拒 → 作者改完重提 → 回到待审核 → 管理员可以再下一次结论。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "一版"}).json()

    client.patch(f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "rejected"})
    # 重提前不能改判
    assert (
        client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
        ).status_code
        == 400
    )

    resubmitted = client.patch(
        f"{API}/{post['id']}", headers=member, json={"title": "二版"}
    ).json()
    assert resubmitted["status"] == "pending"

    second = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "approved"


def test_resubmit_requires_owner(client, auth_headers):
    """别人的帖子不能改。"""
    _, owner = _register_member(client)
    _, other = _register_member(client)

    post = client.post(API, headers=owner, json={"title": "作者的帖子"}).json()
    client.patch(f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "rejected"})

    response = client.patch(f"{API}/{post['id']}", headers=other, json={"title": "篡改"})
    assert response.status_code == 403
    assert "自己" in response.text


def test_resubmit_requires_login(client, auth_headers):
    """不带会员令牌不能改。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "待改的帖子"}).json()
    client.patch(f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "rejected"})

    assert client.patch(f"{API}/{post['id']}", json={"title": "匿名改"}).status_code == 401


def test_resubmit_approved_post_is_rejected(client, auth_headers):
    """已通过的帖子不允许改（避免绕过审核）。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "已通过的帖子"}).json()
    client.patch(f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"})

    response = client.patch(f"{API}/{post['id']}", headers=member, json={"title": "偷偷改"})
    assert response.status_code == 400


def test_member_posts_unknown_member_is_empty(client):
    """查不存在的会员：返回空列表而不是报错。"""
    body = client.get(f"{API}/by-member/999999").json()
    assert body["total"] == 0
    assert body["items"] == []


# ==================== 收藏 ====================
def _approved_post(client, auth_headers, title: str = "可收藏的帖子") -> dict:
    """发一条帖子并审核通过（只有通过的才能被收藏）。"""
    post = create_post(client, title=title)
    client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    return post


def test_favorite_requires_login(client, auth_headers):
    """收藏 / 取消收藏 / 我的收藏都要登录。"""
    post = _approved_post(client, auth_headers)
    assert client.post(f"{API}/{post['id']}/favorite").status_code == 401
    assert client.delete(f"{API}/{post['id']}/favorite").status_code == 401
    assert client.get(f"{API}/favorites").status_code == 401


def test_favorite_toggles_state_in_lists(client, auth_headers):
    """收藏后详情 / 列表的 is_favorited 变 true，取消后变回 false。"""
    member_id, member = _register_member(client)
    post = _approved_post(client, auth_headers, "收藏状态")

    saved = client.post(f"{API}/{post['id']}/favorite", headers=member)
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_favorited"] is True
    assert saved.json()["favorite_count"] == 1

    latest = client.get(f"{API}/latest", headers=member).json()
    item = next(entry for entry in latest["items"] if entry["id"] == post["id"])
    assert item["is_favorited"] is True
    assert item["favorite_count"] == 1

    # 未登录看同一条：收藏状态恒为 false
    anonymous = client.get(f"{API}/latest").json()
    guest = next(entry for entry in anonymous["items"] if entry["id"] == post["id"])
    assert guest["is_favorited"] is False

    # 我的收藏里有它
    favorites = client.get(f"{API}/favorites", headers=member).json()
    assert [entry["id"] for entry in favorites["items"]] == [post["id"]]
    assert favorites["items"][0]["is_favorited"] is True

    # 点赞信息也要带出来：收藏列表同样要能显示真实赞数 / 已点赞状态
    client.post(f"{API}/{post['id']}/like", headers=member)
    favorites = client.get(f"{API}/favorites", headers=member).json()
    assert favorites["items"][0]["like_count"] == 1
    assert favorites["items"][0]["is_liked"] is True

    removed = client.delete(f"{API}/{post['id']}/favorite", headers=member)
    assert removed.status_code == 200, removed.text
    assert removed.json()["is_favorited"] is False
    assert removed.json()["favorite_count"] == 0
    assert client.get(f"{API}/favorites", headers=member).json()["total"] == 0

    again = client.get(f"{API}/latest", headers=member).json()
    assert next(e for e in again["items"] if e["id"] == post["id"])["is_favorited"] is False


def test_favorite_is_idempotent(client, auth_headers):
    """重复收藏只留一条记录；没收藏过也能直接取消。"""
    member_id, member = _register_member(client)
    post = _approved_post(client, auth_headers)

    for _ in range(3):
        assert client.post(f"{API}/{post['id']}/favorite", headers=member).status_code == 200
    assert client.get(f"{API}/favorites", headers=member).json()["total"] == 1

    for _ in range(2):
        assert client.delete(f"{API}/{post['id']}/favorite", headers=member).status_code == 200


def test_favorite_only_approved_posts(client, auth_headers):
    """待审核 / 已拒绝的帖子不能收藏。"""
    member_id, member = _register_member(client)
    pending = client.post(API, headers=member, json={"title": "待审核的帖子"}).json()

    response = client.post(f"{API}/{pending['id']}/favorite", headers=member)
    assert response.status_code == 400
    assert "审核通过" in response.text


def test_favorites_newest_first_and_isolated(client, auth_headers):
    """按收藏时间倒序；各人的收藏互不干扰。"""
    first_id, first = _register_member(client)
    second_id, second = _register_member(client)
    older = _approved_post(client, auth_headers, "先收藏的")
    newer = _approved_post(client, auth_headers, "后收藏的")

    client.post(f"{API}/{older['id']}/favorite", headers=first)
    client.post(f"{API}/{newer['id']}/favorite", headers=first)
    client.post(f"{API}/{newer['id']}/favorite", headers=second)

    mine = client.get(f"{API}/favorites", headers=first).json()
    assert [item["title"] for item in mine["items"]] == ["后收藏的", "先收藏的"]
    # 收藏数是全体会员的总数：后收藏的帖子有两个人收藏
    counts = {item["title"]: item["favorite_count"] for item in mine["items"]}
    assert counts == {"后收藏的": 2, "先收藏的": 1}

    others = client.get(f"{API}/favorites", headers=second).json()
    assert [item["id"] for item in others["items"]] == [newer["id"]]
    assert others["items"][0]["favorite_count"] == 2


def test_favorites_drop_deleted_posts(client, auth_headers):
    """收藏的帖子被删掉后，不再出现在我的收藏里。"""
    member_id, member = _register_member(client)
    post = _approved_post(client, auth_headers, "会被删掉的帖子")
    client.post(f"{API}/{post['id']}/favorite", headers=member)

    assert client.delete(f"{API}/{post['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"{API}/favorites", headers=member).json()["total"] == 0


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
def test_audit_approved_is_final(client, auth_headers):
    """通过之后不能再改（改判 / 改回待审核都不行）。"""
    post = create_post(client)

    approved = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["status_text"] == "已通过"

    for target in ("rejected", "pending", "approved"):
        again = client.patch(
            f"{API}/{post['id']}/status", headers=auth_headers, json={"status": target}
        )
        assert again.status_code == 400, f"{target} 不该被允许"
        assert "不可再更改" in again.text or "只能改为" in again.text


def test_audit_rejected_is_final(client, auth_headers):
    """拒绝之后同样不能再改；作者重新提交后才会回到待审核。"""
    post = create_post(client)

    rejected = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "rejected"}
    )
    assert rejected.status_code == 200
    assert rejected.json()["status_text"] == "已拒绝"

    again = client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    assert again.status_code == 400
    assert "不可再更改" in again.text


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

def test_publisher_follows_member_nickname(client, auth_headers):
    """会员改昵称后，旧帖子的发布人昵称实时跟着变（库里存的是历史快照）。"""
    member_id, member = _register_member(client)
    post = client.post(API, headers=member, json={"title": "昵称同步"}).json()
    client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )

    profile_api = API.replace("/posts", "/member/profile")
    assert (
        client.put(
            profile_api, headers=member, json={"nickname": "改过的昵称"}
        ).status_code
        == 200
    )

    detail = client.get(f"{API}/detail/{post['id']}").json()
    assert detail["publisher"] == "改过的昵称"

    listed = client.get(f"{API}/latest").json()["items"]
    item = next(entry for entry in listed if entry["id"] == post["id"])
    assert item["publisher"] == "改过的昵称"

    # 后台列表 / 详情也要显示新昵称，并且能按新昵称搜到
    admin_items = client.get(API, headers=auth_headers).json()["items"]
    admin_item = next(entry for entry in admin_items if entry["id"] == post["id"])
    assert admin_item["publisher"] == "改过的昵称"

    admin_detail = client.get(f"{API}/{post['id']}", headers=auth_headers).json()
    assert admin_detail["publisher"] == "改过的昵称"

    searched = client.get(
        API, headers=auth_headers, params={"keyword": "改过的昵称"}
    ).json()
    assert post["id"] in [entry["id"] for entry in searched["items"]]

def test_upload_large_image_is_shrunk(client):
    """大图落盘前压缩：长边压到 1600 内、转 JPEG、体积明显变小。"""
    import io

    import pytest

    pytest.importorskip("PIL")
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (3200, 2000), (180, 40, 40)).save(buffer, format="PNG")
    raw = buffer.getvalue()

    response = client.post(
        f"{API}/images", files={"file": ("big.png", raw, "image/png")}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"].endswith(".jpg")
    assert body["size"] < len(raw)

    saved = client.get(body["url"])
    assert saved.status_code == 200
    with Image.open(io.BytesIO(saved.content)) as image:
        assert max(image.size) <= 1600

def test_my_post_endpoint_returns_rejected_own_post(client, auth_headers):
    """作者本人能按 ID 取回被拒绝的动态（未通过通知点进去改稿用），他人不行。"""
    _member_id, member = _register_member(client)
    _other_id, other = _register_member(client)

    post = client.post(API, headers=member, json={"title": "待拒绝", "content": "正文"}).json()
    client.patch(
        f"{API}/{post['id']}/status", headers=auth_headers, json={"status": "rejected"}
    )

    mine = client.get(f"{API}/mine/{post['id']}", headers=member)
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["status"] == "rejected"
    assert body["title"] == "待拒绝"

    assert client.get(f"{API}/mine/{post['id']}", headers=other).status_code == 403
    assert client.get(f"{API}/mine/{post['id']}").status_code == 401
