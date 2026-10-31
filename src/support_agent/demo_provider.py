"""Deterministic local demonstration, never a substitute for real model acceptance."""

import hashlib
import json

from support_agent.providers import Completion, ModelToolCall


class DemoProvider:
    def complete(self, *, messages, tools=None, **kwargs):
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        try:
            payload = json.loads(user)
        except (ValueError, TypeError):
            payload = {}
        if "Compress conversation USER DATA" in messages[0]["content"]:
            return Completion(
                json.dumps(
                    {
                        "items": [
                            {
                                "message_id": row["message_id"],
                                "quote": row["content"][:150],
                                "kind": "request",
                            }
                            for row in payload.get("messages", [])[-8:]
                            if row["content"]
                        ]
                    },
                    ensure_ascii=False,
                ),
                0,
                0,
                0,
            )
        question = payload.get("question", "")
        if tools is not None and messages[-1]["role"] != "tool" and "统计" in question:
            if any(t["function"]["name"] == "text_metrics" for t in tools):
                return Completion(
                    "",
                    0,
                    0,
                    0,
                    tool_calls=(
                        ModelToolCall(
                            "demo_" + hashlib.sha256(question.encode()).hexdigest()[:24],
                            "text_metrics",
                            json.dumps({"text": question.removeprefix("统计").strip() or question}),
                        ),
                    ),
                )
        if tools is None or payload.get("knowledge_enabled"):
            evidence = payload.get("evidence", [])
            return Completion(
                json.dumps(
                    {
                        "answerable": bool(evidence),
                        "citations": [
                            {"chunk_id": hit["chunk_id"], "quote": hit["content"][:600]}
                            for hit in evidence[:1]
                            if len(hit["content"]) >= 8
                        ],
                    },
                    ensure_ascii=False,
                ),
                0,
                0,
                0,
            )
        if messages[-1]["role"] == "tool":
            content = "离线演示：只读工具已返回结果，请查看工具执行记录。"
        else:
            content = "离线演示：我可以演示知识原文检索和已授权的文本统计。当前没有连接真实模型，无法进行真实语义推理。"
        return Completion(content, 0, 0, 0)
