"""Explicit, tenant-scoped demo import using the normal document ingestion path."""

from hashlib import sha256
from uuid import uuid5

from sqlalchemy import select, text

from support_agent.errors import AppError
from support_agent.models import AgentConfig, AgentKnowledgeBase, Document, KnowledgeBase
from support_agent.schemas import AgentCreate
from support_agent.services import knowledge
from support_agent.services.audit import record

# A single small, fictional source. It is parsed and cited exactly like an uploaded document.
DEMO_TEXT = """# 青禾协作使用指南（虚构离线演示）

本资料仅用于 kefuagent 离线体验，不对应真实企业、服务承诺或客户数据。

## 试用期
青禾协作的试用期为 14 天。试用期不需要支付费用。

## 客服支持时间
客服支持时间为周一至周五 09:00–18:00（北京时间），法定节假日除外。

## 数据导出
管理员可以打开“设置 → 数据导出”，选择 CSV 格式后导出工作区数据。
普通成员需要联系工作区管理员操作。
""".encode()


def import_demo(db, context, request):
    # Stable IDs separate this bundle from user-named resources without adding a progress table.
    kid = uuid5(context.tenant_id, "kefuagent:demo:v1:knowledge")
    aid = uuid5(context.tenant_id, "kefuagent:demo:v1:agent")
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": kid.int % (2**63)})
    base = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.tenant_id == context.tenant_id, KnowledgeBase.id == kid
        )
    )
    agent = db.scalar(
        select(AgentConfig).where(AgentConfig.tenant_id == context.tenant_id, AgentConfig.id == aid)
    )
    created = base is None and agent is None
    if created:
        base = KnowledgeBase(
            id=kid,
            tenant_id=context.tenant_id,
            created_by=context.user_id,
            name="青禾协作 · 离线演示",
            description="虚构演示资料；无真实模型调用。",
        )
        data = AgentCreate(
            name="青禾协作 · 离线演示",
            provider="demo",
            model="offline-demo",
            behavior={
                "language": "zh",
                "description": "离线演示，仅返回检索原文；不代表真实模型质量。",
            },
        )
        agent = AgentConfig(
            id=aid, tenant_id=context.tenant_id, created_by=context.user_id, **data.model_dump()
        )
        db.add_all([base, agent])
        db.flush()
        db.add(
            AgentKnowledgeBase(
                tenant_id=context.tenant_id,
                agent_config_id=aid,
                knowledge_base_id=kid,
                created_by=context.user_id,
            )
        )
        for kind, rid in (("knowledge_base", kid), ("agent_config", aid)):
            record(db, request, kind + ".create", kind, rid, tenant_id=context.tenant_id)
        # upload commits the resource + document registration together before writing private files;
        # subsequent retries see the same bundle even if parsing is interrupted.
        doc, _ = knowledge.upload(db, context, kid, "青禾协作-离线演示.md", DEMO_TEXT, request)
    else:
        granted = db.scalar(
            select(AgentKnowledgeBase.id).where(
                AgentKnowledgeBase.tenant_id == context.tenant_id,
                AgentKnowledgeBase.agent_config_id == aid,
                AgentKnowledgeBase.knowledge_base_id == kid,
            )
        )
        if (
            base is None
            or base.status != "active"
            or agent is None
            or agent.provider != "demo"
            or not agent.enabled
            or granted is None
        ):
            raise AppError(
                409,
                "demo_modified",
                "Demo resources were changed or removed; existing data will not be overwritten",
            )
        doc = db.scalar(
            select(Document).where(
                Document.tenant_id == context.tenant_id,
                Document.knowledge_base_id == kid,
                Document.sha256 == sha256(DEMO_TEXT).hexdigest(),
            )
        )
        if doc is None or doc.status == "deleting":
            raise AppError(
                409,
                "demo_modified",
                "Demo document was removed; import will not restore deleted data",
            )
        if doc.status in {"pending", "failed"}:
            # An interrupted initial upload can leave a registered row without a private file.
            # Explicit retry repairs only this bundle's identical content through normal ingestion.
            doc, _ = knowledge.upload(db, context, kid, doc.filename, DEMO_TEXT, request)
    record(
        db,
        request,
        "workspace.demo",
        "agent_config",
        aid,
        tenant_id=context.tenant_id,
        outcome="success" if doc.status == "ready" else "failure",
        reason=doc.error_category or ("document_not_ready" if doc.status != "ready" else None),
        details={"created": created, "document_status": doc.status, "offline": True},
    )
    return {
        "knowledge_base_id": kid,
        "document_id": doc.id,
        "agent_config_id": aid,
        "document_status": doc.status,
        "created": created,
        "offline": True,
    }
