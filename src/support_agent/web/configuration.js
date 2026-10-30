import {
  el,
  button,
  label,
  input,
  textArea,
  select,
  message,
  empty,
  panel,
  actions,
  heading,
  table,
  date,
  json,
  status,
  check,
  form,
  collection,
  pager,
} from "./ui.js";
const asJSON = (value) => {
  try {
    return JSON.parse(value || "{}");
  } catch {
    throw new Error("JSON 格式不正确，请检查括号与引号。");
  }
};
const list = (ctx, path) => collection(ctx.api, path);
const admin = (ctx) => ctx.role === "admin";
const guard = async (ctx, fn) => {
  try {
    await fn();
  } catch (e) {
    if (ctx.isCurrent() && !["StaleResponse", "AbortError"].includes(e.name))
      ctx.notify(e.message);
  }
};

export async function agentsPage(ctx) {
  const [agents, bases] = await Promise.all([
    list(ctx, "/agent-configs"),
    list(ctx, "/knowledge-bases"),
  ]);
  const root = el("div"),
    editor = el("div");
  async function edit(agent) {
    const binding = agent
      ? await ctx.api(`/agent-configs/${agent.id}/knowledge-bases`)
      : null;
    const enabled = check("启用 Agent", agent?.enabled ?? true);
    const provider = select(
      "provider",
      [
        { id: "demo", name: "离线演示（确定性响应，无模型费用）" },
        { id: "openai_compatible", name: "OpenAI 兼容服务" },
      ],
      agent?.provider || "demo",
    );
    const kbChoices = bases
      .filter((b) => b.status === "active")
      .map((b) => ({
        id: b.id,
        ...check(b.name, binding?.knowledge_base_ids.includes(b.id)),
      }));
    const runtime = agent?.runtime || {};
    const supports = check("支持 Tool Calling", runtime.supports_tools ?? true),
      temperature = check("发送温度参数", runtime.send_temperature ?? true);
    const fields = [
      label(
        "Agent 名称",
        input("name", agent?.name || "", { required: true, maxLength: 120 }),
      ),
      label("Provider", provider),
      label(
        "Model ID",
        input("model", agent?.model || "offline-support", {
          required: true,
          maxLength: 120,
        }),
      ),
      label(
        "Base URL（兼容服务必填，须在部署白名单中）",
        input("base_url", agent?.base_url || "", {
          type: "url",
          placeholder: "https://api.example.com/v1",
        }),
      ),
      label(
        "凭证引用（在模型凭证中创建）",
        input("credential_ref", agent?.credential_ref || "", {
          placeholder: "cred_primary",
        }),
      ),
      label(
        "Agent 说明",
        textArea("description", agent?.behavior.description || "", {
          maxLength: 2000,
          rows: 2,
        }),
      ),
      label(
        "客服行为指令",
        textArea("instructions", agent?.behavior.instructions || "", {
          maxLength: 12000,
          rows: 5,
        }),
      ),
      label(
        "语言",
        input("language", agent?.behavior.language || "zh", { required: true }),
      ),
      el(
        "div",
        { class: "form-row" },
        label(
          "温度",
          input("temperature", runtime.temperature ?? 0.2, {
            type: "number",
            step: "0.1",
            min: 0,
            max: 2,
          }),
        ),
        label(
          "最大输出 Token",
          input("max_output_tokens", runtime.max_output_tokens ?? 2048, {
            type: "number",
            min: 1,
            max: 32768,
          }),
        ),
      ),
      el(
        "div",
        { class: "form-row" },
        label(
          "输入预算（保守字节预算）",
          input("max_input_tokens", runtime.max_input_tokens ?? 8192, {
            type: "number",
            min: 2048,
            max: 32768,
          }),
        ),
        label(
          "超时（秒）",
          input("timeout_seconds", runtime.timeout_seconds ?? 30, {
            type: "number",
            min: 1,
            max: 120,
          }),
        ),
      ),
      supports.node,
      temperature.node,
      label(
        "输出限制参数",
        select(
          "token_parameter",
          [
            { id: "max_tokens", name: "max_tokens" },
            { id: "max_completion_tokens", name: "max_completion_tokens" },
          ],
          runtime.token_parameter || "max_tokens",
        ),
      ),
      el(
        "details",
        {},
        el("summary", {}, "任务路由与备用模型（JSON）"),
        el(
          "p",
          { class: "note" },
          'qa、extraction、reasoning、fallback 均为同一 Provider 的模型目标。示例：{"fallback":{"model":"your-model","supports_tools":false}}；未配置则使用主模型。',
        ),
        textArea("routing", JSON.stringify(runtime.routing || {}, null, 2), {
          rows: 8,
        }),
      ),
      enabled.node,
      el(
        "fieldset",
        {},
        el("legend", {}, "授权知识库（最多 10 个）"),
        kbChoices.length
          ? kbChoices.map((c) => c.node)
          : empty("请先创建知识库。"),
      ),
    ];
    const body = form(
      fields,
      async (values) => {
        const payload = {
          name: values.get("name"),
          provider: values.get("provider"),
          model: values.get("model"),
          base_url: values.get("base_url") || null,
          credential_ref: values.get("credential_ref") || null,
          enabled: enabled.box.checked,
          behavior: {
            description: values.get("description"),
            instructions: values.get("instructions"),
            language: values.get("language"),
          },
          runtime: {
            temperature: Number(values.get("temperature")),
            max_output_tokens: Number(values.get("max_output_tokens")),
            max_input_tokens: Number(values.get("max_input_tokens")),
            timeout_seconds: Number(values.get("timeout_seconds")),
            supports_tools: supports.box.checked,
            send_temperature: temperature.box.checked,
            token_parameter: values.get("token_parameter"),
            routing: asJSON(values.get("routing")),
          },
        };
        const saved = await ctx.api(
          agent ? `/agent-configs/${agent.id}` : "/agent-configs",
          {
            method: agent ? "PUT" : "POST",
            body: agent
              ? { ...payload, expected_version: binding.config_version }
              : payload,
          },
        );
        try {
          await ctx.api(`/agent-configs/${saved.id}/knowledge-bases`, {
            method: "PUT",
            body: {
              knowledge_base_ids: kbChoices
                .filter((c) => c.box.checked)
                .map((c) => c.id),
              expected_version: saved.version,
            },
          });
        } catch (e) {
          ctx.notify("Agent 已保存，知识库授权未确认：" + e.message);
          await ctx.refresh();
          return;
        }
        ctx.notify(
          "Agent 与知识库授权已保存。配置变更后的公开入口需重新发布。",
        );
        await ctx.refresh();
      },
      agent ? "保存新版本" : "创建 Agent",
    );
    editor.replaceChildren(
      panel(
        agent ? `编辑 · ${agent.name} · v${agent.version}` : "创建客服 Agent",
        body,
      ),
    );
  }
  root.append(
    heading(
      "Agent 配置",
      "配置模型、行为与知识库。工具授权和公开发布各有独立权限检查。",
      admin(ctx)
        ? button("创建 Agent", () => guard(ctx, () => edit(null)), "primary")
        : null,
    ),
  );
  root.append(
    agents.length
      ? table(
          ["名称", "Provider / 模型", "版本", "状态", "操作"],
          agents.map((a) => [
            a.name,
            `${a.provider} / ${a.model}`,
            a.version,
            status(a.enabled ? "active" : "inactive"),
            admin(ctx)
              ? button("编辑", () => guard(ctx, () => edit(a)))
              : "只读",
          ]),
        )
      : empty("还没有 Agent。企业管理员可创建离线演示或兼容模型配置。"),
    editor,
  );
  return root;
}

