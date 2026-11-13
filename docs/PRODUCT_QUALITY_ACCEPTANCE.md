# 产品与工程质量专项验收

## 续作结论：以当前源码为准

2026-11-07 续作基线：本地 main / GitHub main 均为 `49fc85fbb5ba827507e4a6334a3a4daf995beb73`，待审业务与清理改动仍在工作区。本节是本轮静态结论；后文历史运行证据没有在本轮重跑，不能用来宣布当前实现已通过运行时验收。

| 原专项 | 当前源码证据与处理 | 状态 |
| --- | --- | --- |
| P1 客服消息闭环 | `api/public_delivery.py`、`services/public_delivery.py` 和 Visitor Adapter：人工期独立消息入口、会话锁与稳定幂等 ID、限频、访客/发布版本复核；AI 保留 turn/SSE，未知结果沿原模式恢复。无需重复实现 | FIXED / PASS（源码审查） |
| P1 实用工具 | `tool_runtime.py`、`services/tool_execution.py`、`services/tool_connectors.py`：四项客服只读能力加原 text_metrics；参数/输出 Schema、静态绑定、服务器授权快照及交付复核、进程资源限制。没有任意代码入口 | FIXED / PASS（源码审查） |
| Connector 边界 | 复用 materialize/still_current 与静态 Capability，不额外建设框架。真实 CRM/订单/工单缺接口、账号与权限资料，不编造实现 | BLOCKED（外部集成） |
| P1 队列与未读 | `services/operations.py`、会话 API、0012、ChatPage/useThreadScroll：活动/优先级/SLA 排序、成员独立单调游标、访客消息计数、底部滚动与新消息入口；内部备注不算未读 | FIXED / PASS（源码审查） |
| P2 人工 AI 质量规范 | 补齐 `QUALITY_REVIEW.md` 的中文复杂表达/同义、多文档、追问/条件更新、冲突/拒答、引用、工具与撤权审查；逐 claim 标明支持/部分支持/矛盾/未知、来源版本及评审依据。不恢复数据集、表单、自动评分器 | FIXED / PASS；实际语义 NOT_RUN |
| P2 个人记忆 | `services/user_memory.py`、`model_runtime.py`、UserMemory/ChatPage：精确来源、版本与新旧对照、同意/纠正/过期/撤回、实际保留输入的使用记录和本人查询；调用前提交事务，调用后短事务核算。本轮补齐 usage API 的明确响应 Schema | FIXED / PASS（源码与类型） |
| P2 Demo | App/DemoAdapter 保留跳过/重开/命名空间重置与完整人工闭环；本轮修复共享存储被删除后仍恢复旧内存的问题，并保留写入失败的内存降级。Vite alias 和 CSP 阻止正式 Adapter 混入 Demo | FIXED / PASS（源码与类型）；浏览器 NOT_RUN |
| P2 CI / Dependabot | 6 个 Action SHA 均经上游 Git commit API 核实；YAML 可解析，最低权限、版本注释、weekly Actions/npm/uv/Docker 更新及 PR 上限保留。CI 只有静态检查，3 分钟整体上限，无单项硬超时 | PASS；线上 CI NOT_RUN |
| P2 依赖 | npm audit 当前 0 项；42 个锁定 PyPI 包 OSV 查询无命中；本机安装的 40 包与锁定版本一致且附许可证，另 2 包当前平台未安装。npm 清单/锁与许可声明核对；没有升级/新增依赖 | PASS（指定静态范围）；镜像层扫描 NOT_RUN |
| 兼容性 | Python 3.11 语法解析；pyproject/uv.lock 为 >=3.11,<3.15；已安装包 Requires-Python 下限兼容。PostgreSQL 方言和 12 个迁移离线 SQL、复合键/RLS 声明审查；无实际版本矩阵 | PASS（静态）；Python 3.11–3.14 / PostgreSQL 15+ 运行兼容性 NOT_RUN |
| 开源治理 | 当前仓库 Description/Homepage/8 Topics 与目标一致，SECURITY/CONTRIBUTING/CHANGELOG/RELEASE_ACCEPTANCE 均存在。未改远端配置；Security Updates 与私密报告仍关闭，维护者需明确启用 | PASS；远端安全开关 DEFERRED |
| 测试禁令 | 无测试框架依赖、测试入口或测试 CI；保留生产 Demo、连接诊断、容器健康检查及历史证据，不把名称含 coverage 的检索函数误作覆盖率工具 | PASS |

