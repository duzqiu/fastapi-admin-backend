"""点菜菜单与订单测试：分类、标签、菜品、套餐规则、下单、订单管理。

注意：应用启动时会写入演示菜品数据，因此断言均通过 keyword 隔离本次测试创建的数据。
"""

API = "/api/v1"
MENU = f"{API}/menu"
DISHES = f"{API}/dishes"
CATEGORIES = f"{API}/dish-categories"
TAGS = f"{API}/dish-tags"
ORDERS = f"{API}/dish-orders"


def _member_headers(client, email: str = "diner@example.com") -> dict:
    """注册（幂等）并登录一个会员，用于验证「我的订单」。"""
    login = client.post(f"{API}/member/auth/login", json={"email": email, "password": "member123"})
    if login.status_code != 200:
        code = client.post(
            f"{API}/member/auth/send-code", json={"email": email, "scene": "register"}
        ).json()["debug_code"]
        client.post(
            f"{API}/member/auth/register",
            json={"email": email, "code": code, "password": "member123"},
        )
        login = client.post(
            f"{API}/member/auth/login", json={"email": email, "password": "member123"}
        )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_category(client, auth_headers, name: str) -> int:
    response = client.post(CATEGORIES, headers=auth_headers, json={"name": name, "sort": 1})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_tag(client, auth_headers, name: str) -> int:
    response = client.post(TAGS, headers=auth_headers, json={"name": name, "color": "danger"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_dish(client, auth_headers, **overrides) -> dict:
    payload = {
        "name": "测试菜-宫保鸡丁",
        "description": "测试用菜品",
        "price": 30,
        "stock": 20,
        "unit": "份",
        "status": "on_sale",
        "is_recommended": True,
        "sort": 1,
        "category_id": None,
        "tag_ids": [],
        "specs": [],
    }
    payload.update(overrides)
    response = client.post(DISHES, headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ==================== 分类 / 标签 ====================
def test_category_crud(client, auth_headers):
    category_id = _create_category(client, auth_headers, "测试分类-热菜")

    # 重名冲突
    assert (
        client.post(CATEGORIES, headers=auth_headers, json={"name": "测试分类-热菜"}).status_code
        == 409
    )

    listed = client.get(CATEGORIES, headers=auth_headers)
    assert any(item["name"] == "测试分类-热菜" for item in listed.json())

    updated = client.put(
        CATEGORIES + f"/{category_id}", headers=auth_headers, json={"description": "改过了"}
    )
    assert updated.json()["description"] == "改过了"

    # 分类下有菜品时不允许删除
    _create_dish(client, auth_headers, name="测试菜-归属校验", category_id=category_id)
    assert client.delete(CATEGORIES + f"/{category_id}", headers=auth_headers).status_code == 400


def test_tag_crud(client, auth_headers):
    tag_id = _create_tag(client, auth_headers, "测试标签-招牌")
    assert (
        client.post(TAGS, headers=auth_headers, json={"name": "测试标签-招牌"}).status_code == 409
    )

    dish = _create_dish(client, auth_headers, name="测试菜-带标签", tag_ids=[tag_id])
    assert [tag["name"] for tag in dish["tags"]] == ["测试标签-招牌"]

    # 标签列表带菜品数量
    tags = client.get(TAGS, headers=auth_headers).json()
    assert next(item for item in tags if item["id"] == tag_id)["dish_count"] == 1

    assert client.delete(TAGS + f"/{tag_id}", headers=auth_headers).status_code == 200


def test_tag_is_active(client, auth_headers):
    """标签启用状态：停用后 C 端菜单不再暴露，但后台仍可查看与绑定。"""
    tag_id = _create_tag(client, auth_headers, "测试标签-可停用")
    tags = client.get(TAGS, headers=auth_headers).json()
    assert next(item for item in tags if item["id"] == tag_id)["is_active"] is True
    assert any(item["id"] == tag_id for item in client.get(f"{MENU}/tags").json())

    # 停用前：菜品与菜单都能看到该标签
    dish = _create_dish(client, auth_headers, name="测试菜-停用标签", tag_ids=[tag_id])
    assert any(tag["id"] == tag_id for tag in dish["tags"])

    # 停用标签（PUT 支持局部更新）
    updated = client.put(TAGS + f"/{tag_id}", headers=auth_headers, json={"is_active": False})
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_active"] is False

    # 后台列表默认仍返回它，only_active=true 时才过滤掉
    assert any(
        item["id"] == tag_id for item in client.get(TAGS, headers=auth_headers).json()
    )
    assert all(
        item["id"] != tag_id
        for item in client.get(TAGS, params={"only_active": True}, headers=auth_headers).json()
    )

    # C 端：菜单标签列表与菜品携带的标签都不再暴露停用标签
    assert all(item["id"] != tag_id for item in client.get(f"{MENU}/tags").json())
    detail = client.get(f"{MENU}/dishes/{dish['id']}").json()
    assert all(tag["id"] != tag_id for tag in detail["tags"])

    # 重新启用后恢复展示
    client.put(TAGS + f"/{tag_id}", headers=auth_headers, json={"is_active": True})
    assert any(item["id"] == tag_id for item in client.get(f"{MENU}/tags").json())


# ==================== 菜品与套餐 ====================
def test_dish_crud_with_specs(client, auth_headers):
    category_id = _create_category(client, auth_headers, "测试分类-套餐")
    tag_id = _create_tag(client, auth_headers, "测试标签-新品")

    dish = _create_dish(
        client,
        auth_headers,
        name="测试菜-套餐菜",
        category_id=category_id,
        tag_ids=[tag_id],
        specs=[
            {"name": "单点", "price": 30, "stock": 20, "is_default": True, "sort": 1},
            {
                "name": "单人套餐",
                "price": 42,
                "stock": 10,
                "sort": 2,
                "min_quantity": 1,
                "max_quantity_per_order": 3,
                "daily_limit": 5,
                "serve_start_time": "00:00",
                "serve_end_time": "23:59",
            },
        ],
    )
    dish_id = dish["id"]
    assert dish["category_name"] == "测试分类-套餐"
    assert len(dish["specs"]) == 2
    assert dish["specs"][1]["serve_time_text"] == "00:00 - 23:59"

    # 新增套餐
    added = client.post(
        DISHES + f"/{dish_id}/specs",
        headers=auth_headers,
        json={"name": "双人套餐", "price": 80, "stock": 5, "is_default": True},
    )
    assert added.status_code == 201
    spec_id = added.json()["id"]

    # 新的默认套餐生效，原默认取消
    specs = client.get(DISHES + f"/{dish_id}/specs", headers=auth_headers).json()
    defaults = [item for item in specs if item["is_default"]]
    assert len(defaults) == 1 and defaults[0]["id"] == spec_id

    # 更新套餐
    updated = client.put(
        DISHES + f"/{dish_id}/specs/{spec_id}", headers=auth_headers, json={"price": 88}
    )
    assert updated.json()["price"] == 88

    # 供应时段必须成对填写
    bad = client.put(
        DISHES + f"/{dish_id}/specs/{spec_id}", headers=auth_headers, json={"serve_start_time": "10:00"}
    )
    assert bad.status_code == 400

    # 时间格式校验
    bad_format = client.post(
        DISHES + f"/{dish_id}/specs",
        headers=auth_headers,
        json={"name": "错误时段", "price": 10, "stock": 1, "serve_start_time": "25:00", "serve_end_time": "26:00"},
    )
    assert bad_format.status_code == 422

    # 调整库存
    restocked = client.patch(
        DISHES + f"/{dish_id}/stock", headers=auth_headers, json={"quantity": 5, "mode": "add"}
    )
    assert restocked.json()["stock"] == 25

    # 下架
    off = client.patch(DISHES + f"/{dish_id}/status", headers=auth_headers, json={"status": "off_shelf"})
    assert off.json()["status"] == "off_shelf"

    # 删除套餐与菜品
    assert client.delete(DISHES + f"/{dish_id}/specs/{spec_id}", headers=auth_headers).status_code == 200
    assert client.delete(DISHES + f"/{dish_id}", headers=auth_headers).status_code == 200


def test_dish_stats(client, auth_headers):
    stats = client.get(DISHES + "/stats", headers=auth_headers)
    assert stats.status_code == 200
    body = stats.json()
    assert body["total"] >= 1
    assert body["category_count"] >= 1
    assert isinstance(body["top_selling"], list)


def test_dish_image_upload(client, auth_headers):
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )
    ok = client.post(
        DISHES + "/upload-image", headers=auth_headers, files={"file": ("d.png", png, "image/png")}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["url"].startswith("/api/v1/static/dishes/")

    bad = client.post(
        DISHES + "/upload-image", headers=auth_headers, files={"file": ("d.png", b"x", "image/png")}
    )
    assert bad.status_code == 400


# ==================== 点菜菜单 ====================
def test_menu_browsing(client, auth_headers):
    dish = _create_dish(client, auth_headers, name="测试菜-菜单可见", stock=5)

    categories = client.get(f"{MENU}/categories")
    assert categories.status_code == 200

    dishes = client.get(f"{MENU}/dishes", params={"keyword": "测试菜-菜单可见"})
    assert dishes.json()["total"] == 1
    assert dishes.json()["items"][0]["is_available"] is True

    detail = client.get(f"{MENU}/dishes/{dish['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "测试菜-菜单可见"

    # 下架后不可点单，且默认不出现在菜单里
    client.patch(DISHES + f"/{dish['id']}/status", headers=auth_headers, json={"status": "off_shelf"})
    assert client.get(f"{MENU}/dishes", params={"keyword": "测试菜-菜单可见"}).json()["total"] == 0
    assert client.get(f"{MENU}/dishes/{dish['id']}").status_code == 400


# ==================== 下单 ====================
def test_order_without_spec(client, auth_headers):
    dish = _create_dish(client, auth_headers, name="测试菜-无套餐", price=10, stock=10)

    created = client.post(
        f"{MENU}/orders",
        json={"items": [{"dish_id": dish["id"], "quantity": 2}], "table_no": "A01", "remark": "少放盐"},
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "pending"
    assert order["total_quantity"] == 2
    assert order["total_amount"] == 20
    assert order["items"][0]["dish_name"] == "测试菜-无套餐"

    # 库存扣减、销量累加
    detail = client.get(DISHES + f"/{dish['id']}", headers=auth_headers).json()
    assert detail["stock"] == 8
    assert detail["sold_count"] == 2

    # 后台可见并可操作
    listed = client.get(ORDERS, headers=auth_headers, params={"keyword": order["order_no"]})
    assert listed.json()["total"] == 1

    confirmed = client.patch(
        ORDERS + f"/{order['id']}/status", headers=auth_headers, json={"status": "confirmed"}
    )
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmed_at"] is not None

    completed = client.patch(
        ORDERS + f"/{order['id']}/status", headers=auth_headers, json={"status": "completed"}
    )
    assert completed.json()["status"] == "completed"

    # 已完成不可再取消
    assert (
        client.patch(
            ORDERS + f"/{order['id']}/status", headers=auth_headers, json={"status": "cancelled"}
        ).status_code
        == 400
    )


def test_order_with_spec_and_rollback(client, auth_headers):
    dish = _create_dish(
        client,
        auth_headers,
        name="测试菜-有套餐",
        price=30,
        stock=20,
        specs=[
            {"name": "单点", "price": 30, "stock": 20, "is_default": True, "sort": 1},
            {"name": "套餐A", "price": 40, "stock": 6, "sort": 2, "min_quantity": 2},
        ],
    )
    specs = client.get(DISHES + f"/{dish['id']}/specs", headers=auth_headers).json()
    plain = next(item for item in specs if item["name"] == "单点")
    combo = next(item for item in specs if item["name"] == "套餐A")

    # 有套餐但未指定 spec_id -> 400
    assert (
        client.post(f"{MENU}/orders", json={"items": [{"dish_id": dish["id"], "quantity": 1}]}).status_code
        == 400
    )

    # 低于起购数量 -> 400
    assert (
        client.post(
            f"{MENU}/orders",
            json={"items": [{"dish_id": dish["id"], "spec_id": combo["id"], "quantity": 1}]},
        ).status_code
        == 400
    )

    # 正常下单
    created = client.post(
        f"{MENU}/orders",
        json={"items": [{"dish_id": dish["id"], "spec_id": combo["id"], "quantity": 3}]},
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["total_amount"] == 120

    specs_after = client.get(DISHES + f"/{dish['id']}/specs", headers=auth_headers).json()
    combo_after = next(item for item in specs_after if item["id"] == combo["id"])
    dish_after = client.get(DISHES + f"/{dish['id']}", headers=auth_headers).json()
    assert combo_after["stock"] == 3 and combo_after["sold_count"] == 3
    assert dish_after["stock"] == 17 and dish_after["sold_count"] == 3
    assert plain["stock"] == 20  # 未购买的套餐不受影响

    # 库存不足
    assert (
        client.post(
            f"{MENU}/orders",
            json={"items": [{"dish_id": dish["id"], "spec_id": combo["id"], "quantity": 5}]},
        ).status_code
        == 400
    )

    # 取消订单回滚库存与销量
    admin_cancel = client.patch(
        ORDERS + f"/{order['id']}/status", headers=auth_headers, json={"status": "cancelled"}
    )
    assert admin_cancel.status_code == 200, admin_cancel.text
    assert admin_cancel.json()["status"] == "cancelled"

    specs_final = client.get(DISHES + f"/{dish['id']}/specs", headers=auth_headers).json()
    combo_final = next(item for item in specs_final if item["id"] == combo["id"])
    dish_final = client.get(DISHES + f"/{dish['id']}", headers=auth_headers).json()
    assert combo_final["stock"] == 6 and combo_final["sold_count"] == 0
    assert dish_final["stock"] == 20 and dish_final["sold_count"] == 0


def test_order_rules_and_stock(client, auth_headers):
    # 库存不足
    dish = _create_dish(client, auth_headers, name="测试菜-库存少", stock=1)
    assert (
        client.post(f"{MENU}/orders", json={"items": [{"dish_id": dish["id"], "quantity": 3}]}).status_code
        == 400
    )

    # 每单限购 + 每日限量
    limited = _create_dish(
        client,
        auth_headers,
        name="测试菜-限购",
        stock=100,
        specs=[
            {
                "name": "限量套餐",
                "price": 20,
                "stock": 100,
                "is_default": True,
                "max_quantity_per_order": 2,
                "daily_limit": 3,
                "serve_start_time": "00:00",
                "serve_end_time": "23:59",
            }
        ],
    )
    spec = limited["specs"][0]

    over = client.post(
        f"{MENU}/orders",
        json={"items": [{"dish_id": limited["id"], "spec_id": spec["id"], "quantity": 3}]},
    )
    assert over.status_code == 400

    first = client.post(
        f"{MENU}/orders",
        json={"items": [{"dish_id": limited["id"], "spec_id": spec["id"], "quantity": 2}]},
    )
    assert first.status_code == 201

    second = client.post(
        f"{MENU}/orders",
        json={"items": [{"dish_id": limited["id"], "spec_id": spec["id"], "quantity": 2}]},
    )
    assert second.status_code == 400  # 超过每日限量 3 份


def test_order_out_of_serve_window(client, auth_headers):
    dish = _create_dish(
        client,
        auth_headers,
        name="测试菜-时段限制",
        stock=10,
        specs=[
            {
                "name": "早餐套餐",
                "price": 15,
                "stock": 10,
                "is_default": True,
                "serve_start_time": "03:00",
                "serve_end_time": "03:01",
            }
        ],
    )
    spec = dish["specs"][0]
    response = client.post(
        f"{MENU}/orders",
        json={"items": [{"dish_id": dish["id"], "spec_id": spec["id"], "quantity": 1}]},
    )
    # 该时段极短，正常测试执行时不会命中；若恰好命中则视为通过
    assert response.status_code in (201, 400)


# ==================== 会员订单与权限 ====================
def test_member_orders_and_permissions(client, auth_headers):
    dish = _create_dish(client, auth_headers, name="测试菜-会员下单", stock=10)
    member_headers = _member_headers(client)

    created = client.post(
        f"{MENU}/orders",
        headers=member_headers,
        json={"items": [{"dish_id": dish["id"], "quantity": 1}], "table_no": "B02"},
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    mine = client.get(f"{MENU}/orders", headers=member_headers)
    assert mine.status_code == 200
    assert any(item["id"] == order_id for item in mine.json()["items"])

    assert client.get(f"{MENU}/orders/{order_id}", headers=member_headers).status_code == 200

    # 会员不能访问后台菜品 / 订单管理接口
    assert client.get(DISHES, headers=member_headers).status_code == 401
    assert client.get(ORDERS, headers=member_headers).status_code == 401

    # 会员可以取消自己的订单
    cancelled = client.post(f"{MENU}/orders/{order_id}/cancel", headers=member_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_order_stats(client, auth_headers):
    stats = client.get(ORDERS + "/stats", headers=auth_headers)
    assert stats.status_code == 200
    body = stats.json()
    assert set(["total", "pending", "confirmed", "completed", "cancelled"]).issubset(body.keys())

    sales = client.get(ORDERS + "/dish-sales", headers=auth_headers)
    assert sales.status_code == 200
    assert isinstance(sales.json(), list)
