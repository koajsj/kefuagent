"""Explicit interactive bootstrap; no default credentials or demo data."""

import argparse
from getpass import getpass
from types import SimpleNamespace
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from support_agent.config import Settings
from support_agent.db import build_database, check_database
from support_agent.models import AuditEvent, User
from support_agent.schemas import UserCreate
from support_agent.security import hash_password


def main():
    parser = argparse.ArgumentParser(description="通用客服平台本地管理")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-admin")
    commands.add_parser("preflight", help="只读检查部署配置和数据库")
    rotation = commands.add_parser("rotate-keys", help="租户范围主密钥预览、检查、原子执行或恢复")
    rotation.add_argument("mode", choices=["preview", "check", "execute", "recover"])
    rotation.add_argument("--tenant", type=UUID, required=True)
    rotation.add_argument(
        "--target", required=True, help="非敏感密钥版本标识，密钥只从受保护配置读取"
    )
    rotation.add_argument("--confirm", help="预览返回的完整摘要")
    retention = commands.add_parser("retention", help="默认仅预览；不删除活动请求或当前配额窗口")
    retention.add_argument("mode", choices=["preview", "execute"])
    retention.add_argument("--tenant", type=UUID, required=True)
    retention.add_argument("--confirm")
    retention.add_argument("--batch-size", type=int, default=20)
    retention.add_argument("--documents", action="store_true", help="仅清理既有 deleting 文档")
    for field in ("conversations", "visitors", "calls", "audit"):
        retention.add_argument("--" + field + "-days", type=int)
    args = parser.parse_args()
    if args.command == "preflight":
        return preflight(parser)
    if args.command != "create-admin":
        return maintenance(args, parser)
    try:
        data = UserCreate(
            login=input("登录标识（小写）："),
            display_name=input("显示名称："),
            password=getpass("新密码（至少 12 字符）："),
        )
        if data.password.get_secret_value() != getpass("再次输入密码："):
            parser.exit(1, "两次密码不一致。\n")
    except ValidationError:
        parser.exit(1, "登录标识、名称或密码格式不符合要求。\n")
    engine, sessions = build_database(Settings())
    try:
        check_database(engine)
        with sessions.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(741331, 1)"))
            if db.scalar(select(User.id).where(User.is_platform_admin.is_(True)).limit(1)):
                parser.exit(1, "平台管理员已存在；此命令仅用于首次初始化。\n")
            user = User(
                login=data.login,
                display_name=data.display_name,
                password_hash=hash_password(data.password.get_secret_value()),
                is_platform_admin=True,
            )
            db.add(user)
            db.flush()
            db.add(
                AuditEvent(
                    actor_id=user.id,
                    action="user.bootstrap",
                    resource_type="user",
                    resource_id=user.id,
                    request_id=uuid4(),
                    outcome="success",
                )
            )
        print("平台管理员已创建。密码不会显示或写入文件。")
    except (SQLAlchemyError, RuntimeError):
        parser.exit(1, "初始化失败：请检查独立数据库连接、迁移和用户唯一性。\n")
    finally:
        engine.dispose()


def preflight(parser):
    import json

    from support_agent.preflight import inspect

    try:
        settings = Settings()
        engine, _ = build_database(settings)
    except (ValidationError, ValueError):
        parser.exit(1, "配置无效；请检查环境变量格式，详情不会显示以保护密钥。\n")
    try:
        result = inspect(settings, engine)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ready"]:
            parser.exit(1)
    finally:
        engine.dispose()


def maintenance(args, parser):
    import json

    from support_agent.credentials import Keyring
    from support_agent.errors import AppError
    from support_agent.maintenance import audit, rotate_credentials, rotation_plan
    from support_agent.retention import apply_retention, retention_plan
    from support_agent.storage import LocalDocumentStorage

    settings = Settings()
    engine, sessions = build_database(settings)
    try:
        check_database(engine)
        with sessions() as db:
            if args.mode in {"execute", "recover"} and not args.confirm:
                parser.exit(1, "执行需要先预览，并提供 --confirm 完整摘要。\n")
            try:
                if args.command == "rotate-keys":
                    ring = Keyring(settings)
                    if args.mode in {"preview", "check"}:
                        result = rotation_plan(
                            db, args.tenant, ring, args.target, check=args.mode == "check"
                        )
                    else:
                        result = rotate_credentials(
                            db, args.tenant, ring, args.target, args.confirm
                        )
                else:
                    policy = SimpleNamespace(
                        batch_size=args.batch_size,
                        documents=args.documents,
                        **{
                            field + "_days": getattr(args, field + "_days")
                            if getattr(args, field + "_days") is not None
                            else getattr(settings, "retention_" + field + "_days")
                            for field in ("conversations", "visitors", "calls", "audit")
                        },
                    )
                    result = (
                        retention_plan(db, args.tenant, policy)
                        if args.mode == "preview"
                        else apply_retention(
                            db,
                            args.tenant,
                            policy,
                            args.confirm,
                            LocalDocumentStorage(settings.document_storage_root),
                        )
                    )
            except (AppError, SQLAlchemyError, ValueError, RuntimeError, OSError):
                db.rollback()
                if args.mode in {"execute", "recover"}:
                    # A lost commit acknowledgement is unknown, never recorded as a definite rollback.
                    audit(
                        db,
                        args.tenant,
                        "maintenance.interrupted",
                        {"command": args.command},
                        outcome="failure",
                        reason="result_unknown_check_state",
                    )
                    db.commit()
                raise
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (AppError, SQLAlchemyError, ValueError, RuntimeError, OSError):
        parser.exit(
            1,
            "维护未完成或提交结果未知。未输出密钥；保持入口关闭，检查状态并重新预览，勿盲目执行。\n",
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