本轮实际修改文件：`frontend/src/adapters/storage.ts`、`src/support_agent/user_memory_schemas.py`、`src/support_agent/api/user_memory.py`、`docs/QUALITY_REVIEW.md`、`docs/FRONTEND.md`、`docs/DEPENDENCY_LICENSES.md` 及本文件。其他已有修改原样保留。没有新增迁移，原 `0012_support_experience` 不变；没有连接数据库、执行迁移、改 RLS 策略或操作数据。个人记忆 usage 的响应结构保持原字段，仅新增类型化 OpenAPI 契约，不改变权限。

独立复核还发现存储删除抛错后恢复可读时旧值可能重现，已增加已知键的本地失效标记，并将批量删除改为逐键处理。完全禁止存储枚举时无法发现其他上下文的未知键，仍如实保留限制。人工评审场景已明确列在 `QUALITY_REVIEW.md`，无需恢复专用案例集。

本轮实际静态检查：Ruff / 118 文件格式、85 Python AST 与 12 个迁移离线 SQL/RLS 声明 PASS（约 1.11 秒）；TypeScript PASS；JavaScript 语法/模块链接、HTML 资源、196 个发布文件及 Markdown 链接/敏感模式 PASS（约 0.89 秒）；Python 3.11 语法解析、Shell、4 个 YAML、依赖声明/许可、测试残留扫描及 git diff --check PASS。未跟踪文档另检查行尾空白，暂存区为空、敏感本地文件未跟踪。静态检查不能证明实际 SQL/RLS、网络、重置交互或模型语义正确。

Sol 独立核对记忆与 API/Schema、依赖/许可证、工作流固定值、远端元数据及整合；Terra A 审查工具/RAG并补人工语义规范，Terra B 审查消息/队列/RLS，Terra C 修复存储回退并检查 React/Demo。没有确认缺陷的模块不重复开发。受浏览器存储限制时，各 iframe 独立内存仍无法共享状态；这项产品边界已写入前端文档，不能声称跨上下文重置已运行验证。

本轮不运行测试、不构建、不启动服务、不连接数据库、不调用模型、不提交推送部署；现有 wheel 不在 `dist/`，包资源检查 NOT_RUN。真实模型质量/费用 BLOCKED（未授权）；数据库并发、撤权运行效果、浏览器、Widget、Linux/Docker/生产均 NOT_RUN。源码已实现与静态 PASS 不等于这些项目验收通过。

## 历史实施与证据（非本轮运行结果）

> 后续工程规则更新：当前采用 [Static Verification First](../AGENTS.md)。下文运行时证据仅记载规则更新前已完成的操作；本次清理未启动服务、访问数据库或运行测试。评测执行器、两组合成案例、表单及一次性验证脚本已移除，仅保留历史输出、审计和恢复证据。CI 已收敛为纯静态检查，不再提供 PostgreSQL 服务/迁移矩阵或自动构建。

日期：2026-11-07。源码基线 `49fc85fbb5ba827507e4a6334a3a4daf995beb73`，开始时远端 main 与本地一致；工作区已有 11 个修改文件，本轮在其基础上增量实现。未提交、推送、部署或调用真实模型，没有新增依赖或恢复自动化测试。

`FIXED` 表示源码完成；`VERIFIED` 只覆盖下述实际证据，不能代替浏览器、真实模型或生产验收。

## 完成清单

