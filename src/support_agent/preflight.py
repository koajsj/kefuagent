"""Read-only deployment checks; detailed results are for trusted operators only."""

import os

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from support_agent.credentials import Keyring, cipher
from support_agent.errors import AppError
from support_agent.providers import validate_base_url

EXPECTED_REVISION = "0009_operations"
RLS_TABLES = (
    "agent_configs",
    "conversations",
    "messages",
    "tool_definitions",
    "knowledge_bases",
    "documents",
    "document_chunks",
    "model_credentials",
    "model_calls",
    "agent_tools",
    "tool_executions",
    "agent_knowledge_bases",
    "publications",
    "visitor_sessions",
    "conversation_collaboration",
    "conversation_summaries",
    "visitor_feedback",
)
POLICY_EXPRESSION = (
    "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
)


def inspect(settings, engine):
    checks = []

    def add(name, status, message):
        checks.append({"name": name, "status": status, "message": message})

    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            add(
                "database_role",
                "error" if any(role) else "ok",
                "运行角色必须为 NOSUPERUSER、NOBYPASSRLS 和 NOCREATEROLE。"
                if any(role)
                else "运行角色不具有超级用户、绕过 RLS 或创建角色权限。",
            )
    except (SQLAlchemyError, OSError):
        add("database_role", "error", "无法检查数据库角色；检查运行连接和权限。")

    try:
        with engine.connect() as connection:
            revisions = (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            )
        current = revisions == [EXPECTED_REVISION]
        add(
            "database_revision",
            "ok" if current else "error",
            "数据库迁移版本符合要求。"
            if current
            else "迁移版本不匹配；经授权后用迁移角色升级到 head。",
        )
    except (SQLAlchemyError, OSError):
        add("database_revision", "error", "无法读取迁移版本；检查连接、表和运行角色读取权限。")

    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                           p.polname, p.polcmd, p.polpermissive, p.polroles,
                           pg_get_expr(p.polqual, p.polrelid),
                           pg_get_expr(p.polwithcheck, p.polrelid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    LEFT JOIN pg_policy p ON p.polrelid = c.oid
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                      AND c.relname = ANY(:tables)
                """),
                {"tables": list(RLS_TABLES)},
            ).all()
        valid = len(rows) == len(RLS_TABLES) and {row[0] for row in rows} == set(RLS_TABLES)
        valid = valid and all(
            row[1]
            and row[2]
            and row[3] == "tenant_isolation"
            and row[4] == "*"
            and row[5]
            and list(row[6]) == [0]
            and row[7] == POLICY_EXPRESSION
            and row[8] == POLICY_EXPRESSION
            for row in rows
        )
        add(
            "tenant_rls",
            "ok" if valid else "error",
            "17 张租户表的 FORCE RLS 和租户策略符合预期。"
            if valid
            else "租户表 RLS 或策略不符合预期；请审查迁移和数据库策略。",
        )
    except (SQLAlchemyError, OSError):
        add("tenant_rls", "error", "无法检查租户表 RLS；检查数据库连接与目录读取权限。")

    setup_complete = False
    try:
        with engine.connect() as connection:
            setup_complete = bool(
                connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM users WHERE is_platform_admin IS TRUE)")
                ).scalar_one()
            )
        add(
            "bootstrap_admin",
            "ok" if setup_complete else "warning",
            "平台管理员已初始化。"
            if setup_complete
            else "尚未初始化平台管理员；运行交互式 create-admin。",
        )
    except (SQLAlchemyError, OSError):
        add("bootstrap_admin", "error", "无法检查管理员状态；检查数据库版本和运行角色读取权限。")

    try:
        ring = Keyring(settings)
        if not ring.keys.get(ring.active):
            raise ValueError
        for key in ring.keys.values():
            cipher(key)
        add("credential_keyring", "ok", "凭证密钥配置有效；历史密钥完整性需另行核对。")
    except (AppError, ValueError, TypeError):
        add(
            "credential_keyring",
            "error",
            "凭证密钥配置无效或缺失；检查受保护的 keyring 和活动密钥。",
        )

    add(
        "public_rate_key",
        "ok" if settings.public_rate_key else "error",
        "公开限流密钥已配置。"
        if settings.public_rate_key
        else "缺少公开限流密钥；配置独立随机密钥。",
    )
    root = settings.document_storage_root
    writable = root.is_dir() and os.access(root, os.W_OK | os.X_OK)
    add(
        "document_storage",
        "ok" if writable else "error",
        "文档目录存在且当前用户可写。"
        if writable
        else "文档目录不存在或不可写；由运营方创建私有目录并授权服务账号。",
    )
    add("web_origin", "ok", "Web Origin 格式有效；请核对实际访问地址及 HTTPS 代理。")
    try:
        for host in settings.model_allowed_hosts:
            validate_base_url("https://" + host, [host])
        valid_hosts = bool(settings.model_allowed_hosts)
        if settings.allow_external_models and not valid_hosts:
            add(
                "external_models",
                "error",
                "外部模型已开启但主机白名单为空；配置批准的精确主机或关闭开关。",
            )
        elif settings.allow_external_models:
            add("external_models", "ok", "外部模型已开启且主机白名单非空；未验证供应商连接。")
        else:
            add("external_models", "warning", "外部模型已关闭；如需使用，请先批准供应商和费用。")
    except (AppError, TypeError):
        add("external_models", "error", "模型白名单包含无效主机；仅配置精确 HTTPS 域名。")

    return {
        "ready": not any(check["status"] == "error" for check in checks),
        "setup_complete": setup_complete,
        "checks": checks,
    }
