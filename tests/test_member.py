"""用户中心（会员）测试：注册、登录、重置密码、资料维护、后台管理。

邮箱验证码在测试环境通过接口响应的 debug_code 字段获取（EMAIL_CODE_DEBUG_RETURN=true）。
"""

API = "/api/v1"
MEMBER_API = f"{API}/member"


def _send_code(client, email: str, scene: str) -> str:
    """发送验证码并返回明文验证码（调试回显）。"""
    response = client.post(f"{MEMBER_API}/auth/send-code", json={"email": email, "scene": scene})
    assert response.status_code == 200, response.text
    code = response.json().get("debug_code")
    assert code, "测试环境应回显 debug_code"
    return code


def _register(client, email: str, password: str = "member123", nickname: str = "") -> dict:
    code = _send_code(client, email, "register")
    response = client.post(
        f"{MEMBER_API}/auth/register",
        json={"email": email, "code": code, "password": password, "nickname": nickname},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _member_headers(client, email: str, password: str = "member123") -> dict:
    response = client.post(f"{MEMBER_API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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
    member = _register(client, "register01@example.com", nickname="小明")
    assert member["nickname"] == "小明"
    assert member["email_verified"] is True
    assert member["gender"] == "unknown"
    assert member["is_active"] is True

    # 重复注册 -> 409
    code = client.post(
        f"{MEMBER_API}/auth/send-code",
        json={"email": "register01@example.com", "scene": "register"},
    )
    assert code.status_code == 409


def test_register_wrong_code(client):
    client.post(f"{MEMBER_API}/auth/send-code", json={"email": "badcode@example.com", "scene": "register"})
    response = client.post(
        f"{MEMBER_API}/auth/register",
        json={"email": "badcode@example.com", "code": "000000", "password": "member123"},
    )
    assert response.status_code == 400
    assert "验证码" in response.json()["message"]


def test_register_weak_password_rejected(client):
    code = _send_code(client, "weak@example.com", "register")
    response = client.post(
        f"{MEMBER_API}/auth/register",
        json={"email": "weak@example.com", "code": code, "password": "12345678"},
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


def test_change_password(client):
    _register(client, "chpwd01@example.com")
    headers = _member_headers(client, "chpwd01@example.com")

    wrong = client.post(
        f"{MEMBER_API}/profile/change-password",
        headers=headers,
        json={"old_password": "wrong123", "new_password": "newpass123"},
    )
    assert wrong.status_code == 400

    ok = client.post(
        f"{MEMBER_API}/profile/change-password",
        headers=headers,
        json={"old_password": "member123", "new_password": "newpass123"},
    )
    assert ok.status_code == 200
    assert _member_headers(client, "chpwd01@example.com", "newpass123")


# ==================== 重置密码 ====================
def test_reset_password_flow(client):
    _register(client, "reset01@example.com")
    code = _send_code(client, "reset01@example.com", "reset_password")

    # 错误验证码
    bad = client.post(
        f"{MEMBER_API}/auth/reset-password",
        json={"email": "reset01@example.com", "code": "000000", "new_password": "brand123456"},
    )
    assert bad.status_code == 400

    # 重新获取后正确重置
    code = _send_code(client, "reset01@example.com", "reset_password")
    ok = client.post(
        f"{MEMBER_API}/auth/reset-password",
        json={"email": "reset01@example.com", "code": code, "new_password": "brand123456"},
    )
    assert ok.status_code == 200
    assert _member_headers(client, "reset01@example.com", "brand123456")


# ==================== 后台会员管理 ====================
def test_admin_member_management(client, auth_headers):
    member = _register(client, "managed01@example.com", nickname="待管理")
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
