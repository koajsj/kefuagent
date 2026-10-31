"""P3 real persistence and controlled model/tool boundaries; no external API calls."""

import json
from uuid import uuid4

from phase2_support import config, private_settings  # noqa: F401

PARAMETERS = {
    "type": "object",
    "properties": {"text": {"type": "string", "maxLength": 4000}},
    "required": ["text"],
    "additionalProperties": False,
}
OUTPUT = {
    "type": "object",
    "properties": {"characters": {"type": "integer"}, "words": {"type": "integer"}},
    "required": ["characters", "words"],
    "additionalProperties": False,
}


def setup(c, a):
    cfg, _, secret = config(c, a)
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]
    r = c.post(
        "/api/v1/tools",
        headers=a,
        json={
            "key": "text_metrics",
            "name": "文本统计",
            "description": "统计文本字符和词数",
            "parameters": PARAMETERS,
            "output_schema": OUTPUT,
            "execution_type": "read_only",
        },
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = c.put(f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=a, json={"enabled": True})
    assert r.status_code == 200, r.text
    return cfg, cid, tid, secret


def turn(c, a, cfg, cid, key=None):
    return c.post(
        f"/api/v1/conversations/{cid}/agent-turns",
        headers=a,
        json={
            "agent_config_id": cfg,
            "content": "Count hello world",
            "idempotency_key": key or str(uuid4()),
        },
    )


def test_agent_multitool_history_usage_and_idempotency(platform):
    from support_agent.providers import Completion, ModelToolCall

    c, app, _, ts, hs, _, _ = platform
    a, b = hs
    cfg, cid, tid, secret = setup(c, a)

    class Sequence:
        count = 0

        def complete(self, **kwargs):
            self.count += 1
            if self.count <= 2:
                return Completion(
                    "",
                    10,
                    2,
                    tool_calls=(
                        ModelToolCall(
                            f"call_{self.count}",
                            "text_metrics",
                            json.dumps({"text": "hello world"}),
                        ),
                    ),
                )
            return Completion("The text has 11 characters and 2 words.", 12, 8)

    app.state.provider = Sequence()
    key = str(uuid4())
    r = turn(c, a, cfg, cid, key)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "answered" and len(out["executions"]) == 2
    assert all(
        e["status"] == "succeeded" and e["data"] == {"characters": 11, "words": 2}
        for e in out["executions"]
    )
    assert turn(c, a, cfg, cid, key).json()["call_id"] == out["call_id"]
    assert turn(c, b, cfg, cid).status_code == 404
    calls = c.get("/api/v1/model-calls", headers=a).json()
    assert calls[-1]["input_tokens"] == 32 and calls[-1]["output_tokens"] == 12
    history = c.get(f"/api/v1/conversations/{cid}/messages", headers=a).json()
    assert [m["role"] for m in history] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert all(m["source"] == "agent" for m in history)
    assert history[2]["tool_call_id"] == "call_1"
    events = c.get("/api/v1/audit-events", headers=a).json()
    finished = [e for e in events if e["action"] == "tool_execution.finish"]
    assert len(finished) == 2 and all(e["outcome"] == "success" for e in finished)
    assert secret not in json.dumps(events)
    # Revoked payloads cannot be recovered through history, journal or an idempotent replay.
    c.put(f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=a, json={"enabled": False})
    assert turn(c, a, cfg, cid, key).status_code == 409
    journal = c.get("/api/v1/tool-executions", headers=a).json()
    assert all(row["data"] is None for row in journal)
    old = c.get(f"/api/v1/conversations/{cid}/messages", headers=a).json()
    assert all(
        "11 characters" not in m["content"] and '"characters": 11' not in m["content"] for m in old
    )


def test_provider_native_tool_protocol_and_refusal():
    from support_agent.providers import parse_completion

    body = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "abc",
                            "type": "function",
                            "function": {"name": "text_metrics", "arguments": '{"text":"hello"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    completion = parse_completion(json.dumps(body).encode(), 1, allow_tools=True)
    assert completion.tool_calls[0].name == "text_metrics" and completion.input_tokens == 7
    body["choices"][0] = {
        "finish_reason": "stop",
        "message": {"refusal": "Cannot help", "content": None},
    }
    assert parse_completion(json.dumps(body).encode(), 1, allow_tools=True).refused


def test_process_runner_bounds_and_secret_free_environment():
    import time

    import pytest
    from tool_fixtures import explode, flood, inspect_environment, slow

    from support_agent.tool_protocol import ExecutionContext
    from support_agent.tool_runtime import Capability, ProcessToolRunner, ToolFailure

    runner = ProcessToolRunner()
    ctx = ExecutionContext(uuid4(), uuid4(), uuid4(), "member", uuid4())
    for handler, timeout, category in [
        (slow, 1, "tool_timeout"),
        (explode, 2, "tool_handler_error"),
        (flood, 2, "tool_process_interrupted"),
    ]:
        started = time.monotonic()
        with pytest.raises(ToolFailure) as failure:
            runner.run(
                Capability("fixture", 1, PARAMETERS, OUTPUT, handler, timeout_seconds=timeout),
                {"text": "a"},
                ctx,
            )
        assert failure.value.category == category
        assert time.monotonic() - started < 4
    data = runner.run(
        Capability("fixture", 1, PARAMETERS, OUTPUT, inspect_environment), {"text": "a"}, ctx
    )
    assert data == {"characters": 0, "words": 0}


def test_post_execution_revocation_keeps_actual_state_and_suppresses_delivery(platform):
    from support_agent.tool_runtime import ProcessToolRunner

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, cid, tid, _ = setup(c, a)

    class RevokeAfterExecution:
        def run(self, capability, arguments, context):
            result = ProcessToolRunner().run(capability, arguments, context)
            r = c.put(
                f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=a, json={"enabled": False}
            )
            assert r.status_code == 200
            return result

    app.state.tool_runner = RevokeAfterExecution()
    r = c.post(
        f"/api/v1/tools/{tid}/execute",
        headers=a,
        json={
            "arguments": {"text": "hello"},
            "conversation_id": cid,
            "agent_config_id": cfg,
            "idempotency_key": str(uuid4()),
            "tool_call_id": "revoked_after",
        },
    )
    rows = c.get("/api/v1/tool-executions", headers=a).json()
    assert rows[-1]["status"] == "succeeded", rows
    assert rows[-1]["delivery_error"] == "tool_not_authorized" and rows[-1]["data"] is None
    assert r.status_code == 409
    calls = c.get("/api/v1/model-calls", headers=a).json()
    assert calls[-1]["status"] == "failed" and calls[-1]["error_category"] == "tool_not_authorized"


def direct(c, a, cfg, cid, tid, arguments, key=None, tool_call_id="direct_call"):
    return c.post(
        f"/api/v1/tools/{tid}/execute",
        headers=a,
        json={
            "arguments": arguments,
            "conversation_id": cid,
            "agent_config_id": cfg,
            "idempotency_key": key or str(uuid4()),
            "tool_call_id": tool_call_id,
        },
    )


def test_direct_validation_grants_risks_and_tenant_boundaries(platform):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError, ProgrammingError

    c, app, _, ts, hs, _, _ = platform
    a, b = hs
    cfg, cid, tid, _ = setup(c, a)
    bcfg, bcid, btid, _ = setup(c, b)
    for arguments in [
        {},
        {"text": 9},
        {"text": "ok", "tenant_id": ts[1]["id"]},
        {"text": "x" * 4001},
    ]:
        r = direct(c, a, cfg, cid, tid, arguments)
        assert r.status_code == 200 and r.json()["status"] == "denied", r.text
        assert r.json()["error_category"] == "tool_arguments_invalid"
    malicious_literal = (
        '__import__("os").system("touch /tmp/should-never-exist"); DROP TABLE users; $(id)'
    )
    r = direct(c, a, cfg, cid, tid, {"text": malicious_literal})
    assert r.json()["data"]["characters"] == len(malicious_literal)
    assert direct(c, b, cfg, cid, tid, {"text": "ok"}).status_code == 404
    assert direct(c, a, bcfg, cid, tid, {"text": "ok"}).status_code == 404
    assert direct(c, a, cfg, bcid, tid, {"text": "ok"}).status_code == 404
    assert (
        c.put(
            f"/api/v1/agent-configs/{cfg}/tools/{btid}", headers=a, json={"enabled": True}
        ).status_code
        == 404
    )
    assert c.get("/api/v1/tool-executions", headers=b).json() == []
    assert (
        c.get("/api/v1/tool-executions/" + r.json()["execution_id"], headers=b).status_code == 404
    )
    assert c.post("/api/v1/tools/" + tid + "/execute", json={}).status_code == 401
    c.put(f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=a, json={"enabled": False})
    assert (
        direct(c, a, cfg, cid, tid, {"text": "ok"}).json()["error_category"]
        == "tool_not_authorized"
    )
    for mode, risk, category in [
        ("write", "low", "approval_required"),
        ("read_only", "high", "approval_required"),
        ("read_only", "low", "tool_not_bound"),
    ]:
        tool = c.post(
            "/api/v1/tools",
            headers=a,
            json={
                "key": "unbound_" + uuid4().hex,
                "name": "guarded",
                "description": "deployment binding required",
                "parameters": PARAMETERS,
                "output_schema": OUTPUT,
                "execution_type": mode,
                "risk_level": risk,
            },
        ).json()["id"]
        c.put(f"/api/v1/agent-configs/{cfg}/tools/{tool}", headers=a, json={"enabled": True})
        result = direct(c, a, cfg, cid, tool, {"text": "ok"}).json()
        assert result["status"] == "denied" and result["error_category"] == category
    with app.state.sessions() as db:
        flags = db.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('agent_tools','tool_executions')"
            )
        ).all()
        assert len(flags) == 2 and all(row[1] and row[2] for row in flags)
        for table in ["agent_tools", "tool_executions"]:
            assert db.execute(text(f"SELECT id FROM {table}")).all() == []
            db.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": ts[0]["id"]})
            with pytest.raises(ProgrammingError) as failure:
                db.execute(
                    text(f"UPDATE {table} SET tenant_id=:b WHERE tenant_id=:a"),
                    {"a": ts[0]["id"], "b": ts[1]["id"]},
                )
            assert failure.value.orig.sqlstate == "42501"
            db.rollback()
        db.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": ts[0]["id"]})
        with pytest.raises(IntegrityError) as failure:
            db.execute(
                text("UPDATE agent_tools SET tool_id=:b WHERE tool_id=:a"), {"a": tid, "b": btid}
            )
        assert failure.value.orig.sqlstate == "23503"
        db.rollback()


