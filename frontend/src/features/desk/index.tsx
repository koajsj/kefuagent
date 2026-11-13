import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { Button, Input, Label, TextArea, TextField } from "@heroui/react";
import { useApp } from "../../app/context";
import { DataTable, Empty, ErrorNotice, Field, Loading, PageHeader, Pager, Panel, Status } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";
import { CustomerMemory } from "./CustomerMemory";
import { CustomerExports } from "./CustomerExports";
import { CustomerActivity } from "./CustomerActivity";

const states: Record<string, string> = { open: "待处理", in_progress: "处理中", resolved: "已解决", closed: "已关闭" };
const priorities: Record<string, string> = { low: "低", normal: "普通", high: "高", urgent: "紧急" };
const stamp = (value: string | null) => value ? new Date(value).toLocaleString() : "未设置";
const localMinute = (value: string | null) => value ? new Date(new Date(value).getTime() - new Date(value).getTimezoneOffset() * 60000).toISOString().slice(0,16) : "";

function Notifications({ open }: { open: (ticket: Row) => void }) {
  const { api, tenant } = useApp();
  const [offset, setOffset] = useState(0), [unread, setUnread] = useState(true);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>();
  const rows = useResource<Row[]>((signal) => api.request(`/staff-notifications?limit=10&offset=${offset}&unread=${unread}`, { signal }), [api, tenant, offset, unread]);
  async function view(row: Row) {
    setBusy(true); setError(undefined);
    try {
      const ticket = await api.request<Row>(`/tickets/${row.ticket_id}`);
      await api.request(`/staff-notifications/${row.id}/read`, { method: "POST" });
      open(ticket); rows.reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <Panel title="我的工单提醒">
    <div className="actions"><label><input type="checkbox" checked={unread} onChange={(e) => { setUnread(e.target.checked); setOffset(0); }} />仅未读</label><Button variant="secondary" onPress={rows.reload}>刷新提醒</Button></div>
    <ErrorNotice error={rows.error || error} retry={rows.reload} />
    {rows.loading ? <Loading /> : !rows.error && <DataTable columns={["提醒", "时间", "操作"]} rows={(rows.data || []).map((row) => [row.kind === "ticket_overdue" ? "工单已超过目标期限" : "Agent 工单通知", stamp(row.created_at), <Button variant="secondary" isDisabled={busy} onPress={() => void view(row)}>查看并标记已读</Button>])} />}
    <Pager offset={offset} count={rows.data?.length || 0} size={10} onChange={setOffset} />
    <small>超时提醒由可选 Worker 生成；这里显示已持久化的站内提醒。</small>
  </Panel>;
}

export function ServiceDesk({ page }: { page: "customers" | "tickets" }) {
  const { api, tenant, role, user, notify } = useApp();
  const isCustomer = page === "customers";
  const location = useLocation();
  const [offset, setOffset] = useState(0), [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Row | null>(null), [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [opening, setOpening] = useState(false);
  useEffect(() => {
    const id = isCustomer ? location.state?.customerId : location.state?.ticketId;
    if (!id) return;
    const controller = new AbortController();
    setOpening(true); setError(undefined);
    api.request<Row>(`/${page}/${encodeURIComponent(id)}`, { signal: controller.signal }).then((row) => {
      if (!controller.signal.aborted) { setSelected(row); setCreating(false); }
    }, (e) => { if (!controller.signal.aborted) setError(e); }).finally(() => { if (!controller.signal.aborted) setOpening(false); });
    return () => controller.abort();
  }, [api, tenant, page, isCustomer, location.key]);
  const rows = useResource<Row[]>((signal) => api.request(`/${page}?limit=25&offset=${offset}${filter ? `&${isCustomer ? "q" : "status"}=${encodeURIComponent(filter)}` : ""}`, { signal }), [api, tenant, page, offset, filter]);
  const events = useResource<Row[]>((signal) => selected ? api.request(isCustomer ? `/customers/${selected.id}/conversations?limit=100` : `/tickets/${selected.id}/events?limit=100`, { signal }) : Promise.resolve([]), [api, tenant, selected?.id, selected?.version]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values = Object.fromEntries(form.entries());
    setBusy(true); setError(undefined);
    try {
      let body: Record<string, unknown>;
      if (isCustomer) {
        body = { name: values.name, email: values.email || null, phone: values.phone || null,
          external_ref: values.external_ref || null, notes: values.notes,
          tags: String(values.tags || "").split(",").map((v) => v.trim()).filter(Boolean),
          ...(selected && !creating ? { expected_version: selected.version, status: values.status } : { idempotency_key: key }) };
      } else if (selected && !creating) {
        body = { expected_version: selected.version, status: values.status, priority: values.priority,
          note: values.note, ...(role === "admin" ? { assignee_id: values.assignee_id || null } : {}),
          ...(values.due_at !== localMinute(selected.due_at) ? { due_at: values.due_at ? new Date(String(values.due_at)).toISOString() : null } : {}) };
      } else {
        body = { idempotency_key: key, title: values.title, description: values.description,
          priority: values.priority, conversation_id: values.conversation_id || null, customer_id: values.customer_id || null,
          assignee_id: values.assignee_id || user.id,
          due_at: values.due_at ? new Date(String(values.due_at)).toISOString() : null };
      }
      const result = await api.request<Row>(`/${page}${selected && !creating ? `/${selected.id}` : ""}`, { method: selected && !creating ? "PATCH" : "POST", body });
      setSelected(result); setCreating(false); setKey(crypto.randomUUID()); rows.reload();
      notify("已保存。原请求标识仅在成功后更新。请勿用新标识重试未知结果。");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const editable = creating || (selected && (role === "admin" || (!isCustomer && selected.assignee_id === user.id)));
  return <>
    <PageHeader title={isCustomer ? "客户" : "工单"} description={isCustomer ? "客户由客服明确登记并关联会话；不根据 IP 或访客令牌合并身份。" : "跟进、分配和解决客户问题，保留工单状态与操作历史。"}
      actions={<Button isDisabled={busy || opening} onPress={() => { setSelected(null); setCreating(true); setError(undefined); }}>创建{isCustomer ? "客户" : "工单"}</Button>} />
    <ErrorNotice error={error} />
    {opening && <Loading />}
    {!isCustomer && <Notifications open={(ticket) => { setSelected(ticket); setCreating(false); setError(undefined); }} />}
    <div className="desk-filters">
      <Field label={isCustomer ? "按客户名称查询" : "处理状态"}>
        {isCustomer ? <input value={filter} maxLength={120} onChange={(e) => { setFilter(e.target.value); setOffset(0); }} /> : <select value={filter} onChange={(e) => { setFilter(e.target.value); setOffset(0); }}><option value="">全部</option>{Object.entries(states).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>}
      </Field>
      <Button variant="secondary" onPress={rows.reload}>刷新列表</Button>
    </div>
    <ErrorNotice error={rows.error} retry={rows.reload} />
    {rows.loading ? <Loading /> : !rows.error && <DataTable columns={isCustomer ? ["客户", "联系信息", "标签", "状态", "操作"] : ["工单", "状态", "优先级", "期限", "操作"]}
      rows={(rows.data || []).map((row) => [isCustomer ? row.name : row.title,
        isCustomer ? row.email || row.phone || "未填写" : states[row.status],
        isCustomer ? row.tags.join(" · ") || "无标签" : priorities[row.priority],
        isCustomer ? <Status value={row.status} /> : <span className={row.due_at && new Date(row.due_at).getTime() < Date.now() && ["open", "in_progress"].includes(row.status) ? "warning" : ""}>{stamp(row.due_at)}</span>,
        <Button variant="secondary" isDisabled={busy || opening} onPress={() => { setSelected(row); setCreating(false); setError(undefined); }}>查看</Button>])} />}
    <Pager offset={offset} count={rows.data?.length || 0} size={25} onChange={setOffset} />
    {(creating || selected) && <div className="desk-detail-grid"><Panel title={creating ? `创建${isCustomer ? "客户" : "工单"}` : `${isCustomer ? selected?.name : selected?.title} · v${selected?.version}`}>
      <form key={`${page}-${creating ? key : `${selected?.id}-${selected?.version}`}`} onSubmit={save}>
        {isCustomer ? <>
          <TextField name="name" isRequired isDisabled={!editable || busy} defaultValue={selected?.name || ""}><Label>客户名称</Label><Input maxLength={120} /></TextField>
          <TextField name="external_ref" isDisabled={!editable || busy} defaultValue={selected?.external_ref || ""}><Label>外部标识（人工核实）</Label><Input maxLength={160} /></TextField>
          <TextField name="email" isDisabled={!editable || busy} defaultValue={selected?.email || ""}><Label>邮箱</Label><Input type="email" maxLength={254} /></TextField>
          <TextField name="phone" isDisabled={!editable || busy} defaultValue={selected?.phone || ""}><Label>联系电话</Label><Input maxLength={40} /></TextField>
          <TextField name="tags" isDisabled={!editable || busy} defaultValue={selected?.tags?.join(", ") || ""}><Label>标签（英文逗号分隔）</Label><Input /></TextField>
          <TextField name="notes" isDisabled={!editable || busy} defaultValue={selected?.notes || ""}><Label>内部资料</Label><TextArea maxLength={2000} /></TextField>
          {!creating && <Field label="资料状态"><select name="status" defaultValue={selected?.status} disabled={!editable || busy}><option value="active">有效</option><option value="archived">已归档</option></select></Field>}
        </> : <>
          {creating && <><TextField name="title" isRequired><Label>工单标题</Label><Input maxLength={160} /></TextField>
            <TextField name="description"><Label>问题描述</Label><TextArea maxLength={4000} /></TextField>
            <TextField name="conversation_id"><Label>关联会话 ID（可选）</Label><Input /></TextField>
            <TextField name="customer_id"><Label>客户 ID（可选）</Label><Input /></TextField></>}
          {!creating && <><p className="desk-description">{selected?.description || "没有问题描述。"}</p><p>客户：{selected?.customer_id || "未关联"} · 会话：{selected?.conversation_id || "未关联"}</p>
            <Field label="处理状态"><select name="status" defaultValue={selected?.status} disabled={!editable || busy}>{Object.entries(states).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></Field></>}
          <Field label="优先级"><select name="priority" defaultValue={selected?.priority || "normal"} disabled={!editable || busy}>{Object.entries(priorities).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></Field>
          {(role === "admin" || creating) && <TextField name="assignee_id" isDisabled={!editable || busy} defaultValue={selected?.assignee_id || ""}><Label>负责人用户 ID（创建时留空分配本人）</Label><Input /></TextField>}
          <TextField name="due_at" isDisabled={!editable || busy} defaultValue={localMinute(selected?.due_at)}><Label>目标期限（本机时区，非工作日历 SLA）</Label><Input type="datetime-local" /></TextField>
          {!creating && <TextField name="note" isDisabled={!editable || busy}><Label>处理意见</Label><TextArea maxLength={1000} /></TextField>}
        </>}
        <div className="actions"><Button type="submit" isDisabled={!editable || busy} isPending={busy}>保存</Button><Button variant="secondary" isDisabled={busy} onPress={() => { setCreating(false); setSelected(null); }}>关闭</Button></div>
      </form>
    </Panel><Panel title={isCustomer ? "人工关联的会话" : "操作历史"}>
      <ErrorNotice error={events.error} retry={events.reload} />
      {events.loading ? <Loading /> : events.data?.length ? events.data.map((event) => isCustomer ? <p key={event.conversation_id}><Link to="/chat" state={{ conversationId: event.conversation_id }}>{event.conversation_id}</Link> · {stamp(event.linked_at)}</p> : <article className="desk-event" key={event.id}><strong>{event.action}</strong><small>{stamp(event.created_at)} · {event.actor_id || "系统"}</small><p>{event.details.note || ""}</p>{event.details.changes && Object.entries(event.details.changes).map(([field, value]) => <p key={field}>{field}：{String((value as Row).before ?? "空")} → {String((value as Row).after ?? "空")}</p>)}</article>) : !events.error && <Empty>{creating ? "保存后显示关联记录。" : "没有关联记录。"}</Empty>}
      {events.data?.length === 100 && <p>仅展示最近 100 条；完整记录保留在服务端分页接口。</p>}
    </Panel></div>}
    {isCustomer && selected && !creating && <CustomerMemory key={selected.id} customer={selected} changed={(row) => { setSelected(row); rows.reload(); }} />}
    {isCustomer && selected && !creating && <CustomerExports key={`export-${selected.id}`} customerId={selected.id} />}
    {isCustomer && selected && !creating && <CustomerActivity key={`activity-${selected.id}`} customer={selected} />}
  </>;
}
