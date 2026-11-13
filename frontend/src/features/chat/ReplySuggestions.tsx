import { useEffect, useRef, useState } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { ErrorNotice, Panel, Status } from "../../components/ui";
import { TracePanel } from "./TracePanel";
import { explain } from "../../adapters/errors";
import type { ReplySuggestion } from "../../types/product";

export function ReplySuggestions({ conversationId, agentId, sent }: { conversationId: string; agentId: string; sent: () => void }) {
  const { api, tenant, notify } = useApp();
  const [draft, setDraft] = useState<ReplySuggestion | null>(null), [content, setContent] = useState(""), [feedback, setFeedback] = useState(""), [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(), [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [initialLoading, setInitialLoading] = useState(true), [initialError, setInitialError] = useState<unknown>(), [reload, setReload] = useState(0);
  const lifetime = useRef(new AbortController());
  const observe = (value: ReplySuggestion) => { setDraft(value); setContent(value.content); setConfirmed(false); };
  useEffect(() => { const ctrl = new AbortController(); lifetime.current = ctrl; return () => ctrl.abort(); }, [api, tenant, conversationId]);
  useEffect(() => {
    const ctrl = new AbortController();
    if (api.mode === "api") {
      setInitialLoading(true); setInitialError(undefined);
      api.request<ReplySuggestion[]>(`/conversations/${conversationId}/drafts?limit=1`, { signal: ctrl.signal })
        .then(rows => { if (!ctrl.signal.aborted && rows.length) observe(rows[0]); })
        .catch(e => { if (!ctrl.signal.aborted) setInitialError(e); })
        .finally(() => { if (!ctrl.signal.aborted) setInitialLoading(false); });
    }
    return () => ctrl.abort();
  }, [api, tenant, conversationId, reload]);
  useEffect(() => {
    if (!draft || draft.status !== "GENERATING") return;
    const ctrl = new AbortController(); let timer: ReturnType<typeof setTimeout>, failures = 0;
    const poll = async () => {
      if (document.hidden) { timer = setTimeout(poll, 5000); return; }
      try { const value = await api.request<ReplySuggestion>(`/reply-drafts/${draft.id}`, { signal: ctrl.signal }); if (!ctrl.signal.aborted) { failures = 0; observe(value); if (value.status === "GENERATING") timer = setTimeout(poll, 5000); } } catch (e) { if (!ctrl.signal.aborted) { setError(e); failures++; timer = setTimeout(poll, Math.min(60000, 5000*2**Math.min(4,failures))); } }
    };
    timer = setTimeout(poll, 2000); return () => { ctrl.abort(); clearTimeout(timer); };
  }, [api, draft?.id, draft?.status]);
  async function act(action: string) {
    if (!draft || busy) return;
    setBusy(true); setError(undefined);
    try { const value = await api.request<ReplySuggestion>(`/reply-drafts/${draft.id}/actions`, { method: "POST", body: { action, expected_version: draft.version, ...(action === "edit" || action === "accept_send" ? { content } : {}), ...(feedback.trim() ? { feedback } : {}), confirmed_human_send: action === "accept_send" && confirmed }, signal: lifetime.current.signal }); if (!lifetime.current.signal.aborted) { observe(value); if (action === "accept_send") sent(); } } catch (e) { if (!lifetime.current.signal.aborted) setError(e); } finally { if (!lifetime.current.signal.aborted) setBusy(false); }
  }
  async function generate() {
    if (busy) return;
    if (draft && draft.agent_config_id === agentId && ["DRAFT","GENERATED","EDITED"].includes(draft.status)) { await act("generate"); return; }
    setBusy(true); setError(undefined);
    try { const created = await api.request<ReplySuggestion>(`/conversations/${conversationId}/drafts`, { method: "POST", body: { agent_config_id: agentId, request_key: requestKey }, signal: lifetime.current.signal }); if (lifetime.current.signal.aborted) return; observe(created); setRequestKey(crypto.randomUUID()); const queued = await api.request<ReplySuggestion>(`/reply-drafts/${created.id}/actions`, { method: "POST", body: { action: "generate", expected_version: created.version }, signal: lifetime.current.signal }); if (!lifetime.current.signal.aborted) observe(queued); } catch (e) { if (!lifetime.current.signal.aborted) setError(e); } finally { if (!lifetime.current.signal.aborted) setBusy(false); }
  }
  if (api.mode === "demo") return <Panel title="AI 草稿建议"><p>NOT_AVAILABLE：离线 Demo 不模拟真实草稿生成、预算或人工发送授权。</p></Panel>;
  const editable = draft && ["GENERATED", "EDITED"].includes(draft.status), unsaved = editable && content !== draft.content;
  return <Panel title="AI 草稿建议 · 仅客服可见"><p>生成只产生内部建议；不会发送或执行业务操作。请核实知识来源和业务事实，再明确确认发送。使用上方选择的 Agent；生成需产品任务 Worker。</p><ErrorNotice error={initialError} retry={() => setReload(value => value + 1)} /><ErrorNotice error={error} />{initialLoading && <p role="status">正在加载已有草稿…</p>}<div className="actions"><Button isPending={busy} isDisabled={busy || initialLoading || !!initialError || !agentId || draft?.status === "GENERATING"} onPress={() => void generate()}>{draft && editable ? "重新生成" : "生成回复草稿"}</Button>{draft && <Status value={draft.status} />}</div>
    {draft && <><small>草稿 v{draft.version} · {new Date(draft.expires_at).toLocaleString()} 到期</small>{draft.error_category && <p role="alert">生成失败：{explain(draft.error_category)}</p>}{draft.warnings.map((value,index) => <p className="warning" key={index}>{value}</p>)}
      <textarea aria-label="审核并编辑 AI 草稿" value={content} maxLength={16000} disabled={!editable || busy} onChange={e => { setContent(e.target.value); setConfirmed(false); }} />
      <div className="actions"><Button variant="secondary" isDisabled={!editable || !unsaved || busy} onPress={() => void act("edit")}>保存人工编辑</Button><Button variant="secondary" isDisabled={!content} onPress={() => { navigator.clipboard.writeText(content).then(() => notify("已复制草稿，请核实后使用。")).catch(e => setError(e)); }}>复制</Button>{draft.model_call_id && <details><summary>查看草稿执行记录</summary><TracePanel conversationId={conversationId} callId={draft.model_call_id} /></details>}</div>
      {draft.citations.map((citation,index) => <details key={`${citation.chunk_id}.${index}`}><summary>来源 {index+1}：{citation.document_name}</summary><blockquote>{citation.quote}</blockquote><small>文档 {citation.document_id} · 分块 {citation.chunk_id}</small></details>)}
      <textarea aria-label="草稿评审反馈或拒绝理由" value={feedback} maxLength={1000} onChange={e => setFeedback(e.target.value)} placeholder="记录编辑原因、质量反馈；拒绝时必填" />
      <div className="actions"><Button variant="secondary" isDisabled={busy || !feedback.trim() || !["GENERATED","EDITED","ACCEPTED","REJECTED"].includes(draft.status)} onPress={() => void act("feedback")}>保存反馈</Button><Button variant="danger-soft" isDisabled={busy || !feedback.trim() || !["DRAFT","GENERATING","GENERATED","EDITED"].includes(draft.status)} onPress={() => void act("reject")}>拒绝草稿</Button></div>
      <label><input type="checkbox" checked={confirmed} disabled={!editable || !!unsaved || busy} onChange={e => setConfirmed(e.target.checked)} />我已审核本版本与引用，确认以人工身份发送给客户。</label><Button isDisabled={!editable || !!unsaved || !confirmed || busy || !content.trim()} onPress={() => void act("accept_send")}>采纳并发送人工答复</Button>
      {draft.sent_message_id && <p role="status">已发送，消息 ID：{draft.sent_message_id}。重复请求仅返回原记录。</p>}
    </>}
  </Panel>;
}
