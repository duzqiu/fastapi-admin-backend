"""接口冒烟测试：验证认证、后台账号两条主链路。"""


def test_health(client):
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_success_and_failure(client):
    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong123"})
    assert bad.status_code == 401
    assert bad.json()["code"] == 40100


def test_me_requires_token(client, auth_headers):
    assert client.get("/api/v1/auth/me").status_code == 401
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_user_crud(client, auth_headers):
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "username": "tester01",
            "email": "tester01@example.com",
            "nickname": "测试账号",
            "role": "user",
            "password": "abc123456",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    listed = client.get("/api/v1/users", headers=auth_headers, params={"keyword": "tester01"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    updated = client.put(
        f"/api/v1/users/{user_id}", headers=auth_headers, json={"nickname": "改名了"}
    )
    assert updated.status_code == 200
    assert updated.json()["nickname"] == "改名了"

    deleted = client.delete(f"/api/v1/users/{user_id}", headers=auth_headers)
    assert deleted.status_code == 200
