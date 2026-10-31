import {
  el,
  button,
  label,
  input,
  select,
  message,
  empty,
  panel,
  actions,
  heading,
  table,
  date,
  check,
  form,
  collection,
} from "./ui.js";
export async function publicationsPage(ctx) {
  const [rows, agents, setup] = await Promise.all([
    collection(ctx.api, "/publications"),
    collection(ctx.api, "/agent-configs"),
    ctx.api("/setup-status"),
  ]);
  const editor = el("div"),
    feedback = el("div");
  const act = async (fn) => {
    try {
      await fn();
    } catch (e) {
      if (ctx.isCurrent() && !["StaleResponse", "AbortError"].includes(e.name))
        feedback.replaceChildren(message(e.message, "error"));
    }
  };
  async function create() {
    const agentSelect = select(
      "agent_config_id",
      agents.map((a) => ({ id: a.id, name: a.name + " · " + a.provider })),
    );
    const toolChoices = el("div");
    let options = [], choiceEpoch = 0;
    async function choose() {
      const ticket = ++choiceEpoch;
      options = [];
      toolChoices.replaceChildren();
      const [grants, tools] = await Promise.all([
        ctx.api(`/agent-configs/${agentSelect.value}/tools`),
        collection(ctx.api, "/tools"),
      ]);
      if (ticket !== choiceEpoch) return;
      options = tools
        .filter(
          (t) =>
            t.enabled &&
            t.execution_type === "read_only" &&
            t.risk_level === "low" &&
            !t.permissions.includes("tenant:admin") &&
            grants.some((g) => g.tool_id === t.id && g.enabled),
        )
        .map((t) => ({ id: t.id, ...check(t.name, false) }));
      toolChoices.replaceChildren(
        ...(options.length
          ? options.map((t) => t.node)
          : [empty("该 Agent 没有可公开的只读工具。")]),
      );
    }
    agentSelect.addEventListener("change", () => act(choose));
    if (agents.length) await choose();
    editor.replaceChildren(
      panel(
        "创建公开入口草稿",
        form(
          [
            label(
              "公开客服名称",
              input("name", "", { required: true, maxLength: 120 }),
            ),
            label("Agent", agentSelect),
            el(
              "fieldset",
              {},
              el("legend", {}, "允许公开访客使用的工具（默认无）"),
              toolChoices,
            ),
          ],
          async (v) => {
            await ctx.api("/publications", {
              method: "POST",
              body: {
                name: v.get("name"),
                agent_config_id: v.get("agent_config_id"),
                public_tool_ids: options
                  .filter((o) => o.box.checked)
                  .map((o) => o.id),
              },
            });
            await ctx.refresh();
          },
          "创建草稿",
        ),
      ),
    );
  }
  const links = el("div");
  function share(row) {
    if (!row.available || row.revoked_at || row.requires_republish) {
      links.replaceChildren(message("入口当前不可用，请检查状态并在需要时重新发布。", "warning"));
      return;
    }
    let origin;
    try {
      const parsed = new URL(setup.web_origin);
      const localHttp = parsed.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
      if ((!localHttp && parsed.protocol !== "https:") || parsed.username || parsed.password ||
          parsed.search || parsed.hash || !["", "/"].includes(parsed.pathname) ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(row.id))
        throw new Error();
      origin = parsed.origin;
    } catch {
      links.replaceChildren(message("服务器公开地址或入口标识无效，请联系部署管理员检查 WEB_ORIGIN。", "error"));
      return;
    }
    const url = `${origin}/chat/${row.id}`;
    const widget = `<script src="${origin}/widget.js" data-agent="${row.id}" defer></script>`;
    const notice = el("div");
    async function copy(value, field) {
      try {
        if (!navigator.clipboard?.writeText) throw new Error();
        await navigator.clipboard.writeText(value);
        notice.replaceChildren(message("已复制。"));
      } catch {
        field.focus();
        field.select();
        let copied = false;
        try { copied = document.execCommand("copy"); } catch { /* Select for manual copy. */ }
        notice.replaceChildren(message(copied ? "已复制。" : "无法自动复制，内容已选中，请手动复制。", copied ? "" : "warning"));
      }
    }
    const linkField = input("", url, { readOnly: true });
    const scriptField = el("textarea", { value: widget, readOnly: true, rows: 3 });
    links.replaceChildren(panel("分享与嵌入",
      el("p", {}, "配置或授权变更可能要求重新发布；重新发布会使旧访客会话失效。"),
      label("公开链接", linkField),
      actions(button("复制公开链接", () => copy(url, linkField)),
        el("a", { href: url, target: "_blank", rel: "noopener" }, "在独立窗口打开客服")),
      label("网站嵌入代码", scriptField),
      button("复制嵌入代码", () => copy(widget, scriptField)),
      notice,
      el("p", { class: "note" }, "HTML：将脚本放在页面结束标签前。Vue / React：在应用入口 HTML 中添加脚本，避免重复加载。WordPress：使用允许脚本的主题或插件区域。宿主网站的 CSP 需允许本服务域名的 script-src 与 frame-src。"),
      el("p", { class: "note" }, "脚本加载受限访客页面，不包含 API Key 或管理令牌。"),
    ));
  }

  const listing = el("div");
  function renderRows() {
    listing.replaceChildren(
    rows.length
      ? table(
          ["名称 / Agent 版本", "状态 / 发布版本", "操作"],
          rows.map((r) => [
            r.name + " · Agent v" + r.agent_version,
            r.revoked_at
              ? "已撤销"
              : (r.available
                  ? "公开可用"
                  : r.requires_republish
                    ? "配置变更，需重新发布"
                    : r.enabled
                      ? "关联 Agent 或发布者已停用"
                      : "草稿 / 已下线") +
                " · v" +
                r.version,
            actions(
              r.available && !r.revoked_at && !r.requires_republish
                ? button("链接与嵌入", () => share(r))
                : null,
              !r.revoked_at
                ? button(r.enabled ? "重新发布" : "发布", () =>
                    act(async () => {
                      const saved = await ctx.api(`/publications/${r.id}`, {
                        method: "PATCH",
                        body: { enabled: true, expected_version: r.version },
                      });
                      Object.assign(r, saved);
                      renderRows();
                      share(saved);
                    }),
                  )
                : null,
              r.enabled
                ? button("下线", () =>
                    act(async () => {
                      await ctx.api(`/publications/${r.id}`, {
                        method: "PATCH",
                        body: { enabled: false, expected_version: r.version },
                      });
                      await ctx.refresh();
                    }),
                  )
                : null,
              !r.revoked_at
                ? button(
                    "撤销入口",
                    () =>
                      act(async () => {
                        if (!confirm("撤销不可恢复，链接将失效。确认？"))
                          return;
                        await ctx.api(`/publications/${r.id}`, {
                          method: "DELETE",
                        });
                        await ctx.refresh();
                      }),
                    "danger",
                  )
                : null,
            ),
          ]),
        )
      : empty("还没有公开入口。"),
    );
  }
  renderRows();

  return el(
    "div",
    {},
    heading(
      "公开客服入口",
      "草稿创建后手动发布；修改 Agent 后必须重新发布。访客不会获得管理权限。",
      button("创建入口", () => act(create), "primary"),
    ),
    feedback,
    editor,
    listing,
    links,
  );
}
