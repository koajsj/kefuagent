# 发布前静态审查

遵守 [AGENTS.md](../AGENTS.md)。发布前记录待发布 diff、环境和实际检查结果；本清单不授权构建、运行时验证或发布。

- 检查完整 diff、敏感文件、未提交改动和发布范围，保护用户数据与既有工作。
- 核对 API/DTO、租户与访客身份隔离、撤权、锁、幂等、工具权限、知识来源及个人记忆同意的调用链。
- 审查 ORM、增量迁移、复合外键、索引和 FORCE RLS 声明；不启动数据库，不执行迁移或查询。
- 执行现有 Ruff/格式、Python AST/离线迁移、TypeScript、JavaScript/HTML/模块、Markdown 链接和敏感内容检查。
- 核对依赖锁文件、漏洞与许可证信息、Docker/代理/环境变量和部署恢复文档。不可用工具标记 NOT_AVAILABLE，不为检查新增大型框架。
- 核对 CI 仅做静态检查；无数据库服务、运行时兼容性矩阵或测试执行。独立的手动 Pages 发布仍须用户明确授权。

结果使用 PASS、FAIL、NOT_RUN、NOT_AVAILABLE、NEEDS_RUNTIME_VERIFICATION、FALSE_POSITIVE。实际数据库权限、并发、浏览器、Provider、构建产物、恢复和生产容量不由静态通过证明，需单独授权；未获得证据时列为待运行确认。不得为了发布自行恢复测试体系或启动服务。

产品改动的历史证据见 [专项记录](PRODUCT_QUALITY_ACCEPTANCE.md)，不是当前 CI 或生产通过证明。
