# 离线质量评测与检索

数据集 `data/customer_quality.json` v2 保留 18 场景的预期行为、相关性及人工评估依据。离线评测使用已有 PostgreSQL 知识库，只评估 manifest 选中且数据集有相关性标注的场景；其他场景仍可作为人工评估输入，不调用模型。

```bash
uv run python scripts/evaluate_quality.py --tenant-id TENANT_UUID --user-id USER_UUID --manifest MANIFEST.json
uv run python scripts/evaluate_quality.py --tenant-id TENANT_UUID --user-id USER_UUID --manifest MANIFEST.json --compare .local/evaluations/OLD_REPORT.json
```

先向该企业知识库导入评测文档，并准备 manifest：按场景 ID 指定 `knowledge_base_ids`，并用 `documents` 将数据集中的资料索引（例如 `"0"`）映射到已导入文档 UUID。可用 `--dataset` 指定数据集（默认 `data/customer_quality.json`），`--output` 指定输出目录。显式配置 `DATABASE_URL` 为运行角色，角色不得为 SUPERUSER 或 BYPASSRLS；企业、用户及成员关系须处于活动状态。评测在只读事务中检索，不自动导入文档或创建企业，不执行测试或阈值断言。

manifest 示例（用已有资源 UUID 替换占位符）：

```json
{"Q02": {"knowledge_base_ids": ["KNOWLEDGE_BASE_UUID"], "documents": {"0": "DOCUMENT_UUID"}}}
```

这是受信任本机操作员 CLI，用户 UUID 仅用于校验成员范围，不是公开认证接口。报告还保存企业和 manifest 的范围摘要；只有数据集、配置、Prompt 和范围摘要一致时才比较指标。

输出独立 JSON/Markdown，不覆盖已有报告。Recall@6 / MRR / nDCG@6 按唯一文档及标注等级计算，空相关性为 N/A；检索指标不能作为 AI 客服质量验收。

JSON 包含数据集版本及 SHA-256、检索配置、`none-no-model` Prompt 标识和每例检索结果。只有可比较的报告才计算差值，因此不与 P7 的完整 Oracle 报告直接比较；历史证据按原阶段保留。

## P7 历史结果与限制

2026-10-31，同一 v2 数据集、配置与 Prompt，对改动前 P6 检索和 P7 检索各执行一次：

| 指标 | P6 检索 | P7 检索 |
| --- | --- | --- |
| Recall@6 | 0.818182 | 1.0 |
| MRR | 0.818182 | 1.0 |
| nDCG@6 | 0.818182 | 1.0 |
| 引用有效/逐字匹配 | 1.0 / 1.0 | 1.0 / 1.0 |
| 预期拒答/工具成功/未授权拒绝 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |

11 个有相关文档的检索场景参与排名指标，改善来自两个新增探针。原始报告保留在本机 `.local/p7/baseline` 和 `improved`，含随机测试 UUID，未提交；以上是 P7 当时的小型合成集结果（P9 不再重跑该完整矩阵），非企业语料统计或真实客服效果。

## 检索决策

- 复用中文二字组 GIN 和英文 simple FTS GIN；中英词分别召回，每路最多 60 个候选，覆盖所有获授权知识库后统一合并。
- 增加有限、明确的中英词汇扩展和英语停用词。FTS 表达式只能由词法分析后的安全词构造，不接受用户 tsquery/SQL 片段。
- 对候选按词面覆盖率 >=0.4 过滤，保留已知恶意指令筛查；融合 FTS 两路及内容/标题覆盖排序，RRF 常数 60。该集验证整体修改有效，未单独证明 RRF 的独立增益。
- 沿用 1200 字分块、200 字重叠、页码/章节保存；长资料场景通过。本阶段没有足够证据更换分块算法。页码/章节仍从原解析器传递，引用须经当前租户、KB 授权、文档代次、逐字复核。
- PostgreSQL 实查无 vector 扩展：pgvector **DEFERRED**，未安装扩展/Embedding。Reranker **DEFERRED**：没有可验证的独立收益，不引入模型或依赖。

词面方法仍不能覆盖一般跨语言语义、任意同义表达或复杂矛盾；不能据此把真实模型质量标记通过。
