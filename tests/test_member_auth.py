"""会员登录前邮箱检查：只读服务、公开接口与请求校验（不启动服务）。"""

from unittest.mock import Mock, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_member_auth_service
from app.api.v1.endpoints.member_auth import router
from app.repositories.member_repository import MemberRepository
from app.services.email_code_service import EmailCodeService
from app.services.member_auth_service import MemberAuthService


@pytest.fixture()
def email_check_service():
    """所有持久化与验证码操作均使用 mock，禁止触及真实数据库/邮件。"""
    db = Mock(spec=Session)
    service = MemberAuthService(db)
    service.members = Mock(spec=MemberRepository)
    service.codes = Mock(spec=EmailCodeService)
    return service


@pytest.fixture()
def email_check_client(email_check_service):
    # 只挂认证路由，不使用生产应用的初始化数据库生命周期。
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_member_auth_service] = lambda: email_check_service
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("exists", [True, False])
def test_check_email_service_normalizes_and_is_read_only(email_check_service, exists):
    service = email_check_service
    service.members.email_taken.return_value = exists

    assert service.check_email(" \tMember.Check@EXAMPLE.COM\n") is exists

    assert service.members.mock_calls == [call.email_taken("member.check@example.com")]
    assert service.db.mock_calls == []
    assert service.codes.mock_calls == []


@pytest.mark.parametrize("exists", [True, False])
def test_check_email_public_endpoint_returns_only_exists(
    email_check_client, email_check_service, exists
):
    service = email_check_service
    service.members.email_taken.return_value = exists

    response = email_check_client.post(
        "/api/v1/member/auth/check-email", json={"email": "  Member.Check@EXAMPLE.COM  "}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"exists": exists}
    assert service.members.mock_calls == [call.email_taken("member.check@example.com")]
    assert service.db.mock_calls == []
    assert service.codes.mock_calls == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"email": "not-an-email"}, {"email": ""}, {"email": "  "}, {"email": None}, {"email": 123}],
)
def test_check_email_rejects_invalid_payload_without_queries(
    email_check_client, email_check_service, payload
):
    response = email_check_client.post("/api/v1/member/auth/check-email", json=payload)

    assert response.status_code == 422, response.text
    assert email_check_service.members.mock_calls == []
    assert email_check_service.db.mock_calls == []
    assert email_check_service.codes.mock_calls == []
