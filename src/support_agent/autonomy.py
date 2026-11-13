"""Deterministic deployment policy. Model text and database risk labels cannot grant authority."""

from dataclasses import dataclass

MAX_MODEL_STEPS = 5
POLICY_VERSION = "private-autonomy-v1"
RISK_NAMES = {0: "信息回答", 1: "检索与只读查询", 2: "可逆业务操作", 3: "需人工审批", 4: "禁止操作"}


@dataclass(frozen=True)
class Decision:
    risk: int
    allowed: bool
    reason: str


def decide(tool, capability, *, ceiling=1, public=False, approved=False):
    if capability is None:
        return Decision(4, False, "tool_not_bound")
    minimum = capability.risk
    declared = {"low": 1, "medium": 2, "high": 3}.get(tool.risk_level, 4)
    risk = max(minimum, declared)
    if minimum == 0 and tool.risk_level == "low":
        risk = 0
    if risk >= 4:
        return Decision(4, False, "policy_forbidden")
    if risk == 3:
        if approved and not public and ceiling >= 2:
            return Decision(3, True, "independent_approval")
        return Decision(3, False, "approval_required")
    if public and not capability.read_only:
        return Decision(risk, False, "public_tool_denied")
    if risk > ceiling:
        return Decision(risk, False, "autonomy_limit_exceeded")
    return Decision(risk, True, "policy_allowed")


def plan(content, *, knowledge=False):
    """Explicit lexical routing, not a semantic classifier or model reasoning transcript."""
    handoff = any(term in content for term in ("人工客服", "转人工", "human agent"))
    complex_task = len(content) > 800 or any(
        term in content for term in ("比较", "分析", "结合", "多步")
    )
    return {
        "policy_version": POLICY_VERSION,
        "intent": "human_handoff_requested" if handoff else "support_request",
        "classification_method": "deterministic_lexical_heuristic",
        "semantic_certainty": "UNKNOWN",
        "complexity": "multi_step_candidate" if complex_task else "standard_candidate",
        "retrieval_decision": "authorized_knowledge_available"
        if knowledge
        else "no_selected_knowledge",
        "stages": [
            "context",
            "memory",
            *(["retrieval"] if knowledge else []),
            "model",
            "authorized_tools_if_requested",
            "verify",
            "deliver",
        ],
        "limits": {"model_steps": MAX_MODEL_STEPS, "tool_calls": 4, "seconds": 120},
    }
