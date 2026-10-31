"""Actual persistence/parsers and controlled provider boundaries; no paid calls."""

import json

import pytest
from phase2_support import (
    config,
)


def test_http_transport_errors_retries_and_response_validation(monkeypatch, caplog):
    import httpcore

    from support_agent import providers

    assert hasattr(providers.OpenAICompatibleProvider, "complete_in_process"), (
        "HTTP worker boundary missing"
    )
    secret = "synthetic-transport-secret"
    args = {
        "base_url": "https://api.example.com/v1",
        "api_key": secret,
        "model": "acceptance-model",
        "messages": [{"role": "user", "content": "JSON please"}],
        "runtime": {"temperature": 0, "max_output_tokens": 32, "timeout_seconds": 2},
    }
    adapter = providers.OpenAICompatibleProvider(["api.example.com"])
    caplog.set_level("DEBUG")

    def backend(status, body):
        reply = (
            f"HTTP/1.1 {status} Response\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        instance = httpcore.MockBackend([reply])
        monkeypatch.setattr(providers, "PublicNetworkBackend", lambda: instance)

    for status, category, attempts in [
        (401, "authentication_failed", 1),
        (503, "provider_unavailable", 2),
    ]:
        backend(status, b"Never show this: " + secret.encode())
        with pytest.raises(providers.ProviderFailure) as failure:
            adapter.complete_in_process(**args)
        assert failure.value.category == category and failure.value.attempts == attempts
    for body in [
        b"not JSON",
    ]:
        backend(200, body)
        with pytest.raises(providers.ProviderFailure) as failure:
            adapter.complete_in_process(**args)
        assert failure.value.category == "invalid_response"
    truncated = json.dumps(
        {
            "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        }
    ).encode()
    backend(200, truncated)
    with pytest.raises(providers.ProviderFailure) as failure:
        adapter.complete_in_process(**args)
    assert failure.value.input_tokens == 12 and failure.value.output_tokens == 7
    sent = []
    result_body = json.dumps(
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

    class Stream(httpcore.MockStream):
        def write(self, buffer, timeout=None):
            sent.append(buffer)
            super().write(buffer, timeout)

    class Backend(httpcore.MockBackend):
        def connect_tcp(self, *args, **kwargs):
            return Stream(
                [
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(result_body)).encode()
                    + b"\r\n\r\n"
                    + result_body
                ]
            )

    monkeypatch.setattr(providers, "PublicNetworkBackend", lambda: Backend([]))
    tools = [
        {"type": "function", "function": {"name": "text_metrics", "parameters": {"type": "object"}}}
    ]
    result = adapter.complete_in_process(
        **(
            args
            | {
                "base_url": "https://api.example.com/custom/v1",
                "runtime": args["runtime"]
                | {"token_parameter": "max_completion_tokens", "send_temperature": False},
                "tools": tools,
            }
        )
    )
    request_headers, request_body = b"".join(sent).split(b"\r\n\r\n", 1)
    payload = json.loads(request_body)
    assert request_headers.startswith(b"POST /custom/v1/chat/completions HTTP/1.1\r\n")
    assert ("Bearer " + secret).encode() in request_headers
    assert payload["model"] == args["model"] and payload["tools"] == tools
    assert payload["tool_choice"] == "auto" and payload["parallel_tool_calls"] is False
    assert payload["max_completion_tokens"] == 32
    assert (
        "max_tokens" not in payload
        and "temperature" not in payload
        and "response_format" not in payload
    )
    assert result.tool_calls[0].id == "wire_1" and result.tool_calls[0].name == "text_metrics"
    assert result.tool_calls[0].arguments == '{"text":"ok"}'
    assert result.input_tokens is None and result.output_tokens is None
    assert secret not in caplog.text


def test_ssrf_dns_pinning_and_real_worker(monkeypatch):
    import socket

    import httpcore

    from support_agent import providers
    from support_agent.errors import AppError

    for url in [
        "http://api.example.com/v1",
        "https://user:password@api.example.com/v1",
        "https://api.example.com:444/v1",
        "https://127.0.0.1/v1",
        "https://api.example.com/v1?api_key=secret",
        "https://unapproved.example/v1",
    ]:
        with pytest.raises(AppError):
            providers.validate_base_url(url, ["api.example.com"])
    for address in [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ]:
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, ip=address, **k: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 443))],
        )
        with pytest.raises(providers.ProviderFailure) as denied:
            providers.PublicNetworkBackend().connect_tcp("api.example.com", 443)
        assert denied.value.category == "unsafe_endpoint"
    called = []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        httpcore.SyncBackend, "connect_tcp", lambda self, host, *a, **k: called.append(host)
    )
    providers.PublicNetworkBackend().connect_tcp("api.example.com", 443)
    assert called == ["8.8.8.8"]
    # Real isolated worker, real local DNS, no socket connection: loopback is rejected before connect.
    with pytest.raises(providers.ProviderFailure) as denied:
        providers.OpenAICompatibleProvider(["localhost"]).complete(
            base_url="https://localhost/v1",
            api_key="synthetic",
            model="model",
            messages=[],
            runtime={"timeout_seconds": 3, "max_output_tokens": 10, "temperature": 0},
        )
    assert denied.value.category == "unsafe_endpoint"


