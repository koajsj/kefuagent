import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { EditorModal } from "../../components/EditorModal";
import { ErrorNotice, Field, Pager } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";

export function ChunkVersions({ documentId, chunk, onChanged, readOnly }: { documentId: string; chunk: Row; onChanged: () => void; readOnly: boolean }) {
  const { api, notify } = useApp();
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Row | null>(null);
  const [action, setAction] = useState<"edit" | "delete" | "restore" | null>(null);
  const [content, setContent] = useState(String(chunk.content || ""));
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => { pending.current?.abort(); pending.current = null; }, []);
  const path = `/documents/${documentId}/chunks/${chunk.id}`;
  const versions = useResource<Row[]>(
    (signal) => open ? api.request(`${path}/versions?limit=20&offset=${offset}`, { signal }) : Promise.resolve([]),
    [api, path, open, offset],
  );
  const start = (next: "edit" | "delete" | "restore") => {
    setAction(next); setReason(""); setContent(String(chunk.content || "")); setError(""); setConfirming(false);
  };
  const close = () => {
    if (pending.current) { pending.current.abort(); pending.current = null; notify("请求已中止，操作结果可能未知，请刷新分块确认。"); onChanged(); }
    setBusy(false); setAction(null); setConfirming(false); setError("");
  };
  const prepare = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setConfirming(true);
  };
  const submit = async () => {
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setError("");
    try {
      const body = action === "edit"
        ? { expected_current_id: chunk.id, content, reason }
        : action === "restore"
          ? { expected_current_id: chunk.id, source_version_id: selected!.id, reason }
          : { expected_current_id: chunk.id, reason };
      await api.request(action === "restore" ? `${path}/restore` : path, {
        method: action === "edit" ? "PATCH" : action === "restore" ? "POST" : "DELETE", body, signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setAction(null); setConfirming(false); setSelected(null); versions.reload(); onChanged();
    } catch (e) {
      if (!controller.signal.aborted && !["AbortError", "StaleResponse"].includes((e as Error).name)) {
        const code = (e as { code?: string }).code;
        setError((e as Error).message);
        if (code === "chunk_changed" || code === "document_changed") { notify("版本或文档状态已变化，已刷新分块，请重新操作。"); versions.reload(); onChanged(); }
      }
    } finally { if (pending.current === controller) { pending.current = null; setBusy(false); } }
  };
  return <>
    <div className="actions">
      <Button variant="secondary" onPress={() => { setOpen(!open); setSelected(null); setOffset(0); }}>{open ? "收起版本" : "版本历史"}</Button>
      {!readOnly && !chunk.is_deleted && <Button variant="secondary" onPress={() => start("edit")}>编辑</Button>}
      {!readOnly && !chunk.is_deleted && <Button variant="danger" onPress={() => start("delete")}>删除分块</Button>}
    </div>
    {readOnly && <p>历史代次仅供查看，不能跨代恢复或修改。</p>}
    {open && <div>
      <ErrorNotice error={versions.error} retry={versions.reload} />
      {versions.loading ? <p>版本加载中…</p> : !versions.error && !versions.data?.length ? <p>没有版本记录。</p> : versions.data?.map((v) => <div key={v.id}>
        <Button variant="secondary" onPress={() => setSelected(v)}>版本 {v.revision}{v.is_current ? " · 当前" : ""}{v.is_deleted ? " · 已删除" : ""}</Button>
        <small> · 代次 {v.generation} · 第 {v.position + 1} 块{v.page != null ? ` · 页 ${v.page}` : ""}{v.section ? ` · ${v.section}` : ""} · 修改者 {v.revised_by ?? "—"} · {v.created_at || "—"} · 原因 {v.revision_reason || "—"}</small>
      </div>)}
      <Pager offset={offset} count={versions.data?.length || 0} size={20} onChange={(value) => { setOffset(value); setSelected(null); }} />
      {selected && <>
        <p>文本{chunk.content === selected.content ? "相同" : "不同"}（以下为完整文本对照）。</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "1rem" }}>
          <div><strong>当前版本{chunk.is_deleted ? "（已删除）" : ""}</strong><p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{chunk.content}</p></div>
          <div><strong>所选版本 {selected.revision}{selected.is_deleted ? "（已删除）" : ""}</strong><p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{selected.content}</p></div>
        </div>
        {!readOnly && !selected.is_deleted && !selected.is_current && <Button variant="secondary" onPress={() => start("restore")}>恢复所选版本</Button>}
      </>}
    </div>}
    {action && <EditorModal title={action === "edit" ? "编辑分块" : action === "delete" ? "删除分块" : "恢复版本"} onClose={close}>
      <form onSubmit={prepare}>
        {action === "edit" && <Field label="完整内容"><textarea required maxLength={1200} value={content} onChange={(e) => setContent(e.target.value)} disabled={busy || confirming} /></Field>}
        <Field label="修改原因"><textarea required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy || confirming} /></Field>
        {error && <p role="alert">{error}</p>}
        {confirming ? <>
          <p>{action === "delete" ? "确认删除此分块？它将停止参与检索。" : action === "restore" ? `确认用版本 ${selected?.revision} 创建新的当前版本？` : "确认提交以下完整内容？"}</p>
          {action === "edit" && <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{content}</p>}
          {action === "restore" && <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{selected?.content}</p>}
          <p>原因：{reason}</p>
          <div className="actions"><Button type="button" isDisabled={busy} onPress={() => void submit()}>确认提交</Button><Button type="button" variant="secondary" isDisabled={busy} onPress={() => setConfirming(false)}>返回修改</Button><Button type="button" variant="secondary" onPress={close}>取消</Button></div>
        </> : <div className="actions"><Button type="submit" isDisabled={busy}>检查并确认</Button><Button type="button" variant="secondary" isDisabled={busy} onPress={close}>取消</Button></div>}
      </form>
    </EditorModal>}
  </>;
}
