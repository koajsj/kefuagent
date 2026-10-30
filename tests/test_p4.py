"""P4 offline acceptance: real PostgreSQL, controlled provider; never paid requests."""

import json
from uuid import uuid4

from phase2_support import config, kb, private_settings, upload  # noqa: F401


def rag(c, headers, cfg, cid, kid, content, **extra):
    return c.post(
        f"/api/v1/conversations/{cid}/chat",
        headers=headers,
        json={
            "agent_config_id": cfg,
            "knowledge_base_ids": [kid],
            "content": content,
            "idempotency_key": str(uuid4()),
            **extra,
        },
    )


def test_chinese_retrieval_and_deleted_sources(platform):
    c, _, _, _, hs, _, _ = platform
    a = hs[0]
    kid = kb(c, a)
    doc = upload(
        c, a, kid, "账户.txt", "登录邮箱修改：进入账户设置，完成验证后保存新邮箱。".encode()
    ).json()
    for query in ["如何修改登录邮箱", "能更改电子邮件吗"]:
        hits = c.post(
            f"/api/v1/knowledge-bases/{kid}/search", headers=a, json={"query": query}
        ).json()
        assert hits and hits[0]["document_id"] == doc["id"], (query, hits)
    assert c.delete("/api/v1/documents/" + doc["id"], headers=a).status_code == 204
    assert (
        c.post(
            f"/api/v1/knowledge-bases/{kid}/search", headers=a, json={"query": "邮箱修改"}
        ).json()
        == []
    )


def test_routing_fallback_context_and_usage(platform):
    from support_agent.providers import Completion, ProviderFailure

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, _, _ = config(c, a)
    body = c.get("/api/v1/agent-configs/" + cfg, headers=a).json()
    update = {
        key: body[key]
        for key in [
            "name",
            "enabled",
            "provider",
            "model",
            "runtime",
            "behavior",
            "base_url",
            "credential_ref",
        ]
    }
    update["runtime"]["routing"] = {
        "qa": {"model": "offline-economy", "supports_tools": False},
        "reasoning": {"model": "offline-reasoning", "supports_tools": True},
        "fallback": {"model": "offline-backup", "supports_tools": True},
    }
    r = c.put(
        "/api/v1/agent-configs/" + cfg,
        headers=a,
        json=update | {"expected_version": body["version"]},
    )
    assert r.status_code == 200, r.text
    kid = kb(c, a)
    upload(c, a, kid, "warranty.txt", b"Warranty lasts thirty days.")
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]

    class Controlled:
        def complete(self, **kwargs):
            if kwargs["model"] == "offline-economy":
                raise ProviderFailure("model_unavailable")
            hit = json.loads(kwargs["messages"][-1]["content"])["evidence"][0]
            return Completion(
                json.dumps(
                    {
                        "answerable": True,
                        "citations": [
                            {"chunk_id": hit["chunk_id"], "quote": "Warranty lasts thirty days."}
                        ],
                    }
                ),
                11,
                4,
            )

    app.state.provider = Controlled()
    result = rag(c, a, cfg, cid, kid, "Warranty")
    assert result.status_code == 200 and result.json()["status"] == "answered", result.text
    row = c.get("/api/v1/model-calls/" + result.json()["call_id"], headers=a).json()
    assert [step["model"] for step in row["steps"]] == ["offline-economy", "offline-backup"]
    assert row["steps"][1]["selection_reason"] == "fallback:model_unavailable"
    assert row["phase"] == "completed" and row["attempts"] == 2


