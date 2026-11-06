import { Button } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import { useApp } from "../../app/context";
import type {
  Row,
  Conversation as ConversationRecord,
  Agent,
  TurnOutcome,
} from "../../types";
import { requestIdentity } from "../../adapters/identity";
import { sessionState } from "../../adapters/storage";
import { explain } from "../../adapters/errors";
import { Message, Pager, date, errorText, phases } from "./shared";
import { Operations } from "./Operations";
export function ChatPage() {
  const { api, tenant } = useApp();
  const [rows, setRows] = useState<ConversationRecord[]>([]),
    [offset, setOffset] = useState(0),
    [filters, setFilters] = useState<Record<string, string>>({}),
    [operators, setOperators] = useState<Row[] | null>(null),
    [operatorsError, setOperatorsError] = useState(""),
    [selected, setSelected] = useState<ConversationRecord | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [reload, setReload] = useState(0),
    [opening, setOpening] = useState(false),
    [subject, setSubject] = useState("");
  const openEpoch = useRef(0),
    operatorEpoch = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      ++openEpoch.current;
    };
  }, []);
  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError("");
    api
      .request<ConversationRecord[]>(
        `/conversations?${new URLSearchParams({ limit: "20", offset: String(offset), ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) })}`,
        { signal: ctrl.signal },
      )
      .then((result) => {
        if (!ctrl.signal.aborted) setRows(result);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [api, tenant, offset, filters, reload]);
  async function loadOperators() {
    const ticket = ++operatorEpoch.current;
    setOperatorsError("");
    try {
      const result = await api.request<Row[]>("/workspace/operators");
      if (alive.current && ticket === operatorEpoch.current)
        setOperators(result);
    } catch (e) {
      if (alive.current && ticket === operatorEpoch.current)
        setOperatorsError(errorText(e));
    }
  }
  useEffect(() => {
    setOperators(null);
    loadOperators();
    return () => {
      ++operatorEpoch.current;
    };
  }, [api, tenant]);
  async function open(id: string, force = false) {
    if (busy && !force) return;
    const ticket = ++openEpoch.current;
    setOpening(true);
    setError("");
    try {
      const result = await api.request<ConversationRecord>(
        `/conversations/${id}`,
      );
      if (alive.current && ticket === openEpoch.current) setSelected(result);
    } catch (e) {
      if (alive.current && ticket === openEpoch.current) setError(errorText(e));
    } finally {
      if (alive.current && ticket === openEpoch.current) setOpening(false);
    }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!subject.trim()) return;
    setError("");
    try {
      const result = await api.request<ConversationRecord>("/conversations", {
        method: "POST",
        body: { subject: subject.trim(), channel: "web" },
      });
      if (!alive.current) return;
      setSubject("");
      setOffset(0);
      setReload((v) => v + 1);
      await open(result.id);
    } catch (e) {
      if (alive.current) setError(errorText(e));
    }
  }
  return (
    <>
      <header className="page-heading">
        <div>
          <h1>客服会话</h1>
          <p>企业知识、人工协作与每一步处理记录。</p>
        </div>
        <form onSubmit={create} className="actions">
          <input
            aria-label="新会话标题"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="新会话标题"
            required
            maxLength={160}
          />
          <Button
            variant="primary"
            className="primary"
            type="submit"
            isDisabled={busy || opening}
          >
            新建会话
          </Button>
        </form>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
          <Button variant="secondary" onPress={() => setReload((v) => v + 1)}>
            重试
          </Button>
        </p>
      )}
      <div className="chat-layout">
        <aside className="conversation-sidebar">
          <form
            className="operation-filters"
            onSubmit={(e) => {
              e.preventDefault();
              setFilters(
                Object.fromEntries(new FormData(e.currentTarget)) as Record<
                  string,
                  string
                >,
              );
              setOffset(0);
            }}
          >
            <input
              name="q"
              placeholder="搜索会话标题"
              aria-label="搜索标题"
              maxLength={100}
            />
            <select name="queue" aria-label="会话队列">
              {[
                "all",
                "pending",
                "unassigned",
                "mine",
                "human",
                "ai",
                "resolved",
              ].map((q, i) => (
                <option key={q} value={q}>
                  {
                    [
                      "全部",
                      "待处理",
                      "未分配",
                      "我的",
                      "人工",
                      "AI",
                      "已解决",
                    ][i]
                  }
                </option>
              ))}
            </select>
            <select name="assignee_id" aria-label="负责人">
              <option value="">全部负责人</option>
              {operators?.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.display_name}
                </option>
              ))}
            </select>
            <select name="priority" aria-label="优先级">
              <option value="">全部优先级</option>
              {["low", "normal", "high", "urgent"].map((p, i) => (
                <option key={p} value={p}>
                  {["低", "普通", "高", "紧急"][i]}
                </option>
              ))}
            </select>
            <select name="sort" aria-label="排序">
              <option value="newest">最新优先</option>
              <option value="oldest">最早优先</option>
            </select>
            <Button variant="secondary" type="submit">
              筛选
            </Button>
          </form>
          {operatorsError && (
            <p className="error">
              负责人加载失败：{operatorsError}
              <Button variant="secondary" onPress={loadOperators}>
                重试
              </Button>
            </p>
          )}
          <div className="conversation-list">
            {loading ? (
              <p>正在加载会话…</p>
            ) : !rows.length ? (
              <p className="empty-state">还没有匹配的会话。</p>
            ) : (
              rows.map((r) => (
                <Button
                  variant="secondary"
                  key={r.id}
                  isDisabled={busy || opening}
                  className={`conversation-item ${selected?.id === r.id ? "selected" : ""}`}
                  onPress={() => open(r.id)}
                >
                  <strong>{r.subject}</strong>
                  <span className="badge">{r.support_state}</span>
                  <small>
                    {date(r.updated_at)} · {r.priority || "normal"} · SLA{" "}
                    {r.sla?.state || "未知"}
                  </small>
                </Button>
              ))
            )}
          </div>
          <Pager
            offset={offset}
            count={rows.length}
            size={20}
            onChange={setOffset}
          />
        </aside>
        {selected ? (
          <Conversation
            key={selected.id}
            suspended={opening}
            initial={selected}
            operators={operators}
            onBusy={setBusy}
            refresh={() => open(selected.id, true)}
            changed={() => setReload((v) => v + 1)}
          />
        ) : (
          <section className="chat-main panel empty-state">
            {opening ? "正在打开会话…" : "选择一个会话，或新建会话开始咨询。"}
          </section>
        )}
      </div>
    </>
  );
}
function Conversation({
  initial,
  suspended,
  operators,
  onBusy,
  refresh,
  changed,
}: {
  initial: ConversationRecord;
  suspended: boolean;
  operators: Row[] | null;
  onBusy: (v: boolean) => void;
  refresh: () => Promise<void>;
  changed: () => void;
}) {
  const { api, tenant, role, user } = useApp();
  const [c, setC] = useState(initial),
    [messages, setMessages] = useState<Row[]>([]),
    [historyOffset, setHistoryOffset] = useState(0),
    [historyLoading, setHistoryLoading] = useState(true),
    [historyError, setHistoryError] = useState(""),
    [newMessages, setNewMessages] = useState(false),
    [agents, setAgents] = useState<Agent[]>([]),
    [agent, setAgent] = useState(""),
    [agentQuery, setAgentQuery] = useState(""),
    [agentOffset, setAgentOffset] = useState(0),
    [agentCount, setAgentCount] = useState(0),
    [agentLoading, setAgentLoading] = useState(true),
    [agentError, setAgentError] = useState(""),
    [agentReload, setAgentReload] = useState(0),
    [content, setContent] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [preview, setPreview] = useState(""),
    [runState, setRunState] = useState("尚未发送"),
    [runs, setRuns] = useState<Row[]>([]),
    [runsError, setRunsError] = useState(""),
    [result, setResult] = useState<any>(null),
    [stale, setStale] = useState(false),
    [historyReload, setHistoryReload] = useState(0);
  const controller = useRef(new AbortController()),
    pending = useRef<any>(null),
    state = useRef({ c, historyOffset, busy }),
    latest = useRef<string | null>(null),
    historyEpoch = useRef(0),
    agentRef = useRef(agent);
  agentRef.current = agent;
  state.current = { c, historyOffset, busy };
  const key = `support.pending.${tenant}.${c.id}`;
  useEffect(() => {
    controller.current = new AbortController();
    pending.current = (() => {
      try {
        return JSON.parse(sessionState.get(key) || "null");
      } catch {
        return null;
      }
    })();
    return () => {
      controller.current.abort();
      onBusy(false);
    };
  }, [key]);
  async function readRuns() {
    try {
      const r = await api.request<Row[]>(
        `/conversations/${c.id}/calls?limit=5`,
        { signal: controller.current.signal },
      );
      if (controller.current.signal.aborted) return;
      setRuns(r);
      setRunsError("");
    } catch (e) {
      if (!controller.current.signal.aborted) setRunsError(errorText(e));
    }
  }
  useEffect(() => {
    readRuns();
  }, [api, c.id, initial.version]);
  useEffect(() => {
    setC(initial);
    setStale(false);
    setHistoryReload((v) => v + 1);
  }, [initial]);
  useEffect(() => {
    const ctrl = new AbortController();
    const ticket = ++historyEpoch.current;
    setHistoryLoading(true);
    setHistoryError("");
    api
      .request<Row[]>(
        `/conversations/${c.id}/messages?newest=true&limit=50&offset=${historyOffset}`,
        { signal: ctrl.signal },
      )
      .then((r) => {
        if (ctrl.signal.aborted || ticket !== historyEpoch.current) return;
        setMessages(r);
        if (!historyOffset) {
          latest.current = r.at(-1)?.id || null;
          setNewMessages(false);
        }
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setHistoryError(errorText(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setHistoryLoading(false);
      });
    return () => ctrl.abort();
  }, [api, c.id, historyOffset, historyReload]);
  useEffect(() => {
    const ctrl = new AbortController();
    setAgentLoading(true);
    setAgentError("");
    const timer = setTimeout(() => {
      api
        .request<Agent[]>(
          `/agent-configs?${new URLSearchParams({ q: agentQuery.trim(), limit: "50", offset: String(agentOffset) })}`,
          { signal: ctrl.signal },
        )
        .then((r) => {
          if (ctrl.signal.aborted) return;
          setAgentCount(r.length);
          setAgents((old) => {
            const current = old.find((a) => a.id === agentRef.current);
            return current && !r.some((a) => a.id === current.id)
              ? [current, ...r]
              : r;
          });
          setAgent((current) => current || r.find((a) => a.enabled)?.id || "");
        })
        .catch((e) => {
          if (!ctrl.signal.aborted) setAgentError(errorText(e));
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setAgentLoading(false);
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [api, c.id, agentQuery, agentOffset, agentReload]);
  function update(next: ConversationRecord) {
    setC((old) => {
      if (
        old.version !== next.version ||
        old.assignee_id !== next.assignee_id ||
        old.support_state !== next.support_state ||
        old.status !== next.status
      )
        setStale(true);
      return next;
    });
  }
  useEffect(() => {
    if (suspended) return;
    let stopped = false,
      paused = false,
      timer: ReturnType<typeof setTimeout>,
      pollController: AbortController | undefined,
      failures = 0,
      inFlight = false;
    const active = () =>
      !stopped &&
      !paused &&
      !document.hidden &&
      state.current.c.status === "open";
    const schedule = (delay = 5000) => {
      clearTimeout(timer);
      if (active()) timer = setTimeout(poll, delay);
    };
    async function poll() {
      if (!active() || inFlight) return;
      inFlight = true;
      const request = new AbortController();
      pollController = request;
      try {
        const next = await api.request<ConversationRecord>(
          `/conversations/${initial.id}`,
          {
            signal: request.signal,
          },
        );
        if (!active() || request.signal.aborted) return;
        update(next);
        state.current.c = next;
        if (next.status !== "open") {
          setHistoryOffset(0);
          setHistoryReload((v) => v + 1);
          return;
        }
        if (!state.current.busy) {
          const epoch = historyEpoch.current;
          const anchor = latest.current;
          const r = await api.request<Row[]>(
            `/conversations/${initial.id}/messages?${anchor ? "limit=100&after=" + encodeURIComponent(anchor) : "newest=true&limit=50&offset=0"}`,
            { signal: request.signal },
          );
          if (
            !active() ||
            request.signal.aborted ||
            epoch !== historyEpoch.current
          )
            return;
          if (r.length) {
            latest.current = r.at(-1)!.id;
            if (state.current.historyOffset === 0)
              setMessages((old) =>
                anchor
                  ? [
                      ...old,
                      ...r.filter((m) => !old.some((o) => o.id === m.id)),
                    ]
                  : r,
              );
            else setNewMessages(true);
          }
        }
        failures = 0;
      } catch (e: any) {
        if (!request.signal.aborted) {
          if ([401, 403, 404, 410].includes(e.status)) {
            stopped = true;
            setMessages([]);
            setPreview("");
            setRuns([]);
            setStale(true);
            setError(errorText(e));
          } else failures = Math.min(4, failures + 1);
        }
      } finally {
        inFlight = false;
        schedule(Math.min(60000, 5000 * 2 ** failures));
      }
    }
    const hide = () => {
      clearTimeout(timer);
      pollController?.abort();
    };
    const visibility = () => (document.hidden ? hide() : schedule());
    const pagehide = () => {
      paused = true;
      hide();
    };
    const pageshow = () => {
      paused = false;
      schedule();
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("pagehide", pagehide);
    window.addEventListener("pageshow", pageshow);
    schedule();
    return () => {
      stopped = true;
      hide();
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pagehide", pagehide);
      window.removeEventListener("pageshow", pageshow);
    };
  }, [api, initial.id, suspended]);
  const human = c.support_state === "human",
    canHuman = role === "admin" || c.assignee_id === user.id,
    canSend =
      !suspended &&
      c.status === "open" &&
      (human
        ? canHuman
        : c.support_state === "ai" &&
          c.channel !== "public" &&
          agents.some((a) => a.id === agent && a.enabled));
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !canSend || !content.trim()) return;
    setBusy(true);
    onBusy(true);
    setError("");
    setPreview("");
    setResult(null);
    const submitted = content;
    try {
      if (human)
        await api.request(`/conversations/${c.id}/messages`, {
          method: "POST",
          body: { role: "assistant", content: submitted },
          signal: controller.current.signal,
        });
      else {
        const payload = { agent_config_id: agent, content: submitted };
        pending.current = await requestIdentity(payload, pending.current);
        if (controller.current.signal.aborted) return;
        sessionState.set(key, JSON.stringify(pending.current));
        const r = await api.request<TurnOutcome>(
          `/conversations/${c.id}/agent-turns/stream`,
          {
            method: "POST",
            body: { ...payload, idempotency_key: pending.current.key },
            signal: controller.current.signal,
            onEvent: (event, v) => {
              if (event === "stage") setRunState(phases[v.phase] || v.phase);
              if (event === "delta") setPreview((old) => old + v.text);
              if (event === "discard") setPreview("");
            },
          },
        );
        setResult(r);
        if (r.status === "running") {
          setError("原请求仍在执行，请稍后使用相同内容重试。");
          return;
        }
        pending.current = null;
        sessionState.remove(key);
        setPreview("");
      }
      setContent((old) => (old === submitted ? "" : old));
      setHistoryOffset(0);
      setHistoryReload((v) => v + 1);
      changed();
      await readRuns();
    } catch (e: any) {
      if (!controller.current.signal.aborted)
        setError(
          errorText(e) +
            (human
              ? " 人工回复结果可能未知，请先刷新历史核实。"
              : " 可保留相同内容重试，继续使用原请求标识。"),
        );
    } finally {
      if (!controller.current.signal.aborted) {
        setBusy(false);
        onBusy(false);
        try {
          update(
            await api.request<ConversationRecord>(`/conversations/${c.id}`, {
              signal: controller.current.signal,
            }),
          );
        } catch (e) {
          if (!controller.current.signal.aborted) setError(errorText(e));
        }
      }
    }
  }
  async function handling(value: string) {
    if (busy) return;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      await api.request(`/conversations/${c.id}/handling`, {
        method: "POST",
        body: { state: value, expected_version: c.version },
        signal: controller.current.signal,
      });
      changed();
      onBusy(false);
      setBusy(false);
      await refresh();
    } catch (e) {
      if (!controller.current.signal.aborted) setError(errorText(e));
    } finally {
      if (!controller.current.signal.aborted) {
        setBusy(false);
        onBusy(false);
      }
    }
  }
  return (
    <>
      <section className="chat-main">
        <header className="chat-controls">
          <h2>{c.subject}</h2>
          <span className="badge">
            {c.support_state} · {c.status}
          </span>
          <div className="actions">
            {c.status === "open" && (
              <>
                {(!human || canHuman) && (
                  <Button
                    variant="secondary"
                    isDisabled={busy}
                    onPress={() => handling("waiting")}
                  >
                    标记待人工
                  </Button>
                )}
                {(role === "admin"
                  ? !human
                  : c.support_state === "waiting" &&
                    (!c.assignee_id || c.assignee_id === user.id)) && (
                  <Button
                    variant="secondary"
                    isDisabled={busy}
                    onPress={() => handling("human")}
                  >
                    人工接管
                  </Button>
                )}
                {((role === "admin" && c.support_state !== "ai") ||
                  (human && canHuman)) && (
                  <Button
                    variant="secondary"
                    isDisabled={busy}
                    onPress={() => handling("ai")}
                  >
                    恢复 AI
                  </Button>
                )}
                {(role === "admin" || (human && canHuman)) && (
                  <Button
                    variant="secondary"
                    isDisabled={busy}
                    onPress={() => handling("resolved")}
                  >
                    标记已解决
                  </Button>
                )}
              </>
            )}
            {role === "admin" && c.status === "closed" && (
              <Button
                variant="secondary"
                isDisabled={busy}
                onPress={async () => {
                  try {
                    await api.request(`/conversations/${c.id}`, {
                      method: "PATCH",
                      body: { status: "open" },
                    });
                    await refresh();
                    changed();
                  } catch (e) {
                    setError(errorText(e));
                  }
                }}
              >
                重新打开会话
              </Button>
            )}
            <Button variant="secondary" isDisabled={busy} onPress={refresh}>
              重新打开 / 刷新状态
            </Button>
          </div>
          <label>
            搜索 Agent
            <input
              value={agentQuery}
              onChange={(e) => {
                setAgentQuery(e.target.value);
                setAgentOffset(0);
              }}
              maxLength={120}
            />
          </label>
          <label>
            当前 Agent
            <select
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
              disabled={busy || c.channel === "public" || human}
            >
              <option value="">选择 Agent</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id} disabled={!a.enabled}>
                  {a.name} ·{" "}
                  {a.provider === "demo" ? "离线演示" : "真实模型配置"}
                  {!a.enabled ? "（停用）" : ""}
                </option>
              ))}
            </select>
          </label>
          {agentLoading ? (
            <p>正在加载 Agent…</p>
          ) : agentError ? (
            <p className="error">
              {agentError}
              <Button
                variant="secondary"
                onPress={() => setAgentReload((v) => v + 1)}
              >
                重试
              </Button>
            </p>
          ) : !agents.length ? (
            <p>暂无可用 Agent，请联系管理员。</p>
          ) : null}
          <Pager
            offset={agentOffset}
            count={agentCount}
            size={50}
            onChange={setAgentOffset}
          />
        </header>
        {c.channel === "public" && (
          <p className="note">
            公开会话的 AI
            回复由访客入口发起；管理员或当前负责人可在人工处理时答复。
          </p>
        )}
        {c.support_state === "waiting" && (
          <p className="note">正在等待人工接管，AI 回复已暂停。</p>
        )}
        {historyError ? (
          <p role="alert" className="error">
            {historyError}
            <Button
              variant="secondary"
              onPress={() => setHistoryReload((v) => v + 1)}
            >
              重试消息
            </Button>
          </p>
        ) : historyLoading ? (
          <p>正在加载消息…</p>
        ) : (
          <div className="thread" role="log" aria-label="对话历史">
            {messages.length ? (
              messages.map((m) => (
                <Message
                  key={m.id}
                  message={m}
                  showSourceId={
                    c.channel !== "public" &&
                    m.role === "user" &&
                    m.created_by === user.id &&
                    ["rag", "agent"].includes(m.source)
                  }
                />
              ))
            ) : (
              <p className="empty-state">
                输入问题，开始会话。答案、来源和工具结果将保存在这里。
              </p>
            )}
          </div>
        )}
        <Pager
          offset={historyOffset}
          count={messages.length}
          size={50}
          onChange={setHistoryOffset}
        />
        {newMessages && (
          <Button
            variant="secondary"
            onPress={() => {
              setHistoryOffset(0);
              setHistoryReload((v) => v + 1);
            }}
          >
            有新消息，查看最新
          </Button>
        )}
        <form className="composer" onSubmit={submit}>
          <textarea
            aria-label="消息内容"
            required
            maxLength={4000}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={
              human ? "输入人工答复…" : "咨询企业知识或使用已授权的只读工具…"
            }
          />
          <div className="composer-footer">
            <span className="run-state" aria-live="polite">
              {runState}
            </span>
            <Button
              variant="primary"
              className="primary"
              type="submit"
              isDisabled={busy || !canSend}
            >
              {busy ? "正在发送…" : human ? "发送人工答复" : "发送消息"}
            </Button>
          </div>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {preview && (
          <article className="message assistant" aria-live="polite">
            {preview}
          </article>
        )}
        {result?.error_category && (
          <p className="warning">{explain(result.error_category)}</p>
        )}
        {!!result?.executions?.length && (
          <details open>
            <summary>工具执行结果</summary>
            {result.executions.map((r: any, i: number) => (
              <div key={i}>
                <p>
                  {r.tool_name} · {r.status}
                </p>
                <pre>
                  {r.data
                    ? JSON.stringify(r.data, null, 2)
                    : explain(r.error_category)}
                </pre>
              </div>
            ))}
          </details>
        )}
        <section className="panel">
          <h3>最近运行</h3>
          {runsError ? (
            <p className="error">
              {runsError}
              <Button variant="secondary" onPress={readRuns}>
                重试
              </Button>
            </p>
          ) : !runs.length ? (
            <p>暂无运行记录。</p>
          ) : (
            runs.map((r) => (
              <details key={r.id}>
                <summary>
                  {date(r.created_at)} · {r.model} ·{" "}
                  {phases[r.phase] || r.phase}
                </summary>
                <p>
                  输入 Token：{r.input_tokens ?? "未知"} / 输出 Token：
                  {r.output_tokens ?? "未知"}；
                  {r.usage_complete ? "用量完整" : "可能不完整，不代表账单总量"}
                </p>
                {r.error_category && <p>{explain(r.error_category)}</p>}
                <pre>{JSON.stringify(r.steps, null, 2)}</pre>
              </details>
            ))
          )}
        </section>
      </section>
      <aside className="conversation-detail">
        <Operations
          key={initial.version}
          conversation={initial}
          operators={operators}
          refresh={refresh}
          stale={stale}
        />
      </aside>
    </>
  );
}
