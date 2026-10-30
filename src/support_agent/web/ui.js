export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (key.startsWith("on"))
      node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key in node && !key.startsWith("aria-")) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined)
      node.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  }
  return node;
}
export const button = (text, action, cls = "") =>
  el("button", { type: "button", class: cls, onClick: action }, text);
export const label = (text, input) => el("label", {}, text, input);
export const input = (name, value = "", attrs = {}) =>
  el("input", { name, value, ...attrs });
export const textArea = (name, value = "", attrs = {}) =>
  el("textarea", { name, value, ...attrs });
export function select(name, items, value = "", attrs = {}) {
  return el(
    "select",
    { name, ...attrs },
    items.map((item) =>
      el(
        "option",
        { value: item.id, selected: String(item.id) === String(value) },
        item.name,
      ),
    ),
  );
}
export const message = (text, kind = "") =>
  el(
    "div",
    { class: "notice " + kind, role: kind === "error" ? "alert" : "status" },
    text,
  );
export const empty = (text) => el("div", { class: "empty" }, text);
export const panel = (title, ...content) =>
  el(
    "section",
    { class: "panel" },
    title ? el("h2", {}, title) : null,
    ...content,
  );
export const actions = (...items) => el("div", { class: "actions" }, ...items);
export function heading(title, subtitle, ...controls) {
  return el(
    "header",
    { class: "page-head" },
    el("div", {}, el("h1", {}, title), el("p", {}, subtitle)),
    actions(...controls),
  );
}
export function table(headers, rows) {
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "data-table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          headers.map((h) => el("th", { scope: "col" }, h)),
        ),
      ),
      el(
        "tbody",
        {},
        rows.map((row) =>
          el(
            "tr",
            {},
            row.map((cell) => el("td", {}, cell)),
          ),
        ),
      ),
    ),
  );
}
export const date = (value) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export const number = (value) =>
  value === null || value === undefined
    ? "未知"
    : Number(value).toLocaleString("zh-CN");
export const json = (value) => el("pre", {}, JSON.stringify(value, null, 2));
export function status(value) {
  const names = {
    active: "启用",
    inactive: "停用",
    ready: "已就绪",
    failed: "失败",
    deleting: "待清理",
    processing: "处理中",
    pending: "等待中",
    open: "进行中",
    closed: "已结束",
    ai: "AI 处理中",
    waiting: "待人工",
    human: "人工处理中",
    resolved: "已解决",
    answered: "已回复",
    unresolved: "待补充/无法确认",
    running: "执行中",
    connected: "连接成功",
    succeeded: "执行成功",
    denied: "已拒绝",
    timed_out: "超时",
    demo: "离线演示",
    success: "成功",
    failure: "失败",
    rejected: "已拒绝",
  };
  return el(
    "span",
    {
      class:
        "tag " +
        (["failed", "denied", "timed_out", "failure"].includes(value)
          ? "error"
          : ""),
    },
    names[value] || value,
  );
}
export function check(text, checked = false) {
  const box = input("", "", { type: "checkbox", checked });
  return { node: el("label", { class: "checkbox" }, box, text), box };
}
export function form(children, submit, submitText = "保存") {
  const error = el("div");
  const submitButton = el(
    "button",
    { type: "submit", class: "primary" },
    submitText,
  );
  const node = el("form", {}, ...children, error, submitButton);
  node.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitButton.disabled) return;
    error.replaceChildren();
    submitButton.disabled = true;
    try {
      await submit(new FormData(node));
    } catch (err) {
      if (err.name !== "AbortError" && err.name !== "StaleResponse")
        error.append(message(err.message, "error"));
    } finally {
      submitButton.disabled = false;
    }
  });
  return node;
}
export function pager(offset, count, limit, onPage) {
  return el(
    "div",
    { class: "pager" },
    el(
      "button",
      {
        type: "button",
        disabled: offset === 0,
        onClick: () => onPage(Math.max(0, offset - limit)),
      },
      "上一页",
    ),
    el(
      "span",
      { class: "note" },
      count ? `${offset + 1}–${offset + count} 条` : "本页暂无记录",
    ),
    el(
      "button",
      {
        type: "button",
        disabled: count < limit,
        onClick: () => onPage(offset + limit),
      },
      "下一页",
    ),
  );
}
export async function collection(api, path, cap = 500) {
  const items = [];
  for (let offset = 0; offset < cap; offset += 100) {
    const page = await api(
      `${path}${path.includes("?") ? "&" : "?"}limit=100&offset=${offset}`,
    );
    items.push(...page);
    if (page.length < 100) return items;
  }
  throw new Error(
    "选项超过 500 条，请通过 API 分页管理，工作台未截断后代为保存。",
  );
}
