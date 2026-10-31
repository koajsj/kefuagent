import { operationFilters, operationsPanel } from "./operations.js";
import { sessionState } from "./storage.js";
import { requestIdentity, explain } from "./api.js";
import {
  el,
  button,
  label,
  input,
  select,
  heading,
  panel,
  form,
  empty,
  actions,
  status,
  date,
  json,
  message,
  pager,
} from "./ui.js";

const PHASES = {
  pending: "等待执行",
  retrieving: "知识检索中",
  model_running: "模型请求中",
  tool_running: "工具执行中",
  completed: "已完成",
  failed: "失败",
};
export async function chatPage(ctx) {
  const root = el("div");
  let selected = null,
    offset = 0,
    historyOffset = 0,
    busy = false,
    openEpoch = 0;
  const [agents, operators] = await Promise.all([ctx.api("/agent-configs?limit=100"), ctx.api("/workspace/operators")]);
  let filters = {}, listEpoch = 0;
  const list = el("div", { class: "panel flush conversation-list" }),
    main = el("section", { class: "chat-main" });
  const listPager = el("div");
  const showError = (error) => {
    if (
      ctx.isCurrent() &&
      !["StaleResponse", "AbortError"].includes(error.name)
    )
      ctx.notify(error.code === "version_conflict" ? "会话已被其他人更新，请重新打开会话后再操作。" : error.message);
  };
  async function createConversation() {
    const subject = prompt("会话标题", "新会话");
    if (!subject?.trim()) return;
    try {
      const created = await ctx.api("/conversations", {
        method: "POST",
        body: { subject: subject.trim(), channel: "web" },
      });
      offset = 0;
      await loadList();
      await open(created);
    } catch (error) {
      showError(error);
    }
  }
  async function loadList() {
    const ticket = ++listEpoch;
    const params = new URLSearchParams({limit: "20", offset: String(offset), ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value))});
    const rows = await ctx.api(`/conversations?${params}`);
    if (!ctx.isCurrent() || ticket !== listEpoch) return;
    list.replaceChildren(
      ...rows.map((row) =>
        el(
          "div",
          { class: "item" + (selected?.id === row.id ? " selected" : "") },
          el(
            "div",
            {},
            button(row.subject, () => open(row).catch(showError), "link"),
            el("p", {}, status(row.support_state)),
            el("small", {}, date(row.updated_at) + " · " + (row.priority || "normal") + " · " + (row.sla?.state || "未知")),
          ),
        ),
      ),
    );
    if (!rows.length) list.append(empty("还没有会话。新建一条，开始咨询。"));
    listPager.replaceChildren(
      pager(offset, rows.length, 20, (next) => {
        offset = next;
        loadList().catch(showError);
      }),
    );
  }
  async function open(row) {
    if (busy) {
      ctx.notify("当前发送尚未结束，请等待或查看运行状态。");
      return;
    }
    const ticket = ++openEpoch;
    const next = await ctx.api("/conversations/" + row.id);
    if (ticket !== openEpoch) return;
    selected = next;
    historyOffset = 0;
    const cid = selected.id;
    const agent = select(
      "agent",
      agents.map((a) => ({
        id: a.id,
        name:
          a.name +
          (a.provider === "demo" ? " · 离线演示" : " · 真实模型配置") +
          (a.enabled ? "" : "（停用）"),
      })),
      agents.find((a) => a.enabled)?.id || "",
    );
    const runState = el("span", { class: "run-state" }, "尚未发送");
    const thread = el("div", {
      class: "thread",
      role: "log",
      "aria-label": "对话历史",
    });
    const historyPager = el("div");
    async function readHistory() {
      const rows = await ctx.api(
        `/conversations/${cid}/messages?newest=true&limit=50&offset=${historyOffset}`,
      );
      if (selected?.id !== cid) return;
      thread.replaceChildren(
        ...rows.map((m) => {
          const name =
            m.role === "user"
              ? "用户"
              : m.role === "tool"
                ? "工具"
                : m.source === "manual"
                  ? "人工/录入"
                  : "助手";
          const node = el(
            "article",
            { class: "message " + m.role },
            el(
              "div",
              { class: "message-label" },
              name + " · " + date(m.created_at),
            ),
            el("p", {}, m.content || "工具调用请求"),
          );
          if (m.metadata?.citations?.length)
            node.append(
              el(
                "div",
                { class: "citations" },
                m.metadata.citations.map((c) =>
                  el(
                    "div",
                    {},
                    c.document_name + (c.page ? " · 第 " + c.page + " 页" : ""),
                    el("div", {}, c.quote),
                  ),
                ),
              ),
            );
          if (m.metadata?.tool_calls)
            node.append(
              el(
                "details",
                {},
                el("summary", {}, "调用信息"),
                json(m.metadata.tool_calls),
              ),
            );
          return node;
        }),
      );
      if (!rows.length)
        thread.append(
          empty("输入问题后发送。答案、知识来源和工具结果会保存在本会话。"),
        );
      historyPager.replaceChildren(
        pager(historyOffset, rows.length, 50, (next) => {
          historyOffset = next;
          readHistory().catch(showError);
        }),
      );
      thread.scrollTop = thread.scrollHeight;
    }
    const runs = el("div");
    async function readRuns() {
      const calls = await ctx.api(`/conversations/${cid}/calls?limit=5`);
      if (selected?.id !== cid) return;
      const current = calls[0];
      if (current)
        runState.textContent =
          (PHASES[current.phase] || current.phase) +
          " · " +
          current.model +
          (current.error_category
            ? " · " + explain(current.error_category)
            : "");
      runs.replaceChildren(
        ...calls.map((c) =>
          el(
            "details",
            {},
            el(
              "summary",
              {},
              date(c.created_at) +
                " · " +
                c.model +
                " · " +
                (PHASES[c.phase] || c.phase),
            ),
            el(
              "p",
              { class: "note" },
              "输入 Token：" +
                (c.input_tokens ?? "未知") +
                " / 输出 Token：" +
                (c.output_tokens ?? "未知") +
                "；" +
                (c.usage_complete ? "用量完整" : "可能不完整，不代表账单总量"),
            ),
            json(c.steps),
          ),
        ),
      );
    }
    const composer = el("form", { class: "composer" });
    const content = el("textarea", {
      name: "content",
      required: true,
      maxLength: 4000,
      placeholder:
        selected.support_state === "human"
          ? "输入人工答复…"
          : "咨询企业知识，或使用已授权的只读工具…",
      "aria-label": "消息内容",
    });
    const human = selected.support_state === "human";
    const publicView = selected.channel === "public";
    const canSend = () => selected?.id === cid && selected.status === "open" && (human
      ? selected.support_state === "human" && (ctx.role === "admin" || selected.assignee_id === ctx.user.id)
      : selected.support_state === "ai" && agents.length > 0 && !publicView);
    agent.disabled = publicView;
    const send = el(
      "button",
      {
        type: "submit",
        class: "primary",
        disabled: !canSend(),
      },
      human ? "发送人工答复" : "发送消息",
    );
    composer.append(
      content,
      el("div", { class: "composer-footer" }, runState, send),
    );
    const inline = el("div");
    if (publicView)
      inline.append(
        message(
          "公开会话的 AI 回复由访客入口发起。管理员或当前负责人可在人工处理时答复；不会使用其他 Agent 的私有配置。",
        ),
      );
    composer.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (busy || send.disabled) return;
      busy = true;
      send.disabled = true;
      agent.disabled = true;
      inline.replaceChildren();
      runState.textContent = "正在提交…";
      const keyName = "support.pending." + ctx.tenant + "." + cid;
      try {
        if (human) {
          await ctx.api(`/conversations/${cid}/messages`, {
            method: "POST",
            body: { role: "assistant", content: content.value },
          });
        } else {
          const payload = {
            agent_config_id: agent.value,
            content: content.value,
          };
          let previous;
          try {
            previous = JSON.parse(sessionState.get(keyName));
          } catch {
            previous = null;
          }
          const identity = await requestIdentity(payload, previous);
          sessionState.set(keyName, JSON.stringify(identity));
          const preview = el("p", { class: "message assistant", "aria-live": "polite" });
          inline.append(preview);
          const response = await ctx.api(`/conversations/${cid}/agent-turns/stream`, {
            method: "POST",
            body: { ...payload, idempotency_key: identity.key },
            onEvent(event, value) {
              if (!ctx.isCurrent() || selected?.id !== cid) return;
              if (event === "stage") runState.textContent = PHASES[value.phase] || value.phase;
              if (event === "delta") preview.textContent += value.text;
              if (event === "discard") preview.textContent = "";
            },
          });
          if (response.status === "running") {
            inline.append(message("原请求仍在执行，请稍后使用相同内容重试。"));
            return;
          }
          preview.remove();
          sessionState.remove(keyName);
          if (response.error_category)
            inline.append(
              message(
                explain(response.error_category),
                response.status === "failed" ? "error" : "warning",
              ),
            );
          if (response.executions?.length)
            inline.append(
              el(
                "details",
                { open: true },
                el("summary", {}, "工具执行结果"),
                response.executions.map((e) =>
                  el(
                    "div",
                    {},
                    status(e.status),
                    el("span", {}, " " + e.tool_name),
                    e.data
                      ? json(e.data)
                      : message(explain(e.error_category), "warning"),
                  ),
                ),
              ),
            );
        }
        content.value = "";
        await readHistory();
        await loadList();
        await readRuns();
      } catch (error) {
        if (
          ctx.isCurrent() &&
          !["StaleResponse", "AbortError"].includes(error.name)
        )
          inline.append(
            message(
              error.message +
                (human
                  ? " 人工回复结果可能未知，请刷新历史核实后再决定是否发送。"
                  : " 可保留相同内容重试。"),
              "error",
            ),
          );
      } finally {
        busy = false;
        if (ctx.isCurrent() && selected?.id === cid && ticket === openEpoch) {
          try {
            const current = await ctx.api(`/conversations/${cid}`);
            if (ctx.isCurrent() && selected?.id === cid && ticket === openEpoch) {
              selected = current;
              send.disabled = !canSend();
              agent.disabled = publicView || current.status !== "open";
              if (!canSend()) inline.append(message("会话状态或权限已变化，请重新打开会话查看。"));
            }
          } catch (error) {
            showError(error);
          }
        }
      }
    });
    async function handling(state) {
      if (busy) return;
      try {
        await ctx.api(`/conversations/${cid}/handling`, {
          method: "POST",
          body: { state, expected_version: selected.version },
        });
        await loadList();
        await open({ id: cid });
      } catch (error) {
        showError(error);
      }
    }
    const controls = actions();
    if (selected.status === "open" && (selected.support_state !== "human" || ctx.role === "admin" || selected.assignee_id === ctx.user.id))
      controls.append(button("标记待人工", () => handling("waiting")));
    if (ctx.role === "admin") {
      if (selected.support_state !== "human" && selected.status === "open")
        controls.append(button("人工接管", () => handling("human")));
      if (selected.support_state !== "ai" && selected.status === "open")
        controls.append(button("恢复 AI", () => handling("ai")));
      if (selected.status === "closed") controls.append(button("重新打开会话", async () => {
        try {
          await ctx.api(`/conversations/${cid}`, {method:"PATCH",body:{status:"open"}});
          await open({id:cid});
        } catch (error) { showError(error); }
      }));
      if (selected.status === "open")
        controls.append(button("标记已解决", () => handling("resolved")));
    } else if (selected.status === "open") {
      if (selected.support_state === "waiting" && (!selected.assignee_id || selected.assignee_id === ctx.user.id))
        controls.append(button("人工接管", () => handling("human")));
      if (selected.support_state === "human" && selected.assignee_id === ctx.user.id) {
        controls.append(button("恢复 AI", () => handling("ai")));
        controls.append(button("标记已解决", () => handling("resolved")));
      }
    }
    const operations = await operationsPanel(ctx, selected, operators, () => ctx.isCurrent() && selected?.id === cid && ticket === openEpoch, () => open({id:cid}));
    if (!ctx.isCurrent() || selected?.id !== cid || ticket !== openEpoch) return;
    main.replaceChildren(
      el(
        "div",
        { class: "chat-controls" },
        el("h2", {}, selected.subject),
        status(selected.support_state),
        label("当前 Agent", agent),
        controls,
      ),
      thread,
      historyPager,
      composer,
      inline,
      el("div", { class: "chat-controls" }, el("h3", {}, "最近运行"), runs),
      operations,
    );
    if (selected.support_state === "waiting")
      inline.append(
        message(
          "已标记待人工。管理员或符合权限的成员可接管；当前不会自动发送给外部客服。",
        ),
      );
    if (!agents.length)
      inline.append(
        message("尚未配置 Agent，请联系管理员创建离线演示或真实模型配置。"),
      );
    await readHistory();
    await readRuns();
    await loadList();
  }
  root.append(
    heading(
      "客服会话",
      "基于企业知识和已授权工具回答，保留每一步处理记录。",
      button("新建会话", createConversation, "primary"),
    ),
    el("div", { class: "chat-layout" }, el("div", {}, operationFilters(operators, values => { filters = values; offset = 0; loadList().catch(showError); }), list, listPager), main),
  );
  main.append(
    empty("选择会话查看历史，或新建会话。企业成员共享当前企业的工作区。"),
  );
  await loadList();
  return root;
}
