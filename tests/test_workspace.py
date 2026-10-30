"""Workspace boundaries against real PostgreSQL; no external model calls."""

from phase2_support import private_settings  # noqa: F401


def test_browser_session_origin_logout_and_bearer_compatibility(platform):
    c, app, _, _, hs, users, password = platform
    origin = "http://testserver"
    app.state.settings = app.state.settings.model_copy(update={"web_origin": origin})
    denied = c.post(
        "/api/v1/web-session",
        headers={"Origin": "https://other.example"},
        json={"login": users[0]["login"], "password": password},
    )
    assert denied.status_code == 403
    login = c.post(
        "/api/v1/web-session",
        headers={"Origin": origin},
        json={"login": users[0]["login"], "password": password},
    )
    assert login.status_code == 200 and "access_token" not in login.text
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert c.get("/api/v1/auth/me").json()["id"] == users[0]["id"]
    assert c.post("/api/v1/auth/logout").status_code == 403
    assert c.post("/api/v1/auth/logout", headers={"Origin": origin}).status_code == 204
    assert c.get("/api/v1/auth/me").status_code == 401
    assert c.get("/api/v1/auth/me", headers=hs[0]).status_code == 200


def test_demo_provider_persists_and_external_transport_is_disabled(platform, monkeypatch):
    from uuid import uuid4

    from support_agent import providers

    c, _, _, _, hs, _, _ = platform
    a = hs[0]
    cfg = c.post(
        "/api/v1/agent-configs",
        headers=a,
        json={"name": "离线演示", "provider": "demo", "model": "offline-support"},
    ).json()["id"]
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]

    def forbidden(*args, **kwargs):
        raise AssertionError("External transport must not start")

    monkeypatch.setattr(providers.subprocess, "run", forbidden)
    answer = c.post(
        f"/api/v1/conversations/{cid}/agent-turns",
        headers=a,
        json={"agent_config_id": cfg, "content": "你好", "idempotency_key": str(uuid4())},
    )
    assert answer.status_code == 200 and answer.json()["status"] == "answered", answer.text
    assert "离线演示" in answer.json()["answer"]
    rows = c.get("/api/v1/model-calls", headers=a).json()
    assert rows[-1]["steps"][0]["provider"] == "demo"
    assert rows[-1]["reserved_tokens"] == 0
    assert c.get("/api/v1/workspace", headers=a).json()["external_models_enabled"] is False
    import pytest

    with pytest.raises(providers.ProviderFailure) as failure:
        providers.OpenAICompatibleProvider(["api.example.com"], enabled=False).complete()
    assert failure.value.category == "external_models_disabled"


def test_knowledge_authorization_grounding_handoff_and_call_history(platform):
    from uuid import uuid4

    from phase2_support import kb, upload

    c, _, _, _, hs, _, _ = platform
    a, b = hs
    cfg = c.post(
        "/api/v1/agent-configs",
        headers=a,
        json={"name": "知识客服", "provider": "demo", "model": "offline-support"},
    ).json()["id"]
    kid = kb(c, a)
    upload(c, a, kid, "邮箱.txt", "邮箱修改：进入账户设置，验证后保存。".encode())
    binding = c.put(
        f"/api/v1/agent-configs/{cfg}/knowledge-bases",
        headers=a,
        json={"knowledge_base_ids": [kid]},
    )
    assert binding.status_code == 200, binding.text
    assert (
        c.put(
            f"/api/v1/agent-configs/{cfg}/knowledge-bases",
            headers=b,
            json={"knowledge_base_ids": []},
        ).status_code
        == 404
    )
    cid = c.post("/api/v1/conversations", headers=a, json={"subject": "账号咨询"}).json()["id"]

    def ask(content="如何修改邮箱", **extra):
        return c.post(
            f"/api/v1/conversations/{cid}/agent-turns",
            headers=a,
            json={
                "agent_config_id": cfg,
                "content": content,
                "idempotency_key": str(uuid4()),
                **extra,
            },
        )

    answer = ask()
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "answered" and answer.json()["grounded"]
    assert answer.json()["citations"][0]["document_name"] == "邮箱.txt"
    calls = c.get(f"/api/v1/conversations/{cid}/calls", headers=a).json()
    assert calls[0]["id"] == answer.json()["call_id"]
    other = kb(c, b)
    assert ask(knowledge_base_ids=[other]).status_code in {403, 404}
    assert (
        c.post(
            f"/api/v1/conversations/{cid}/handling", headers=a, json={"state": "waiting"}
        ).status_code
        == 200
    )
    denied = ask()
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "human_handling_active"
    assert (
        c.post(
            f"/api/v1/conversations/{cid}/handling", headers=a, json={"state": "human"}
        ).status_code
        == 200
    )
    reply = c.post(
        f"/api/v1/conversations/{cid}/messages",
        headers=a,
        json={"role": "assistant", "content": "人工答复"},
    )
    assert reply.status_code == 201
    assert (
        c.post(f"/api/v1/conversations/{cid}/handling", headers=a, json={"state": "ai"}).status_code
        == 200
    )
    assert ask().json()["grounded"]
    assert c.get(f"/api/v1/conversations/{cid}/calls", headers=b).status_code == 404


