import { FileAttachments } from "../../components/FileAttachments";
import { useState, type FormEvent } from "react";
import { Button, Input, Label, TextField } from "@heroui/react";
import { Link } from "react-router-dom";
import { useApp } from "../../app/context";
import { useResource } from "../../hooks/useResource";
import { ErrorNotice } from "../../components/ui";
import type { Row } from "../../types";

export function CustomerContext({ conversation, refresh, disabled = false }: { conversation: Row; refresh: () => Promise<void>; disabled?: boolean }) {
  const { api, tenant, role, user } = useApp();
  const [error, setError] = useState<unknown>(), [busy, setBusy] = useState(false);
  const [handoff, setHandoff] = useState<Row | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const customer = useResource<Row | null>((signal) => api.request(`/conversations/${conversation.id}/customer`, { signal }), [api, tenant, conversation.id, conversation.version]);
  const tickets = useResource<Row[]>((signal) => api.request(`/tickets?conversation_id=${conversation.id}&limit=10`, { signal }), [api, tenant, conversation.id, key]);
  const editable = !disabled && (role === "admin" || conversation.assignee_id === user.id);
  async function link(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true); setError(undefined);
    try {
      await api.request(`/conversations/${conversation.id}/customer`, { method: "PUT", body: { customer_id: form.get("customer_id"), expected_version: conversation.version } });
      await refresh(); customer.reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true); setError(undefined);
    try {
      await api.request("/tickets", { method: "POST", body: { idempotency_key: key, title: form.get("title"), description: form.get("description") || "", conversation_id: conversation.id, assignee_id: user.id } });
      setKey(crypto.randomUUID()); tickets.reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <section aria-label="客户与工单" className="customer-context"><h3>客户与工单</h3><ErrorNotice error={error} /><ErrorNotice error={customer.error} retry={customer.reload} />
    {customer.loading ? <p role="status">正在读取客户…</p> : customer.data ? <p>{customer.data.name} · <Link to="/customers" state={{ customerId: customer.data.id }}>客户档案</Link> · 人工确认关联，非自动身份验证</p> : !customer.error && <p>尚未关联客户。匿名访客不会自动合并为同一身份。</p>}
    {!customer.loading && !customer.error && !customer.data && editable && <form onSubmit={link}><TextField name="customer_id" isRequired isDisabled={busy}><Label>已核实的客户 ID</Label><Input /></TextField><Button variant="secondary" type="submit" isDisabled={busy}>确认关联</Button></form>}
    <ErrorNotice error={tickets.error} retry={tickets.reload} />
    {tickets.loading ? <p>正在读取工单…</p> : !tickets.error && <>{tickets.data?.map((row) => <p key={row.id}><Link to="/tickets" state={{ ticketId: row.id }}>{row.title}</Link> · {row.status}</p>)}<Link to="/tickets">管理工单</Link></>}
    {editable && <details><summary>为当前会话创建工单</summary><form key={key} onSubmit={create}><TextField name="title" isRequired isDisabled={busy}><Label>工单标题</Label><Input maxLength={160} /></TextField><TextField name="description" isDisabled={busy}><Label>问题说明</Label><Input maxLength={4000} /></TextField><Button type="submit" isDisabled={busy}>创建并分配本人</Button></form></details>}
    <FileAttachments api={api} prefix={`/conversations/${conversation.id}`} disabled={disabled || conversation.status !== "open" || !editable} />
    <Button variant="secondary" isDisabled={busy} onPress={async () => { setBusy(true); setError(undefined); setHandoff(null); try { setHandoff(await api.request(`/conversations/${conversation.id}/handoff`)); } catch(e) { setError(e); } finally { setBusy(false); } }}>查看交接上下文</Button>
    {handoff && <div className="handoff-packet"><p>转交原因：{handoff.reason || "未记录"}；来源：{handoff.knowledge_sources_state}。未记录任务：未知。</p><p>对话摘要：{handoff.summary ? "来源摘录如下" : "未采集"}</p>{handoff.summary?.statements?.map((item: Row, index: number) => <p key={index}>{item.quote}</p>)}{handoff.knowledge_sources.map((source: Row) => <p key={source.chunk_id}>{source.document_name} · {source.chunk_id}</p>)}{handoff.tool_executions.map((tool: Row) => <p key={tool.execution_id}>{tool.tool_name} · {tool.status} · {tool.error_category || ""}</p>)}{handoff.pending_tickets.map((ticket: Row) => <p key={ticket.id}>未完成工单：{ticket.title}</p>)}{handoff.pending_tickets_truncated && <p>待办超过 100 条，请在工单页继续查询。</p>}</div>}
  </section>;
}
