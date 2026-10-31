# P12 生产准备审查（2026-10-31）

基线：本地 main/远端均为 `a2c40e9bfba680c732995a45e0f54d90a192b84e`，工作区开始时干净。当前项目版本仍为 pyproject.toml 的 0.7.1。本轮不操作现有 dev/test 或生产库，不新增迁移，不调用真实模型，不运行 Docker/VPS/GUI。

## 架构与关键安全路径

保留模块化单体、FastAPI、同步 SQLAlchemy/PostgreSQL 和原生 ES Modules。API 校验/身份依赖 → Service → ORM；I/O 后的重新授权是撤权与交易边界需要，不能按“重复代码”移除。

| 范围 | 复核路径与结论（源码/静态证据，不是运行时认证） |
| --- | --- |
| 身份及租户 | dependencies 的 current_user/tenant_context/resume_context、identity/tenants 服务：已认证身份、活动成员和企业后建立上下文；事务局部 set_config，不用模型参数或前端企业 ID 单独授权。 |
| 数据隔离 | models、0001–0010、db、preflight：17 张租户表声明 FORCE RLS，主要业务关联含复合 tenant FK；用户、企业、成员、审计与最小公开定位等全局/启动前查询由服务授权，不能笼统声称全部表均有 RLS。 |
| 访客及协作 | public_delivery 的 authenticate/locate/delivery_guard/history 与 conversations/operations：Visitor 和管理身份分离；固定公开入口/企业/会话/Agent，发布版本及发布者撤权复查；负责人不替代成员身份；备注在 Collaboration，不写入 Message/访客历史。 |
| 模型及工具 | model_runtime、tool_execution、tool_protocol、tool_runtime：静态注册、JSON Schema、Agent 授权及公开白名单，执行前后复核，未知结果不盲目重发；模型和不可信工具内容不能授予权限。 |
| 知识及记忆 | retrieval、chat、agent_turns、memory：现行代次/来源/逐字引用校验，摘要只取用户消息摘录，不作为企业事实或系统指令；仍不证明语义正确性和通用注入抵御。 |
| 凭证及维护 | credentials、maintenance、retention、knowledge、storage：AES-256-GCM、tenant/ref/版本 AAD，旧 Keyring 兼容，租户级确认/原子轮换；删除 tombstone、批次、重试与审计边界保留。跨文件/数据库不具有原子事务。 |

没有证据要求重写这些业务服务，未因“去冗余”删掉授权、锁、幂等、审计或原有时间/资源限制；直接依赖均保留，没有新增框架或测试。

## 发现、等级与处理

| 等级 | 证据与处理 |
| --- | --- |
| P1 配置风险 | 原预检缺少生产模式；HTTPS、入口启用和运行角色所有权不是强制条件。新增显式 DEPLOYMENT_ENVIRONMENT=production，启动强制预检；CLI preflight --production 可单独严格检查。开发默认仍不冒充生产要求。 |
| P2 入口遗漏 | http_limits 的 health 前缀整体豁免包含会访问 DB 的 ready/setup。现在仅精确 GET /api/v1/health/live 豁免，其余正常计数；POST live 也不豁免。 |
| P2 资源缺口 | main 请求体原先只有大小限制，没有整段读取预算。增加从应用读取阶段开始的 30 秒预算及安全 408；大小超限仍 413，断连安全处理。此预算不代替代理接收阶段、Provider/Agent 或 SSE 的限制。 |
| P2 代理信任 | Docker/直连命令未显式关闭 Uvicorn 的代理头默认行为；风险取决于对端和代理配置，并非已经证明公网可绕过。Docker 与 README 直连命令显式 no-proxy-headers；受控代理另行精确信任、覆盖头。 |
| P2 观测 | 入口准入发生在原 trace ContextVar 设置前，DEBUG DB 耗时可能缺少关联。请求 ID 在最外层生成并 set/reset，覆盖准入/拒绝/后续生命周期；统一异常和审计失败为无载荷 JSON 日志。匿名诊断仍只返回简要状态。 |
| P2 部署一致性 | 新生产目录校验与镜像默认 0755 不一致，已对镜像新建目录设 0700；既有卷不自动修改。多实例共享 PG 却使用不同文档卷可造成分块/文件不一致，明确要求共享同一私有文件系统和权限，未验收前按单实例部署。 |

未发现有证据的 P0；这不构成不存在未知漏洞的保证。

## 生产预检与交付

