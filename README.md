# kefuagent · 通用客服 Agent 平台

可独立部署的多租户客服产品：管理工作台、知识库、模型凭证、客服会话、只读工具、公开客服链接和网站嵌入。Python / FastAPI / PostgreSQL 模块化单体；没有行业连接器、任意代码插件、Redis、Celery 或向量服务。

**当前 0.7.0（P8）**：增加企业客服队列、负责人分配、内部协作备注和轻量 SLA；会话级可追溯摘录记忆；真实数据运营 Dashboard 与访客反馈；只读配置预检及可选 Compose。保留 P7 的检索、安全 SSE、密钥维护和保留策略。真实模型/摘要语义、GUI 和容器部署仍未验收，P7 远端 CI 首次超时。见 [P8 实施与验收](docs/P8_ACCEPTANCE.md) 和 [可选部署](docs/P8_DEPLOYMENT.md)；[P7 记录](docs/P7_ACCEPTANCE.md)、[P6 记录](docs/ACCEPTANCE.md) 保留。

## 本机启动

要求 Python 3.11–3.14、PostgreSQL 15+、uv；本机使用 Python 3.13 / PostgreSQL 17。管理后台使用原生 ES Modules，资源随 Python 包提供，无 Node 构建或 CDN 依赖。

```bash
cd support-agent-platform
uv sync --locked
# 当前工作区已经初始化集群和 .env，只启动，不重新 init：
./scripts/local-postgres.sh start
# 仅在确认目标独立数据库并取得授权后执行迁移：
uv run alembic upgrade head
# 仅首次，在本机交互设置登录名与 >=12 位密码，无默认账号：
uv run python -m support_agent.cli create-admin
uv run uvicorn support_agent.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

集群已经运行时无需重复 start；本机已有 `.venv` 也可使用 `.venv/bin/python`、`.venv/bin/alembic`、`.venv/bin/uvicorn`。**只有全新本机安装**才执行 `uv sync --locked` 后的 `./scripts/local-postgres.sh init`；已有 `.env` 或 `.local/pgdata` 时脚本拒绝覆盖。它创建本项目独立 dev/test 库，默认端口 55439；`PG_BIN` 指向 PostgreSQL bin 目录（macOS 默认 Homebrew PostgreSQL17），首次可用 SUPPORT_PG_PORT 改端口。外部 PostgreSQL、Linux、密钥初始化和权限配置见 [部署与恢复](docs/DEPLOYMENT.md)。

打开 [管理工作台](http://127.0.0.1:8000)、[健康检查](http://127.0.0.1:8000/api/v1/health)、[Swagger](http://127.0.0.1:8000/docs)、[ReDoc](http://127.0.0.1:8000/redoc)。浏览器地址须与 WEB_ORIGIN 完全一致，默认使用 `127.0.0.1`，不混用 localhost。

当前迁移 head 为 **0009_operations**。服务启动检查版本及非 SUPERUSER / 非 BYPASSRLS 运行角色，不会自动建库、迁移或初始化用户。0007–0009 已获得本项目 dev/test 升级授权；其他环境仍须先审查 SQL 再授权执行。禁止清库重装解决升级错误。

## 首次使用流程

1. 平台管理员登录，在“平台管理”创建企业管理员用户、企业；同一用户可加入多个企业。平台管理员没有隐式企业业务旁路，应使用有效企业成员身份进入工作区。
2. 企业管理员配置模型凭证，Key 只写入、不可回显。也可在“Agent 配置”选择 **离线演示**，无需真实 Key。模型配置包括 Base URL、Model ID、温度、输出上限、超时、能力声明、任务路由与备用模型。
3. 创建知识库，上传 PDF / DOCX / TXT / Markdown（每文件最多 5 MiB），查看解析状态、失败原因、分块和检索预览；支持重新处理与显式删除。删除资料立即停止检索。
4. 创建 Agent，填写说明/行为指令并授权知识库；在“工具授权”注册平台已安装的静态只读能力、给 Agent 授权。当前内置文本统计，没有行业工具或写操作。
5. 在“客服会话”发起内部咨询，查看消息、来源、运行阶段与失败原因。企业内部是**成员共享工作区**；普通成员不能修改企业敏感配置。管理员可标记人工接管、录入人工答复、恢复 AI 或结束会话；不是自动转接外部客服系统。
6. 企业管理员在“公开客服入口”创建草稿，显式选择可供访客使用的只读工具，再手动发布。复制独立链接或嵌入代码。没有可用模型时先用演示验证流程；不把演示当真实客服上线。
7. Dashboard、模型调用、工具记录、审计均来自真实数据库。Token 未知单独列出；费用没有可靠价格数据，始终显示未知。

## 配置与第三方模型

`.env.example` 仅含占位示例；真实 `.env`、`.local`、密钥、日志和临时文件被忽略。

| 变量 | 含义 |
| --- | --- |
| DATABASE_URL | 独立 PostgreSQL `postgresql+psycopg` 运行连接；角色无 SUPERUSER/BYPASSRLS |
| MIGRATION_DATABASE_URL | 可选独立迁移角色；HTTP 不使用此连接 |
| WEB_ORIGIN | Web/API 的精确同源地址；本机回环可 HTTP，其他地址必须 HTTPS |
| SESSION_HOURS | 管理会话有效期，默认 12 小时 |
| DOCUMENT_STORAGE_ROOT | 私有文档目录，默认 `.local/documents`，不得位于公共静态目录或备份目录 |
| CREDENTIAL_MASTER_KEY | 旧格式 32 随机字节 base64url 主密钥，无默认值；旧密文/备份仍需保留 |
| CREDENTIAL_KEYRING / CREDENTIAL_ACTIVE_KEY | 受保护的版本→主密钥 JSON / 活动 ID；见密钥维护文档 |
| RETENTION_*_DAYS | 默认空、不自动删除；须用 CLI 预览及确认执行 |
| PUBLIC_RATE_KEY | 独立至少 32 随机字符，用于匿名 IP 限流 HMAC；缺失时公开会话初始化返回 503 |
| MODEL_ALLOWED_HOSTS | 精确批准主机 JSON 数组，默认 `[]`，例如 `["api.provider.example"]` |
| ALLOW_EXTERNAL_MODELS | 默认 false；部署方确定模型能力和费用后才显式开启。本阶段未开启真实调用 |
| TENANT/USER/AGENT_* | PostgreSQL 持久化分钟/并发/UTC 日 Token 保守预算，详见示例与用量页面 |

缺少主密钥仍可启动并使用离线演示；保存/解密凭证会安全失败。密钥的一次性生成方法见部署文档。**主密钥与数据库密文匹配，丢失将无法恢复 API Key；禁止每次重启重新生成或直接替换。** 主密钥轮换提供维护窗口内的版本兼容读取、单企业原子重加密、检查和反向恢复 CLI，见 [维护说明](docs/P7_RUNTIME.md)；不提供无停机配置分发。普通企业 API Key 更新/停用/删除已实现。

第三方兼容模型示例（仅示意，需自行提供合法 Endpoint/模型）：

```json
{
  "name": "通用客服",
  "provider": "openai_compatible",
  "model": "your-model-id",
  "base_url": "https://api.provider.example/custom/v1",
  "credential_ref": "cred_primary",
  "runtime": {
    "temperature": 0.2,
    "max_output_tokens": 2048,
    "max_input_tokens": 8192,
    "timeout_seconds": 30,
    "supports_tools": true,
    "token_parameter": "max_tokens",
    "send_temperature": true,
    "routing": {"fallback": {"model": "your-fallback-model", "supports_tools": true}}
  },
  "behavior": {"instructions": "简洁回答，有依据再确认。", "language": "zh"}
}
```

凭证通过 `/api/v1/model-credentials` 保存 `{ref, api_key, enabled}`，ref 以 `cred_` 开头。API Key 不强制 `sk-` 格式，只校验安全认证头字符/长度；AES-256-GCM 随机 nonce，AAD 绑定企业及不可重命名引用。API、日志不返回明文或密文。在途轮换/删除阻止旧结果交付，保留真实可得用量。

Base URL 可自定义，但必须通过部署方白名单、HTTPS:443、公网 DNS 和固定 IP 连接检查。禁止数字 IP、私网、回环、用户信息、查询参数、跳转和环境代理。自建服务需要批准的公网 HTTPS 域名，暂不支持内网模型。Token 参数、温度、Tool Calling 是管理员能力声明，不能证明厂商兼容。上游适配非流式 Chat Completions；前端 SSE 实时显示阶段，答案经检查、持久化后分段交付，不承诺上游逐 token 首字延迟。不支持厂商私有协议、Responses 或任意自定义认证头。无工具能力模型在确需工具时明确失败/按配置降级，不伪装成功。

主/备用与 qa/extraction/reasoning 路由共享当前 Provider/凭证。只对明确模型不可用或不支持工具尝试备用；认证、未知网络结果、超时不盲目切换。有限 HTTP 重试与未知用量规则见 [运行安全](docs/OPERATIONS.md)。ChatGPT 订阅不是 API Key。

## 公开客服与嵌入

公开链接形如 `/chat/PUBLICATION_UUID`；网站可以使用工作台生成的：

```html
<script src="https://your-domain.example/widget.js" data-agent="PUBLICATION_UUID" defer></script>
```

脚本仅创建独立 iframe，无管理 Token 或 API Key。访客必须主动开始会话，获得仅限该入口/版本/会话的随机令牌，数据库只存哈希；令牌不出现在 URL，浏览器仅保存在当前标签页 sessionStorage，12 小时过期，结束后失效。每个访客独立对话，服务端固定企业和 Agent，不接受访客传入 tenant_id/agent_config_id/conversation_id；管理认证不接受 Visitor 令牌。无需开放跨站 CORS。

发布记录和访客表 FORCE RLS；全局 public_routes **仅**保存随机入口 ID、企业映射和创建时间，无聊天、凭证或 Agent 配置。发布固定 Agent 配置版本；变更配置/知识库授权后必须重新发布。下线、撤销、重新发布、Agent 停用或发布者失去管理员身份均阻止旧会话访问；重新发布会切换发布者为当前企业管理员。撤销不可恢复，需创建新入口。

公开工具须同时满足发布白名单、现有 Agent 授权、静态绑定、只读/低风险、JSON Schema 与每次执行和交付复核；模型输出不是授权。文档与工具结果始终为不可信数据，不能执行用户/模型生成的 Python、Shell、SQL。

匿名限制由 PostgreSQL 原子计数：同入口/IP 每滚动分钟最多 3 个新会话、每 UTC 日 20 个；每企业每日最多 1000 个新会话；每访客每分钟最多 6 轮、总计 30 轮、单消息最多 2000 字。IP 仅保留按入口 HMAC，不信任未经批准的代理头。保留企业/Agent 模型限额，访客不冒充发布者消耗个人配额。幂等重放不重复计数。生产反向代理仍需一般 HTTP/连接限流和容量验收。

## 知识、工具与历史边界

- 中文二字组 + GIN 和英文 `simple` FTS，中英词汇扩展、有界多路召回、统一多 KB 合并/RRF，无向量/语义模型检索。词面召回不保证语义相关；无法识别所有冲突或提示注入。
- 绑定知识库的 Agent 可在同一轮检索、调用工具，再让模型选择引用。服务器核对当前企业/知识授权、文档版本、逐字原文后构造摘录答案。`grounded=true` 只证明来源/摘录通过校验，不证明文档真实或语义充分；无证据/明确冲突时 unresolved。
- 保留原 `/chat` 与 `/agent-turns` API；无知识绑定的普通对话是未验证模型文字。演示 Provider 只演示固定回答、检索原文与文本统计，不能验证真实中文多轮推理。
- 最多 5 次推理、4 次工具、整轮 120 秒；工具与解析有隔离子进程和资源上限，**不是恶意插件安全沙箱**。写工具/审批仍禁止。
- 请求作用域 `(tenant, conversation, idempotency_key)`；同键同输入重放，不同输入 409。浏览器对结果未知的 AI 发送复用原标识；人工录入回复没有幂等保证，网络中断后先核实历史。
- 新增内部和访客 `/stream` SSE（非流式接口保留），可区分检索/模型/工具/完成/失败，租约过期归类未知结果，不自动重发。已撤权工具或公开已失效知识来源的历史 payload 会被遮蔽；数据库仍保留已发生记录，不等于全链路隐私擦除。

## API 与结构

完整契约以 `/openapi.json` 为准，Swagger 可用 Bearer 认证；内部业务 API 还需 `X-Tenant-ID`。浏览器使用 HttpOnly / SameSite Strict Cookie，写操作验证精确 Origin。平台身份不绕过企业成员验证。

| 范围 | 主要 API（前缀 `/api/v1`） |
| --- | --- |
| 认证、组织 | `/auth/*`、`/web-session`、`/users`、`/tenants`、`/memberships` |
| 工作区、Agent | `/workspace`、`/workspace/statistics`、`/setup-status`、`/agent-configs`、`/{id}/knowledge-bases` |
| 模型 | `/model-credentials`、`/model-calls`、`/usage-limits`、`/agent-configs/{id}/test-connection` |
| 知识库 | `/knowledge-bases`、`/documents/{id}`、`/documents/{id}/chunks`、检索/重处理/删除 |
| 内部会话 | `/conversations`、消息、`/chat`、`/agent-turns`、`/calls`、`/handling` |
| 工具、审计 | `/tools`、`/tool-capabilities`、Agent 工具授权、`/tool-executions`、`/audit-events` |
| 公开管理 | `/publications`：创建草稿、发布/下线、撤销 |
| 访客 | `/public/{pid}`、`/sessions`、`/{sid}/messages`、`/turns`、`/status`、`/end`，仅 Visitor 令牌 |

```text
src/support_agent/
  api/、services/             # 请求契约、业务、授权与事务
  web/                        # 真实管理后台、公开聊天、小组件，无构建依赖
  models.py、*_schemas.py      # 数据与接口
  providers.py、credentials.py # 模型传输与 AES-GCM
  retrieval.py、search_text.py # PostgreSQL 检索
  ingestion.py、storage.py     # 四格式解析、私有文件
  tool_protocol.py、tool_runtime.py、tool_worker.py
  dependencies.py、main.py、db.py、config.py、cli.py
migrations/                   # 0001–0009 增量迁移
scripts/、tests/、docs/
```

## 验证与已知限制

```bash
uv run python scripts/check.py
# 可选开发检查，生产运行不需要 Node：
node --test tests/web.test.mjs
```

检查脚本执行 Ruff、格式、dev/test Alembic 差异和有界 PostgreSQL/Mock 回归。外部环境必须指定独立 TEST_DATABASE_URL（库名含 test），不模拟真实数据库、不清库；测试只追加随机数据并删除自身创建的文档。P6 基线 51 项 Python / 4 项 JS；P7 为 54 / 5 项；P8 最多 56 / 6 项，Python 单次全量硬上限 60 秒。离线质量评测和 CI 说明见下方链接。

已在本机隔离副本验证数据库、文档和密钥恢复；未进行真实模型、浏览器 GUI、生产 Linux/HTTPS 或负载验收；不承诺已完成生产质量验收。SSE 只在最终校验后交付答案，尚无上游逐 token 输出、匿名人机验证、审批写工具、完整全渠道人工工作台、全链路隐私擦除或无停机密钥分发。保留策略默认关闭，CLI 执行需要显式确认。内部成员共享企业会话可见性；负责人限制人工控制，不是个人私有收件箱。

常见问题：401 检查登录/访客令牌期限；403 检查成员角色、Origin 与企业；409 检查版本、忙会话与幂等键；413/422 检查文件与 Schema/地址白名单；503 检查数据库、主密钥、PUBLIC_RATE_KEY 和迁移。失败响应仅分类/关联 ID，不回显输入/堆栈。不要用清库或关闭安全校验解决。

P7 专项：[离线质量评测与检索](docs/P7_QUALITY.md)、[SSE / 密钥轮换与恢复 / 数据保留 / CI](docs/P7_RUNTIME.md)。`uv run python scripts/evaluate_quality.py --compare OLD_REPORT.json` 可生成同版本比较；不提供默认开启的真实模型评测。

详细资料：[架构](docs/ARCHITECTURE.md)、[开源来源](docs/OPEN_SOURCE_REUSE.md)、[运行安全与保留](docs/OPERATIONS.md)、[Linux/备份/升级](docs/DEPLOYMENT.md)。本项目当前不接入任何行业系统。项目代码采用 [MIT License](LICENSE)，版权署名 koajsj；第三方依赖保留各自许可证，见 [依赖授权](docs/DEPENDENCY_LICENSES.md)。


## 日常客服运营（离线演示）

1. 按上方交互命令首次创建管理员，再在平台管理创建企业、用户和 admin/member 关系；无默认密码。
2. 创建 `demo` Agent，导入 TXT/Markdown/PDF/DOCX 到知识库并授权 Agent；无需真实 Key。新建会话咨询知识或使用静态只读工具，Mock 只验证流程。
3. 在客服会话标记待人工，管理员分配有效成员；客服在“我的会话”接管、回复、记录内部备注、标签及分类，再恢复 AI 或解决。内部备注不展示给访客，不发送给模型。并发版本冲突需重新打开读取，不自动覆盖。
4. 在公开入口发布演示，用两个独立访客会话验证隔离；后台接管后用访客刷新历史读取人工回复，在结束前提交满意/不满意评价。
5. 运营概览选择 7/30 天或不超过 90 天 UTC 半开区间。未知用量及费用单列；引用验证率和 AI 解决数均不是回答正确率。轻量 SLA 的口径见验收文档。
6. 长对话由 Agent turn 自动触发旧用户摘录摘要，查看版本及来源范围。近期完整轮次、旧摘要和当前证据分别处理；摘要不作为事实证据。真实语义保留能力尚未验收。

```bash
mkdir -p .local/documents && chmod 700 .local/documents  # 自建私有目录，不指向备份
uv run python -m support_agent.cli preflight  # 只读，非零退出时按分类修复
# Liveness: /api/v1/health/live
# DB/角色/迁移 readiness: /api/v1/health/ready
# 初始化及必要配置: /api/v1/health/setup（未就绪返回 503）
```

新增 API：会话 `/operations`、`/collaboration`、`/summary`；企业 `/workspace/operators`、`/workspace/analytics`；访客 `/feedback`。认证、Origin、租户和访客令牌规则沿用原接口。备份与恢复继续使用数据库 + 私有文档 + 独立密钥三部分方案，不通过删除卷解决故障。
