# 独立部署、升级与恢复

运行环境使用 PostgreSQL、本地私有文档目录和 Python 服务。React Web 资源在构建机通过 Node 22.12+ 构建，随 Python wheel 提供；运行机不需要 Node 或 CDN。以下包含部署方案与本机恢复验证边界：P6 已在 Mac 隔离副本验证恢复，生产 Linux、HTTPS 反向代理和灾难环境切换尚未验收。

## Linux 首次安装

使用 Python 3.11–3.14、PostgreSQL 15+、pgvector 和 uv。0018 前须由独立受控维护身份安装并启用扩展，具体配置见下文「pgvector 与隔离 Compose」。以普通系统账号运行；应用目录与存储目录只对服务账号可写。

```bash
git clone https://github.com/koajsj/kefuagent.git
cd kefuagent
uv sync --locked
npm ci --prefix frontend
npm run build --prefix frontend
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

运行 `.env` 中的 DATABASE_URL 使用 support_app，**不加入 MIGRATION_DATABASE_URL**。仅在单独的受保护迁移环境中设置 MIGRATION_DATABASE_URL（support_owner），供下方显式迁移命令读取；迁移后退出该环境，再以运行配置创建管理员和启动 HTTP 服务。数据库账号密码含特殊字符时必须 URL 编码，不把连接串写进聊天、日志或命令历史。

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

配置 WEB_ORIGIN 为最终 HTTPS 地址（无路径），DOCUMENT_STORAGE_ROOT 为服务账号私有的绝对目录；MODEL_ALLOWED_HOSTS 是精确主机 JSON 数组，例如 `["api.provider.example"]`。默认仅连接公网 HTTPS:443；私有兼容模型须将精确 DNS 主机同时列入 MODEL_ALLOWED_HOSTS 和 MODEL_PRIVATE_HOSTS，并在 HTTPS:443 提供有效证书（可通过企业受控反向代理）。不开放任意端口、HTTP、重定向或环境代理，链路本地/元数据地址仍拒绝。ALLOW_EXTERNAL_MODELS 保持 false 进行离线验收；部署方自行确认供应商和费用后才开启真实调用，本阶段没有执行。

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

数据默认保留；凭证由管理员显式删除，公开入口可下线/撤销。文档/知识库物理删除因历史 JSON 引用依赖未完整预览而 BLOCKED；仅提供已知影响预览，不清理历史修订或文件。访客 Token 过期不自动删除会话、审计或幂等记录。备份保留期、完整隐私擦除、生产容量与生产恢复演练需部署方另行确认。P7 可按显式保留策略预览、确认和有界清理，默认没有自动任务或生产部署。

P6 本机演练使用现有测试库的只读 schema 副本，在全新随机数据库中经 CLI 初始化管理员、录入模拟业务，停止应用后执行 custom-format pg_dump，再 pg_restore --exit-on-error 到另一个空库；文档复制到新的私有目录，用对应模拟主密钥验证解密。表记录数、文档 SHA-256、迁移版本、14 张表的 FORCE RLS 和策略均核对。原 dev/test 行数、原文档及 .env 哈希保持一致；新演练库与 0700/0600 证据保留在本机，未上传。不等于已执行从零迁移或生产灾难切换。详见 [验收记录](ACCEPTANCE.md)。

SSE 代理需关闭响应缓冲（应用返回 X-Accel-Buffering: no），保持至少 180 秒读超时，长于约 10 秒心跳间隔；应用自身上限仍然生效。阶段实时发送，最终答案先完整校验再分段交付；断连后先查记录，不能新建幂等键盲目重发。新增版本密钥/保留配置及 CI 见 [P7 运行维护](P7_RUNTIME.md)。

P8 配置预检、三类健康接口、可选本机 Compose 与显式迁移说明见 [P8 部署](P8_DEPLOYMENT.md)。相关新增表也必须授予运行角色最小表权限并保留 FORCE RLS。


P10 的 0010_http_ingress 迁移中，新增共享入口计数表只存 HMAC 与短期计数/租约，须给予运行角色正常 SELECT/INSERT/UPDATE/DELETE 权限，不授予跨业务租户旁路。生产入口开关、同实例组密钥/数据库一致性及尚未验收的容量边界见 [P10 记录](P10_ACCEPTANCE.md)。静态检查与可选只读 schema 检查见 [P7 运行维护](P7_RUNTIME.md)；检查不会执行迁移。

上线前逐项记录目标环境检查与未执行项，见 [生产上线检查清单](PRODUCTION_CHECKLIST.md)。

代理缓冲及读超时的语义参考 [Nginx 官方代理模块文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)：读超时约束相邻读取间隔，不能当作整个响应的绝对时限。示例与说明只做源码/文档核对，未执行 `nginx -t` 或 TLS 部署。

React 源码更新后必须重新执行正式构建，再构建 wheel 或镜像；不要把 `frontend/dist-demo` 用于正式服务。Dockerfile 含独立 Node 构建阶段（本轮未实际运行 Docker）。Pages Demo 由管理员授权后手动发布，配置与验证见 [前端说明](FRONTEND.md)。


## P15-C 部署交接

当前源码迁移 head 为 `0020_conversation_idempotency`，本次未应用到任何数据库；0020 兼容性见下方专节。已有部署须另行授权升级，先完成一致备份并审查增量 SQL。0013 保留原主键，验证 Publication 与 PublicRoute 同租户；历史不一致会使迁移事务失败，不能自动重分配。Chunk 根 ID 在现有 FORCE RLS 下逐企业回填，不关闭策略、不使用 BYPASSRLS；迁移身份须有 DDL、tenant 枚举和必要 UPDATE 权限，不将其配置交给 HTTP 服务。回填不完整将被 NOT NULL 约束拒绝。0014–0016 新增客户、关联、工单、事件、提醒、附件和客户记忆共七表，须授予运行角色必要 CRUD 并保留 FORCE RLS；不授予 RLS 旁路。

`user_memory_consents`、`user_memories`、`conversation_read_cursors` 仍须必要 CRUD 和 ENABLE/FORCE RLS 的 tenant + user 策略。0012 的历史隔离验证不代表 0013 已执行或兼容性验收。0013 移除旧的全代次 document/position 唯一键，建立版本及当前行约束，保留旧代和人工修订；数据增长须纳入备份容量计划。不能在线同时运行新旧知识写入代码，升级时停止写入/排空处理任务。0013 downgrade 明确阻断；回退需独立的数据保全方案。

Compose 的 app 宽限停止时间设为 180 秒，供 Uvicorn 收到终止信号后排空请求；这不是保证外部调用或工具执行完成。先关闭入口并等待在途请求与文档操作完成，再停止 app，确认退出后才停止数据库。超过宽限期会被强制结束，未知结果须查记录并按原幂等键协调，不盲目重发。镜像通过 exec 形式启动 Uvicorn，运行 UID 10001；新卷初始化的目录权限和已有卷的 UID、权限应在目标环境核实。不要通过递归修改或清空已有卷解决权限问题。

上线入口至少配置 HTTPS、精确 Origin、代理拒绝未知 Host 并固定上游 Host、覆盖转发头、代理速率与连接限制，并启用 `HTTP_LIMITS_ENABLED=true` 和所有实例一致的 `HTTP_RATE_KEY`（或按配置使用 `PUBLIC_RATE_KEY`）。限制密钥、阈值及代理信任范围必须一致；预检无法替代对真实代理和直连路径的验证。详细交接、恢复闸门和责任见 [P15-C 运维交接](P15_C_OPERATIONS.md)。

健康检查连接容器回环地址但使用 `WEB_ORIGIN` 的域名及端口作为 Host；系统外探针也应使用该规范 Host。应用 Host 校验按配置的 hostname 执行；反向代理应拒绝未知 Host 并固定发送规范域名，核查其他虚拟主机是否允许绕过。


## 私有部署新增能力（0014–0016，未执行）

一个实例只允许一个企业；初始化后不再创建第二企业。已有多企业库会拒绝启动/业务访问，须由运维另外审查拆分，不自动迁移、合并或删除数据。身份、成员、tenant_id 与复合 FK 保留。

本地模式沿用 DOCUMENT_STORAGE_ROOT。S3 模式设置 DOCUMENT_STORAGE_BACKEND=s3、S3_ENDPOINT（HTTPS 原点）、S3_BUCKET、S3_REGION、S3_PREFIX，以及受保护的 S3_ACCESS_KEY/S3_SECRET_KEY，可选 S3_SESSION_TOKEN。部署账号仅授予指定 bucket/prefix 的读取和条件新增；上传只使用服务生成的 tenant/UUID 键。普通 path-style S3 兼容端点需支持 SigV4 与 If-None-Match 条件 PUT；目录 bucket/特殊端点未支持。412 后核对相同内容，未知写入结果保留 DB 登记并以原键重试。禁止把 bucket 暴露公开读取。参考 [AWS 条件写入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html) 与 [SigV4 请求格式](https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html)。当前只有静态实现，实际兼容性、IAM、TLS、故障和版本策略待验收。

对象存储不能用目录备份代替：在停写/排空窗口记录 DB 批次、bucket/prefix、对象版本清单与摘要、生命周期、加密配置及恢复所需的密钥。先恢复到全新隔离 bucket/prefix，不能直接连接生产对象位置。S3 凭证不等于数据加密密钥。版本感知物理删除继续 BLOCKED，配置生命周期不能作为完整隐私擦除证明。

可选 Worker 使用与 app 相同镜像、运行角色和受保护环境，通过 `docker compose --profile worker up -d` 启用；本轮没有执行该命令、构建镜像或启动容器。也可由进程管理器运行 `python -m support_agent.worker --interval 30`，或用 `--once` 执行单批。每批最多 100 张逾期工单和 100 条过期客户记忆；SKIP LOCKED、唯一提醒键避免并行重复。提醒仅为站内持久记录，不承诺外部送达；新加入/恢复的接收人可补发当前版本提醒。前端工单页提供查看和已读操作。记忆到期立即从读取接口过滤，Worker 只清除此份引用正文，保留来源/摘要墓碑，原消息和备份保留。

维护、备份、升级和恢复前停入口、排空 app，再停 Worker；恢复后核对未来/逾期工单、提醒去重、记忆有效期与撤回墓碑。Worker 失败输出固定分类，不打印 SQL、客户正文或凭证；需要运维监控进程、错误分类和积压。尚无可验证的 Worker 健康时间戳，管理端显示 UNKNOWN。0013–0016 不提供自动破坏式 downgrade；回滚应用需要匹配 Schema 的隔离保全方案。


## 专项 A 升级闸门（0017，未执行）

本节是待单独授权的升级清单，本轮没有启动服务或执行 SQL。先停入口、排空 app/Worker，完成可恢复的一致备份；核对目标库真实 revision 与约束，审查完整0001–0017链。0014/0016为本工作区未提交草稿，已修复默认唯一键重名；如果目标库已执行任何草稿，先独立比对实际结构，不能自动 stamp、重跑或修改其历史记录。

0017新增 erasure_requests、tool_approvals、budget_policies、cost_reservations、widget_sites、widget_bootstraps；运行角色需六表必要 CRUD，保留 ENABLE/FORCE tenant RLS，不授予 owner/superuser/BYPASSRLS。VisitorSession 新网站复合 FK 和 ToolExecution tenant+id 唯一键均保留约束；原 owner RLS 不变。运行身份不得使用迁移身份。备份范围须包含六表及与 DB 一致的 Keyring，不能丢弃原有成本占用或一次性审批记录。

升级有两项默认阻断变化：

- **付费模型**：没有启用的管理员金额策略，一律不派发（包括连接诊断）。MODEL_PRICES 须配置 context_window_tokens、cost_bound_verified=true、含时区 valid_until，并核实生效时间、币种、所有费用项及供应商强制 Token 上界；未确认保持关闭。管理员审核价格目录摘要并配置 Run/日/月/累计及可选 Agent 限额；重新配置价格后需再次审核策略。原 Token 配额仍有效。多实例须使用一致价格目录，否则不匹配实例拒绝调用；未知费用预留跨期保留，无自动对账释放。内部预算不替代供应商硬配额。
- **正式 Widget**：旧无网站绑定的 Visitor、无签名直链和仅 data-agent 的嵌入代码失效。设置固定部署 UUID `WIDGET_INSTANCE_ID`，所有实例共用 HTTPS WEB_ORIGIN、PUBLIC_RATE_KEY 和 Keyring；登记并验证网站，启用后取得最新集成配置，由网站真实后端按[签名协议](WEBSITE_INTEGRATION.md)签发。PUBLIC_RATE_KEY/实例 UUID 轮换会撤销旧凭证。网站后端必须实施本站授权/CSRF/限流，不向浏览器暴露密钥。不要用放宽 CORS 或取消网站验证恢复旧接入。

R3 固定事务命令至少需要另一位活动管理员；单管理员部署不能自批。Keyring 轮换现在覆盖模型凭证、审批参数、网站密钥，仍须停止旧配置进程并保留备份所需旧密钥。完整擦除当前 BLOCKED，任务登记不能作为数据已撤权/清除凭证。

恢复必须在隔离环境核对账本未决占用、审批执行记录、网站版本/nonce/一次性凭证及密钥一致性，再验证撤权与恢复重放；备份过期和删除抑制尚无可执行全链路保证。未经上述运行验收不得开放生产或宣称安全专项已上线。


## 专项 B 升级闸门（0018，未执行）

以下仅为操作员将来获得单独授权后的步骤，本轮未执行。保持 A 的 0017、R3、金额预算及 Widget 身份协议；该专项当时的 head 为 `0018_core_products`，44 张 ORM 表、37 张 RLS 表。

- 0018 前必须由受控数据库维护身份安装兼容 PostgreSQL 的 **pgvector** 扩展并启用 `vector`。迁移只检查扩展存在，不给应用扩展安装权、不自动安装、不放宽 FORCE RLS。基础 Compose 的 `postgres:17` 原镜像没有提供这一前提；现提供下文显式选择的新隔离卷配置，已有环境须单独审查受控安装方案，不能直接切换原卷。本轮未替换运行中镜像或运行容器。余弦/HNSW 与 RRF 的依据见 [pgvector 官方文档](https://github.com/pgvector/pgvector)。
- 离线审查完整 0001–0018 SQL，备份数据库、存储及 Keyring；先停入口并排空 app/Worker，再经授权升级。0018 只增加四表及 ModelCall.kind 枚举，不修改既有记录；运行角色需四表必要 CRUD，保留 tenant FORCE RLS/复合 FK，不使用 owner/BYPASSRLS。没有自动 downgrade。
- Embedding 当前固定 **1536 维**，兼容 `/embeddings` 的 `dimensions` 参数和浮点返回。知识库索引绑定 Agent、模型、精确端点和索引版本；查询 Agent 需使用相同已批准端点，并有此 KB 授权。不同端点显式降级关键词，不能混用向量空间。无价格、失效价格、未确认成本上界、未启用金额策略均拒绝付费请求；须同时配置 Embedding 模型和回答/重排模型的价格。Embedding 用量未知继续占用预算，重排采用已有 LLM，无新增供应商适配器。
- 产品任务默认关闭。经授权的进程管理器可使用 `python -m support_agent.worker --product-jobs --interval 30`；现有 Compose worker 默认命令仍只处理提醒/记忆到期，启用 B 需显式覆盖 command 加入 `--product-jobs`，本轮没有启动。每轮各处理一个清理、导出、草稿和一个 Chunk 索引批次，复用应用角色、存储与预算，不新增队列服务。
- 后台任务绑定申请人的真实 AuthSession，注销、到期、成员/Agent/知识授权撤销会阻断；管理员重新登录后可显式重排索引或重新确认导出。未知付费执行不自动重试或释放金额；不配长期服务用户来绕过撤权。
- 导出仅申请管理员本人下载，默认24小时；一个任务最多10万导出记录、每类1万关联、512MiB ZIP，超限失败，不发布部分结果。JSONL 逐行写入一致快照，附件分批校验；存储分片4MiB且先登记所有权。临时 ZIP 使用匿名 TemporaryFile，下载流结束关闭，进程退出由 OS 回收，不留下具名临时客户副本。
- 本地文件到期由产品 Worker 幂等清理。现有 S3 接口没有版本感知删除，因此 **S3 导出物理清理 BLOCKED**，记录 CLEANUP_BLOCKED/保留分片清单并重试，到期独立禁止下载；需经授权实现并验证所有对象版本、复制及保留规则后解除。不能以过期链接声称物理擦除。备份/供应商副本仍依现有独立保留策略，不属于导出包。

运行验收尚未执行：扩展/索引计划、实际 RLS/并发/升级、供应商1536维及用量、Worker中断/撤权、下载完整性/到期、本地/S3清理、人工草稿发送与浏览器交互均为 NEEDS_RUNTIME_VERIFICATION。


## 第一阶段升级闸门（0019，未执行）

0019 增加 5 个唯一键、14 个复合外键和 1 个 CHECK，绑定调用的会话/Agent、访客的会话/站点以及后台任务申请人的认证会话。历史迁移、RLS、权限和既有 ON DELETE 均保留；不一致历史行将阻止升级，不自动修复、清理或 stamp。须先由操作员独立审查 SQL、既有数据及索引开销、停写排空和一致备份，再另行授权迁移；本轮没有执行上述操作。

人工消息 POST /conversations/{id}/messages 现在要求 UUID idempotency_key；同账号/会话同键同内容返回原消息，不同内容 409。React、旧界面和 Demo 已同步；外部客户端须同步字段。草稿采纳继续以草稿状态、版本与稳定消息键防重复。

新模型输入保存有界、扁平化知识依赖；旧助手内容无法补证时保留原记录但拒绝交付/模型继承，原始用户问题可继续用于上下文。新历史复用只接受当前修订；历史来源交付仍遵循同代有效 lineage、当前发布及授权，逻辑删除/撤回/换代会遮蔽。已人工发送的 AI 草稿仍保留来源关系，不因 Message.source=manual 绕过撤权。

Token 在每次付费派发前按已核验 context_window_tokens 加输出上限逐步预留；明确零派发释放，完整 usage 结算，未知保留。日口径为请求起始 UTC 日，运行中/未知占用跨日保留，旧请求跨 UTC 日不再派发新步骤。供应商边界和真实账单须另验；旧未知预留不能据静态修改推定足额，须操作员复核后再开放付费调用。

本地存储用同 UUID 的 .pending 路径写完/fsync 后无覆盖发布；重试可协调本轮机制留下的 pending。旧版最终路径已经存在的不同内容不会自动覆盖，需人工审查；S3 全版本物理删除、完整擦除和备份清理仍 BLOCKED。详见[第一阶段报告](FINALIZATION_PHASE_1.md)。

## 会话创建幂等升级（0020，未执行）

`0020_conversation_idempotency` 接在 0019 后，只给 `conversations` 增加两个可空列 `idempotency_key` / `input_digest`、一个 `(tenant_id, created_by, idempotency_key)` 唯一约束及成对非空/64 位十六进制摘要 CHECK。不回填或猜测历史创建身份；历史行和访客独立认证创建保持双 NULL，员工 API 新建必须写入二者。表级 FORCE RLS、外键、角色与权限不变，无新增表。旧应用不能绕过 head 检查运行，新应用也不能连接 0019 库；必须停写排空、审查索引/DDL 锁开销、备份、另行授权升级后协调发布，不支持新旧版本混跑。本轮没有执行上述操作。

员工 `POST /api/v1/conversations` 必须包含 UUID `idempotency_key`；缺少时返回 422。稳定键范围是企业 + 已认证创建人 + 该键，输入摘要基于版本 1 与经过 Schema 规范化的 subject/channel（包括默认值）。同范围、同键、同输入返回同一会话的**当前状态**，不同输入 409；不同创建人/企业独立，不能用别人的键重放其会话。首次与重放均保持原 201 状态码和 ConversationOut，内部键/摘要不出现在该响应。关闭、分配或后续更新不会在重放时回退；原始摘要不按当前标题重新计算。

每次创建/重放先重新验证 Session、成员与企业，依次持有授权共享门、请求范围事务锁；会话、幂等列和首次审计一起提交，重放另记无正文审计。不调用模型，不自动换键重试。锁等待失败、提交结果未知或响应丢失均保留原键，客户端应显式同键重试。唯一约束提供最终数据库防重；真实事务隔离、并发和中断恢复仍需新隔离库人工确认。

React、旧网页和静态 Demo 已同步。两个正式界面按企业/用户/规范化输入摘要在标签页保存未确认请求键，正文不额外存入该记录；修改输入后再改回也保留原键。仅确认创建响应成功后清理；错误不自动重试。允许 sessionStorage 时刷新后同输入可复用；浏览器存储不可用仅有内存回退，失败时明确提醒不要刷新、先核对列表。退出登录、清理存储、关闭标签页和跨设备不保证恢复原键；外部客户端须自行持久保存并复用同一操作的键，不以标题相同判定同一业务意图。

应用引擎显式使用 `READ COMMITTED`：每条后续查询读取自己的语句快照，避免数据库默认被改成 `REPEATABLE READ` 时，等到请求锁后仍看不到先前创建结果或权限变更。依据为 [PostgreSQL 事务隔离规则](https://www.postgresql.org/docs/current/transaction-iso.html)与 [SQLAlchemy 引擎隔离级别参数](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#transaction-isolation-level)；这是源码声明，不是目标数据库实测。导出任务仍在独立事务显式使用 `REPEATABLE READ`，未改其快照。创建在拿到请求锁后再次 resume_context，处理等待期间自然到期的 Session；额外校验保留，不用少查几次数据库换取过期授权。既有授权门仍先于请求锁，创建服务不自行提交，最终由 function-scope get_db 在响应发送前提交/失败回滚。锁等待/死锁/连接故障不会被包装成幂等成功，也不自动重放事务。

客户端仅在当前页面仍有效、响应含合法会话 UUID 且企业/创建人匹配时确认并清理请求键；页面已离开或响应不完整时继续保留，使用原键显式核对。确认创建后，列表/详情加载失败单独提示“已创建”，旧界面列表刷新失败仍尝试打开。React/旧 API Client 统一在异步响应交付时检查当前代次和取消信号，SSE 释放流之后再次检查；取消/切换账号后的终态不再触发成功处理。取消仅停止客户端接收，不证明服务端已回滚，不能据此换键重复创建或发送消息。

幂等身份随会话保留，无 TTL 或后台清理，不能根据审计保留期删除。将来获批物理删除会话时，必须另行审查幂等墓碑和删除后重放规则；本轮完整擦除继续 BLOCKED。摘要不是匿名化证明，也不是替代原始输入校验的授权。不得把它公开或复制到日志。

升级操作员须核对新增列的 SELECT/INSERT 权限（现有表级授权通常覆盖新增列；列级授权需单独评审）、RLS 与唯一约束；不向运行角色增加 DDL 或 BYPASSRLS 权限。回滚不能直接 drop 列丢弃已接受请求的身份，down_revision 仅供图关系，downgrade 明确阻断并等待独立回滚审查。不能声称新增迁移已经应用。

## pgvector 与隔离 Compose

基础 `compose.yaml` 保持原镜像。新部署可显式叠加 [docker/compose.pgvector.yaml](../docker/compose.pgvector.yaml)：固定 `pgvector/pgvector:0.8.7-pg17-bookworm`，即 PostgreSQL 17 / Debian Bookworm / pgvector 0.8.7。标签及构建来源已对照 [pgvector v0.8.7 官方说明](https://github.com/pgvector/pgvector/blob/v0.8.7/README.md#docker)和 [Dockerfile](https://github.com/pgvector/pgvector/blob/v0.8.7/Dockerfile)；未拉取镜像，实际补丁版、架构、digest、扩展加载与运行兼容性仍须在隔离环境确认。部署前记录拉取的 digest，不能将版本标签当作镜像内容不可变证明。

叠加配置强制提供 `PGVECTOR_DATA_VOLUME`、`PGVECTOR_DOCUMENT_VOLUME`，两者均须是操作员确认不存在的新卷名，Compose 项目名也须全新。配置不会自动验证名称未占用；授权前由操作员核实，不能指向已有业务卷、备份或另一实例。另建受保护 `.env.compose`、新秘密文件和独立密钥；不能复制生产凭证、文档目录或数据库连接。以下只是**获授权后**的操作示例，本轮未执行：

```bash
export PGVECTOR_DATA_VOLUME=YOUR_NEW_UNUSED_DB_VOLUME
export PGVECTOR_DOCUMENT_VOLUME=YOUR_NEW_UNUSED_DOCUMENT_VOLUME
export KEFU_ISOLATED_PROJECT=your-new-unused-project
docker compose -p "${KEFU_ISOLATED_PROJECT:?Set a new unused project name}" -f compose.yaml -f docker/compose.pgvector.yaml up -d db
```

镜像安装扩展文件，不会自动在库中启用。由独立数据库维护身份连接已确认的新隔离库，另行批准后执行 `CREATE EXTENSION vector;`，核对 `pg_extension.extversion` 为 `0.8.7`、实际 PostgreSQL 17 版本及 HNSW 支持。应用和迁移角色不获扩展安装权，运行角色保持非 owner、NOSUPERUSER/NOBYPASSRLS 及最小业务权限。先启用扩展，再以单独的迁移配置按 0001–0020 顺序升级；所有后续命令都必须保留相同新项目、两个配置文件和新卷变量，迁移时额外叠加 `docker/compose.migration.yaml`。

此配置是隔离新部署的可审阅方案，不能证明现有数据库可原地升级；已有 PostgreSQL 的大版本、发行版、locale、扩展和备份恢复需单独审查，不自动更换镜像、挂载旧卷或删除卷。非 Docker 环境由 DBA 为目标 PostgreSQL 安装匹配的 pgvector；本机 INIT 脚本不承担扩展安装。Python 3.11–3.14 与 PostgreSQL 15+ 是源码兼容声明，本轮没有实际版本矩阵证据。
