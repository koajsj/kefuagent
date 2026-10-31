# 本机快速开始

适用于全新、独立的 macOS 开发环境，需要 Python 3.11–3.14、PostgreSQL 15+ 和 [uv](https://docs.astral.sh/uv/)；本机脚本默认使用 Homebrew PostgreSQL 17。Linux、已有数据库和生产环境请先阅读[部署与恢复](DEPLOYMENT.md)。

```bash
git clone https://github.com/koajsj/kefuagent.git
cd kefuagent
uv sync --locked

# 在交互终端中按提示配置；首次迁移和建管理员前可能返回退出码 1
uv run python -m support_agent.cli setup --configure

# 仅在目标数据库获得授权后明确执行；已有数据库先备份并审查
uv run alembic upgrade head
uv run python -m support_agent.cli create-admin

# 只读检查；处理阻塞项后再启动
uv run python -m support_agent.cli setup
uv run uvicorn support_agent.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

`setup --configure` 在没有 `.env` 和环境变量 `DATABASE_URL` 时，可在 macOS 上为全新本机开发环境输入 `INIT` 创建独立集群和开发库；否则隐藏输入外部 PostgreSQL 运行连接 URL，创建私有 `.env`。已有 `.env` 或 `.local/pgdata` 不会被初始化脚本覆盖；已有本机集群停止时可使用 `./scripts/local-postgres.sh start`，不要删除现有数据或配置来绕过保护。该本机脚本的应用角色拥有开发数据库，不满足生产环境的 DBA 角色分离要求。

开发模式下可按提示创建私有文档目录，并输入 `NEW KEYS` 只为缺失项追加随机密钥。已有配置（包括空值）不会覆盖；已有加密凭证或备份必须恢复原主密钥，新密钥不能解密旧数据。使用外部环境注入且没有 `.env` 时，请通过原秘密管理渠道补齐密钥。配置模式不自动迁移、创建管理员或启用外部模型；生产配置应由部署管理员按[部署与恢复](DEPLOYMENT.md)处理。

打开 <http://127.0.0.1:8000>，以刚创建的平台管理员登录，按[首次使用](FIRST_RUN.md)创建企业并体验离线演示。浏览器地址须与 `WEB_ORIGIN` 完全一致，勿混用 `localhost` 和 `127.0.0.1`。敏感信息不要发到聊天、日志或版本库。

| 检查项 | 处理方向 |
| --- | --- |
| 数据库 | 检查 PostgreSQL、端口和运行角色；已有本机集群使用 `start`，不要重建。 |
| 迁移 | 确认目标库并取得授权；已有库先备份，使用独立迁移环境执行上述命令。 |
| 密钥 | 全新安装可在配置模式按提示补缺；旧数据必须恢复原主密钥。公开访客会话需要 `PUBLIC_RATE_KEY`。 |
| 文档目录 | 检查配置的私有目录存在、可写及权限；开发模式可按提示创建。 |
| 管理员 | 数据库就绪后交互执行 `create-admin`；已有停用管理员需走受信任的恢复流程。 |
| Origin | `WEB_ORIGIN` 必须与实际访问地址一致；生产环境使用最终 HTTPS 地址。 |

真实模型须由部署方另行配置并确认费用。生产配置、安全与恢复见[部署与恢复](DEPLOYMENT.md)、[运维与安全](OPERATIONS.md)和[生产检查清单](PRODUCTION_CHECKLIST.md)。本次新手流程的浏览器 GUI、macOS 全新安装、Linux、Docker、生产环境和真实模型尚未验收（NOT_RUN）；历史验证见各阶段记录。
