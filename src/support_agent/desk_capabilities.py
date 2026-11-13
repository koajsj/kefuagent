"""Deployment-owned input/output contracts for the service desk tools."""

from support_agent.tool_runtime import EMPTY_PARAMETERS, Capability, conversation_snapshot


def obj(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


TEXT_ID = {"type": "string", "minLength": 36, "maxLength": 36}
TICKET_RESULT = obj(
    {
        "ticket_id": TEXT_ID,
        "ticket_version": {"type": "integer", "minimum": 1},
        "status": {"type": "string"},
    }
)
TICKET_VIEW = obj(
    {
        "id": TEXT_ID,
        "title": {"type": "string", "maxLength": 160},
        "status": {"type": "string"},
        "priority": {"type": "string"},
        "version": {"type": "integer", "minimum": 1},
    }
)
HANDOFF_REASONS = [
    "customer_requested",
    "knowledge_insufficient",
    "tool_failed",
    "policy_requires_review",
    "other",
]


def capabilities():
    return [
        Capability(
            "customer_lookup",
            1,
            EMPTY_PARAMETERS,
            obj(
                {
                    "found": {"type": "boolean"},
                    "customer_id": {"type": "string"},
                    "name": {"type": "string", "maxLength": 120},
                    "version": {"type": "integer", "minimum": 0},
                }
            ),
            conversation_snapshot,
        ),
        Capability(
            "ticket_lookup",
            1,
            EMPTY_PARAMETERS,
            obj({"tickets": {"type": "array", "maxItems": 5, "items": TICKET_VIEW}}),
            conversation_snapshot,
        ),
        Capability(
            "ticket_create",
            1,
            obj(
                {
                    "title": {"type": "string", "minLength": 1, "maxLength": 160},
                    "description": {"type": "string", "maxLength": 2000},
                }
            ),
            TICKET_RESULT,
            conversation_snapshot,
            read_only=False,
            risk=2,
        ),
        Capability(
            "ticket_update",
            1,
            obj(
                {
                    "ticket_id": TEXT_ID,
                    "expected_version": {"type": "integer", "minimum": 1},
                    "status": {
                        "type": "string",
                        "enum": ["open", "in_progress", "resolved", "closed"],
                    },
                    "note": {"type": "string", "maxLength": 1000},
                }
            ),
            TICKET_RESULT,
            conversation_snapshot,
            read_only=False,
            risk=2,
        ),
        Capability(
            "human_handoff",
            1,
            obj({"reason": {"type": "string", "enum": HANDOFF_REASONS}}),
            obj({"support_state": {"type": "string"}, "reason": {"type": "string"}}),
            conversation_snapshot,
            read_only=False,
            risk=2,
        ),
        Capability(
            "notification",
            1,
            obj({"ticket_id": TEXT_ID}),
            TICKET_RESULT,
            conversation_snapshot,
            read_only=False,
            risk=2,
        ),
    ]
