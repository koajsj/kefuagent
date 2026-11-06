# P15-C 产品与生产准备交付记录

日期：2026-11-06。起点为 `main` / `86371077f792f06c05478e319b03252336615460`，叠加开始时已有的 P15-A、P15-B、React 和其他未提交修改。没有重写迁移历史、升级依赖、恢复测试套件或调用真实模型；没有提交、推送、发布、启用 Pages 或操作生产环境。

FIXED 表示代码或文档已改；VERIFIED 仅表示注明层级的实际核对；NOT_RUN 表示未执行；BLOCKED 表示缺少环境或授权；DEFERRED 表示明确留待后续。静态 Demo、离线 API 和合成恢复均不等于真实模型质量或生产验收。

用户最新边界：前端到此停止，只面向常见电脑浏览器尺寸；不再扩展移动端或继续视觉精修，收尾优先本体与交付。

## 实现与协作

Sol 负责整合、后端入口与预检、Adapter/Widget修复、隔离运行及最终检查；Terra A 提供前端增量，Terra B 提供运维增量，Terra C 独立只读复核。子模型因写入权限限制交付补丁，由 Sol 核对起点并应用；没有多人同时写同一文件。最终独立复核未发现有证据支持的新增阻断问题，属于静态证据。

| 工作项 | 结果 | 状态 |
| --- | --- | --- |
| 视觉与交互 | 中性色、统一边框表格、筛选栏、表单宽度、空分页、错误/加载态、侧栏展开语义与跳转主内容；沿用克制动画和骨架屏 | FIXED；下述浏览器范围 VERIFIED |
| P15-B 前端能力 | 个人记忆显式同意、来源、期限、版本更新、删除/撤回/清理；内部消息带来源预填且仍须确认；Agent 编辑保留回答模式；费用详情独立加载且未知不计零 | FIXED；Demo 与隔离 API 分别 VERIFIED |
| Demo 隔离 | 本地记忆和费用模拟，构建图双向禁止混入另一 Adapter；保留 connect-src none，固定 React Aria 样式精确 CSP hash；本地 favicon | FIXED；正式/Demo 构建及浏览器网络 VERIFIED |
| Widget | 修复 sandbox 缺少 allow-forms 导致发送被浏览器拦截；关闭卸载 iframe 停止轮询，重开恢复，重复脚本去重 | FIXED；正式与 Demo 浏览器 VERIFIED |
| 应用入口 | 仅接受 WEB_ORIGIN 主机；默认输出 INFO 级安全 JSON 日志并避免重复 handler；补查记忆表 CRUD 授权 | FIXED；隔离 HTTP、日志和权限缺失检查 VERIFIED；生产预检拒绝关闭入口/HTTP Origin/迁移连接 |
| 运维 | CI 迁移/运行角色分离；Compose 健康检查带可信 Host、180 秒关闭宽限；Nginx 拒绝未知主机并覆盖转发头；备份、密钥、撤销重放与责任边界 | FIXED；配置静态核对 VERIFIED；目标环境仍待验收 |

## 质量闸门

