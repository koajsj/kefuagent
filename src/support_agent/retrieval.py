import re
from typing import Protocol

from sqlalchemy import func, select

from support_agent.models import Document, DocumentChunk, KnowledgeBase
from support_agent.rag_schemas import SearchHit
from support_agent.services.knowledge import active_base

_INJECTION = re.compile(
    r"(?:ignore|disregard|override|forget).{0,80}(?:previous|system|developer|instruction)|"
    r"(?:system|developer)\s*(?:prompt|message)\s*[:：]|"
    r"(?:忽略|覆盖|绕过|无视).{0,40}(?:指令|系统|规则|提示词)|"
    r"(?:泄露|输出|显示).{0,20}(?:API.?KEY|密钥|访问令牌)|"
    r"(?:reveal|output|print).{0,30}(?:api.?key|secret|access.?token)",
    re.IGNORECASE,
)


def reference_is_safe(content):
    # Conservative known-pattern screen, not a general prompt-injection classifier.
    return not _INJECTION.search(content)


class Retriever(Protocol):
    def search(self, db, context, knowledge_base_ids, query, limit=6) -> list[SearchHit]: ...


class PostgresFTSRetriever:
    def search(self, db, context, knowledge_base_ids, query, limit=6):
        for kid in knowledge_base_ids:
            active_base(db, context, kid)
        tsquery = func.plainto_tsquery("simple", query)
        score = func.ts_rank_cd(DocumentChunk.search_vector, tsquery, 32)
        rows = db.execute(
            select(DocumentChunk, Document.filename, score.label("score"))
            .join(
                Document,
                (Document.tenant_id == DocumentChunk.tenant_id)
                & (Document.id == DocumentChunk.document_id),
            )
            .join(
                KnowledgeBase,
                (KnowledgeBase.tenant_id == Document.tenant_id)
                & (KnowledgeBase.id == Document.knowledge_base_id),
            )
            .where(
                DocumentChunk.tenant_id == context.tenant_id,
                Document.tenant_id == context.tenant_id,
                KnowledgeBase.tenant_id == context.tenant_id,
                Document.knowledge_base_id.in_(knowledge_base_ids),
                Document.status == "ready",
                KnowledgeBase.status == "active",
                DocumentChunk.generation == Document.generation,
                DocumentChunk.search_vector.op("@@")(tsquery),
                score >= 0.001,
            )
            .order_by(score.desc(), DocumentChunk.id)
            .limit(limit)
        ).all()
        return [
            SearchHit(
                document_id=chunk.document_id,
                document_name=name,
                chunk_id=chunk.id,
                content=chunk.content,
                score=rank,
                page=chunk.page,
                section=chunk.section,
                generation=chunk.generation,
            )
            for chunk, name, rank in rows
            if reference_is_safe(chunk.content)
        ]

    def current_chunks(self, db, context, chunk_ids, *, lock=False):
        stmt = (
            select(DocumentChunk, Document)
            .join(
                Document,
                (Document.tenant_id == DocumentChunk.tenant_id)
                & (Document.id == DocumentChunk.document_id),
            )
            .join(
                KnowledgeBase,
                (KnowledgeBase.tenant_id == Document.tenant_id)
                & (KnowledgeBase.id == Document.knowledge_base_id),
            )
            .where(
                DocumentChunk.tenant_id == context.tenant_id,
                DocumentChunk.id.in_(chunk_ids),
                Document.tenant_id == context.tenant_id,
                KnowledgeBase.tenant_id == context.tenant_id,
                Document.status == "ready",
                KnowledgeBase.status == "active",
                DocumentChunk.generation == Document.generation,
            )
        )
        if lock:
            stmt = stmt.with_for_update(read=True, of=Document)
        return {chunk.id: (chunk, doc) for chunk, doc in db.execute(stmt)}
