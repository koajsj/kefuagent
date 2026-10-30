"""Synthetic credentials and bounded data for stage-two PostgreSQL acceptance."""

import base64
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def private_settings(monkeypatch, tmp_path):
    import os

    monkeypatch.setenv("CREDENTIAL_MASTER_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DOCUMENT_STORAGE_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("MODEL_ALLOWED_HOSTS", '["api.example.com"]')


def kb(c, headers, name="General"):
    r = c.post("/api/v1/knowledge-bases", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(c, headers, kid, filename, content, mime="application/octet-stream"):
    return c.post(
        f"/api/v1/knowledge-bases/{kid}/documents",
        headers=headers,
        files={"file": (filename, content, mime)},
    )


def config(c, headers):
    secret = "synthetic-not-a-provider-key-" + uuid4().hex
    cr = c.post(
        "/api/v1/model-credentials", headers=headers, json={"ref": "cred_main", "api_key": secret}
    )
    assert cr.status_code == 201, cr.text
    assert secret not in cr.text and "ciphertext" not in cr.text
    r = c.post(
        "/api/v1/agent-configs",
        headers=headers,
        json={
            "name": "RAG",
            "provider": "openai_compatible",
            "model": "acceptance-model",
            "base_url": "https://api.example.com/v1",
            "credential_ref": "cred_main",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], cr.json()["id"], secret
