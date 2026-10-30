# 通用多租户客服 Agent 平台

独立模块化单体后端。P1 提供认证、企业/成员、配置、会话、工具协议与审计；P2 提供知识库、凭证、全文检索与 RAG；P3 增量提供可运行、逐次授权、可审计的只读工具执行和有界模型循环。没有行业接口、前端、审批工作台、MCP、多智能体或工作流引擎。

P2 `/chat` 回答采用**经核验的原文摘录**：模型选择证据，服务器检查引用和逐字原文，再构造答案。`grounded=true` 只表示引用通过这些检查，不代表资料真实、语义完全相关或所有事实已被独立证明。没有真实模型凭证，本次只验证可控模型边界。

## 本机环境与启动

Python 3.11–3.14（本机 3.13.18）、PostgreSQL（本机 17.11）、uv。Unix/macOS 本机运行；Windows 原生解析资源限制未适配，可另评估 WSL。仅使用 PostgreSQL 和本地文件，不需要 Docker、Redis、Celery、向量服务或 LangGraph。

```text
support-agent-platform/
├── src/support_agent/
│   ├── api/、services/               # 版本化 API、业务与事务
│   ├── models.py、schemas.py、rag_schemas.py
│   ├── dependencies.py、security.py  # 身份、成员与租户上下文
│   ├── ingestion.py、storage.py      # 有界解析、本地 UUID 文件存储
│   ├── retrieval.py、providers.py、credentials.py
│   ├── tool_runtime.py、tool_worker.py # 静态能力注册、隔离进程与资源边界
│   └── main.py、db.py、config.py、cli.py、tool_protocol.py
├── migrations/                      # 0001–0003 基础/RAG；0004 工具引擎；0005 交付状态
├── tests/、scripts/
├── docs/                            # 架构、源码调研与依赖授权
└── pyproject.toml、uv.lock、.env.example
```

在本项目目录运行。当前工作区已有独立集群和 `.env`，使用 `start`，不要重新初始化：

