"""pytest 公共夹具：使用内存 SQLite，保证测试不污染开发数据。"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在导入 app 之前设置环境变量（settings 带 lru_cache）
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["FIRST_SUPERUSER_USERNAME"] = "admin"
os.environ["FIRST_SUPERUSER_PASSWORD"] = "admin123"
# 用户中心：不发真实邮件、回显验证码、取消发送冷却、上传到临时目录
os.environ["MAIL_ENABLED"] = "false"
os.environ["EMAIL_CODE_DEBUG_RETURN"] = "true"
os.environ["EMAIL_CODE_RESEND_SECONDS"] = "0"
os.environ["UPLOAD_DIR"] = str(Path(tempfile.gettempdir()) / "fastapi_admin_test_uploads")

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture(scope="session")
def testing_session_local():
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def setup_database(testing_session_local):
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    db.add(
        User(
            username="admin",
            email="admin@example.com",
            nickname="超级管理员",
            role="admin",
            is_active=True,
            hashed_password=hash_password("admin123"),
        )
    )
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(testing_session_local):
    app = create_app()

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_token(client) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def auth_headers(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}