def test_credential_rotation_and_deletion_suppress_inflight_payload(platform):
    from support_agent.providers import Completion

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, cred, _ = config(c, a)
    kid = kb(c, a)
    upload(c, a, kid, "source.txt", b"Warranty lasts thirty days.")
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]

    class ChangedCredential:
        mode = "rotate"

        def complete(self, **kwargs):
            if self.mode == "rotate":
                response = c.put(
                    "/api/v1/model-credentials/" + cred,
                    headers=a,
                    json={"ref": "cred_main", "api_key": "synthetic-rotated-key"},
                )
            else:
                response = c.delete("/api/v1/model-credentials/" + cred, headers=a)
            assert response.status_code in (200, 204)
            hit = json.loads(kwargs["messages"][-1]["content"])["evidence"][0]
            return Completion(
                json.dumps(
                    {
                        "answerable": True,
                        "citations": [
                            {"chunk_id": hit["chunk_id"], "quote": "Warranty lasts thirty days."}
                        ],
                    }
                ),
                17,
                8,
            )

    provider = ChangedCredential()
    app.state.provider = provider
    for mode in ["rotate", "delete"]:
        provider.mode = mode
        result = rag(c, a, cfg, cid, kid, "Warranty").json()
        assert result["status"] == "failed" and result["answer"] == "" and result["citations"] == []
        assert result["error_category"] == "credential_or_configuration_changed"
        call = c.get("/api/v1/model-calls/" + result["call_id"], headers=a).json()
        assert call["input_tokens"] == 17 and call["phase"] == "failed"
    result = rag(c, a, cfg, cid, kid, "Warranty").json()
    assert result["status"] == "failed" and result["error_category"] == "credential_unavailable"
    assert c.get("/api/v1/model-calls/" + result["call_id"], headers=a).json()["attempts"] == 0


def test_limits_unknown_usage_and_idempotency(platform):
    from support_agent.providers import Completion

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, _, _ = config(c, a)
    kid = kb(c, a)
    upload(c, a, kid, "source.txt", b"Warranty lasts thirty days.")
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]

    class UnknownUsage:
        def complete(self, **kwargs):
            return Completion('{"answerable":false,"citations":[]}')

    app.state.provider = UnknownUsage()
    runtime = c.get("/api/v1/agent-configs/" + cfg, headers=a).json()["runtime"]
    held = 4 * (runtime["max_input_tokens"] + runtime["max_output_tokens"])
    app.state.settings.user_daily_token_budget = held
    key = str(uuid4())
    first = rag(c, a, cfg, cid, kid, "Warranty", idempotency_key=key)
    row = c.get("/api/v1/model-calls/" + first.json()["call_id"], headers=a).json()
    assert (
        row["reserved_tokens"] == held and row["input_tokens"] is None and not row["usage_complete"]
    )
    assert rag(c, a, cfg, cid, kid, "Warranty", idempotency_key=key).json()["call_id"] == row["id"]
    rejected = rag(c, a, cfg, cid, kid, "Warranty")
    assert (
        rejected.status_code == 429 and rejected.json()["error"]["code"] == "token_budget_exceeded"
    )
    app.state.settings.user_daily_token_budget = 1000000
    app.state.settings.user_requests_per_minute = 1
    assert rag(c, a, cfg, cid, kid, "Warranty").json()["error"]["code"] == "request_limit_exceeded"
    view = c.get("/api/v1/usage-limits", headers=a).json()
    assert view["current_user_usage"]["tokens_reserved_today"] == held