| 工作项 | 实现与验证边界 | 状态 |
| --- | --- | --- |
| 人工消息闭环 | 独立访客消息 API；waiting/human 只落消息，AI 保持原 turn。隔离 HTTP 验证 AI→人工→连续提问/回复→AI | FIXED / VERIFIED |
| 幂等、并发与限频 | visitor UUID + 请求 UUID 派生消息 ID、会话行锁；同键同内容重放、异内容 409、并发一条；每会话每分钟 30 条人工期访客消息，原 HTTP 共享限流仍在 | FIXED / VERIFIED |
| 客服队列 | 默认最近消息活动；优先级、SLA 排序保留筛选分页；消息时间改用实际写入时钟，避免锁等待后落在已读位置之前 | FIXED / VERIFIED（SQL/HTTP） |
| 成员未读 | tenant + user FORCE RLS 游标、复合外键、单调前进。仅计公开客户消息，不计客服、工具、内部备注；两个成员互不覆盖 | FIXED / VERIFIED |
| 前端消息体验 | 原模式/原键恢复未知结果、草稿、游标去重、5 秒轮询/最长 60 秒退避、隐藏与切换取消；底部才自动滚动，否则提示查看最新 | FIXED；类型检查 VERIFIED；浏览器 NOT_RUN |
| 实用工具 | 五个静态能力，真实子进程/业务数据验证见下表；绑定状态与数据库定义分开展示 | FIXED / VERIFIED |
| AI 质量治理 | 按最新指令移除评测执行器、专用数据及表单；保留静态 AI 契约审查、历史证据与质量边界说明 | 静态 PASS；语义 NEEDS_RUNTIME_VERIFICATION |
| 个人记忆 | 来源精确跳转、旧/新替换确认、创建/使用/到期时间、本人回答使用记录。提交前被裁掉/零尝试/未知尝试不冒充确认使用；更新使用时间不回退 | FIXED / VERIFIED（服务端与类型） |
| Demo | 可跳过/重开引导、同标签页完整人工流程、命名空间重置、旧 Widget 会话失效。Node VM 执行真实 Adapter，禁止网络且请求数 0 | FIXED / VERIFIED（Adapter）；浏览器 NOT_RUN |
| CI / 供应链 | Actions 完整官方 SHA；weekly Dependabot，Actions/npm/uv 各最多 2 个更新 PR，Docker 最多 1 个；纯静态 CI，不启动数据库或自动构建 | FIXED；CI NOT_RUN |
| 开源治理 | SECURITY、CONTRIBUTING、CHANGELOG、人工发布清单；Description/Homepage/8 Topics 已通过 GitHub API 更新 | FIXED / VERIFIED（元数据） |

人工期 `/messages` 是独立入口；旧 `/turns` 和 SSE `/turns/stream` 保留兼容与原键恢复。相同键不能从 AI 变成新人工请求或反向重复推理。终止/失效会话不能新增消息；已接收回执可幂等重放。访客审计 `actor_id` 为空，独立记录 visitor_session_id，不记录 Token、消息正文或原始 IP。

未读口径是企业共享客服中的公开客户消息，不是所有内部用户提问；已读表示客户端已呈现的最新页位置，不声称能证明客服已阅读每个字。来源跳转直接按 ID 读取并复用历史交付校验，不分页扫描全部消息。

## 工具目录与连接器边界

| 工具 | 数据与边界 | 实际证据 |
| --- | --- | --- |
| text_metrics | 原有有限文本统计 | 保留原实现；本轮非重点重验 |
| conversation_status | 当前会话 status/support_state，含 observed_at | 实际进程 + 受控 Provider 连续工具轮 |
| conversation_history | 当前会话最近 6 条 Agent 用户原始输入，每条最多 400 字符；不含助手、工具、人工消息、内部备注；公开访客禁用 | 实际进程 + 输出进入下一轮 |
| conversation_sla | 现有 SLA 状态、首响目标截止时间、observed_at；目标不是对客户作出的承诺 | 实际进程；首响写入后不错误撤销观察快照 |
| knowledge_search | 当前回合选定与 Agent 授权知识库交集；最多 3 个结果、每条最多 500 字符 | 真实 PostgreSQL 资料 + 子进程；额外 tenant 参数拒绝；撤权后历史结果隐藏 |

`ToolSpec` 数据库记录不能指定代码；`/tool-capabilities` 才是部署运行时目录，`ToolOut.runtime_bound/binding_error` 表示契约是否匹配，不等于已获 Agent 或公开授权。子进程只收参数和有限数据快照，不收数据库 Session、密码或主密钥；保留 2 秒工具上限、4 个进程槽与输出/RSS 限制。Agent 原有总轮次、工具次数和时间预算未扩大。

最小连接器扩展边界是 `services/tool_connectors.py` 的服务端 `materialize` / `still_current` 与静态 `Capability` 契约。新增真实连接器需部署方代码、独立权限/结果来源复核和有界请求，不接受模型指定 URL 或处理器。CRM、订单、工单集成 **BLOCKED**：缺少服务商、接口文档、授权范围、字段及脱敏方案；未编造业务查询。未引入新的连接器框架。

