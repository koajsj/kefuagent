import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { DataTable, Empty, ErrorNotice, Field, JsonView, Loading, PageHeader, Panel, Status } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import { collection } from "../../adapters/collection";
import type { Row } from "../../types";
import type { IndexStatus, RetrievalDiagnostic, RetrievalHit } from "../../types/product";

function Hits({ title, hits }: { title: string; hits: RetrievalHit[] }) {
  return <Panel title={title}>{hits.length ? <DataTable columns={["文档 / 分块", "排序分数", "证据"]} rows={hits.map(hit => [<span>{hit.document_name}<small>代次 {hit.generation} · {hit.chunk_id}</small></span>, hit.score.toFixed(5), <details><summary>{hit.content.slice(0,100)}</summary><p className="source-excerpt">{hit.content}</p><small>{hit.strategy} · {hit.section || "无章节"}</small></details>])} /> : <Empty>该阶段没有可交付结果；请结合阶段状态判断原因。</Empty>}</Panel>;
}

export function KnowledgeIntelligence() {
  const { api, tenant, role } = useApp();
  const [kid, setKid] = useState("");
  const [busy, setBusy] = useState(false);
  const bases = useResource<Row[]>(signal => collection(api.request.bind(api), "/knowledge-bases", 500, signal), [api, tenant]);
  useEffect(() => { if (!kid && bases.data?.length) setKid(bases.data[0].id); }, [bases.data, kid]);
  if (role !== "admin") return <Panel title="检索管理">需要管理员权限。</Panel>;
  if (api.mode === "demo") return <><PageHeader title="检索诊断与向量索引" description="NOT_AVAILABLE：离线 Demo 无 pgvector、Embedding 和付费重排，不伪造索引或效果。" /><a href="#/knowledge">查看 Demo 关键词知识查询</a></>;
  return <><PageHeader title="检索诊断与向量索引" description="查看每条召回路径与融合依据。Embedding 和可选重排均受服务端金额预算约束。" /><ErrorNotice error={bases.error} retry={bases.reload} /><Field label="知识库"><select value={kid} disabled={busy} onChange={e => setKid(e.target.value)}><option value="">选择知识库</option>{bases.data?.map(base => <option key={base.id} value={base.id}>{base.name}</option>)}</select></Field>{kid ? <Workspace key={`${tenant}.${kid}`} kid={kid} onBusyChange={setBusy} /> : <Empty>创建并发布知识文档后，可配置索引和诊断。</Empty>}</>;
}

