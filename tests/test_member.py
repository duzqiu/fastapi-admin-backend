"""用户中心（会员）测试：注册、登录、重置密码、资料维护、后台管理。

邮箱验证码在测试环境通过接口响应的 debug_code 字段获取（EMAIL_CODE_DEBUG_RETURN=true）。
"""

import re

import pytest

API = "/api/v1"
MEMBER_API = f"{API}/member"


def _send_code(client, email: str, scene: str) -> str:
    """发送验证码并返回明文验证码（调试回显）。"""
    response = client.post(f"{MEMBER_API}/auth/send-code", json={"email": email, "scene": scene})
    assert response.status_code == 200, response.text
    code = response.json().get("debug_code")
    assert code, "测试环境应回显 debug_code"
    return code


def _register(client, email: str, password: str = "member123", confirm_password: str = "") -> dict:
    """注册并返回会员信息；confirm_password 留空时默认与 password 一致。"""
    code = _send_code(client, email, "register")
    response = client.post(
        f"{MEMBER_API}/auth/register",
        json={
            "email": email,
            "code": code,
            "password": password,
            "confirm_password": confirm_password or password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _member_headers(client, email: str, password: str = "member123") -> dict:
    response = client.post(f"{MEMBER_API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _send_member_code(client, headers: dict) -> str:
    """登录状态下发送「修改密码」验证码（邮箱取当前账号），返回明文验证码。"""
    response = client.post(f"{MEMBER_API}/send-code", headers=headers)
    assert response.status_code == 200, response.text
    code = response.json().get("debug_code")
    assert code, "测试环境应回显 debug_code"
    return code


# ==================== 注册流程 ====================
def test_send_code_scene_validation(client):
    # 注册场景：邮箱已注册 -> 409
    _register(client, "dup@example.com")
    conflict = client.post(
        f"{MEMBER_API}/auth/send-code", json={"email": "dup@example.com", "scene": "register"}
    )
    assert conflict.status_code == 409

    # 重置密码场景：邮箱未注册 -> 400
    missing = client.post(
        f"{MEMBER_API}/auth/send-code", json={"email": "nobody@example.com", "scene": "reset_password"}
    )
    assert missing.status_code == 400


def test_send_code_cooldown(client, monkeypatch):
    """冷却时间内重复发送应被拒绝（测试环境默认把冷却设为 0）。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "EMAIL_CODE_RESEND_SECONDS", 60)

    email = "cooldown01@example.com"
    first = client.post(f"{MEMBER_API}/auth/send-code", json={"email": email, "scene": "register"})
    assert first.status_code == 200

    second = client.post(f"{MEMBER_API}/auth/send-code", json={"email": email, "scene": "register"})
    assert second.status_code == 400
    assert "频繁" in second.json()["message"]


def test_register_and_duplicate(client):
    from app.core.config import settings

    member = _register(client, "register01@example.com")
    # 昵称由系统自动生成，头像使用默认头像
    assert member["nickname"], "注册后应自动生成默认昵称"
    assert member["avatar"] == settings.DEFAULT_AVATAR
    assert member["email_verified"] is True
    assert member["gender"] == "unknown"
    assert member["is_active"] is True
    # 注册成功会生成 10 位数字会员编号
    assert re.fullmatch(r"\d{10}", member["member_no"]), member["member_no"]

    # 重复注册 -> 409
    code = client.post(
        f"{MEMBER_API}/auth/send-code",
        json={"email": "register01@example.com", "scene": "register"},
    )
    assert code.status_code == 409


def test_register_generates_unique_member_no(client, auth_headers):
    """注册生成的 10 位会员编号随机且不重复，并能被后台按编号检索。"""
    numbers = []
    for index in range(4):
        member = _register(client, f"memberno{index:02d}@example.com")
        assert re.fullmatch(r"\d{10}", member["member_no"]), member["member_no"]
        numbers.append(member["member_no"])

    assert len(set(numbers)) == len(numbers), f"会员编号不能重复: {numbers}"

    # 后台列表返回编号，并支持按编号搜索
    listed = client.get(
        f"{API}/members", headers=auth_headers, params={"keyword": numbers[0]}
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["member_no"] == numbers[0]

    # 编号是 10 位纯数字，且不会超过长度上限
    from app.core.utils import generate_member_no

    assert all(len(generate_member_no()) == 10 for _ in range(200))


def test_register_password_mismatch(client):
    """两次密码不一致 -> 422。"""
    code = _send_code(client, "mismatch01@example.com", "register")
    response = client.post(
        f"{MEMBER_API}/auth/register",
        json={
            "email": "mismatch01@example.com",
            "code": code,
            "password": "member123",
            "confirm_password": "member456",
        },
    )
    assert response.status_code == 422
    assert "两次输入的密码不一致" in response.text


def test_register_wrong_code(client):
    client.post(f"{MEMBER_API}/auth/send-code", json={"email": "badcode@example.com", "scene": "register"})
    response = client.post(
        f"{MEMBER_API}/auth/register",
        json={
            "email": "badcode@example.com",
            "code": "000000",
            "password": "member123",
            "confirm_password": "member123",
        },
    )
    assert response.status_code == 400
    assert "验证码" in response.json()["message"]


def test_register_weak_password_rejected(client):
    code = _send_code(client, "weak@example.com", "register")
    response = client.post(
        f"{MEMBER_API}/auth/register",
        json={
            "email": "weak@example.com",
            "code": code,
            "password": "12345678",
            "confirm_password": "12345678",
        },
    )
    assert response.status_code == 422


# ==================== 登录 / 令牌 ====================
def test_login_and_token_scope(client, auth_headers):
    _register(client, "login01@example.com")
    headers = _member_headers(client, "login01@example.com")

    me = client.get(f"{MEMBER_API}/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "login01@example.com"

    # 会员令牌不能访问后台接口
    assert client.get(f"{API}/users", headers=headers).status_code == 401
    assert client.get(f"{API}/members", headers=headers).status_code == 401

    # 后台令牌不能访问用户中心接口
    assert client.get(f"{MEMBER_API}/profile", headers=auth_headers).status_code == 401

    # 密码错误
    bad = client.post(
        f"{MEMBER_API}/auth/login", json={"email": "login01@example.com", "password": "wrong123"}
    )
    assert bad.status_code == 401


def test_refresh_token(client):
    _register(client, "refresh01@example.com")
    login = client.post(
        f"{MEMBER_API}/auth/login", json={"email": "refresh01@example.com", "password": "member123"}
    ).json()
    refreshed = client.post(
        f"{MEMBER_API}/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


# ==================== 资料维护 ====================
def test_profile_update(client):
    _register(client, "profile01@example.com")
    headers = _member_headers(client, "profile01@example.com")

    payload = {
        "nickname": "资料已完善",
        "gender": "female",
        "birthday": "1998-03-15",
        "phone": "13900000000",
        "bio": "你好，我是新注册的用户。",
        "avatar": "https://cdn.example.com/avatar.png",
    }
    updated = client.put(f"{MEMBER_API}/profile", headers=headers, json=payload)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["nickname"] == "资料已完善"
    assert body["gender"] == "female"
    assert body["birthday"] == "1998-03-15"
    assert body["age"] and body["age"] > 0
    assert body["phone"] == "13900000000"

    # 生日不能晚于今天
    future = client.put(f"{MEMBER_API}/profile", headers=headers, json={"birthday": "2999-01-01"})
    assert future.status_code == 422


def test_avatar_upload(client):
    _register(client, "avatar01@example.com")
    headers = _member_headers(client, "avatar01@example.com")

    # 1x1 透明 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )
    ok = client.post(
        f"{MEMBER_API}/profile/avatar",
        headers=headers,
        files={"file": ("a.png", png, "image/png")},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["url"].startswith("/api/v1/static/avatars/")

    # 非图片内容 -> 400
    bad = client.post(
        f"{MEMBER_API}/profile/avatar",
        headers=headers,
        files={"file": ("a.png", b"not-an-image", "image/png")},
    )
    assert bad.status_code == 400

    # 不支持的扩展名 -> 400
    bad_ext = client.post(
        f"{MEMBER_API}/profile/avatar",
        headers=headers,
        files={"file": ("a.txt", png, "text/plain")},
    )
    assert bad_ext.status_code == 400


def test_avatar_stored_and_returned_by_profile(client):
    """头像按会员 ID 分目录存放，并由「查看我的资料」接口的 avatar_url 带出来。"""
    from app.core.config import settings

    member = _register(client, "avatar02@example.com")
    member_id = member["id"]
    headers = _member_headers(client, "avatar02@example.com")

    # 1x1 透明 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )

    # 还没上传：资料接口给出的就是系统默认头像地址
    profile = client.get(f"{MEMBER_API}/profile", headers=headers).json()
    assert profile["avatar_url"] == settings.DEFAULT_AVATAR

    # 上传：URL 与磁盘位置都以会员 ID 为维度
    ok = client.post(
        f"{MEMBER_API}/profile/avatar",
        headers=headers,
        files={"file": ("a.png", png, "image/png")},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert f"/avatars/{member_id}/" in body["url"]
    directory = settings.upload_dir / "avatars" / str(member_id)
    assert directory.is_dir(), f"头像应放在 {directory}"
    assert (directory / body["filename"]).is_file()

    # 资料接口带出的 avatar_url 指向刚上传那张，且真的能取到图片
    profile = client.get(f"{MEMBER_API}/profile", headers=headers).json()
    assert f"/avatars/{member_id}/" in profile["avatar_url"]
    assert profile["avatar_url"] == body["url"]
    image = client.get(profile["avatar_url"])
    assert image.status_code == 200
    assert image.content == png

    # 旧的「读取头像」接口已移除（头像地址统一由资料接口给出）
    assert client.get(f"{MEMBER_API}/profile/avatar", headers=headers).status_code == 405
    assert client.get(f"{MEMBER_API}/avatar/{member_id}", headers=headers).status_code == 404


def test_background_stored_and_returned_by_profile(client, auth_headers):
    """背景图：与头像同一套规则 —— 按会员 ID 分目录存，资料接口的 background_url 带出。"""
    from app.core.config import settings

    member = _register(client, "bg01@example.com")
    member_id = member["id"]
    headers = _member_headers(client, "bg01@example.com")

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )

    # 还没上传：背景没有默认图，background_url 是空串
    profile = client.get(f"{MEMBER_API}/profile", headers=headers).json()
    assert profile["background"] == ""
    assert profile["background_url"] == ""

    # 上传：目录以会员 ID 命名
    ok = client.post(
        f"{MEMBER_API}/profile/background",
        headers=headers,
        files={"file": ("bg.png", png, "image/png")},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert f"/backgrounds/{member_id}/" in body["url"]
    directory = settings.upload_dir / "backgrounds" / str(member_id)
    assert (directory / body["filename"]).is_file()

    # 资料接口带出的 background_url 指向刚上传那张，且真的能取到
    profile = client.get(f"{MEMBER_API}/profile", headers=headers).json()
    assert profile["background_url"] == body["url"]
    assert client.get(profile["background_url"]).content == png

    # 覆盖上传：目录里只留最新一张
    ok2 = client.post(
        f"{MEMBER_API}/profile/background",
        headers=headers,
        files={"file": ("bg2.png", png, "image/png")},
    )
    assert ok2.status_code == 200
    assert len([item for item in directory.iterdir() if item.is_file()]) == 1
    assert client.get(f"{MEMBER_API}/profile", headers=headers).json()[
        "background_url"
    ] == ok2.json()["url"]

    # 后台代传：同一个会员目录，且后台详情带出的地址与会员侧一致
    admin_ok = client.post(
        f"{API}/members/{member_id}/background",
        headers=auth_headers,
        files={"file": ("bg3.png", png, "image/png")},
    )
    assert admin_ok.status_code == 200, admin_ok.text
    assert f"/backgrounds/{member_id}/" in admin_ok.json()["url"]
    detail = client.get(f"{API}/members/{member_id}", headers=auth_headers).json()
    assert detail["background_url"] == admin_ok.json()["url"]
    # 后台可以直接取图片流；会员令牌不能调后台接口
    assert client.get(
        f"{API}/members/{member_id}/background", headers=auth_headers
    ).content == png
    assert (
        client.post(
            f"{API}/members/{member_id}/background",
            headers=headers,
            files={"file": ("bg.png", png, "image/png")},
        ).status_code
        == 401
    )


def test_iphone_heic_avatar_converted_to_jpeg(client):
    """iPhone 拍的 HEIC 头像：接口照收，但**落盘一定是 JPEG**（HEIC 哪儿都渲染不了）。"""
    import io

    from PIL import Image

    from app.core.config import settings

    pytest.importorskip("pillow_heif")

    member = _register(client, "heic01@example.com")
    member_id = member["id"]
    headers = _member_headers(client, "heic01@example.com")

    import pillow_heif

    pillow_heif.register_heif_opener()
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 100, 50)).save(buffer, format="HEIF")
    heic = buffer.getvalue()

    ok = client.post(
        f"{MEMBER_API}/profile/avatar",
        headers=headers,
        # 后缀故意用大写：iOS 给的文件名经常是 `IMG_0001.HEIC`
        files={"file": ("IMG_0001.HEIC", heic, "image/heic")},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["url"].endswith(".jpg"), body

    stored = settings.upload_dir / "avatars" / str(member_id) / body["filename"]
    content = stored.read_bytes()
    assert content.startswith(b"\xff\xd8\xff"), "落盘文件必须是 JPEG"
    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "JPEG"

    # 资料接口带出的地址指向这张 JPEG，且能直接取到
    profile = client.get(f"{MEMBER_API}/profile", headers=headers).json()
    assert profile["avatar_url"] == body["url"]
    assert client.get(profile["avatar_url"]).content == content


def test_profile_update_nickname_bio_gender_birthday_region(client):
    """修改资料接口一次可改：昵称 / 简介 / 性别 / 生日 / 地区；未传的字段保持原值。"""
    member = _register(client, "profile02@example.com")
    assert member["region"] == ""
    headers = _member_headers(client, "profile02@example.com")

    payload = {
        "nickname": "七七",
        "bio": "爱做饭的程序员",
        "gender": "female",
        "birthday": "1995-08-08",
        "region": "苏州",
    }
    updated = client.put(f"{MEMBER_API}/profile", headers=headers, json=payload)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["nickname"] == "七七"
    assert body["bio"] == "爱做饭的程序员"
    assert body["gender"] == "female"
    assert body["birthday"] == "1995-08-08"
    assert body["region"] == "苏州"

    # 回读：GET /member/profile 拿到的就是改后的值
    profile = client.get(f"{MEMBER_API}/profile", headers=headers).json()
    assert profile["nickname"] == "七七"
    assert profile["bio"] == "爱做饭的程序员"
    assert profile["gender"] == "female"
    assert profile["birthday"] == "1995-08-08"
    assert profile["region"] == "苏州"

    # 只改一个字段时，其余字段保持原值
    only = client.put(f"{MEMBER_API}/profile", headers=headers, json={"region": "南京"})
    assert only.status_code == 200, only.text
    assert only.json()["region"] == "南京"
    assert only.json()["bio"] == "爱做饭的程序员"
    assert only.json()["nickname"] == "七七"
    assert only.json()["gender"] == "female"


def test_admin_update_profile_fields(client, auth_headers):
    """后台修改资料同样支持：昵称 / 简介 / 性别 / 生日 / 地区（外加启用状态）。"""
    member = _register(client, "adminprofile01@example.com")
    member_id = member["id"]

    updated = client.put(
        f"{API}/members/{member_id}",
        headers=auth_headers,
        json={
            "nickname": "后台改名",
            "bio": "后台写的简介",
            "gender": "male",
            "birthday": "1990-02-02",
            "region": "重庆",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["nickname"] == "后台改名"
    assert body["bio"] == "后台写的简介"
    assert body["gender"] == "male"
    assert body["birthday"] == "1990-02-02"
    assert body["region"] == "重庆"

    # 会员侧看到的是同一份资料
    headers = _member_headers(client, "adminprofile01@example.com")
    assert client.get(f"{MEMBER_API}/profile", headers=headers).json()["region"] == "重庆"


def test_member_list_item_keeps_editable_fields(client, auth_headers):
    """后台列表项必须带出可编辑字段：从列表点「编辑」原样保存时，简介/手机号不能被清空。"""
    member = _register(client, "listitem01@example.com")
    headers = _member_headers(client, "listitem01@example.com")
    client.put(
        f"{MEMBER_API}/profile",
        headers=headers,
        json={"phone": "13800000000", "bio": "列表别把我弄丢", "region": "西安"},
    )

    item = client.get(
        f"{API}/members", headers=auth_headers, params={"keyword": "listitem01"}
    ).json()["items"][0]
    assert item["phone"] == "13800000000"
    assert item["bio"] == "列表别把我弄丢"
    assert item["region"] == "西安"

    # 模拟后台「编辑」：把列表项原样回填并提交
    saved = client.put(
        f"{API}/members/{item['id']}",
        headers=auth_headers,
        json={
            "nickname": item["nickname"],
            "gender": item["gender"],
            "birthday": item["birthday"],
            "phone": item["phone"],
            "region": item["region"],
            "bio": item["bio"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["bio"] == "列表别把我弄丢"
    assert saved.json()["phone"] == "13800000000"


def test_profile_region(client):
    """资料新增「地区」字段：注册默认为空，可改、可回读，超长报错。"""
    member = _register(client, "region01@example.com")
    assert member["region"] == ""
    headers = _member_headers(client, "region01@example.com")

    updated = client.put(f"{MEMBER_API}/profile", headers=headers, json={"region": "杭州"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["region"] == "杭州"

    # 超过 64 字符 -> 422
    too_long = client.put(f"{MEMBER_API}/profile", headers=headers, json={"region": "杭" * 65})
    assert too_long.status_code == 422


def test_admin_upload_and_read_avatar_by_member_id(client, auth_headers):
    """后台：按会员 ID 上传 / 读取头像（与会员自助上传同一套存放规则）。"""
    from app.core.config import settings

    member = _register(client, "adminavatar01@example.com")
    member_id = member["id"]

    # 1x1 透明 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )

    # 未上传：后台读头像退回系统默认头像
    before = client.get(f"{API}/members/{member_id}/avatar", headers=auth_headers)
    assert before.status_code == 200
    assert "svg" in before.headers["content-type"]

    # 上传：以会员 ID 为维度落盘
    ok = client.post(
        f"{API}/members/{member_id}/avatar",
        headers=auth_headers,
        files={"file": ("a.png", png, "image/png")},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert f"/avatars/{member_id}/" in body["url"]
    directory = settings.upload_dir / "avatars" / str(member_id)
    assert (directory / body["filename"]).is_file()

    # 按会员 ID 读回来就是刚上传那张
    after = client.get(f"{API}/members/{member_id}/avatar", headers=auth_headers)
    assert after.status_code == 200
    assert after.content == png

    # 会员侧资料接口带出的 avatar_url 指向同一张（两端共用一份文件）
    member_headers = _member_headers(client, "adminavatar01@example.com")
    profile = client.get(f"{MEMBER_API}/profile", headers=member_headers).json()
    assert f"/avatars/{member_id}/" in profile["avatar_url"]
    assert client.get(profile["avatar_url"]).content == png

    # 后台详情同样带出 avatar_url
    detail = client.get(f"{API}/members/{member_id}", headers=auth_headers).json()
    assert detail["avatar_url"] == profile["avatar_url"]

    # 后台接口不接受会员令牌；会员不存在 -> 404
    assert (
        client.post(
            f"{API}/members/{member_id}/avatar",
            headers=member_headers,
            files={"file": ("a.png", png, "image/png")},
        ).status_code
        == 401
    )
    assert client.get(f"{API}/members/999999/avatar", headers=auth_headers).status_code == 404


def test_admin_update_region(client, auth_headers):
    """后台可编辑「地区」字段。"""
    member = _register(client, "adminregion01@example.com")
    member_id = member["id"]

    updated = client.put(
        f"{API}/members/{member_id}",
        headers=auth_headers,
        json={"nickname": member["nickname"], "region": "成都"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["region"] == "成都"

    # 列表也带出地区
    listed = client.get(
        f"{API}/members", headers=auth_headers, params={"keyword": "adminregion01"}
    ).json()
    assert listed["items"][0]["region"] == "成都"


def test_change_password(client):
    _register(client, "chpwd01@example.com")
    headers = _member_headers(client, "chpwd01@example.com")

    # 未登录不能获取改密码验证码
    assert client.post(f"{MEMBER_API}/send-code").status_code == 401

    # 公开发送验证码接口不接受 change_password 场景（必须走登录态）
    public = client.post(
        f"{MEMBER_API}/auth/send-code",
        json={"email": "chpwd01@example.com", "scene": "change_password"},
    )
    assert public.status_code == 400

    code = _send_member_code(client, headers)

    # 验证码错误 -> 400
    wrong = client.post(
        f"{MEMBER_API}/profile/change-password",
        headers=headers,
        json={"code": "000000", "new_password": "newpass123", "confirm_password": "newpass123"},
    )
    assert wrong.status_code == 400

    # 两次密码不一致 -> 422
    mismatch = client.post(
        f"{MEMBER_API}/profile/change-password",
        headers=headers,
        json={"code": code, "new_password": "newpass123", "confirm_password": "other123"},
    )
    assert mismatch.status_code == 422

    ok = client.post(
        f"{MEMBER_API}/profile/change-password",
        headers=headers,
        json={"code": code, "new_password": "newpass123", "confirm_password": "newpass123"},
    )
    assert ok.status_code == 200, ok.text
    assert _member_headers(client, "chpwd01@example.com", "newpass123")

    # 验证码一次性：重复使用 -> 400
    reuse = client.post(
        f"{MEMBER_API}/profile/change-password",
        headers=headers,
        json={"code": code, "new_password": "another123", "confirm_password": "another123"},
    )
    assert reuse.status_code == 400


# ==================== 重置密码 ====================
def test_reset_password_flow(client):
    _register(client, "reset01@example.com")
    code = _send_code(client, "reset01@example.com", "reset_password")

    # 错误验证码
    bad = client.post(
        f"{MEMBER_API}/auth/reset-password",
        json={
            "email": "reset01@example.com",
            "code": "000000",
            "new_password": "brand123456",
            "confirm_password": "brand123456",
        },
    )
    assert bad.status_code == 400

    # 两次密码不一致 -> 422
    mismatch = client.post(
        f"{MEMBER_API}/auth/reset-password",
        json={
            "email": "reset01@example.com",
            "code": "000000",
            "new_password": "brand123456",
            "confirm_password": "brand654321",
        },
    )
    assert mismatch.status_code == 422
    assert "两次输入的密码不一致" in mismatch.text

    # 重新获取后正确重置
    code = _send_code(client, "reset01@example.com", "reset_password")
    ok = client.post(
        f"{MEMBER_API}/auth/reset-password",
        json={
            "email": "reset01@example.com",
            "code": code,
            "new_password": "brand123456",
            "confirm_password": "brand123456",
        },
    )
    assert ok.status_code == 200
    assert _member_headers(client, "reset01@example.com", "brand123456")


# ==================== 后台会员管理 ====================
def test_admin_member_management(client, auth_headers):
    member = _register(client, "managed01@example.com")
    member_id = member["id"]

    # 列表 + 搜索
    listed = client.get(f"{API}/members", headers=auth_headers, params={"keyword": "managed01"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["email"] == "managed01@example.com"

    # 详情
    assert client.get(f"{API}/members/{member_id}", headers=auth_headers).status_code == 200

    # 管理员修改资料
    updated = client.put(
        f"{API}/members/{member_id}",
        headers=auth_headers,
        json={"nickname": "管理员改名", "gender": "male", "birthday": "2000-01-01", "is_active": True},
    )
    assert updated.status_code == 200
    assert updated.json()["nickname"] == "管理员改名"
    assert updated.json()["gender"] == "male"

    # 禁用后无法登录，且已有令牌立即失效
    headers = _member_headers(client, "managed01@example.com")
    disabled = client.patch(
        f"{API}/members/{member_id}/status", headers=auth_headers, json={"is_active": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert client.get(f"{MEMBER_API}/profile", headers=headers).status_code == 401
    assert (
        client.post(
            f"{MEMBER_API}/auth/login",
            json={"email": "managed01@example.com", "password": "member123"},
        ).status_code
        == 401
    )

    # 重新启用
    assert (
        client.patch(
            f"{API}/members/{member_id}/status", headers=auth_headers, json={"is_active": True}
        ).status_code
        == 200
    )

    # 管理员重置密码
    reset = client.patch(
        f"{API}/members/{member_id}/password",
        headers=auth_headers,
        json={"new_password": "adminreset123"},
    )
    assert reset.status_code == 200
    assert _member_headers(client, "managed01@example.com", "adminreset123")

    # 统计
    stats = client.get(f"{API}/members/stats", headers=auth_headers)
    assert stats.status_code == 200
    assert stats.json()["total"] >= 1

    # 删除
    assert client.delete(f"{API}/members/{member_id}", headers=auth_headers).status_code == 200
    assert client.get(f"{API}/members/{member_id}", headers=auth_headers).status_code == 404


# ==================== 公开资料（帖子作者主页用，无需登录）====================
def test_public_member_profile_needs_no_login(client):
    """作者主页要的资料：不带令牌也能读到昵称 / 简介 / 头像，且不含隐私字段。"""
    member = _register(client, "public-author@example.com")
    headers = _member_headers(client, "public-author@example.com")
    client.put(
        f"{MEMBER_API}/profile", headers=headers, json={"bio": "写代码，也写生活"}
    )

    response = client.get(f"{API}/members/{member['id']}/public")  # 故意不带令牌
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["id"] == member["id"]
    assert body["nickname"] == member["nickname"]
    assert body["bio"] == "写代码，也写生活"
    assert body["avatar_url"].startswith("/api/v1/")
    # 隐私字段一律不出
    for key in ("email", "phone", "birthday", "last_login_at"):
        assert key not in body


@pytest.mark.parametrize("gender", ["male", "female", "unknown"])
def test_public_member_profile_gender(client, gender):
    """性别保存后可由公开主页回读，保密使用 unknown，不泄露其他隐私。"""
    email = f"public-gender-{gender}@example.com"
    member = _register(client, email)
    headers = _member_headers(client, email)
    # 先设为男，保证 unknown 用例也验证从已公开切回保密。
    initial = client.put(f"{MEMBER_API}/profile", headers=headers, json={"gender": "male"})
    assert initial.status_code == 200, initial.text
    updated = client.put(f"{MEMBER_API}/profile", headers=headers, json={"gender": gender})
    assert updated.status_code == 200, updated.text
    assert updated.json()["gender"] == gender
    profile = client.get(f"{MEMBER_API}/profile", headers=headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()["gender"] == gender
    response = client.get(f"{API}/members/{member['id']}/public")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gender"] == gender
    for key in ("email", "phone", "birthday", "last_login_at"):
        assert key not in body


def test_public_member_profile_unknown_is_404(client):
    """不存在的会员按 404 处理。"""
    assert client.get(f"{API}/members/999999/public").status_code == 404


def test_public_member_profile_disabled_is_404(client, auth_headers):
    """被禁用的账号同样按不存在处理，别把账号状态暴露出去。"""
    member = _register(client, "public-disabled@example.com")
    client.patch(
        f"{API}/members/{member['id']}/status",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert client.get(f"{API}/members/{member['id']}/public").status_code == 404
