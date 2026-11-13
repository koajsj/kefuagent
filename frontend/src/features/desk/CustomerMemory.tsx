import { useState, type FormEvent } from "react";
import { Button, Input, Label, TextArea, TextField } from "@heroui/react";
import { useApp } from "../../app/context";
import { DataTable, ErrorNotice, Loading, Pager, Panel } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";

export function CustomerMemory({ customer, changed }: { customer: Row; changed: (customer: Row) => void }) {
  const { api, tenant, role } = useApp();
  const [offset, setOffset] = useState(0), [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const rows = useResource<Row[]>((signal) => api.request(`/customers/${customer.id}/memories?limit=10&offset=${offset}`, { signal }), [api, tenant, customer.id, customer.version, offset]);
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(undefined);
    try { await fn(); rows.reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget, data = new FormData(form);
    void act(async () => {
      await api.request(`/customers/${customer.id}/memories`, { method: "POST", body: { expected_customer_version: customer.version, source_message_id: data.get("source"), content: data.get("content"), lifetime_days: Number(data.get("days")) } });
      form.reset();
    });
  }
  return <Panel title="客户记忆 · 人工确认的原话">
    <p>仅保存已关联会话中客户 user 消息的逐字引用，不将模型推测写成事实。默认关闭；不会自动发送给模型。</p>
    <p>撤回或关闭会清除此处副本，留下来源标识和不可恢复墓碑；原会话、备份与外部副本不属于此操作。过期引用立即停止展示，Worker 可清除过期正文。</p>
    <ErrorNotice error={error || rows.error} retry={rows.reload} />
    {role === "admin" && <Button variant="secondary" isDisabled={busy} onPress={() => {
      if (!customer.memory_enabled || confirm("关闭记忆会清除所有已保存引用，重新启用不会恢复它们。继续？")) void act(async () => changed(await api.request<Row>(`/customers/${customer.id}/memory-consent`, { method: "PUT", body: { expected_version: customer.version, enabled: !customer.memory_enabled } })));
    }}>{customer.memory_enabled ? "关闭并清除记忆" : "明确启用客户记忆"}</Button>}
    {rows.loading ? <Loading /> : !rows.error && <DataTable columns={["客户原话", "来源消息", "有效期至", "操作"]} rows={(rows.data || []).map((row) => [row.content, row.source_message_id, new Date(row.expires_at).toLocaleString(), role === "admin" ? <Button variant="danger" isDisabled={busy} onPress={() => { if (confirm("撤回这条引用？此副本不可恢复，源消息保留。")) void act(async () => { await api.request(`/customers/${customer.id}/memories/${row.id}/forget`, { method: "POST", body: { expected_version: row.version } }); }); }}>撤回副本</Button> : "仅管理员可撤回"])} />}
    <Pager offset={offset} count={rows.data?.length || 0} size={10} onChange={setOffset} />
    {role === "admin" && customer.memory_enabled && customer.status === "active" && <form onSubmit={add}>
      <TextField name="source" isRequired isDisabled={busy}><Label>已关联会话中的来源消息 ID</Label><Input /></TextField>
      <TextField name="content" isRequired isDisabled={busy}><Label>客户原话（必须是源消息的精确片段）</Label><TextArea maxLength={500} /></TextField>
      <TextField name="days" isRequired isDisabled={busy} defaultValue="30"><Label>有效天数（1–365）</Label><Input type="number" min={1} max={365} /></TextField>
      <Button type="submit" isDisabled={busy}>人工确认并保存</Button>
    </form>}
  </Panel>;
}
