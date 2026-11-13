# React 前端与静态 Demo

管理台、客服三栏工作台和访客页共享 React 19、TypeScript、React Router、HeroUI v3、Tailwind v4 与 Lucide。具体版本由 `frontend/package.json` 和 `package-lock.json` 固定，Node 构建要求 22.12+。运行 Python 服务不需要 Node。

## 当前工作台补充（静态审查阶段）

本次增加知识分块的代次/修订历史、原文位置、完整文本对照及管理员编辑/逻辑删除/恢复；历史代只读，修改以当前 ID 防并发覆盖，取消请求不等于服务端回滚。Trace 显示阶段、关联 ID、真实记录的时间及未知状态；过期运行租约不冒充正常运行，客户端收取结果未知。回答反馈增加分类/状态筛选、原问题跳转、人工意见及知识库/文档/Chunk 关联，保存需 `expected_revision`。上述功能在原 Adapter 与 Demo 均有独立路径，但本轮未运行 Demo 或浏览器；旧静态网页没有这些新操作。

- 知识库/文档提供「删除影响」预览，披露已知文档和版本数量及未知的历史关联；物理删除 BLOCKED，界面不发起执行或显示成功。原分块逻辑删除/恢复继续可用；Demo 同步这一阻断语义。
- 会话可按完整标签筛选及最近客户发言排序；个人视图和快捷回复按模式、企业、用户保存在本机浏览器，每类最多 100 项。仅支持会话标题、客服姓名两个文本变量，插入后编辑并手动发送；不属于企业共享模板。Demo 使用标签页专属命名空间，随演示重置清除。
- 草稿及待确认请求按企业、用户、会话隔离；旧的无用户键不自动迁移。已发生或未知结果仍应从服务端历史检查，不盲目重发。已读位置仅在最新页已提交到 DOM、页面可见且接近底部时推进；浏览旧消息保留新消息入口。
- 最近运行可展开时间线和回答级人工反馈。诊断仅发起人/企业管理员可读，反馈是内部协作备注，处理状态仅管理员或当前负责人可改；不自动写入知识或记忆。概览可筛选访客满意度并跳转原会话，满意度不是 AI 准确率。
- Agent 配置页提供版本/变更字段记录，不保存历史 Prompt 正文，不支持历史恢复；当前版本和发布版本仍沿用原机制。知识页只展示真实返回的最终命中排名、策略、分数和来源，不能展示后端未采集的候选过滤过程。

这些功能的本轮证据仅为源码、类型和契约检查，见[深度审查记录](DEEP_AUDIT_REPORT.md)。没有 React 构建产物时服务仍回退旧 ES Modules；旧界面不具备上述新增视图、反馈与时间线，不承诺与 React 功能对等。本轮未构建、未验收浏览器或正式 API。

## 本机开发与交付

```bash
npm ci --prefix frontend
npm run check --prefix frontend
npm run build --prefix frontend
npm run build:demo --prefix frontend
```

正式产物在 `src/support_agent/web-react`，Demo 产物在 `frontend/dist-demo`。两者均忽略 Git。正式构建完成后再构建 wheel（`uv build --wheel`）；Hatch 显式包含已生成的 React 资源。Dockerfile 有独立 Node 构建阶段。

正式 FastAPI 仍使用 `/`、`/assets/*`、`/chat/{publication_id}`、`/widget.js`。检测到正式 React 构建时交付新页面；没有构建时暂时回退旧界面。旧 `web/` 保留供迁移参照与回退，不在本轮删除。管理端使用 Hash 路由，访客端保留原公开 URL。

`npm run dev --prefix frontend` 启动 Vite，并将 `/api` 代理到本机 8000；开发访问地址须与后端 `WEB_ORIGIN` 一致，否则 Cookie 写操作会被拒绝。更简单的集成检查方式是构建后从 FastAPI 的同一可信 Origin 访问。

## 页面与职责

- `app/`：登录、企业切换、角色导航、路由、页面错误边界和提示。
- `components/`、`styles/`：HeroUI 控件、编辑弹窗、统一表格/错误/空态、语义颜色与减少动画。
- `features/admin`、`knowledge`：向导、概览、用户/企业/成员、模型凭证、Agent/知识库/工具授权、发布、用量及审计。
- `features/chat`：主消息、运行记录、摘要及协作面板独立加载；人工处理、运营编辑与 SLA。
- `features/visitor`：独立访客身份、聊天、历史、评价和结束。
- `adapters/`：正式网络协议、纯本地 Demo、SSE、幂等摘要、可取消的有界集合及标签页存储。

