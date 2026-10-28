"""Public registration-code verification: isolated HTTP, schema, and service tests."""

from datetime import timedelta
from unittest.mock import Mock, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.deps import get_member_auth_service
from app.api.v1.endpoints.member_auth import router
from app.core.exceptions import BusinessError, ConflictError, register_exception_handlers
from app.core.utils import utcnow
from app.models.email_code import EmailCode, EmailScene
from app.models.member import Member
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberRegister, MemberVerifyRegisterCode
from app.services.email_code_service import EmailCodeService
from app.services.member_auth_service import MemberAuthService


@pytest.fixture()
def register_code_service():
    """Use mocks for all persistence and code operations; no DB or SMTP."""
    service = MemberAuthService(Mock(spec=Session))
    service.members = Mock(spec=MemberRepository)
    service.codes = Mock(spec=EmailCodeService)
    service._issue_tokens = Mock()
    return service


@pytest.fixture()
def register_code_client(register_code_service):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_member_auth_service] = lambda: register_code_service
    with TestClient(app) as client:
        yield client


def test_verify_register_code_service_normalizes_without_consuming(register_code_service):
    service = register_code_service
    service.members.email_taken.return_value = False

    assert service.verify_register_code(" \tMember.Register@EXAMPLE.COM\n", "123456") is None

    assert service.members.mock_calls == [call.email_taken("member.register@example.com")]
    assert service.codes.mock_calls == [
        call.verify("member.register@example.com", EmailScene.REGISTER.value, "123456", consume=False)
    ]
    assert service.db.mock_calls == []
    service._issue_tokens.assert_not_called()


def test_verify_register_code_service_rejects_registered_email(register_code_service):
    service = register_code_service
    service.members.email_taken.return_value = True

    with pytest.raises(ConflictError, match="该邮箱已注册"):
        service.verify_register_code(" Member.Register@EXAMPLE.COM ", "123456")

    assert service.members.mock_calls == [call.email_taken("member.register@example.com")]
    assert service.codes.mock_calls == []
    assert service.db.mock_calls == []


def test_verify_register_code_service_propagates_verification_error(register_code_service):
    service = register_code_service
    service.members.email_taken.return_value = False
    error = BusinessError("验证码不正确，还可尝试 4 次")
    service.codes.verify.side_effect = error

    with pytest.raises(BusinessError) as exc:
        service.verify_register_code("member.register@example.com", "000000")

    assert exc.value is error
    service.codes.verify.assert_called_once_with(
        "member.register@example.com", "register", "000000", consume=False
    )
    assert service.db.mock_calls == []


def test_verify_register_code_public_endpoint_returns_only_message(
    register_code_client, register_code_service
):
    register_code_service.members.email_taken.return_value = False

    response = register_code_client.post(
        "/api/v1/member/auth/verify-register-code",
        json={"email": " Member.Register@EXAMPLE.COM ", "code": "123456"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"message": "验证码验证成功", "detail": None}
    register_code_service.members.email_taken.assert_called_once_with("member.register@example.com")
    register_code_service.codes.verify.assert_called_once_with(
        "member.register@example.com", "register", "123456", consume=False
    )
    assert register_code_service.db.mock_calls == []
    register_code_service._issue_tokens.assert_not_called()


def test_verify_register_code_endpoint_rejects_registered_email(
    register_code_client, register_code_service
):
    register_code_service.members.email_taken.return_value = True

    response = register_code_client.post(
        "/api/v1/member/auth/verify-register-code",
        json={"email": "member.register@example.com", "code": "123456"},
    )

    assert response.status_code == 409, response.text
    assert response.json() == {
        "code": 40900,
        "message": "该邮箱已注册，请直接登录或使用「忘记密码」找回",
        "data": None,
    }
    register_code_service.codes.verify.assert_not_called()
    assert register_code_service.db.mock_calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "member.register@example.com"},
        {"code": "123456"},
        {"email": "not-an-email", "code": "123456"},
        {"email": None, "code": "123456"},
        {"email": " ", "code": "123456"},
        {"email": 123, "code": "123456"},
        {"email": "member.register@example.com", "code": "123"},
        {"email": "member.register@example.com", "code": "12345678901"},
        {"email": "member.register@example.com", "code": None},
        {"email": "member.register@example.com", "code": 123456},
    ],
)
def test_verify_register_code_schema_rejects_invalid_payload(payload):
    with pytest.raises(ValidationError):
        MemberVerifyRegisterCode.model_validate(payload)


def test_verify_register_code_openapi_contract(register_code_client):
    spec = register_code_client.get("/openapi.json").json()
    operation = spec["paths"]["/api/v1/member/auth/verify-register-code"]["post"]
    schema = spec["components"]["schemas"]["MemberVerifyRegisterCode"]

    assert not operation.get("security")
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MemberVerifyRegisterCode"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MessageResponse"
    }
    assert schema["required"] == ["email", "code"]
    assert schema["properties"]["email"]["format"] == "email"
    assert schema["properties"]["code"]["minLength"] == 4
    assert schema["properties"]["code"]["maxLength"] == 10


def test_preverify_then_register_consumes_code_and_rejects_replay_or_wrong_scene():
    """The public check is read-only; final register remains the consuming boundary."""
    engine = create_engine("sqlite:///:memory:")
    EmailCode.__table__.create(engine)
    Member.__table__.create(engine)
    register_email = "member.register@example.com"
    reset_email = "member.reset-scene@example.com"
    register_code = EmailCode(
        email=register_email,
        code="123456",
        scene=EmailScene.REGISTER.value,
        expires_at=utcnow() + timedelta(minutes=10),
    )
    reset_scene_code = EmailCode(
        email=reset_email,
        code="654321",
        scene=EmailScene.RESET_PASSWORD.value,
        expires_at=utcnow() + timedelta(minutes=10),
    )

    try:
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            db.add_all([register_code, reset_scene_code])
            db.commit()
            service = MemberAuthService(db)

            service.verify_register_code(register_email, "123456")
            assert register_code.used_at is None

            member = service.register(
                MemberRegister(
                    email=register_email,
                    code="123456",
                    password="Register123",
                    confirm_password="Register123",
                )
            )
            assert member.email == register_email
            assert register_code.used_at is not None
            db.commit()

            with pytest.raises(ConflictError, match="该邮箱已注册"):
                service.verify_register_code(register_email, "123456")
            with pytest.raises(ConflictError, match="该邮箱已注册"):
                service.register(
                    MemberRegister(
                        email=register_email,
                        code="123456",
                        password="Register123",
                        confirm_password="Register123",
                    )
                )

            with pytest.raises(BusinessError, match="验证码不存在或已过期"):
                service.register(
                    MemberRegister(
                        email=reset_email,
                        code="654321",
                        password="ResetScene123",
                        confirm_password="ResetScene123",
                    )
                )
            assert reset_scene_code.used_at is None
    finally:
        engine.dispose()