def test_tool_failures_are_terminal_redacted_and_audited(platform, caplog):
    from tool_fixtures import explode, slow

    from support_agent.tool_runtime import Capability, ToolRegistry

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, cid, tid, secret = setup(c, a)
    for handler, seconds, state, category in [
        (slow, 1, "timed_out", "tool_timeout"),
        (explode, 2, "failed", "tool_handler_error"),
    ]:
        app.state.tool_registry = ToolRegistry(
            [Capability("text_metrics", 1, PARAMETERS, OUTPUT, handler, timeout_seconds=seconds)]
        )
        key = str(uuid4())
        first = direct(c, a, cfg, cid, tid, {"text": "sensitive-input-do-not-audit"}, key)
        assert first.status_code == 200, first.text
        result = first.json()
        assert result["status"] == state and result["error_category"] == category
        again = direct(c, a, cfg, cid, tid, {"text": "sensitive-input-do-not-audit"}, key).json()
        assert again["execution_id"] == result["execution_id"] and again["status"] == state
        events = c.get("/api/v1/audit-events", headers=a).json()
        finish = next(
            e
            for e in events
            if e["resource_id"] == result["execution_id"] and e["action"] == "tool_execution.finish"
        )
        assert finish["outcome"] == "failure" and finish["reason"] == category
        assert finish["details"]["status"] == state
        assert "sensitive-input-do-not-audit" not in json.dumps(events)
    assert secret not in caplog.text and "fixture-sensitive-stack-do-not-leak" not in caplog.text