所有页面只调用 Adapter。正式模式沿用 HttpOnly Cookie、X-Tenant-ID 选择器及服务端成员验证；访客使用 `Authorization: Visitor …`，`credentials: omit`，不携带管理身份。企业切换取消旧管理请求并重挂载页面；不把模型输出当授权。

P15-A 后端摘要逻辑未在本轮改写。前端保留主会话与附属面板独立加载、稳定 ID 去重、5 秒轮询与最长 60 秒退避、隐藏/离开/关闭时停止、协作 `before` 游标、Agent `q/limit/offset` 搜索及停用选择项。有界集合接受 499/500，501 明确报错。SSE 不自动重连；未知结果保留原幂等标识。已经发送的内容不能撤回。

访客发送由服务端会话状态决定处理方式：AI 状态使用原回合；等待人工或人工接管时，React 使用独立 `POST /public/{pid}/sessions/{sid}/messages`，返回 `status: received`、`message_id`、`conversation_id` 和 `request_id`，不调用模型。JSON `/turns` 和 SSE `/turns/stream` 仍兼容人工消息，旧访客页继续使用这一入口；SSE 通过 `completed` 返回回执。结果未知时保留原发送模式、内容和幂等键，以原入口恢复，不能因模式切换重新发起另一轮。双端通过 5 秒轮询同步，失败最长退避 60 秒。

会话队列默认按最近消息活动排序，未读只统计公开会话客户消息，不包含客服回复、工具或内部备注。`POST /conversations/{id}/read` 的消息游标属于当前成员，单调前进。个人记忆来源用 `GET /conversations/{id}/messages/{message_id}` 精确定位并复用历史交付校验；不扫描全量历史。`GET /user-memory/usage/{call_id}` 仅本人可查实际发送的记忆版本，普通模型调用列表不会暴露该字段。两个消息端仅在最新页且已位于底部时自动滚动。

Demo 首次引导可跳过或重新打开；重置只清除 `kefu.static-demo.` 存储命名空间。完整人工闭环在同标签页共享虚构数据，Widget 的旧访客会话也随重置失效。演示的记忆使用为本地模拟，不代表真实模型调用。

共享存储被其他同源 iframe 清除后，不再回退到本页面缓存的旧值；写入失败的键使用最新内存值，删除失败的已知键保留本上下文失效标记，逐键清理不会因单个异常跳过其他键。浏览器禁止存储枚举时无法发现其他页面创建的键，不同页面/iframe 的内存也互不共享，无法保证跨上下文同步和重置，应使用独立客服链接；该限制不构成正式模式的服务端撤权保障。

## Demo 隔离与 Pages

```bash
npm run dev:demo --prefix frontend
# 或构建后
npm run preview:demo --prefix frontend
```

访问终端显示 Origin 的 `/kefuagent/`。全部数据为虚构，操作只存在当前标签页（存储不可用时使用内存），不上传文件正文、不保存输入的 Key/密码。上传、检索、摘要和 AI 回复均为模拟，不能视为真实解析、检索或模型验收。不同标签页的 Demo 状态不实时同步；同源、同一标签页的 Widget 预览在每次本地请求前重新读取演示状态，消息通过既有轮询同步；浏览器禁止存储时，各页面仅保留自己的内存状态，不能跨 iframe 同步。

Vite 构建时将 `@adapter` 分别解析到正式或 Demo 实现；构建期双向拒绝混入另一模式的 Adapter。Demo HTML 配置 `connect-src 'none'` 和 `form-action 'none'`；不读取正式 API 地址、Cookie 或凭证，标签页存储也有独立命名空间。正式构建不包含虚构 Demo Adapter。

Pages 基路径固定 `/kefuagent/`，使用 `#/…` 解决刷新路由。Demo 访客 URL 是 `/kefuagent/#/chat/UUID`，演示 Widget 由同一基路径加载。正式 Widget 协议不变，宿主只加载约 2.6 KB 的独立 iframe 加载器，不注入管理应用。分享地址来自服务端受验证的 `WEB_ORIGIN`；Demo 地址只指向当前静态构建 Origin 和固定基路径。

