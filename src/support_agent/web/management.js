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
  number,
  json,
  status,
  form,
  collection,
  pager,
} from "./ui.js";
const guard = async (ctx, fn) => {
  try {
    await fn();
  } catch (e) {
    if (ctx.isCurrent() && !["StaleResponse", "AbortError"].includes(e.name))
      ctx.notify(e.message);
  }
};
export async function dashboardPage(ctx) {
  const output = el("div");
  const start = input("start", "", {type:"date", required:true});
  const end = input("end", "", {type:"date", required:true});
  const notice = el("div");
  let epoch = 0;
  const utcDay = d => d.toISOString().slice(0, 10);
  function preset(days) {
    const today = new Date();
    const boundary = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() + 1));
    end.value = utcDay(boundary);
    start.value = utcDay(new Date(boundary.getTime() - days * 86400000));
    guard(ctx, load);
  }
  async function load() {
    const ticket = ++epoch;
    output.replaceChildren();
    const from = new Date(start.value + "T00:00:00Z"), to = new Date(end.value + "T00:00:00Z");
    if (!start.value || !end.value || !Number.isFinite(from.getTime()) || !Number.isFinite(to.getTime()) || to <= from || to - from > 90 * 86400000) {
      notice.replaceChildren(message("请选择不超过 90 天的有效 UTC 区间，结束日期不包含在内。", "error"));
      return;
    }
    notice.replaceChildren(el("p", {class:"loading", role:"status"}, "正在加载运营数据…"));
    let s;
    try {
      s = await ctx.api(`/workspace/analytics?${new URLSearchParams({start:from.toISOString(),end:to.toISOString()})}`);
    } catch (error) {
      if (ctx.isCurrent() && ticket === epoch && !["StaleResponse", "AbortError"].includes(error.name))
        notice.replaceChildren(message(error.message, "error"));
      return;
    }
    if (!ctx.isCurrent() || ticket !== epoch) return;
    notice.replaceChildren();
    const pct = n => n == null ? "未知" : `${(n * 100).toFixed(1)}%`;
    const seconds = n => n == null ? "未知" : `${Math.round(n)} 秒`;
    const c = s.conversations, ai = s.ai, u = s.usage, f = s.feedback;
    output.replaceChildren(
      el("div", {class:"kpi-row"}, ...[["会话",c.total],["待处理",c.pending],["已解决",c.resolved],["超时",c.overdue],["调用",u.calls],["失败调用",u.failed]].map(([name,n]) => panel(name, el("strong",{class:"kpi"},number(n))))),
      panel("服务与 AI", el("p",{}, `平均首次响应 ${seconds(c.avg_first_response_seconds)} · 平均解决 ${seconds(c.avg_resolution_seconds)} · 转人工率 ${pct(c.handoff_rate)}`), el("p",{}, `AI 解决 ${number(c.ai_resolved)} · 转人工 ${number(c.ai_to_human)} · 未解决 ${number(c.ai_unresolved)}`), el("p",{}, `检索使用率 ${pct(ai.retrieval_use_rate)} · 引用验证率 ${pct(ai.valid_citation_rate)} · 工具成功率 ${pct(ai.tool_success_rate)}`), el("p",{class:"note"},"引用验证仅表示引用有效，不代表回答正确。")),
      panel("用量与费用", el("p",{}, `已知输入 ${number(u.input_tokens)} · 已知输出 ${number(u.output_tokens)} Token · ${number(u.unknown_usage_calls)} 次用量未知`), el("p",{}, `已知费用 ${number(u.known_cost)} · ${number(u.unknown_cost_calls)} 次费用未知`), u.models.length ? table(["模型","调用","已知输入 Token","已知输出 Token","用量未知"],u.models.map(m => [m.model,number(m.calls),number(m.input_tokens),number(m.output_tokens),number(m.unknown_usage_calls)])) : empty("暂无模型用量。")),
      panel("每日趋势（UTC）", s.trend.length ? table(["日期","会话","AI","人工","调用","已知输入 Token","已知输出 Token","用量未知"],s.trend.map(t => [t.day,number(t.conversations),number(t.ai),number(t.human),number(t.calls),number(t.input_tokens),number(t.output_tokens),number(t.unknown_usage_calls)])) : empty("该区间暂无趋势数据。")),
      panel("分类与未解决会话", s.categories.length ? table(["分类","会话数"],s.categories.map(x => [x.category || "未分类",number(x.count)])) : empty("暂无分类。"), s.unresolved.length ? table(["未解决会话","编号"],s.unresolved.map(x => [x.subject,x.id])) : empty("暂无未解决会话。")),
      panel("访客反馈", el("p",{}, `满意 ${number(f.satisfied)} · 不满意 ${number(f.dissatisfied)} · 未评价 ${number(f.unrated)} · 满意率 ${pct(f.satisfaction_rate)}`))
    );
  }
  const range = el("form",{class:"operation-filters"}, label("开始日期（UTC，含）",start), label("结束日期（UTC，不含）",end), el("button",{type:"submit"},"查询"), button("最近 7 天",() => preset(7)), button("最近 30 天",() => preset(30)));
  range.addEventListener("submit", e => { e.preventDefault(); guard(ctx, load); });
  const root = el("div",{}, heading("运营概览","按 UTC 半开区间统计，最多查询 90 天。"), range, notice, output);
  preset(7);
  return root;
}
export async function setupPage(ctx) {
  const [s, health] = await Promise.all([
    ctx.api("/setup-status"),
    ctx.api("/health"),
  ]);
  return el(
    "div",
    {},
    heading("运行检查", "检查当前配置与数据库状态，不会连接任何外部模型。"),
    panel(
      "服务状态",
      el("p", {}, `数据库：${health.database} · Web Origin：${s.web_origin}`),
      el(
        "p",
        {},
        `外部模型：${s.external_models_enabled ? "已开启，调用可能计费" : "已关闭"}`,
      ),
      el(
        "p",
        {},
        `匿名访客限流密钥：${s.public_rate_key_ready ? "已配置" : "未配置，公开会话安全拒绝初始化"}`,
      ),
      el(
        "p",
        {},
        `凭证加密：${s.credential_encryption_ready ? "有效主密钥" : "未就绪"}`,
      ),
      el("p", {}, "批准主机：" + (s.model_allowed_hosts.join("、") || "无")),
      el(
        "p",
        {},
        `有效凭证 ${s.enabled_credentials} · 已启用 Agent ${s.enabled_agents} · 离线演示 ${s.demo_agents}`,
      ),
    ),
    message(
      "真实模型效果与生产环境尚未验收。演示模式只用于验证产品流程。",
      "warning",
    ),
    panel(
      "部署管理员",
      el(
        "p",
        {},
        "模型 Base URL 必须使用部署方批准的公开 HTTPS 主机。配置 CREDENTIAL_MASTER_KEY 和 MODEL_ALLOWED_HOSTS 后重启服务。主密钥不得丢失或直接替换。",
      ),
      el(
        "p",
        {},
        "按 README 执行数据库迁移和 create-admin。备份必须包含数据库、私有文档存储与独立安全保存的主密钥。",
      ),
    ),
  );
}
export async function membersPage(ctx) {
  const members = await collection(ctx.api, "/memberships");
  const editor = el("div");
  return el(
    "div",
    {},
    heading("企业成员", "成员身份关联已有平台用户；用户由平台管理员创建。"),
    panel(
      "添加成员",
      form(
        [
          label("用户 UUID", input("user_id", "", { required: true })),
          label(
            "角色",
            select("role", [
              { id: "member", name: "普通成员" },
              { id: "admin", name: "企业管理员" },
            ]),
          ),
        ],
        async (v) => {
          await ctx.api("/memberships", {
            method: "POST",
            body: { user_id: v.get("user_id"), role: v.get("role") },
          });
          await ctx.refresh();
        },
        "添加",
      ),
    ),
    members.length
      ? table(
          ["用户 UUID", "角色", "状态", "操作"],
          members.map((m) => [
            m.user_id,
            m.role === "admin" ? "企业管理员" : "普通成员",
            status(m.status),
            actions(
              button("修改角色", () =>
                editor.replaceChildren(
                  panel(
                    "更新成员",
                    form(
                      [
                        label(
                          "角色",
                          select(
                            "role",
                            [
                              { id: "member", name: "普通成员" },
                              { id: "admin", name: "企业管理员" },
                            ],
                            m.role,
                          ),
                        ),
                      ],
                      async (v) => {
                        await ctx.api(`/memberships/${m.id}`, {
                          method: "PATCH",
                          body: { role: v.get("role") },
                        });
                        await ctx.refresh();
                      },
                    ),
                  ),
                ),
              ),
              button(m.status === "active" ? "停用" : "启用", () =>
                guard(ctx, async () => {
                  if (
                    !confirm(
                      "确认更改此成员状态？最后一位管理员受到服务端保护。",
                    )
                  )
                    return;
                  await ctx.api(`/memberships/${m.id}`, {
                    method: "PATCH",
                    body: {
                      status: m.status === "active" ? "inactive" : "active",
                    },
                  });
                  await ctx.refresh();
                }),
              ),
            ),
          ]),
        )
      : empty("暂无成员。"),
    editor,
  );
}
export async function platformPage(ctx) {
  const [users, tenants] = await Promise.all([
    collection(ctx.api, "/users"),
    collection(ctx.api, "/tenants"),
  ]);
  const editor = el("div");
  return el(
    "div",
    {},
    heading(
      "平台管理",
      "平台身份不自动获得企业业务权限。请使用企业成员账号进入工作区。",
    ),
    panel(
      "创建用户",
      form(
        [
          label(
            "登录名",
            input("login", "", {
              required: true,
              autocomplete: "off",
              pattern: "[a-z0-9][a-z0-9@._+\\-]*",
            }),
          ),
          label("显示名称", input("display_name", "", { required: true })),
          label(
            "初始密码（至少 12 位）",
            input("password", "", {
              type: "password",
              required: true,
              minLength: 12,
              maxLength: 128,
              autocomplete: "new-password",
            }),
          ),
        ],
        async (v) => {
          await ctx.api("/users", {
            method: "POST",
            body: {
              login: v.get("login"),
              display_name: v.get("display_name"),
              password: v.get("password"),
            },
          });
          await ctx.refresh();
        },
        "创建用户",
      ),
    ),
    panel(
      "创建企业",
      form(
        [
          label("企业名称", input("name", "", { required: true })),
          label(
            "唯一标识（小写字母、数字与连字符）",
            input("slug", "", {
              required: true,
              pattern: "[a-z0-9]+(?:-[a-z0-9]+)*",
            }),
          ),
          label(
            "企业管理员",
            select(
              "admin_user_id",
              users
                .filter((u) => u.status === "active")
                .map((u) => ({
                  id: u.id,
                  name: u.display_name + " · " + u.login,
                })),
            ),
          ),
        ],
        async (v) => {
          await ctx.api("/tenants", {
            method: "POST",
            body: {
              name: v.get("name"),
              slug: v.get("slug"),
              admin_user_id: v.get("admin_user_id"),
            },
          });
          await ctx.refreshTenants();
        },
        "创建企业",
      ),
    ),
    panel(
      "企业",
      tenants.length
        ? table(
            ["名称", "标识", "状态", "操作"],
            tenants.map((t) => [
              t.name,
              t.slug,
              status(t.status),
              button(t.status === "active" ? "停用" : "启用", () =>
                guard(ctx, async () => {
                  if (
                    !confirm("更改企业状态将影响全部成员和公开客服入口，确认？")
                  )
                    return;
                  await ctx.api(`/tenants/${t.id}`, {
                    method: "PATCH",
                    body: {
                      status: t.status === "active" ? "inactive" : "active",
                    },
                  });
                  await ctx.refreshTenants();
                }),
              ),
            ]),
          )
        : empty("还没有企业。"),
    ),
    panel(
      "用户",
      table(
        ["名称 / 登录", "UUID", "状态", "操作"],
        users.map((u) => [
          u.display_name + " / " + u.login,
          u.id,
          status(u.status),
          button(u.status === "active" ? "停用" : "启用", () =>
            guard(ctx, async () => {
              if (!confirm("确认更改用户状态？")) return;
              await ctx.api(`/users/${u.id}`, {
                method: "PATCH",
                body: { status: u.status === "active" ? "inactive" : "active" },
              });
              await ctx.refresh();
            }),
          ),
        ]),
      ),
    ),
    editor,
  );
}
export async function activityPage(ctx) {
  const limits = await ctx.api("/usage-limits");
  const output = el("div"),
    details = el("div");
  const choices = [
    { id: "calls", name: "模型调用" },
    { id: "tools", name: "工具执行" },
    { id: "audit", name: "审计事件" },
  ];
  let kind = "calls";
  async function load(offset = 0) {
    const path = {
      calls: "/model-calls",
      tools: "/tool-executions",
      audit: "/audit-events",
    }[kind];
    const rows = await ctx.api(`${path}?limit=20&offset=${offset}`);
    const headers =
      kind === "calls"
        ? ["模型 / 状态", "用量", "原因", "时间", "详情"]
        : kind === "tools"
          ? ["工具", "状态", "原因", "时间", "详情"]
          : ["操作", "结果", "原因", "时间", "详情"];
    const cells = rows.map((r) =>
      kind === "calls"
        ? [
            r.model + " / " + r.status,
            `输入 ${number(r.input_tokens)} / 输出 ${number(r.output_tokens)} · 费用未知`,
            r.error_category || "—",
            date(r.created_at),
            button("查看", () =>
              details.replaceChildren(panel("调用记录", json(r))),
            ),
          ]
        : kind === "tools"
          ? [
              r.tool_name,
              status(r.status),
              r.error_category || r.delivery_error || "—",
              date(r.started_at),
              button("查看", () =>
                details.replaceChildren(panel("执行记录", json(r))),
              ),
            ]
          : [
              r.action,
              status(r.outcome),
              r.reason || "—",
              date(r.created_at),
              button("查看", () =>
                details.replaceChildren(panel("审计记录", json(r))),
              ),
            ],
    );
    output.replaceChildren(
      rows.length ? table(headers, cells) : empty("本页暂无记录。"),
      pager(offset, rows.length, 20, (n) => guard(ctx, () => load(n))),
    );
  }
  const selector = select("", choices);
  selector.addEventListener("change", () => {
    kind = selector.value;
    details.replaceChildren();
    guard(ctx, () => load());
  });
  await load();
  return el(
    "div",
    {},
    heading(
      "用量与审计",
      "未知 Token 不按零计；当前没有可靠价格数据，费用显示未知。",
    ),
    el("details", {}, el("summary", {}, "请求限制与保守预算"), json(limits)),
    selector,
    output,
    details,
  );
}
