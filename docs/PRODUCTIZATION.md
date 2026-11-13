# 私有化产品化实施

本轮基线：2026-11-09，main `49fc85f`，包含既有未提交成果。只执行静态检查；禁止测试、构建、服务、数据库/迁移、模型和生产操作。源码完成不等于 Production-Ready 验收。


## 专项 B 当前矩阵（2026-11-10）

本节为最新源码结论，覆盖下方历史的“向量/完整导出/草稿未实现”状态；专项 A 的安全机制和完整擦除 BLOCKED 保留。仅单企业私有化部署，不增加 SaaS、独立向量服务、消息队列、依赖或测试体系。FIXED 是源码已修改，不是运行验收通过。

| 能力 | 状态 | 实际实现与边界 |
| --- | --- | --- |
| B1 Embedding 与索引 | FIXED / NEEDS_RUNTIME_VERIFICATION | pgvector VECTOR(1536)/余弦/HNSW；Agent/精确端点/模型/索引版本绑定；PostgreSQL Worker 每批一个 Chunk、增量/逻辑重建、持久状态/租约/显式重试。Gateway 逐 HTTP 金额预留/结算；未知用量不清零。 |
| B1 混合检索 | FIXED / NEEDS_RUNTIME_VERIFICATION | 当前已发布/有效代次与修订，KB 授权及文档/章节过滤；词法与向量 RRF 1/(60+rank)，可选预算内 LLM 排序；每个模型 I/O 后重查身份/授权/索引版本及所有候选来源；RAG 与 Agent 准备阶段接入。事务内工具知识查询仍为词法快照。 |
| B1 诊断 | FIXED / NEEDS_RUNTIME_VERIFICATION | 实际关键词/向量/融合/重排/最终候选、每 KB 失败、阶段及总耗时/索引缺失；向量失败公开降级原因，不伪装语义召回成功。候选不是已生成引用，正式回答继续复用引用校验。 |
| B2 客户导出 | FIXED / NEEDS_RUNTIME_VERIFICATION | 管理员本人、固定策略+范围摘要+人工归属/第三方审查确认、稳定申请键；Worker REPEATABLE READ 快照、批量 JSONL/附件 ZIP、manifest、私有分片/哈希、24小时授权下载、来源撤回/范围变更重查。失败不发布部分文件；本地过期清理可重试。 |
| B2 导出保留 | BLOCKED（S3物理清理） | S3 当前没有版本感知删除，保持 CLEANUP_BLOCKED 和准确分片清单；下载到期独立生效。无法承诺所有介质清除；内部备注/员工身份/原始协议/个人记忆/凭证/共享知识/备份/供应商副本按策略明确排除。 |
| B3 AI 草稿 | FIXED / NEEDS_RUNTIME_VERIFICATION | 独立 ReplyDraft 表及七态、原文/人工编辑、引用、拒绝/反馈、复制、审计/Trace/预算；只处理有权操作的人工会话，不调用工具。版本、上下文、授权、知识来源及有效期重查，只有明确人工确认的 accept_send 同事务写 Message 并记录发送回执，重复请求不再发送。 |
| B4 UI/契约 | FIXED / PASS（静态） | HeroUI3与现有组件；真实索引/诊断、导出预览/详情/状态/下载、工作台草稿/引用/Trace。OpenAPI、前端类型及正式 Adapter 一致；Demo 显示 NOT_AVAILABLE，无静态假实现。 |
| 完整擦除/知识物理删除 | BLOCKED | 新增向量、草稿原文/引用、导出 manifest/文件已加入依赖 UNKNOWN；不能以禁读、换版本或链接失效声称物理清除。 |

### 关键文件与数据关系

- `models.py`、`vector_type.py`、`product_schemas.py`、`api/product_capabilities.py`；0018 新增 knowledge_indexes、chunk_embeddings、customer_exports、reply_drafts，完整链18个迁移，44张ORM/37张RLS。0017和此前迁移本轮未修改，所有迁移均未执行。
- `providers.py` / `services/model_runtime.py` 增受控 Embedding；`services/search.py` / `vector_index.py` 整合检索、索引与诊断，knowledge/chunk_versions 在知识写事务内排队；chat/agent_turns 接入并保留原有权限/工具审批门。
- `services/customer_exports.py`：Customer→人工确认 ConversationCustomer→Conversation→客户可见 Message/Attachment/VisitorFeedback；Customer/关联 Conversation→Ticket→TicketEvent；Customer→CustomerMemory；白名单关联 AuditEvent 元数据。CustomerIdentity 模型不存在，不导出 Visitor/AuthSession token；AgentRun/Trace 由 ModelCall/审计投影表示，原始载荷按内部策略排除。单会话/工单混入另一客户时 BLOCKED，不猜测归属。
- `services/drafts.py` / `background.py` / `worker.py`：独立队列状态、真实原申请人会话、无永久服务用户授权；草稿从未混入客户消息流，生成请求与人工发送是两个操作。
- 前端 `KnowledgeIntelligence.tsx`、`CustomerExports.tsx`、`ReplySuggestions.tsx`、`types/product.ts`，复用正式 JSON/Blob Adapter、TracePanel 和现有工作台/客户详情，不新增 UI 库。

