"""Read-only retrieval evaluation on operator-selected documents; never invokes a model."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from support_agent.config import Settings
from support_agent.db import build_database, check_database, set_tenant
from support_agent.errors import AppError, forbidden
from support_agent.evaluation import markdown, ranking_metrics, summarize
from support_agent.models import Document, Membership, Tenant, User
from support_agent.retrieval import PostgresFTSRetriever
from support_agent.tool_protocol import ExecutionContext


def evaluate(settings, tenant_id, user_id, dataset, manifest):
    selected = {case["id"]: case for case in dataset["cases"]}
    if not manifest or set(manifest) - selected.keys():
        raise ValueError("Manifest requires known dataset case IDs")
    report = {
        "mode": "offline_retrieval",
        "real_model_verified": False,
        "answer_quality": "not_evaluated",
        "dataset_version": dataset["version"],
        "config_version": "read-only-manifest-v1",
        "prompt_version": "none-no-model",
        "retrieval_version": "PostgresFTSRetriever",
        "cases": [],
    }
    engine, sessions = build_database(settings)
    try:
        check_database(engine)
        for case_id, mapping in manifest.items():
            case = selected[case_id]
            if not case.get("relevance"):
                raise ValueError(f"No relevance annotations for {case_id}; use manual evaluation")
            kids = [UUID(value) for value in mapping["knowledge_base_ids"]]
            docs = {str(index): UUID(value) for index, value in mapping["documents"].items()}
            if not 1 <= len(kids) <= 20 or not 1 <= len(docs) <= 100:
                raise ValueError("Each case requires 1–20 knowledge bases and 1–100 documents")
            if not set(case["relevance"]) <= docs.keys() or len(set(docs.values())) != len(docs):
                raise ValueError("Document mapping must uniquely cover the annotated relevance IDs")
            with sessions.begin() as db:
                db.execute(text("SET TRANSACTION READ ONLY"))
                membership = db.scalar(
                    select(Membership)
                    .join(Tenant, Tenant.id == Membership.tenant_id)
                    .join(User, User.id == Membership.user_id)
                    .where(
                        Membership.tenant_id == tenant_id,
                        Membership.user_id == user_id,
                        Membership.status == "active",
                        Tenant.status == "active",
                        User.status == "active",
                    )
                )
                if membership is None:
                    raise forbidden()
                set_tenant(db, tenant_id)
                context = ExecutionContext(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    membership_id=membership.id,
                    role=membership.role,
                    request_id=uuid4(),
                )
                visible = set(
                    db.scalars(
                        select(Document.id).where(
                            Document.tenant_id == tenant_id,
                            Document.id.in_(docs.values()),
                            Document.knowledge_base_id.in_(kids),
                            Document.status == "ready",
                        )
                    )
                )
                if visible != set(docs.values()):
                    raise ValueError(
                        "Mapped documents must be ready and belong to the selected scope"
                    )
                started = time.monotonic()
                hits = PostgresFTSRetriever().search(db, context, kids, case["question"])
                elapsed = (time.monotonic() - started) * 1000
                labels = {value: key for key, value in docs.items()}
                # Unlabelled candidates retain their rank and count as non-relevant.
                ranked = [labels.get(hit.document_id, str(hit.document_id)) for hit in hits]
                report["cases"].append(
                    {
                        "id": case_id,
                        "kind": "retrieval",
                        "retrieval": ranking_metrics(ranked, case["relevance"], k=6),
                        "ranked_documents": ranked,
                        "elapsed_ms": round(elapsed, 3),
                        "real_answer_correctness": "not_evaluated",
                    }
                )
    finally:
        engine.dispose()
    report["metrics"] = summarize(report["cases"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument(
        "--user-id", type=UUID, required=True, help="Existing active member; operator CLI"
    )
    parser.add_argument(
        "--manifest", type=Path, required=True, help="Case IDs mapped to existing KB/docs"
    )
    parser.add_argument("--dataset", type=Path, default=Path("data/customer_quality.json"))
    parser.add_argument("--compare", type=Path, help="Compare reports from identical dataset/scope")
    parser.add_argument("--output", type=Path, default=Path(".local/evaluations"))
    args = parser.parse_args()
    dataset_bytes = args.dataset.read_bytes()
    manifest = json.loads(args.manifest.read_text())
    try:
        report = evaluate(
            Settings(), args.tenant_id, args.user_id, json.loads(dataset_bytes), manifest
        )
    except AppError as exc:
        raise SystemExit(f"Evaluation refused: {exc.code}") from None
    except (SQLAlchemyError, RuntimeError):
        raise SystemExit("Database unavailable, unsafe role or pending migration") from None
    except (ValueError, KeyError, TypeError):
        raise SystemExit("Invalid dataset/manifest or unavailable document scope") from None
    report["dataset_sha256"] = hashlib.sha256(dataset_bytes).hexdigest()
    report["scope_sha256"] = hashlib.sha256(
        json.dumps([str(args.tenant_id), manifest], sort_keys=True).encode()
    ).hexdigest()
    previous = json.loads(args.compare.read_text()) if args.compare else None
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / f"quality-offline-{uuid4().hex}.json"
    with target.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    with target.with_suffix(".md").open("x") as stream:
        stream.write(markdown(report, previous))
    print("Offline retrieval report:", target.resolve())
    print("Real model and semantic answer quality: NOT_EVALUATED")


if __name__ == "__main__":
    main()
