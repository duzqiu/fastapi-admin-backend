"""热搜榜单：按渠道出榜、渠道统计、后台列表 / 编辑 / 删除（后台不提供新增入口）。"""

import uuid

import pytest

from app.core.security import create_access_token
from app.models import HotListItem, User

PUBLIC_API = "/api/v1/hot-lists"
ADMIN_API = "/api/v1/hot-lists/admin"


@pytest.fixture()
def db(testing_session_local):
    with testing_session_local() as session:
        yield session


def unique_source(prefix: str = "baidu") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def add_items(session, source: str, count: int = 3, **overrides) -> list:
    """直接写库造数据：热搜榜单条目由爬虫写入，接口层没有新增。"""
    created = []
    for index in range(count):
        item = HotListItem(
            source=source,
            name=f"{source}-条目-{index}-{uuid.uuid4().hex[:6]}",
            heat=f"{index + 1}28.6万",
            tags=["热"] if index == 0 else [],
            rank=str(index + 1),
        )
        for key, value in overrides.items():
            setattr(item, key, value)
        session.add(item)
        created.append(item)
    session.commit()
    return created


def test_public_board_returns_source_count_and_all_fields(client, db):
    source = unique_source()
    add_items(db, source, count=3)

    response = client.get(PUBLIC_API, params={"source": source})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["source"] == source
    assert body["count"] == 3
    assert [item["id"] for item in body["items"]] == sorted(
        item["id"] for item in body["items"]
    )
    first = body["items"][0]
    assert set(first) == {
        "id",
        "source",
        "name",
        "heat",
        "tags",
        "rank",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert first["tags"] == ["热"]
    assert first["rank"] == "1"
    assert first["heat"].endswith("万")


def test_public_board_keeps_text_rank_and_limit_only_caps_items(client, db):
    source = unique_source("weibo")
    add_items(db, source, count=2, rank="置顶", heat=None, tags=[])

    body = client.get(PUBLIC_API, params={"source": source, "limit": 1}).json()
    assert body["count"] == 2, "count 是渠道总条数，不跟 limit 走"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["rank"] == "置顶", "排名原样保存，允许非数字"
    assert item["heat"] is None
    assert item["tags"] == []


def test_public_board_unknown_source_is_empty_not_404(client, db):
    body = client.get(PUBLIC_API, params={"source": unique_source("none")}).json()
    assert body["count"] == 0
    assert body["items"] == []

    # source 必填、limit 有上下限
    assert client.get(PUBLIC_API).status_code == 422
    source = unique_source()
    assert client.get(PUBLIC_API, params={"source": source, "limit": 0}).status_code == 422
    assert client.get(PUBLIC_API, params={"source": source, "limit": 201}).status_code == 422


def test_public_sources_lists_channels_with_counts(client, db):
    first, second = unique_source("chan-a"), unique_source("chan-b")
    add_items(db, first, count=2)
    add_items(db, second, count=1)

    response = client.get(f"{PUBLIC_API}/sources")
    assert response.status_code == 200, response.text
    mapping = {row["source"]: row["count"] for row in response.json()}
    assert mapping[first] == 2
    assert mapping[second] == 1


def test_admin_list_requires_admin_and_supports_filters(
    client, db, auth_headers, testing_session_local
):
    source = unique_source()
    add_items(db, source, count=2)
    assert client.get(ADMIN_API).status_code == 401

    with testing_session_local() as other:
        editor = User(
            username=f"editor-{uuid.uuid4().hex}",
            email=f"{uuid.uuid4().hex}@example.com",
            nickname="编辑",
            role="editor",
            is_active=True,
            hashed_password="unused",
        )
        other.add(editor)
        other.commit()
        editor_id = editor.id
    editor_headers = {
        "Authorization": f"Bearer {create_access_token(editor_id)}"
    }
    assert client.get(ADMIN_API, headers=editor_headers).status_code == 403

    body = client.get(ADMIN_API, headers=auth_headers, params={"source": source}).json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    keyword = body["items"][0]["name"]
    found = client.get(
        ADMIN_API, headers=auth_headers, params={"source": source, "keyword": keyword}
    ).json()
    assert found["total"] == 1
    assert found["items"][0]["name"] == keyword

    page = client.get(
        ADMIN_API,
        headers=auth_headers,
        params={"source": source, "page": 2, "page_size": 1},
    ).json()
    assert page["total"] == 2
    assert page["pages"] == 2
    assert len(page["items"]) == 1


def test_admin_update_is_partial_and_can_clear_optional_fields(client, db, auth_headers):
    source = unique_source()
    [item] = add_items(db, source, count=1)
    url = f"{ADMIN_API}/{item.id}"

    response = client.put(
        url,
        headers=auth_headers,
        json={"name": "新的标题", "tags": "热,新", "rank": "2"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "新的标题"
    assert body["tags"] == ["热", "新"]
    assert body["rank"] == "2"
    assert body["source"] == source, "没传的字段保持原值"
    assert body["heat"] == item.heat, "没传的字段保持原值"

    cleared = client.put(
        url, headers=auth_headers, json={"heat": "", "rank": None, "tags": []}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["heat"] is None
    assert cleared.json()["rank"] is None
    assert cleared.json()["tags"] == []

    for payload in (
        {"name": "   "},
        {"source": None},
        {"unknown_field": 1},
        {"tags": [f"t{index}" for index in range(21)]},
        {"rank": "x" * 21},
    ):
        response = client.put(url, headers=auth_headers, json=payload)
        assert response.status_code == 422, (payload, response.text)

    assert client.put(f"{ADMIN_API}/2147483647", headers=auth_headers, json={"name": "x"}).status_code == 404


def test_admin_detail_and_delete(client, db, auth_headers):
    [item] = add_items(db, unique_source(), count=1)
    url = f"{ADMIN_API}/{item.id}"

    detail = client.get(url, headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == item.id
    assert detail.json()["tags"] == ["热"]

    assert client.delete(url, headers=auth_headers).status_code == 200
    assert client.get(url, headers=auth_headers).status_code == 404
    assert client.delete(url, headers=auth_headers).status_code == 404


def test_article_hot_list_has_no_create_endpoint(client, auth_headers):
    """条目由爬虫写入，后台刻意不提供发布入口。"""
    payload = {
        "source": "baidu",
        "name": "不该被创建",
        "heat": None,
        "tags": [],
        "rank": "1",
    }
    assert client.post(ADMIN_API, headers=auth_headers, json=payload).status_code == 405
    assert client.post(PUBLIC_API, json=payload).status_code == 405

def test_public_board_hides_disabled_items(client, db):
    """已从最新榜单消失（is_active=False）的条目不再对外返回，但计数按启用条数。"""
    source = unique_source()
    add_items(db, source, count=3)
    [disabled] = add_items(db, source, count=1, is_active=False)

    body = client.get(PUBLIC_API, params={"source": source}).json()
    assert body["count"] == 3
    ids = [item["id"] for item in body["items"]]
    assert disabled.id not in ids


def test_public_sources_counts_only_active_items(client, db):
    first = unique_source("active-a")
    add_items(db, first, count=2)
    add_items(db, first, count=1, is_active=False)

    mapping = {
        row["source"]: row["count"] for row in client.get(f"{PUBLIC_API}/sources").json()
    }
    assert mapping[first] == 2


def test_admin_list_includes_disabled_and_filters_by_status(client, db, auth_headers):
    source = unique_source()
    add_items(db, source, count=2)
    add_items(db, source, count=3, is_active=False)

    everything = client.get(
        ADMIN_API, headers=auth_headers, params={"source": source}
    ).json()
    assert everything["total"] == 5

    enabled = client.get(
        ADMIN_API, headers=auth_headers, params={"source": source, "is_active": "true"}
    ).json()
    assert enabled["total"] == 2
    assert all(item["is_active"] is True for item in enabled["items"])

    disabled = client.get(
        ADMIN_API, headers=auth_headers, params={"source": source, "is_active": "false"}
    ).json()
    assert disabled["total"] == 3
    assert all(item["is_active"] is False for item in disabled["items"])


def test_admin_can_toggle_status(client, db, auth_headers):
    source = unique_source()
    [item] = add_items(db, source, count=1)
    url = f"{ADMIN_API}/{item.id}"

    off = client.put(url, headers=auth_headers, json={"is_active": False})
    assert off.status_code == 200, off.text
    assert off.json()["is_active"] is False
    assert client.get(PUBLIC_API, params={"source": source}).json()["count"] == 0

    on = client.put(url, headers=auth_headers, json={"is_active": True})
    assert on.json()["is_active"] is True
    assert client.get(PUBLIC_API, params={"source": source}).json()["count"] == 1

    assert client.put(url, headers=auth_headers, json={"is_active": None}).status_code == 422

def test_source_and_name_are_unique(db):
    """(source, name) 唯一索引：同一渠道同一标题不允许重复落库。"""
    from sqlalchemy.exc import IntegrityError

    source = unique_source()
    name = f"{source}-唯一标题"
    db.add(HotListItem(source=source, name=name, tags=[]))
    db.commit()

    db.add(HotListItem(source=source, name=name, tags=["热"]))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

def test_admin_update_rejects_duplicate_source_and_name(client, db, auth_headers):
    """后台把条目改成和同渠道另一条同名时，返回 400 而不是 500。"""
    source = unique_source()
    first, second = add_items(db, source, count=2)
    second.name = f"{unique_source('other')}-不同名"
    db.commit()

    response = client.put(
        f"{ADMIN_API}/{second.id}",
        headers=auth_headers,
        json={"name": first.name},
    )
    assert response.status_code == 400, response.text
    assert "同名" in response.json()["message"]


# ==================== 热度格式化 ====================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 已经是标准格式：原样保留（幂等）
        ("452.3万", "452.3万"),
        ("128.6万", "128.6万"),
        # 任意格式统一换成「万」
        ("4523000", "452.3万"),
        ("3.2亿", "32000万"),
        ("12.6k", "1.3万"),
        ("2.4w", "2.4万"),
        ("856千", "85.6万"),
        ("1,286", "0.1万"),
        # 最小 0.x万：1000~9999 保留在万级
        ("1000", "0.1万"),
        ("1286", "0.1万"),
        ("9999", "1万"),
        # 不足 0.x万（< 1000）降到千
        ("860", "0.9千"),
        ("100", "0.1千"),
        # 空值 / 解析不了的文本原样返回
        (None, None),
        ("", None),
        ("   ", None),
        ("热度未知", "热度未知"),
    ],
)
def test_format_heat(raw, expected):
    from app.schemas.article_hot_list import format_heat

    assert format_heat(raw) == expected


def test_public_board_normalizes_heat(client, db):
    """出参热度统一成 xx.x万 / 0.x万 / 0.x千，库里仍存爬虫原文。"""
    source = unique_source()
    add_items(
        db,
        source,
        count=1,
        heat="4523000",
        name=f"{source}-纯数字热度",
    )
    [other] = add_items(db, source, count=1, heat="860")

    body = client.get(PUBLIC_API, params={"source": source}).json()
    heats = {item["name"]: item["heat"] for item in body["items"]}
    assert heats[f"{source}-纯数字热度"] == "452.3万"
    assert heats[other.name] == "0.9千"
