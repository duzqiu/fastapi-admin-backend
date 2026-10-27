"""站内消息测试：互动事件写入通知、未读数、已读。"""

import uuid
from datetime import datetime

import pytest

from app.core.config import settings
from app.models.message import MemberMessage

API = settings.API_V1_PREFIX
POSTS = f"{API}/posts"
MEMBERS = f"{API}/members"
COMMENTS = f"{API}/comments"
MESSAGES = f"{API}/messages"


def _register_member(client) -> tuple[int, dict, str]:
    email = f"msg-{uuid.uuid4().hex[:8]}@example.com"
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
    return me["id"], headers, me["nickname"]


def _approved_post(client, auth_headers, author_headers, title="消息-帖子") -> dict:
    post = client.post(POSTS, headers=author_headers, json={"title": title}).json()
    client.patch(
        f"{POSTS}/{post['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    return post


def _messages(client, headers) -> list[dict]:
    body = client.get(MESSAGES, headers=headers)
    assert body.status_code == 200, body.text
    return body.json()["items"]


def test_follow_creates_message(client, auth_headers):
    """关注后对方收到通知；未读数 / 单条已读 / 全部已读都生效。"""
    author_id, author, author_name = _register_member(client)
    fan_id, fan, fan_name = _register_member(client)

    client.post(f"{MEMBERS}/{author_id}/follow", headers=fan)

    items = _messages(client, author)
    assert items and items[0]["type"] == "follow"
    assert items[0]["title"] == f"{fan_name} 关注了你"
    assert items[0]["is_read"] is False

    unread = client.get(f"{MESSAGES}/unread-count", headers=author)
    assert unread.json()["unread_count"] >= 1

    first_id = items[0]["id"]
    assert (
        client.post(f"{MESSAGES}/{first_id}/read", headers=author).status_code == 200
    )
    assert client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"] == 0

    # 换一个人再关注一次，用「全部已读」清掉（同一人重复关注是幂等的，不会重复通知）
    third_id, third, _ = _register_member(client)
    client.post(f"{MEMBERS}/{author_id}/follow", headers=third)
    assert client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"] >= 1
    assert client.post(f"{MESSAGES}/read-all", headers=author).status_code == 200
    assert client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"] == 0

    # 未登录拿不到
    assert client.get(MESSAGES).status_code == 401


def test_like_and_comment_create_messages(client, auth_headers):
    """点赞 / 评论都会通知作者；自己赞自己不产生消息。"""
    author_id, author, _ = _register_member(client)
    fan_id, fan, fan_name = _register_member(client)
    post = _approved_post(client, auth_headers, author)

    client.post(f"{POSTS}/{post['id']}/like", headers=fan)
    comment = client.post(
        f"{POSTS}/{post['id']}/comments", headers=fan, json={"content": "写得好"}
    ).json()

    types = [item["type"] for item in _messages(client, author)]
    assert "like" in types
    # 评论还没审核通过：此时不该有「评论了你的帖子」的通知
    assert "comment" not in types

    # 后台审核通过后才通知作者
    client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    picked = {item["type"]: item for item in _messages(client, author)}
    assert "comment" in picked
    assert picked["like"]["post_id"] == post["id"]
    assert fan_name in picked["comment"]["title"]
    # 文案统一用「动态」，不再出现「帖子」
    assert "动态" in picked["like"]["title"]
    assert "动态" in picked["comment"]["title"]

    # 自己赞自己的帖子：不该多出消息
    before = client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"]
    client.post(f"{POSTS}/{post['id']}/like", headers=author)
    after = client.get(f"{MESSAGES}/unread-count", headers=author).json()["unread_count"]
    assert after == before


def test_audit_results_create_messages(client, auth_headers):
    """帖子 / 评论审核结果会通知作者与评论人。"""
    author_id, author, _ = _register_member(client)
    fan_id, fan, _ = _register_member(client)

    post = _approved_post(client, auth_headers, author, title="待审核的帖子")
    comment = client.post(
        f"{POSTS}/{post['id']}/comments", headers=fan, json={"content": "待审评论"}
    ).json()

    audited = client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    assert audited.status_code == 200, audited.text

    commenter_types = [item["type"] for item in _messages(client, fan)]
    assert "comment_audit" in commenter_types

    # 帖子审核：新建一条待审核帖子再通过
    pending = client.post(POSTS, headers=author, json={"title": "第二条"}).json()
    client.patch(
        f"{POSTS}/{pending['id']}/status", headers=auth_headers, json={"status": "approved"}
    )
    author_items = _messages(client, author)
    assert "post_audit" in [item["type"] for item in author_items]
    audit_title = next(
        item["title"] for item in author_items if item["type"] == "post_audit"
    )
    assert "动态" in audit_title and "帖子" not in audit_title


@pytest.fixture()
def mixed_messages(client, testing_session_local):
    """交错写入不同类型和不同会员的消息，避免分页后过滤也侥幸通过。"""
    member_id, headers, _ = _register_member(client)
    other_id, other_headers, _ = _register_member(client)
    message_types = [
        "like", "follow", "comment", "like", "post_audit",
        "follow", "like", "comment_audit",
    ]
    own_ids = {message_type: [] for message_type in message_types}
    other_ids = []
    with testing_session_local() as db:
        for message_type in message_types:
            message = MemberMessage(
                member_id=member_id,
                type=message_type,
                title=f"我的{message_type}消息",
                created_at=datetime(2026, 1, 1),
            )
            other_message = MemberMessage(
                member_id=other_id,
                type=message_type,
                title=f"他人的{message_type}消息",
                created_at=datetime(2026, 1, 1),
            )
            db.add_all([message, other_message])
            db.flush()
            own_ids[message_type].append(message.id)
            other_ids.append(other_message.id)
        db.commit()
    return headers, other_headers, own_ids, other_ids


@pytest.mark.parametrize(
    "message_type", ["like", "follow", "comment", "post_audit", "comment_audit"]
)
def test_messages_filter_by_type(client, mixed_messages, message_type):
    """三类互动和两类审核消息均支持 type 筛选，且不会泄漏他人消息。"""
    headers, _, own_ids, other_ids = mixed_messages
    response = client.get(MESSAGES, headers=headers, params={"type": message_type})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(own_ids[message_type])
    assert [item["id"] for item in body["items"]] == own_ids[message_type][::-1]
    assert all(item["type"] == message_type for item in body["items"])
    assert not set(other_ids).intersection(item["id"] for item in body["items"])


def test_messages_without_type_returns_mixed_types(client, mixed_messages):
    """不传 type 仍返回当前会员所有类型，并保持最新在前。"""
    headers, _, own_ids, _ = mixed_messages
    response = client.get(MESSAGES, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    expected_ids = sorted(
        [message_id for ids in own_ids.values() for message_id in ids], reverse=True
    )
    assert body["total"] == len(expected_ids)
    assert [item["id"] for item in body["items"]] == expected_ids
    assert {item["type"] for item in body["items"]} == set(own_ids)


def test_messages_filtered_pagination_total(client, mixed_messages):
    """类型必须在 SQL 分页前过滤，total/pages 也只能计入自己的匹配消息。"""
    headers, _, own_ids, _ = mixed_messages
    expected_ids = own_ids["like"][::-1]
    for page, expected in [(1, expected_ids[:2]), (2, expected_ids[2:]), (3, [])]:
        response = client.get(
            MESSAGES,
            headers=headers,
            params={"type": "like", "page": page, "page_size": 2},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 3
        assert body["pages"] == 2
        assert body["page"] == page
        assert body["page_size"] == 2
        assert [item["id"] for item in body["items"]] == expected


def test_messages_filter_cannot_read_other_members_messages(client, mixed_messages):
    """双方按同类型查询也只能看见各自的消息。"""
    _, other_headers, own_ids, other_ids = mixed_messages
    response = client.get(MESSAGES, headers=other_headers, params={"type": "follow"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert all(item["type"] == "follow" for item in body["items"])
    assert {item["id"] for item in body["items"]}.issubset(other_ids)
    assert not set(own_ids["follow"]).intersection(item["id"] for item in body["items"])


@pytest.mark.parametrize("message_type", ["unknown", "LIKE", "", "like,follow"])
def test_messages_invalid_type_returns_422(client, message_type):
    _, headers, _ = _register_member(client)
    response = client.get(MESSAGES, headers=headers, params={"type": message_type})
    assert response.status_code == 422, response.text


def test_messages_filter_with_no_matches_returns_empty_page(client, testing_session_local):
    """当前会员没有该类型时返回空页，即使其他会员有匹配的消息。"""
    member_id, headers, _ = _register_member(client)
    other_id, _, _ = _register_member(client)
    with testing_session_local() as db:
        db.add_all([
            MemberMessage(member_id=member_id, type="follow", title="我的关注消息"),
            MemberMessage(member_id=other_id, type="like", title="他人的点赞消息"),
        ])
        db.commit()
    response = client.get(MESSAGES, headers=headers, params={"type": "like"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["pages"] == 0


def test_unread_counts_by_type_cover_all_messages_and_isolate_members(
    client, testing_session_local
):
    """分类统计包含五类、超过一页的未读，不含已读或其他会员的消息。"""
    member_id, headers, _ = _register_member(client)
    other_id, other_headers, _ = _register_member(client)
    expected_counts = {
        "like": 25, "follow": 2, "comment": 3,
        "post_audit": 1, "comment_audit": 1,
    }
    with testing_session_local() as db:
        for message_type, count in expected_counts.items():
            db.add_all([
                MemberMessage(member_id=member_id, type=message_type)
                for _ in range(count)
            ])
            db.add(MemberMessage(
                member_id=member_id, type=message_type, is_read=True
            ))
        db.add_all([
            MemberMessage(member_id=other_id, type="like") for _ in range(4)
        ])
        db.commit()

    response = client.get(f"{MESSAGES}/unread-count", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "unread_count": sum(expected_counts.values()),
        "counts_by_type": expected_counts,
    }
    other_response = client.get(f"{MESSAGES}/unread-count", headers=other_headers)
    assert other_response.status_code == 200, other_response.text
    assert other_response.json() == {
        "unread_count": 4, "counts_by_type": {"like": 4},
    }


@pytest.mark.parametrize(
    "message_type", ["like", "follow", "comment", "post_audit", "comment_audit"]
)
def test_mark_all_read_by_type_preserves_other_types_and_members(
    client, mixed_messages, message_type
):
    """分类全读只清当前会员该类型，其余类型与其他会员保持未读，重复调用幂等。"""
    headers, other_headers, own_ids, _ = mixed_messages
    initial_counts = {kind: len(ids) for kind, ids in own_ids.items()}
    remaining_counts = {
        kind: count for kind, count in initial_counts.items() if kind != message_type
    }
    for _ in range(2):
        response = client.post(
            f"{MESSAGES}/read-all", headers=headers, params={"type": message_type}
        )
        assert response.status_code == 200, response.text
        unread = client.get(f"{MESSAGES}/unread-count", headers=headers)
        assert unread.status_code == 200, unread.text
        assert unread.json() == {
            "unread_count": sum(remaining_counts.values()),
            "counts_by_type": remaining_counts,
        }

    items = _messages(client, headers)
    assert all(item["is_read"] == (item["type"] == message_type) for item in items)
    other_unread = client.get(f"{MESSAGES}/unread-count", headers=other_headers)
    assert other_unread.status_code == 200, other_unread.text
    assert other_unread.json() == {
        "unread_count": sum(initial_counts.values()),
        "counts_by_type": initial_counts,
    }
    assert all(not item["is_read"] for item in _messages(client, other_headers))


@pytest.mark.parametrize("message_type", ["unknown", "LIKE", "", "like,follow"])
def test_mark_all_read_invalid_type_returns_422_without_changes(
    client, mixed_messages, message_type
):
    headers, _, own_ids, _ = mixed_messages
    response = client.post(
        f"{MESSAGES}/read-all", headers=headers, params={"type": message_type}
    )
    assert response.status_code == 422, response.text
    unread = client.get(f"{MESSAGES}/unread-count", headers=headers)
    assert unread.status_code == 200, unread.text
    expected_counts = {kind: len(ids) for kind, ids in own_ids.items()}
    assert unread.json() == {
        "unread_count": sum(expected_counts.values()),
        "counts_by_type": expected_counts,
    }


def test_mark_all_read_without_type_clears_all_types_only_for_current_member(
    client, mixed_messages
):
    """省略 type 兼容旧客户端：全部清空，并且仍不能修改其他会员。"""
    headers, other_headers, own_ids, _ = mixed_messages
    for _ in range(2):
        response = client.post(f"{MESSAGES}/read-all", headers=headers)
        assert response.status_code == 200, response.text
        unread = client.get(f"{MESSAGES}/unread-count", headers=headers)
        assert unread.status_code == 200, unread.text
        assert unread.json() == {"unread_count": 0, "counts_by_type": {}}
    assert all(item["is_read"] for item in _messages(client, headers))
    other_unread = client.get(f"{MESSAGES}/unread-count", headers=other_headers)
    assert other_unread.status_code == 200, other_unread.text
    expected_counts = {kind: len(ids) for kind, ids in own_ids.items()}
    assert other_unread.json() == {
        "unread_count": sum(expected_counts.values()),
        "counts_by_type": expected_counts,
    }

def test_messages_filter_multiple_types(client, auth_headers):
    """合并分类：一次传多个 type（赞和评论 / 系统消息）。"""
    author_id, author, _ = _register_member(client)
    fan_id, fan, _ = _register_member(client)

    post = _approved_post(client, auth_headers, author)
    client.post(f"{POSTS}/{post['id']}/like", headers=fan)
    comment = client.post(
        f"{POSTS}/{post['id']}/comments", headers=fan, json={"content": "多类型"}
    ).json()
    client.patch(
        f"{COMMENTS}/{comment['id']}/status",
        headers=auth_headers,
        json={"status": "approved"},
    )
    client.post(f"{MEMBERS}/{author_id}/follow", headers=fan)

    # 赞和评论：一次要两类
    both = client.get(
        MESSAGES, headers=author, params=[("type", "like"), ("type", "comment")]
    )
    assert both.status_code == 200, both.text
    types = {item["type"] for item in both.json()["items"]}
    assert types == {"like", "comment"}

    # 系统消息：审核类（帖子审核 + 评论审核）
    system = client.get(
        MESSAGES,
        headers=author,
        params=[("type", "post_audit"), ("type", "comment_audit")],
    )
    assert system.status_code == 200, system.text
    assert all(
        item["type"] in {"post_audit", "comment_audit"}
        for item in system.json()["items"]
    )

    # 一次传多个 type 的「全部已读」
    marked = client.post(
        f"{MESSAGES}/read-all",
        headers=author,
        params=[("type", "like"), ("type", "comment")],
    )
    assert marked.status_code == 200, marked.text
    left = client.get(
        MESSAGES, headers=author, params=[("type", "like"), ("type", "comment")]
    ).json()["items"]
    assert all(item["is_read"] for item in left)
