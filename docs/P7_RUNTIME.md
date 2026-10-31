# P7 流式交付、密钥与数据维护

## SSE 契约

保留所有非流式接口，新增 POST：

- `/api/v1/conversations/{conversation_id}/agent-turns/stream`：认证、X-Tenant-ID、AgentTurnInput 与原 agent-turns 相同。
- `/api/v1/public/{pid}/sessions/{sid}/turns/stream`：Visitor 令牌、VisitorTurn 与原 turns 相同，访客不能指定企业/Agent/会话。

响应 `text/event-stream`，每帧 `event: NAME\ndata: JSON\n\n`，10 秒空闲注释保活，`Cache-Control: no-store`、`X-Accel-Buffering: no`。代理须关闭 SSE 缓冲并保留至少 180 秒读超时。成功建流后业务错误通过事件表达，HTTP 200 不代表成功；认证和输入错误也可能在建流前返回原 JSON 错误。

| 事件 | 含义 |
| --- | --- |
| stage | pending / retrieving / model_running / tool_running，只交付阶段名 |
| delta | 通过最终检查的答案片段，含 text / call_id |
| completed | 与非流式 AgentTurnOut 相同的最终答案、引用、执行状态 |
| pending | 同键请求仍在执行；结果未知，保留 key，不创建新轮次 |
| failed / timed_out | 错误分类，可能含 result_unknown / discard_deltas；清除临时展示并查询历史 |

采用**运行阶段实时流 + 已提交答案分段交付**。上游 Provider 继续使用兼容的非流式协议，不承诺逐 token 首字延迟：RAG 是证据选择 JSON，工具参数需要完整校验，且在途撤权必须禁止原始文本交付。先执行既有有界 Agent 循环和完整结算，最终持久化成功后才交付答案；每段前重新验证身份、工具及知识来源，不显示推理或半截工具参数。并非原生上游 token streaming，后者 **DEFERRED**，须另行设计可撤回的授权交付和流式用量协议。

断连不取消已开始的有界执行、不自动重发；服务关闭等待已开始任务，进程崩溃仍使用原租约归类未知结果。每进程最多 32 个流式任务，企业/用户/访客/Agent 原有限额继续生效；这不是生产代理连接限流替代品。分段前检查事务已提交，不在网络等待期间持有事务。检查后字节发出与撤权无法构成分布式原子操作，已发字节不可撤回。

管理/访客页面采用 POST fetch 流解析，不用会自动重连的 EventSource。切换企业取消读取、抑制旧上下文结果；会话发送期间不能切换会话，禁止重复发送。失败保留完整输入与原幂等键，重试由用户明确触发。引用/工具结果使用 textContent 安全渲染。

## 版本化主密钥

继续 AES-256-GCM / 12 字节随机 nonce。旧记录 AAD 为 `v1:tenant:ref`，无封装的旧密文仍兼容；新记录封装包含 key ID，AAD 为 `v2:key_id:tenant:ref`，版本、企业和引用不能互换。未知版本安全失败，不试遍密钥。

新增受保护环境配置：

- `CREDENTIAL_KEYRING`：JSON 对象，最多 8 个版本 ID 到 32 随机字节 base64url 的映射。真实值放在受限配置或密钥管理器，不写源码、命令参数或日志。
- `CREDENTIAL_ACTIVE_KEY`：活动版本 ID，1–32 个字母/数字/下划线/连字符。
- `CREDENTIAL_MASTER_KEY`：保留旧 v1 读取；也可把旧值放入 keyring 的 `legacy`。两处同时设置必须一致。

不配置活动版本时沿用旧写入方式；配置后新凭证使用活动版本。新旧版本可以兼容读取，缺少必要密钥将安全失败。主密钥版本是部署配置，非企业 API Key；原 HTTP Key 更新/删除及在途交付指纹检查保留。

### 维护窗口轮换

这是运行数据库凭证的运维权限，CLI 不暴露为管理员 HTTP API。仅用非 SUPERUSER / 非 BYPASSRLS 的运行连接，必须显式指定企业；不绕过 FORCE RLS。单企业最多 1000 条凭证，禁止默默部分提交。

1. 停止所有入口与旧配置 worker，排空/核实模型调用；CLI 拒绝仍有 running 调用的企业。确认已有可恢复数据库备份并分离保管所有旧密钥，不自动创建或改动备份。
2. 在安全配置中保留全部旧版本并添加新版本，配置活动 ID。配置部署不是数据库事务，维护期间不得让旧配置进程写入。
3. 对每个需轮换企业先预览、检查，再人工复制非敏感摘要确认：

