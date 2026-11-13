# 安装依赖与许可证

2026-11-13 静态复核：42 个锁定 PyPI 包中，本机已安装的 40 个版本匹配且所列授权文件存在；greenlet、tzdata 未安装。npm 的 214 个锁条目与根清单直接依赖匹配，非根条目均声明 license；声明不代替许可原文和分发义务。GitHub Actions 的 uses 均固定 40 位 SHA。本轮未修改依赖、联网查漏洞库、核验上游 SHA 身份或构建 wheel/镜像，历史漏洞查询结果不代表当前状态。

2026-11-07 续作静态复核：当前锁定 42 个 PyPI 包，本机安装的 40 个版本与锁文件一致，发行版均附带许可证文件；`greenlet`、`tzdata` 未安装于当前平台，未据此声称其发行文件已检查。npm 锁文件与根清单一致，声明许可涵盖 MIT、Apache-2.0、ISC、0BSD、BSD-3-Clause、MPL-2.0 和 CC-BY-4.0，分发仍须保留对应原文及署名。当前 npm audit 无命中；42 个锁定 Python 包的 OSV 精确版本查询无命中。这是查询当时的公告覆盖结果，不是无漏洞或镜像层通过保证；没有安装、升级或删除依赖。

历史快照：2026-10-30 本机 Python 3.13.18 环境，包含当时的开发和测试依赖，并非当前锁文件清单。读取实际安装发行版元数据及列出的授权文件；这里不替代授权原文，打包分发必须保留完整许可证及第三方声明。未修改这些库。

2026-10-31 对本项目 `.venv` 的发行版元数据核对：下表中的 httpcore2、httpx2、iniconfig、packaging、pluggy、Pygments、pytest、truststore 已不在当前环境，其余所列包及版本仍存在。实际分发应以目标环境安装的发行版及其许可证为准；本记录保留历史快照，不代表镜像已检查。

| 包 | 版本 | 元数据授权 | 实际保留的授权文件 |
| --- | --- | --- | --- |
| alembic | 1.20.1 | MIT | alembic-1.20.1.dist-info/licenses/LICENSE |
| annotated-doc | 0.0.5 | MIT | annotated_doc-0.0.5.dist-info/licenses/LICENSE |
| annotated-types | 0.8.0 | MIT | annotated_types-0.8.0.dist-info/licenses/LICENSE |
| anyio | 4.15.1 | MIT | anyio-4.15.1.dist-info/licenses/LICENSE |
| argon2-cffi | 25.1.0 | MIT | argon2_cffi-25.1.0.dist-info/licenses/LICENSE |
| argon2-cffi-bindings | 26.1.0 | MIT | argon2_cffi_bindings-26.1.0.dist-info/licenses/LICENSE |
| attrs | 26.1.0 | MIT | attrs-26.1.0.dist-info/licenses/LICENSE |
| certifi | 2026.10.23 | MPL-2.0 | certifi-2026.10.23.dist-info/licenses/LICENSE |
| cffi | 2.1.1 | MIT-0 | cffi-2.1.1.dist-info/licenses/LICENSE |
| click | 8.5.0 | BSD-3-Clause | click-8.5.0.dist-info/licenses/LICENSE.txt |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | cryptography-50.0.2.dist-info/licenses/LICENSE; cryptography-50.0.2.dist-info/licenses/LICENSE.APACHE; cryptography-50.0.2.dist-info/licenses/LICENSE.BSD |
| fastapi | 0.162.0 | MIT | fastapi-0.162.0.dist-info/licenses/LICENSE |
| h11 | 0.16.0 | MIT | h11-0.16.0.dist-info/licenses/LICENSE.txt |
| httpcore | 1.0.9 | BSD-3-Clause | httpcore-1.0.9.dist-info/licenses/LICENSE.md |
| httpcore2 | 2.16.0 | BSD-3-Clause | httpcore2-2.16.0.dist-info/licenses/LICENSE.md |
| httpx2 | 2.16.0 | BSD-3-Clause | httpx2-2.16.0.dist-info/licenses/LICENSE.md |
| idna | 3.20 | BSD-3-Clause | idna-3.20.dist-info/licenses/LICENSE.md |
| iniconfig | 2.3.1 | MIT | iniconfig-2.3.1.dist-info/licenses/LICENSE |
| jsonschema | 4.26.0 | MIT | jsonschema-4.26.0.dist-info/licenses/COPYING |
| jsonschema-specifications | 2025.9.1 | MIT | jsonschema_specifications-2025.9.1.dist-info/licenses/COPYING |
| lxml | 6.1.3 | BSD-3-Clause | lxml-6.1.3.dist-info/licenses/LICENSE.txt; lxml-6.1.3.dist-info/licenses/LICENSES.txt |
| Mako | 1.4.3 | MIT | mako-1.4.3.dist-info/licenses/LICENSE |
| MarkupSafe | 3.0.4 | BSD-3-Clause | markupsafe-3.0.4.dist-info/licenses/LICENSE.txt |
| opentelemetry-api | 1.45.1 | Apache-2.0 | opentelemetry_api-1.45.1.dist-info/licenses/LICENSE |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | packaging-26.3.dist-info/licenses/LICENSE; packaging-26.3.dist-info/licenses/LICENSE.APACHE; packaging-26.3.dist-info/licenses/LICENSE.BSD |
| pluggy | 1.7.0 | MIT | pluggy-1.7.0.dist-info/licenses/LICENSE |
| psutil | 7.2.2 | BSD-3-Clause | psutil-7.2.2.dist-info/LICENSE |
| psycopg | 3.3.6 | LGPL-3.0-only | psycopg-3.3.6.dist-info/licenses/LICENSE.txt |
| psycopg-binary | 3.3.6 | LGPL-3.0-only | psycopg_binary-3.3.6.dist-info/licenses/LICENSE.txt |
| pycparser | 3.12 | BSD-3-Clause | pycparser-3.12.dist-info/licenses/LICENSE |
| pydantic | 2.14.1 | MIT | pydantic-2.14.1.dist-info/licenses/LICENSE |
| pydantic-settings | 2.16.2 | MIT | pydantic_settings-2.16.2.dist-info/licenses/LICENSE |
| pydantic_core | 2.50.1 | MIT | pydantic_core-2.50.1.dist-info/licenses/LICENSE |
| Pygments | 2.21.0 | BSD-2-Clause | pygments-2.21.0.dist-info/licenses/LICENSE |
| pypdf | 6.21.4 | BSD-3-Clause | pypdf-6.21.4.dist-info/licenses/LICENSE |
| pytest | 9.2.0 | MIT | pytest-9.2.0.dist-info/licenses/LICENSE |
| python-docx | 1.2.0 | MIT | python_docx-1.2.0.dist-info/licenses/LICENSE |
| python-dotenv | 1.2.4 | BSD-3-Clause | python_dotenv-1.2.4.dist-info/licenses/LICENSE |
| python-multipart | 0.0.32 | Apache-2.0 | python_multipart-0.0.32.dist-info/licenses/LICENSE.txt |
| referencing | 0.37.0 | MIT | referencing-0.37.0.dist-info/licenses/COPYING |
| rpds-py | 2026.9.1 | MIT | rpds_py-2026.9.1.dist-info/licenses/LICENSE |
| ruff | 0.17.3 | MIT | ruff-0.17.3.dist-info/licenses/LICENSE |
| SQLAlchemy | 2.0.55 | MIT | sqlalchemy-2.0.55.dist-info/licenses/LICENSE |
| starlette | 1.10.0 | BSD-3-Clause | starlette-1.10.0.dist-info/licenses/LICENSE.md |
| truststore | 0.10.5 | MIT | truststore-0.10.5.dist-info/licenses/LICENSE |
| typing-inspection | 0.4.4 | MIT | typing_inspection-0.4.4.dist-info/licenses/LICENSE |
| typing_extensions | 4.16.0 | PSF-2.0 | typing_extensions-4.16.0.dist-info/licenses/LICENSE |
| uvicorn | 0.54.0 | BSD-3-Clause | uvicorn-0.54.0.dist-info/licenses/LICENSE.md |