function Workspace({ kid, onBusyChange }: { kid: string; onBusyChange: (busy: boolean) => void }) {
  const { api, tenant, notify } = useApp();
  const state = useResource<IndexStatus>(signal => api.request(`/knowledge-bases/${kid}/index`, { signal }), [api, tenant, kid]);
  const agents = useResource<Row[]>(signal => collection(api.request.bind(api), "/agent-configs", 500, signal), [api, tenant]);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(), [result, setResult] = useState<RetrievalDiagnostic | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => {
    if (pending.current) {
      pending.current.abort();
      notify("已停止等待；服务端操作结果可能未知，请检查索引状态和用量后再重试。");
    }
  }, []);
  function begin() {
    if (pending.current) return null;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); onBusyChange(true); setError(undefined);
    return controller;
  }
  function finish(controller: AbortController) {
    if (controller.signal.aborted || pending.current !== controller) return;
    pending.current = null;
    setBusy(false); onBusyChange(false);
  }
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget), controller = begin();
    if (!controller) return;
    try {
      await api.request(`/knowledge-bases/${kid}/index`, { method: "PUT", body: { expected_version: state.data?.configuration?.version || 0, agent_config_id: f.get("agent"), model: f.get("model"), enabled: f.has("enabled"), rerank: f.has("rerank") }, signal: controller.signal });
      if (!controller.signal.aborted) { setResult(null); state.reload(); }
    } catch (e) { if (!controller.signal.aborted) setError(e); } finally { finish(controller); }
  }
  async function queue(rebuild: boolean) {
    const controller = begin(); if (!controller) return;
    try {
      await api.request(`/knowledge-bases/${kid}/index`, { method: "POST", body: { expected_version: state.data!.configuration!.version, rebuild }, signal: controller.signal });
      if (!controller.signal.aborted) { setResult(null); state.reload(); }
    } catch (e) { if (!controller.signal.aborted) setError(e); } finally { finish(controller); }
  }
  async function diagnose(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget), controller = begin();
    if (!controller) return;
    setResult(null);
    try {
      const value = await api.request<RetrievalDiagnostic>(`/knowledge-bases/${kid}/diagnostics`, { method: "POST", body: { agent_config_id: f.get("agent"), query: f.get("query"), limit: 6, document_ids: String(f.get("documents") || "").split(/[,\s]+/).filter(Boolean), section: f.get("section") || null, rerank: f.has("rerank") }, signal: controller.signal });
      if (!controller.signal.aborted) setResult(value);
    } catch (e) { if (!controller.signal.aborted) setError(e); } finally { finish(controller); }
  }
  const options = agents.data?.filter(a => a.enabled).map(a => <option key={a.id} value={a.id}>{a.name} · {a.model}</option>);
  return <><ErrorNotice error={state.error || agents.error || error} retry={busy ? undefined : () => { state.reload(); agents.reload(); }} />
    <div className="desk-detail-grid"><Panel title="向量索引"><Button variant="secondary" isDisabled={busy} onPress={state.reload}>刷新索引状态</Button>{state.loading ? <Loading /> : state.data && <><Status value={state.data.configuration?.state || "未配置"} /><p>已索引 {state.data.indexed_chunks} / {state.data.eligible_chunks} · 待处理 {state.data.missing_chunks}</p>{state.data.configuration?.error_category && <p role="alert">失败：{state.data.configuration.error_category}</p>}<form key={state.data.configuration?.version || 0} onSubmit={save}><fieldset disabled={busy}><Field label="索引计费与凭证 Agent（须授权此知识库）"><select name="agent" required defaultValue={state.data.configuration?.agent_config_id || ""}><option value="">选择 Agent</option>{options}</select></Field><Field label="Embedding 模型（同一批准端点，1536 维）"><input name="model" required maxLength={120} defaultValue={state.data.configuration?.model || ""} /></Field><label><input name="enabled" type="checkbox" defaultChecked={state.data.configuration?.enabled} />启用向量召回</label><label><input name="rerank" type="checkbox" defaultChecked={state.data.configuration?.rerank} />启用额外付费的 LLM 重排</label><Button type="submit" isDisabled={busy || !agents.data}>保存配置并排队</Button></fieldset></form><div className="actions"><Button variant="secondary" isDisabled={busy || !state.data.configuration?.enabled} onPress={() => void queue(false)}>增量索引 / 重试</Button><Button variant="secondary" isDisabled={busy || !state.data.configuration?.enabled} onPress={() => void queue(true)}>重建逻辑索引</Button></div><small>需要启用产品任务 Worker；重建会立即停用旧模型空间。物理擦除继续 BLOCKED。</small></>}</Panel>
      <Panel title="执行一次真实检索诊断"><form onSubmit={diagnose}><fieldset disabled={busy}><Field label="查询与重排计费 Agent"><select name="agent" required defaultValue=""><option value="">选择已授权 Agent</option>{options}</select></Field><Field label="客户问题"><textarea name="query" required minLength={1} maxLength={1000} /></Field><Field label="限定文档 ID（可选，逗号分隔）"><input name="documents" /></Field><Field label="精确章节（可选）"><input name="section" maxLength={200} /></Field><label><input name="rerank" type="checkbox" />本次启用额外付费重排</label><Button type="submit" isDisabled={busy || !agents.data} isPending={busy}>查询各阶段</Button></fieldset></form><small>不配置向量时只显示真实关键词召回；失败会显示原因。最终引用仍须回答生成时核对。</small></Panel></div>
    {busy && <p role="status">正在执行，请等待结果；知识库切换已暂时锁定。</p>}
    {error != null && <p className="note">操作结果可能未知。先刷新索引状态并查看用量记录，勿直接重复付费诊断。</p>}
    {result && <><Panel title={`诊断完成 · ${result.elapsed_ms} ms`}><p>调用 ID：{result.call_id}</p><JsonView value={{ stages: result.stages, indexes: result.index_states }} /></Panel><div className="desk-detail-grid"><Hits title="关键词召回" hits={result.keyword} /><Hits title="向量召回" hits={result.vector} /><Hits title="RRF 融合排序" hits={result.fused} /><Hits title="可选 LLM 重排" hits={result.reranked} /></div><Hits title="最终证据候选（不等于已生成引用）" hits={result.final} /></>}
  </>;
}
