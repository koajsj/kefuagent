import { useEffect, useState } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { date, errorText } from "./shared";

type TraceEvent = {
  kind: "model" | "tool" | "audit" | "context" | "retrieval" | "memory" | "request" | "result" | "delivery";
  label: string;
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  execution_id: string | null;
  tool_id: string | null;
  model: string | null;
  purpose: string | null;
  provider: string | null;
  task: string | null;
  prompt_id: string | null;
  prompt_version: number | null;
  prompt_hash: string | null;
  error_category: string | null;
  risk: number | null;
  decision: string | null;
  policy_version: string | null;
};
type Trace = {
  request_id: string;
  call_id: string;
  conversation_id: string;
  agent_config_id: string;
  status: string;
  execution_state: string;
  lease_expired: boolean;
  phase: string;
  elapsed_ms: number | null;
  config_version: number;
  error_category: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  usage_complete: boolean;
  cost: { complete: boolean; total: string | null; currency: string | null; unknown_steps: number; known_subtotals: Record<string, string> };
  events: TraceEvent[];
  truncated: boolean;
};

export function TracePanel({ conversationId, callId }: { conversationId: string; callId: string }) {
  const { api, tenant } = useApp();
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setTrace(null);
    setError("");
    setLoading(true);
    api.request<Trace>(`/conversations/${encodeURIComponent(conversationId)}/runs/${encodeURIComponent(callId)}/trace`, { signal: ctrl.signal })
      .then((value) => { if (!ctrl.signal.aborted) setTrace(value); })
      .catch((e) => { if (!ctrl.signal.aborted) setError(errorText(e)); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [api, tenant, conversationId, callId, revision]);
  if (loading) return <p role="status">正在加载执行记录…</p>;
  if (error) return <p role="alert">执行记录不可用：{error} <Button variant="secondary" onPress={() => setRevision((v) => v + 1)}>重试</Button></p>;
  if (!trace) return <p>暂无执行记录</p>;
  return <section aria-label="执行记录">
    <Button variant="secondary" onPress={() => setRevision((value) => value + 1)}>刷新执行记录</Button>
    <p>状态：{trace.status} · 当前阶段：{trace.phase} · 耗时：{trace.elapsed_ms == null ? "未知" : `${trace.elapsed_ms} ms`}</p>
    <p>执行状态：{trace.execution_state || "UNKNOWN"}{trace.lease_expired ? " · 租约已过期，实际结果未知；此诊断查询不会自动重试或结算。" : "（依据最后持久化记录）"}</p>
    <p>请求 ID：{trace.request_id} · 会话 ID：{trace.conversation_id} · 调用 ID：{trace.call_id}</p>
    <p>Agent ID：{trace.agent_config_id}</p>
    <p>Agent 配置 v{trace.config_version} · 输入 {trace.input_tokens ?? "未知"} / 输出 {trace.output_tokens ?? "未知"} Token · {trace.usage_complete ? "用量完整" : "用量可能不完整"}</p>
    {trace.error_category && <p className="warning">{trace.error_category}</p>}
    <p className="note">仅发起人或企业管理员可查看诊断元数据；不包含请求正文、Prompt、记忆、参数或工具结果。旧记录未采集的阶段和耗时显示为未知。</p>
    <p>费用估算：{trace.cost.total != null ? `${trace.cost.total} ${trace.cost.currency}` : "总额未知"}；未知步骤 {trace.cost.unknown_steps}。仅供估算，非账单。</p>
    {Object.entries(trace.cost.known_subtotals).map(([currency, amount]) => <p key={currency}>已知小计：{amount} {currency}</p>)}
    {trace.events.length ? <ol>{trace.events.map((event, index) => <li key={index}>
      {event.label} · {event.status || "未知"} · {event.started_at ? date(event.started_at) : "时间未知"} · {event.elapsed_ms == null ? "耗时未知" : `${event.elapsed_ms} ms`} · 结束 {event.finished_at ? date(event.finished_at) : "未知"}
      {event.kind === "model" && ` · 输入 ${event.input_tokens ?? "未知"} / 输出 ${event.output_tokens ?? "未知"} tokens`}
      {event.risk != null && ` · 风险 R${event.risk}`}{event.decision && ` · 策略 ${event.decision}`}{event.policy_version && ` · ${event.policy_version}`}
      {event.provider && ` · ${event.provider}`}{event.model && ` · ${event.model}`}{event.purpose && ` · ${event.purpose}`}{event.task && ` · 任务 ${event.task}`}
      {event.kind === "model" && <small> · 模板 {event.prompt_id ? `${event.prompt_id} v${event.prompt_version ?? "未知"}` : "未知或无文本模板"}{event.prompt_hash && ` · SHA-256 ${event.prompt_hash}`}</small>}
      {event.execution_id && <small> · 执行 ID {event.execution_id}</small>}
      {event.tool_id && <small> · 工具 ID {event.tool_id}</small>}
      {event.error_category && <p className="warning">{event.error_category}</p>}
    </li>)}</ol> : <p>暂无阶段事件</p>}
    {trace.truncated && <p>记录过多，已截断。</p>}
  </section>;
}