## 个人记忆隐私

`last_used_at` 是确认交付给 Provider 的提交时间下界；结果未知时保持未知，进程意外退出也可能缺失记录，不宣称完整取证。Provider 等待期间没有为此持有数据库锁。多轮只记录实际保留在输入中的记忆，Provider 调用结束后以短事务更新，版本/来源改变仍拒绝答案交付。

`GET /user-memory/usage/{call_id}` 只允许当前本人查询内部调用，返回仍有效的记忆版本与来源 ID；撤销/删除/纠正后不泄漏旧内容。一般模型调用 steps 隐去使用依赖字段。实际 HTTP 已验证他人 404、历史回答遮蔽、撤回后本人历史遮蔽；原有同意、版本、过期和敏感来源限制保持。

## 数据库及 API

新增 `0012_support_experience`：

- `conversation_read_cursors`，唯一 `(tenant_id, conversation_id, user_id)`，复合成员/消息外键；唯一索引供会话页成员游标查询使用。ENABLE + FORCE RLS 同时验证企业和当前用户。
- `user_memories.last_used_at` 可空，旧数据不伪造回填。没有新增任务、后台进程或其他基础设施。

仅在新建合成验证库 `support_agent_quality_7953997e` 执行 0001–0012。运行角色没有数据库管理/BYPASSRLS 权限，20 张租户表策略和 Alembic ORM 对比通过。现有 dev/test/业务库未连接或升级。新隔离库与私有文档仍保留用于追溯，未擅自删除数据库、角色或备份。

新增 API：访客 `POST .../sessions/{sid}/messages`、成员 `POST /conversations/{id}/read`、来源 `GET /conversations/{id}/messages/{message_id}`、本人 `GET /user-memory/usage/{call_id}`。会话增加 unread_count/last_activity_at 和排序选项，工具增加派生绑定信息，记忆增加 last_used_at。OpenAPI 当前 **105 个操作**。已有部署启动前须经授权升级至 0012，详见[部署说明](DEPLOYMENT.md)。

## 质量、供应链与验收证据

- Ruff、格式、Python AST、12 个迁移的离线 SQL/RLS 声明检查通过；TypeScript `tsc --noEmit` 通过。发布文件/已知密钥模式/Markdown 链接检查通过。无构建、测试套件或部署。
- 隔离真实 HTTP 覆盖消息闭环、相同/不同键、并发、跨企业/访客拒绝、游标不回退、备注不算未读、人工消息限频及来源精确读取。工具使用真实子进程与受控 Provider，不是模型质量评价。
- 个人记忆覆盖确认提交、零尝试/未知结果不误记、裁掉的输入不误记、并发逆序完成不回退使用时间、隐私与撤回。SQL 时钟原子验证确认较早事务在锁等待后写入的消息晚于已读时间边界。
- Demo Node VM 只运行 Adapter 和模拟 Storage，不构建资源、不运行浏览器。已证实人工闭环/去重/未读/作用域重置/旧 Widget 访客失效和零 fetch 调用；不证明点击、剪贴板、iframe 或滚动布局效果。
- 原历史词面报告配对 18 例：可比较的文档词面覆盖均值 0.777778 → 0.777778；没有新的检索/模型准确率提升结论。新增 16 例仅词面诊断，不与原 18 例合并评分。人工语义、真实模型、实际外部连接器均未运行。
- npm audit（含开发依赖）报告 0 项；42 个锁定 PyPI 包的 OSV 精确版本查询无命中。未修改锁文件或依赖；这不是无漏洞保证。Docker 基础镜像已静态核查并纳入更新配置，镜像层扫描 **NOT_RUN**。
- 原计划的四个 PostgreSQL 运行组合及自动构建 job 已按后续指令移除。当前 CI 仅 Python 3.13 / Node 22 静态检查，保留整体 3 分钟保护，不含单项子进程时限。未执行当前 GitHub CI；历史本机运行证据仅 Python 3.13 / PostgreSQL 17。
- Dependabot 的 `uv` 生态依据 [GitHub 官方支持表](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories) 配置，更新 `uv.lock`，不增加另一套依赖管理。所有 Action 固定值已从官方仓库 refs 核验；原 setup-uv 固定的是 annotated tag 对象 SHA，本轮解引用确认对应 commit 后改用该 commit SHA；原值有效，不能称为失效引用。
- GitHub 实际设置：Dependabot Alerts、Security Updates、私密漏洞报告当前关闭；Secret scanning 与 push protection 开启。仅核查，没有擅自变更这些安全开关，尚需维护者启用私密报告及依赖安全功能。