export async function credentialsPage(ctx) {
  const [credentials, setup] = await Promise.all([
    list(ctx, "/model-credentials"),
    ctx.api("/setup-status"),
  ]);
  const editor = el("div");
  function edit(row) {
    const enabled = check("启用凭证", row?.enabled ?? true);
    editor.replaceChildren(
      panel(
        row ? "轮换凭证内容" : "新增第三方凭证",
        form(
          [
            label(
              "凭证引用",
              input("ref", row?.ref || "", {
                required: true,
                readOnly: !!row,
                placeholder: "cred_primary",
                pattern: "cred_[a-z0-9][a-z0-9_-]*",
              }),
            ),
            label(
              "API Key（只写入，不会回显）",
              input("api_key", "", {
                type: "password",
                required: true,
                maxLength: 4096,
                autocomplete: "off",
              }),
            ),
            enabled.node,
          ],
          async (values) => {
            await ctx.api(
              row ? `/model-credentials/${row.id}` : "/model-credentials",
              {
                method: row ? "PUT" : "POST",
                body: {
                  ref: values.get("ref"),
                  api_key: values.get("api_key"),
                  enabled: enabled.box.checked,
                },
              },
            );
            editor.querySelector("[name=api_key]").value = "";
            ctx.notify("凭证已加密保存。");
            await ctx.refresh();
          },
        ),
      ),
    );
  }
  return el(
    "div",
    {},
    heading(
      "模型凭证",
      "第三方 Key 按企业与引用绑定加密；配置在 Agent 页面引用。",
      button("新增凭证", () => edit(null), "primary"),
    ),
    message(
      setup.credential_encryption_ready
        ? "主密钥配置有效。界面不会读取或显示 API Key。"
        : "尚未配置有效的 CREDENTIAL_MASTER_KEY，凭证保存会安全失败。",
      "warning",
    ),
    message(
      "批准的模型主机：" +
        (setup.model_allowed_hosts.join("、") ||
          "无。请由部署管理员设置 MODEL_ALLOWED_HOSTS。"),
    ),
    credentials.length
      ? table(
          ["引用", "状态", "更新时间", "操作"],
          credentials.map((r) => [
            r.ref,
            status(r.enabled ? "active" : "inactive"),
            date(r.updated_at),
            actions(
              button("更新/停用", () => edit(r)),
              button(
                "删除",
                () =>
                  guard(ctx, async () => {
                    if (
                      !confirm(
                        "删除凭证后，引用它的 Agent 将无法继续真实调用。确认删除？",
                      )
                    )
                      return;
                    await ctx.api(`/model-credentials/${r.id}`, {
                      method: "DELETE",
                    });
                    await ctx.refresh();
                  }),
                "danger",
              ),
            ),
          ]),
        )
      : empty("尚无凭证。离线演示无需凭证。"),
    editor,
  );
}

