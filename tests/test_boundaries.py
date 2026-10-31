"""Real PostgreSQL acceptance. No SQLite, mock database, truncation or schema reset."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError


def test_passwords_use_argon2id():
    from support_agent.security import hash_password, verify_password

    password = "Acceptance-only-" + uuid4().hex
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$")
    assert password not in encoded
    assert verify_password(encoded, password)
    assert not verify_password(encoded, "wrong password")


@pytest.fixture
def platform():
    from support_agent.config import Settings
    from support_agent.main import create_app
    from support_agent.models import User
    from support_agent.schemas import UserOut
    from support_agent.security import hash_password

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
    password = "Acceptance-only-" + uuid4().hex
    encoded = hash_password(password)
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
    with TestClient(app, raise_server_exceptions=False) as client:
        token = client.post("/api/v1/auth/login", json={"login": root_login, "password": password})
        assert token.status_code == 200, token.text
        root_headers = {"Authorization": "Bearer " + token.json()["access_token"]}
        users = []
        for label in ["a", "b", "member", "second"]:
            if label == "a":
                # Keep a real API creation and password hash in every fixture.
                resp = client.post(
                    "/api/v1/users",
                    headers=root_headers,
                    json={
                        "login": f"{label}-{suffix}",
                        "display_name": label,
                        "password": password,
                    },
                )
                assert resp.status_code == 201, resp.text
                users.append(resp.json())
            else:
                # The other identities are setup data, not repeated user-creation checks.
                # Reuse this fixture's real hash; authentication still verifies Argon2 normally.
                with app.state.sessions.begin() as db:
                    user = User(
                        login=f"{label}-{suffix}", display_name=label, password_hash=encoded
                    )
                    db.add(user)
                    db.flush()
                    users.append(UserOut.model_validate(user).model_dump(mode="json"))
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


def test_crud_isolation_and_membership_revocation(platform):
    c, app, root, ts, hs, users, password = platform
    a, b = hs
    prefix = "/api/v1"
    assert c.get(prefix + "/conversations").status_code == 401
    assert (
        c.get(prefix + "/conversations", headers=root | {"X-Tenant-ID": ts[0]["id"]}).status_code
        == 403
    )
    assert (
        c.get(prefix + "/conversations", headers=a | {"X-Tenant-ID": ts[1]["id"]}).status_code
        == 403
    )
    assert (
        c.get(prefix + "/conversations", headers={"Authorization": a["Authorization"]}).status_code
        == 422
    )
    assert len(c.get(prefix + "/tenants", headers=a).json()) == 1
    objects = []
    for h in hs:
        cfg = c.post(
            prefix + "/agent-configs",
            headers=h,
            json={
                "name": "General support",
                "provider": "example",
                "model": "example-model",
                "runtime": {"temperature": 0.2, "max_output_tokens": 1024},
                "behavior": {"instructions": "Be accurate and concise."},
                "credential_ref": "cred_primary",
            },
        )
        assert cfg.status_code == 201, cfg.text
        conv = c.post(prefix + "/conversations", headers=h, json={"channel": "api"})
        assert conv.status_code == 201, conv.text
        cid = conv.json()["id"]
        for role in ["user", "assistant", "tool"]:
            msg = c.post(
                prefix + f"/conversations/{cid}/messages",
                headers=h,
                json={"role": role, "content": f"{role} history", "metadata": {"source": "manual"}},
            )
            assert msg.status_code == 201, msg.text
        history = c.get(prefix + f"/conversations/{cid}/messages", headers=h)
        assert [m["role"] for m in history.json()] == ["user", "assistant", "tool"]
        assert all(m["tenant_id"] == h["X-Tenant-ID"] for m in history.json())
        objects.append((cfg.json()["id"], cid))
    bcfg, bcid = objects[1]
    for path in [
        f"/agent-configs/{bcfg}",
        f"/conversations/{bcid}",
        f"/conversations/{bcid}/messages",
    ]:
        assert c.get(prefix + path, headers=a).status_code == 404
    assert (
        c.put(
            prefix + f"/agent-configs/{bcfg}",
            headers=a,
            json={
                "name": "attack",
                "provider": "example",
                "model": "example",
                "expected_version": 1,
            },
        ).status_code
        == 404
    )
    assert (
        c.post(
            prefix + f"/conversations/{bcid}/messages",
            headers=a,
            json={"role": "user", "content": "attack"},
        ).status_code
        == 404
    )
    assert (
        c.post(
            prefix + "/conversations", headers=a, json={"channel": "api", "tenant_id": ts[1]["id"]}
        ).status_code
        == 422
    )
    assert (
        c.get(prefix + "/conversations?tenant_id=" + ts[1]["id"], headers=a).json()[0]["id"]
        == objects[0][1]
    )
    mid = users[2]["id"]
    for h in hs:
        resp = c.post(prefix + "/memberships", headers=h, json={"user_id": mid, "role": "member"})
        assert resp.status_code == 201, resp.text
    login = c.post(prefix + "/auth/login", json={"login": users[2]["login"], "password": password})
    member = {"Authorization": "Bearer " + login.json()["access_token"], "X-Tenant-ID": ts[0]["id"]}
    assert len(c.get(prefix + "/tenants", headers=member).json()) == 2
    assert c.get(prefix + "/conversations", headers=member).status_code == 200
    assert (
        c.post(
            prefix + "/agent-configs",
            headers=member,
            json={"name": "forbidden", "provider": "x", "model": "y"},
        ).status_code
        == 403
    )
    assert c.get(prefix + "/audit-events", headers=member).status_code == 403
    own = next(
        m
        for m in c.get(prefix + "/memberships", headers=a).json()
        if m["user_id"] == users[0]["id"]
    )
    assert (
        c.patch(
            prefix + "/memberships/" + own["id"], headers=a, json={"status": "inactive"}
        ).status_code
        == 409
    )
    membership = next(
        m for m in c.get(prefix + "/memberships", headers=a).json() if m["user_id"] == mid
    )
    assert (
        c.patch(
            prefix + "/memberships/" + membership["id"], headers=a, json={"status": "inactive"}
        ).status_code
        == 200
    )
    assert c.get(prefix + "/conversations", headers=member).status_code == 403
    assert (
        c.get(prefix + "/conversations", headers=member | {"X-Tenant-ID": ts[1]["id"]}).status_code
        == 200
    )
    assert (
        c.patch(
            prefix + "/tenants/" + ts[0]["id"], headers=root, json={"status": "inactive"}
        ).status_code
        == 200
    )
    assert c.get(prefix + "/conversations", headers=a).status_code == 403
    assert c.post(prefix + "/auth/logout", headers=member).status_code == 204
    assert c.get(prefix + "/auth/me", headers=member).status_code == 401
    # Verify persistence through an independent connection, not an ORM identity map.
    with app.state.sessions() as db:
        assert (
            db.scalar(text("SELECT count(*) FROM tenants WHERE id=:id"), {"id": ts[1]["id"]}) == 1
        )


def test_tool_contract_audit_and_safe_errors(platform, caplog):
    c, app, root, ts, hs, users, password = platform
    a, b = hs
    p = "/api/v1"
    definition = {
        "key": "generic_lookup",
        "name": "Generic lookup",
        "description": "Metadata only",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "risk_level": "low",
        "permissions": ["tools:invoke"],
        "enabled": True,
    }
    tool = c.post(p + "/tools", headers=b, json=definition)
    assert tool.status_code == 201, tool.text
    tid = tool.json()["id"]
    assert c.get(p + "/tools", headers=a).json() == []
    assert c.get(p + "/tools/" + tid, headers=a).status_code == 404
    assert c.patch(p + "/tools/" + tid, headers=a, json={"enabled": False}).status_code == 404
    assert (
        c.post(
            p + "/tools/" + tid + "/validate", headers=a, json={"arguments": {"query": "ok"}}
        ).status_code
        == 404
    )
    assert (
        c.post(
            p + "/tools/" + tid + "/execute", headers=a, json={"arguments": {"query": "ok"}}
        ).status_code
        == 404
    )
    bad = c.post(p + "/tools/" + tid + "/execute", headers=b, json={"arguments": {"query": 12}})
    assert bad.status_code == 422, bad.text
    assert (
        c.post(
            p + "/tools/" + tid + "/validate", headers=b, json={"arguments": {"query": "ok"}}
        ).json()["status"]
        == "validated"
    )
    result = c.post(
        p + "/tools/" + tid + "/execute", headers=b, json={"arguments": {"query": "ok"}}
    )
    assert result.status_code == 501, result.text
    assert result.json()["status"] == "rejected"
    assert result.json()["error_category"] == "execution_not_enabled"
    conv = c.post(p + "/conversations", headers=a, json={"channel": "api"}).json()["id"]
    assert (
        c.post(
            p + "/tools/" + tid + "/execute",
            headers=b,
            json={"arguments": {"query": "ok"}, "conversation_id": conv},
        ).status_code
        == 404
    )
    malicious = definition | {
        "key": "evil",
        "parameters": {"type": "object", "$ref": "https://example.invalid/schema"},
    }
    assert c.post(p + "/tools", headers=b, json=malicious).status_code == 422
    assert (
        c.post(p + "/tools", headers=b, json=definition | {"handler": "os.system"}).status_code
        == 422
    )
    assert c.post(p + "/tools", headers=b, json=definition).status_code == 409
    assert c.patch(p + "/tools/" + tid, headers=b, json={"enabled": False}).status_code == 200
    assert (
        c.post(
            p + "/tools/" + tid + "/validate", headers=b, json={"arguments": {"query": "ok"}}
        ).status_code
        == 409
    )
    secret = "secret-do-not-log-" + uuid4().hex
    failed = c.post(p + "/auth/login", json={"login": users[0]["login"], "password": secret})
    assert failed.status_code == 401
    validation = c.post(
        p + "/agent-configs",
        headers=b,
        json={"name": "x", "provider": "x", "model": "y", "api_key": secret},
    )
    assert validation.status_code == 422
    assert secret not in validation.text
    assert (
        c.post(
            p + "/agent-configs",
            headers=b,
            json={"name": "x", "provider": "x", "model": "y", "credential_ref": "sk-proj-real-key"},
        ).status_code
        == 422
    )
    events = c.get(p + "/audit-events", headers=b)
    assert events.status_code == 200
    assert all(e["tenant_id"] == ts[1]["id"] for e in events.json())
    assert any(
        e["action"] == "tool.execute" and e["reason"] == "execution_not_enabled"
        for e in events.json()
    )
    assert any(e["outcome"] == "failure" for e in events.json())
    assert any(
        e["resource_id"] == tid
        and e["request_id"] == bad.json()["request_id"]
        and e["outcome"] == "failure"
        for e in events.json()
    )
    assert result.headers["X-Request-ID"] == result.json()["request_id"]
    assert secret not in events.text
    assert secret not in caplog.text
    assert password not in caplog.text
    assert b["Authorization"] not in caplog.text
    # Safe database conflict payload; SQL and constraints are never exposed.
    duplicate = c.post(
        p + "/tenants",
        headers=root,
        json={"name": "duplicate", "slug": ts[0]["slug"], "admin_user_id": users[1]["id"]},
    )
    assert duplicate.status_code == 409
    assert "INSERT" not in duplicate.text and "password_hash" not in duplicate.text


def test_real_postgres_rls_and_optimistic_concurrency(platform):
    c, app, root, ts, hs, users, password = platform
    a, b = hs
    p = "/api/v1"
    configs = []
    for h in hs:
        configs.append(
            c.post(
                p + "/agent-configs",
                headers=h,
                json={"name": "Concurrent", "provider": "example", "model": "model"},
            ).json()
        )
    with app.state.sessions() as db:
        assert db.scalar(text("SELECT current_setting('app.tenant_id',true)")) in (None, "")
        assert db.execute(text("SELECT * FROM agent_configs")).all() == []
        db.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": ts[0]["id"]})
        assert {str(row[0]) for row in db.execute(text("SELECT tenant_id FROM agent_configs"))} == {
            ts[0]["id"]
        }
        with pytest.raises(ProgrammingError) as denied:
            db.execute(
                text(
                    "INSERT INTO conversations(id,tenant_id,channel,status,created_by) VALUES (:id,:t,'api','open',:u)"
                ),
                {"id": str(uuid4()), "t": ts[1]["id"], "u": users[0]["id"]},
            )
        assert denied.value.orig.sqlstate == "42501"
        db.rollback()
        assert db.execute(text("SELECT * FROM agent_configs")).all() == []
        tables = db.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('agent_configs','conversations','messages','tool_definitions')"
            )
        ).all()
        assert len(tables) == 4 and all(row[1] and row[2] for row in tables)
        role = db.execute(
            text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        assert role == (False, False)
    cfg = configs[0]

    def update(i):
        return c.put(
            p + "/agent-configs/" + cfg["id"],
            headers=a,
            json={
                "name": f"Version {i}",
                "provider": "example",
                "model": "model",
                "expected_version": 1,
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(update, [1, 2]))
    assert sorted(statuses) == [200, 409]
    assert c.get(p + "/agent-configs/" + cfg["id"], headers=a).json()["version"] == 2
    # Composite FK blocks a message pointing to a conversation in the other tenant.
    bconv = c.post(p + "/conversations", headers=b, json={"channel": "api"}).json()["id"]
    with app.state.sessions() as db:
        db.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": ts[0]["id"]})
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO messages(id,tenant_id,conversation_id,role,content,metadata,created_by) VALUES (:id,:t,:c,'user','x','{}',:u)"
                ),
                {"id": str(uuid4()), "t": ts[0]["id"], "c": bconv, "u": users[0]["id"]},
            )
        db.rollback()


def test_request_limits_and_unexpected_errors_do_not_leak(platform, monkeypatch, caplog):
    from support_agent.services import conversations

    c, app, root, ts, hs, users, password = platform
    secret = "never-log-" + uuid4().hex
    oversized = c.post(
        "/api/v1/conversations",
        headers=hs[0] | {"Content-Type": "text/plain"},
        content="x" * 131073,
    )
    assert oversized.status_code == 413

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(conversations, "create", fail)
    response = c.post("/api/v1/conversations", headers=hs[0], json={"channel": "api"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    assert secret not in response.text and secret not in caplog.text


def test_real_database_failure_is_safe(platform, caplog):
    from support_agent.dependencies import get_db

    c, app, root, ts, hs, users, password = platform
    secret = "never-log-" + uuid4().hex

    def broken_database():
        with app.state.sessions() as db:
            db.execute(text("SELECT CAST(:value AS integer)"), {"value": secret})
            yield db

    app.dependency_overrides[get_db] = broken_database
    try:
        response = c.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "database_unavailable"
        assert secret not in response.text and secret not in caplog.text
    finally:
        app.dependency_overrides.clear()


def test_last_admin_concurrency_and_disabled_user(platform):
    from datetime import UTC, datetime, timedelta

    from support_agent.models import AuthSession
    from support_agent.security import token_digest

    c, app, root, ts, hs, users, password = platform
    p = "/api/v1"
    a = hs[0]
    added = c.post(p + "/memberships", headers=a, json={"user_id": users[3]["id"], "role": "admin"})
    assert added.status_code == 201
    second = c.post(
        p + "/auth/login", json={"login": users[3]["login"], "password": password}
    ).json()
    s = {"Authorization": "Bearer " + second["access_token"], "X-Tenant-ID": ts[0]["id"]}
    own = next(
        m for m in c.get(p + "/memberships", headers=a).json() if m["user_id"] == users[0]["id"]
    )

    def demote(args):
        headers, mid = args
        return c.patch(
            p + "/memberships/" + mid, headers=headers, json={"role": "member"}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(demote, [(a, own["id"]), (s, added.json()["id"])]))
    assert sorted(codes) == [200, 409]
    remaining = a if codes[0] == 409 else s
    assert (
        sum(
            m["role"] == "admin" and m["status"] == "active"
            for m in c.get(p + "/memberships", headers=remaining).json()
        )
        == 1
    )
    member = c.post(
        p + "/auth/login", json={"login": users[2]["login"], "password": password}
    ).json()
    headers = {"Authorization": "Bearer " + member["access_token"]}
    assert (
        c.patch(
            p + "/users/" + users[2]["id"], headers=root, json={"status": "inactive"}
        ).status_code
        == 200
    )
    assert c.get(p + "/auth/me", headers=headers).status_code == 401
    assert (
        c.patch(p + "/users/" + users[2]["id"], headers=root, json={"status": "active"}).status_code
        == 200
    )
    assert c.get(p + "/auth/me", headers=headers).status_code == 401
    with app.state.sessions.begin() as db:
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == token_digest(second["access_token"])
            )
        )
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert c.get(p + "/auth/me", headers=s).status_code == 401
