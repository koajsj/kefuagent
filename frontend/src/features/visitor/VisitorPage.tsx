import { Button } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import { adapter } from "../../adapters";
import { requestIdentity } from "../../adapters/identity";
import { sessionState } from "../../adapters/storage";
import { explain } from "../../adapters/errors";
import type { RequestOptions, Row } from "../../types";
import { Message, Pager, date, errorText, phases } from "../chat/shared";
export function VisitorPage({ publicationId }: { publicationId: string }) {
  return <Visitor key={publicationId} publicationId={publicationId} />;
}
function Visitor({ publicationId: pid }: { publicationId: string }) {
  const key = "support.visitor." + pid;
  const stored = useRef<any>(
    (() => {
      try {
        const value = JSON.parse(sessionState.get(key) || "null");
        return value?.session && new Date(value.session.expires_at) > new Date()
          ? value
          : null;
      } catch {
        return null;
      }
    })(),
  );
  const [info, setInfo] = useState<Row | null>(null),
    [session, setSession] = useState<Row | null>(
      stored.current?.session || null,
    ),
    [messages, setMessages] = useState<Row[]>([]),
    [offset, setOffset] = useState(0),
    [historyReload, setHistoryReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [feedback, setFeedback] = useState(""),
    [busy, setBusy] = useState(false),
    [closed, setClosed] = useState(false),
    [content, setContent] = useState(""),
    [preview, setPreview] = useState(""),
    [phase, setPhase] = useState(""),
    [newMessages, setNewMessages] = useState(false),
    [rating, setRating] = useState<Row | null>(null),
    [ratingValue, setRatingValue] = useState("satisfied"),
    [comment, setComment] = useState(""),
    [ratingError, setRatingError] = useState(""),
    [ratingBusy, setRatingBusy] = useState(false),
    [ratingLoaded, setRatingLoaded] = useState(false),
    [fatal, setFatal] = useState(false);
  const sessionRef = useRef(session),
    pending = useRef<any>(stored.current?.pending || null),
    life = useRef(new AbortController()),
    latest = useRef<string | null>(null),
    historyEpoch = useRef(0),
    current = useRef({ offset, busy, closed });
  sessionRef.current = session;
  current.current = { offset, busy, closed };
  function save(next: Row | null, p = pending.current) {
    if (next)
      sessionState.set(key, JSON.stringify({ session: next, pending: p }));
    else sessionState.remove(key);
  }
  function reset() {
    sessionRef.current = null;
    setSession(null);
    pending.current = null;
    sessionState.remove(key);
    latest.current = null;
    setMessages([]);
    setClosed(false);
    setRating(null);
    setRatingLoaded(false);
    setPreview("");
  }
  function fail(e: any) {
    if (["AbortError", "StaleResponse"].includes(e.name)) return;
    if (
      [
        "visitor_authentication_required",
        "visitor_access_revoked",
        "publication_revoked",
      ].includes(e.code) ||
      [401, 403, 404, 410].includes(e.status)
    ) {
      reset();
      if (e.code !== "visitor_authentication_required") setFatal(true);
    }
    setError(errorText(e));
  }
  async function api<T = any>(path = "", options: RequestOptions = {}) {
    const requestSession = sessionRef.current;
    const value = await adapter.request<T>(`/public/${pid}${path}`, {
      ...options,
      signal: options.signal || life.current.signal,
      visitorToken: requestSession?.token,
      onHeaders: (headers) => {
        options.onHeaders?.(headers);
        if (
          sessionRef.current === requestSession &&
          headers.get("X-Conversation-Status") === "closed"
        )
          current.current.closed = true;
      },
      onEvent: options.onEvent
        ? (event, value) => {
            if (
              sessionRef.current === requestSession &&
              !life.current.signal.aborted
            )
              options.onEvent!(event, value);
          }
        : undefined,
    });
    if (sessionRef.current !== requestSession)
      throw Object.assign(new Error("会话已切换"), { name: "StaleResponse" });
    return value;
  }
  useEffect(() => {
    life.current = new AbortController();
    if (!/^[0-9a-f-]{36}$/i.test(pid)) {
      setError("客服链接无效。");
      setLoading(false);
      setFatal(true);
      return;
    }
    api<Row>()
      .then((value) => {
        if (life.current.signal.aborted) return;
        setInfo(value);
        document.title = value.name + " · 在线客服";
        setLoading(false);
      })
      .catch((e) => {
        if (!life.current.signal.aborted) {
          setLoading(false);
          setFatal(true);
          fail(e);
        }
      });
    return () => life.current.abort();
  }, [pid]);
  async function loadRating() {
    const sid = sessionRef.current?.id;
    if (!sid) return;
    setRatingError("");
    try {
      const r = await api<Row | null>(`/sessions/${sid}/feedback`);
      setRating(r);
      setRatingValue(r?.rating || "satisfied");
      setComment(r?.comment || "");
      setRatingLoaded(true);
    } catch (e) {
      if (!life.current.signal.aborted) setRatingError(errorText(e));
    }
  }
  async function runtime() {
    const sid = sessionRef.current?.id;
    if (!sid) return;
    try {
      const r = await api<Row | null>(`/sessions/${sid}/status`);
      setPhase(
        r
          ? `${phases[r.phase] || r.phase}${r.error_category ? " · " + explain(r.error_category) : ""}`
          : "",
      );
    } catch (e) {
      fail(e);
    }
  }
  useEffect(() => {
    if (!session || !info) return;
    loadRating();
    runtime();
  }, [session?.id, info]);
  useEffect(() => {
    if (!session || !info) return;
    const ctrl = new AbortController();
    const ticket = ++historyEpoch.current;
    setLoading(true);
    api<Row[]>(`/sessions/${session.id}/messages?limit=50&offset=${offset}`, {
      signal: ctrl.signal,
    })
      .then((rows) => {
        if (ticket !== historyEpoch.current || ctrl.signal.aborted) return;
        setMessages(rows);
        if (current.current.closed) setClosed(true);
        if (!offset) {
          latest.current = rows.at(-1)?.id || null;
          setNewMessages(false);
        }
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) fail(e);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [session?.id, info, offset, historyReload]);
  useEffect(() => {
    if (!session || !info || closed) return;
    let stopped = false,
      paused = false,
      failures = 0,
      timer: ReturnType<typeof setTimeout>,
      ctrl: AbortController | undefined,
      inFlight = false;
    const active = () =>
      !stopped &&
      !paused &&
      !document.hidden &&
      sessionRef.current?.id === session.id &&
      !current.current.closed;
    const schedule = (delay = 5000) => {
      clearTimeout(timer);
      if (active()) timer = setTimeout(poll, delay);
    };
    async function poll() {
      if (!active() || inFlight) return;
      inFlight = true;
      const request = new AbortController();
      ctrl = request;
      try {
        if (!current.current.busy) {
          const anchor = latest.current,
            ticket = historyEpoch.current;
          const rows = await api<Row[]>(
            `/sessions/${session!.id}/messages?${anchor ? "limit=100&after=" + encodeURIComponent(anchor) : "limit=50&offset=0"}`,
            { signal: request.signal },
          );
          if (
            request.signal.aborted ||
            sessionRef.current?.id !== session!.id ||
            ticket !== historyEpoch.current ||
            stopped ||
            paused ||
            document.hidden
          )
            return;
          if (rows.length) {
            latest.current = rows.at(-1)!.id;
            if (current.current.offset === 0)
              setMessages((old) =>
                anchor
                  ? [
                      ...old,
                      ...rows.filter((r) => !old.some((o) => o.id === r.id)),
                    ]
                  : rows,
              );
            else setNewMessages(true);
          }
        }
        if (current.current.closed) setClosed(true);
        failures = 0;
      } catch (e: any) {
        if (!request.signal.aborted) {
          if (
            [
              "visitor_authentication_required",
              "conversation_closed",
              "publication_revoked",
              "visitor_access_revoked",
            ].includes(e.code) ||
            [401, 403, 404, 410].includes(e.status)
          ) {
            stopped = true;
            fail(e);
          } else failures = Math.min(4, failures + 1);
        }
      } finally {
        inFlight = false;
        schedule(Math.min(60000, 5000 * 2 ** failures));
      }
    }
    const hide = () => {
      clearTimeout(timer);
      ctrl?.abort();
    };
    const visible = () => {
      if (document.hidden) hide();
      else {
        setHistoryReload((v) => v + 1);
        schedule();
      }
    };
    const pagehide = () => {
      paused = true;
      hide();
    };
    const pageshow = () => {
      paused = false;
      setHistoryReload((v) => v + 1);
      schedule();
    };
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("pagehide", pagehide);
    window.addEventListener("pageshow", pageshow);
    schedule();
    return () => {
      stopped = true;
      hide();
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("pagehide", pagehide);
      window.removeEventListener("pageshow", pageshow);
    };
  }, [session?.id, info, closed]);
  async function start() {
    if (busy || fatal) return;
    setBusy(true);
    setError("");
    try {
      const next = await api<Row>("/sessions", { method: "POST" });
      pending.current = null;
      sessionRef.current = next;
      setSession(next);
      setContent("");
      setOffset(0);
      setClosed(false);
      setFeedback("");
      setPreview("");
      save(next, null);
    } catch (e) {
      fail(e);
    } finally {
      if (!life.current.signal.aborted) setBusy(false);
    }
  }
  async function end(restart = false) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/sessions/${sessionRef.current!.id}/end`, { method: "POST" });
      reset();
      setContent("");
      if (restart) {
        const next = await api<Row>("/sessions", { method: "POST" });
        sessionRef.current = next;
        setSession(next);
        setOffset(0);
        save(next, null);
      }
    } catch (e) {
      fail(e);
    } finally {
      if (!life.current.signal.aborted) setBusy(false);
    }
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !session || closed || !content.trim()) return;
    const submitted = content.trim();
    setBusy(true);
    setError("");
    setFeedback("");
    setPreview("");
    try {
      pending.current = await requestIdentity(
        { content: submitted },
        pending.current,
      );
      if (life.current.signal.aborted) return;
      save(session);
      const result = await api<any>(`/sessions/${session.id}/turns/stream`, {
        method: "POST",
        body: { content: submitted, idempotency_key: pending.current.key },
        onEvent: (event, value) => {
          if (event === "stage") setPhase(phases[value.phase] || value.phase);
          if (event === "delta") setPreview((old) => old + value.text);
          if (event === "discard") setPreview("");
        },
      });
      if (result.status !== "running") {
        pending.current = null;
        save(session, null);
        setContent((old) => (old.trim() === submitted ? "" : old));
        setPreview("");
      }
      setFeedback(
        result.status === "failed"
          ? "回复失败：" + explain(result.error_category)
          : result.status === "running"
            ? "请求仍在执行。请稍后刷新消息或重试相同问题。"
            : result.status === "unresolved"
              ? "资料不足以确认，请补充问题或联系企业。"
              : "已收到客服回复。",
      );
      setOffset(0);
      setHistoryReload((v) => v + 1);
      await runtime();
    } catch (e) {
      fail(e);
    } finally {
      if (!life.current.signal.aborted) setBusy(false);
    }
  }
  async function rate(e: React.FormEvent) {
    e.preventDefault();
    if (ratingBusy || !session) return;
    setRatingBusy(true);
    setRatingError("");
    try {
      await api(`/sessions/${session.id}/feedback`, {
        method: "POST",
        body: { rating: ratingValue, comment: comment.trim() || null },
      });
      await loadRating();
    } catch (e) {
      setRatingError(errorText(e));
    } finally {
      if (!life.current.signal.aborted) setRatingBusy(false);
    }
  }
  return (
    <main
      className={`visitor-shell${window.parent !== window ? " visitor-shell--embedded" : ""}`}
    >
      <header className="visitor-header">
        <div className="brand-mark" aria-hidden="true">
          S
        </div>
        <h1>{info?.name || "在线客服"}</h1>
        <p>
          {info?.mode === "demo" || adapter.mode === "demo"
            ? "离线演示 · 确定性响应，未连接真实模型"
            : "在线客服 · 回答请结合引用来源核实"}
        </p>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!info && !fatal ? (
        <p>正在加载客服入口…</p>
      ) : fatal ? (
        <section className="panel">
          <h2>客服暂不可用</h2>
          <p>入口可能尚未发布、已下线或配置已变更。</p>
        </section>
      ) : !session ? (
        <section className="panel">
          <p>
            开始后会创建独立访客会话。令牌仅保存在当前浏览器标签页，有效期由企业入口设置。
          </p>
          <Button
            variant="primary"
            className="primary"
            isDisabled={busy}
            onPress={start}
          >
            {busy ? "正在创建…" : "开始会话"}
          </Button>
        </section>
      ) : (
        <>
          <p className="note">
            本次会话令牌有效至 {date(session.expires_at)}。
          </p>
          <div className="visitor-actions actions">
            <Button
              variant="secondary"
              isDisabled={busy}
              onPress={() => {
                setOffset(0);
                setHistoryReload((v) => v + 1);
              }}
            >
              刷新消息
            </Button>
            <Button
              variant="secondary"
              isDisabled={busy}
              onPress={() => end(true)}
            >
              重新开始
            </Button>
            <Button variant="secondary" isDisabled={busy} onPress={() => end()}>
              结束会话
            </Button>
          </div>
          {loading ? (
            <p>正在加载消息…</p>
          ) : (
            <div className="thread" role="log" aria-label="会话消息">
              {messages.length ? (
                messages.map((m) => <Message key={m.id} message={m} visitor />)
              ) : (
                <p className="empty-state">您好，请描述您需要帮助的问题。</p>
              )}
            </div>
          )}
          <Pager
            offset={offset}
            count={messages.length}
            size={50}
            onChange={setOffset}
          />
          {newMessages && (
            <Button
              variant="secondary"
              onPress={() => {
                setOffset(0);
                setHistoryReload((v) => v + 1);
              }}
            >
              有新消息，查看最新
            </Button>
          )}
          {closed && <p className="note">会话已结束，可查看历史或重新开始。</p>}
          <form className="composer" onSubmit={submit}>
            <label>
              您的问题
              <textarea
                required
                maxLength={2000}
                rows={3}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                disabled={closed}
                placeholder="请描述需要帮助的问题"
              />
            </label>
            <div className="composer-footer">
              <span aria-live="polite" className="run-state">
                {phase}
              </span>
              <Button
                variant="primary"
                className="primary"
                type="submit"
                isDisabled={busy || closed}
              >
                {busy ? "正在发送…" : "发送"}
              </Button>
            </div>
          </form>
          {preview && (
            <article className="message assistant" aria-live="polite">
              {preview}
            </article>
          )}
          {feedback && <p role="status">{feedback}</p>}
          <details className="public-rating panel">
            <summary>服务评价</summary>
            {ratingError ? (
              <p className="error">
                {ratingError}
                <Button variant="secondary" onPress={loadRating}>
                  重试加载评价
                </Button>
              </p>
            ) : !ratingLoaded ? (
              <p>正在加载评价…</p>
            ) : (
              <>
                <p className="note">
                  {rating
                    ? "已评价 · " + date(rating.created_at)
                    : "您的反馈会帮助企业改善服务。"}
                </p>
                <form onSubmit={rate}>
                  <label>
                    服务评价
                    <select
                      value={ratingValue}
                      onChange={(e) => setRatingValue(e.target.value)}
                      required
                    >
                      <option value="satisfied">满意</option>
                      <option value="dissatisfied">不满意</option>
                    </select>
                  </label>
                  <label>
                    评价内容（选填）
                    <textarea
                      maxLength={1000}
                      rows={2}
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                    />
                  </label>
                  <Button
                    variant="secondary"
                    type="submit"
                    isDisabled={ratingBusy}
                  >
                    {rating ? "更新评价" : "提交评价"}
                  </Button>
                </form>
              </>
            )}
          </details>
        </>
      )}
      <footer>请勿发送密码、API Key 或其他敏感凭证。</footer>
    </main>
  );
}
