"""Offline mechanical metrics. Semantic correctness always requires a human reviewer."""

import math
from statistics import mean


def ranking_metrics(ranked, relevance, k=6):
    ranked = list(dict.fromkeys(ranked))[:k]
    relevant = {item for item, grade in relevance.items() if grade > 0}
    if not relevant:
        return dict(recall_at_k=None, mrr=None, ndcg_at_k=None)
    dcg = sum((2 ** relevance.get(item, 0) - 1) / math.log2(i + 2) for i, item in enumerate(ranked))
    ideal = sum(
        (2**grade - 1) / math.log2(i + 2)
        for i, grade in enumerate(sorted(relevance.values(), reverse=True)[:k])
    )
    return {
        "unjudged_or_irrelevant_fraction_at_k": (
            sum(item not in relevant for item in ranked) / len(ranked) if ranked else None
        ),
        "recall_at_k": len(set(ranked) & relevant) / len(relevant),
        "mrr": next((1 / (i + 1) for i, item in enumerate(ranked) if item in relevant), 0),
        "ndcg_at_k": dcg / ideal if ideal else 0,
    }


def summarize(cases):
    def average(values):
        values = [v for v in values if v is not None]
        return round(mean(values), 6) if values else None

    metrics = {
        name: average(c.get("retrieval", {}).get(name) for c in cases)
        for name in ("recall_at_k", "mrr", "ndcg_at_k", "unjudged_or_irrelevant_fraction_at_k")
    }
    metrics["mean_latency_ms"] = average(c.get("elapsed_ms") for c in cases)
    return metrics


def markdown(report, previous=None):
    fixture = report["mode"] == "fixture_lexical_diagnostic"
    lines = [
        "# 离线客服质量评测",
        "",
        f"数据集：{report['dataset_version']}；模式：{report['mode']}；非真实模型评测。",
        f"配置：{report['config_version']}；Prompt：{report['prompt_version']}。",
        "",
        (
            "仅检查虚构文本的词面覆盖；不是 PostgreSQL 召回/排名，也不是 AI 回答质量。"
            if fixture
            else "仅评测文档召回与排名；未标注候选计入非相关/未知比例，不代表已人工判定无关。"
        ),
        "回答、引用语义、工具、Token 用量与真实模型：NOT_RUN。",
        "",
        "| 指标 | 当前值 | 较前次变化 |",
        "| --- | --- | --- |",
    ]
    comparable = previous and all(
        previous.get(key) == report.get(key)
        for key in (
            "mode",
            "dataset_version",
            "dataset_sha256",
            "config_version",
            "prompt_version",
            "scope_sha256",
        )
    )
    for key, value in report["metrics"].items():
        old = previous.get("metrics", {}).get(key) if comparable else None
        delta = (
            round(value - old, 6)
            if isinstance(value, (float, int)) and isinstance(old, (float, int))
            else "N/A"
        )
        lines.append(f"| {key} | {value if value is not None else 'N/A'} | {delta} |")
    if fixture:
        lines += [
            "",
            "| 场景 | 可构造检索词 | 各文档词面覆盖 | SQL / 回答 / Agent |",
            "| --- | --- | --- | --- |",
        ]
        for case in report["cases"]:
            lines.append(
                f"| {case['id']} | {case['searchable']} | "
                f"{case['document_lexical_coverage']} | NOT_RUN |"
            )
        return "\n".join(lines) + "\n"
    lines += [
        "",
        "不同数据集/配置/Prompt 不计算差值。",
        "",
        "| 场景 | Recall@K / MRR / nDCG@K | 延迟 ms | 未评估 |",
        "| --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        metric = case.get("retrieval", {})
        lines.append(
            f"| {case['id']} | "
            f"{metric.get('recall_at_k')} / {metric.get('mrr')} / {metric.get('ndcg_at_k')} | "
            f"{case.get('elapsed_ms')} | 回答质量需人工 |"
        )
    return "\n".join(lines) + "\n"


def lexical_baseline(dataset):
    """Fixture-only coverage diagnostic. No PostgreSQL candidate ranking or model is evaluated."""
    from support_agent.search_text import coverage, latin_expression, query_expression, query_groups

    cases = []
    positive, hits = 0, 0
    for case in dataset["cases"]:
        groups = query_groups(case["question"])
        searchable = bool(query_expression(groups) or latin_expression(groups))
        docs = case.get("documents", [])
        scores = [coverage(content, groups) for content in docs]
        relevant = case.get("relevance", {})
        labels = [int(label) for label, grade in relevant.items() if grade > 0]
        if any(index < 0 or index >= len(docs) for index in labels):
            raise ValueError("Relevance annotation outside fixture documents")
        positive += len(labels)
        hits += sum(searchable and scores[index] >= 0.4 for index in labels)
        cases.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "searchable": searchable,
                "document_lexical_coverage": scores,
                "postgres_ranking": "NOT_RUN",
                "answer_quality": "NOT_RUN",
                "agent_behavior": "NOT_RUN",
            }
        )
    return {
        "mode": "fixture_lexical_diagnostic",
        "dataset_version": dataset["version"],
        "config_version": "fixture-coverage-threshold-0.4-v1",
        "prompt_version": "none-no-model",
        "real_model_verified": False,
        "metrics": {
            "annotated_positive_documents": positive,
            "lexically_eligible_positive_documents": hits,
            "positive_lexical_eligibility_ratio": hits / positive if positive else None,
        },
        "limitations": "Literal fixture coverage only; not Recall@K/MRR/nDCG, SQL ranking, latency, answer correctness, tool execution or token usage.",
        "cases": cases,
    }
