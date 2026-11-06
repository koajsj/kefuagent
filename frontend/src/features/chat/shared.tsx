import { Button } from "@heroui/react";
import { Link } from "react-router-dom";
import type { Row } from "../../types";
export const phases: Record<string, string> = {
  pending: "等待执行",
  retrieving: "知识检索中",
  model_running: "模型请求中",
  tool_running: "工具执行中",
  completed: "已完成",
  failed: "失败",
};
export const date = (value: string) =>
  value ? new Date(value).toLocaleString("zh-CN") : "未知";
export const errorText = (error: any) =>
  error.code === "version_conflict"
    ? "会话已被其他人更新，请重新打开后操作。"
    : error.message || "请求失败";
export function Message({
  message: m,
  visitor = false,
  showSourceId = false,
}: {
  message: Row;
  visitor?: boolean;
  showSourceId?: boolean;
}) {
  const citations = m.citations || m.metadata?.citations || [];
  return (
    <article className={`message ${m.role}`}>
      <div className="message-label">
        {m.role === "user"
          ? visitor
            ? "您"
            : "用户"
          : m.role === "tool"
            ? "工具"
            : m.source === "manual"
              ? "人工回复"
              : "客服助手"}{" "}
        · {date(m.created_at)}
      </div>
      <p>{m.content || "工具调用请求"}</p>
      {showSourceId && (
        <div className="message-memory">
          <Link
            to="/memory"
            state={{
              source: m.id,
              quote: String(m.content || "").slice(0, 300),
            }}
          >
            保存为个人记忆
          </Link>
          <details>
            <summary>查看来源消息 ID</summary>
            <small className="message-source">{m.id}</small>
          </details>
        </div>
      )}
      {!!citations.length && (
        <div className="citations">
          {citations.map((c: any, i: number) => (
            <p key={i}>
              [{i + 1}] {c.document_name}
              {c.page ? ` · 第 ${c.page} 页` : ""}：{c.quote}
            </p>
          ))}
        </div>
      )}
      {m.metadata?.tool_calls && (
        <details>
          <summary>调用信息</summary>
          <pre>{JSON.stringify(m.metadata.tool_calls, null, 2)}</pre>
        </details>
      )}
      {m.tool_results?.map((t: any, i: number) => (
        <details key={i}>
          <summary>
            {t.name} · {t.status}
          </summary>
          <pre>
            {JSON.stringify(t.data ?? { error: t.error_category }, null, 2)}
          </pre>
        </details>
      ))}
    </article>
  );
}
export function Pager({
  offset,
  count,
  size,
  onChange,
}: {
  offset: number;
  count: number;
  size: number;
  onChange: (offset: number) => void;
}) {
  return (
    <div className="message-pagination">
      <Button
        variant="secondary"
        isDisabled={!offset}
        onPress={() => onChange(Math.max(0, offset - size))}
      >
        上一页
      </Button>
      <span>第 {Math.floor(offset / size) + 1} 页</span>
      <Button
        variant="secondary"
        isDisabled={count < size}
        onPress={() => onChange(offset + size)}
      >
        下一页
      </Button>
    </div>
  );
}
