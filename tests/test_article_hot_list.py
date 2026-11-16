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
            tabs=["热"] if index == 0 else [],
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
        "tabs",
        "rank",
        "created_at",
        "updated_at",
    }
    assert first["tabs"] == ["热"]
    assert first["rank"] == "1"
    assert first["heat"].endswith("万")


def test_public_board_keeps_text_rank_and_limit_only_caps_items(client, db):
    source = unique_source("weibo")
    add_items(db, source, count=2, rank="置顶", heat=None, tabs=[])

    body = client.get(PUBLIC_API, params={"source": source, "limit": 1}).json()
    assert body["count"] == 2, "count 是渠道总条数，不跟 limit 走"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["rank"] == "置顶", "排名原样保存，允许非数字"
    assert item["heat"] is None
    assert item["tabs"] == []


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
        json={"name": "新的标题", "tabs": "热,新", "rank": "2"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "新的标题"
    assert body["tabs"] == ["热", "新"]
    assert body["rank"] == "2"
    assert body["source"] == source, "没传的字段保持原值"
    assert body["heat"] == item.heat, "没传的字段保持原值"

    cleared = client.put(
        url, headers=auth_headers, json={"heat": "", "rank": None, "tabs": []}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["heat"] is None
    assert cleared.json()["rank"] is None
    assert cleared.json()["tabs"] == []

    for payload in (
        {"name": "   "},
        {"source": None},
        {"unknown_field": 1},
        {"tabs": [f"t{index}" for index in range(21)]},
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
    assert detail.json()["tabs"] == ["热"]

    assert client.delete(url, headers=auth_headers).status_code == 200
    assert client.get(url, headers=auth_headers).status_code == 404
    assert client.delete(url, headers=auth_headers).status_code == 404


def test_article_hot_list_has_no_create_endpoint(client, auth_headers):
    """条目由爬虫写入，后台刻意不提供发布入口。"""
    payload = {
        "source": "baidu",
        "name": "不该被创建",
        "heat": None,
        "tabs": [],
        "rank": "1",
    }
    assert client.post(ADMIN_API, headers=auth_headers, json=payload).status_code == 405
    assert client.post(PUBLIC_API, json=payload).status_code == 405