```bash
uv sync --locked
./scripts/local-postgres.sh start
uv run alembic upgrade head
uv run python scripts/migrate_test_db.py
# 仅首次需要；交互输入身份和 >=12 字符密码，无默认账号/密码：
uv run python -m support_agent.cli create-admin
uv run uvicorn support_agent.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

本机已有 `.venv` 时，也可使用 `.venv/bin/python`、`.venv/bin/alembic`、`.venv/bin/uvicorn`。全新安装才执行 `./scripts/local-postgres.sh init`：它在 `.local/pgdata` 创建新集群和独立 dev/test 数据库，监听 `127.0.0.1:55439`；已有 `.env` 或集群时拒绝覆盖。`PG_BIN` 可指定 PostgreSQL bin 目录，首次初始化可用 `SUPPORT_PG_PORT` 改端口。脚本只支持 init/start/stop/status，不删除数据、不注册系统自启。

访问 [健康检查](http://127.0.0.1:8000/api/v1/health)、[Swagger](http://127.0.0.1:8000/docs)、[ReDoc](http://127.0.0.1:8000/redoc)、[OpenAPI](http://127.0.0.1:8000/openapi.json)。登录后在 Swagger Authorize 填 bearer token，业务请求另选 `X-Tenant-ID`。服务启动检查迁移版本，不会自动迁移/建表/初始化用户。

使用外部 PostgreSQL 时，按 `.env.example` 配置独立库，HTTP 角色必须 `NOSUPERUSER NOBYPASSRLS`。可用 `MIGRATION_DATABASE_URL` 指定单独迁移拥有者；迁移后由拥有者授予运行角色 schema USAGE 和必要表的 SELECT/INSERT/UPDATE/**DELETE** 权限。生产建议运行角色无 DDL 权限，且使用 TLS/HTTPS。不要对其他业务数据库执行本项目迁移。

## 新配置和凭证

| 环境变量 | 含义 |
| --- | --- |
| `DATABASE_URL`、`MIGRATION_DATABASE_URL`、`SESSION_HOURS` | 原有独立数据库、迁移角色与登录期限配置 |
| `DOCUMENT_STORAGE_ROOT` | 私有文件根目录，默认 `.local/documents`；不得放在静态服务、用户资料或备份目录中 |
| `MODEL_ALLOWED_HOSTS` | JSON 数组形式的部署方精确主机白名单；默认 `[]` 禁止配置任何模型地址 |
| `CREDENTIAL_MASTER_KEY` | 外部提供的 32 随机字节之 base64url 编码；没有默认值，不写入数据库 |

未配置主密钥也能启动和管理知识库，但凭证保存/读取失败会安全返回 503。主密钥应由部署方密钥管理器或受保护环境提供，安全保留并在重启时复用；丢失后无法解密现有凭证。不要每次启动重新生成，不提交到 Git、日志或公共文档。当前未实现主密钥在线轮换；轮换前必须另行设计重加密与恢复流程。真实 `.env`、`.local/`、密钥、日志均被忽略；本机 `.env` 为 0600、数据库目录为 0700。

企业管理员先通过 `/model-credentials` 保存 `{ref, api_key, enabled}`，再创建或更新现有 `/agent-configs`：

```json
{
  "name": "通用客服",
  "provider": "openai_compatible",
  "model": "provider-model-id",
  "base_url": "https://api.provider.example/v1",
  "credential_ref": "cred_primary",
  "runtime": {
    "temperature": 0.2,
    "max_output_tokens": 2048,
    "max_input_tokens": 8192,
    "timeout_seconds": 30
  },
  "behavior": {"instructions": "简洁回答", "language": "zh"}
}
```

示例域名需要替换并由部署方加入白名单。PUT 配置仍需 `expected_version`；旧配置保留且仍可读写，未满足新调用条件时不自动补凭证或调用模型。凭证 AES-256-GCM 加密，随机 nonce，AAD 绑定企业及不可重命名的 ref；API 仅返回 ID/ref/启用状态/时间，不返回明文或密文。凭证修改、删除和配置测试均要求企业管理员。没有平台共享密钥或跨租户回退。

Provider 使用非流式 Chat Completions、JSON object 输出、`temperature`、`max_tokens`；兼容厂商/模型必须支持这些参数，当前不自动切换协议或删除不支持参数。仅允许白名单 HTTPS 主机默认 443，禁止数字 IP、私网/回环/链路本地、多播地址、URL 用户信息/查询、跳转和环境代理；解析后连接已检查 IP，TLS 仍校验原主机。自建内网模型暂不支持，不能通过关闭检查绕过。

整体调用在有独立计时的子进程执行，超时终止；单 API 进程最多 8 个模型子进程。仅对明确的 429/502/503/504 最多重试一次，受同一时间预算限制；认证、格式错误、超时和未知网络结果不自动重试。重试仍可能产生额外费用，远端处理不会因本地断连接而保证停止。没有跨系统“恰好一次”承诺。

## API 与操作顺序

所有 API 位于 `/api/v1`，准确字段和响应见 OpenAPI。列表有分页上限。

| API | 权限与用途 |
| --- | --- |
| `/health`；`/auth/login`、`/auth/me`、`/auth/logout` | 健康、登录、当前用户、撤销会话 |
| `/users`；`/tenants`；`/memberships` | 平台管理员管理普通用户/企业，企业管理员管理成员；保护最后有效管理员 |
| `/agent-configs` | 成员读取，管理员创建/版本更新；新增非敏感 `base_url` |
| `POST /agent-configs/{id}/test-connection` | 企业管理员显式发起一次小型模型调用，返回调用状态及已知用量 |
| `/model-credentials`、`/{id}` | 管理员创建/查询/更新/删除加密凭证，ref 不可重命名 |
| `/knowledge-bases`、`/{id}` | 成员查询；管理员创建、PATCH 更新、DELETE |
| `/knowledge-bases/{id}/documents` | 成员列表；管理员 multipart 上传单个 `file` |
| `/documents/{id}`；`POST /documents/{id}/reprocess` | 成员详情；管理员删除或重新处理 |
| `POST /knowledge-bases/{id}/search` | 成员检索，输入 `{query, limit}`，返回分块/文档/排名/页码/章节 |
| `/conversations`、`/{id}`、`/{id}/messages` | 原有共享会话、开关和历史接口 |
| `POST /conversations/{id}/chat` | 成员发起有界 RAG 一轮，结构化返回 answered/unresolved/failed/running |
| `/model-calls`、`/{id}` | 管理员查询调用状态、失败分类、真实可得 Token、耗时与尝试次数；查询时将到期未收尾记录归为结果未知 |
| `/tools`、`/{id}/validate`、`/{id}/execute` | 定义/参数校验；携带完整执行上下文可运行授权的静态只读工具；旧式无 Agent 上下文请求保留 501 |
| `/tool-capabilities` | 管理员查询部署能力及精确输入/输出协议，无 handler 地址 |
| `/agent-configs/{id}/tools`；`PUT /agent-configs/{id}/tools/{tool_id}` | 成员查询授权；管理员显式授予或禁用，不隐式授权所有工具 |
| `POST /conversations/{id}/agent-turns` | 成员发起最多 5 次模型推理/4 次工具调用的一轮 Agent 对话 |
| `/tool-executions`、`/{id}` | 管理员分页查询实际状态与安全错误；结果交付仍检查授权 |
| `/audit-events`、`/platform/audit-events` | 当前企业管理员审计；平台管理员仅平台管理/认证事件 |

典型顺序：平台管理员创建用户/企业 → 企业管理员创建知识库、上传文档并确认 ready → 保存凭证并配置模型 → 显式连接测试 → 创建会话并调用 chat。

```json
{
  "agent_config_id": "CONFIG_UUID",
  "knowledge_base_ids": ["KNOWLEDGE_BASE_UUID"],
  "content": "资料里如何说明服务范围？",
  "idempotency_key": "NEW_REQUEST_UUID"
}
```

同一会话同一幂等键且相同输入返回同一 call；不同输入 409。在途调用返回 running，其他发送、历史追加和关闭会话 409。调用前提交用户消息和 reservation，网络期间不持有数据库事务/行锁；结束后重新验证用户/会话/成员，并检查引用分块仍属于当前企业、文档仍 ready、版本未变。模型失败保留用户消息和失败记录，**不写成功助手消息**；调用中撤权只完成内部记账，不把模型内容返回给失权者。

调用保留原请求 ID，当前响应也有服务端 `request_id`/`X-Request-ID`。进程中断后相同幂等键不会自动重新发送，到期标记 `interrupted_result_unknown`；次数未知为 null，未调用为 0。新幂等键是新的调用，不能用它假装恢复原调用。Token 仅保存提供方实际返回的值；缺失为 null。`cost` 当前始终 null，没有验证过的账单或定价信息，不伪造金额。

## P3 工具执行使用与边界

总计 **58 个 API 操作**；原有 `/chat` 不改变语义。`/agent-turns` 使用原生 Chat Completions `tools` / `tool_calls` / `tool` 消息，不要求 JSON object 最终回答；兼容模型须支持 function calling。P2 的 JSON evidence 协议继续独立使用。真实模型互操作和客服效果尚未验收。

管理员先查询 `/tool-capabilities`。当前部署只有 `text_metrics@1`：输入 `{text: string(maxLength=4000)}`，输出 `{characters: integer, words: integer}`，无网络/数据库访问或副作用。将该能力的 `key/version/parameters/output_schema` 精确复制到 `POST /tools`，另填 name、description、`execution_type: "read_only"`；再 `PUT /agent-configs/{config_id}/tools/{tool_id}`，请求 `{ "enabled": true }`。注册定义或授予 Agent 均不安装/加载代码。定义注册后协议/版本不可变，PATCH 只切启用状态；部署扩展需审查源码、静态注册和新能力定义，不开放租户插件上传。

```json
{
  "agent_config_id": "CONFIG_UUID",
  "content": "统计 hello world 的字符和词数",
  "idempotency_key": "NEW_REQUEST_UUID"
}
```

提交到 `POST /conversations/{conversation_id}/agent-turns`。流程为：验证身份/企业/会话 → 持久用户消息与 ModelCall reservation → 模型自主选择当前 Agent 获准工具 → 参数/授权/静态协议检查 → 持久 ToolExecution → 提交并释放事务 → 子进程执行 → 复查授权、保存实际结果与审计 → tool 消息回模型 → 最终 assistant 回复。连续调用可以跨模型轮次或一次返回多个请求，服务端串行执行，最多 4 次工具、5 次模型推理；120 秒 I/O 执行预算，单次工具最多 5 秒（内置 2 秒），数据库等待/收尾另计。每轮调用前刷新身份、配置版本、凭证与授权，无数据库事务跨模型/工具 I/O。

手工执行同样经过授权：`POST /tools/{tool_id}/execute` 在原 `arguments` 外必须同时提供 `agent_config_id`、`conversation_id`、`idempotency_key`、`tool_call_id`。不需要真实模型凭证。工具参数不提供可信 tenant/user/权限；这些只存在于服务端不可变 ExecutionContext。没有动态 eval/exec、Shell、SQL 执行入口，工具不接收数据库 session、密钥或 token。

安全边界：

- 只有部署代码中固定 handler、版本、输入/输出 Schema 且标记只读的低风险工具可执行；数据库声明只能收紧。`write`、非 low 风险或部署代码标副作用一律 `denied/approval_required`，没有审批流程或绕过入口。未部署能力 `tool_not_bound`；不一致 `tool_contract_mismatch`。
- JSON Schema 使用原有有界 2020-12 子集，拒绝未知属性、重复 JSON 键、NaN/Infinity、超过 16 KiB 参数、引用/正则/递归等扩展。Python/Shell/SQL 字符串只是文本，不能选择执行代码。输出也须匹配静态 Schema，至多 8 KiB。
- 工具进程每 API 进程最多 4 个并发，清空凭证环境、关闭继承 FD、使用临时空目录、限制 CPU/输出文件大小、监测 256 MiB RSS，超时终止进程组并有界回收；Linux 另限地址空间。它是可信部署代码的故障隔离，**不是操作系统安全沙箱**，不允许以此承载恶意第三方插件；RSS 采样有短暂超调，父进程崩溃不等同远端工作取消。
- 状态为 running → succeeded/failed/timed_out，执行前不获准为 denied。工具调用幂等作用域为 `(tenant, ModelCall, tool_call_id)`，整轮请求作用域为 `(tenant, conversation, idempotency_key)`；同键换输入或跨端点 409，运行中返回已有记录，重复模型调用 ID 拒绝。不同键是新请求。无模型或工具自动恢复循环；执行租约到期标 `interrupted_result_unknown`，工具超时不证明远端从未处理，未知结果不能当作成功或盲目重试。写能力始终禁用。
- 工具实际执行状态与交付权限分离：执行后撤权仍记录真实 succeeded/failed，`delivery_error` 标原因并清除待交付 payload；整轮 failed，不继续发送该结果。每次执行、模型传输、重放与公开历史读取重新检查权限；后续答案继承历史工具依赖（有界扁平引用），撤权后派生答案也被屏蔽。历史数据本身不被删除。
- 工具返回只作绑定 tool_call_id 的 `tool` 消息，不提升为 system 或权限来源。即使模型被诱导请求其他工具，服务端仍拒绝未授权/跨企业/写操作。提示词无法保证模型不受注入影响；最终自由回复固定 `grounded=false`，不宣称事实已核验。调用者应当文本显示结果，不能作为 HTML/代码执行。
- 用量逐模型步骤保存提供方实际返回值；任一步未知时聚合值为 null，步骤明细保留已知部分，费用不编造。异常/拒绝/超时均有安全分类，无内部堆栈。审计只保存标识、参数字段数/脱敏标志、授权结果、真实状态与耗时，不保存参数值、工具结果正文或真实凭证。reservation 的审计不标执行成功，finish 才记录实际结果。

## 文档、检索与回答边界

- 支持 PDF、DOCX、UTF-8 TXT/Markdown；单文件 5 MiB，上传路由总请求体另有 64 KiB multipart 余量，其他请求仍 128 KiB。只接受一个 file，无其他表单字段；声明 MIME 不作为可信证明。
- PDF 验签并实际解析，最多 100 页、文本总量 50 万字符、解压流有界；扫描图/加密/无可读文字文档失败，不提供 OCR。DOCX 检查 ZIP 结构、成员数、解压大小、宏，再解析段落、标题和表格；不请求外部链接。TXT/MD 拒绝二进制控制字节/错误编码；MD 保留标题来源。
- 解析子进程最多 8 秒 CPU、15 秒整体时间、512 MiB RSS 监测，Linux 另有地址空间限制；单 API 进程同时最多 4 个解析。RSS 采样会有短暂超调，子进程不是操作系统沙箱。保存页码（PDF）或章节，不编造 DOCX 页码。分块最长 1200 字符，相邻窗口重叠 200。
- 状态为 pending → processing → ready/failed；失败只返回安全分类。处理状态/令牌/30 秒租约持久化；重启后不会自动跑丢失的后台任务，租约到期后显式 reprocess。重复内容按企业+知识库+SHA-256 去重，返回既有文档；处理中拒绝竞争重处理。
- 文件路径仅由服务器生成的企业/文档 UUID 构成，目录不公开、拒绝符号链接，用户文件名仅作显示。先持久化拥有路径的行再写文件；重处理使用相同文件并验证摘要，原子替换分块。
- 删除先持久标为 deleting 并清分块，使检索立即不可见，再清文件与行；清文件失败 503 并保留清理记录，重试同一 DELETE 完成。未知或已删除 ID 统一 204（不能据此判断其他企业是否存在该 ID）。KB 删除也可重试，期间不再接受上传/检索。成功删除不留下可检索分块或原文件。
- 检索为 PostgreSQL `simple` FTS + GIN + `ts_rank_cd`，SQL 先限定企业、知识库、ready 和 generation；无语义/Embedding/向量/混合检索。中文连续文本没有分词，跨同义词、改写和含额外词的问题召回有限，可能需更精确关键词；无可靠命中则 unresolved。短指代问题只可用本会话最近成功用户轮次辅助检索。
- 最多读取最近 4 个成功机器轮次，并按配置的保守 UTF-8 字节/token 上界和消息框架余量裁剪完整轮次、证据；不无限加载历史，也不把该预算当真实用量。旧人工 assistant/tool 以及伪造 metadata 不进入可信机器历史，API 不能设置机器来源字段。
- 文档/历史/企业偏好都作为不可信参考数据，模型只能选择当前提供的原文，不授予工具、密钥或数据库权限。已知明显提示注入模式会保守过滤；错 ID、错 quote、额外自由事实、被删除/重处理引用均不通过。过滤可能误拒或漏检，未进行真实模型对抗验收，不能保证彻底识别所有注入或语义错误。答案与资料应作为文本显示，不能直接当 HTML/指令执行。
- 删除知识库不是删除已经发生的对话：历史消息/调用结果保留审计来源，可能含旧摘录；检索不再返回已删分块，后续模型历史和幂等重放也会剔除已失效来源。现阶段没有会话内容/备份的全链路个人信息擦除接口或保留期限策略。

## 隔离、安全与排错

登录沿用 Argon2id + 256 位随机 opaque bearer；数据库只存 token 摘要，注销/用户停用撤销。每请求复查用户、企业、成员；`X-Tenant-ID` 只是选择器，平台管理员也没有企业业务旁路。资源操作显式 tenant 过滤，知识/RAG 五表、原有四表及 P3 两表均 FORCE RLS；复合租户外键限制知识库/文档/分块/配置/会话关联。事务提交后必须恢复经过验证的租户上下文。

RLS 防遗漏过滤，不能抵御应用凭据泄露或任意 SQL；身份、成员、审计依靠服务授权。企业内是共享工作区，不是每用户私有会话。一般撤权影响后续请求，已授权在途操作可能完成；RAG 在返回前额外复查身份。生产运行角色应无 DDL 权限。

审计记录主体/企业/资源/结果/分类/请求 ID，不记密码、密钥、token、消息或原文。普通写入/审计同事务；多阶段文档和调用状态有明确提交边界及补偿。失败回滚后独立审计；数据库完全不可用时不能保证审计入库，只记安全关联日志。SQL 参数隐藏，不开启请求体、原始异常或含敏感 URL 的 access log。

- 401/403：检查 token、账户状态、企业/成员角色与 `X-Tenant-ID`，不要把 token 放 URL。
- 409：检查版本、幂等键、在途会话、文档处理租约、deleting 状态、最后管理员保护。
- 413/422：检查路由体积限制、文件实际内容、字段和输入预算；错误不回显原始输入。
- 503：检查 PostgreSQL、外部主密钥、文件权限或待完成删除；不要重建/清空数据库。
- Provider 失败：在 call 中区分 timeout/authentication_failed/rate_limited/network_error/invalid_response 等；HTTP 200 的结构化 failed 仍是失败，不能只看 HTTP 状态。

## 验证与交付记录

```bash
uv run python scripts/check.py
```

脚本执行 Ruff、格式、dev/test Alembic 差异检查及有界验收。外部环境必须显式指定独立 `TEST_DATABASE_URL`，库名含 test；不使用 SQLite 或模拟数据库代替 PostgreSQL。基础测试只追加随机隔离数据；文档测试会删除自己新建的测试资源验证清理，不清库、不触碰现有数据或备份。

第一阶段历史验收：7 个权限/完整性用例、非超级角色 RLS、初始迁移、32 个 API 操作、实际本机 HTTP 健康与文档页通过。第二阶段 2026-10-30 实际结果：

- 独立 dev/test 均增量升级至 `0003_runtime_bounds`，新增五表，原迁移未改；两库 Alembic check 无差异，离线升级 SQL 生成通过，没有降级/清库。
- `scripts/check.py` 通过：Ruff、54 个 Python 文件格式检查、两库迁移差异检查、**21 个验收用例**（最终 15.05 秒）。覆盖真实四格式解析、去重/重处理/失败/删除、ZIP/体积/RSS 上限、双租户 API/RLS/复合 FK、会话并发/幂等/机器来源、旧回归、模型错误/有限重试/未知用量/截断失败用量保留/超时子进程、SSRF/DNS 固定连接、密文篡改与租户绑定、撤权收尾、错引用/已删来源与已知注入模式。
- uv 锁文件和已安装依赖兼容检查、shell 语法检查通过。真实独立 Uvicorn 启动后健康、Swagger、ReDoc、OpenAPI 均 HTTP 200；33 个路径、52 个操作，操作 ID 唯一，multipart/认证/密钥 writeOnly 输出契约检查通过；临时 HTTP 进程随后停止。
- terra 完成设计、参考源码补充与实际代码定向对抗审查。主模型核实并修复锁读取的旧 ORM 状态、并发重复删除、网络整体超时、未知次数误记零和连接测试撤权后不收尾等问题，并增加对应验证。没有采用“逐字引用即事实可靠/全面防注入”的假设。
- 开发库用户/企业/模型凭证均为 0；真实 `.env` 0600，初始迁移与原测试内容保持不变。没有真实模型 API Key，没有外部模型或 Embedding 调用；受控响应/HTTP 解析验证不等于真实模型端到端验收。

P3 2026-10-30 实际验收：

- 用户确认后，独立 dev/test 增量升级至 `0005_execution_delivery`；两张新表 ENABLE/FORCE RLS、复合企业 FK 和幂等约束。两库 Alembic check 无差异，离线增量 SQL `.local/p3-upgrade.sql` 可审查。原 0001–0003 迁移及全部 P1/P2 测试源码未改；不清库、不降级。
- 最终 `scripts/check.py` 通过：Ruff、62 个 Python 文件格式、两库迁移差异及 **32 项验收，24.84 秒**（原 21 项 + P3 11 项）。覆盖真实工具进程、连续调用、协议/真实受控 HTTP 编码、参数/授权/租户边界、写操作拒绝、幂等/并发、中断结果未知与状态防覆盖、超时/异常/输出上限/凭证环境隔离、工具注入无法授予权限、历史派生授权与撤权收尾、审计一致性。
- 真实 Uvicorn 在 127.0.0.1:8781 启动；健康、Swagger、ReDoc、OpenAPI 均 200；39 路径/58 操作，操作 ID 唯一，新接口和旧式 501 契约存在，未认证查询返回 401。临时 HTTP 进程已正常停止，原 PostgreSQL 保持运行。
- 锁文件及 49 个已安装包兼容、shell 语法、可审查文件实际数据库密码扫描通过；`.env` 仍 0600，开发库 users/tenants 均 0，运行角色非 SUPERUSER/BYPASSRLS。没有新增第三方依赖。唯一 terra 完成只读安全复核，主模型已核实修复关键意见。
- 未调用真实模型、未产生模型 API 费用；Mock Provider/故障工具验证不能证明真实模型工具选择质量或抵御所有提示注入。没有审批实现、写工具、行业连接器、前端、生产部署。进程故障隔离不等于恶意插件沙箱；真实远端副作用的取消/未知结果与审批仍需后续专门验收。

压力、跨版本矩阵、Windows、生产 TLS/部署、密钥轮换、备份恢复和真实模型语义/注入对抗仍未验收。

源码来源、授权、采用/拒绝理由见 [OPEN_SOURCE_REUSE.md](docs/OPEN_SOURCE_REUSE.md)，完整安装依赖见 [DEPENDENCY_LICENSES.md](docs/DEPENDENCY_LICENSES.md)，设计与阶段记录见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)。没有自动提交、推送、发布或部署，也没有读取、修改或集成其他业务项目。

下一阶段应进行显式授权的真实模型 function calling、多轮客服质量和注入对抗验收；再评估审批/副作用连接器、中文召回、凭证轮换/恢复、数据保留及生产限流。当前不接入任何行业系统，不执行真实写业务。
