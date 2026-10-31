"""Three document-ranking probes; no Oracle answer/tool/error simulation matrix."""

import hashlib
import json
import os
import time
from pathlib import Path

from phase2_support import kb, upload

from support_agent.evaluation import ranking_metrics, summarize


def test_offline_retrieval_quality_set(platform):
    c, app, _, _, hs, _, _ = platform
    a = hs[0]
    source = Path(__file__).parent / "fixtures/customer_quality.json"
    dataset = json.loads(source.read_text())
    report = {
        "mode": "offline_retrieval",
        "real_model_verified": False,
        "answer_quality": "not_evaluated",
        "dataset_version": dataset["version"],
        "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "config_version": "retrieval-only-v3",
        "prompt_version": "none-no-model",
        "retrieval_version": type(app.state.retriever).__name__,
        "cases": [],
    }
    # One Chinese synonym, one English synonym and one mixed-language ranking check.
    # Other scenarios remain manual prompts, not hidden runtime tests.
    for case in (row for row in dataset["cases"] if row["id"] in {"Q02", "Q17", "Q18"}):
        kid = kb(c, a, case["id"])
        ids = []
        for n, content in enumerate(case["documents"]):
            doc = upload(c, a, kid, f"source-{n}.txt", content.encode()).json()
            assert doc["status"] == "ready"
            ids.append(doc["id"])
        started = time.monotonic()
        response = c.post(
            f"/api/v1/knowledge-bases/{kid}/search", headers=a, json={"query": case["question"]}
        )
        assert response.status_code == 200, response.text
        ranked = [str(ids.index(hit["document_id"])) for hit in response.json()]
        metrics = ranking_metrics(ranked, case["relevance"], k=6)
        assert metrics["recall_at_k"] == 1, case["id"]
        report["cases"].append(
            {
                "id": case["id"],
                "kind": "retrieval",
                "retrieval": metrics,
                "ranked_documents": ranked,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "real_answer_correctness": "not_evaluated",
            }
        )
    report["metrics"] = summarize(report["cases"])
    target = os.environ.get("P4_EVAL_REPORT")
    if target:
        with open(target, "x") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
