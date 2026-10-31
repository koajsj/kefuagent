# 独立部署、升级与恢复

本项目只使用 PostgreSQL、本地私有文档目录和 Python 服务。Web 资源随 Python 包提供，不需要 Node、前端构建或 CDN。以下包含部署方案与本机恢复验证边界：P6 已在 Mac 隔离副本验证恢复，生产 Linux、HTTPS 反向代理和灾难环境切换尚未验收。

## Linux 首次安装

使用 Python 3.11–3.14、PostgreSQL 15+、uv。以普通系统账号运行；应用目录与存储目录只对服务账号可写。

```bash
git clone https://github.com/koajsj/kefuagent.git
cd kefuagent
uv sync --locked
cp .env.example .env
chmod 600 .env
```

由数据库管理员在**全新的独立数据库**交互执行，替换角色名和库名：

```sql
CREATE ROLE support_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
\password support_owner
CREATE ROLE support_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
\password support_app
CREATE DATABASE support_agent OWNER support_owner;
```

`.env` 中 DATABASE_URL 使用 support_app；MIGRATION_DATABASE_URL 使用 support_owner。数据库账号密码含特殊字符时必须 URL 编码，不把连接串写进聊天、日志或命令历史。

首次生成主密钥和匿名限流密钥：在已经复制的 `.env` **尚无这两个变量时**执行以下一次性脚本。已有密钥时拒绝覆盖。两项密钥不会打印。

```bash
uv run python - <<'PY'
from pathlib import Path
import base64, os, secrets
path = Path('.env')
content = path.read_text()
keys = ['CREDENTIAL_MASTER_KEY', 'PUBLIC_RATE_KEY']
if any(line.strip().startswith(k + '=') for line in content.splitlines() for k in keys):
    raise SystemExit('已有密钥，禁止替换；按运维方案处理轮换。')
with path.open('a') as stream:
    stream.write('\nCREDENTIAL_MASTER_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode() + '\n')
    stream.write('PUBLIC_RATE_KEY=' + secrets.token_urlsafe(48) + '\n')
path.chmod(0o600)
PY
```

配置 WEB_ORIGIN 为最终 HTTPS 地址（无路径），DOCUMENT_STORAGE_ROOT 为服务账号私有的绝对目录；MODEL_ALLOWED_HOSTS 是精确主机 JSON 数组，例如 `["api.provider.example"]`。只支持批准公网 HTTPS:443，私网、回环模型服务不支持。ALLOW_EXTERNAL_MODELS 保持 false 进行离线验收；部署方自行确认供应商和费用后才开启真实调用，本阶段没有执行。

经目标数据库负责人授权后迁移（服务不会自动迁移）：

```bash
uv run alembic upgrade head
```

数据库管理员连接 support_agent，授予运行账号最小业务权限；**不要授予 schema CREATE 或 DDL 权限**：

```sql
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO support_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO support_app;
-- 应用不会写迁移版本：
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM support_app;
ALTER DEFAULT PRIVILEGES FOR ROLE support_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO support_app;
```

FORCE RLS 不允许运行账号拥有 SUPERUSER/BYPASSRLS。新建数据库的 `public` schema 所有权也必须属于受控迁移角色，而非普通成员。全局用户、成员和最小公开定位表由服务端显式授权，不假定它们由租户 RLS 保护。

