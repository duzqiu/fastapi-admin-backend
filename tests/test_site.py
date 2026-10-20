"""个人网站设置接口测试：欢迎语与「关于我」密码。"""

API = "/api/v1"
PUBLIC_WELCOME = f"{API}/site/welcome"
PUBLIC_VERIFY = f"{API}/site/about/verify"
PUBLIC_ACCESS = f"{API}/site/about/access"
ADMIN_WELCOME = f"{API}/site/admin/welcome"
ADMIN_PASSWORD = f"{API}/site/admin/about-password"


def test_public_welcome_defaults(client):
    response = client.get(PUBLIC_WELCOME)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"]
    assert data["subtitle"]
    assert "blessing" in data


def test_about_password_verify(client):
    wrong = client.post(PUBLIC_VERIFY, json={"password": "wrong-password"})
    assert wrong.status_code == 400

    ok = client.post(PUBLIC_VERIFY, json={"password": "123456"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True


def test_admin_update_welcome_and_password(client, auth_headers):
    # 未登录不能访问后台设置
    assert client.get(ADMIN_WELCOME).status_code == 401

    payload = {
        "title": "中文主标题 · 测试工程师",
        "subtitle": "功能测试 · 自动化测试 · 接口测试",
        "blessing": "愿你今天也有好心情。",
    }
    updated = client.put(ADMIN_WELCOME, headers=auth_headers, json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json() == payload
    assert client.get(PUBLIC_WELCOME).json() == payload

    status = client.get(ADMIN_PASSWORD, headers=auth_headers)
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert status.json()["enabled"] is True
    assert status.json()["password"] == "123456"

    # 最低 4 位，少于 4 位接口直接拒绝
    too_short = client.put(
        ADMIN_PASSWORD,
        headers=auth_headers,
        json={"enabled": True, "password": "abc"},
    )
    assert too_short.status_code == 422

    # 长中文密码：旧 bcrypt 会在 72 字节处截断，两个前缀相同的密码会撞车；
    # 现在先 SHA-256 再 bcrypt，整串中文都参与校验。
    chinese_password = "这是一个很长的中文访问密码" * 4 + "甲"
    another_password = "这是一个很长的中文访问密码" * 4 + "乙"
    changed = client.put(
        ADMIN_PASSWORD,
        headers=auth_headers,
        json={"enabled": True, "password": chinese_password},
    )
    assert changed.status_code == 200, changed.text
    assert client.get(
        ADMIN_PASSWORD, headers=auth_headers
    ).json()["password"] == chinese_password

    assert client.post(
        PUBLIC_VERIFY, json={"password": "123456"}
    ).status_code == 400
    assert client.post(
        PUBLIC_VERIFY, json={"password": chinese_password}
    ).status_code == 200
    assert client.post(
        PUBLIC_VERIFY, json={"password": another_password}
    ).status_code == 400

    # 关闭后不校验密码，公开状态接口同步返回 false
    disabled = client.put(
        ADMIN_PASSWORD,
        headers=auth_headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    assert client.get(PUBLIC_ACCESS).json()["password_enabled"] is False
    assert client.post(
        PUBLIC_VERIFY, json={"password": "任意错误密码"}
    ).status_code == 200

    # 重新开启并复位密码，避免影响同一次测试会话里的其它用例
    re_enabled = client.put(
        ADMIN_PASSWORD,
        headers=auth_headers,
        json={"enabled": True, "password": "123456"},
    )
    assert re_enabled.status_code == 200
    assert re_enabled.json()["enabled"] is True
    assert client.get(PUBLIC_ACCESS).json()["password_enabled"] is True
    assert client.post(
        PUBLIC_VERIFY, json={"password": "123456"}
    ).status_code == 200
