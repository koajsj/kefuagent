"""P4 offline acceptance: real PostgreSQL, controlled provider; never paid requests."""

import json
from uuid import uuid4

from phase2_support import config, kb, upload  # noqa: F401


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
