# P8 实施计划与接口约定

基线：本地 main `2c86a5f` / 0.6.0，保留 P7_ACCEPTANCE.md 与 test_boundaries.py 的本地收尾。P7 记录 54 Python / 5 JS，46.24 秒；CI 首次超时，不宣称通过。用户允许 P8 交付时一次性远端核对和正常推送，禁止 Actions 查询、轮询和监控。

1. 工作台：扩展 conversations，负责人/优先级/标签/分类/服务时间；独立 collaboration 表保存备注、分配和状态历史。复用现有 handling/messages，行锁 + expected_version 防止竞争；普通成员仅能操作自己负责的人工会话，管理员可转交。公开回复重新核验入口和发布授权。
2. 会话记忆：摘要表保存版本、来源消息范围和摘要生成用量。仅压缩旧用户陈述，近期完整轮次沿用原授权校验；摘要以不可信用户数据注入，不能充当证据。生成复用 Provider、ModelCall 配额/审计，在既有 Agent turn 内有界执行，无后台任务。
3. 分析：UTC 半开区间（最多 90 天），有界聚合；不扫描消息正文。grounded 仅表示引用验证；费用未知为 null。公开反馈固定访客身份，独立记录且不进入 AI 上下文。
4. 部署：只读 CLI preflight，liveness/readiness/setup 分离，可选应用 + PG Compose，显式迁移，无默认密码或管理员。保留 macOS 本机方式。
5. 验收：净增 Python 最多 2 项、JS 最多 1 项，整套只运行一次（60 秒硬上限），高风险多租户/并发/记忆污染在新授权隔离库执行；迁移执行另行授权。只发布审查过的文件。

## 前端契约

所有管理端路径前缀 /api/v1，沿用 ctx.api、Cookie/Origin 和 X-Tenant-ID。
- GET /conversations 原 list 数组，增加 q（标题、上限100字符）、queue=all|pending|unassigned|mine|human|ai|resolved，assignee_id、priority=low|normal|high|urgent、sort=newest|oldest、limit<=100、offset<=10000。
- ConversationOut 增加 assignee_id:null|UUID、priority、tags:string[]、category、version:int、first_response_at、waiting_since、human_started_at、resolved_at、ever_human:bool、sla:{first_response_seconds:null|number, human_wait_seconds:null|number, resolution_seconds:null|number, state:ok|due_soon|overdue}。
- GET /workspace/operators -> [{id,display_name}]（启用企业成员，不泄露登录标识）。
- PATCH /conversations/{id}/operations body {expected_version,assignee_id?,priority?,tags?,category?} -> ConversationOut。仅管理员分配/取消/转交；普通成员可更新自己负责的会话元数据。
- POST /conversations/{id}/handling body {state,expected_version?} -> ConversationOut。管理员可接管/恢复/解决；成员可标记 waiting 或接管未分配或分配给自己的待人工会话、操作自己负责的人工会话；成员不可越过 waiting 直接恢复AI。
- GET /conversations/{id}/collaboration?limit=30&offset=0 -> [{id,kind,actor_id,content,details,created_at}]，仅内部。POST 同路径 body {content}，写备注。
- GET /conversations/{id}/summary -> null|{id,version,content,source_start_id,source_end_id,source_count,created_at,input_tokens,output_tokens}；只读展示，达到阈值的 Agent turn 内自动生成，不提供伪生成按钮。
- GET /workspace/analytics?start=ISO_UTC&end=ISO_UTC -> {start,end,conversations:{total,pending,resolved,avg_first_response_seconds,avg_resolution_seconds,handoff_rate,overdue,ai_resolved,ai_to_human,ai_unresolved},ai:{retrieval_use_rate,valid_citation_rate,tool_success_rate},usage:{calls,failed,input_tokens,output_tokens,unknown_usage_calls,known_cost:null,unknown_cost_calls,models:[{model,calls,input_tokens,output_tokens,unknown_usage_calls}]},trend:[{day,conversations,ai,human,calls,input_tokens,output_tokens}],categories:[{category,count}],unresolved:[{id,subject}],feedback:{satisfied,dissatisfied,unrated,satisfaction_rate}}。
- POST /public/{pid}/sessions/{sid}/feedback body {rating:satisfied|dissatisfied,comment?:string<=1000}，Visitor Token/当前会话；GET 同路径返回 null|{rating,comment,created_at}。不能传会话ID/tenant。

Terra 前端负责 chat.js、新 operations.js、management.js（仅 dashboardPage 替换）、public.js/public.html/public.css/styles.css。Sol 不同时改这些文件。Terra 部署负责 preflight.py、cli.py、Dockerfile、compose.yaml、.dockerignore、docker/、docs/P8_DEPLOYMENT.md。Sol 负责其余后端、迁移、测试和集成。所有成果由 Sol 核实后提交。