def test_model_errors_injection_and_loop_budgets(platform):
    from tool_fixtures import injection

    from support_agent.providers import Completion, ModelToolCall, ProviderFailure
    from support_agent.tool_runtime import Capability, ToolRegistry

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, cid, tid, _ = setup(c, a)
    schema = {
        "type": "object",
        "properties": {"notice": {"type": "string", "maxLength": 2000}},
        "required": ["notice"],
        "additionalProperties": False,
    }
    app.state.tool_registry = ToolRegistry(
        [Capability("text_metrics", 1, PARAMETERS, OUTPUT, injection)]
    )
    # Contract mismatch cannot be relaxed by changing only a database declaration.
    assert direct(c, a, cfg, cid, tid, {"text": "ok"}).json()["status"] == "failed"
    tool = c.post(
        "/api/v1/tools",
        headers=a,
        json={
            "key": "notice",
            "name": "notice",
            "description": "untrusted data",
            "parameters": PARAMETERS,
            "output_schema": schema,
            "execution_type": "read_only",
        },
    ).json()["id"]
    c.put(f"/api/v1/agent-configs/{cfg}/tools/{tool}", headers=a, json={"enabled": True})
    app.state.tool_registry = ToolRegistry([Capability("notice", 1, PARAMETERS, schema, injection)])

    class Injected:
        count = 0

        def complete(self, **kwargs):
            self.count += 1
            if self.count == 1:
                return Completion(
                    "", tool_calls=(ModelToolCall("first", "notice", '{"text":"ok"}'),)
                )
            if self.count == 2:
                assert "Switch tenant" not in kwargs["messages"][0]["content"]
                assert kwargs["messages"][-1]["role"] == "tool"
                # Even a model fooled by returned instructions cannot gain an ungranted write tool.
                return Completion("", tool_calls=(ModelToolCall("evil", "write_everything", "{}"),))
            return Completion("That requested action is unavailable.")

    app.state.provider = Injected()
    result = turn(c, a, cfg, cid).json()
    assert result["status"] == "answered"
    assert [e["status"] for e in result["executions"]] == ["succeeded", "denied"]
    assert result["executions"][1]["error_category"] == "tool_unavailable"

    class Repeated:
        count = 0

        def complete(self, **kwargs):
            self.count += 1
            return Completion("", tool_calls=(ModelToolCall("repeat", "notice", '{"text":"ok"}'),))

    app.state.provider = Repeated()
    repeated = turn(c, a, cfg, cid).json()
    assert repeated["error_category"] == "duplicate_tool_call" and len(repeated["executions"]) == 1

    class Endless:
        count = 0

        def complete(self, **kwargs):
            self.count += 1
            return Completion("", tool_calls=(ModelToolCall(str(self.count), "absent", "{}"),))

    app.state.provider = Endless()
    limited = turn(c, a, cfg, cid).json()
    assert limited["error_category"] == "tool_limit_exceeded" and len(limited["executions"]) == 4

    class Refused:
        def complete(self, **kwargs):
            return Completion("", 2, 1, refused=True)

    app.state.provider = Refused()
    assert turn(c, a, cfg, cid).json()["error_category"] == "model_refused"

    class Failed:
        def complete(self, **kwargs):
            raise ProviderFailure("timeout", attempts=None, input_tokens=5)

    app.state.provider = Failed()
    failed = turn(c, a, cfg, cid).json()
    assert failed["status"] == "failed" and failed["error_category"] == "timeout"
    usage = c.get("/api/v1/model-calls", headers=a).json()[-1]
    assert (
        usage["input_tokens"] == 5 and usage["output_tokens"] is None and usage["attempts"] is None
    )