def test_versioned_rotation_and_retention_are_atomic_tenant_scoped(platform, monkeypatch):
    import base64
    import os
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from uuid import UUID

    from pydantic import SecretStr
    from sqlalchemy import select

    from support_agent.credentials import Keyring
    from support_agent.db import set_tenant
    from support_agent.errors import AppError
    from support_agent.maintenance import rotate_credentials, rotation_plan
    from support_agent.models import AuditEvent, Conversation, Message, ModelCredential
    from support_agent.retention import apply_retention, retention_plan

    c, app, _, tenants, hs, _, _ = platform
    a = hs[0]
    tenant = UUID(tenants[0]["id"])
    _, foreign_id, _ = config(c, hs[1])
    _, credential_id, secret = config(c, a)
    credential_id = UUID(credential_id)
    settings = app.state.settings.model_copy(
        update={
            "credential_keyring": SecretStr(
                json.dumps({"next": base64.urlsafe_b64encode(os.urandom(32)).decode()})
            ),
            "credential_active_key": "next",
        }
    )
    ring = Keyring(settings)
    with app.state.sessions() as db:
        plan = rotation_plan(db, tenant, ring, "next")
        assert plan["counts"] == {"legacy": 1}
        assert secret not in str(plan)

        def fail(*_):
            raise RuntimeError("simulated interrupted transaction")

        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", fail)
            with pytest.raises(RuntimeError):
                rotate_credentials(db, tenant, ring, "next", plan["confirmation"])
        db.rollback()
        set_tenant(db, tenant)
        row = db.get(ModelCredential, credential_id)
        assert ring.version(row.encrypted_secret) == "legacy"
        db.rollback()
        rotate_credentials(db, tenant, ring, "next", plan["confirmation"])
        set_tenant(db, tenant)
        row = db.get(ModelCredential, credential_id)
        assert ring.version(row.encrypted_secret) == "next"
        assert ring.open(tenant, row.ref, row.encrypted_secret) == secret
        with pytest.raises(AppError):
            ring.open(UUID(tenants[1]["id"]), row.ref, row.encrypted_secret)
        with pytest.raises(AppError):
            ring.open(tenant, "cred_wrong", row.encrypted_secret)
        without_new = Keyring(app.state.settings)
        with pytest.raises(AppError):
            without_new.open(tenant, row.ref, row.encrypted_secret)
        set_tenant(db, UUID(tenants[1]["id"]))
        foreign = db.get(ModelCredential, UUID(foreign_id))
        assert ring.version(foreign.encrypted_secret) == "legacy"
        set_tenant(db, tenant)
        assert not rotation_plan(db, tenant, ring, "next")["affected"]
        db.rollback()
        original_settings = app.state.settings
        app.state.settings = settings
        created = c.post(
            "/api/v1/model-credentials",
            headers=a,
            json={"ref": "cred_new", "api_key": "synthetic-new-key"},
        )
        assert created.status_code == 201
        set_tenant(db, tenant)
        current = db.get(ModelCredential, UUID(created.json()["id"]))
        assert ring.version(current.encrypted_secret) == "next"
        assert ring.open(tenant, current.ref, current.encrypted_secret) == "synthetic-new-key"
        app.state.settings = original_settings
        back = rotation_plan(db, tenant, ring, "legacy")
        rotate_credentials(db, tenant, ring, "legacy", back["confirmation"])
        set_tenant(db, tenant)
        row = db.get(ModelCredential, credential_id)
        assert ring.version(row.encrypted_secret) == "legacy"
        db.rollback()

    # New, isolated records only: deletion does not touch existing test data.
    cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]
    c.post(
        f"/api/v1/conversations/{cid}/messages",
        headers=a,
        json={"role": "user", "content": "synthetic private content"},
    )
    c.patch(f"/api/v1/conversations/{cid}", headers=a, json={"status": "closed"})
    cid = UUID(cid)
    with app.state.sessions.begin() as db:
        set_tenant(db, tenant)
        row = db.get(Conversation, cid)
        row.updated_at = datetime.now(UTC) - timedelta(days=40)
        for message in db.scalars(select(Message).where(Message.conversation_id == cid)):
            message.created_at = datetime.now(UTC) - timedelta(days=40)
    policy = SimpleNamespace(
        conversations_days=30, visitors_days=7, calls_days=30, audit_days=None, batch_size=10
    )
    with app.state.sessions() as db:
        preview = retention_plan(db, tenant, policy)
        assert preview["counts"]["conversations"] == 1
        with pytest.raises(ValueError):
            apply_retention(db, tenant, policy, "wrong", app.state.storage)
        db.rollback()
        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", fail)
            with pytest.raises(RuntimeError):
                apply_retention(db, tenant, policy, preview["confirmation"], app.state.storage)
        db.rollback()
        set_tenant(db, tenant)
        assert db.get(Conversation, cid) is not None
        db.rollback()
        apply_retention(db, tenant, policy, preview["confirmation"], app.state.storage)
        set_tenant(db, tenant)
        assert db.get(Conversation, cid) is None
        assert not db.scalar(select(Message.id).where(Message.conversation_id == cid))
        assert db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "retention.execute", AuditEvent.tenant_id == tenant
            )
        )
        assert retention_plan(db, tenant, policy)["counts"]["conversations"] == 0
        assert apply_retention(db, tenant, policy, preview["confirmation"], app.state.storage) == {
            "already_applied": True
        }