| 要求 | 实际证据和边界 | 状态 |
| --- | --- | --- |
| 1 React 正式构建 | `npm run build --prefix frontend`，tsc 与 Vite 完成；正式资源生成于 web-react | VERIFIED |
| 2 Demo 独立构建 | `npm run build:demo --prefix frontend`；/kefuagent/、Hash 路由、静态 Widget 和 CSP 产物存在 | VERIFIED |
| 3 TypeScript / 依赖 | 两次构建均运行 tsc；`npm ls --prefix frontend --depth=0` 无缺失或无效项；未升级依赖。没有执行在线漏洞审计 | VERIFIED；漏洞审计 NOT_RUN |
| 4 Python 静态 | `scripts/check.py`：Ruff、格式、85 个 Python 源文件、11 个迁移与 RLS 声明检查；不是行为测试 | VERIFIED |
| 5 Wheel 交付 | Hatchling 构建 0.7.1 wheel，`scripts/check_delivery.py --wheel …` 核对正式 React、旧资源、JS模块、许可证和文档引用；运行端不依赖 Node | VERIFIED |
| 6 Demo 浏览器 | 独立 Playwright Chrome 会话逐页检查 13 个管理路由，另验访客与 Widget，详见下表；不是所有角色/浏览器/异常组合的穷尽验收 | VERIFIED（有界范围） |
| 7 响应式 / 视觉 | 1440×900 逐页截图人工审阅；1024、1440、1920 宽度核对主要 6 页，无文档级横向溢出；早期额外做过 390/768 检查，依用户最新要求不再作为验收目标；减弱动画与键盘入口另行核对 | VERIFIED（Chrome） |
| 8 Demo 网络隔离 | 全页面浏览仅当前 Origin /kefuagent/ 静态资源，未出现 fetch/XHR/WebSocket 或外部资源；跨 Origin Demo Widget 同样只读静态资源；CSP 限制保留 | VERIFIED |
| 9 FastAPI 集成 | 新建临时 PostgreSQL、合成企业/用户/文档；真实 HTTP Cookie、Agent 搜索、SSE、after/before、去重、人工接管、内部备注、协作游标、记忆权限、Host/Origin/访客隔离及上传 | VERIFIED（本机离线） |
| 10 Widget | 跨 Origin 宿主创建/恢复访客、发送与离线回复；Visitor 请求不带管理 Cookie；关闭后观察超过一个轮询周期无请求，重开恢复，重复脚本仅一实例，移除后停止；Demo 发送模拟回复 | VERIFIED（Chrome、本机 HTTP） |
| 11 迁移 / RLS | 新 PostgreSQL 17 集群从零 0001–0011；只读 ORM schema 无差异；19 张 FORCE RLS；记忆用户+企业隔离、owner 受 FORCE 约束、写策略、2 个复合外键与错误来源拒绝；缺少 UPDATE 时预检报错 | VERIFIED（新隔离库） |
| 12 Docker / 代理 | Dockerfile、Compose、Nginx 和 CI 源码审查；Compose 与两工作流通过 YAML 1.2 解析（旧 Ruby YAML 1.1 对端口写法不兼容，未据此改动有效配置）；当前无 docker、nginx 可执行文件，未安装或操作现有容器 | VERIFIED（静态）；实际构建/启动/nginx -t BLOCKED |
| 13 合成备份恢复 | 新隔离恢复库；完整 dump、新文件目录、3 文件校验、2 合成凭证轮换与解密、缺失新密钥拒绝、记忆删除/凭证禁用/发布撤销和会话失效重放、19 FORCE RLS | VERIFIED（合成数据）；真实备份 NOT_RUN |

## 全页面与功能核对

| 页面 / 功能 | 浏览器与接口范围 | 状态 / 未覆盖 |
| --- | --- | --- |
| 登录 / 企业 | Demo 身份和标识；正式合成管理员登录、选择企业；企业/用户隔离由真实 HTTP/RLS核对 | VERIFIED；全部角色组合 NOT_RUN |
| 仪表盘 / 运营分析 | 指标、真实空态与未知用量、布局、筛选栏、直接访问/刷新 | VERIFIED；真实经营数据 NOT_RUN |
| 用户 / 企业 / 成员 | 两管理路由、表单与表格、角色相关导航视觉检查 | VERIFIED（浏览）；全部管理写操作 NOT_RUN |
| Agent / 模型配置 | 搜索空态，编辑 evidence_synthesis 保存后重开保留；凭证页、表单和运行状态；不输入真实 Key | VERIFIED；真实 Provider 列表/连接 BLOCKED |
| 知识库 | Demo 上传合成文件、重新处理 ready、中文检索预览；隔离 API 真实 multipart 上传、解析 ready 和超限 413 | VERIFIED（Demo 模拟与 API 真实解析分开）；全部异常流程 NOT_RUN |
| 客服三栏工作台 | Demo 发送模拟回答、备注、协作面板、消息来源跳记忆；正式 HTTP SSE/接管/备注隐私/游标/重复读取稳定 ID | VERIFIED；浏览器所有撤权/断网竞态 NOT_RUN |
| 个人记忆 | Demo 同意、预填、保存、版本更新、撤回清空；正式页面加载；服务端本人/跨用户/跨企业/来源/版本/撤回真实 HTTP | VERIFIED；真实模型使用记忆 BLOCKED |
| 工具 / 发布 / 向导 / 运行设置 | 逐页布局和空态；Demo 重新发布及公开入口；正式合成发布/访客 API | VERIFIED；真实工具/模型执行 NOT_RUN |
| 用量与审计 | 页面、筛选与费用详情面板，模拟调用总额未知、未知步骤 1、已知小计无，未按零计；费用接口调用链核对 | VERIFIED（Demo 浏览与静态）；真实账单 NOT_RUN |
| 独立访客 / Widget | Demo 与正式 Widget 会话及发送；正式 SSE/身份隔离/历史/接管 HTTP | VERIFIED；Safari/Firefox、阻止第三方存储和生产 HTTPS NOT_RUN |
| P15-A 轮询 / 分页 | 两端代码保留；真实 after/before/协作游标与重复 ID；Widget 关闭/恢复/移除浏览器核对 | VERIFIED；所有隐藏/企业切换/取消竞态 NOT_RUN |

## 数据、恢复与生产边界

0011 未修改历史。从零迁移及恢复均在本轮全新集群完成，未连接现有 dev/test/生产库。运行角色与迁移 owner 分离、均无 SUPERUSER/BYPASSRLS，HTTP 不注入迁移配置。完整备份使用隔离集群的备份管理员，不能用受 RLS 限制的运行角色冒充全库备份。