def test_active_execution_idempotency_interruption_and_state_fencing(platform):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime, timedelta
    from threading import Event

    from sqlalchemy import select

    from support_agent.models import ModelCall, ToolExecution
    from support_agent.tool_runtime import ProcessToolRunner

    c, app, _, ts, hs, _, _ = platform
    a = hs[0]
    cfg, cid, tid, _ = setup(c, a)
    entered, release = Event(), Event()

    class Blocking:
        def run(self, capability, arguments, context):
            entered.set()
            assert release.wait(5)
            return ProcessToolRunner().run(capability, arguments, context)

    app.state.tool_runner = Blocking()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(direct, c, a, cfg, cid, tid, {"text": "once"}, key)
        assert entered.wait(5)
        try:
            pending = direct(c, a, cfg, cid, tid, {"text": "once"}, key)
            assert pending.status_code == 200 and pending.json()["status"] == "running"
            assert direct(c, a, cfg, cid, tid, {"text": "different"}, key).status_code == 409
            assert turn(c, a, cfg, cid).status_code == 409
            assert (
                c.patch(
                    "/api/v1/conversations/" + cid, headers=a, json={"status": "closed"}
                ).status_code
                == 409
            )
            assert (
                c.post(
                    "/api/v1/conversations/" + cid + "/messages",
                    headers=a,
                    json={"role": "user", "content": "race"},
                ).status_code
                == 409
            )
            with app.state.sessions.begin() as db:
                db.execute(
                    __import__("sqlalchemy").text("SELECT set_config('app.tenant_id',:id,true)"),
                    {"id": ts[0]["id"]},
                )
                row = db.scalar(select(ToolExecution).where(ToolExecution.conversation_id == cid))
                row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                call = db.get(ModelCall, row.model_call_id)
                call.lease_expires_at = row.lease_expires_at
                eid = str(row.id)
            interrupted = direct(c, a, cfg, cid, tid, {"text": "once"}, key)
            assert interrupted.json()["status"] == "failed"
            assert interrupted.json()["error_category"] == "interrupted_result_unknown"
        finally:
            release.set()
        stale = future.result(timeout=5)
    assert stale.status_code == 409
    stored = c.get("/api/v1/tool-executions/" + eid, headers=a).json()
    assert stored["status"] == "failed" and stored["data"] is None
    events = c.get("/api/v1/audit-events", headers=a).json()
    assert (
        len(
            [
                e
                for e in events
                if e["resource_id"] == eid and e["action"] == "tool_execution.finish"
            ]
        )
        == 1
    )
    assert not any(e["resource_id"] == eid and e["outcome"] == "success" for e in events)


