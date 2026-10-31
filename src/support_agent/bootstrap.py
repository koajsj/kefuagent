"""Operator-only setup guidance, backed by the existing Settings and preflight."""

import base64
import fcntl
import os
import shutil
import stat
import subprocess
import sys
from getpass import getpass
from importlib.metadata import version
from pathlib import Path
from secrets import token_bytes, token_urlsafe

from dotenv import dotenv_values
from pydantic import ValidationError

from support_agent.config import Settings
from support_agent.db import build_database
from support_agent.preflight import inspect


class SetupRefused(Exception):
    """An operator-facing refusal containing only fixed, safe recovery guidance."""


def private_env():
    mode = Path(".env").lstat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise SetupRefused(".env 必须是仅所有者可读写的普通文件；请自行核对后 chmod 600 .env。")


def configure_local():
    """Only operator-confirmed, missing values; never replace keys or database contents."""
    if Path(".env").exists() or Path(".env").is_symlink():
        private_env()
    # Settings treats environment names case-insensitively; apply the same rule before any write.
    environment = {name.lower(): value for name, value in os.environ.items()}
    if environment.get("deployment_environment", "development") not in {
        "development",
        "production",
    }:
        raise SetupRefused("DEPLOYMENT_ENVIRONMENT 只能为 development 或 production；未创建配置。")
    if environment.get("deployment_environment") == "production":
        raise SetupRefused("生产配置仅检查；请由部署管理员按 DEPLOYMENT.md 管理密钥和权限。")
    if not Path(".env").exists() and not environment.get("database_url"):
        local_script = Path("scripts/local-postgres.sh")
        if (
            sys.platform == "darwin"
            and local_script.is_file()
            and not Path(".local/pgdata").exists()
            and input(
                "全新本机开发安装：创建独立 PostgreSQL 集群和 dev 库？输入 INIT 确认，否则配置外部数据库："
            )
            == "INIT"
        ):
            subprocess.run(["sh", str(local_script), "init"], check=True)
        else:
            raw = getpass("独立 PostgreSQL 运行连接 URL（隐藏输入；不得使用超级用户）：")
            # Use Settings' normal validation; reject multiline dotenv injection separately.
            Settings(_env_file=None, database_url=raw)
            if any(c in raw for c in "\n\r\x00") or "${" in raw:
                raise SetupRefused("连接 URL 必须为单行；特殊字符需 URL 编码。")
            fd = os.open(".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(
                    "DATABASE_URL='" + raw.replace("\\", "\\\\").replace("'", "\\'") + "'\n"
                )
    settings = Settings()
    if settings.deployment_environment == "production":
        raise SetupRefused("生产配置仅检查；请由部署管理员按 DEPLOYMENT.md 管理密钥和权限。")
    root = settings.document_storage_root
    if not root.exists() and input("创建配置指定的私有文档目录（0700）？[y/N]：").lower() == "y":
        root.mkdir(parents=True, mode=0o700)
    missing_master = not (
        settings.credential_master_key
        or settings.credential_keyring
        or settings.credential_active_key
    )
    missing_public = settings.public_rate_key is None
    if not (missing_master or missing_public):
        return
    if not Path(".env").exists():
        print("使用外部环境注入配置；请在相同秘密管理渠道补齐密钥，不另建 .env。")
        return
    print(
        "仅适用于没有旧加密凭证的全新安装。已有凭证或备份必须恢复原主密钥；新密钥不能解密旧数据。"
    )
    if input("将缺失的随机密钥追加到 .env？输入 NEW KEYS 确认：") != "NEW KEYS":
        return
    fd = os.open(".env", os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
    with os.fdopen(fd, "a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        mode = os.fstat(stream.fileno()).st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise SetupRefused(".env 权限发生变化；未写入密钥。")
        stream.seek(0)
        existing = dotenv_values(stream=stream)
        changes = {}
        if missing_master and not any(
            k in existing or k in os.environ
            for k in ("CREDENTIAL_MASTER_KEY", "CREDENTIAL_KEYRING", "CREDENTIAL_ACTIVE_KEY")
        ):
            changes["CREDENTIAL_MASTER_KEY"] = base64.urlsafe_b64encode(token_bytes(32)).decode()
        if (
            missing_public
            and "PUBLIC_RATE_KEY" not in existing
            and "PUBLIC_RATE_KEY" not in os.environ
        ):
            changes["PUBLIC_RATE_KEY"] = token_urlsafe(48)
        if changes:
            stream.write("\n" + "".join(f"{k}={v}\n" for k, v in changes.items()))
            stream.flush()
            os.fsync(stream.fileno())
            print("已追加缺失密钥；原配置和已有密钥未替换。请离线安全保管 .env，勿提交 Git。")
        else:
            print("已有配置项（包括空值）保留；请手动检查，不生成替代密钥。")


def setup(parser, *, configure=False):
    print(f"kefuagent {version('support-agent-platform')} · Python {sys.version.split()[0]}")
    if not (3, 11) <= sys.version_info[:2] < (3, 15):
        parser.exit(1, "请使用 pyproject.toml 声明支持的 Python 3.11–3.14。\n")
    if not shutil.which("uv"):
        print(
            "[warning] 未找到 uv；当前 Python 环境可继续检查，后续 uv 命令需按快速开始先安装 uv。"
        )
    print("依赖已可加载。默认只读；--configure 才会交互创建缺失配置，不执行迁移或创建账号。")
    if configure and not sys.stdin.isatty():
        parser.exit(1, "--configure 需要交互终端；不会从管道读取数据库连接或密钥。\n")
    try:
        if configure:
            configure_local()
        settings = Settings()
        engine, _ = build_database(settings)
    except (KeyboardInterrupt, EOFError):
        parser.exit(
            130,
            "\n初始化已中断；已写入的配置保留，不自动回滚数据库或替换密钥。检查 .env 后可重新运行 setup --configure；若本机集群已创建，请使用 start 或按部署文档恢复，勿重新 init。\n",
        )
    except SetupRefused as error:
        parser.exit(1, str(error) + "\n")
    except (ValidationError, OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(
            1,
            "配置未就绪。请检查 .env 权限、变量格式及 PostgreSQL 工具。全新本机可用 setup --configure；外部数据库请参阅 docs/QUICK_START.md。不会覆盖配置、重建数据库或显示连接秘密。\n",
        )
    try:
        report = inspect(settings, engine)
    finally:
        engine.dispose()
    for check in report["checks"]:
        print(f"[{check['status']}] {check['name']}: {check['message']}")
    by_name = {check["name"]: check["status"] for check in report["checks"]}
    if by_name.get("database_role") != "ok":
        print(
            "数据库：核对 PostgreSQL 是否启动、端口及运行角色。已有本机集群可运行 ./scripts/local-postgres.sh start；不要重新 init 或删除数据目录。"
        )
    if by_name.get("database_revision") != "ok":
        print(
            "迁移：先备份并取得目标库授权，再在单独的迁移环境执行 uv run alembic upgrade head；迁移凭证不得注入 HTTP 服务。setup 不执行迁移。"
        )
    if not report["setup_complete"]:
        print(
            "管理员：数据库就绪后运行 uv run python -m support_agent.cli create-admin，交互设置强密码；无默认账号。已有停用管理员需走受信任恢复流程。"
        )
    print(
        "启动（在项目目录）：uv run uvicorn support_agent.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers"
    )
    print("该启动命令仅监听本机；外部 PostgreSQL/Linux/HTTPS 与代理配置见 docs/DEPLOYMENT.md。")
    print(
        "配置的管理地址：" + settings.web_origin + "/；API 文档：" + settings.web_origin + "/docs"
    )
    print("登录后打开“使用向导”，导入离线演示。不会自动开启外部模型。")
    if not report["ready"]:
        parser.exit(1, "存在阻塞项；按上述建议处理后重复运行 setup。\n")
    print("预检完成；不代表浏览器、真实模型或生产环境已验收。")
