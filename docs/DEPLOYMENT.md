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
CREATE ROLE support_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password support_owner
CREATE ROLE support_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
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

数据库管理员连接 support_agent，确认 schema 由迁移角色持有，授予运行账号最小业务权限；运行角色不能拥有数据库、schema、业务表或函数，也不能是这些 owner 角色的成员。不要授予运行角色数据库 CREATE/TEMPORARY、schema CREATE、DDL 或 owner 角色成员权限。下例仅适用于上述全新独立库，既有库先由 DBA 审查已有授权及成员关系：

```sql
ALTER SCHEMA public OWNER TO support_owner;
REVOKE CREATE, TEMPORARY ON DATABASE support_agent FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO support_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO support_app;
-- 应用不会写迁移版本：
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM support_app;
ALTER DEFAULT PRIVILEGES FOR ROLE support_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO support_app;
```

FORCE RLS 不允许运行账号拥有 SUPERUSER、BYPASSRLS、CREATEROLE、CREATEDB 或 REPLICATION。检查直接及继承的角色成员关系与现有授权，确保 `support_app` 不拥有数据库、schema、业务表或函数，也不是其 owner 角色的成员，不具有数据库 CREATE/TEMPORARY 或 schema CREATE。`public` schema 所有权必须属于受控迁移角色，而非普通成员。全局用户、成员和最小公开定位表由服务端显式授权，不假定它们由租户 RLS 保护。

```bash
uv run python -m support_agent.cli create-admin
uv run uvicorn support_agent.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --proxy-headers --forwarded-allow-ips=127.0.0.1
```

没有默认账号或弱密码。首次管理员只在本机交互创建，且必须处于 active 状态。HTTP 进程只能使用运行 DATABASE_URL，不能注入 MIGRATION_DATABASE_URL，包括通过其读取的 `.env` 间接注入；迁移使用单独的受保护配置。create-admin 需要业务 INSERT 权限，无需超级用户。

`DEPLOYMENT_ENVIRONMENT` 默认为 `development`；生产环境显式设为 `production`。在生产启动前以运行账号和相同配置执行只读检查：

```bash
uv run python -m support_agent.cli preflight --production
```

检查发现 error 时退出码为 1；生产模式启动也强制执行严格预检并在错误时拒绝启动。检查包含 HTTPS Origin、入口保护及密钥、active 管理员、私有可写文档目录、`.env` 权限、运行角色及权限、迁移和 RLS；预检不能证明真实代理、跨实例、恢复或业务验收。建议私有文档目录使用绝对路径和 0700；预检要求目录不是符号链接且不授予 group/other 权限。使用 `.env` 时建议设 0600，0400 也可接受。新容器目录按私有权限初始化；已有卷由部署方单独检查权限，不自动修改旧数据。详细结果仅供受信运维人员查看。

## HTTPS 与进程管理

可使用 systemd 运行上述 uvicorn 命令；WorkingDirectory 指向项目，User 使用专属普通账号，EnvironmentFile 指向 0600 配置，设置 Restart=on-failure、UMask=0077。为模型/解析子进程保留执行权限，不使用会阻断现有隔离子进程的随意沙箱配置。文件目录和 PostgreSQL 应由系统服务分别管理。

在 Nginx/Caddy 终止 TLS，后端仅监听回环。可从 [Nginx 示例](../deploy/nginx.conf.example) 开始，替换域名和证书并检查目标环境；示例假设 Nginx 直接面对客户端。后端所在主机只允许受控代理访问回环端口，数据库不得暴露公网。Compose 的主机端口也仅绑定回环，镜像默认 `--no-proxy-headers`。需要代理头时须覆盖容器启动命令，显式使用 `--proxy-headers --forwarded-allow-ips=实际已知代理地址`；容器网关不等于 127.0.0.1，须在实际网络确认 Uvicorn 的直接对端并限制可访问该地址的主体，不要使用 `*`。反向代理要求：