export async function knowledgePage(ctx) {
  const bases = await list(ctx, "/knowledge-bases"),
    details = el("div"),
    editor = el("div");
  let selection = 0;
  async function open(base, offset = 0) {
    const ticket = ++selection;
    const docs = await ctx.api(
      `/knowledge-bases/${base.id}/documents?limit=20&offset=${offset}`,
    );
    if (ticket !== selection) return;
    const results = el("div");
    async function chunks(doc, part = 0) {
      const rows = await ctx.api(
        `/documents/${doc.id}/chunks?limit=20&offset=${part}`,
      );
      results.replaceChildren(
        panel(
          doc.filename + " · 分块",
          ...rows.map((r) =>
            panel(
              "第 " +
                (r.position + 1) +
                " 块" +
                (r.page ? " · 页 " + r.page : ""),
              el("p", {}, r.content),
            ),
          ),
          pager(part, rows.length, 20, (n) => guard(ctx, () => chunks(doc, n))),
        ),
      );
    }
    const search = form(
      [
        label(
          "中文检索预览",
          input("query", "", {
            required: true,
            maxLength: 1000,
            placeholder: "输入客户常见问题",
          }),
        ),
      ],
      async (values) => {
        const hits = await ctx.api(`/knowledge-bases/${base.id}/search`, {
          method: "POST",
          body: { query: values.get("query") },
        });
        results.replaceChildren(
          ...(hits.length
            ? hits.map((h) =>
                panel(
                  h.document_name,
                  el("p", {}, h.content),
                  el(
                    "p",
                    { class: "note" },
                    `分块 ${h.chunk_id} · ${h.strategy}${h.page ? " · 页 " + h.page : ""}`,
                  ),
                ),
              )
            : [empty("没有找到相关来源。")]),
        );
      },
      "检索",
    );
    const upload = admin(ctx)
      ? form(
          [
            label(
              "上传资料（PDF / DOCX / TXT / Markdown，最大 5 MiB）",
              input("file", "", {
                type: "file",
                required: true,
                accept: ".pdf,.docx,.txt,.md,.markdown",
              }),
            ),
          ],
          async (values) => {
            const file = values.get("file");
            if (file.size > 5 * 1024 * 1024)
              throw new Error("文件超过 5 MiB。");
            await ctx.api(`/knowledge-bases/${base.id}/documents`, {
              method: "POST",
              body: values,
            });
            ctx.notify("文档已上传并处理，请检查处理状态。");
            await open(base, offset);
          },
          "上传并解析",
        )
      : null;
    details.replaceChildren(
      panel(
        base.name,
        el("p", {}, base.description),
        upload,
        docs.length
          ? table(
              ["文档", "处理状态", "分块", "原因", "操作"],
              docs.map((d) => [
                d.filename,
                status(d.status),
                d.chunk_count,
                d.error_category || "—",
                actions(
                  button("信息", () =>
                    results.replaceChildren(panel("文档信息", json(d))),
                  ),
                  button("查看分块", () => guard(ctx, () => chunks(d))),
                  admin(ctx)
                    ? button("重新处理", () =>
                        guard(ctx, async () => {
                          await ctx.api(`/documents/${d.id}/reprocess`, {
                            method: "POST",
                          });
                          await open(base, offset);
                        }),
                      )
                    : null,
                  admin(ctx)
                    ? button(
                        "删除",
                        () =>
                          guard(ctx, async () => {
                            if (
                              !confirm(
                                `删除 ${d.filename}？删除后立即停止检索。`,
                              )
                            )
                              return;
                            await ctx.api(`/documents/${d.id}`, {
                              method: "DELETE",
                            });
                            await open(base, offset);
                          }),
                        "danger",
                      )
                    : null,
                ),
              ]),
            )
          : empty("尚未上传文档。"),
        pager(offset, docs.length, 20, (n) => guard(ctx, () => open(base, n))),
        search,
        results,
      ),
    );
  }
  return el(
    "div",
    {},
    heading(
      "知识库",
      "资料按企业隔离。当前检索使用 PostgreSQL FTS 与中文二字组。",
      admin(ctx)
        ? button("创建知识库", () =>
            editor.replaceChildren(
              panel(
                "新建知识库",
                form(
                  [
                    label(
                      "名称",
                      input("name", "", { required: true, maxLength: 120 }),
                    ),
                    label(
                      "说明",
                      textArea("description", "", { maxLength: 2000 }),
                    ),
                  ],
                  async (v) => {
                    await ctx.api("/knowledge-bases", {
                      method: "POST",
                      body: {
                        name: v.get("name"),
                        description: v.get("description"),
                      },
                    });
                    await ctx.refresh();
                  },
                ),
              ),
            ),
          )
        : null,
    ),
    editor,
    bases.length
      ? table(
          ["名称", "状态", "操作"],
          bases.map((b) => [
            b.name,
            status(b.status),
            actions(
              button("查看资料", () => guard(ctx, () => open(b))),
              admin(ctx)
                ? button(
                    "删除知识库",
                    () =>
                      guard(ctx, async () => {
                        if (
                          !confirm(
                            "确认删除整个知识库及其文档？现有引用将失效。",
                          )
                        )
                          return;
                        await ctx.api(`/knowledge-bases/${b.id}`, {
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
      : empty("还没有知识库。"),
    details,
  );
}

export async function toolsPage(ctx) {
  const [tools, agents, capabilities] = await Promise.all([
    list(ctx, "/tools"),
    list(ctx, "/agent-configs"),
    admin(ctx) ? ctx.api("/tool-capabilities") : [],
  ]);
  const grants = el("div");
  let grantEpoch = 0;
  async function choose(id) {
    const ticket = ++grantEpoch;
    if (!id) {
      grants.replaceChildren();
      return;
    }
    const assigned = await ctx.api(`/agent-configs/${id}/tools`);
    if (ticket !== grantEpoch) return;
    grants.replaceChildren(
      panel(
        "Agent 工具授权",
        ...tools.map((t) => {
          const enabled = assigned.some((g) => g.tool_id === t.id && g.enabled);
          return el(
            "div",
            { class: "item" },
            el("span", {}, t.name + " · " + t.execution_type),
            status(enabled ? "active" : "inactive"),
            admin(ctx)
              ? button(enabled ? "撤销授权" : "授权", () =>
                  guard(ctx, async () => {
                    await ctx.api(`/agent-configs/${id}/tools/${t.id}`, {
                      method: "PUT",
                      body: { enabled: !enabled },
                    });
                    await choose(id);
                  }),
                )
              : null,
          );
        }),
      ),
    );
  }
  const selector = select("", [
    { id: "", name: "选择 Agent" },
    ...agents.map((a) => ({ id: a.id, name: a.name })),
  ]);
  selector.addEventListener("change", () =>
    guard(ctx, () => choose(selector.value)),
  );
  return el(
    "div",
    {},
    heading(
      "工具协议与授权",
      "仅静态注册的低风险只读能力能够执行；数据库定义不能变成代码。",
    ),
    tools.length
      ? table(
          ["名称 / 标识", "版本 / 类型", "状态", "操作"],
          tools.map((t) => [
            t.name + " / " + t.key,
            `${t.version} / ${t.execution_type}`,
            status(t.enabled ? "active" : "inactive"),
            actions(
              button("查看协议", () =>
                grants.replaceChildren(panel(t.name, json(t))),
              ),
              admin(ctx)
                ? button(t.enabled ? "禁用" : "启用", () =>
                    guard(ctx, async () => {
                      await ctx.api(`/tools/${t.id}`, {
                        method: "PATCH",
                        body: { enabled: !t.enabled },
                      });
                      await ctx.refresh();
                    }),
                  )
                : null,
            ),
          ]),
        )
      : empty("暂无工具定义。"),
    admin(ctx)
      ? panel(
          "注册现有静态能力",
          ...capabilities
            .filter((c) => !tools.some((t) => t.key === c.key))
            .map((c) =>
              button("注册 " + c.key, () =>
                guard(ctx, async () => {
                  await ctx.api("/tools", {
                    method: "POST",
                    body: {
                      ...c,
                      name: c.key,
                      description: "平台内置只读能力 " + c.key,
                      risk_level: "low",
                      permissions: ["tools:invoke"],
                      enabled: true,
                    },
                  });
                  await ctx.refresh();
                }),
              ),
            ),
        )
      : null,
    panel("选择 Agent 管理授权", selector),
    grants,
  );
}