psycopg/psycopg-binary 为 LGPL-3.0 系列，certifi 为 MPL-2.0；cryptography 为 Apache-2.0/BSD 双许可并包含底层库声明，lxml 及其二进制组件以包内各授权文本为准。快照记录时没有静态链接、改库或制作二进制分发；分发包/镜像必须复查实际依赖和附带组件的授权义务，并保留适用的授权文件。

## React 前端（2026-11-06）

前端精确依赖和传递依赖见 `frontend/package-lock.json`。已读取安装包的元数据与根目录许可证/声明文件；运行依赖原文汇总到 [THIRD_PARTY_NOTICES](../frontend/THIRD_PARTY_NOTICES.txt)，随两种构建分发。没有修改上游包，没有移植 BoardUI 源码。

- HeroUI React/Styles：Apache-2.0；[官方安装指南](https://heroui.com/docs/react/getting-started/quick-start)要求 React 19+ / Tailwind v4，无 Provider。
- React、React DOM、React Router、Tailwind、Vite、TypeScript：MIT；React Aria 与国际化依赖的声明保留在汇总文件中。
- Lucide：ISC。BoardUI CLI 的 npm 元数据为 MIT，但本轮仅使用 MCP/Skill 方案参考，不分发 BoardUI 组件源码。
- `client-only@0.0.1` 的 [npm 发行元数据](https://www.npmjs.com/package/client-only)声明 MIT，但包内没有许可原文或版权声明，不能据此臆造 Meta/Vercel 归属。本纯浏览器 SPA 在 Vite 将其无绑定的副作用导入替换为本项目自写的空虚拟模块，正式/Demo 全构建图均禁止任何 `node_modules/client-only/` 模块；不分发原包三个文件或 npm archive。锁文件保留安装关系，未升级/删除依赖。此边界不适用于未来 SSR/RSC、node_modules/npm 缓存或原包再分发；这些发布须重新解决许可来源。

兼容性来源：[Vite](https://vite.dev/guide/)、[Tailwind Vite](https://tailwindcss.com/docs/installation/using-vite)、[React Router](https://reactrouter.com/start/declarative/installation)，以及实际安装 peerDependencies。构建和 npm ls 验证的是本机锁定组合，不代表所有平台通过。
