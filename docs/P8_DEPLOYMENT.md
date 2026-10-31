# P8 部署检查与可选 Compose

macOS 本机部署继续使用 [部署、升级与恢复](DEPLOYMENT.md) 的 Python/PostgreSQL 流程。预检不连接外部模型、不写数据库、不创建目录：

```bash
uv run python -m support_agent.cli preflight
```

JSON 包含 `ready`、`setup_complete` 和逐项状态；配置格式无效或存在 error 时退出码为 1，warning 不影响 ready。ready 表示依赖和配置检查通过，setup_complete 单独表示已存在平台管理员；它们均不代表真实模型、备份恢复、代理或业务验收通过。检查只使用当前进程的身份和配置，目录权限采用进程访问检查，不试写文件。详细结果只供受信任运维人员查看，不要将其暴露给匿名客户端。凭证密钥格式验证不能证明历史密文均可解密。

## 可选 Compose

此方案仅包含应用和 PostgreSQL，应用绑定主机回环；公网使用受控 HTTPS 反向代理，参见 [部署文档](DEPLOYMENT.md)。Docker 和 Compose 需由部署方预先安装；本方案没有自动迁移、管理员或角色初始化。数据库及文档分别保存在命名卷。不要删除或重建已有卷，也不要把任何备份目录映射进容器。

1. 在全新部署目录创建 `secrets/postgres_password`，写入高强度随机数据库管理员密码并限制文件访问；不要将其提交或打印。创建 `.env.compose`（权限 0600），提供应用运行角色的 `DATABASE_URL=postgresql+psycopg://...@db:5432/support_agent`、`DOCUMENT_STORAGE_ROOT=/data/documents`、`WEB_ORIGIN`、独立随机 `PUBLIC_RATE_KEY` 和凭证密钥等配置。参考 `.env.example`；特殊字符需 URL 编码。HTTP 进程不要配置迁移账户凭证。不要使用示例占位密码。
2. 执行 `docker compose up -d db`，由 DBA 安全连接该数据库，参照 [部署文档](DEPLOYMENT.md) 创建独立 `support_owner` 和 `support_app` 登录角色，均为 NOSUPERUSER、NOBYPASSRLS、NOCREATEROLE，分别设置强密码；将数据库及 public schema 的所有权交给迁移角色。数据库管理员仅用于初始化，绝不用于应用或迁移。角色密码不要出现在命令历史。
3. 经目标数据库负责人授权，以受保护的独立迁移配置（包含运行 DATABASE_URL 和 MIGRATION_DATABASE_URL）将受保护配置的绝对路径放入 `MIGRATION_ENV_FILE`，通过独立的 migration 服务显式执行：

   ```bash
   MIGRATION_ENV_FILE=/SECURE/PATH/migration.env docker compose -f compose.yaml -f docker/compose.migration.yaml run --rm --no-deps migration
   ```

   迁移配置须含 `DATABASE_URL` 和正确的 `MIGRATION_DATABASE_URL`，文件不进入镜像或版本库；普通 app 服务不会读取该配置。完成后按部署文档授予运行角色表权限，撤销 alembic_version 写入权限；检查默认权限并保留 RLS。
4. 使用 `docker compose run --rm --no-deps app python -m support_agent.cli preflight` 检查；如提示未初始化管理员，运行 `docker compose run --rm --no-deps app python -m support_agent.cli create-admin` 交互创建。然后 `docker compose up -d app`。首次目录由命名卷初始化，确保服务 UID 10001 对其有写权限；不要通过清空已有卷解决权限问题。

PostgreSQL `pg_isready` 只表示数据库接受连接，并不证明迁移或应用可用。Compose 应用健康检查调用 `/api/v1/health/ready`；`/api/v1/health/live` 是进程存活检查，首次设置状态通过 `/api/v1/health/setup` 单独检查（未就绪 503，无详细配置泄漏）。不要将容器运行状态视为就绪证明。镜像使用 uv 0.13.6 和 `uv.lock` 安装运行依赖，PostgreSQL 使用 17 版本。预检核对 17 张租户表的 FORCE RLS 和预期策略，但不代替租户隔离的实际验收。升级、备份和恢复仍须遵守 [部署文档](DEPLOYMENT.md) 的授权与密钥保管要求。本方案未进行 Docker 构建、运行或生产部署验证。

停止与恢复：`docker compose stop` 保留命名卷；恢复使用 `docker compose start`，升级镜像时按显式迁移与三部分备份流程执行。不要使用 `down -v`，不要挂载原有备份目录作为数据卷。