```bash
uv run python -m support_agent.cli create-admin
uv run uvicorn support_agent.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

没有默认账号或弱密码。首次管理员只在本机交互创建。建议服务启动时只提供运行 DATABASE_URL，不向 HTTP 进程注入迁移角色凭证。create-admin 需要业务 INSERT 权限，无需超级用户。

## HTTPS 与进程管理

可使用 systemd 运行上述 uvicorn 命令；WorkingDirectory 指向项目，User 使用专属普通账号，EnvironmentFile 指向 0600 配置，设置 Restart=on-failure、UMask=0077。为模型/解析子进程保留执行权限，不使用会阻断现有隔离子进程的随意沙箱配置。文件目录和 PostgreSQL 应由系统服务分别管理。

在 Nginx/Caddy 终止 TLS，后端仅监听回环。反向代理要求：

- 转发同一个域名下的 `/`、`/assets/`、`/chat/`、`/widget.js` 和 `/api/`；保留 Authorization 与 Origin，不开放通配 CORS。
- 管理页面要求 HTTPS；HTTP 到 HTTPS 重定向、HSTS 由代理配置。WEB_ORIGIN 与用户实际访问 Origin 精确一致，否则写请求 403。不要混用 localhost 和 127.0.0.1。
- 只信任确定的代理 IP；Uvicorn 使用 `--proxy-headers --forwarded-allow-ips=127.0.0.1` 时，代理必须**覆盖**客户端传入的 X-Forwarded-For，不能透传伪造头。公网直连关闭代理头解析。否则匿名 IP 限流可能失真。
- 上传代理限额可设 6 MiB，应用仍限制文件 5 MiB；代理响应超时至少 180 秒，避免 120 秒 Agent 时间预算内连接提前中断。未知结果使用同一幂等键查询/重试，不生成新键盲目重发。
- 对公开 API、登录与所有 HTTP 请求增加代理入口速率/连接限制。应用已有持久模型准入和匿名创建/调用限制，但没有承诺抵御 DDoS 或高频 GET。日志不要记录 Authorization、Cookie、请求体或供应商 Key；尽量记录路由模板而非敏感路径。
- 管理页面 CSP 禁止嵌入；仅 `/chat/{公开入口ID}` 允许网站 iframe。小组件宿主需允许本服务域名的 script-src/frame-src。跨站 iframe 的存储能力取决于浏览器隐私政策；被阻止时使用独立链接。

## 备份关系

一次可恢复备份必须关联三部分：

1. PostgreSQL（包括企业、认证、密文、发布、访客、用量、审计、迁移版本）。
2. DOCUMENT_STORAGE_ROOT 私有文档目录及权限。
3. 与该批密文对应的 CREDENTIAL_MASTER_KEY；与数据库备份分开加密保存。PUBLIC_RATE_KEY 也应安全保留，丢失将重置 IP 维度计数，不能当作限额恢复保证。

**主密钥丢失将导致模型凭证无法解密；仅恢复数据库或重生成主密钥不能恢复原 API Key。** 访客令牌及认证数据包含在数据库备份中，备份必须受限访问。

需要一致备份时停止入口并排空模型/工具/文档处理，确认没有解析或删除正在跨文件与数据库执行。由运营方确定全新备份位置；P6 仅为随机隔离演练库创建新的受限备份，未改动任何已有备份。示例命令由运营方在备份窗口执行，密码通过受保护的 `.pgpass` 提供，不在命令行展开：

```bash
pg_dump --format=custom --host=DB_HOST --username=BACKUP_ROLE --file=/NEW_BACKUP_LOCATION/database.dump support_agent
# 在静止窗口用受控备份工具保存私有文档目录，并单独保管密钥。
```

FORCE RLS 下备份角色必须有经过审批的完整备份能力（通常独立受控超级/备份角色）；普通 support_app 不可用于全库备份，避免只导出部分租户或报错。不要把备份角色用于 HTTP。

恢复必须先在**新建隔离数据库和新存储目录**进行，不覆盖运行库或已有备份。由 DBA 使用恢复角色 `pg_restore --exit-on-error`，核对对象拥有者/角色映射和 FORCE RLS，再使用对应主密钥、私有文档副本启动隔离实例（外部调用保持关闭）。检查健康、登录、租户隔离、文档检索、凭证解密和迁移版本后，按另行批准的切换方案处理正式入口。恢复旧备份可能恢复已撤销访客/管理会话和已删数据；上线前必须重放撤销/删除策略，不能直接放量。

经批准的新目标示例（数据库必须不存在，禁止添加 `--clean` 或 `--create` 覆盖现有对象；替换占位名称）：

```bash
createdb --host=DB_HOST --username=RESTORE_ADMIN --owner=support_owner support_agent_restore
pg_restore --exit-on-error --single-transaction --host=DB_HOST --username=RESTORE_ADMIN --dbname=support_agent_restore /EXISTING_BACKUP_LOCATION/database.dump
```

失败时不切换入口，检查非零退出码并保留证据；单事务恢复回滚数据库对象，文档副本仍需单独核对。备份中的角色须预先存在或由 DBA 明确映射，恢复角色需具备完整恢复权限。重新授予最小运行权限、比较表计数/文档摘要并验证 RLS 后，在隔离实例使用新数据库 URL、新文档目录和该备份对应主密钥；不要让恢复实例使用原文件目录。

## 升级与轮换

保留本地修改，审查变更和增量 SQL，记录当前版本，先在隔离副本升级；正式升级需明确授权与维护窗口。停止入口、备份三部分、执行迁移、授予新增表必要权限、执行检查，再重启。应用要求当前迁移 head，版本不符安全拒绝启动。不执行自动 downgrade；0007–0009 明确拒绝会丢数据的自动降级。

P7 提供版本化 keyring 与维护窗口轮换/恢复 CLI，见 [P7 运行维护](P7_RUNTIME.md)。必须保留旧密钥，不能直接替换唯一环境变量；该流程不等于无停机密钥分发。普通企业 API Key 更新已实现；在途配置/凭证变化会阻止旧结果交付。

数据默认保留；文档/知识库与凭证由管理员显式删除，公开入口可下线/撤销。访客 Token 过期不自动删除会话、审计或幂等记录。备份保留期、完整隐私擦除、生产容量与生产恢复演练需部署方另行确认。P7 可按显式保留策略预览、确认和有界清理，默认没有自动任务或生产部署。

P6 本机演练使用现有测试库的只读 schema 副本，在全新随机数据库中经 CLI 初始化管理员、录入模拟业务，停止应用后执行 custom-format pg_dump，再 pg_restore --exit-on-error 到另一个空库；文档复制到新的私有目录，用对应模拟主密钥验证解密。表记录数、文档 SHA-256、迁移版本、14 张表的 FORCE RLS 和策略均核对。原 dev/test 行数、原文档及 .env 哈希保持一致；新演练库与 0700/0600 证据保留在本机，未上传。不等于已执行从零迁移或生产灾难切换。详见 [验收记录](ACCEPTANCE.md)。

SSE 代理需关闭响应缓冲（应用返回 X-Accel-Buffering: no），保持至少 180 秒读超时。阶段实时发送，最终答案先完整校验再分段交付；断连后先查记录，不能新建幂等键盲目重发。新增版本密钥/保留配置及 CI 见 [P7 运行维护](P7_RUNTIME.md)。

P8 配置预检、三类健康接口、可选本机 Compose 与显式迁移说明见 [P8 部署](P8_DEPLOYMENT.md)。当前 head 为 0009_operations，新增关联表也必须授予运行角色最小表权限并保留 FORCE RLS。
