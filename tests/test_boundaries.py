"""Real PostgreSQL acceptance. No SQLite, mock database, truncation or schema reset."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError


def test_crud_isolation_and_membership_revocation(platform):
    c, app, root, ts, hs, users, password = platform
    a, b = hs
    prefix = "/api/v1"
    login = "created-" + uuid4().hex
    created = c.post(
        prefix + "/users",
        headers=root,
        json={"login": login, "display_name": "Created user", "password": password},
    )
    assert created.status_code == 201 and password not in created.text
    assert (
        c.post(prefix + "/auth/login", json={"login": login, "password": password}).status_code
        == 200
    )
    assert (
        c.post(
            prefix + "/auth/login", json={"login": login, "password": "wrong-password"}
        ).status_code
        == 401
    )
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


def test_real_postgres_rls_and_optimistic_concurrency(platform):
    from support_agent.preflight import RLS_TABLES

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
        assert len(RLS_TABLES) == 17
        for name in RLS_TABLES:
            assert db.execute(text(f'SELECT id FROM "{name}" LIMIT 1')).all() == []
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
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relnamespace='public'::regnamespace AND relname=ANY(:tables)"
            ),
            {"tables": list(RLS_TABLES)},
        ).all()
        assert len(tables) == 17 and all(row[1] and row[2] for row in tables)
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