### 运行前提与剩余限制

pgvector须操作员另行安装/授权；Compose原PostgreSQL镜像未替换。Embedding只支持1536维且查询需相同批准端点；多模型/端点迁移、召回质量和HNSW过滤表现未验收。产品任务需显式 `--product-jobs`，默认 Worker 命令不处理 B 任务。登录到期阻断任务，需重新登录后显式重排/重新申请。大小上限、JSONL格式、内部信息/第三方审查策略、24小时导出以及 S3 清理解除条件见[0018部署闸门](DEPLOYMENT.md#专项-b-升级闸门0018未执行)。不提供完整自动PII识别或草稿事实正确性保证；人工审核不可省略。

PASS：Ruff/格式、126 Python AST、18迁移链及离线SQL/RLS/FK目标检查、TypeScript、44表ORM DDL编译、0018冻结SQL与ORM匹配、127路径/174操作OpenAPI元数据、专项A四个保护文件哈希不变。交付文件与最终Diff检查见[专项B报告](DEEP_AUDIT_REPORT.md#专项-b核心产品能力2026-11-10)。NOT_RUN：测试、构建、服务/DB/迁移、真实模型、浏览器、提交/推送/部署。所有动态行为均 NEEDS_RUNTIME_VERIFICATION。

## 专项 A 当前矩阵（2026-11-10）

本节保留专项 A 实施时的快照；最新 B 增量见上方矩阵。当时只处理擦除、R3、金额预算与可信 Widget。保留现有修改；未执行测试、构建、服务、数据库、迁移、模型、网站或存储网络验证，无提交/推送/部署。

| 专项 | 当前状态 | 实际实现 / 未解除边界 |
| --- | --- | --- |
| 用户/客户/会话完整擦除 | BLOCKED | 真实 ORM 全 FK 图、自由文本/JSON 列清单、可见计数与 UNKNOWN；真实管理预览、幂等登记、重复评估及审计。请求未获准，因此不会声称 ACCESS_BLOCKED/PURGING/PURGED。跨用户 RLS、共享记录合法保留、弱引用、文件版本、备份重放尚无法完整证明，不执行局部删除冒充擦除。 |
| R3 审批 | FIXED / NEEDS_RUNTIME_VERIFICATION | 参数加密、具体工具/资源/配置/授权版本与 SHA-256 绑定；独立管理员审批/拒绝/撤销/过期、请求人执行、执行前重查、一次性消费与 DB 命令/执行记录/审计同事务。当前只支持固定 desk 数据库命令；无安全幂等协议的外部副作用继续 BLOCKED，R4 永久拒绝。 |
| 金额硬预算 | FIXED / NEEDS_RUNTIME_VERIFICATION | 统一模型网关原子预留，单 Run / UTC 日/月 / 系统累计及可选 Agent 累计；Decimal 账本、价格目录摘要、结算/释放/UNKNOWN 跨期占用，超界冻结。缺失/过期/未确认成本上界/币种不符均不发付费请求。 |
| Widget 网站身份 | FIXED / NEEDS_RUNTIME_VERIFICATION | 精确 HTTPS 网站、固定文件归属验证、30天到期/启停/轮换、网站后端 HMAC 断言；部署 UUID / 发布 / 网站版本绑定；nonce 与 Bootstrap 单次消费；平台签名短期会话、逐次撤权复核、精确 frame-ancestors、无跨域 API 放行。网站真实后端/域名仍待接入。客户登录身份不在本协议中推断。 |
| 必要管理界面 | FIXED / NEEDS_RUNTIME_VERIFICATION | 数据擦除预览与阻断原因、R3操作详情/决定/执行、预算配置和真实账本、可信网站验证/轮换/接入配置。沿用 HeroUI 与现有组件；Demo 明确不模拟安全授权。 |

### 执行与配置边界

- 新增 0017_security_controls（六张 tenant FORCE RLS 表），应用要求迁移 head 0017。ORM 40表、RLS 33表；VisitorSession 增网站绑定，ToolExecution 增 tenant+id 唯一键供审批复合 FK。未执行迁移。
- 系统性检查发现**上一轮未提交迁移草稿**0014/0016 的多个唯一键使用同名默认约束；本轮只显式区分命名，并记录缺陷。已提交 0001–0011 未改，0012/0013/0015 未改，不靠修改已提交迁移隐藏问题。目标库真实结构未查询，升级前操作员必须核对，不擅自 stamp 或自动修库。
- 未配置/未启用金额策略时，所有真实模型调用（包括连接诊断）默认拒绝；离线 Provider 不收费，不绕过对真实 Provider 的检查。原 Token 配额仍独立生效。
- MODEL_PRICES 增 `context_window_tokens`、`cost_bound_verified`、`valid_until`。部署者需核验供应商强制上下文/输出上限、所有费用仅由已声明 Token 费率覆盖、用量字段语义与价格有效期；未确认则保持阻断。每次 HTTP 单独预留，移除底层隐式重试；主备回退各自预留。Embedding/Reranker 尚不存在（NOT_AVAILABLE），外部收费工具无真实实现（BLOCKED），未增加旁路。
- 已知单次完整用量按冻结费率结算；明确零次尝试才释放；不完整/超时/进程中断保持占用且不因换日释放。超过核验成本上界将保留较大占用并关闭付费策略。UNKNOWN 无自动释放/伪造供应商对账按钮；需要可信供应商证据的后续对账实现。
- 账期按平台派发 UTC 时间；未决项跨所有账期计入。内部定价与供应商发票/计费周期不同，缺少供应商硬配额时不能承诺外部账单绝不超支。供应商违反核验上限或使用不可计量额外费用也不属于平台可证明范围。
- R3 提案结束原回合，不在审批等待期间占用活动执行租约。批准后由原请求人执行固定操作；不额外调用模型。需至少另一位活动管理员；不能自批。审批参数不能原地编辑；新参数/资源/策略需新申请，旧摘要不能授权新操作。
- Widget 升级使无网站绑定的旧 Visitor token 失效，旧无签名直链和后台 iframe 预览停止创建会话；没有匿名兼容后门。配置 WIDGET_INSTANCE_ID 后按[网站接入协议](WEBSITE_INTEGRATION.md)实现网站后端签发。网站公开 ID/Origin/Referer 不作为秘密或单独授权依据。
- Keyring 轮换盘点现覆盖模型凭证、审批参数、网站密钥；所有加密写入共用轮换共享锁。仍须停旧配置进程、排空执行并保留备份所需旧密钥，不能以新包络轮换为理由删除备份。

完整擦除的解除条件：定义并审核主体/多参与人及合法保留规则；各 owner 的 RLS 可枚举协作授权；所有派生副本与 JSON 的可追溯索引；可锁定的跨介质清单、存储版本删除/失败重试；备份到期与恢复重放抑制。未满足时无执行确认值、无假进度、无 PURGED。

本轮 PASS：Ruff/格式、117 Python AST、17迁移离线 SQL/RLS/约束、TypeScript、246文件交付检查、40表ORM DDL和118路径OpenAPI元数据及Git Diff。具体证据见[专项审查报告](DEEP_AUDIT_REPORT.md#专项-a安全与执行控制2026-11-10)。生产可靠性仍 NEEDS_RUNTIME_VERIFICATION，整体不标记 Production-Ready。

## Phase 0：现状与改造依据

| 模块 | 已有真实实现 | 本轮切入与边界 |
| --- | --- | --- |
| 身份与部署 | Cookie/Bearer、成员角色、tenant RLS、复合外键 | 单实例单企业；已有多企业数据拒绝使用，不自动合并/删除 |
| 会话/人工协作 | 访客消息、SSE阶段事件、接管/分配、备注、标签、游标、评价、快捷回复 | 复用现有状态机；补客户/工单关联和转交事实上下文 |
| 客户与工单 | 无独立客户、工单模型 | 新增企业范围客户/人工确认关联、工单状态/分配/历史与通知，不以IP推断身份 |
| Agent与工具 | 有界循环、模型路由、逐次授权、静态只读工具、执行幂等/审计 | 补确定性风险策略和可追踪计划；审批/成本未知不得放行 |
| 知识与记忆 | 四格式隔离解析、词法FTS/CJK融合、generation/修订/历史、本人记忆/会话摘要 | HTML本地文本解析；语义向量/Reranker和客户身份授权须诚实区分 |
| 数据治理 | 固定批次/摘要、独立审计、UNKNOWN/RLS安全阻断 | 用户/会话/知识完整擦除仍有不可见和派生历史依赖，不以局部删除宣称擦除 |
| 模型/观测 | OpenAI兼容Chat、主备/任务路由、保守Token预留、白名单Trace/估算费用 | 复用Gateway，不假装已有Embedding/Reranker或金额硬预算 |
| 部署/运维 | Compose、HTTPS代理、健康检查、手工一致性备份/隔离恢复说明 | 修正文档版本/私有化边界；S3源码已补；恢复仍为受控手册流程，无自动恢复按钮 |

基线27张ORM表，本轮增至34张；0012/0013已存在但未提交，0013从未在本会话执行。全部新Schema只追加迁移，不修改历史迁移。重要数据链：tenant→membership/Agent/KB/conversation；conversation→messages/calls/executions/visitor/collaboration；message→用户级memory/cursor；document→所有generation/revisions；历史JSON/派生正文不受FK追踪。

## 设计与实施顺序

已读取 HeroUI、BoardUI Skill 与 Taste Skill/app-screens。实际使用 BoardUI MCP get_started/list_components/app-shell 及 HeroUI MCP 官方文档，沿用HeroUI3/React19/Tailwind4；BoardUI仅取页面范围、标题动作、表格与详情层级，不安装其Next/motion/图表组件。界面以客服当前任务为主，使用现有中性底色、语义状态、统一间距和文字层级；Widget保持移动浏览器布局。浏览器/Taste截图验收NOT_RUN。

按Phase1安全→Phase2自治→Phase3工具→Phase4知识/记忆→Phase5真实业务UI→Phase6运营→Phase7部署静态整合推进。完整擦除、第三方订单/通知、真实模型效果和运行时验收有证据才解除阻断；实施结果与剩余缺口如下；静态通过不代替产品验收。


## 专项 A 前的实施快照（2026-11-09，历史基线）

| 阶段 | 源码结果 | 尚未完成/解除条件 |
| --- | --- | --- |
| 0 盘点 | 34 ORM 表、27 RLS 表、14 路由模块；保留现有 Adapter、Gateway、知识与记忆实现 | 所有运行状态 UNKNOWN；不以历史验收替代当前验收 |
| 1 安全治理 | 单企业不变量；新命令授权门与撤权串行；成员变更稳定锁序；保留预览明确新 CRM/附件/记忆 UNKNOWN | 用户/会话/客户整体擦除与知识物理删除 BLOCKED，见下方证据 |
| 2 Runtime | 确定性 R0–R4 策略、词法意图/复杂度候选、带版本计划、模型循环、结果/来源复核和交接终止 | 不是语义分类器；R3 审批和金额硬预算未实现，不能提升权限 |
| 3 工具 | 六项固定 CRM/工单/交接/站内通知能力，复用知识搜索/会话查询；执行前重查、幂等、事件与审计同事务 | 订单与外部通知无真实业务接口；不接任意地址/SQL/Shell |
| 4 知识/记忆 | 五格式导入；隔离 HTML 文本提取；文档发布/撤回；新代/Chunk 修订撤回待发布；有来源且可撤回的客户引用记忆 | 向量、Embedding/Reranker 和语义混合检索未实现；客户记忆不自动发送模型 |
| 5 业务/UI | 客户 CRUD/人工关联/活动/近期工单；工单状态/分配/期限/历史/提醒；交接包；私有附件；管理导航覆盖22领域 | 可信网站身份、AI草稿建议、完整客户导出尚未实现；部分导航共用视图；Widget 为消息/阶段流+最终分段，非未经校验逐Token外发 |
| 6 网关/运营 | 复用 Chat 主备和任务路由；结构化路由编辑；显式内网 HTTPS 白名单；Trace 补风险/工具关联、预留状态；反馈质量/未知成本保留 | Chat 之外的 Provider Adapter 未实现；Token预留不是金额保证；客户交付仍 UNKNOWN |
| 7 私有部署 | 本地/S3实现、可选 PostgreSQL Worker、Compose profile、密钥/备份/恢复/升级手册与版本说明 | 镜像、TLS、IAM、实际S3条件写入、进程与恢复均 NEEDS_RUNTIME_VERIFICATION |

### 模块与数据映射

API→service→SQLAlchemy 模块化单体保持不变。`desk` 管理客户和工单，`customer_memory` 管理管理员确认的原话副本，`attachments` 管理会话文件所有权，`desk_tools` 提供固定 Agent 命令；`autonomy` 决定风险边界，既有 `agent_turns/model_runtime/tool_execution` 仍负责有界运行、用量和交付复核。Worker 只领取 PostgreSQL 有界批次，不增加 Redis、队列或微服务。

迁移：0014 新增 customers/conversation_customers/tickets/ticket_events/staff_notifications 与 Document.is_published；0015 新增 conversation_attachments；0016 新增 customer_memories。新表均 tenant FORCE RLS。客户→会话人工关联唯一；工单→会话/客户/负责人均复合 FK；事件/提醒→工单不可静默级联；附件→会话/访客、客户记忆→来源消息均 NO ACTION。来源消息 FK 使用现有 `(tenant_id,conversation_id,id)` 唯一键，禁止关联另一会话。

新文档默认未发布；0014 对现存文档保留原可用性（发布字段回填 true，仍受 ready/active/授权检查）。新代处理成功或 Chunk 修订会撤回文档；管理员按 generation+updated_at 确认发布，历史版本不自动恢复上线。首次全新导入的内置离线资料允许正常发布；重复导入不重发已撤回资料。HTML 不执行脚本、不拉取链接，处理常见 hidden/aria-hidden/内联隐藏样式，不实现完整 CSS 渲染可见性判断。

### 新增 API 契约摘要

公共前缀 `/api/v1`；正式完整字段以 `/openapi.json` 的声明为准，本轮只生成路由元数据，未启动服务。

| 资源 | 路由/规则 |
| --- | --- |
| 客户 | GET/POST `/customers`、GET/PATCH `/customers/{id}`；创建带稳定 idempotency_key，修改带 expected_version，修改仅管理员 |
| 关联/活动 | GET/PUT `/conversations/{id}/customer`；人工核实并匹配会话版本，拒绝覆盖身份和已有工单冲突；GET `/customers/{id}/conversations`、`/activity`（审计元数据，分页） |
| 导出/删除 | GET `/customers/{id}/export` 明确 profile_only/complete_export=false；DELETE 返回409，无擦除伪成功 |
| 客户记忆 | GET/POST `/customers/{id}/memories`、PUT `.../memory-consent`、POST `.../memories/{mid}/forget`；管理员启用/确认/撤回，有来源、1–365天、每客户最多100条有效引用；客户版本与记忆版本并发保护 |
| 工单 | GET/POST `/tickets`、GET/PATCH `/tickets/{id}`、GET `.../events`；新建幂等，修改版本匹配，负责人/管理员处理，管理员重分配；due_at 必须带时区，不宣称工作日历SLA |
| 提醒 | GET `/staff-notifications`、POST `.../{id}/read`，只取本人；唯一 ticket/version/user/kind 约束，站内提醒不等于送达 |
| 交接 | GET `/conversations/{id}/handoff`，持久摘要、当前可用知识来源、完整工具授权复核、待办工单及原因；缺失任务与交付 UNKNOWN |
| 附件 | GET/POST `/conversations/{id}/attachments` 和 `/public/{pid}/sessions/{sid}/attachments`；POST需 upload_id，最多20份/会话、5MiB/份；GET `.../{aid}/content` 强制下载，不内联执行 |
| 治理 | GET `/autonomy-policy`、GET `/administration`、POST `/administration/retention/preview`；HTTP不执行保留清理，无伪造恢复/集成成功 |
| 发布 | POST `/documents/{id}/publication`，管理员 generation+updated_at 乐观检查；撤回即停止当前检索和历史引用交付 |

客户记忆仅存已人工关联会话的 user 消息精确片段，不存模型概括。撤回/关闭清除副本正文，保留来源与摘要墓碑，同来源同内容不可恢复；更换来源或新文本不是跨来源完整隐私防恢复。到期立即停止读取，Worker异步清除正文，未运行/故障时旧正文仍在DB。所有源消息、备份、摘要与第三方副本需另行治理；摘要墓碑不等于无个人信息。未把客户记忆接到公共 Agent，避免将未验证身份的访客当作客户。

附件先提交 DB 所有权登记，再执行不可变存储写入并重查会话/权限；中断可能留下 pending，保留原 upload_id+内容重试，不发新键假装未知操作未发生。下载存储I/O后重查权限、可见性和SHA-256；访客只读本会话公开/本人文件。原始格式校验与资源限制不等于恶意文件扫描，不预览或执行上传内容。

### UI 与设计实际使用

HeroUI MCP读取 Button/Card/TextField/Input/Label/TextArea/Chip/Tabs/Table 官方文档；Table使用v3组合API。BoardUI Skill/MCP已实际获取 get_started、list_components、app-shell 和 sidebar 用法，作为导航/页面职责与列表详情布局参考，没有机械复制其 Next/motion/图表依赖。Taste已运行 `draw.mjs --app --kind support --screens inbox,list,detail,settings --theme light --keep palette,type --style framed-sheet`，保留现有字体/中性色，将工作框架与白色内容面板分层。浏览器/截图验收 NOT_RUN，不宣称视觉已验收。

导航对应：Dashboard/Inbox/Conversations/Customers/Tickets；Agent配置/Autonomy/Tools/Execution/Quality；Knowledge/Documents/Retrieval；Providers/Routing/Usage；Users/Integrations/Security/Retention/Recovery/Settings。复用现有真实 API；集成、恢复与设置明确展示配置或缺失能力，不用可点击假流程冒充后端。Demo与正式Adapter隔离，客户/工单/版本/记忆仅在虚构标签页保存；附件只演示元数据，不编造可下载正文。

### 阻断证据与解除条件

| 未完成项 | 证据/原因 | 解除条件 |
| --- | --- | --- |
| 用户/会话/客户完整擦除 | tenant维护上下文无法数尽user RLS的memory/cursor；新增CRM/文件NO ACTION、历史JSON、派生摘要/日志/备份不由FK追踪 | 独立审查可完整枚举且不绕过RLS的影响图，绑定版本/内容的预览、批准/锁/跨介质协调及恢复撤回策略 |
| 知识物理删除 | Document/全部代次/修订之外，call/result、message metadata、tool结果、反馈/摘要及存储版本未全量锁定枚举 | 完整引用索引与保留语义，版本感知存储、失败可恢复协调；未满足时DELETE继续409、无执行确认值 |
| 向量/Embedding/Reranker | 现有策略仅PostgreSQL词法FTS/CJK融合；没有嵌入索引或这两类Gateway请求 | 实施有模型/版本/维度/源权限绑定的增量索引及撤回失效、受控Provider与用量核算；当前NOT_AVAILABLE |
| R3审批、金额硬预算 | 高风险工具确定性拒绝；现有价格为估算、用量可未知，无金额原子预留 | 实施与payload/资源版本/审批人绑定的一次性批准，及定价覆盖/未知失败闭锁的原子成本预留；当前BLOCKED |
| 网站可信客户身份/完整导出/AI建议 | 只有匿名能力令牌+人工关联；导出仅档案；没有独立建议草稿调用/使用/核算链 | 实施由企业站点后端签名的身份映射和撤销，受限分页完整导出与审计，独立草稿运行和人工采纳流程；不能复用发消息路径冒充建议 |
| 生产可靠性 | 用户限制本轮静态检查，未运行应用或外部系统 | 另行授权目标环境迁移/RLS/锁/并发/幂等中断、Provider/存储、浏览器/Widget、备份恢复和部署验收 |

以上是明确未完成项，不能把本轮标为完整产品化或 Production-Ready。无新增依赖、锁文件、微服务、测试体系；无提交、推送或部署；既有未提交内容保留。依赖清单和锁文件、历史已跟踪迁移无diff，暂存区为空，HEAD仍为基线。

## 专项 A 前的静态验证记录

- PASS：Ruff/格式（144 Python 文件）、109 Python AST、16条线性迁移、离线SQL/RLS声明，新增复合FK目标唯一键检查。
- PASS：34张ORM表/索引PostgreSQL DDL编译；14路由模块、104个OpenAPI路径、128个schema元数据生成；109文件Python3.11语法。未调用app factory、endpoint、数据库或Provider。
- PASS：`npm run check --prefix frontend`（tsc --noEmit）；`scripts/check_delivery.py`扫描234个发布文件、JS语法/模块链接、HTML/本地Markdown链接与已知敏感模式，构建资源/Wheel NOT_RUN。
- NOT_RUN：测试、构建、应用/Worker/数据库/迁移、模型/S3网络、浏览器、备份恢复、生产环境。