`uv run python -m support_agent.cli preflight --production` 仅查询和读取状态；error 退出 1，warning 可保留但不代表生产通过。结果明确 mode 和 production_verified=false。显式生产启动也要求通过，不自动生成密钥、迁移、建管理员或修权限。

严格模式检查 HTTPS、HTTP 保护/密钥、Keyring、PUBLIC_RATE_KEY、已知秘密占位符、活动管理员、可写私有文档根目录及本地 .env 权限；HTTP 配置不得携带 MIGRATION_DATABASE_URL。数据库角色拒绝 SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB/REPLICATION，并查询 CREATE/TEMPORARY、schema/表/函数所有权或相关成员身份。缺少 .env 时外部秘密注入权限仍由部署平台保证；检查不证明密钥熵、完整 ACL、旧备份密钥兼容或任意 PostgreSQL 权限路径。

迁移 head 统一为 db.EXPECTED_REVISION 的 0010_http_ingress；预检和启动共用，未改任何已发布迁移或 ORM 模型。现有数据库版本本轮未查询，不能假设旧 dev/test 已升级。

[部署文档](DEPLOYMENT.md)、[生产清单](PRODUCTION_CHECKLIST.md)、[Nginx 示例](../deploy/nginx.conf.example) 明确角色分离、HTTPS/可信代理、头/体/连接/空闲/SSE、三部分备份、恢复顺序、轮换及撤销/删除重放。Nginx 示例从 http 上下文加载，阈值仅供部署方评估；读取间隔超时不等于整请求期限。HTTP 计数按每次网络请求，模型幂等重放不重复执行/模型准入，二者不混淆。

## 实际验收

| 检查 | 结果 |
| --- | --- |
| Ruff/格式、AST、离线迁移 | check.py 一次通过，1.077 秒；78 个 Python AST、10 项线性迁移、约束/索引名称和 17 表 RLS 声明。没有连接数据库；不是实际 schema 一致性或 RLS 行为验收。 |
| Wheel、前端及发布 | wheel 0.7.1 构建成功；check_delivery.py 一次通过，0.819 秒；16 个 Web 资源、JS 语法/模块、HTML/DOM、MIT、链接及已知秘密扫描。 |
| 一次性无 DB ASGI 检查 | 在临时目录、模拟配置、不可用的本机 port 1 地址进行：live GET 200；缺少入口密钥时 ready/setup/其他 health 路径和 POST live 503；伪造请求 ID 不采纳且 ContextVar 返回空；数据库不可用时生命周期启动安全拒绝。直接 ASGI 调用未启动正常服务或验证合法生产启动。临时脚本未保存为测试。 |
| CLI | preflight --help 显示 --production；严格预检对不完整配置/不可用 DB 返回不就绪。未执行成功数据库查询或真实 Keyring 解密。 |
| 发布核对 | git diff --check；原迁移、历史验收、依赖锁、18 场景数据及生产 Provider/工具/解析超时保持原实现。仅 SSE 审计失败日志格式变更，未改交付算法。 |

Python/JavaScript 自动化测试均保持 0，不声称“测试套件通过”。检查子进程无单项硬超时；CI 3 分钟整体保护及 PostgreSQL 健康检查原样保留。

## 未完成与结论

- **BLOCKED（上线验收）**：缺少目标环境的合法配置、最小角色权限和完整业务/安全验收，当前不能宣布生产就绪。本轮离线工作没有实施阻塞。
- **DEFERRED**：没有新增有代表性负载证据，不增加索引或 Worker Pool，不重构稳定业务或引入额外设施。
- **NOT_RUN**：新生产 DDL 查询实际执行、有效配置下的生产启动、真实跨租户/撤权/幂等/租约/30 秒超时行为；迁移和完整恢复/轮换；nginx -t、真实 TLS/代理、多实例、真实容量、Docker、浏览器 GUI、真实模型和远端 CI。既有历史验证按原阶段保留，不能视为本轮重新通过。

Sol 完成关键路径审查、生产模式/预检、角色检查、入口/请求体/日志修改及最终整合；Terra 分别实施部署/Nginx/清单、环境/容器/许可证/README整理，并只读安全复核。Sol 核实并修复复核发现的目录权限冲突和函数所有权遗漏。未引入额外业务、依赖或自动化测试。

用户已授权本阶段正常提交并推送 main；具体 SHA 由 Git 历史和交付消息提供，不 force push、不创建 Release、不部署、不查询或监控 Actions。
