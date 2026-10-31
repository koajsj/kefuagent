import { el, button, label, input, message, panel, actions, heading, form, collection } from "./ui.js";

const go = (ctx, name, page) => button(name, () => ctx.navigate(page));

function platformStage(ctx) {
  return el("div", {},
    heading("使用向导", "先建立企业工作区，再以企业管理员身份完成配置。"),
    message("已有企业请先在左侧选择有成员权限的企业，无需重复创建。平台管理员身份不会自动赋予企业权限；新建企业时可将当前账号设为初始企业管理员，或在平台管理中指定其他用户。"),
    panel("创建企业", form([
      label("企业名称", input("name", "", { required: true, maxLength: 120 })),
      label("唯一标识（小写字母、数字与连字符）", input("slug", "", { required: true, minLength: 3, maxLength: 80, pattern: "[a-z0-9]+(?:-[a-z0-9]+)*" })),
    ], async (values) => {
      const created = await ctx.api("/tenants", { method: "POST", body: {
        name: values.get("name"), slug: values.get("slug"), admin_user_id: ctx.user.id,
      }});
      await ctx.refreshTenants(created.id);
    }, "创建企业并进入")),
    actions(go(ctx, "打开平台管理", "platform")),
  );
}

export async function onboardingPage(ctx) {
  if (ctx.role !== "admin") {
    if (ctx.user.is_platform_admin) return platformStage(ctx);
    return message("使用向导需要企业管理员权限。", "error");
  }
  const [workspace, setup, bases, agents, publications, statistics] = await Promise.all([
    ctx.api("/workspace"), ctx.api("/setup-status"),
    collection(ctx.api, "/knowledge-bases"), collection(ctx.api, "/agent-configs"),
    collection(ctx.api, "/publications"), ctx.api("/workspace/statistics"),
  ]);
  const result = el("div");
  const importButton = button("导入离线演示", async () => {
    importButton.disabled = true;
    result.replaceChildren(message("正在导入演示资源…"));
    try {
      const demo = await ctx.api("/workspace/demo", { method: "POST" });
      if (!ctx.isCurrent()) return;
      result.replaceChildren(message(
        `${demo.created ? "已创建" : "已找到"}离线演示资源。文档状态：${demo.document_status}。知识库 ${demo.knowledge_base_id}；文档 ${demo.document_id}；Agent ${demo.agent_config_id}。` +
        (demo.document_status === "ready" ? " 可前往客服会话选择演示 Agent。" : " 文档尚未就绪，请在知识库查看原因或重新处理；初次写入中断可再次导入恢复。"),
        demo.document_status === "failed" ? "error" : demo.document_status === "ready" ? "" : "warning",
      ));
    } catch (error) {
      if (ctx.isCurrent() && !["StaleResponse", "AbortError"].includes(error.name))
        result.replaceChildren(message(error.message, "error"));
    } finally { importButton.disabled = false; }
  }, "primary");
  const steps = [
    ["01", "模型与运行环境", `外部模型${setup.external_models_enabled ? "已开启" : "已关闭"}；有效凭证 ${setup.enabled_credentials} 个。真实模型质量尚未验收。`, [go(ctx, "模型凭证", "credentials"), go(ctx, "运行检查", "setup")]],
    ["02", "准备知识", `当前 ${bases.length} 个知识库、${statistics.documents} 个文档。请在知识库检查文档处理状态。`, [go(ctx, "打开知识库", "knowledge")]],
    ["03", "配置 Agent", `当前 ${agents.length} 个 Agent，其中启用 ${setup.enabled_agents} 个、离线演示 ${setup.demo_agents} 个。`, [go(ctx, "配置 Agent", "agents")]],
    ["04", "体验客服与人工接管", `当前 ${statistics.conversations} 个会话。创建会话后可在会话页面体验人工接管。`, [go(ctx, "打开客服会话", "chat")]],
    ["05", "发布与观察", `当前 ${publications.length} 个公开入口，其中 ${publications.filter((p) => p.available).length} 个可用。发布须手动操作。`, [go(ctx, "公开客服入口", "publications"), go(ctx, "运营概览", "dashboard")]],
  ];
  return el("div", {},
    heading("使用向导", "按需完成配置；进度依据当前企业资源，每次打开都会刷新。", button("刷新状态", () => ctx.refresh())),
    el("p", { class: "note" }, `当前企业 ${workspace.tenant_id} · 企业管理员`),
    panel("快速体验：青禾协作（虚构 SaaS）",
      el("p", {}, "导入内置离线演示知识库、文档和 Agent，不调用外部模型。导入不会创建会话、公开入口或运营统计数据。"),
      el("p", {}, "可在客服会话选择离线演示 Agent，尝试提问："),
      el("ul", {}, el("li", {}, "青禾协作的试用期有多久？"), el("li", {}, "客服支持时间是什么时候？"), el("li", {}, "如何导出 CSV？")),
      el("p", { class: "note" }, "示例资料：试用 14 天；周一至周五 09:00–18:00 支持；在设置 → 数据导出中导出 CSV。演示响应不代表真实模型效果。"),
      importButton, result,
    ),
    el("div", { class: "onboarding-steps" }, steps.map(([n, title, detail, controls]) =>
      el("section", { class: "panel onboarding-step" },
        el("span", { class: "onboarding-number", "aria-hidden": "true" }, n),
        el("div", {}, el("h2", {}, title), el("p", {}, detail), actions(...controls)),
      ),
    )),
  );
}