- 转发同一个域名下的 `/`、`/assets/`、`/chat/`、`/widget.js` 和 `/api/`；保留 Authorization 与 Origin，不开放通配 CORS。
- 管理页面要求 HTTPS；HTTP 到 HTTPS 重定向、HSTS 由代理配置。WEB_ORIGIN 与用户实际访问 Origin 精确一致，否则写请求 403。不要混用 localhost 和 127.0.0.1。
- 只信任确定的代理 IP；Uvicorn 使用 `--proxy-headers --forwarded-allow-ips=127.0.0.1` 时，代理必须**覆盖**客户端传入的 X-Forwarded-For，不能透传伪造头。公网直连关闭代理头解析。否则匿名 IP 限流可能失真。
- 上传代理限额可设 6 MiB；应用限制文件 5 MiB，上传请求体上限为 5 MiB 加 65536 字节 multipart 开销，其他请求体上限为 128 KiB，读取请求体预算为 30 秒，不是整个请求的超时，也不改变 Provider/Agent 时间预算。代理 `proxy_read_timeout` 示例设为 180 秒，它限制两次上游读取之间的间隔，不是整个请求的绝对期限；流式等待约 140 秒超时，启用 HTTP 入口限制时流式响应还有 150 秒上限，代理超时不会延长应用上限。未知结果使用同一幂等键查询/重试，不生成新键盲目重发。
- 示例在 `http {}` 中定义按客户端 IP 的速率/连接共享区，并在代理位置启用示例阈值及 429；部署方须结合实际流量调整并验收。客户端头、请求体空闲、连接保活、发送以及代理发送超时和头缓冲均有示例配置。`proxy_request_buffering off` 将请求体逐步送往应用，使应用开始读取后执行 30 秒总读取预算；这不是客户端到 Nginx 首字节的绝对期限。对公开 API、登录与所有 HTTP 请求增加代理入口速率/连接限制。应用已有持久模型准入和匿名创建/调用限制，但没有承诺抵御 DDoS 或高频 GET。日志不要记录 URI、查询参数、Authorization、Cookie、请求体或供应商 Key；尽量记录路由模板而非敏感路径。示例关闭 Nginx access log，告警另行配置并使用应用关联 ID 日志；还需审查和限制 Nginx error log 的内容、访问和保留，关闭 access log 不能保证所有日志保密。示例尚未在本机执行 `nginx -t` 或部署验证。
- 管理页面 CSP 禁止嵌入；仅 `/chat/{公开入口ID}` 允许网站 iframe。小组件宿主需允许本服务域名的 script-src/frame-src。跨站 iframe 的存储能力取决于浏览器隐私政策；被阻止时使用独立链接。

生产默认单实例；多实例投入使用前须验证一致性与故障行为。所有实例必须使用同一私有文档文件系统并具有一致的受限访问权限，同时共享数据库、入口密钥和阈值；仅共享数据库不能保证文档可读。

## 备份关系

一次可恢复备份必须关联三部分：

1. PostgreSQL（包括企业、认证、密文、发布、访客、用量、审计、迁移版本）。
2. DOCUMENT_STORAGE_ROOT 私有文档目录及权限。
3. 与该批密文对应的 CREDENTIAL_MASTER_KEY、CREDENTIAL_KEYRING 全部所需历史版本及 CREDENTIAL_ACTIVE_KEY 标识，与数据库备份分开加密保存；恢复数据库及旧备份所需的旧密钥不能提前销毁。PUBLIC_RATE_KEY、HTTP_RATE_KEY 和其他受保护运行配置也应安全保留；更换 HMAC 密钥会改变计数命名空间，不能当作限额恢复保证，必须协调所有实例的维护窗口。

**密文所需主密钥版本丢失将导致对应模型凭证无法解密；仅恢复数据库或重生成主密钥不能恢复原 API Key。** 访客令牌及认证数据包含在数据库备份中，备份必须受限访问。

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

SSE 代理需关闭响应缓冲（应用返回 X-Accel-Buffering: no），保持至少 180 秒读超时，长于约 10 秒心跳间隔；应用自身上限仍然生效。阶段实时发送，最终答案先完整校验再分段交付；断连后先查记录，不能新建幂等键盲目重发。新增版本密钥/保留配置及 CI 见 [P7 运行维护](P7_RUNTIME.md)。

P8 配置预检、三类健康接口、可选本机 Compose 与显式迁移说明见 [P8 部署](P8_DEPLOYMENT.md)。相关新增表也必须授予运行角色最小表权限并保留 FORCE RLS。


P10 当前迁移为 0010_http_ingress；新增共享入口计数表只存 HMAC 与短期计数/租约，须给予运行角色正常 SELECT/INSERT/UPDATE/DELETE 权限，不授予跨业务租户旁路。生产入口开关、同实例组密钥/数据库一致性及尚未验收的容量边界见 [P10 记录](P10_ACCEPTANCE.md)。静态检查与可选只读 schema 检查见 [P7 运行维护](P7_RUNTIME.md)；检查不会执行迁移。

上线前逐项记录目标环境检查与未执行项，见 [生产上线检查清单](PRODUCTION_CHECKLIST.md)。

代理缓冲及读超时的语义参考 [Nginx 官方代理模块文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)：读超时约束相邻读取间隔，不能当作整个响应的绝对时限。示例与说明只做源码/文档核对，未执行 `nginx -t` 或 TLS 部署。