`.github/workflows/pages-demo.yml` 仅支持 `workflow_dispatch`，需要仓库管理员授权并配置 GitHub Pages 的 Actions 来源后手动执行。演示入口为 [KefuAgent Demo](https://koajsj.github.io/kefuagent/)，实际发布记录见 [Pages Actions](https://github.com/koajsj/kefuagent/actions/workflows/pages-demo.yml)。更换仓库名时需同步修改 Vite 的 Demo base。

## 组件来源

实际读取并使用了 Frontend Design、BoardUI、HeroUI Skills；实际调用 BoardUI MCP 的发现、免费组件目录、stat-cards 完整源码和 sidebar 示例，以及 HeroUI MCP 的安装和组件文档。HeroUI 作为唯一主要组件库实际使用 Button、Chip、Skeleton、TextField/Input 和 Modal；BoardUI 只借鉴侧栏分组、信息层级和指标布局，不移植其源码，也不引入其基础组件依赖。没有使用 Pro 源码或许可证。

HeroUI 包为 Apache-2.0，React/Vite/Tailwind/Router 为 MIT，Lucide 为 ISC；安装包原始许可证/声明汇总在 `frontend/THIRD_PARTY_NOTICES.txt`，构建时同时分发。`client-only` 的 npm 元数据标注 MIT，但发行包缺少许可原文；当前纯浏览器构建以本项目自写的空虚拟模块处理其副作用标记导入，并在正式/Demo 全构建图中禁止原包模块，原包代码不分发。锁文件仍保留安装关系；SSR/RSC 或原包再分发须另行审查。依赖清单与官方安装参考见 [依赖授权记录](DEPENDENCY_LICENSES.md)。

## P15-C 产品完善与实际验收

以常见电脑浏览器尺寸为验收重点，不再扩展移动端视觉改造；具体通过范围以实际浏览器验收记录为准。

统一柔和中性色、蓝色主操作、边框表格、留白和信息层级；页头筛选横向排列，空分页不再显示 1–0。保留轻量过渡、骨架屏和 reduced-motion，侧栏提供展开语义及跳到主内容的键盘入口。

个人记忆页面支持本人当前企业的显式同意、查看、来源摘录保存、版本更新、期限、删除、清空、过期清理和撤回同意；内部会话本人的用户消息可带来源进入表单，仍需人工确认。Agent 编辑保留 P15-B 的回答模式；用量详情独立读取费用核算，未知费用保持未知。Demo 提供对应本地模拟，不能据此证明服务端权限。

Widget 和发布预览 iframe 允许表单事件，仍受页面 CSP 限制；关闭时卸载为 about:blank，以停止轮询，重开沿用标签页访客。重复脚本只保留一个实例。嵌入模式采用紧凑布局，评价按需展开；消息分页使用独立类名，避免与组件库样式冲突。跨 Origin 正式 Widget 的发送、离线回复、Cookie 隔离、关闭、恢复与移除已在本机浏览器核对；Demo Widget 仅请求静态资源。浏览器阻止第三方存储时仍须提供独立链接。

React Aria 的固定内联样式使用精确 SHA-256 CSP 例外；没有启用 unsafe-inline。依赖升级若改变该样式，须重新计算并用浏览器复核，不能扩大为任意内联样式。

实际记录见 [P15-C 交付记录](P15_C_ACCEPTANCE.md)：正式/Demo 构建、wheel、13 页浏览器与网络隔离、本机 FastAPI、全新 PostgreSQL 迁移/RLS和合成恢复分别标明证据。未恢复自动化测试体系，也未调用真实模型。Docker、Linux、真实 HTTPS 代理、生产部署仍需验收，公开 Pages 状态需实际验证；剪贴板、跨浏览器、真实模型语义和目标规模容量也不能由本次结果推断。

浏览器人工检查建议：进入 Demo → 搜索/分页 Agent → 导入/查看资料 → 会话发送/人工接管/备注/历史 → 发布/下线 → 打开独立访客和 Widget 预览 → 切换企业检查清空 → 窄屏和键盘焦点 → 网络面板确认没有 API 请求。正式环境需另验 Cookie、Visitor、权限撤销、SSE 中断和来源失效，不把静态 Demo 的成功当作这些能力通过。

## 2026-11-06 公开发布前复核

- PASS：TypeScript、正式/Demo 独立构建、Python 静态检查及 wheel 资源交付检查；发布路径与本地文档引用扫描。
- PASS：Chrome 中 13 个管理路由在 1440×900 直接访问；概览、Agent、知识库、发布、运营、会话在 1024×768 和 1920×1080 检查初始布局。README 三张截图来自虚构数据的真实浏览器。
- PASS：Agent 搜索空态、合成 22 项的 20/2 分页及返回、弹窗 Escape/焦点恢复、键盘跳到主内容；人工接管、内部备注、独立访客模拟回答、Widget 人工回复轮询及关闭/续接。
- PASS：Demo CSP 阻断同源 API 探针；Widget 验收未出现 API、模型或第三方网络请求。构建图拒绝混入正式 Adapter，未分发 `client-only` 原包。
- NOT_RUN：所有筛选组合、所有面板展开状态、跨浏览器和完整移动端视觉验收。当时人工接管期间访客不能追加问题，已在下述修复中补齐。

线上部署结果以 [Pages Actions](https://github.com/koajsj/kefuagent/actions/workflows/pages-demo.yml) 和实际公开站点为准；本节本地结果不代替线上验收。

## 2026-11-07 人工双向消息修复

FIXED：正式与 Demo 接管后可继续接收访客消息；人工消息不占用模型配额，不伪造 AI 回复。正式消息使用访客会话范围的稳定 ID 去重，并在同一会话锁内与处理模式切换串行。人工消息写入时间使用数据库实际时钟，避免先开始、后写入的事务被增量游标漏读；无迁移、依赖或样式变更。

PASS：全新隔离 PostgreSQL 的真实 HTTP 验证 JSON/SSE、重试/冲突、等待人工、恢复 AI、跨模式重试、访客身份隔离、关闭拒绝与人工消息零模型调用；事务交错的游标漏读先复现、修复后通过。Chrome 在正式 Widget 与静态 Demo 中分别完成连续两轮双向轮询、备注隔离、关闭/恢复。Demo Adapter 另核对去重和跨模式重试。构建及 Python 检查通过；这些结果不代表真实模型、跨浏览器或线上部署验收。

## 产品质量专项增量（本轮）

上面的浏览器/构建记录为本轮开始前已有的验收内容。本轮新增成员未读、精确来源定位、底部滚动策略、个人记忆使用记录及 Demo 引导/重置；它们仅通过 TypeScript、Node Adapter 原子检查和隔离 HTTP 验证，未重跑浏览器或构建，不能沿用旧截图/构建结果宣布新增交互已验收。详见[本轮记录](PRODUCT_QUALITY_ACCEPTANCE.md)。


私有客服增量：客户/工单页接真实 CRUD、版本冲突、历史/关联、站内通知及客户引用记忆；客服会话侧栏接客户确认、工单、交接事实包和附件。新增模型路由、自治策略、执行/质量、集成/治理/恢复/设置入口复用同一 Adapter，未实现能力以 BLOCKED/UNKNOWN 显示。HeroUI3 是实际组件体系（含 Table）；BoardUI MCP/Skill 用于工作台层级参考，Taste framed-sheet 用于共享框架/内容纸面，不加入第二套 UI 依赖。22 个导航领域中部分共用现有业务视图，不代表 22 个独立模块均完整。静态 Demo 仅虚构状态；附件仅演示元数据，不能下载虚构文件冒充已存储正文。未做浏览器或截图验收，历史图片不代表当前布局。


## 专项 B 工作流（源码完成，运行验收待授权）

`KnowledgeIntelligence` 复用现有 Panel/DataTable/Field/HeroUI Button，管理导航的检索诊断和索引入口共用真实 API 页面：配置/排队/逻辑重建、缺失 Chunk、失败原因，文档/章节过滤，关键词、向量、RRF、可选 LLM 重排及最终证据候选分栏。候选不是已经生成的引用，不标伪造相关率。

客户详情中的 `CustomerExports` 提供范围预览、人工审查确认、申请、分页任务/manifest/错误、刷新和授权 ZIP 下载。`ReplySuggestions` 仅出现在有权操作的人工会话，调用独立草稿 API，显示生成/失败/到期、编辑、来源、复制、反馈/拒绝、执行 Trace；采纳须先保存本版本编辑并勾选人工审核确认，服务端版本与幂等发送约束独立生效。切企业/用户/会话隔离组件，请求取消和生成轮询/退避沿用现有模式。

正式 Adapter 使用现有鉴权 JSON/Blob 请求。Demo 的三项 B 接口明确返回 `product_capability_unavailable`，页面显示 NOT_AVAILABLE，不模拟付费索引、客户 ZIP 或发送授权。本轮读取 BoardUI/HeroUI/Taste Skills，实际调用 BoardUI get_started/list_components、HeroUI Button/TextArea/Table 文档，运行 Taste 本地布局建议；未新增组件库、依赖或 Mock。TypeScript 静态通过；无构建、浏览器或截图验收。
