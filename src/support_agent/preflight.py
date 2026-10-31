"""Read-only deployment checks; detailed results are for trusted operators only."""

import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from support_agent.credentials import Keyring, cipher
from support_agent.db import EXPECTED_REVISION
from support_agent.errors import AppError
from support_agent.providers import validate_base_url

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


def inspect(settings, engine, *, production=False):
    production = production or settings.deployment_environment == "production"
    checks = []

    def add(name, status, message):
        checks.append({"name": name, "status": status, "message": message})

    rate_key = settings.http_rate_key or settings.public_rate_key
    ingress_ready = settings.http_limits_enabled and rate_key is not None
    add(
        "http_ingress",
        "ok"
        if ingress_ready
        else "error"
        if production or settings.http_limits_enabled
        else "warning",
        "HTTP 入口保护已启用；所有实例须共享数据库与密钥。"
        if ingress_ready
        else "HTTP 入口保护未启用或缺少密钥；生产启用前检查部署配置。",
    )
    https = urlsplit(settings.web_origin).scheme == "https"
    add(
        "production_https",
        "ok" if https else "error" if production else "warning",
        "已配置 HTTPS Origin；TLS 和代理信任仍需部署方验证。"
        if https
        else "HTTP Origin 仅用于本机开发；生产必须配置 HTTPS。",
    )
    add(
        "migration_credentials",
        "error"
        if production and settings.migration_database_url
        else "warning"
        if settings.migration_database_url
        else "ok",
        "HTTP 进程不得持有迁移连接；将迁移配置与运行环境分离。"
        if settings.migration_database_url
        else "运行配置未加载迁移连接。",
    )
    env = Path(".env")
    try:
        mode = env.lstat().st_mode
        private_env = stat.S_ISREG(mode) and not mode & 0o077
        add(
            "environment_file",
            "ok" if private_env else "error" if production else "warning",
            "本地 .env 是仅所有者可访问的普通文件。"
            if private_env
            else "本地 .env 不得为链接或向组/其他用户开放；生产使用 0600/0400。",
        )
    except FileNotFoundError:
        add("environment_file", "warning", "未发现 .env；外部注入秘密的权限由部署平台保证。")
    except OSError:
        add("environment_file", "error", "无法检查 .env 权限。")
    if production:
        values = [make_url(settings.database_url.get_secret_value()).password or ""]
        values.extend(
            value.get_secret_value()
            for value in (settings.public_rate_key, settings.http_rate_key)
            if value
        )
        placeholders = any(
            value.upper().startswith(("CHANGE_ME", "REPLACE_", "YOUR_", "EXAMPLE_"))
            for value in values
        )
        add(
            "secret_placeholders",
            "error" if placeholders else "ok",
            "配置仍含示例秘密占位符。"
            if placeholders
            else "未发现已知示例秘密占位符；不代表已验证密钥随机性或平台权限。",
        )

    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            add(
                "database_role",
                "error" if any(role) else "ok",
                "运行角色不得有 SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB/REPLICATION。"
                if any(role)
                else "运行角色不具有数据库管理或绕过 RLS 的属性。",
            )
    except (SQLAlchemyError, OSError):
        add("database_role", "error", "无法检查数据库角色；检查运行连接和权限。")

    if production:
        try:
            with engine.connect() as connection:
                ddl = connection.execute(
                    text("""
                    SELECT
                        EXISTS (SELECT 1 FROM pg_database d
                            WHERE d.datname = current_database()
                              AND pg_has_role(current_user, d.datdba, 'MEMBER')),
                        has_database_privilege(current_user, current_database(), 'CREATE')
                            OR has_database_privilege(current_user, current_database(), 'TEMPORARY'),
                        EXISTS (SELECT 1 FROM pg_namespace n
                            WHERE left(n.nspname, 3) <> 'pg_' AND n.nspname <> 'information_schema'
                              AND (has_schema_privilege(current_user, n.oid, 'CREATE')
                                   OR pg_has_role(current_user, n.nspowner, 'MEMBER'))),
                        EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE left(n.nspname, 3) <> 'pg_' AND n.nspname <> 'information_schema'
                              AND pg_has_role(current_user, c.relowner, 'MEMBER')),
                        EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                            WHERE left(n.nspname, 3) <> 'pg_' AND n.nspname <> 'information_schema'
                              AND pg_has_role(current_user, p.proowner, 'MEMBER')),
                        EXISTS (SELECT 1 FROM pg_roles r
                            WHERE (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole
                                   OR r.rolcreatedb OR r.rolreplication)
                              AND pg_has_role(current_user, r.oid, 'MEMBER'))
                """)
                ).one()
            add(
                "database_ddl",
                "error" if any(ddl) else "ok",
                "运行角色具有 DDL/所有者或高权角色成员权限；由 DBA 收敛后再启动。"
                if any(ddl)
                else "运行角色未发现 CREATE/TEMPORARY、表/函数/schema 所有权或高权角色成员权限。",
            )
        except (SQLAlchemyError, OSError):
            add("database_ddl", "error", "无法只读检查数据库 DDL 权限和成员关系。")

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
                    text(
                        "SELECT EXISTS (SELECT 1 FROM users WHERE is_platform_admin IS TRUE AND status = 'active')"
                    )
                ).scalar_one()
            )
        add(
            "bootstrap_admin",
            "ok" if setup_complete else "error" if production else "warning",
            "平台管理员已初始化。"
            if setup_complete
            else "缺少活动平台管理员；请通过受信任的初始化/恢复流程处理。",
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
    if production:
        try:
            mode = root.lstat().st_mode
            private_root = stat.S_ISDIR(mode) and not mode & 0o077
        except OSError:
            private_root = False
        add(
            "private_storage",
            "ok" if private_root else "error",
            "文档根目录是仅所有者可访问的普通目录；ACL/共享存储仍需部署方验证。"
            if private_root
            else "文档根目录须为私有普通目录（0700），不得为链接或公开可读写。",
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
        "mode": "production" if production else "development",
        "production_verified": False,
        "ready": not any(check["status"] == "error" for check in checks),
        "setup_complete": setup_complete,
        "checks": checks,
    }
