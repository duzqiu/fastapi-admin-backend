"""Real email-code verification against a per-test SQLite memory database; no SMTP."""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.security import hash_password, verify_password
from app.core.utils import utcnow
from app.models.email_code import EmailCode, EmailScene
from app.models.member import Member
from app.schemas.member import MemberResetPassword
from app.services.email_code_service import EmailCodeService
from app.services.member_auth_service import MemberAuthService


EMAIL = "member.reset@example.com"
SCENE = EmailScene.RESET_PASSWORD.value
CODE = "123456"


@pytest.fixture()
def code_db(monkeypatch):
    # Never use the configured application engine or a file-backed database.
    engine = create_engine("sqlite:///:memory:")
    EmailCode.__table__.create(engine)
    Member.__table__.create(engine)
    monkeypatch.setattr(settings, "EMAIL_CODE_MAX_ATTEMPTS", 3)
    # Verification must never send mail, even if an implementation regresses.
    monkeypatch.setattr(
        "app.services.email_code_service.send_email_code",
        Mock(side_effect=AssertionError("Verification must not send SMTP")),
    )
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def create_code(db, **overrides):
    values = {
        "email": EMAIL, "scene": SCENE, "code": CODE,
        "expires_at": utcnow() + timedelta(minutes=10), "attempts": 0,
    }
    values.update(overrides)
    record = EmailCode(**values)
    db.add(record)
    db.commit()
    return record


def test_success_nonconsume_is_read_only_then_default_consumes(code_db):
    record = create_code(code_db)
    service = EmailCodeService(code_db)

    with (
        patch.object(code_db, "add", wraps=code_db.add) as add,
        patch.object(code_db, "flush", wraps=code_db.flush) as flush,
        patch.object(code_db, "commit", wraps=code_db.commit) as commit,
    ):
        assert service.verify(EMAIL.upper(), SCENE, " 123456 ", consume=False) is record
        assert service.verify(EMAIL, SCENE, CODE, consume=False) is record
        assert record.used_at is None
        assert record.attempts == 0
        assert not code_db.dirty
        assert not code_db.new
        add.assert_not_called()
        flush.assert_not_called()
        commit.assert_not_called()

    # A later page/request still sees an unused code after the read-only session ends.
    code_db.rollback()
    code_db.expire_all()
    assert code_db.get(EmailCode, record.id).used_at is None

    with (
        patch.object(code_db, "add", wraps=code_db.add) as add,
        patch.object(code_db, "flush", wraps=code_db.flush) as flush,
        patch.object(code_db, "commit", wraps=code_db.commit) as commit,
    ):
        assert service.verify(EMAIL, SCENE, CODE) is record
        assert record.used_at is not None
        add.assert_called_once_with(record)
        flush.assert_called_once_with()
        commit.assert_not_called()  # Success transactions remain caller-owned.

    code_db.commit()
    with Session(code_db.bind) as observer:
        assert observer.get(EmailCode, record.id).used_at is not None
    for consume in (False, True):
        with pytest.raises(BusinessError, match="验证码不存在或已过期"):
            service.verify(EMAIL, SCENE, CODE, consume=consume)


def test_explicit_consume_true_preserves_original_behavior(code_db):
    record = create_code(code_db)
    assert EmailCodeService(code_db).verify(EMAIL, SCENE, CODE, consume=True) is record
    assert record.used_at is not None
    code_db.commit()
    code_db.expire_all()
    assert code_db.get(EmailCode, record.id).used_at is not None


def test_consume_argument_is_keyword_only(code_db):
    create_code(code_db)
    with pytest.raises(TypeError):
        EmailCodeService(code_db).verify(EMAIL, SCENE, CODE, False)


@pytest.mark.parametrize("consume", [False, True])
def test_wrong_code_attempts_persist_and_valid_code_respects_consume(code_db, consume):
    record = create_code(code_db)
    service = EmailCodeService(code_db)

    with pytest.raises(BusinessError, match="验证码不正确，还可尝试 2 次"):
        service.verify(EMAIL, SCENE, "000000", consume=consume)

    code_db.rollback()  # Failure attempts must already have been committed.
    code_db.expire_all()
    assert record.attempts == 1
    assert record.used_at is None
    with Session(code_db.bind) as observer:
        assert observer.get(EmailCode, record.id).attempts == 1

    service.verify(EMAIL, SCENE, CODE, consume=consume)
    assert record.attempts == 1
    assert (record.used_at is not None) is consume


