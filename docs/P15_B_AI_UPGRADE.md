# P15-B：AI 能力补全与离线验收

本记录更新此前八个文件的首轮 P15-B 报告。起点为本地 `86371077f792f06c05478e319b03252336615460` 加已有 P15-A、P15-B 和 React 未提交改动。没有进入 P15-C，没有构建、提交、推送或部署。用户已明确暂不进行真实模型调用。

## 验收结论

FIXED 表示代码已改，VERIFIED 仅表示本表注明的验证层级；两者都不代表真实 AI 或生产验收。

| 项目 | 实现与实际证据 | 状态 |
| --- | --- | --- |
| PostgreSQL 检索 | 原 18 场景中 11 个有正相关标注的检索场景，真实 PostgreSQL、相同去重共享语料、固定文档与 chunk ID，比较 HEAD、续作前快照和当前实现 | VERIFIED：SQL 检索；真实回答 BLOCKED |
| 中文问句 | 实际发现问句虚词产生跨词二字组、稀释 coverage；仅补通用问句词组边界，不降低 0.4 阈值 | FIXED；隔离 PostgreSQL VERIFIED |
| 单汉字 | 已授权、有效 generation 范围内的受限 LIKE 通道；最多 1000 chunks、60 匹配、10 返回；越界明确拒绝，独立 1 秒数据库语句预算 | FIXED；隔离 PostgreSQL VERIFIED |
| 自然语言综合 | 显式启用结构化 claims、类型和来源关联，保留校验原文；默认仍摘录，非法关联回退摘录 | FIXED；Chat/Agent HTTP + 受控 Provider VERIFIED；真实语义质量 BLOCKED |
| 连续工具 | 实际 ProcessToolRunner 连续两步、工具结果进入下一轮、参数拒绝、失败后新请求恢复、同键重放及并发排他 | 隔离 PostgreSQL + 受控 Provider VERIFIED |
| 授权撤销 | 成员撤权、工具授权撤销、历史依赖、知识解绑、凭证轮换与禁用、未知工具结果协调 | 按下文区分 HTTP 与服务级 VERIFIED |
| 摘要与预算 | 积压 16 条分批、水位推进、一次 Provider 故障降级、工具协议保留、敏感源排除 | 隔离 PostgreSQL / 受控 Provider / 原子 VERIFIED |
| 超大摘要源 | 不再使每个新 Agent 请求失败；保留原文与待处理水位，禁用旧摘要，返回近期完整历史及 context_warnings | FIXED；隔离 HTTP VERIFIED；跨轮分片摘要 DEFERRED |
| 跨会话记忆 | 企业+用户双重 RLS、显式同意、精确用户来源、版本更新、期限、查看/删除/撤回/清理、逐次发送与交付复核 | FIXED；隔离服务、HTTP 和锁并发 VERIFIED |
| Token 与费用 | 每步保存部署价格快照，按请求汇总摘要/RAG/Agent/主备模型；未知用量或价格保留 unknown | FIXED；确定性核算、隔离 HTTP 和受控 Provider VERIFIED；实际账单 BLOCKED |
| P15-A 双端同步 | HTTP after/before、协作 before、稳定 ID、跨会话游标拒绝通过；现有 JS 语法与调用链检查 | API VERIFIED；浏览器取消/隐藏/切换 NOT_RUN |
| 向量 / Embedding / Reranker | 当前 PostgreSQL 未提供 vector 扩展；没有获准使用的语义模型或新增基础设施 | BLOCKED；没有编造比较数据 |

## 检索前后对比

使用 `data/customer_quality.json` 原有 18 个场景；相关性评分只统计 11 个有正标注的案例。将各案例的原始文档按完整文本去重，形成 13 篇共享文档；同一事务、相同固定 UUID、相同 K=6，对比原 HEAD、续作前检索快照和当前实现。其余场景不能充当检索正例或真实回答评分。

| 真实 PostgreSQL 指标 | HEAD | 续作前 | 当前 |
| --- | --- | --- | --- |
| 文档 Recall@6 | 1.000000 | 1.000000 | 1.000000 |
| MRR | 0.765152 | 0.765152 | 0.765152 |
| nDCG@6 | 0.815859 | 0.815859 | 0.815859 |
| 未标注或非相关候选占比 | 0.534848 | 0.534848 | 0.534848 |

