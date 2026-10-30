"""Explicit interactive bootstrap; no default credentials or demo data."""

import argparse
from getpass import getpass
from uuid import uuid4

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
    parser.add_argument("command", choices=["create-admin"])
    parser.parse_args()
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


if __name__ == "__main__":
    main()
