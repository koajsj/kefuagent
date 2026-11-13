import { useState, type FormEvent } from "react";
import { Button, Input, Label, TextField } from "@heroui/react";
import { AgentPicker } from "../../components/AgentPicker";
import { ErrorNotice, Loading, PageHeader, Panel } from "../../components/ui";
import { useApp } from "../../app/context";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";

const routes = { qa: "普通回答", extraction: "结构提取", reasoning: "复杂问题", fallback: "备用模型" };
export function ModelRouting() {
  const { api, tenant, notify } = useApp();
  const [id, setId] = useState(""), [error, setError] = useState<unknown>(), [busy, setBusy] = useState(false);
  const selected = useResource<Row | null>((signal) => id ? api.request(`/agent-configs/${id}`, { signal }) : Promise.resolve(null), [api, tenant, id]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected.data) return;
    const data = selected.data, form = new FormData(event.currentTarget);
    const routing = Object.fromEntries(Object.keys(routes).map((key) => [key, form.get(key) ? { model: form.get(key), supports_tools: form.has(key + "_tools"), token_parameter: data.runtime.routing?.[key]?.token_parameter ?? data.runtime.token_parameter, send_temperature: data.runtime.routing?.[key]?.send_temperature ?? data.runtime.send_temperature } : null]));
    setBusy(true); setError(undefined);
    try {
      await api.request(`/agent-configs/${data.id}`, { method: "PUT", body: { name: data.name, enabled: data.enabled, provider: data.provider, model: data.model, behavior: data.behavior, base_url: data.base_url, credential_ref: data.credential_ref, expected_version: data.version, runtime: { ...data.runtime, routing } } });
      selected.reload(); notify("模型路由已保存，配置版本已更新；需要时请重新发布公开入口。");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <><PageHeader title="模型路由" description="按任务选择模型并保留原网关的兼容参数、主备规则和版本检查。空值使用默认模型。" /><AgentPicker value={id} onChange={setId} disabled={busy} /><ErrorNotice error={selected.error} retry={selected.reload} /><ErrorNotice error={error} />{selected.loading ? <Loading /> : selected.data && <Panel title={`${selected.data.name} · v${selected.data.version}`}><form key={`${selected.data.id}-${selected.data.version}`} onSubmit={save}>{Object.entries(routes).map(([key, name]) => <div className="route-field" key={key}><TextField name={key} defaultValue={selected.data?.runtime.routing?.[key]?.model || ""} isDisabled={busy}><Label>{name}</Label><Input maxLength={120} /></TextField><label><input type="checkbox" name={key + "_tools"} defaultChecked={selected.data?.runtime.routing?.[key]?.supports_tools ?? true} disabled={busy} /> 支持工具协议</label></div>)}<Button type="submit" isPending={busy} isDisabled={busy}>保存路由</Button></form></Panel>}</>;
}