其他案例的文档未被该问题标注，并不等于确认为无关，因此最后一行不能称为精确噪声率。样本较小，数据集未覆盖广泛同义改写、真实用户长对话或大规模语料；没有证明整体排名提升或真实答案正确率提升。最早按每题小语料池得到的全 1.0 指标不用于宣称质量；此前词面准入 13/13 也不是 SQL 检索指标。

新增实际错例（没有改原 18 题）：

- 文档一：`账户退款审核需要提交订单编号，审核完成后会通知用户。`
- 文档二：`账户退款通常需要七个工作日，节假日时间顺延。`
- 查询：`账户退款需要什么资料以及多久？`
- 修改前两篇均未召回，coverage 均为 3/11；加入有限的 `需要(?=什么|哪些)|什么|哪些|以及` 问句边界后，两篇均召回，coverage 均为 2/4。没有增加退款行业词典或降低候选阈值。

单汉字验证包括安全命中、恶意资料过滤、跨租户 KB 返回 404、1001 个 scope chunks 和 61 个匹配明确返回 `query_too_broad`，事务语句预算恢复至原 10 秒。保存了小样本 SQL EXPLAIN ANALYZE/BUFFERS，不据此声称大规模性能通过；没有新增索引或扩展。

向量方案尚未实际执行：没有安装 pgvector，没有下载语义模型或调用 Embedding。不能以字符向量假装语义 Embedding，也不能据未执行的实验判断“无收益”。后续比较需先确定授权的本地/远程 Embedding、价格与隐私边界、扩展安装授权，再在相同标注语料上比较词法、向量、RRF 混合及候选重排的质量、噪声和实际延迟。现阶段保留 PostgreSQL 词法架构。

## 回答与引用契约

Agent 的 `behavior.answer_mode` 默认 `verified_extracts`；可显式设置 `evidence_synthesis`。后者要求模型返回结构化 `claims`：`statement`、`kind`（fact / inference / uncertain）及 `chunk_ids`。服务器先验证当轮候选、当前原文、generation、来源权限和逐字引用，再验证每条 claim 只能关联已验证的来源；最多 6 条 claim，每条最多 3 个来源。

综合模式的响应明确为 `grounding_mode=evidence_synthesis_unverified`、`semantic_verified=false`、`grounded=false`。答复正文也显示未做语义核验，并列出原文，避免旧客户端忽略新增字段后误认为事实已经确认。fact 是模型提出的事实类陈述，不是服务器证明其真实性。推断和不确定信息分别标识。

非法、缺失或敏感 claim 退回摘录；冲突、模型拒绝或证据不足不生成有依据的答案。显式标签矛盾检测仍只是保守规则，并非通用语义冲突识别。逐字校验不能证明引用支持每个结论；安全摘录同样不证明资料真实或完整。没有把自由生成文本标为 grounded。

真实 HTTP 受控验证覆盖 Chat 与 Agent 两条路径：两篇资料综合、非法 claim ID 回退、冲突拒答、未配置价格保持 unknown。真实模型综合质量仍 BLOCKED。

## Agent、上下文与安全

保留 5 次推理、4 次工具和 120 秒整轮预算；未增加任意代码工具、写操作、审批绕过、模型授权或未知结果自动重试。

实际证据：

- 受控 Provider 驱动两个真实隔离工具进程，执行结果进入下一轮模型输入；非法参数被拒并交回模型。
- 完成后的同键重放不再次调用；不同输入复用同键拒绝。执行期间同键返回 running，异键返回 409，Provider 仅调用一次。
- 模型等待时撤销成员返回 403；撤销工具授权后生成的调用记录 denied、不含工具数据；历史依赖撤权后同键返回 409，后续模型提示排除旧问答。
- 知识解绑后的重放 unresolved；等待模型期间解绑后请求 failed，无答案或引用。
- 独立复核发现内部历史原来只为 Visitor 复核知识引用：已修复为内部 RAG/Agent 消息也检查当前绑定和来源，失效后脱敏；用真实 HTTP 复核通过。Chat 新请求的 KB 也须属于当前 Agent 授权范围。
- 工具子进程已启动后撤权：静态注册的受控只读 handler 实际执行成功，记录 succeeded、delivery_error=tool_not_authorized、result=null；HTTP 409，结果未进入下一次模型输入。审计保留执行成功事实，不把撤权说成从未执行。
- 模拟凭证在模型等待期间经 API 轮换后，交付失败；服务级禁用检查也通过。请求仅使用本次生成的模拟凭证，未输出密钥内容。
- 服务级未知执行协调：过期 running 工具标记 `interrupted_result_unknown`，未过期保持 running。没有验证真实进程被外部杀死后的全过程。
- 消息 after/before、协作 before 的重复请求返回稳定 ID，跨会话游标均 404。

