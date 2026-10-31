# P10 性能与资源治理（2026-10-31）

## 基线与实施

本地与本轮一次性远端核对均为 `39a6e0788bd95d31445d4def5e0e88d54b5daf6d`，工作区开始时干净。它包含用户所给 e525948 后已验收的“移除检查执行器超时”提交，没有回退。无真实模型、VPS、生产数据库、负载压测或新增依赖。

- 检索：缓存正文/标题 coverage，rank 字典替代 lexical.index；保持 lane 顺序、RRF 权重与稳定 tie，排序 O(n log n)。候选仍各 lane 60 条，不声称企业语料质量提升。
- Analytics：PostgreSQL 条件 COUNT/SUM/AVG、UTC 日分组、JSON steps 模型统计；三类别各 LIMIT 10001 的有界 count 保留超量拒绝。保留空值、未知费用、访客会话 cohort、最新跨时间段调用、分类并列顺序与 SLA 口径，不加载三类完整 ORM 集合。小型合成样本中旧/新输出完全一致（含空企业、NULL、steps、分类并列与 UTC）；没有吞吐/内存百分比结论。
- 历史：公开层与共享 conversations.history 都批量读取页面涉及的 ModelCall/ToolExecution；公开层按调用排序工具结果，消息原序不变，缺失关联 fail closed。授权、派生工具依赖和来源失效遮蔽继续逐调用核验，仍可能有安全查询；不宣称全链路常数次 SQL。
- SSE：上游仍为非流式 Provider；完整答案先校验并持久化。以 128 字片段组装缓冲，累计 2048 字或自上次检查 250 ms 时触发新快照，检查成功才发出这一批，结束前重新检查；余量也在检查后释放。恢复调度/网络背压后必须检查再放行，不持有跨 yield 的事务。上限是待释放缓冲 2048 字、时间触发阈值 250 ms，不是墙钟调度/代理延迟保证。撤权丢弃未发送缓冲；已发送内容无法撤回，discard_deltas 只是客户端展示信号。
- 知识库：DELETE 每次至多清理 25 文档（可配置 1–100）；preview=true 只预览数量/首批 ID、文件名与状态，200。库 tombstone 先提交，即刻阻止检索/上传/重处理；批次文档和分块先标记并提交，随后串行文件删除和记录清理，仍保留删除审计。完成 204，未完 202 给 deleted/remaining，客户端显式“继续清理”；失败 503 可重复执行，不自动无限循环。并发已完成视为成功，不恢复已删文件；数据库与文件无跨介质原子性。

## 数据库与隔离

新增 `0010_http_ingress` 只创建 http_buckets（HMAC key、短期计数/租约、更新时间）及按更新时间清理索引。它是全局准入元数据，不存租户授权、明文 IP、Token、消息或凭证；业务的 17 张 FORCE RLS 表、复合外键与策略均保留。它本身不是租户业务表，不能用它授予企业权限。

已取得用户授权：只新建 support_agent_p10_test 并执行 0001–0010、写合成验收数据。现有 dev/test/P8 数据库、备份、密钥与文档未升级/清理。应用与 preflight 要求 0010；原 dev/test 启动前须另经目标负责人授权升级，禁止清库重装。SQL 审查文件在本机 .local/p10/upgrade.sql，未提交。

现有 VisitorSession 缺 tenant+created_at 专用索引、Feedback 缺 tenant+conversation 专用索引，但隔离 P8 样本约 59/10 行。只读 EXPLAIN：session Seq Scan cost 0.01..2.71；feedback 使用现有 tenant+created_at 索引 cost 0.14..8.16，conversation 作过滤。未运行 ANALYZE/压测、未生成代表性大数据；不能据此证明新索引收益，两个候选均 DEFERRED。

## 入口与观测

显式启用 `HTTP_LIMITS_ENABLED=true` 后，HTTP API（健康检查除外）使用共享 PostgreSQL 事务/行锁计数。默认每客户端 IP 每分钟总请求 1200、登录 30、上传/重处理 20、公开请求 120、SSE 开流 20；SSE 每 IP 4、全局 32 连接。HMAC 使用 HTTP_RATE_KEY，缺省复用 PUBLIC_RATE_KEY；启用但缺密钥/数据库不可用时拒绝，不降级到内存计数。默认关闭以保持部署兼容，生产必须主动配置，preflight 会报告关闭/缺密钥；未启用不能声称有总入口保护。