def test_member_cannot_release_handoff_via_legacy_status_and_chunks_are_scoped(platform):
    from phase2_support import kb, upload

    c, _, _, tenants, hs, users, password = platform
    a, b = hs
    assert (
        c.post("/api/v1/memberships", headers=a, json={"user_id": users[2]["id"]}).status_code
        == 201
    )
    token = c.post(
        "/api/v1/auth/login", json={"login": users[2]["login"], "password": password}
    ).json()["access_token"]
    member = {"Authorization": "Bearer " + token, "X-Tenant-ID": tenants[0]["id"]}
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]
    assert (
        c.post(
            f"/api/v1/conversations/{cid}/handling", headers=member, json={"state": "waiting"}
        ).status_code
        == 200
    )
    assert (
        c.patch(f"/api/v1/conversations/{cid}", headers=member, json={"status": "open"}).status_code
        == 403
    )
    assert (
        c.post(
            f"/api/v1/conversations/{cid}/handling", headers=member, json={"state": "ai"}
        ).status_code
        == 403
    )
    kid = kb(c, a)
    doc = upload(c, a, kid, "说明.txt", "账户支持：请先完成安全验证。".encode()).json()
    rows = c.get(f"/api/v1/documents/{doc['id']}/chunks", headers=member)
    assert rows.status_code == 200 and rows.json()[0]["content"] == "账户支持：请先完成安全验证。"
    assert c.get(f"/api/v1/documents/{doc['id']}/chunks", headers=b).status_code == 404
    assert (
        c.post(
            "/api/v1/publications",
            headers=member,
            json={"agent_config_id": cid, "name": "不可发布"},
        ).status_code
        == 403
    )
    cfg = c.post(
        "/api/v1/agent-configs",
        headers=a,
        json={"name": "版本", "provider": "demo", "model": "offline-support"},
    ).json()
    body = {"knowledge_base_ids": [kid], "expected_version": cfg["version"]}
    assert (
        c.put(
            f"/api/v1/agent-configs/{cfg['id']}/knowledge-bases", headers=a, json=body
        ).status_code
        == 200
    )
    assert (
        c.put(
            f"/api/v1/agent-configs/{cfg['id']}/knowledge-bases",
            headers=a,
            json=body | {"knowledge_base_ids": []},
        ).status_code
        == 409
    )


def test_web_assets_and_public_embed_policy(platform):
    c, *_ = platform
    from pathlib import Path

    web = Path(__file__).parents[1] / "src/support_agent/web"
    assert c.get("/").status_code == 200
    assert "frame-ancestors 'none'" in c.get("/").headers["content-security-policy"]
    for path in web.iterdir():
        if path.suffix in {".js", ".css"}:
            r = c.get("/assets/" + path.name)
            assert r.status_code == 200, path.name
            assert r.headers["x-content-type-options"] == "nosniff"
    from uuid import uuid4

    response = c.get("/chat/" + str(uuid4()))
    assert (
        response.status_code == 200
        and "frame-ancestors *" in response.headers["content-security-policy"]
    )
    assert c.get("/widget.js").status_code == 200
    assert c.get("/assets/../../.env").status_code == 404
    assert c.get("/api/v1/public/" + str(uuid4())).status_code == 404