P15-A 的客户端隐藏、AbortController、会话切换与去重调用链已检查，三个旧 JS 模块语法通过；不等于浏览器并发操作验收。React 和旧前端共 44 份起点记录文件的哈希均保持不变。

摘要：24 个合成历史轮触发两次 refresh，来源数量从 16 推进至 21，第一次 use_memory=false，追平后 true。另 23 个受控对话轮验证一次摘要 Provider 故障后继续回答及后续持续推进。工具轮裁剪保留当前用户、Assistant Tool Call 和 Tool Result，无法满足预算时明确拒绝。认证、凭证与授权失效不作为可降级的瞬时故障。

超大源的新降级验证：6016 字符的首条源、2048 输入预算下，本轮 answered 并返回 `context_warnings=[summary_source_too_large]`；原文完整、摘要记录为 0、大源未发送给模型、没有跳过水位。**尚未实现可恢复的跨轮分片摘要**；需要提高已配置预算后才能处理该完整源，期间只有预算内近期历史，可能缺少远期条件，不能宣称完整记忆。高置信度凭证正则只是保守最小化，不是完整 DLP。

## 显式跨会话记忆

新增 `/api/v1/user-memory`，只对经过身份和企业成员验证的当前用户开放：

- GET/PUT `/consent`：默认关闭，撤回与删除记忆在同一事务。
- GET 根路径、PUT/DELETE `/{key}`、DELETE 根路径：查看、保存/纠正、单项或全部删除。
- POST `/cleanup`：按用户清理过期项，单次最多 100 条，可重复执行。

保存需要用户明确提交一段自己的既有 user 消息原文（最多 300 字）、来源 ID 和期限（1–365 天，默认 30 天）；仅接收内部 rag/agent 来源，不接收其他成员、assistant、tool、内部备注或 public 访客来源。已有 key 必须携带 expected_version；最多 20 条有效项。没有自动采集或跨企业共享；失效项不再用于推理。

每条记忆保留来源、版本、创建/更新时间及失效时间。注入内容属于不可信用户报告，不能证明企业事实、改变权限或覆盖当前用户指令。每次 Provider 尝试前和交付时复核同意、版本、期限、身份及来源。持久化依赖，历史不会把记忆派生的答案再转成其他用户或未来轮次的事实；其他用户读取相关回答会脱敏。公开访客不加载该记忆。

网络等待期间不持数据库事务：已经发出的请求不能因随后撤回而从外部撤销；撤回会阻止后续发送及尚未授权交付。返回失败仍保留已观察到的 Token。此前已交付内容也无法撤回；原始消息与既有审计的保留政策没有改变。

真实数据库验证覆盖用户/企业 RLS、精确来源、敏感模式拒绝、版本冲突、过期清理、撤回和回滚、交付与撤回锁序列化，以及跨会话 HTTP、另成员历史脱敏和等待时撤回。Chat 等待时撤回另经 HTTP 验证：调用 failed/user_memory_changed、已知用量 5/3、结算预留量 8，未遗留 running 状态。修复来源检查与当前会话锁的逆序风险：保留会话关联校验，只锁消息来源；现无修改 channel 的 API，未来如开放必须重新评估。

## Token 与费用

新增可选 `MODEL_PRICES` JSON 配置。每项明确 provider、model、精确 HTTPS endpoint、currency、input_per_million、output_per_million、source 和带时区的 effective_at；空列表代表没有价格。只匹配已生效的精确配置，调用前保存价格快照，后续修改价格不会重算旧调用。

`GET /api/v1/model-calls/{call_id}/cost` 复用企业管理员权限，返回每步用途、模型、用量、价格来源、估算、未知项及按币种已知小计。一个请求的 steps 包含摘要、RAG 或 Agent 多轮及主备模型，不将历史请求重复计费。未知 Token 或价格不作零处理；含未知项或多币种不提供单一合计。没有用 Token 预留量冒充实际费用。

