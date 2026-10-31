"""Small API data helpers shared by the retained boundary checks."""

from uuid import uuid4


def kb(c, headers, name="General"):
    r = c.post("/api/v1/knowledge-bases", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(c, headers, kid, filename, content):
    return c.post(
        f"/api/v1/knowledge-bases/{kid}/documents",
        headers=headers,
        files={"file": (filename, content, "application/octet-stream")},
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