0011 downgrade 会删除记忆与同意数据：这是明确数据丢失风险。DEFERRED：由 DBA 在批准的升级窗口提出数据保留回退方案，先完整备份并在新库演练；不擅改已发布迁移、不自动 downgrade。删除与撤销重放依赖部署方维护可信的备份后记录，本轮合成重放不能证明真实环境记录完整。

数据库、私有文档、匹配密钥版本与配置必须形成同一备份批次：停止入口、排空写入、dump、文件快照、密钥独立保管、校验，再在全新目标恢复并重放撤销/删除。密钥轮换须保留所有未到期备份需要的历史密钥。建议初始保留基线及详细责任/故障处置见 [运维交接](P15_C_OPERATIONS.md)、[部署](DEPLOYMENT.md)、[检查清单](PRODUCTION_CHECKLIST.md)；未配置自动备份、清理或外部告警。

## 监控与有界可靠性

实际观察到带 request_id 的 JSON http_request 及 sse_closed 日志，既有健康、准入、Provider、工具和用量记录继续使用。耗时仅代表各自记录阶段，不能把响应头耗时当完整 SSE。外部日志保留、磁盘/数据库容量、证书、备份失败、拒绝率、Provider 错误、未知工具结果和告警路由由部署方配置；本轮没有引入独立监控平台。

合成小样本：12 次消息读取、4 workers，中位约 20.8 ms，观察最大约 30.2 ms；16 次共享准入、4 workers，中位约 5.5 ms，最大约 10.1 ms。SSE 租约上限 2，第三次被拒，释放后可再进入；独立 HTTP 限流实例按 200、200、429 返回并给 Retry-After。连接池检查结束 checked-out=0；单次 RSS 快照约 PostgreSQL 主进程 11 MiB、API 164 MiB。以上不是基准、容量承诺或优化比例，没有足够证据认定数据库热点/线程池瓶颈，故未做推测性优化。

NOT_RUN：目标规模并发会话、长时间 SSE、超大知识库分页/检索、真实 Agent 资源消耗、连接池耗尽、持续内存增长、进程强杀及生产排空。需要目标容量、资源预算和授权环境后另验；应用内部限流不能冒充 DDoS 防护。

## Pages、修改范围与证据

本地 Pages base=/kefuagent/，Hash 刷新与直接访问、Widget 路径和网络隔离已验证。既有手动 workflow_dispatch 工作流保留，不含 push 自动触发。GitHub Pages API 只读查询返回 404，无法据此确认仓库设置或权限状态；远端当前仅看到静态交付检查工作流。DEFERRED：管理员审阅后另行授权开启 Actions 来源、推送和手动部署；本轮没有公开 URL。

本轮增量主要涉及：

- 前端：`src/adapters/demo.ts`、`demo-data.ts`、`app/App.tsx`、`components/ui.tsx`、`features/admin/{Agents,Operations,Overview,Publications,index}.tsx`、新增 `UserMemory.tsx`、`features/chat/{ChatPage,shared}.tsx`、`features/visitor/VisitorPage.tsx`、`types/index.ts`、`styles/global.css`、`index.html`、新增 favicon、`vite.config.ts`（均相对 frontend/）。
- 后端与交付：`main.py`、`preflight.py`、`web/widget.js`，以及 Compose、Nginx 示例、CI、`.gitignore`。Dockerfile 和 Pages 工作流的已有 React 改动被保留，未冒充本轮新实现。
- 文档：README、FRONTEND、DEPLOYMENT、OPERATIONS、PRODUCTION_CHECKLIST，新增本记录与 P15_C_OPERATIONS。依赖新增/升级/删除为 0；P15-A/B 核心业务和 0011 历史保留。

本地忽略证据位于 `.local/p15c/`：http-results、rls-results、recovery-results、upload-results、capacity-results、http-rate-results、schema-check、浏览器截图和 wheel。截图为视口截图，13 页 1440×900，另存 Widget/正式记忆；早期窄屏截图仅为附加记录，不继续精修。完整起点差异快照和一次性验证脚本位于本机临时目录；未加入仓库测试体系。最终补核正式与 Demo Widget 的发送、离线回复、评价提交及紧凑嵌入布局均通过，消息分页保持横向。合成恢复备份包含模拟密钥，权限受限并保持本地，不能提交或公开；没有读取、覆盖或清理现有真实备份。

最终工作区保留未提交修改。生产 Linux/Docker/TLS、真实模型、生产容量、外部告警和真实灾难切换仍是上线缺口，不能宣称生产已验收。

收尾：本轮独立浏览器、API、Demo 预览、Widget 宿主及临时 PostgreSQL 已停止；合成备份与本地证据保留。最终 `git diff --check` 和交付资源/敏感信息/文档链接检查通过，暂存区为空，HEAD 未变。
