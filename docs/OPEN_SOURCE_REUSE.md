# 开源调研与复用

2026-10-29 针对性源码审查，非完整安全审计。通过 GitHub API 读取目录树、固定提交，并下载必要文件至工作区外临时目录只读检查；没有整仓复制、运行参考项目或批量移植。链接均固定到实际检查版本。个别下载曾失败后重试；下表仅列最终实际读取的文件/片段。未运行上游测试，不承诺上游行为已验证。

| 参考项目与提交 | 检查过的源码模块 | 可复用或借鉴内容 | 处理方式与理由 |
| --- | --- | --- | --- |
| [Sight](https://github.com/orwa-mahmoud/sight/tree/0ea264a2547a6fffcb4fec958e59dc0e267b8eb1) | `backend/src/infrastructure/persistence/postgres/models/{user_tenant,conversation,message}.py`、`repositories/conversation_repo.py`、`backend/alembic/versions/a83dce9a149a_enable_row_level_security_on_tenant_.py`、`backend/tests/integration/test_tenant_rls.py`、`backend/src/drivers/api/v1/tenants/routes.py`、`backend/pyproject.toml`、`LICENSE` | 成员关系唯一约束、消息角色、tenant 过滤 + 事务租户上下文 + RLS 默认拒绝、真实非超级角色隔离验证 | 借鉴至 `models.py`、`dependencies.py`、`db.py`、迁移和真实 PG 测试。没有采用首个企业自动选择方式；增加复合 FK、FORCE RLS、明确企业选择器。重型 DDD、Redis、RAG、渠道不适用。 |
| [Enterprise Customer Service Agent V2](https://github.com/iwcdoit/enterprise-customer-service-agent-v2/tree/c1db4a4f363cb72c4b31ef739c27142c4a26c429) | `src/customer_service_app/services/{tool_registry,conversation_service}.py`、`api/routes_conversations.py`、`migrations/versions/0001_baseline.py`、`tests/test_conversation_service.py`、`pyproject.toml`、`LICENSE` | 先校验会话归属再读取消息；ToolSpec、执行上下文及 jsonschema 校验分离 | 借鉴至会话服务及 `tool_protocol.py`，直接依赖 jsonschema。拒绝复制携带 DB session/search client 的执行上下文、行业表及 handler；避免错误中回显原始参数。现有依赖/调用链与本阶段范围不匹配。 |
| [OpenLivery](https://github.com/sarrazola/openlivery/tree/07810e4ce1f4f226131883a2346ae6bac93e6376) | `apps/api/app/models.py` 中 User/Client/Agent/AgentTool/Conversation/Message/PortalUser、`deps.py`、`routers/agent_tools.py`、`services/tools/{specs,runner}.py`、`tests/test_agent_tools.py` 中 CRUD、Schema、SSRF 相关用例、`apps/api/pyproject.toml`、`LICENSE` | 工具元数据独立持久化、按归属查询工具、未知工具拒绝，工具参数和平台上下文分离 | 借鉴定义存储与统一入口；不采用 agency/client/行业/渠道模型，不实现 HTTP/MCP 执行及密钥保存。该 pyproject 仅含测试配置，不能据此推断全部依赖许可证；本项目无其代码/依赖传递。 |
| [AgentDesk](https://github.com/huabeitech/agent-desk/tree/9f211c0d799ebc57463d465fc7a34ce39a9e3754) | `internal/ai/tooling/{registry,executor,registry_test}.go`、`internal/ai/runtime/tooling/tool_result.go`、`internal/middleware/auth_middleware.go`、`internal/repositories/conversation_repository.go`、`go.mod`、`LICENSE` | 引擎无关工具定义、集中风险/权限/参数体积边界、结构化工具结果 | 借鉴至工具协议与服务；不采用 Go/Eino/MCP/业务工具代码，也不照搬空白 allow-list 放行或认证失败 HTTP 200 语义。参考 repository 的通用 ID 查询不足以单独保证本项目多租户隔离。 |
| [Chatwoot](https://github.com/chatwoot/chatwoot/tree/e2151d769963a5451d5dc74d33ef319398330f87) | `app/models/account_user.rb`、`app/models/conversation.rb` 的归属/关联片段、`app/controllers/concerns/ensure_current_account_helper.rb`、`app/controllers/api/v1/accounts/base_controller.rb`、`conversations/messages_controller.rb`、`app/policies/conversation_policy.rb`、`Gemfile`、`LICENSE`、`enterprise/LICENSE` | 全局用户 + 企业成员角色；先确定当前 account 并查成员；会话归属授权 | 借鉴至用户/企业/成员、租户依赖和归属服务。Rails 全平台移植成本高且超范围；明确不复制 enterprise 内容，未采用其企业版审计实现。 |
| [LangGraph](https://github.com/langchain-ai/langgraph/tree/ffc3336367e8139668d11e5f0b0e6def57e7c762) | `libs/prebuilt/langgraph/prebuilt/tool_node.py` 的 `_validate_tool_call`、ToolRuntime/InjectedState，`tool_validator.py` 的验证节点与弃用声明、`libs/{prebuilt,checkpoint-postgres}/pyproject.toml`、根及 prebuilt `LICENSE` | 工具名必须命中注册表；可信运行时上下文不由模型参数提供；校验可独立于执行 | 借鉴至数据型 ExecutionContext 和验证/执行契约。ValidationNode 有弃用标记且依赖编排/消息运行时；本阶段没有推理循环或 checkpoint 必要性，按要求不安装 LangGraph。 |

## 维护状态与调查限度

检查时 API 元数据中 Sight、Enterprise V2、AgentDesk、Chatwoot、LangGraph 均非 archived；pushed_at 的 UTC 日期依次为 2026-07-28、2026-09-07、2026-10-20、2026-10-29、2026-10-28。OpenLivery 已固定取得提交与源码，但未保留完整仓库维护元数据，不据此断言维护活跃度。提交时间、星数或 README 不等同实现质量；没有完整漏洞/issue 检索、上游测试执行或平台运行验收，故只采用经当前需求验证的设计，未直接接入上游运行时。

## 许可证核对与决策

检查上述仓库根 LICENSE 和已列文件头；已读目标文件未发现单独的冲突授权声明。此判断不覆盖未读目录、第三方 vendored 代码或整个依赖树。Sight、Enterprise V2、OpenLivery、LangGraph 为 MIT；AgentDesk 为 Apache-2.0；Chatwoot 根授权对普通目录为 MIT，明确排除 `enterprise/`，后者生产用途需要企业订阅授权。不能根据 GitHub 的仓库级标签覆盖目录/文件特例。

没有移植任何参考仓库源码或提示词：同栈候选已具体评估，Sight 与 Enterprise V2 的上下文、领域层、会话/工具运行时依赖超出本阶段；OpenLivery 的渠道与 agency/client 模型不符合本项目统一成员身份；Go/Ruby 实现不适合直接移植；LangGraph 会引入明确禁止且没有用途的编排依赖。这里采用的是通用关系模型、归属检查顺序、双层隔离和工具治理方法，独立编写当前需求下的代码，并用成熟库完成基础机制。

因此不存在需保留上游代码头的移植文件；未来新增源码移植时必须在此登记原仓库/固定提交/来源文件/目标路径/许可证和版权声明/修改说明，并保留所需授权文本，不能把本文当成未来复制的预先授权。

## 实际依赖复用

| 直接库 | 用途 | 许可证与处理 |
| --- | --- | --- |
| FastAPI / Pydantic v2 / pydantic-settings | 路由、OpenAPI、类型与配置验证 | MIT，使用官方包，不修改源码 |
| SQLAlchemy 2 / Alembic | ORM、事务、约束、显式版本迁移 | MIT，同上 |
| psycopg / psycopg-binary | PostgreSQL 驱动 | LGPL-3.0 系列；使用独立安装的未修改库，发行时保留包内 LICENSE/NOTICE，二进制附带组件授权也须保留 |
| argon2-cffi | Argon2id 密码哈希 | MIT；底层 bindings/Argon2 授权以安装包 LICENSE 为准，保持原包完整 |
| jsonschema | 标准参数 Schema 验证 | MIT；本项目收窄 Schema 关键字，不自行实现验证器 |
| Uvicorn | 本机 ASGI 服务 | BSD-3-Clause |

主要直接依赖的安装包 LICENSE/COPYING 已实际读取，包含 psycopg 的 LGPL 文本和 Uvicorn 的 BSD 条款；未修改它们。精确运行/开发/传递依赖版本见 `uv.lock`；安装发行版元数据的许可证清单见 `DEPENDENCY_LICENSES.md`。本项目不重新打包上游源码或二进制，标准包的许可证文件保留在安装包中。发行安装器/容器/离线包时必须一并包含第三方许可证和 psycopg 二进制附带声明，不能只带本表。未对未安装的参考平台完整依赖树作授权通过结论。

## 自行实现的部分

本阶段服务授权策略、会话生命周期、opaque session 生命周期、管理员保护、配置版本冲突、租户 RLS 策略、审计事务、错误净化和工具执行拒绝由本项目实现；哈希、ORM、JSON Schema、HTTP/OpenAPI 使用上述库。未运行上游平台，不声称其完整实现安全或维护质量获验收。

## 第二阶段：知识、检索与模型边界（2026-10-30）

继续使用上表固定提交；不把第一阶段已读 README 当作本阶段源码审查。主模型读取以下相关实现及片段，terra 补充存储/预算/pgvector 只读分析；未运行上游服务或测试，也没有移植源码/提示词。

| 参考项目 | 本阶段实际检查的源码模块 | 采用与代码落点 | 未采用内容、授权与理由 |
| --- | --- | --- | --- |
| Sight（同上固定提交） | `backend/src/infrastructure/rag/{parser,chunker,retriever}.py`；`backend/src/application/documents/use_cases/process_document.py` 的 processing 提交、重设租户上下文及失败清理 | 借鉴格式分派、分块重叠、租户过滤与“处理状态先提交，索引原子替换”；落实 `ingestion.py`、`services/knowledge.py`、`retrieval.py`。直接依赖它也采用的 pypdf、python-docx，实际解析本项目四格式 | MIT。未采用 tiktoken/Embedding/RRF/Redis/重型 UoW；上游部分解析无当前所需的进程/ZIP/内容资源边界，查询文本日志也不照搬。这里是 PG FTS，不能因看过 RRF 就声称混合检索。 |
| Enterprise V2（同上固定提交） | `services/rag_service.py`；`infrastructure/knowledge_ingestion/markdown_chunker.py`；`services/knowledge_lifecycle_service.py` 的 tenant 命名空间及旧索引清理 | 借鉴先做可回答性门禁、保留 Markdown 标题/内容摘要、更新与删除索引生命周期；落实 `ingestion.py`、`services/chat.py`、知识服务 | MIT。未采用行业路由/FAQ 识别、外部向量引擎、Reranker、跨异步任务降级及原始异常日志；不移植它的整个知识治理框架。 |
| AgentDesk（同上固定提交） | `internal/ai/rag/{answer,retrieve_search,index_cleanup_helpers}.go`；`internal/services/storage/safety.go` 的名称清理、MIME 嗅探与主动内容拒绝 | 借鉴无检索命中回退、检索限定 KB、结果 hydrate 后复查有效性、先清索引再重建；文件名仅显示，存储路径全为服务端 UUID。落实 `storage.py`、`retrieval.py`、知识/对话服务 | Apache-2.0。Go 运行时不兼容；不照搬“取前三 hits 即引用”或问题/答案日志，因为不能证明答案引用正确，也可能泄露内容。这里额外逐字校验 quote 并在生成结束复查来源。 |
| OpenLivery（同上固定提交） | `apps/api/app/services/{knowledge,providers}.py`；`apps/api/migrations/versions/0007_provider_credentials.py` | 借鉴独立加密凭证、引用解析与 Provider 边界；落实 `credentials.py`、`providers.py`、`services/model_configs.py` | MIT。拒绝 agency/行业/渠道/共享部署密钥回退；不采用全库拼上下文、全量向量加载后 Python 排序、无检索命中仍塞首块等策略。本项目不改旧迁移、不删除旧配置表，也不从它的加密列名推断加密安全性。 |
| LangGraph（同上固定提交） | `libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py` 的 `pre_model_hook`、历史有效性和 `remaining_steps` 分支；已读根/prebuilt MIT LICENSE | 借鉴模型输入历史与持久历史分离，预算属于调用边界；落实 `services/chat.py` 的成功轮次选择与字节预算 | 未安装。`remaining_steps` 是工具循环步数，绝非自动 token 裁剪；历史裁剪需调用方实现。当前单轮有界 RAG 不需要编排图、checkpoint 或工具循环。 |
| [pgvector](https://github.com/pgvector/pgvector/tree/44624c1f8d17327943fbe9a62fa96b3fbd59d2b2) | `src/vector.c` 的维数、NaN/Infinity 校验；`src/hnswscan.c` 的 ef_search、discarded 候选迭代、内存/扫描预算；`LICENSE` | 完成候选评估，保留 `Retriever` 接口；当前落点为 PostgreSQL 原生 tsvector/GIN，无 vector 依赖或索引 | PostgreSQL 许可。本机 `pg_available_extensions` 无 vector；不改已有 PG 安装或强装扩展。未来 ANN 必须验证租户过滤后的召回、维数、Embedding 版本与重建预算。 |

本阶段源码读取在固定提交上进行；不据此声称这些项目的最新分支、完整依赖树或全部漏洞状态已审计。AgentDesk/LangGraph/pgvector 的关键结论由主模型再读相关文件或片段核实。未复制任何第三方文件，所以没有源码移植落点或需补留的上游文件头；原包许可证保留在依赖分发中。

新增直接依赖：pypdf（BSD-3-Clause）、python-docx（MIT）、python-multipart（Apache-2.0）、cryptography（Apache-2.0 OR BSD-3-Clause，底层组件另有声明）、httpcore（BSD-3-Clause）、psutil（BSD-3-Clause）。psutil 用于本机跨平台监测解析子进程 RSS，避免 macOS 不支持特定 rlimit 时失去内存边界；不引入监控服务。已检查实际安装元数据和授权文件，版本与传递依赖见 `DEPENDENCY_LICENSES.md` / `uv.lock`。

标准机制参考：[PostgreSQL 全文检索](https://www.postgresql.org/docs/17/textsearch-controls.html)、[pypdf 文本/解压资源限制](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)、[cryptography AEAD/AAD](https://cryptography.io/en/latest/hazmat/primitives/aead/)、[Chat Completions 请求协议](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) 与 [JSON 输出契约](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)。协议兼容不等于所有厂商/模型已通过真实连接测试。

## P3 工具引擎增量

P3 未移植新的第三方源码、未增加依赖。沿用前两阶段已审查的 `jsonschema` 有界 2020-12 验证、SQLAlchemy/Alembic、PostgreSQL RLS/唯一约束、FastAPI/Pydantic 及 psutil；使用 Python 标准库 subprocess/resource 的受限进程。许可证清单不增加分发义务。

按[官方 Chat Completions 协议](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)扩展现有 `providers.py`：原生 function tools、assistant.tool_calls、tool_call_id、拒绝、finish_reason 和逐步骤用量，不引入 SDK/Agent 框架。按 [JSON Schema 2020-12 验证规范](https://json-schema.org/draft/2020-12/json-schema-validation)继续使用成熟验证库，保留已有安全子集，不接受任意引用或扩展执行代码。协议和部署注册表由本项目实现，没有复制官方示例或上游实现。

此前研究的 LangGraph 工具节点/循环、Sight 与 AgentDesk 的执行/来源边界只借鉴设计：采用服务端授权、明确状态、有界循环和结果关联；本阶段需求无需引入完整图运行时、工作流、外部网络工具协议或其全部基础设施。静态 `tool_runtime.py` 与持久执行服务是本项目实现，不从租户数据库加载 Python、Shell、SQL、模块路径或 URL。

## P4 离线增量

无新增第三方依赖、源码移植或提示词复制，继续使用上述库及原包许可证。本阶段实际查阅 [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)、[API 错误分类](https://developers.openai.com/api/docs/guides/error-codes)、[PostgreSQL FTS](https://www.postgresql.org/docs/17/textsearch-controls.html) 和 [pg_trgm](https://www.postgresql.org/docs/17/pgtrgm.html) 官方文档；没有借此宣称任何具体模型已实测。

采用协议中的工具往返关联和明确错误分类，落实 `providers.py`、`services/model_runtime.py` 的受配置能力/路由和有限降级。复用 PostgreSQL tsvector/GIN、事务 advisory lock、现有 ModelCall/FORCE RLS，落实中文词面召回与跨进程准入。实测原 simple FTS 三个中文问题无命中、英文基线有命中，选择生成二字组列、有限同义词和有界重排；未引入 pg_trgm 扩展（不需要额外相似度能力）、向量服务/Embedding（尚无必要性和真实质量证据）、大型路由/多 Agent SDK（现有适配器足够）。

查询切分、通用同义词列表、预算/阶段记录、凭证变更交付检查及离线场景由本项目实现，不移植上游平台代码。部署级主密钥轮换只提供前置条件/恢复方案，未声称已实现或验证；源码来源与依赖许可证记录沿用且没有新增授权义务。

## P5 产品化

继续直接依赖既有 FastAPI/Starlette（StaticFiles、FileResponse、Cookie）、Pydantic、SQLAlchemy/Alembic/PostgreSQL、AES-GCM 和 JSON Schema；复用本项目 P1–P4 身份、RLS、检索、工具循环、审计与用量机制。前端使用浏览器原生 ES Modules、DOM、Fetch、Web Crypto 和有限会话存储，无运行/构建框架依赖。公开交付和前端为本项目实现，没有复制上述仓库源码或引入第三方网页模板/素材。Prettier 仅作为临时格式化工具使用，不成为项目依赖，也不分发其源码。原有依赖许可证记录不变，主密钥轮换没有因产品化伪装为已实现功能。