def test_each_model_call_rechecks_grants_and_member_permissions(platform):
    from support_agent.providers import Completion, ModelToolCall
    from support_agent.tool_runtime import ProcessToolRunner

    c, app, _, _, hs, users, password = platform
    a = hs[0]
    cfg, cid, tid, _ = setup(c, a)

    # The model received this tool before revocation, but its response grants no authority.
    class Revoking:
        count = 0

        def complete(self, **kwargs):
            self.count += 1
            if self.count == 1:
                c.put(
                    f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=a, json={"enabled": False}
                )
                return Completion(
                    "", tool_calls=(ModelToolCall("stale", "text_metrics", '{"text":"ok"}'),)
                )
            return Completion("Tool unavailable.")

    app.state.provider = Revoking()
    result = turn(c, a, cfg, cid).json()
    assert result["executions"][0]["status"] == "denied"
    assert result["executions"][0]["error_category"] == "tool_not_authorized"
    c.put(f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=a, json={"enabled": True})
    c.post("/api/v1/memberships", headers=a, json={"user_id": users[2]["id"], "role": "member"})
    login = c.post(
        "/api/v1/auth/login", json={"login": users[2]["login"], "password": password}
    ).json()
    member = a | {"Authorization": "Bearer " + login["access_token"]}
    assert (
        c.put(
            f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=member, json={"enabled": False}
        ).status_code
        == 403
    )
    assert direct(c, member, cfg, cid, tid, {"text": "ok"}).json()["status"] == "succeeded"
    restricted = c.post(
        "/api/v1/tools",
        headers=a,
        json={
            "key": "admin_only",
            "name": "admin",
            "description": "admin required",
            "parameters": PARAMETERS,
            "output_schema": OUTPUT,
            "execution_type": "read_only",
            "permissions": ["tools:invoke", "tenant:admin"],
        },
    ).json()["id"]
    c.put(f"/api/v1/agent-configs/{cfg}/tools/{restricted}", headers=a, json={"enabled": True})
    assert (
        direct(c, member, cfg, cid, restricted, {"text": "ok"}).json()["error_category"]
        == "tool_not_authorized"
    )

    class DropMembership:
        def run(self, capability, arguments, context):
            result = ProcessToolRunner().run(capability, arguments, context)
            own = next(
                m
                for m in c.get("/api/v1/memberships", headers=a).json()
                if m["user_id"] == users[2]["id"]
            )
            c.patch("/api/v1/memberships/" + own["id"], headers=a, json={"status": "inactive"})
            return result

    app.state.tool_runner = DropMembership()
    denied = direct(c, member, cfg, cid, tid, {"text": "sensitive"})
    assert denied.status_code == 403
    calls = c.get("/api/v1/model-calls", headers=a).json()
    assert calls[-1]["status"] == "failed" and calls[-1]["error_category"] == "access_revoked"
    row = c.get("/api/v1/tool-executions", headers=a).json()[-1]
    assert (
        row["status"] == "succeeded"
        and row["data"] is None
        and row["delivery_error"] == "access_revoked"
    )


