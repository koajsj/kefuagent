import re

from sqlalchemy import exists, func, select
from sqlalchemy.orm import aliased

from support_agent.errors import AppError
from support_agent.models import Document, DocumentChunk, KnowledgeBase
from support_agent.rag_schemas import SearchHit
from support_agent.search_text import (
    HAN,
    coverage,
    latin_expression,
    query_expression,
    query_groups,
)
from support_agent.services.knowledge import active_base
from support_agent.services.memory import sensitive

_INJECTION = re.compile(
    r"(?:ignore|disregard|override|forget).{0,80}(?:previous|system|developer|instruction)|"
    r"(?:system|developer)\s*(?:prompt|message)\s*[:：]|"
    r"(?:忽略|覆盖|绕过|无视).{0,40}(?:指令|系统|规则|提示词)|"
    r"(?:泄露|输出|显示).{0,20}(?:API.?KEY|密钥|访问令牌)|"
    r"(?:reveal|output|print).{0,30}(?:api.?key|secret|access.?token)",
    re.IGNORECASE,
)


def reference_is_safe(content, *, document_name="", section=None):
    # Shared by retrieval and historical delivery; known credentials must not
    # reach a model or visitor through an otherwise authorized knowledge source.
    # These conservative patterns are not general DLP or injection detection.
    return all(
        not sensitive(value) and not _INJECTION.search(value)
        for value in (content, document_name, section or "")
    )