def test_rag_history_scope_conflict_and_state_visibility(platform):
    from support_agent.providers import Completion

    c, app, _, _, hs, _, _ = platform
    a, b = hs
    cfg, _, _ = config(c, a)
    first, second = kb(c, a, "one"), kb(c, a, "two")
    upload(c, a, first, "a.txt", b"Warranty lasts thirty days.")
    upload(c, a, second, "b.txt", b"Warranty lasts sixty days.")
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]

    class Scoped:
        prior = ""

        def complete(self, **kwargs):
            if self.prior:
                assert self.prior not in json.dumps(kwargs["messages"])
            calls = c.get("/api/v1/model-calls", headers=a).json()
            current = c.get(
                f"/api/v1/conversations/{cid}/runs/" + calls[-1]["id"], headers=a
            ).json()
            assert current["phase"] == "model_running"
            assert (
                c.get(f"/api/v1/conversations/{cid}/runs/" + calls[-1]["id"], headers=b).status_code
                == 404
            )
            hit = json.loads(kwargs["messages"][-1]["content"])["evidence"][0]
            return Completion(
                json.dumps(
                    {
                        "answerable": True,
                        "citations": [{"chunk_id": hit["chunk_id"], "quote": hit["content"]}],
                    }
                ),
                9,
                3,
            )

    provider = Scoped()
    app.state.provider = provider
    assert rag(c, a, cfg, cid, first, "Warranty").json()["status"] == "answered"
    provider.prior = "Warranty lasts thirty days."
    assert rag(c, a, cfg, cid, second, "Warranty").json()["status"] == "answered"
    conflict = kb(c, a, "conflict")
    upload(c, a, conflict, "one.txt", "服务期限：三十天。".encode())
    upload(c, a, conflict, "two.txt", "服务期限：七天。".encode())
    result = rag(c, a, cfg, cid, conflict, "服务期限").json()
    assert result["status"] == "unresolved" and result["error_category"] == "conflicting_evidence"


def test_transport_quota_and_model_capabilities(monkeypatch):
    import httpcore
    import pytest

    from support_agent import providers

    body = b'{"error":{"code":"insufficient_quota"}}'
    wire = b"HTTP/1.1 429 Error\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    backend = httpcore.MockBackend([wire])
    monkeypatch.setattr(providers, "PublicNetworkBackend", lambda: backend)
    with pytest.raises(providers.ProviderFailure) as exc:
        providers.OpenAICompatibleProvider(["api.example.com"]).complete_in_process(
            base_url="https://api.example.com/v1",
            api_key="synthetic",
            model="offline-only",
            messages=[],
            runtime={"timeout_seconds": 2, "temperature": 0, "max_output_tokens": 8},
        )
    assert exc.value.category == "quota_exhausted" and exc.value.attempts == 1
    assert (
        providers.normalize_status(
            400, b'{"error":{"code":"unsupported_parameter","param":"tools"}}'
        )
        == "tools_not_supported"
    )


def test_cross_conversation_admission_and_connection_cap(platform):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from support_agent.providers import Completion

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, _, _ = config(c, a)
    entered, release = Event(), Event()

    class Bounded:
        def complete(self, **kwargs):
            assert kwargs["runtime"]["max_output_tokens"] == 32
            return Completion('{"ok":true}', 9, 4)

    app.state.provider = Bounded()
    checked = c.post(f"/api/v1/agent-configs/{cfg}/test-connection", headers=a)
    assert checked.status_code == 200 and checked.json()["status"] == "connected", checked.text
    assert checked.json()["reserved_tokens"] == 13
    assert "credential_stamp" not in checked.text
    kid = kb(c, a)
    upload(c, a, kid, "source.txt", b"Warranty lasts thirty days.")
    one, two = [c.post("/api/v1/conversations", headers=a, json={}).json()["id"] for _ in range(2)]
    app.state.settings.user_concurrent_calls = 1

    class Blocked:
        def complete(self, **kwargs):
            entered.set()
            assert release.wait(10)
            return Completion('{"answerable":false,"citations":[]}', 12, 4)

    app.state.provider = Blocked()
    with ThreadPoolExecutor(max_workers=1) as workers:
        first = workers.submit(rag, c, a, cfg, one, kid, "Warranty")
        try:
            assert entered.wait(10)
            second = rag(c, a, cfg, two, kid, "Warranty")
            assert second.status_code == 429, second.text
            assert second.json()["error"]["code"] == "concurrency_limit_exceeded"
        finally:
            release.set()
        assert first.result().status_code == 200
    assert c.get("/api/v1/usage-limits", headers=a).json()["tenant_usage"]["active_calls"] == 0
