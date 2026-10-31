"""Sixteen non-industry scenarios. Oracle responses test mechanics, never real-model quality."""

import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from phase2_support import config, kb, private_settings, upload  # noqa: F401
from sqlalchemy import text

from support_agent.evaluation import ranking_metrics, summarize
from support_agent.providers import Completion, ModelToolCall, ProviderFailure
from support_agent.tool_runtime import TEXT_OUTPUT, TEXT_PARAMETERS


def test_offline_customer_quality_set(platform):
    c, app, _, tenants, hs, _, _ = platform
    a, b = hs
    cfg, cred, _ = config(c, a)
    tool = c.post(
        "/api/v1/tools",
        headers=a,
        json={
            "key": "text_metrics",
            "name": "文本统计",
            "description": "无副作用统计",
            "parameters": TEXT_PARAMETERS,
            "output_schema": TEXT_OUTPUT,
            "execution_type": "read_only",
        },
    ).json()["id"]
    c.put(f"/api/v1/agent-configs/{cfg}/tools/{tool}", headers=a, json={"enabled": True})
    dataset = json.loads((Path(__file__).parent / "fixtures/customer_quality.json").read_text())
    report = {
        "mode": "offline_mock",
        "real_model_verified": False,
        "answer_quality": "not_evaluated",
        "dataset_version": dataset["version"],
        "dataset_sha256": hashlib.sha256(
            (Path(__file__).parent / "fixtures/customer_quality.json").read_bytes()
        ).hexdigest(),
        "config_version": "offline-oracle-v2",
        "prompt_version": "extract-only-v1",
        "retrieval_version": type(app.state.retriever).__name__,
        "cases": [],
    }
    for case in dataset["cases"]:
        cid = c.post("/api/v1/conversations", headers=a, json={}).json()["id"]
        kid = kb(c, a, case["id"])
        ids = []
        for n, content in enumerate(case.get("documents", [])):
            if case["kind"] == "long":
                content = "通用帮助说明。" * 500 + content
            doc = upload(c, a, kid, f"{case['id']}-{n}.txt", content.encode()).json()
            assert doc["status"] == "ready"
            ids.append(doc["id"])
        if case["kind"] == "removed":
            c.delete("/api/v1/documents/" + ids[0], headers=a)
        search = c.post(
            f"/api/v1/knowledge-bases/{kid}/search", headers=a, json={"query": case["question"]}
        ).json()
        ranked = [str(ids.index(hit["document_id"])) for hit in search]
        retrieval = ranking_metrics(ranked, case["relevance"], k=6)
        if case["kind"] == "retrieval":
            assert retrieval["recall_at_k"] == 1, case["id"]
            report["cases"].append(
                {
                    "id": case["id"],
                    "kind": case["kind"],
                    "retrieval": retrieval,
                    "ranked_documents": ranked,
                    "semantic_correctness": "manual_required",
                }
            )
            continue
        with app.state.sessions() as db:
            db.execute(
                text("SELECT set_config('app.tenant_id',:id,true)"), {"id": tenants[0]["id"]}
            )
            baseline = db.scalar(
                text("""SELECT count(*) FROM document_chunks c JOIN documents d
                ON d.id=c.document_id AND d.tenant_id=c.tenant_id
                WHERE d.knowledge_base_id=:kb AND d.status='ready'
                AND c.search_vector @@ plainto_tsquery('simple',:query)"""),
                {"kb": kid, "query": case["question"]},
            )

        class Oracle:
            n = 0

            def complete(self, case=case, **kwargs):
                self.n += 1
                if case["kind"] == "timeout":
                    raise ProviderFailure("timeout", attempts=None)
                if case["kind"] in {"tool", "unauthorized"}:
                    count = case.get("tool_steps", 1)
                    if self.n <= count:
                        name = "text_metrics" if case["kind"] == "tool" else "write_everything"
                        return Completion(
                            "",
                            10,
                            3,
                            tool_calls=(
                                ModelToolCall(
                                    "quality_" + str(self.n),
                                    name,
                                    json.dumps({"text": "hello world"})
                                    if name == "text_metrics"
                                    else "{}",
                                ),
                            ),
                        )
                    return Completion("工具调用已结束，请核实执行状态。", 8, 3)
                evidence = json.loads(kwargs["messages"][-1]["content"])["evidence"]
                quotes = case.get("quotes", [case.get("quote", "")])
                selected = [
                    {"chunk_id": hit["chunk_id"], "quote": quote}
                    for quote in quotes
                    if quote
                    for hit in evidence
                    if quote in hit["content"]
                ][:3]
                return Completion(
                    json.dumps({"answerable": bool(selected), "citations": selected}), 12, 5
                )

        app.state.provider = Oracle()
        if case["kind"] == "credential":
            c.delete("/api/v1/model-credentials/" + cred, headers=a)
        started = time.monotonic()
        if case["kind"] in {"tool", "unauthorized", "tenant_isolation"}:
            headers = b if case["kind"] == "tenant_isolation" else a
            response = c.post(
                f"/api/v1/conversations/{cid}/agent-turns",
                headers=headers,
                json={
                    "agent_config_id": cfg,
                    "content": case["question"],
                    "idempotency_key": str(uuid4()),
                },
            )
        else:

            def ask(question, cid=cid, kid=kid):
                return c.post(
                    f"/api/v1/conversations/{cid}/chat",
                    headers=a,
                    json={
                        "agent_config_id": cfg,
                        "knowledge_base_ids": [kid],
                        "content": question,
                        "idempotency_key": str(uuid4()),
                    },
                )

            response = ask(case["question"])
            if case["kind"] == "followup":
                assert response.json()["status"] == "answered"
                response = ask(case["followup"])
        value = response.json()
        if case["kind"] == "tenant_isolation":
            assert response.status_code == 404
        else:
            assert response.status_code == 200, (case["id"], value)
            expected = (
                "failed"
                if case["kind"] in {"timeout", "credential"}
                else "unresolved"
                if case["kind"] in {"unknown", "conflict", "removed", "injection"}
                else "answered"
            )
            assert value["status"] == expected, (case["id"], value)
            if case["kind"] == "tool":
                assert len(value["executions"]) == case["tool_steps"]
                assert all(e["status"] == "succeeded" for e in value["executions"])
            if case["kind"] == "unauthorized":
                assert value["executions"][0]["status"] == "denied"
            if case["kind"] == "multi_source":
                assert len({item["document_id"] for item in value["citations"]}) == 2
        call = (
            c.get("/api/v1/model-calls/" + value["call_id"], headers=a).json()
            if "call_id" in value
            else {}
        )
        report["cases"].append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "status": value.get("status"),
                "retrieval": retrieval,
                "ranked_documents": ranked,
                "source_valid": all(
                    item["document_id"] in ids
                    and any(item["chunk_id"] == h["chunk_id"] for h in search)
                    for item in value.get("citations", [])
                )
                if value.get("citations")
                else None,
                "quote_matches": all(
                    any(item["quote"] in doc for doc in case.get("documents", []))
                    for item in value.get("citations", [])
                )
                if value.get("citations")
                else None,
                "correct_refusal": value.get("status") == "unresolved"
                if case["kind"] in {"unknown", "conflict", "removed", "injection"}
                else None,
                "tool_success": all(e["status"] == "succeeded" for e in value.get("executions", []))
                if case["kind"] == "tool"
                else None,
                "unauthorized_denied": value["executions"][0]["status"] == "denied"
                if case["kind"] == "unauthorized"
                else None,
                "mechanical_checks": "passed",
                "provider": "offline-mock",
                "models": [s["model"] for s in call.get("steps", [])],
                "baseline_retrieval_hit": bool(baseline),
                "improved_retrieval_hit": bool(search),
                "input_tokens": call.get("input_tokens"),
                "output_tokens": call.get("output_tokens"),
                "usage_complete": call.get("usage_complete"),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "tool_call_count": len(value.get("executions", [])),
                "sources": value.get("citations", []),
                "failure_reason": value.get("error_category") or value.get("error", {}).get("code"),
                "real_answer_correctness": "not_evaluated",
            }
        )
    report["metrics"] = summarize(report["cases"])
    target = os.environ.get("P4_EVAL_REPORT")
    if target:
        with open(target, "x") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)


def test_rank_metrics_use_relevance_and_do_not_claim_semantic_accuracy():
    from support_agent.evaluation import ranking_metrics

    result = ranking_metrics(["noise", "a", "a", "b"], {"a": 2, "b": 1}, k=3)
    assert result["recall_at_k"] == 1
    assert result["mrr"] == 0.5
    assert 0 < result["ndcg_at_k"] < 1
    assert ranking_metrics([], {}, k=3)["recall_at_k"] is None