这是**部署单价估算，不是供应商账单**，尚未支持缓存 Token、阶梯价、税费、折扣或工具收费等独立账单项目；此类部署不能以本端点代替完整账单。

确定性原子核算使用明确标记的合成单价，覆盖已知/未知、价格生效时间、精确 endpoint、重复配置拒绝。真实 HTTP + 受控 Provider 验证主模型失败后备用模型成功，记录 10 输入 / 3 输出 Token、2 次传输及两步价格；修改配置后旧估算保持不变。该金额不是实际模型费用或节省比例。没有配置真实供应商价格，也未进行真实 API 调用。

## 数据库、检查与修改范围

仅新建并使用隔离库 `support_agent_p15b_096c68`，分离迁移和受限运行角色；运行角色 NOBYPASSRLS、非数据库/表所有者。全部资料为合成内容，没有连接、升级或清理现有 dev/test/业务库。检索夹具事务回滚；HTTP 夹具只在该隔离库。未擅自删除验证库或备份；连接元数据只在忽略的 `.local/p15b-final/database.json`，权限 0600。

新增 `0011_user_memory`：两张同意/记忆表，复合成员与消息来源外键，ENABLE + FORCE RLS，策略同时约束 app.tenant_id 和服务端 app.user_id。迁移仅应用于新隔离库。运行版本检查更新至 0011；**已有部署需另获授权迁移后再启动新版，未自动升级既有数据库**。

实际检查：Ruff、格式、85 个 Python 文件 AST、11 项线性迁移及离线 SQL/RLS 声明；隔离库 Alembic check 无差异，运行角色、0011 版本及 19 张表 FORCE RLS/策略检查通过。三个旧前端 JS 模块语法和 git diff --check 通过；最终静态脚本 1.098 秒，三个 JS 语法检查合计 0.155 秒。OpenAPI 生成成功，共 101 个操作。未新增自动化测试套件、测试依赖或框架；Python/JavaScript 自动化测试仍为 0。未执行构建。

代码范围：

- 既有 AI 文件继续增量维护：search_text、retrieval、api/knowledge、services/chat、agent_turns、memory、model_runtime；既有 evaluation 和 evaluate_quality 改动保留。
- 记忆：models、0011_user_memory、services/user_memory、api/user_memory、user_memory_schemas；db、preflight、main 注册与版本检查。
- 回答契约：schemas、rag_schemas、tool_protocol；交付：services/conversations、tool_execution。
- 费用：services/costs、config、api/model_access、.env.example。
- 本报告。新增依赖：0；React 前端：0 修改。

私有一次性证据位于 `.local/p15b-final/`：rag-results、agent-results、additional-results、knowledge-results、knowledge-wait-results、history-fix-results、summary-results、backlog-results、summary-degraded-results、cursor-results、memory-results、memory-http-results、chat-memory-results、schema-cost-results、synthesis-results、synthesis-http-results、cost-http-results、worker-revocation-results。它们不随 Git 发布；不是恢复的测试套件或真实客户数据。

## 协作与剩余事项

Sol：综合回答、记忆接入与最终交付、费用、迁移、授权修复、隔离 HTTP 与全局整合。Terra A：真实检索对比、单字实现、问句错例及综合原子复核。Terra B：显式记忆服务/API、版本与锁序修复、隔离记忆验收。Terra C：工具/摘要/游标/撤权运行验证和只读安全复核，发现并促成内部历史授权修复。主 Agent 核实并整合结论。

- **BLOCKED**：真实模型回答、语义冲突识别、实际任务规划/工具选择质量、真实 Token/账单验收；用户选择本轮不真实调用。
- **BLOCKED**：语义 Embedding、向量/混合及 Reranker 的实际比较；缺少扩展及授权语义模型。没有证据证明其收益或无收益。
- **DEFERRED**：超大摘要源的跨轮可恢复分片；现为明确警告的近期历史降级，原文和水位保留。
- **NOT_RUN**：真实浏览器轮询取消/隐藏/切换与 React 运行、真实进程崩溃恢复全过程、生产/容量验收。
- 后续仍需授权模型与预算、语义人工评审及必要基础设施，才能完成剩余验收。本阶段停止于 P15-B，不自动进入 P15-C。