def test_derived_history_remains_bound_to_original_tool_grants(platform):
    from support_agent.providers import Completion, ModelToolCall

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, cid, tid, _ = setup(c, a)

    class HistoryAware:
        n = 0
        revoke = False

        def complete(self, **kwargs):
            self.n += 1
            if self.revoke:
                c.put(
                    f"/api/v1/agent-configs/{cfg}/tools/{tid}", headers=a, json={"enabled": False}
                )
            if self.n == 1:
                return Completion(
                    "",
                    tool_calls=(
                        ModelToolCall("history_source", "text_metrics", '{"text":"hello"}'),
                    ),
                )
            if self.n == 3:
                assert any(
                    m["role"] == "assistant" and m.get("content") == "Private derived result."
                    for m in kwargs["messages"]
                )
            return Completion("Private derived result.")

    app.state.provider = HistoryAware()
    assert turn(c, a, cfg, cid).json()["status"] == "answered"
    key = str(uuid4())
    derived = turn(c, a, cfg, cid, key).json()
    assert derived["status"] == "answered" and derived["executions"] == []
    app.state.provider.revoke = True
    assert turn(c, a, cfg, cid).status_code == 409
    call = c.get("/api/v1/model-calls", headers=a).json()[-1]
    assert call["status"] == "failed" and call["error_category"] == "tool_not_authorized"
    assert turn(c, a, cfg, cid, key).status_code == 409
    history = c.get(f"/api/v1/conversations/{cid}/messages", headers=a).json()
    assert not any("Private derived result." in m["content"] for m in history)


def test_provider_sends_native_tools_and_validates_response(monkeypatch):
    import httpcore
    import pytest

    from support_agent import providers

    sent = []

    class Stream(httpcore.MockStream):
        def write(self, buffer, timeout=None):
            sent.append(buffer)
            super().write(buffer, timeout)

    response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "wire_1",
                                "type": "function",
                                "function": {"name": "text_metrics", "arguments": '{"text":"ok"}'},
                            }
                        ],
                    },
                }
            ]
        }
    ).encode()

    class Backend(httpcore.MockBackend):
        def connect_tcp(self, *args, **kwargs):
            return Stream(
                [
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(response)).encode()
                    + b"\r\n\r\n"
                    + response
                ]
            )

    monkeypatch.setattr(providers, "PublicNetworkBackend", lambda: Backend([]))
    tools = [{"type": "function", "function": {"name": "text_metrics", "parameters": PARAMETERS}}]
    completion = providers.OpenAICompatibleProvider(["api.example.com"]).complete_in_process(
        base_url="https://api.example.com/v1",
        api_key="synthetic-wire-secret",
        model="model",
        messages=[{"role": "user", "content": "count"}],
        tools=tools,
        runtime={"timeout_seconds": 2, "temperature": 0, "max_output_tokens": 32},
    )
    assert completion.tool_calls[0].id == "wire_1"
    payload = json.loads(b"".join(sent).split(b"\r\n\r\n", 1)[1])
    assert payload["tools"] == tools and payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is False and "response_format" not in payload
    bad = json.loads(response)
    bad["choices"][0]["message"]["tool_calls"] *= 2
    with pytest.raises(providers.ProviderFailure) as failure:
        providers.parse_completion(json.dumps(bad).encode(), 1, allow_tools=True)
    assert failure.value.category == "invalid_response"


def test_sse_reuses_turn_idempotency_and_never_delivers_failed_text(platform):
    import json

    from support_agent.providers import Completion, ProviderFailure

    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    cfg, _, _ = config(c, a)
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]
    payload = {"agent_config_id": cfg, "content": "hello", "idempotency_key": str(uuid4())}

    class Provider:
        count = 0

        def complete(self, **kwargs):
            self.count += 1
            return Completion("可核对的客服答复" * 20, 12, 8)

    provider = Provider()
    app.state.provider = provider
    endpoint = f"/api/v1/conversations/{cid}/agent-turns/stream"
    r = c.post(endpoint, headers=a, json=payload)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [
        (part.splitlines()[0][7:], json.loads(part.splitlines()[1][6:]))
        for part in r.text.strip().split("\n\n")
        if part.startswith("event:")
    ]
    assert frames[0][0] == "stage"
    result = next(data for event, data in frames if event == "completed")
    assert "".join(data["text"] for event, data in frames if event == "delta") == result["answer"]
    assert result["status"] == "answered"
    assert c.post(endpoint, headers=a, json=payload).status_code == 200
    assert provider.count == 1
    assert (
        c.post(f"/api/v1/conversations/{cid}/agent-turns", headers=a, json=payload).json()[
            "call_id"
        ]
        == result["call_id"]
    )

    class Timeout:
        def complete(self, **kwargs):
            raise ProviderFailure("timeout", attempts=None)

    app.state.provider = Timeout()
    payload["idempotency_key"] = str(uuid4())
    r = c.post(endpoint, headers=a, json=payload)
    assert "event: timed_out" in r.text and "event: delta" not in r.text
    assert c.get(f"/api/v1/conversations/{cid}/messages", headers=a).json()[-1]["role"] == "user"
