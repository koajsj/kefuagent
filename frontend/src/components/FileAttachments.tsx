import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import type { Adapter, Row } from "../types";
import { useResource } from "../hooks/useResource";
import { ErrorNotice } from "./ui";

export function FileAttachments({ api, prefix, visitorToken, disabled = false }: { api: Adapter; prefix: string; visitorToken?: string; disabled?: boolean }) {
  const [key, setKey] = useState(() => crypto.randomUUID()), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>();
  const list = useResource<Row[]>((signal) => api.request(`${prefix}/attachments?limit=20`, { signal, visitorToken }), [api, prefix, visitorToken]);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget, data = new FormData(form); setBusy(true); setError(undefined);
    const file = data.get("file") as File;
    if (!file || file.size > 5 * 1024 * 1024) { setError(new Error("请选择不超过 5 MiB 的文件。")); setBusy(false); return; }
    try {
      await api.request(`${prefix}/attachments?upload_id=${key}`, { method: "POST", body: data, visitorToken });
      setKey(crypto.randomUUID()); form.reset(); list.reload();
    } catch(e) { setError(e); } finally { setBusy(false); }
  }
  async function download(row: Row) {
    setBusy(true); setError(undefined);
    try {
      const blob = await api.request<Blob>(`${prefix}/attachments/${row.id}/content`, { responseType: "blob", visitorToken });
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = row.filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch(e) { setError(e); } finally { setBusy(false); }
  }
  return <details className="file-attachments"><summary>会话附件</summary><p className="note">附件私有保存，不自动作为知识或发送给模型。PDF、DOCX、TXT、Markdown、HTML，每份最多 5 MiB，每会话最多 20 份。</p>
    <ErrorNotice error={error} /><ErrorNotice error={list.error} retry={list.reload} />
    <Button variant="secondary" size="sm" isDisabled={busy || list.loading} onPress={list.reload}>刷新附件</Button>
    {list.loading ? <p role="status">正在读取附件…</p> : !list.error && <ul>{list.data?.map((row) => <li key={row.id}>{row.filename} · {Math.ceil(row.size_bytes / 1024)} KiB · {row.status} <Button size="sm" variant="secondary" isDisabled={busy || row.status !== "ready"} onPress={() => void download(row)}>下载</Button></li>)}</ul>}
    <form onSubmit={upload}><label>选择文件<input name="file" type="file" accept=".pdf,.docx,.txt,.md,.html" required disabled={busy || disabled} /></label>{!visitorToken && <label><input type="checkbox" name="public" value="true" disabled={busy || disabled} /> 明确分享给当前访客（默认仅企业成员可见）</label>}<Button type="submit" variant="secondary" isPending={busy} isDisabled={busy || disabled}>上传附件</Button></form>
    <p>上传失败或结果未知时，保留当前文件与请求标识重试；物理擦除仍受数据治理阻断。</p>
  </details>;
}
