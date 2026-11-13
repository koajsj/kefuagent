import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { useResource } from "../../hooks/useResource";
import { DataTable, ErrorNotice, Panel } from "../../components/ui";
import type { Row } from "../../types";

export function FeedbackInbox() {
  const { api, tenant } = useApp();
  const [rating, setRating] = useState("dissatisfied");
  const [cursors, setCursors] = useState<string[]>([]);
  const before = cursors.at(-1);
  const rows = useResource<Row[]>((signal) => api.request(`/workspace/feedback?${new URLSearchParams({ limit: "20", ...(rating ? { rating } : {}), ...(before ? { before } : {}) })}`, { signal }), [api, tenant, rating, before]);
  return <Panel title="访客服务评价">
    <p className="note">访客评价关联原会话，可用于人工跟进；满意度不代表 AI 答案准确率。</p>
    <select aria-label="评价筛选" value={rating} onChange={(event) => { setRating(event.target.value); setCursors([]); }}>
      <option value="dissatisfied">不满意</option><option value="satisfied">满意</option><option value="">全部评价</option>
    </select>
    <ErrorNotice error={rows.error} retry={rows.reload} />
    {rows.loading ? <p role="status">正在加载评价…</p> : !rows.error && <>
      {rows.data?.length ? <DataTable columns={["评价", "原因", "时间", "会话"]} rows={rows.data.map((row) => [row.rating === "satisfied" ? "满意" : "不满意", row.comment || "未填写", new Date(row.created_at).toLocaleString(), <Link to="/chat" state={{ conversationId: row.conversation_id }}>查看原会话</Link>])} /> : <p>没有符合条件的评价。</p>}
      <div className="actions">
        <Button variant="secondary" isDisabled={!cursors.length} onPress={() => setCursors((old) => old.slice(0, -1))}>较新评价</Button>
        <Button variant="secondary" isDisabled={rows.data?.length !== 20} onPress={() => { const last = rows.data?.at(-1); if (last) setCursors((old) => [...old, last.id]); }}>更早评价</Button>
      </div>
    </>}
  </Panel>;
}