```bash
uv run python -m support_agent.cli rotate-keys preview --tenant TENANT_UUID --target KEY_ID
uv run python -m support_agent.cli rotate-keys check --tenant TENANT_UUID --target KEY_ID
uv run python -m support_agent.cli rotate-keys execute --tenant TENANT_UUID --target KEY_ID --confirm PLAN_SHA256
```

程序按固定顺序锁凭证，解密全部目标，逐条随机重加密并反解核对，数据与成功审计同事务提交；失败未提交则整笔回滚。共享/排他 advisory lock 与 HTTP 凭证写入协调，预览后集合变化则拒绝。输出仅版本、数量和摘要，不输出明文/密文/密钥。

4. 提交附近中断时保持停机，先 `check`，确认版本计数和可解密性；不假定提交失败。反向恢复需要仍保留新旧密钥：重新以旧 ID（v1 用 `legacy`）预览，再使用 `recover --target OLD_KEY_ID --confirm NEW_PLAN_SHA256`。恢复也是单企业原子重加密，不恢复整个数据库、不覆盖备份。失败审计记为提交结果可能未知，不能当已回滚证明。
5. 全部企业检查成功后用同一 keyring/活动 ID 重启。旧密钥在旧数据库备份过期且恢复演练完成前不能销毁；不得直接删掉旧版本。没有实现热配置分发、无停机 KMS 或操作系统进程全局封锁。

## 数据保留与隐私

默认所有期限为空，不自动调度。新增 `RETENTION_CONVERSATIONS_DAYS`、`RETENTION_VISITORS_DAYS`、`RETENTION_CALLS_DAYS`、`RETENTION_AUDIT_DAYS`，也可在 CLI 显式指定。业务期限至少 2 天，审计至少 30 天，均按 UTC 日界线计算，避免清理当日配额；审计期限必须另行根据业务/法定要求选择。

```bash
uv run python -m support_agent.cli retention preview --tenant TENANT_UUID --conversations-days 90 --visitors-days 30 --calls-days 90 --batch-size 20
# 核对本批影响数量和 executable；人工确认摘要后执行，参数须相同：
uv run python -m support_agent.cli retention execute --tenant TENANT_UUID --conversations-days 90 --visitors-days 30 --calls-days 90 --batch-size 20 --confirm PLAN_SHA256
```

- 每类最多选择 1–100 个根记录，预览包含本批消息/执行/调用/访客/分块关联数量；总影响超过 10000 行拒绝执行，不能用“大批处理”绕过事务边界。
- 仅选择已关闭且最后活动已过期的内部会话；访客过期并闲置超过期限可删除完整会话。任何 running 调用（含待核实中断）均保护；消息或调用仍在保留/配额窗口内也保护。
- 会话与消息、工具记录、模型调用、访客记录按外键顺序同事务删除；旧会话 ID 以后 404，不允许重放触发新调用。独立连接测试仅压缩步骤细节，保留最小身份/幂等/结果/用量摘要；不把删计费凭据当隐私方案。
- 已 ready 的知识文档不按年龄自动删除。`--documents` 仅续做已有 deleting 文档：先前已不可检索，文件不存在可重试；本地文件和 DB 无跨介质事务，失败保留 tombstone，重新预览可恢复清理。引用历史和备份有自己的生命周期。
- 每批成功审计与数据库修改同事务，重复提交同摘要返回 already_applied；集合变化要求重新预览。失败时检查状态与审计后重试，不运行无限循环；默认不安装 cron。

这是业务保留与删除工具，**不是完整隐私擦除**。全局用户身份、审计、保留摘要、备份、远端模型留存及导出副本需分别治理；旧备份恢复后还需重放撤销/删除。尚无自动合规判断或全链路擦除证明。

## CI

`.github/workflows/ci.yml` 在 main push、PR 或手动触发。固定 Actions 提交，contents:read，不保留 Git 凭证；全新 PostgreSQL17 service、非超级/非 BYPASSRLS 应用角色，执行 0001–0008 增量链再复用 scripts/check.py。没有个人路径、真实 Key 或外部模型；服务和模拟密码仅用于短暂 CI。

uv 锁定依赖，Python3.13、Ruff/格式、两库 schema diff、Python 回归只执行一次，子进程 60 秒上限。之后 wheel 打包、5 项 JS（10 秒上限）、JS 语法和 15 个 Web 资源/许可证检查。工作流 3 分钟超时，不上传环境、日志或数据制品。Node 使用 runner 自带版本；无前端构建框架。实际 Actions 结果记录在 P7_ACCEPTANCE，不以 YAML 存在代替运行通过。
