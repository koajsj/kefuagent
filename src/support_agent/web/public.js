import { readEvents } from "./stream.js";
import { sessionState } from "./storage.js";
import {
  el,
  button,
  message,
  heading,
  label,
  textArea,
  actions,
  date,
} from "./ui.js";
import { requestIdentity, explain } from "./api.js";
const root = document.querySelector("#public-app"),
  pid = location.pathname.split("/").pop();
let info,
  session,
  busy = false,
  pending,
  offset = 0,
  poll;
const key = "support.visitor." + pid;
const feedback = el("div"),
  ratingArea = el("section", {class:"public-rating"}),
  thread = el("div", {
    class: "thread",
    role: "log",
    "aria-label": "会话消息",
  }),
  runs = el("div", { class: "note" }),
  body = textArea("content", "", {
    required: true,
    maxLength: 2000,
    rows: 3,
    placeholder: "请描述需要帮助的问题",
  });
const send = el("button", { type: "submit", class: "primary" }, "发送"),
  older = button("查看更早消息", () =>
    loadHistory(offset + 50).catch(showError),
  );
async function api(path = "", options = {}) {
  const response = await fetch("/api/v1/public/" + pid + path, {
    method: options.method || "GET",
    credentials: "omit",
    cache: "no-store",
    headers: {
      ...(session ? { Authorization: "Visitor " + session.token } : {}),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (response.ok && options.onEvent) return readEvents(response, options.onEvent);
  const result = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const err = new Error(
      explain(result?.error?.code) || "客服暂时不可用，请稍后再试。",
    );
    err.code = result?.error?.code;
    throw err;
  }
  return result;
}
function showError(error) {
  if (error.code === "visitor_authentication_required") {
    session = null;
    pending = null;
    sessionState.remove(key);
    render();
  }
  feedback.replaceChildren(
    message(
      error instanceof TypeError
        ? "连接中断，结果可能已保存。请先刷新消息；重试相同问题会复用请求标识。"
        : error.message,
      "error",
    ),
  );
}
function save() {
  sessionState.set(key, JSON.stringify({ session, pending }));
}
async function loadHistory(next = 0) {
  const rows = await api(
    `/sessions/${session.id}/messages?limit=50&offset=${next}`,
  );
  offset = next;
  thread.replaceChildren(
    ...rows.map((m) =>
      el(
        "article",
        { class: "message " + m.role },
        el(
          "div",
          { class: "message-label" },
          (m.role === "user" ? "您" : "客服") + " · " + date(m.created_at),
        ),
        el("div", {}, m.content),
        ...(m.tool_results || []).map((t) =>
          el(
            "details",
            {},
            el("summary", {}, t.name + " · " + t.status),
            el(
              "pre",
              {},
              JSON.stringify(t.data ?? { error: t.error_category }, null, 2),
            ),
          ),
        ),
        m.citations.length
          ? el(
              "div",
              { class: "citations" },
              ...m.citations.map((c, i) =>
                el(
                  "p",
                  {},
                  `[${i + 1}] ${c.document_name}${c.page ? " · 第 " + c.page + " 页" : ""}：${c.quote}`,
                ),
              ),
            )
          : null,
      ),
    ),
  );
  if (!rows.length) thread.append(message("请发送您的问题。"));
  older.disabled = rows.length < 50;
  if (next === 0) thread.scrollTop = thread.scrollHeight;
}
async function loadRating() {
  if (!session) return;
  const sid = session.id;
  const existing = await api(`/sessions/${sid}/feedback`);
  if (session?.id !== sid) return;
  const rating = el("select", {name:"rating", required:true}, el("option",{value:"satisfied", selected:existing?.rating === "satisfied"},"满意"), el("option",{value:"dissatisfied", selected:existing?.rating === "dissatisfied"},"不满意"));
  const comment = textArea("comment", existing?.comment || "", {maxLength:1000, rows:2, placeholder:"可选：告诉我们您的体验"});
  const result = el("div");
  const submit = el("button", {type:"submit"}, existing ? "更新评价" : "提交评价");
  const form = el("form", {}, label("服务评价", rating), label("评价内容（选填）", comment), submit, result);
  form.addEventListener("submit", async e => {
    e.preventDefault();
    if (submit.disabled || session?.id !== sid) return;
    submit.disabled = true;
    try {
      await api(`/sessions/${sid}/feedback`, {method:"POST", body:{rating:rating.value, comment:comment.value.trim() || null}});
      if (session?.id === sid) await loadRating();
    } catch (error) { if (session?.id === sid) result.replaceChildren(message(error.message,"error")); }
    finally { submit.disabled = false; }
  });
  ratingArea.replaceChildren(el("h2", {}, "服务评价"), existing ? el("p", {class:"note"}, "已评价 · " + date(existing.created_at)) : null, form);
}
async function runtime() {
  if (!session) return;
  const result = await api(`/sessions/${session.id}/status`);
  runs.textContent = result
    ? `${{ model_running: "模型请求中", retrieving: "检索知识中", tool_running: "只读工具执行中", completed: "已完成", failed: "调用失败" }[result.phase] || result.phase}${result.error_category ? " · " + result.error_category : ""}`
    : "";
}
async function start() {
  if (busy) return;
  busy = true;
  try {
    session = await api("/sessions", { method: "POST" });
    pending = null;
    body.value = "";
    save();
    render();
    await loadHistory();
    await loadRating();
  } finally {
    busy = false;
  }
}

function render() {
  const startButton = button(
    "开始会话",
    () => start().catch(showError),
    "primary",
  );
  const composer = el(
    "form",
    { class: "composer" },
    label("您的问题", body),
    actions(send),
  );
  composer.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy || !session) return;
    const content = body.value.trim();
    if (!content) return;
    busy = true;
    send.disabled = true;
    feedback.replaceChildren();
    try {
      pending = await requestIdentity({ content }, pending);
      save();
      const preview = el("article", { class: "message assistant", "aria-live": "polite" });
      feedback.append(preview);
      const result = await api(`/sessions/${session.id}/turns/stream`, {
        method: "POST",
        body: { content, idempotency_key: pending.key },
        onEvent(event, value) {
          if (event === "stage") runs.textContent = { pending: "等待执行", retrieving: "检索知识中", model_running: "模型请求中", tool_running: "只读工具执行中" }[value.phase] || value.phase;
          if (event === "delta") preview.textContent += value.text;
          if (event === "discard") preview.textContent = "";
        },
      });
      if (result.status !== "running") {
        pending = null;
        body.value = "";
        save();
      }
      feedback.replaceChildren(
        message(
          result.status === "failed"
            ? "回复失败：" + result.error_category
            : result.status === "running"
              ? "请求仍在执行。请稍后刷新消息或重试同一问题。"
              : result.status === "unresolved"
                ? "当前资料不足以确认，请补充问题或联系企业。"
                : "已收到客服回复。",
          result.status === "failed" ? "error" : "",
        ),
      );
      await loadHistory();
      await runtime();
      await loadRating();
    } catch (error) {
      showError(error);
    } finally {
      clearInterval(poll);
      busy = false;
      send.disabled = false;
    }
  });
  root.replaceChildren(
    heading(
      info.name,
      info.mode === "demo"
        ? "离线演示 · 确定性响应，未连接真实模型"
        : "在线客服 · 回答请结合引用来源核实",
    ),
    feedback,
    ...(session
      ? [
          actions(
            button("刷新消息", () => loadHistory().catch(showError)),
            older,
            button("最新消息", () => loadHistory(0).catch(showError)),
            button("重新开始", async () => {
              if (busy || !confirm("结束当前会话并重新开始？")) return;
              try {
                await api(`/sessions/${session.id}/end`, { method: "POST" });
                session = null;
                pending = null;
                sessionState.remove(key);
                await start();
              } catch (error) {
                showError(error);
              }
            }),
            button("结束会话", async () => {
              if (busy) return;
              try {
                await api(`/sessions/${session.id}/end`, { method: "POST" });
                session = null;
                pending = null;
                sessionState.remove(key);
                render();
              } catch (e) {
                showError(e);
              }
            }),
          ),
          thread,
          runs,
          composer,
          ratingArea,
        ]
      : [
          message(
            "开始后会创建独立访客会话。会话令牌仅保存在当前浏览器标签页，12 小时后失效。",
          ),
          startButton,
        ]),
    el("footer", {}, "请勿发送密码、API Key 或其他敏感凭证。"),
  );
}
try {
  if (!/^[0-9a-f-]{36}$/.test(pid)) throw new Error("客服链接无效。");
  info = await api();
  document.title = info.name + " · 在线客服";
  try {
    const stored = JSON.parse(sessionState.get(key) || "null");
    session = stored?.session;
    pending = stored?.pending;
    if (session && new Date(session.expires_at) <= new Date()) {
      session = null;
      pending = null;
      sessionState.remove(key);
    }
  } catch {
    session = null;
    pending = null;
  }
  render();
  if (session) {
    try {
      await loadHistory();
      await runtime();
      await loadRating();
    } catch (error) {
      if (
        ["visitor_authentication_required", "http_error"].includes(error.code)
      ) {
        session = null;
        pending = null;
        sessionState.remove(key);
        render();
      }
      showError(error);
    }
  }
} catch (error) {
  root.replaceChildren(
    heading("客服暂不可用", "入口可能尚未发布、已下线或配置已变更。"),
    message(error.message, "error"),
  );
}
window.addEventListener("pagehide", () => clearInterval(poll));
