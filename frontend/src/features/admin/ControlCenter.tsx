import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { DataTable, Empty, ErrorNotice, Field, JsonView, Loading, PageHeader, Pager, Panel } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import { TracePanel } from "../chat/TracePanel";
import { FeedbackInbox } from "./FeedbackInbox";
import type { Row } from "../../types";

export function ControlCenter({ page }: { page: string }) {
  const { api, tenant } = useApp();
  const [offset, setOffset] = useState(0), [selected, setSelected] = useState<Row | null>(null);
  const [plan, setPlan] = useState<Row | null>(null), [error, setError] = useState<unknown>(), [busy, setBusy] = useState(false);
  const path = page === "autonomy" ? "/autonomy-policy" : page === "executions" ? `/model-calls?limit=25&offset=${offset}` : page === "quality" ? "/workspace/analytics" : "/administration";
  const resource = useResource<any>((signal) => api.request(path, { signal }), [api, tenant, page, offset]);
  const titles: Record<string, string> = { autonomy: "自治策略", executions: "Agent 执行与 Trace", quality: "质量与运营", retention: "数据保留", recovery: "备份与恢复", integrations: "接入能力", settings: "系统设置" };
  async function preview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(undefined); setPlan(null);
    const form = new FormData(event.currentTarget);
    try {
      const values = Object.fromEntries(["conversations_days", "visitors_days", "calls_days", "audit_days"].map((key) => [key, form.get(key) ? Number(form.get(key)) : null]));
      setPlan(await api.request("/administration/retention/preview", { method: "POST", body: { ...values, documents: form.has("documents"), batch_size: 20 } }));
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <>
    <PageHeader title={titles[page]} description="信息来自当前企业 API；未知、未配置和运行时未验证均按实际状态展示。" actions={<Button variant="secondary" onPress={resource.reload}>刷新</Button>} />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    {resource.loading ? <Loading /> : !resource.error && resource.data && <>
      {page === "executions" && <><DataTable columns={["模型", "状态", "调用目的", "用量", "操作"]} rows={resource.data.map((row: Row) => [row.model, row.status, row.kind, row.usage_complete ? `${row.input_tokens ?? "未知"} / ${row.output_tokens ?? "未知"}` : "未知 / 不完整", <Button variant="secondary" isDisabled={!row.conversation_id} onPress={() => setSelected(row)}>执行详情</Button>])} /><Pager offset={offset} size={25} count={resource.data.length} onChange={setOffset} />{selected && <Panel title={`调用 ${selected.id}`}><TracePanel key={selected.id} conversationId={selected.conversation_id} callId={selected.id} /></Panel>}</>}
      {page === "autonomy" && <><Panel title={`策略 ${resource.data.version}`}><DataTable columns={["风险", "行为"]} rows={resource.data.levels.map((level: Row) => [`R${level.risk}`, level.name])} /><p>默认 R{resource.data.default_max_risk}。R2 需在 Agent 配置中显式选择，并授权部署工具及业务资源；模型不能提升权限。R3 审批执行：{resource.data.r3_execution}。</p><p>每回合最多 {resource.data.limits.model_steps} 次模型步骤、{resource.data.limits.tool_calls} 次工具、{resource.data.limits.seconds} 秒。金额预留由统一模型网关执行，缺价或成本上界未知会拒绝付费调用。</p><a href="#/agents">配置 Agent 自治上限</a> · <a href="#/approvals">R3 审批中心</a> · <a href="#/budget">金额预算</a></Panel></>}
      {page === "quality" && <><Panel title="回答与检索指标"><p>以下是来源校验和执行统计，不能代替答案语义正确率。缺少样本时保持未知。</p><JsonView value={resource.data.ai} /><p>已知输入 / 输出 Token：{resource.data.usage?.input_tokens ?? "未知"} / {resource.data.usage?.output_tokens ?? "未知"}；用量未知调用：{resource.data.usage?.unknown_usage_calls ?? "未知"}。费用仍为估算或未知。</p></Panel><FeedbackInbox /></>}
      {!["autonomy", "executions", "quality"].includes(page) && <>
        <Panel title="本实例"><p>企业私有化部署 · 数据库版本要求 {resource.data.required_revision} · 存储 {resource.data.storage_backend}</p><p>外部模型：{resource.data.external_models_enabled ? "已启用" : "关闭"}；自动迁移：关闭。配置由部署方管理，页面不会修改环境变量或执行 Shell。</p></Panel>
        {page === "retention" && <Panel title="影响预览"><p>默认策略：未设置表示保留。会话、客户与知识物理擦除存在未确认依赖，保持阻断。可执行的独立清理仍仅由操作员 CLI 处理。</p><form onSubmit={preview}>{["conversations_days", "visitors_days", "calls_days", "audit_days"].map((name, index) => <Field key={name} label={["会话保留天数", "访客保留天数", "独立调用保留天数", "审计保留天数"][index]}><input type="number" name={name} min={name === "audit_days" ? 30 : 2} max={36500} defaultValue={resource.data.retention[name] ?? ""} /></Field>)}<label><input type="checkbox" name="documents" /> 包含已标记待删除文档的影响预览</label><Button type="submit" isPending={busy} isDisabled={busy}>生成预览</Button></form><ErrorNotice error={error} />{plan && <><p role="status">{plan.executable ? "CLI 批次可审阅；网页不执行删除。" : `执行已阻断：${plan.blocked_reason}`}</p><JsonView value={plan} /></>}</Panel>}
        {page === "recovery" && <Panel title="一致性备份与恢复"><p>最近已验证备份：未知。当前采用操作员流程，没有后台一键覆盖恢复。</p><ol><li>获得目标环境授权，停止入口和 Worker，排空执行。</li><li>一致保存数据库、私有文件或对象版本，以及匹配的加密密钥；密钥与备份分离保管。</li><li>在隔离环境恢复，先审查迁移和运行角色，再逐步升级；重放撤销和删除记录。</li><li>核实权限、引用、幂等和文件完整性后恢复入口。历史迁移 downgrade 不自动销毁版本记录。</li></ol><p>当前恢复演练：NOT_RUN。不要将健康检查或存在备份文件当成恢复成功。</p></Panel>}
        {["integrations", "settings"].includes(page) && <Panel title="能力与配置边界"><DataTable columns={["能力", "状态", "说明"]} rows={resource.data.capabilities.map((item: Row) => [item.name, item.state, item.detail])} /><a href="#/publications">网站 Widget 与发布授权</a><p>超时提醒使用可选 PostgreSQL Worker，当前 Worker 运行健康未知。无第三方订单或通知凭证时不发送外部请求。</p></Panel>}
      </>}
    </>}
    {!resource.loading && !resource.error && !resource.data && <Empty>当前没有可显示的记录。</Empty>}
  </>;
}