@pytest.mark.parametrize("consume", [False, True])
def test_attempt_limit_invalidates_and_persists_even_for_correct_code(code_db, consume):
    record = create_code(code_db)
    service = EmailCodeService(code_db)

    for remaining in (2, 1, 0):
        with pytest.raises(BusinessError, match=f"验证码不正确，还可尝试 {remaining} 次"):
            service.verify(EMAIL, SCENE, "000000", consume=consume)

    assert record.attempts == 3
    # Preserve the existing contract: invalidation occurs on the next verification.
    assert record.used_at is None
    with pytest.raises(BusinessError, match="验证码错误次数过多，请重新获取"):
        service.verify(EMAIL, SCENE, CODE, consume=consume)

    code_db.rollback()
    code_db.expire_all()
    assert record.attempts == 3
    assert record.used_at is not None
    with Session(code_db.bind) as observer:
        saved = observer.get(EmailCode, record.id)
        assert saved.used_at is not None
        assert saved.attempts == 3
    with pytest.raises(BusinessError, match="验证码不存在或已过期"):
        service.verify(EMAIL, SCENE, CODE, consume=consume)


@pytest.mark.parametrize("consume", [False, True])
@pytest.mark.parametrize("supplied_code", [CODE, "000000"])
def test_expiry_rejected_before_attempts_or_mutations(code_db, consume, supplied_code):
    now = datetime(2026, 1, 1, 12, 0, 0)
    record = create_code(code_db, expires_at=now - timedelta(seconds=1), attempts=1)
    with (
        patch("app.models.email_code.utcnow", return_value=now),
        patch.object(code_db, "add", wraps=code_db.add) as add,
        patch.object(code_db, "flush", wraps=code_db.flush) as flush,
        patch.object(code_db, "commit", wraps=code_db.commit) as commit,
    ):
        with pytest.raises(BusinessError, match="验证码不存在或已过期"):
            EmailCodeService(code_db).verify(EMAIL, SCENE, supplied_code, consume=consume)
        add.assert_not_called()
        flush.assert_not_called()
        commit.assert_not_called()
    code_db.rollback()
    code_db.expire_all()
    assert record.used_at is None
    assert record.attempts == 1


@pytest.mark.parametrize("consume", [False, True])
@pytest.mark.parametrize("mismatch", ["email", "scene", "used", "missing"])
def test_unavailable_code_cannot_be_verified(code_db, consume, mismatch):
    if mismatch != "missing":
        overrides = {
            "email": {"email": "other@example.com"},
            "scene": {"scene": EmailScene.REGISTER.value},
            "used": {"used_at": utcnow()},
        }[mismatch]
        create_code(code_db, **overrides)
    with pytest.raises(BusinessError, match="验证码不存在或已过期"):
        EmailCodeService(code_db).verify(EMAIL, SCENE, CODE, consume=consume)


def test_member_verify_then_reset_in_separate_sessions_consumes_and_changes_password(code_db):
    record = create_code(code_db)
    member = Member(
        member_no="1234567890", email=EMAIL, hashed_password=hash_password("Oldpass123")
    )
    code_db.add(member)
    code_db.commit()
    service = MemberAuthService(code_db)
    service._issue_tokens = Mock(side_effect=AssertionError("Reset must not issue tokens"))
    original_hash = member.hashed_password

    assert service.verify_reset_code(" Member.Reset@EXAMPLE.COM ", CODE) is None
    assert record.used_at is None
    assert member.hashed_password == original_hash
    assert not code_db.dirty
    code_db.rollback()

    # Final reset still needs email + code + matching new/confirmation passwords.
    payload = MemberResetPassword(
        email=EMAIL, code=CODE, new_password="Newpass123", confirm_password="Newpass123"
    )
    with Session(code_db.bind, autoflush=False) as next_request:
        reset_service = MemberAuthService(next_request)
        reset_service._issue_tokens = Mock(side_effect=AssertionError("Reset must not issue tokens"))
        assert reset_service.reset_password(payload) is None
        reset_service._issue_tokens.assert_not_called()

    code_db.expire_all()
    assert record.used_at is not None
    assert member.hashed_password != original_hash
    assert verify_password("Newpass123", member.hashed_password)
    assert not verify_password("Oldpass123", member.hashed_password)
    with pytest.raises(BusinessError, match="验证码不存在或已过期"):
        service.verify_reset_code(EMAIL, CODE)
    service._issue_tokens.assert_not_called()
