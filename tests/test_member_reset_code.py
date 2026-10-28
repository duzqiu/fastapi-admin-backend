"""Public reset-code verification: isolated HTTP, schema, and service tests."""

from unittest.mock import Mock, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_member_auth_service
from app.api.v1.endpoints.member_auth import router
from app.core.exceptions import BusinessError, register_exception_handlers
from app.models.email_code import EmailScene
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberResetPassword, MemberVerifyResetCode
from app.services.email_code_service import EmailCodeService
from app.services.member_auth_service import MemberAuthService


@pytest.fixture()
def reset_code_service():
    service = MemberAuthService(Mock(spec=Session))
    service.members = Mock(spec=MemberRepository)
    service.codes = Mock(spec=EmailCodeService)
    service._issue_tokens = Mock()
    return service


@pytest.fixture()
def reset_code_client(reset_code_service):
    # No production app lifespan, DB dependency, SMTP, or authentication dependency.
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_member_auth_service] = lambda: reset_code_service
    with TestClient(app) as client:
        yield client


def test_verify_reset_code_service_normalizes_without_mutations(reset_code_service):
    service = reset_code_service
    service.members.email_taken.return_value = True

    assert service.verify_reset_code(" \tMember.Reset@EXAMPLE.COM\n", "123456") is None

    assert service.members.mock_calls == [call.email_taken("member.reset@example.com")]
    assert service.codes.mock_calls == [
        call.verify("member.reset@example.com", EmailScene.RESET_PASSWORD.value, "123456", consume=False)
    ]
    assert service.db.mock_calls == []
    service._issue_tokens.assert_not_called()


def test_verify_reset_code_service_rejects_unregistered_email(reset_code_service):
    service = reset_code_service
    service.members.email_taken.return_value = False

    with pytest.raises(BusinessError, match="该邮箱尚未注册"):
        service.verify_reset_code(" Member.Reset@EXAMPLE.COM ", "123456")

    assert service.members.mock_calls == [call.email_taken("member.reset@example.com")]
    assert service.codes.mock_calls == []
    assert service.db.mock_calls == []
    service._issue_tokens.assert_not_called()


def test_verify_reset_code_service_propagates_verification_error(reset_code_service):
    service = reset_code_service
    error = BusinessError("验证码不正确，还可尝试 4 次")
    service.codes.verify.side_effect = error

    with pytest.raises(BusinessError) as exc:
        service.verify_reset_code("member.reset@example.com", "000000")

    assert exc.value is error
    service.codes.verify.assert_called_once_with(
        "member.reset@example.com", "reset_password", "000000", consume=False
    )
    assert service.db.mock_calls == []
    service._issue_tokens.assert_not_called()


def test_verify_reset_code_public_endpoint_returns_only_message(reset_code_client, reset_code_service):
    response = reset_code_client.post(
        "/api/v1/member/auth/verify-reset-code",
        json={"email": " Member.Reset@EXAMPLE.COM ", "code": "123456"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"message": "验证码验证成功", "detail": None}
    reset_code_service.members.email_taken.assert_called_once_with("member.reset@example.com")
    reset_code_service.codes.verify.assert_called_once_with(
        "member.reset@example.com", "reset_password", "123456", consume=False
    )
    assert reset_code_service.db.mock_calls == []
    reset_code_service._issue_tokens.assert_not_called()


@pytest.mark.parametrize(
    "registered,error",
    [(False, "该邮箱尚未注册"), (True, "验证码不存在或已过期，请重新获取")],
)
def test_verify_reset_code_endpoint_business_errors(
    reset_code_client, reset_code_service, registered, error
):
    reset_code_service.members.email_taken.return_value = registered
    if registered:
        reset_code_service.codes.verify.side_effect = BusinessError(error)

    response = reset_code_client.post(
        "/api/v1/member/auth/verify-reset-code",
        json={"email": "member.reset@example.com", "code": "123456"},
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"code": 40000, "message": error, "data": None}
    if not registered:
        reset_code_service.codes.verify.assert_not_called()
    assert reset_code_service.db.mock_calls == []
    reset_code_service._issue_tokens.assert_not_called()


INVALID_PAYLOADS = [
    {},
    {"email": "member.reset@example.com"},
    {"code": "123456"},
    {"email": "not-an-email", "code": "123456"},
    {"email": None, "code": "123456"},
    {"email": " ", "code": "123456"},
    {"email": 123, "code": "123456"},
    {"email": "member.reset@example.com", "code": "123"},
    {"email": "member.reset@example.com", "code": "12345678901"},
    {"email": "member.reset@example.com", "code": None},
    {"email": "member.reset@example.com", "code": 123456},
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_verify_reset_code_schema_rejects_invalid_payload(payload):
    with pytest.raises(ValidationError):
        MemberVerifyResetCode.model_validate(payload)


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_verify_reset_code_endpoint_rejects_before_queries(
    reset_code_client, reset_code_service, payload
):
    response = reset_code_client.post("/api/v1/member/auth/verify-reset-code", json=payload)

    assert response.status_code == 422, response.text
    assert reset_code_service.members.mock_calls == []
    assert reset_code_service.codes.mock_calls == []
    assert reset_code_service.db.mock_calls == []
    reset_code_service._issue_tokens.assert_not_called()


@pytest.mark.parametrize("code", ["1234", "1234567890"])
def test_verify_reset_code_schema_accepts_code_length_boundaries(code):
    payload = MemberVerifyResetCode(email=" Member.Reset@EXAMPLE.COM ", code=code)
    assert str(payload.email) == "Member.Reset@example.com"
    assert payload.code == code
    assert set(payload.model_dump()) == {"email", "code"}


def test_reset_endpoints_openapi_contracts_unchanged(reset_code_client):
    spec = reset_code_client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    new_operation = spec["paths"]["/api/v1/member/auth/verify-reset-code"]["post"]
    assert not new_operation.get("security")
    assert new_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MessageResponse"
    }
    assert schemas["MemberVerifyResetCode"]["required"] == ["email", "code"]
    assert schemas["MemberVerifyResetCode"]["properties"]["email"]["format"] == "email"
    assert schemas["MemberVerifyResetCode"]["properties"]["code"]["minLength"] == 4
    assert schemas["MemberVerifyResetCode"]["properties"]["code"]["maxLength"] == 10
    assert schemas["MemberResetPassword"]["required"] == [
        "email", "code", "new_password", "confirm_password"
    ]
    reset_operation = spec["paths"]["/api/v1/member/auth/reset-password"]["post"]
    assert reset_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MemberResetPassword"
    }
    assert reset_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MessageResponse"
    }


def test_existing_reset_endpoint_keeps_message_and_payload(reset_code_client, reset_code_service):
    reset_code_service.reset_password = Mock()
    payload = {
        "email": "member.reset@example.com", "code": "123456",
        "new_password": "Newpass123", "confirm_password": "Newpass123",
    }

    response = reset_code_client.post("/api/v1/member/auth/reset-password", json=payload)

    assert response.status_code == 200, response.text
    assert response.json() == {"message": "密码重置成功，请使用新密码登录", "detail": None}
    reset_code_service.reset_password.assert_called_once_with(MemberResetPassword(**payload))
