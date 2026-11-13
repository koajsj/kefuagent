"""Flat, bounded source dependencies for every knowledge-bearing model input."""

from uuid import UUID

from support_agent.errors import AppError

VERSION = 1
MAX_SOURCES = 512


def initialize(call):
    call.result = (call.result or {}) | {
        "knowledge_provenance_version": VERSION,
        "knowledge_dependencies": [],
    }


def sources(call):
    result = call.result or {}
    if result.get("knowledge_provenance_version") != VERSION:
        return None
    values = result.get("knowledge_dependencies")
    if not isinstance(values, list) or len(values) > MAX_SOURCES:
        return None
    try:
        return {UUID(value) for value in values}
    except (ValueError, TypeError, AttributeError):
        return None


def bind(call, chunk_ids):
    previous = sources(call)
    if previous is None:
        raise AppError(409, "knowledge_provenance_unknown", "Knowledge input provenance is unknown")
    combined = previous | {UUID(str(cid)) for cid in chunk_ids}
    if len(combined) > MAX_SOURCES:
        raise AppError(
            409, "knowledge_dependency_limit", "Start a new conversation to bound sources"
        )
    call.result = call.result | {"knowledge_dependencies": sorted(map(str, combined))}
