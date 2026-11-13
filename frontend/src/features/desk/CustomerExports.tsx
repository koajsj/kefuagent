import { useState } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { DataTable, ErrorNotice, JsonView, Loading, Pager, Panel, Status } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { ExportPreview, ExportTask } from "../../types/product";

export function CustomerExports({ customerId }: { customerId: string }) {
  const { api, tenant, role } = useApp();
  if (role !== "admin") return null;
  if (api.mode === "demo") return <Panel title="客户数据导出"><p>NOT_AVAILABLE：离线 Demo 不生成含客户资料和附件的真实导出文件。</p></Panel>;
  return <Exports key={`${tenant}.${customerId}`} customerId={customerId} />;
}
function Exports({ customerId }: { customerId: string }) {
  const { api, tenant } = useApp();
  const [offset, setOffset] = useState(0), [preview, setPreview] = useState<ExportPreview | null>(null), [detail, setDetail] = useState<ExportTask | null>(null), [reviewed, setReviewed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>();
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const tasks = useResource<ExportTask[]>(signal => api.request(`/customers/${customerId}/exports?limit=10&offset=${offset}`, { signal }), [api, tenant, customerId, offset]);
  async function inspect() {
    setBusy(true); setError(undefined); setPreview(null); setReviewed(false);
    try { setPreview(await api.request(`/customers/${customerId}/export-preview`)); } catch(e) { setError(e); } finally { setBusy(false); }
  }
  async function create() {
    if (!preview || !reviewed) return;
    setBusy(true); setError(undefined);
    try { const task = await api.request<ExportTask>(`/customers/${customerId}/exports`, { method: "POST", body: { request_key: requestKey, scope_digest: preview.scope_digest, policy: preview.policy, reviewed_subject_content: true } }); setDetail(task); setRequestKey(crypto.randomUUID()); setPreview(null); setReviewed(false); tasks.reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function download(task: ExportTask) {
    setBusy(true); setError(undefined);
    try { const file = await api.request<Blob>(`/customer-exports/${task.id}/content`, { responseType: "blob" }); const url = URL.createObjectURL(file); const link = document.createElement("a"); link.href = url; link.download = `customer-export-${task.id}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 60000); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function open(task: ExportTask) {
    setBusy(true); setError(undefined);
    try { setDetail(await api.request(`/customer-exports/${task.id}`)); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <Panel title="客户数据导出 · JSONL 与附件 ZIP"><p>仅申请管理员本人下载，24 小时有效。范围包含客户资料、人工关联身份、会话消息、允许的附件、工单记录、记忆与评价；内部备注、员工身份和凭证排除。需要产品任务 Worker。</p><p>导出是经授权的客户数据副本，不执行客户删除；当前 S3 导出文件的物理清理为 BLOCKED；到期仍会禁止下载。</p>
    <div className="actions"><Button isDisabled={busy} onPress={() => void inspect()}>预览数据范围</Button><Button variant="secondary" onPress={tasks.reload}>刷新任务</Button></div><ErrorNotice error={error || tasks.error} retry={tasks.reload} />
    {preview && <div><JsonView value={preview} /><label><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />我已审核关联会话与文件属于此客户，并确认第三方内容可依法导出；已知凭证模式会阻断导出，系统不提供完整 PII 识别保证。</label><Button isDisabled={!reviewed || busy} onPress={() => void create()}>确认此范围并申请导出</Button></div>}
    {tasks.loading ? <Loading /> : !tasks.error && <DataTable columns={["申请时间", "状态", "有效期", "操作"]} rows={(tasks.data || []).map(task => [new Date(task.created_at).toLocaleString(), <><Status value={new Date(task.expires_at).getTime() <= Date.now() && task.status === "READY" ? "EXPIRED" : task.status} />{task.error_category && <small role="alert">{task.error_category}</small>}</>, new Date(task.expires_at).toLocaleString(), <div className="actions"><Button variant="secondary" isDisabled={busy} onPress={() => void open(task)}>详情</Button><Button isDisabled={busy || task.status !== "READY" || new Date(task.expires_at).getTime() <= Date.now()} onPress={() => void download(task)}>授权下载 ZIP</Button></div>])} />}
    <Pager offset={offset} count={tasks.data?.length || 0} size={10} onChange={setOffset} />
    {detail && <details open><summary>任务 {detail.id} · {detail.status}</summary><JsonView value={detail} /><small>失败不会发布不完整文件；范围变更后需重新预览并申请。过期即禁止下载，物理清理状态另行显示。</small></details>}
  </Panel>;
}