所有实例须连接同一数据库并使用相同密钥与阈值；不信任应用自行读取的转发头，部署方必须控制 ASGI/代理可信 IP 配置。IP 限制不能替代身份授权、原企业/用户/Agent 持久配额、代理连接限制或 DDoS 防护。SSE 使用数据库随机租约（240 秒故障兜底），准入完成后连接生命周期上限 150 秒；正常/取消均释放，准入途中取消会跟踪迟到结果并回收；后台模型执行不因浏览器重连而重启。过期桶有界清理使用排序 SKIP LOCKED，不删除业务记录。全局计数表只是准入保护，不是无限容量的恶意流量清洗设施。

HTTP 日志为 JSON，包含服务器请求 ID、路由模板、状态及响应头阶段耗时；SSE 关闭包含连接耗时，拒绝有类别/原因；数据库操作耗时在 support_agent.database 的 DEBUG 日志输出（不含 SQL/参数）。Provider 用量/耗时、Agent phase、工具终态及解析状态仍来自现有记录，不虚构新监控平台。未启动独立日志收集或告警服务，数据库 DEBUG 应按需启用。

## 资源与版本

保留 Provider 8、解析/工具各 4 的每进程并发、已有 CPU/RSS/输入输出/超时及回收机制。无网络/凭证的三次子进程启动小样本：provider 131.8/128.0/77.6 ms，ingestion 80.5/75.4/77.7 ms，tool 242.8/180.3/187.7 ms。不是实际请求/峰值 CPU/RSS/FD/吞吐测量；进程内 semaphore 不能当作跨实例总量。Provider 的资源隔离不等同解析/工具沙箱；ASGI worker 数会放大解析/进程资源，需要部署容量验收。

Worker Pool DEFERRED：缺代表性收益证据，常驻进程会改变凭证、环境与租户上下文隔离及超时回收。维持一次性子进程，不引入队列基础设施。

版本仍为 pyproject.toml 的 0.7.1，应用读取安装发行版元数据，移除 main.py 硬编码。发现本机旧 editable 元数据 0.4.0，uv sync --locked --offline 后已是 0.7.1，无库版本升级；部署/开发应始终按锁同步再启动。架构文档明确旧 0.4.0 为历史阶段；P6/P8/P9 历史验收原文不重写，P9 后续当前策略亦保留。

## 协作与验收

Terra 实际执行：retrieval.py/架构文档、public_delivery.py/知识批次界面、analytics.py 三个独立工作包；另只读核对索引/进程资源并复核 Sol 的核心修改。Sol 定义统计/历史契约、独立审查整合，完成 SSE、共享历史层、批次恢复、全局准入/迁移与观测。复核发现的取消租约、清理锁序、并发删除完成误报已修正并分别作针对性验证。

已完成原子检查：旧/新 PostgreSQL Analytics 等价；2+1 文档批次、预览/墓碑拒绝/重复删除；两个独立连接池的登录竞争与全局 SSE 限额、释放后恢复；真实 PostgreSQL + Mock 模型的 8192 字 SSE 四批交付及首批后撤权；准入中取消后的迟到 PostgreSQL 租约释放；启用中间件后的健康正常、第二次登录 429、版本展示 0.7.1。

现有 Python 全套只运行一次：28 项全部通过，20.76 秒；含 Ruff/格式/新隔离库 Alembic 无差异的脚本 22.72 秒。最终补齐共享历史层批量读取后，只追加对应的公开知识/工具/审计原子回归，1 项 2.33 秒通过，不重跑全套。3 项 JS 105.44 ms 通过，模块/HTML/wheel 资源及 MIT 授权通过，交付脚本 0.31 秒。最终 Ruff/格式、git diff --check 通过。没有测试执行器 timeout、skip/xfail、收集过滤、新测试文件或新依赖；CI Job 总限制与 PostgreSQL 健康保护不变。

## 尚未验收

BLOCKED：无（原 dev/test 升级需另行授权，未擅自执行）。DEFERRED：额外业务查询索引、Worker Pool、实际规模的容量/资源测量。NOT_RUN：真实模型/摘要语义、GUI、Docker、远端 Actions、Linux/HTTPS/生产多实例、生产代理/DDoS/负载验收。两个本机独立池只证明共享计数的数据库原子性，不等于真实多机部署验收。

发布仅包含 P10 文件，正常 main 提交/推送后一次性核对 SHA，不查询/监控 Actions，不创建 Release、不部署；最终 SHA 见交付消息。