运行脚本已删除；历史结果证据保留在忽略目录 `.local/product-quality/`：`acceptance-results.json`、`deep-results.json`、`final-atomic-results.json`、`memory-order-results.json`、`demo-results.json`、`final-checks.json`、依赖审计及质量对照输出。它们是本次合成验收材料，不是新增长期自动化测试套件，不发布本地连接配置。

## 代码职责和剩余事项

Sol 实施迁移/模型、服务端用户上下文、记忆使用与隐私 API、绑定状态 API、来源精确读取、并发时钟修复、隔离验收及最终整合。Terra 分别实施消息/队列后端、静态工具与质量资料、React/Demo 体验、CI/开源治理；独立 Terra 复核发现的时间回退问题经 Sol 核实修复并验证。所有文件按职责独占修改，未新增依赖。

主要修改位置：`api/{conversations,public_delivery,tools,user_memory}.py`，`services/{operations,public_delivery,tool_connectors,tool_execution,user_memory,model_runtime,agent_turns,chat}.py`，模型/Schema/0012；React `features/{chat,visitor,admin}`、Demo Adapter 与共享滚动 hook；质量脚本/合成数据/表单；`.github` 与上述治理文档。开始时的 11 个未提交修改保留并纳入整合审查。

- **NOT_RUN**：浏览器人工验收、实际滚动/焦点/剪贴板/跨站 Widget；当前静态 CI；本轮正式/Demo/Wheel 构建（遵守此前“不构建”要求）；Docker/Linux/生产、备份恢复新一轮验收。
- **BLOCKED**：真实模型语义质量与费用（未授权，不调用）；外部 CRM/订单/工单（缺资料）。
- **DEFERRED**：安全开关启用由维护者处理；真实负载、更多多实例容量和 DDoS 防护需单独授权验收。

源码可审阅，未据此宣称生产就绪。后续工作遵守根目录静态规范；构建和运行时确认须单独授权；不自动提交、推送或发布。

## 静态检查优先清理（后续指令）

- **PASS**：根目录 AGENTS.md 已整合永久测试禁令、分层静态审查范围、现有命令、六种结果状态和运行时授权边界；README/CONTRIBUTING/发布清单及现行运维说明同步。
- **PASS**：删除评测入口、评分模块、配对脚本、两套专用案例和 CSV 表单（共 6 项，其中 3 项是此前未提交的新文件）；另清理 49 个忽略目录中的一次性验证脚本及对应字节码。源码快照、历史结果、数据库、文档和备份保留，未进行数据清理。
- **PASS**：移除 CI PostgreSQL 服务、临时角色/建库/迁移、运行时矩阵、自动构建与数据库检查选项；保留 3 分钟 Job 上限和 Action SHA。手动 Pages 是独立发布功能，未触发。
- **PASS**：Ruff/格式、85 个 Python AST、12 个迁移离线声明（约 1.27 秒）；TypeScript（约 2.45 秒）；源码交付/196 个发布文件、链接和敏感模式（约 0.89 秒）；Shell 语法与 git diff --check。这些是静态检查，不是测试或运行时通过。
- **PASS**：逐文件 SHA-256 对比清理前快照，151 项业务源码、React、迁移、依赖/锁文件和手动 Pages 配置完全不变；仅删除确认无业务调用方的 evaluation.py。Demo Provider、连接诊断功能、授权/RLS/幂等及生产超时保护保留。
- **NOT_RUN**：本次清理未运行测试、构建、应用、数据库或服务，未提交、推送、部署。当前 CI 尚未执行。
- **NEEDS_RUNTIME_VERIFICATION**：当前真实数据库结构、浏览器交互、权限/并发行为、模型质量和生产环境；此前隔离证据仅适用于当时源码，不据静态结果扩大结论。

前一专项的消息、工具、队列、记忆和 Demo 业务改动均保留并完成静态整合；专用质量评测机制依照本次新指令移除，后续运行确认须另行明确授权。
