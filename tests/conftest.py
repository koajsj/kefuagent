"""Isolated per-test identities; real authentication, PostgreSQL and no external models."""

import base64
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def private_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_EXTERNAL_MODELS", "false")
    monkeypatch.setenv("CREDENTIAL_MASTER_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DOCUMENT_STORAGE_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("PUBLIC_RATE_KEY", "synthetic-public-test-rate-secret-" + uuid4().hex)
    monkeypatch.setenv("MODEL_ALLOWED_HOSTS", '["api.example.com"]')


@pytest.fixture(scope="session")
def login_secret():
    from support_agent.security import hash_password

    password = "Acceptance-only-" + uuid4().hex
    return password, hash_password(password)


@pytest.fixture
def platform(login_secret):
    from support_agent.config import Settings
    from support_agent.main import create_app
    from support_agent.models import User
    from support_agent.schemas import UserOut

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL must point to a separately migrated PostgreSQL test database"
        )
    settings = Settings(database_url=url)
    if "test" not in settings.database_url.get_secret_value().rsplit("/", 1)[-1]:
        pytest.fail("Refusing a database whose name does not contain test")
    app = create_app(settings)
    suffix = uuid4().hex
    # Immutable setup values only; users, tenants and mutable state stay isolated per check.
    # The CRUD check owns API user creation. Every fixture still authenticates normally.
    password, encoded = login_secret
    with app.state.sessions.begin() as db:
        root = User(
            login=f"root-{suffix}",
            display_name="Acceptance root",
            password_hash=encoded,
            is_platform_admin=True,
        )
        db.add(root)
        db.flush()
        root_login = root.login
        users = []
        for label in ["a", "b", "member", "second"]:
            user = User(login=f"{label}-{suffix}", display_name=label, password_hash=encoded)
            db.add(user)
            db.flush()
            users.append(UserOut.model_validate(user).model_dump(mode="json"))
    with TestClient(app, raise_server_exceptions=False) as client:
        token = client.post("/api/v1/auth/login", json={"login": root_login, "password": password})
        assert token.status_code == 200, token.text
        root_headers = {"Authorization": "Bearer " + token.json()["access_token"]}
        tenants, headers = [], []
        for label, user in zip(["a", "b"], users[:2], strict=True):
            resp = client.post(
                "/api/v1/tenants",
                headers=root_headers,
                json={"name": label, "slug": f"{label}-{suffix}", "admin_user_id": user["id"]},
            )
            assert resp.status_code == 201, resp.text
            tenant = resp.json()
            tenants.append(tenant)
            login = client.post(
                "/api/v1/auth/login", json={"login": user["login"], "password": password}
            )
            assert login.status_code == 200, login.text
            headers.append(
                {
                    "Authorization": "Bearer " + login.json()["access_token"],
                    "X-Tenant-ID": tenant["id"],
                }
            )
        yield client, app, root_headers, tenants, headers, users, password
    app.state.engine.dispose()
