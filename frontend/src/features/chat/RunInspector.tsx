import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { useResource } from "../../hooks/useResource";
import { TracePanel } from "./TracePanel";
import { date, errorText } from "./shared";
import type { Row } from "../../types";

const categories: Record<string, string> = {
  helpful: "有帮助", not_helpful: "没有帮助", citation_inaccurate: "引用不准确",
  incomplete: "答案不完整", knowledge_missing: "知识缺失", other: "其他问题",
};
const statuses: Record<string, string> = { open: "待复核", processing: "处理中", reviewed: "已复核", resolved: "已处理" };

export function RunInspector({ conversationId, callId, canReview = false }: { conversationId: string; callId: string; canReview?: boolean }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>执行时间线与人工反馈</summary>
    {open && <>
      <TracePanel conversationId={conversationId} callId={callId} />
      <AnswerReviews conversationId={conversationId} callId={callId} canReview={canReview} />
    </>}
  </details>;
}

function AnswerReviews({ conversationId, callId, canReview }: { conversationId: string; callId: string; canReview: boolean }) {
  const { api, tenant } = useApp();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [cursors, setCursors] = useState<string[]>([]);
  const [category, setCategory] = useState(""), [reviewStatus, setReviewStatus] = useState("");
  const controller = useRef(new AbortController());
  useEffect(() => { controller.current = new AbortController(); return () => controller.current.abort(); }, []);
  const before = cursors.at(-1);
  const prefix = `/conversations/${conversationId}/answer-feedback`;
  const reviews = useResource<Row[]>((signal) => api.request(`${prefix}?call_id=${callId}&limit=30${before ? `&before=${before}` : ""}${category ? `&category=${category}` : ""}${reviewStatus ? `&status=${reviewStatus}` : ""}`, { signal }), [api, tenant, conversationId, callId, before, category, reviewStatus]);
  const own = useResource<Row[]>((signal) => api.request(`${prefix}?call_id=${callId}&mine=true&limit=1`, { signal }), [api, tenant, conversationId, callId]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError("");
    try {
      await api.request(prefix, { method: "POST", body: { call_id: callId, category: data.get("category"), comment: data.get("comment") }, signal: controller.current.signal });
      if (!controller.current.signal.aborted) { form.reset(); reviews.reload(); own.reload(); }
    } catch (e) { if (!controller.current.signal.aborted) setError(errorText(e)); }
    finally { if (!controller.current.signal.aborted) setBusy(false); }
  }
  async function review(event: FormEvent<HTMLFormElement>, row: Row) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      const related = [...data.getAll("related_chunk_ids").map(String), ...String(data.get("additional_chunks") || "").split(/[\s,，]+/).filter(Boolean)];
      await api.request(`${prefix}/${row.id}`, { method: "PATCH", body: { status: data.get("status"), expected_status: row.status, expected_revision: row.revision ?? 0, resolution_category: data.get("resolution_category") || null, resolution_note: data.get("resolution_note"), related_chunk_ids: [...new Set(related)] }, signal: controller.current.signal });
      if (!controller.current.signal.aborted) reviews.reload();
    } catch (e) { if (!controller.current.signal.aborted) setError(errorText(e)); }
    finally { if (!controller.current.signal.aborted) setBusy(false); }
  }
  return <section aria-label="人工回答反馈">
    <h4>人工反馈</h4>
    <p className="note">仅内部协作，关联当前回答及原始引用；不会自动写入知识库或个人记忆。评价不等于语义正确性证明。</p>
    <div className="actions">
      <label>反馈类别<select value={category} onChange={(event) => { setCategory(event.target.value); setCursors([]); }}><option value="">全部类别</option>{Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>处理状态<select value={reviewStatus} onChange={(event) => { setReviewStatus(event.target.value); setCursors([]); }}><option value="">全部状态</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    </div>
    {reviews.loading ? <p role="status">加载反馈…</p> : reviews.error ? <p role="alert">{errorText(reviews.error)} <Button variant="secondary" onPress={reviews.reload}>重试</Button></p> : <>
      {reviews.data?.length ? reviews.data.map((row) => <article key={row.id}>
        <p>{categories[row.category] || row.category} · {statuses[row.status]} · {date(row.created_at)}</p>
        {row.comment && <p>{row.comment}</p>}
        <small><Link to="/chat" state={{ conversationId, messageId: row.message_id }}>查看原回答</Link> · 关联引用 {row.citation_chunk_ids.length} 项</small>
        {row.question_message_id ? <small> · <Link to="/chat" state={{ conversationId, messageId: row.question_message_id }}>查看原始问题</Link></small> : <small> · 原问题关联未知</small>}
        {(row.related_sources || []).map((source: Row) => <p key={source.chunk_id}><small>知识库 {source.knowledge_base_id} · 文档 {source.document_id} · 分块 {source.chunk_id}</small></p>)}
        {canReview && <form onSubmit={(event) => void review(event, row)} key={`${row.id}:${row.revision ?? 0}`}>
          <label>处理状态<select name="status" defaultValue={row.status} disabled={busy}>
            {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          <label>处理分类<select name="resolution_category" defaultValue={row.resolution_category || ""}>
            <option value="">未分类</option><option value="correct">回答正确</option><option value="answer_issue">回答问题</option><option value="knowledge_issue">知识缺失</option><option value="retrieval_issue">检索错误</option><option value="citation_issue">引用错误</option><option value="other">其他</option>
          </select></label>
          <label>处理意见<textarea name="resolution_note" maxLength={1000} defaultValue={row.resolution_note || ""} /></label>
          {row.citation_chunk_ids.map((id: string) => <label key={id}><input type="checkbox" name="related_chunk_ids" value={id} defaultChecked={(row.related_chunk_ids || []).includes(id)} />关联引用 {id}</label>)}
          <label>其他相关知识分块 ID<textarea name="additional_chunks" defaultValue={(row.related_chunk_ids || []).filter((id: string) => !row.citation_chunk_ids.includes(id)).join(", ")} placeholder="从知识检索预览复制 ID，以逗号分隔；服务端会检查企业和访问权限。" /></label>
          <Button type="submit" variant="secondary" isDisabled={busy}>保存处理结果</Button>
        </form>}
        {!canReview && row.resolution_note && <p>处理意见：{row.resolution_note}</p>}
      </article>) : <p>尚无人工反馈。失败或尚未持久化的回答无法提交评价。</p>}
      <div className="actions">
        <Button variant="secondary" isDisabled={!cursors.length} onPress={() => setCursors((old) => old.slice(0, -1))}>较新反馈</Button>
        <Button variant="secondary" isDisabled={reviews.data?.length !== 30} onPress={() => { const last = reviews.data?.at(-1); if (last) setCursors((old) => [...old, last.id]); }}>更早反馈</Button>
      </div>
      {own.error && <p role="alert">本人反馈暂不可用。<Button variant="secondary" onPress={own.reload}>重试</Button></p>}
      {!!own.data?.length && <p>你已提交反馈，可在历史反馈中查阅。</p>}
      {!own.loading && !own.error && !own.data?.length && <form onSubmit={submit}>
        <label>反馈分类<select name="category" required>{Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>内部备注<textarea name="comment" maxLength={1000} placeholder="记录事实与来源问题，请勿填写凭证或不必要的个人信息。" /></label>
        <Button type="submit" variant="secondary" isDisabled={busy}>提交人工反馈</Button>
      </form>}
    </>}
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}