class PostgresFTSRetriever:
    def search(
        self, db, context, knowledge_base_ids, query, limit=6, *, document_ids=None, section=None
    ):
        for kid in knowledge_base_ids:
            active_base(db, context, kid)
        groups = query_groups(query)
        single_han = [group[0] for group in groups if len(group) == 1 and HAN.fullmatch(group[0])]
        if groups and len(groups) == len(single_han):
            return self._bounded_han(
                db,
                context,
                knowledge_base_ids,
                single_han,
                limit,
                document_ids=document_ids,
                section=section,
            )
        lanes = [
            (DocumentChunk.chinese_vector, query_expression(groups)),
            (DocumentChunk.search_vector, latin_expression(groups)),
        ]
        candidates = {}
        fused = {}
        body_coverage = {}
        # Each lane covers all authorized KBs together; do not let a per-KB quota bias fusion.
        for vector, expression in lanes:
            if not expression:
                continue
            tsquery = func.to_tsquery("simple", expression)
            score = func.ts_rank_cd(vector, tsquery, 32)
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
                    Document.is_published.is_(True),
                    KnowledgeBase.status == "active",
                    DocumentChunk.generation == Document.generation,
                    DocumentChunk.is_current.is_(True),
                    DocumentChunk.is_deleted.is_(False),
                    Document.id.in_(document_ids) if document_ids else True,
                    DocumentChunk.section == section if section else True,
                    vector.op("@@")(tsquery),
                    score >= 0.001,
                )
                .order_by(score.desc(), DocumentChunk.document_id, DocumentChunk.position)
                .limit(60)
            ).all()
            for rank, (chunk, name, _) in enumerate(rows, 1):
                if not reference_is_safe(chunk.content, document_name=name, section=chunk.section):
                    continue
                if chunk.id not in body_coverage:
                    body_coverage[chunk.id] = coverage(chunk.content, groups)
                if body_coverage[chunk.id] < 0.4 or any(
                    character not in chunk.content for character in single_han
                ):
                    continue
                candidates[chunk.id] = (chunk, name)
                fused[chunk.id] = fused.get(chunk.id, 0) + 1 / (60 + rank)
        # A third lexical lane distinguishes intent coverage and headings among FTS candidates.
        title_coverage = {
            cid: coverage((chunk.section or "") + " " + name, groups)
            for cid, (chunk, name) in candidates.items()
        }
        lexical = sorted(
            candidates,
            key=lambda cid: (
                -body_coverage[cid],
                -title_coverage[cid],
                str(candidates[cid][0].document_id),
                candidates[cid][0].position,
            ),
        )
        lexical_rank = {cid: rank for rank, cid in enumerate(lexical, 1)}
        for cid, rank in lexical_rank.items():
            fused[cid] += 1 / (60 + rank)
        ordered = sorted(candidates, key=lambda cid: (-fused[cid], lexical_rank[cid]))[:limit]
        return [
            SearchHit(
                document_id=candidates[cid][0].document_id,
                document_name=candidates[cid][1],
                chunk_id=cid,
                content=candidates[cid][0].content,
                score=fused[cid],
                page=candidates[cid][0].page,
                section=candidates[cid][0].section,
                generation=candidates[cid][0].generation,
                strategy="postgres_rrf",
            )
            for cid in ordered
        ]

    def _bounded_han(
        self, db, context, knowledge_base_ids, characters, limit, *, document_ids=None, section=None
    ):
        if not 1 <= limit <= 10:
            raise AppError(422, "unsupported_query", "Bounded Han search limit must be 1–10")
        scope = (
            select(DocumentChunk.id)
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
                Document.is_published.is_(True),
                KnowledgeBase.status == "active",
                DocumentChunk.generation == Document.generation,
                DocumentChunk.is_current.is_(True),
                DocumentChunk.is_deleted.is_(False),
                Document.id.in_(document_ids) if document_ids else True,
                DocumentChunk.section == section if section else True,
            )
            .limit(1001)
        )
        with db.begin_nested():
            previous_timeout = db.scalar(select(func.current_setting("statement_timeout")))
            db.execute(select(func.set_config("statement_timeout", "1000ms", True)))
            ids = list(db.scalars(scope))
            if len(ids) > 1000:
                raise AppError(
                    422, "query_too_broad", "Bounded Han search scope exceeds 1000 chunks"
                )
            rows = db.execute(
                select(DocumentChunk, Document.filename)
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
                    Document.is_published.is_(True),
                    KnowledgeBase.status == "active",
                    DocumentChunk.generation == Document.generation,
                    DocumentChunk.is_current.is_(True),
                    DocumentChunk.is_deleted.is_(False),
                    Document.id.in_(document_ids) if document_ids else True,
                    DocumentChunk.section == section if section else True,
                    DocumentChunk.id.in_(ids),
                    *(DocumentChunk.content.like(f"%{character}%") for character in characters),
                )
                .order_by(DocumentChunk.document_id, DocumentChunk.position)
                .limit(61)
            ).all()
            if len(rows) > 60:
                raise AppError(
                    422, "query_too_broad", "Bounded Han search matches more than 60 chunks"
                )
            db.execute(select(func.set_config("statement_timeout", previous_timeout, True)))
        return [
            SearchHit(
                document_id=chunk.document_id,
                document_name=name,
                chunk_id=chunk.id,
                content=chunk.content,
                score=1 / (60 + rank),
                page=chunk.page,
                section=chunk.section,
                generation=chunk.generation,
                strategy="postgres_han_bounded",
            )
            for rank, (chunk, name) in enumerate(
                (
                    (chunk, name)
                    for chunk, name in rows
                    if reference_is_safe(chunk.content, document_name=name, section=chunk.section)
                ),
                1,
            )
            if rank <= limit
        ]

    def current_chunks(self, db, context, chunk_ids, *, lock=False, current_only=False):
        if lock:
            # Lock before evaluating lineage, using deletion's KB -> document order.
            bases = (
                select(Document.knowledge_base_id)
                .join(DocumentChunk, DocumentChunk.document_id == Document.id)
                .where(
                    Document.tenant_id == context.tenant_id,
                    DocumentChunk.tenant_id == context.tenant_id,
                    DocumentChunk.id.in_(chunk_ids),
                )
            )
            db.scalars(
                select(KnowledgeBase)
                .where(KnowledgeBase.tenant_id == context.tenant_id, KnowledgeBase.id.in_(bases))
                .order_by(KnowledgeBase.id)
                .with_for_update(read=True)
            ).all()
            db.scalars(
                select(Document)
                .where(
                    Document.tenant_id == context.tenant_id,
                    Document.id.in_(
                        select(DocumentChunk.document_id).where(
                            DocumentChunk.tenant_id == context.tenant_id,
                            DocumentChunk.id.in_(chunk_ids),
                        )
                    ),
                )
                .order_by(Document.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            ).all()
        current = aliased(DocumentChunk)
        valid_lineage = exists(
            select(current.id).where(
                current.tenant_id == DocumentChunk.tenant_id,
                current.document_id == DocumentChunk.document_id,
                current.generation == DocumentChunk.generation,
                current.root_chunk_id == DocumentChunk.root_chunk_id,
                current.is_current.is_(True),
                current.is_deleted.is_(False),
            )
        )
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
                Document.is_published.is_(True),
                KnowledgeBase.status == "active",
                DocumentChunk.generation == Document.generation,
                DocumentChunk.is_deleted.is_(False),
                valid_lineage,
            )
        )
        if current_only:
            stmt = stmt.where(DocumentChunk.is_current.is_(True))
        return {
            chunk.id: (chunk, doc)
            for chunk, doc in db.execute(stmt)
            if reference_is_safe(chunk.content, document_name=doc.filename, section=chunk.section)
        }
