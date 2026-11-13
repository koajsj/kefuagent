import { CustomerContext } from "./CustomerContext";
import { Button } from "@heroui/react";
import { useEffect, useState, useRef } from "react";
import { useApp } from "../../app/context";
import type { Row } from "../../types";
import { date, errorText } from "./shared";
export function Operations({
  conversation: c,
  operators,
  refresh,
  stale,
}: {
  conversation: Row;
  operators: Row[] | null;
  refresh: () => Promise<void>;
  stale: boolean;
}) {
  const { api, role, user } = useApp();
  const [notes, setNotes] = useState<Row[]>([]),
    [summary, setSummary] = useState<Row | null>(null),
    [error, setError] = useState(""),
    [more, setMore] = useState(true),
    [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false),
    [notesError, setNotesError] = useState(""),
    [summaryError, setSummaryError] = useState(""),
    [summaryLoaded, setSummaryLoaded] = useState(false);
  const lifetime = useRef(new AbortController()),
    notesInFlight = useRef(false);
  const [notesLoading, setNotesLoading] = useState(false);
  const editable =
    !stale &&
    (role === "admin" || c.assignee_id === user.id) &&
    (role !== "admin" || operators !== null);
  async function load(initial = false) {
    if (notesInFlight.current) return;
    notesInFlight.current = true;
    setNotesLoading(true);
    setNotesError("");
    try {
      const rows = await api.request<Row[]>(
        `/conversations/${c.id}/collaboration?limit=30${!initial && notes.length ? "&before=" + encodeURIComponent(notes.at(-1)!.id) : ""}`,
        { signal: lifetime.current.signal },
      );
      if (lifetime.current.signal.aborted) return;
      setNotes((old) =>
        initial
          ? rows
          : [...old, ...rows.filter((r) => !old.some((n) => n.id === r.id))],
      );
      setMore(rows.length === 30);
      setLoaded(true);
    } catch (e) {
      if (!lifetime.current.signal.aborted) setNotesError(errorText(e));
    } finally {
      notesInFlight.current = false;
      if (!lifetime.current.signal.aborted) setNotesLoading(false);
    }
  }
  async function loadSummary(signal?: AbortSignal) {
    signal ||= lifetime.current.signal;
    setSummaryError("");
    try {
      const result = await api.request<Row | null>(
        `/conversations/${c.id}/summary`,
        { signal },
      );
      if (!signal?.aborted) {
        setSummary(result);
        setSummaryLoaded(true);
      }
    } catch (e) {
      if (!signal?.aborted) setSummaryError(errorText(e));
    }
  }
  useEffect(() => {
    const ctrl = new AbortController();
    lifetime.current = ctrl;
    load(true);
    loadSummary(ctrl.signal);
    return () => ctrl.abort();
  }, [c.id, api]);
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api.request(`/conversations/${c.id}/operations`, {
        method: "PATCH",
        body: {
          expected_version: c.version,
          priority: f.get("priority"),
          tags: String(f.get("tags"))
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          category: String(f.get("category")).trim() || null,
          ...(role === "admin"
            ? { assignee_id: f.get("assignee_id") || null }
            : {}),
        },
      });
      await refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function note(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    setError("");
    try {
      await api.request(`/conversations/${c.id}/collaboration`, {
        method: "POST",
        body: { content: new FormData(form).get("content") },
      });
      form.reset();
      await load(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  let quotes: any[] = [];
  let invalidSummary = false;
  try {
    quotes = summary ? JSON.parse(summary.content) : [];
    if (!Array.isArray(quotes)) invalidSummary = true;
  } catch {
    invalidSummary = true;
  }
  return (
    <div className="operations">
      <CustomerContext conversation={c} refresh={refresh} disabled={stale} />
      {stale && (
        <p className="warning">
          会话已更新，草稿已保留。重新打开会话后可保存运营信息。
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
          <Button variant="secondary" onPress={() => load(true)}>
            重试加载记录
          </Button>
        </p>
      )}
      <section className="panel">
        <h3>运营信息</h3>
        <p className="note">
          SLA：{c.sla?.state || "未知"} · 首次响应{" "}
          {c.sla?.first_response_seconds ?? "未知"} 秒 · 人工等待{" "}
          {c.sla?.human_wait_seconds ?? "未知"} 秒 · 解决{" "}
          {c.sla?.resolution_seconds ?? "未知"} 秒
        </p>
        <form onSubmit={save}>
          <fieldset disabled={!editable || busy}>
            {role === "admin" && (
              <label>
                负责人
                <select name="assignee_id" defaultValue={c.assignee_id || ""}>
                  <option value="">未分配</option>
                  {operators?.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              优先级
              <select name="priority" defaultValue={c.priority || "normal"}>
                {["low", "normal", "high", "urgent"].map((p, i) => (
                  <option key={p} value={p}>
                    {["低", "普通", "高", "紧急"][i]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              标签（逗号分隔）
              <input name="tags" defaultValue={(c.tags || []).join(", ")} />
            </label>
            <label>
              分类
              <input name="category" defaultValue={c.category || ""} />
            </label>
            <Button
              variant="secondary"
              type="submit"
              isDisabled={!editable || busy}
            >
              保存运营信息
            </Button>
          </fieldset>
        </form>
        {!editable && (
          <p className="note">
            仅负责人或管理员可编辑；管理员还需成功加载负责人列表。
          </p>
        )}
      </section>
      <section className="panel">
        <h3>协作记录</h3>
        {notesError ? (
          <p className="error" role="alert">
            {notesError}
            <Button variant="secondary" onPress={() => load(true)}>
              重试加载协作记录
            </Button>
          </p>
        ) : !loaded ? (
          <p>正在加载协作记录…</p>
        ) : !notes.length ? (
          <p className="empty-state">暂无协作记录。</p>
        ) : (
          notes.map((n) => (
            <article key={n.id} className="collaboration-entry">
              <strong>{n.kind}</strong>
              <small>
                {" "}
                · {date(n.created_at)} ·{" "}
                {operators?.find((o) => o.id === n.actor_id)?.display_name ||
                  n.actor_id}
              </small>
              <p>{n.content}</p>
              {n.details && Object.keys(n.details).length > 0 && (
                <pre>{JSON.stringify(n.details, null, 2)}</pre>
              )}
            </article>
          ))
        )}
        {more && (
          <Button
            variant="secondary"
            isDisabled={busy || notesLoading}
            onPress={() => load()}
          >
            加载更早记录
          </Button>
        )}
        <form onSubmit={note}>
          <label>
            内部备注
            <textarea name="content" required maxLength={4000} rows={3} />
          </label>
          <Button
            variant="secondary"
            type="submit"
            isDisabled={busy || notesLoading}
          >
            添加内部备注
          </Button>
        </form>
      </section>
      <section className="panel">
        <h3>会话摘要（只读）</h3>
        {summaryError ? (
          <p className="error" role="alert">
            {summaryError}
            <Button variant="secondary" onPress={() => loadSummary()}>
              重试加载摘要
            </Button>
          </p>
        ) : !summaryLoaded ? (
          <p>正在加载摘要…</p>
        ) : invalidSummary ? (
          <p className="error">
            摘要格式异常，无法显示。
            <Button variant="secondary" onPress={() => loadSummary()}>
              重新加载摘要
            </Button>
          </p>
        ) : summary ? (
          <>
            <ul>
              {quotes.map((q, i) => (
                <li key={i}>{q.quote}</li>
              ))}
            </ul>
            <small>
              来源：{summary.source_start_id} 至 {summary.source_end_id} · 版本{" "}
              {summary.version} · {summary.source_count} 条来源消息 ·{" "}
              {date(summary.created_at)}
            </small>
          </>
        ) : (
          <p className="empty-state">尚无摘要。</p>
        )}
      </section>
    </div>
  );
}
