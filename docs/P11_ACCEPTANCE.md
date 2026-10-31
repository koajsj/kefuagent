# P11 清理与验收（2026-10-31）

基线 `fd3a119742a1088f5bd81a95e5244496e4200642`，开始时本地 main 与远端一致、工作区干净。当前版本仍为 pyproject.toml 的 0.7.1；本阶段无数据库迁移、无真实模型、无生产部署。

## 已实现

- 删除 tests/ 的 9 份 Python 测试文件（28 个函数）、web.test.mjs（3 项）、conftest.py、phase2_support.py、tool_fixtures.py，以及 scripts/migrate_test_db.py。删除旧测试缓存；没有移动或改名保留测试套件。
- 数据集原样迁至 data/customer_quality.json（18 场景）；正式 evaluate_quality.py 改为操作员显式选择已有企业、成员和文档的只读排名评测，不再执行 pytest、建企业、导入资料或断言阈值。数据库运行角色检查、活动成员及 tenant 过滤仍执行；比较报告还校验范围摘要。评测不是公开认证入口。
- 删除 pytest、httpx2、pytest 配置与 TEST_DATABASE_URL 执行逻辑；锁文件从 53 到 43 个包，未升级保留依赖。开发依赖仅 Ruff，运行依赖保留。许可证清单保留为历史快照。
- 新安装只创建 dev 库；没有运行初始化脚本、升级旧库、清理文档或改动 .local/pgdata。local-postgres.sh 的已有集群拒绝覆盖逻辑不变。
- check.py 默认只做 Ruff、格式、AST、线性迁移链、离线 SQL 中的表/约束/索引名称与 17 表 RLS 声明检查。名称检查不证明列定义或数据库实际结构完全一致；真实 schema diff 与策略核验只由 --database 在全新隔离 CI 库执行。
- check_delivery.py 删除测试数量预算和 Node 测试调用，保留 Node 语法、ES Modules 链接、HTML ID/DOM、静态资源、wheel/MIT，并纳入本地 Markdown 路径、敏感文件名、已知本机密钥值及常见密钥模式扫描。扫描不构成任意秘密检测的保证。
- 删除无消费者的 Retriever/DocumentStorage Protocol；保留实际检索、存储、演示 Provider、静态工具注册表、连接测试业务 API、运维 CLI 与全部迁移。
- 前端删除空 stopPoll/onLeave 生命周期，失败流的 discard 从两次变为 finally 一次；删除仅旧测试使用的 fetch 注入参数，唯一正式调用仍为 createClient()。租户切换 abort/epoch、SSE 释放、幂等及人工协作流程保留。

## 实际执行的检查

| 项目 | 结果 |
| --- | --- |
| uv lock/sync --offline | 成功；移除测试依赖及其独占传递依赖 |
| check.py | 通过，1.029 秒；Ruff/格式、78 个 Python AST、10 项离线迁移与 RLS 声明 |
| wheel 构建 | 成功，support_agent_platform-0.7.1-py3-none-any.whl |
| check_delivery.py | 通过，0.829 秒；16 个 Web 资源、JS/DOM/模块/MIT/链接和发布扫描 |
| evaluate_quality.py --help、sh -n local-postgres.sh | 通过；未执行评测数据库查询或初始化 |
| git diff --check、数据集内容及生产边界差异核对 | 通过；历史迁移及验收报告未改 |

Python/JavaScript 自动化测试均为 0；未执行已删除的测试，也未用其他脚本隐藏运行。这里的耗时是静态/交付检查，不与 P10 的 28 项业务回归耗时比较。

## 安全、性能与限制

多租户授权、复合 FK/FORCE RLS、AES-GCM、工具授权/幂等/审计、SSE 周期验权和租约回收、HTTP 共享计数的实现未改动。本轮仅源码与静态声明复核，运行时回归 **NOT_RUN**；不能因测试删除宣称业务安全已经重新验证。

入口限流仍默认关闭；显式开启缺密钥时 preflight 报错且请求准入拒绝，PG 故障返回 503。所有实例必须共享数据库、HMAC 密钥和阈值；未改为进程内限流。HTTPS Origin、Provider 主机白名单和运行角色权限仍由现有配置/预检约束。

生产 Provider/Agent/工具/解析/数据库/SSE 超时、CPU/RSS/并发边界及结构化日志保持原实现。CI 整体 3 分钟、PostgreSQL 健康检查 `pg_isready -U postgres -d postgres` 保留；检查子进程无单项硬超时。

本轮没有足够代表性数据证明新索引或 Worker Pool 的收益，两者继续 **DEFERRED**；P10 批量历史、SQL 聚合和检索排序保持不变。不宣称新增吞吐或响应速度提升。

数据库实际迁移/schema diff、只读评测查询、运行时业务与权限行为、浏览器 GUI、Docker、真实多实例/代理/生产容量、真实模型质量、远端 CI 均 **NOT_RUN**。删除测试使后续行为回归缺少自动化防线，上线前仍需独立验收；没有生产就绪保证。现有旧 dev/test 的升级需另行授权，本轮未连接数据库。

## 协作与发布

Terra 分别完成测试删除与数据迁移、前端三处冗余清理、README/当前运维文档整理；Sol 核实其全部差异，完成依赖、CI/检查脚本、只读评测、初始化与无用 Protocol 清理、最终静态与交付验收。无额外业务功能或基础设施。

仅按用户授权正常提交并推送 main；提交 SHA 由 Git 历史及交付消息提供，不查询或监控 Actions，不创建 Release，不部署。
