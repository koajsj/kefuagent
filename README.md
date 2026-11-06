<div align="center">

# KefuAgent

**Open-source AI Customer Support Platform**

面向企业的多租户客服平台，连接知识检索、AI Agent 与人工协作。

[![Python](https://img.shields.io/badge/Python-3.11--3.14-blue)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)](https://fastapi.tiangolo.com/) [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-4169E1)](https://www.postgresql.org/) [![React](https://img.shields.io/badge/React-19-087EA4)](https://react.dev/) [![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[静态演示入口](https://koajsj.github.io/kefuagent/) · [快速开始](docs/QUICK_START.md) · [部署指南](docs/DEPLOYMENT.md) · [网站集成](docs/WEBSITE_INTEGRATION.md)

</div>

## 产品概览

KefuAgent 采用 FastAPI 和 PostgreSQL 模块化单体，提供 React 管理工作台、独立访客聊天和网站 Widget。企业可以管理知识与 Agent 配置，在会话中查看来源、分配负责人、人工接管和添加内部备注，并查看用量与运营信息。

- **知识与回答**：导入 PDF、DOCX、TXT 和 Markdown；使用 PostgreSQL 全文检索、中文词面扩展及有界召回，回答关联来源并校验引用。
- **有界 Agent**：接入兼容 Chat Completions 的模型服务，工具须静态注册并授权，支持预算、调用记录和审计；不执行任意代码或数据库写操作。
- **人工协作**：会话队列、转交、优先级、内部备注和 SLA 与公开访客入口协同工作。
- **企业隔离**：服务端成员授权结合 PostgreSQL FORCE RLS；访客身份独立于管理身份，模型凭证加密保存。
- **运营与记忆**：展示会话、模型用量与未知费用；个人记忆需要明确同意，可查看、修改、删除和撤回。

## 界面预览

![管理概览](docs/images/demo-dashboard.png)

![客服工作台](docs/images/demo-workbench.png)

![知识库](docs/images/demo-knowledge.png)

## 静态演示

[打开静态 Demo](https://koajsj.github.io/kefuagent/)。站点由[手动 Pages 工作流](https://github.com/koajsj/kefuagent/actions/workflows/pages-demo.yml)发布。演示使用虚构数据和浏览器本地 Adapter，不连接 API、数据库或真实模型；上传、检索与回答均为模拟，不代表正式环境或模型效果。

本地体验需要 Node 22.12+：

```bash
npm ci --prefix frontend
npm run dev:demo --prefix frontend
# 或构建并预览
npm run build:demo --prefix frontend
npm run preview:demo --prefix frontend
```

访问终端显示地址下的 `/kefuagent/`。Pages 工作流仅支持管理员授权后的手动 `workflow_dispatch`，详见[前端说明](docs/FRONTEND.md)。

## 本机运行

需要 Python 3.11–3.14、PostgreSQL 15+、Node 22.12+ 和 [uv](https://docs.astral.sh/uv/)。全新 macOS 开发环境：

```bash
git clone https://github.com/koajsj/kefuagent.git
cd kefuagent
uv sync --locked
npm ci --prefix frontend
npm run build --prefix frontend
uv run python -m support_agent.cli setup --configure
# 确认目标数据库并获得授权后执行
uv run alembic upgrade head
uv run python -m support_agent.cli create-admin
uv run python -m support_agent.cli setup
uv run uvicorn support_agent.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

打开 <http://127.0.0.1:8000>；浏览器地址须与 `WEB_ORIGIN` 一致。已有数据库先备份，配置和首次使用详见[快速开始](docs/QUICK_START.md)。正式 React 资源随 Python 包交付，运行服务无需 Node；未构建时暂时回退旧界面。

Dockerfile 提供 Node 构建阶段，Compose 及生产配置、权限、备份和恢复要求见[部署指南](docs/DEPLOYMENT.md)。部署方应先检查配置和数据库授权；Docker 实际运行及生产环境尚未完成验收。

## 架构与边界

React 管理台、访客页和 Widget 通过 FastAPI 接入同一个模块化单体；应用使用 PostgreSQL 保存业务数据，私有目录保存文档，模型请求访问部署方批准的 HTTPS 端点。检索没有向量数据库，来源校验不保证事实或语义正确。SSE 展示运行阶段并在校验后交付结果，不表示上游逐 token 输出。工具只允许经授权的低风险只读能力；本项目也不是完整的全渠道客服系统。

离线、本机和隔离环境的验收范围见 [P15-C 记录](docs/P15_C_ACCEPTANCE.md)；真实模型质量、生产容量、Docker 与实际生产部署仍需单独验证。不要将静态 Demo 视为生产验收。

## 文档

- [首次使用](docs/FIRST_RUN.md) · [前端与 Demo](docs/FRONTEND.md) · [网站集成](docs/WEBSITE_INTEGRATION.md)
- [架构](docs/ARCHITECTURE.md) · [部署与恢复](docs/DEPLOYMENT.md) · [生产检查清单](docs/PRODUCTION_CHECKLIST.md) · [运维与安全](docs/OPERATIONS.md)
- [AI 能力与离线验收](docs/P15_B_AI_UPGRADE.md) · [产品与生产准备记录](docs/P15_C_ACCEPTANCE.md)

项目采用 [MIT License](LICENSE)，第三方依赖许可证见[依赖授权记录](docs/DEPENDENCY_LICENSES.md)。
