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
  const [rows, agents] = await Promise.all([
    collection(ctx.api, "/publications"),
    collection(ctx.api, "/agent-configs"),
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
    let options = [];
    async function choose() {
      const [grants, tools] = await Promise.all([
        ctx.api(`/agent-configs/${agentSelect.value}/tools`),
        collection(ctx.api, "/tools"),
      ]);
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
    const url = new URL("/chat/" + row.id, location.origin).href;
    const widget = `<script src="${location.origin}/widget.js" data-agent="${row.id}" defer></script>`;
    links.replaceChildren(
      panel(
        "分享与嵌入",
        el(
          "p",
          {},
          "发布后才可访问。配置或授权变更可能要求重新发布；重新发布会使旧访客会话失效。",
        ),
        label("公开链接", input("", url, { readOnly: true })),
        el(
          "a",
          { href: url, target: "_blank", rel: "noopener" },
          "在独立窗口打开客服",
        ),
        label(
          "网站嵌入代码",
          el("textarea", { value: widget, readOnly: true, rows: 3 }),
        ),
        el(
          "p",
          { class: "note" },
          "脚本只加载受限访客页面，无 API Key 和管理令牌。宿主网站需允许本服务域名的 script-src 与 frame-src。",
        ),
      ),
    );
  }
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
              button("链接与嵌入", () => share(r)),
              !r.revoked_at
                ? button(r.enabled ? "重新发布" : "发布", () =>
                    act(async () => {
                      await ctx.api(`/publications/${r.id}`, {
                        method: "PATCH",
                        body: { enabled: true, expected_version: r.version },
                      });
                      await ctx.refresh();
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
    links,
  );
}
