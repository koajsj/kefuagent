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
        for name in ("recall_at_k", "mrr", "ndcg_at_k")
    }
    for name in (
        "source_valid",
        "quote_matches",
        "correct_refusal",
        "tool_success",
        "unauthorized_denied",
    ):
        metrics[name + "_rate"] = average(c.get(name) for c in cases)
    executed = [c for c in cases if c.get("status") is not None]
    metrics["failure_rate"] = average(c["status"] == "failed" for c in executed)
    metrics["mean_latency_ms"] = average(c.get("elapsed_ms") for c in executed)
    metrics["input_tokens"] = sum(c.get("input_tokens") or 0 for c in executed)
    metrics["output_tokens"] = sum(c.get("output_tokens") or 0 for c in executed)
    metrics["unknown_usage_cases"] = sum(c.get("input_tokens") is None for c in executed)
    return metrics


def markdown(report, previous=None):
    lines = [
        "# 离线客服质量评测",
        "",
        f"数据集：{report['dataset_version']}；Provider：offline-mock；模型：Oracle（非真实模型）。",
        f"配置：{report['config_version']}；Prompt：{report['prompt_version']}。",
        "",
        "仅验证确定性协议、召回和引用机制；语义正确性、真实模型及任意提示注入抵御：NOT_EVALUATED。",
        "",
        "| 指标 | 当前值 | 较前次变化 |",
        "| --- | --- | --- |",
    ]
    comparable = previous and all(
        previous.get(key) == report.get(key)
        for key in ("dataset_version", "dataset_sha256", "config_version", "prompt_version")
    )
    for key, value in report["metrics"].items():
        old = previous.get("metrics", {}).get(key) if comparable else None
        delta = (
            round(value - old, 6)
            if isinstance(value, (float, int)) and isinstance(old, (float, int))
            else "N/A"
        )
        lines.append(f"| {key} | {value if value is not None else 'N/A'} | {delta} |")
    lines += [
        "",
        "不同数据集/配置/Prompt 不计算差值。",
        "",
        "| 场景 | 状态 | Recall@K / MRR / nDCG@K | 输入 / 输出 Token | 延迟 ms | 工具次数 | 引用数 | 失败原因 | 未评估 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        metric = case.get("retrieval", {})
        lines.append(
            f"| {case['id']} | {case.get('status', 'retrieval_only')} | "
            f"{metric.get('recall_at_k')} / {metric.get('mrr')} / {metric.get('ndcg_at_k')} | "
            f"{case.get('input_tokens')} / {case.get('output_tokens')} | {case.get('elapsed_ms')} | "
            f"{case.get('tool_call_count')} | {len(case.get('sources', []))} | "
            f"{case.get('failure_reason') or '-'} | 语义正确性需人工 |"
        )
    return "\n".join(lines) + "\n"
