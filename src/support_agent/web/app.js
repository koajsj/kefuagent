import { createClient, StaleResponse } from "./api.js";
import { el, button, heading, message, select, collection } from "./ui.js";
import { chatPage } from "./chat.js";
import {
  agentsPage,
  credentialsPage,
  knowledgePage,
  toolsPage,
} from "./configuration.js";
import {
  activityPage,
  membersPage,
  platformPage,
  setupPage,
  dashboardPage,
} from "./management.js";

import { publicationsPage } from "./publications.js";

import { sessionState } from "./storage.js";

const client = createClient();
const view = document.querySelector("#view");
let user = null,
  tenant = "",
  role = "",
  tenants = [],
  epoch = 0,
  noticeTimer;
const pages = {
  dashboard: ["工作区概览", dashboardPage],
  publications: ["公开客服入口", publicationsPage],
  chat: ["客服会话", chatPage],
  knowledge: ["知识库", knowledgePage],
  agents: ["Agent 配置", agentsPage],
  tools: ["工具授权", toolsPage],
  credentials: ["模型凭证", credentialsPage],
  activity: ["用量与审计", activityPage],
  members: ["企业成员", membersPage],
  setup: ["运行检查", setupPage],
  platform: ["平台管理", platformPage],
};
function notify(text) {
  const box = document.querySelector("#announcements");
  box.textContent = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => box.replaceChildren(), 6000);
}
function loggedOut() {
  epoch++;
  client.setTenant("");
  user = null;
  tenant = "";
  role = "";
  view.replaceChildren();
  document.querySelector("#workspace").hidden = true;
  document.querySelector("#login").hidden = false;
}
client.onUnauthorized(() => {
  loggedOut();
  document.querySelector("#login-error").textContent =
    "登录已过期，请重新登录。";
});
function clearPending() {
  sessionState.removePrefix("support.pending.");
}
function navigation() {
  const nav = document.querySelector("#navigation");
  nav.replaceChildren();
  for (const [key, [name]] of Object.entries(pages)) {
    if (key === "platform" && !user.is_platform_admin) continue;
    if (
      ["credentials", "activity", "members", "setup", "publications"].includes(
        key,
      ) &&
      role !== "admin"
    )
      continue;
    if (!role && key !== "platform") continue;
    nav.append(el("a", { href: "#" + key, "data-page": key }, name));
  }
}
async function chooseTenant(id) {
  client.setTenant(id);
  tenant = id;
  role = "";
  epoch++;
  view.replaceChildren(el("p", { class: "loading" }, "正在验证企业权限…"));
  if (id) {
    try {
      const info = await client.request("/workspace");
      role = info.role;
      document.querySelector("#mode-banner").textContent =
        info.external_models_enabled
          ? "外部模型开关已开启；本次未做真实模型质量验收。真实调用可能计费。"
          : "外部模型调用已关闭。可管理平台和使用明确标识的离线演示；真实客服效果尚未验收。";
    } catch (error) {
      if (!user) return;
      if (error.name === "StaleResponse") return;
      if (error.status !== 403) throw error;
    }
  }
  navigation();
  if (!role && user?.is_platform_admin) location.hash = "platform";
  else if (
    !pages[location.hash.slice(1)] ||
    (location.hash === "#platform" && !user?.is_platform_admin)
  )
    location.hash = "chat";
  await render();
}
async function signedIn() {
  user = await client.request("/auth/me");
  tenants = await collection(client.request.bind(client), "/tenants");
  document.querySelector("#login").hidden = true;
  document.querySelector("#workspace").hidden = false;
  document.querySelector("#identity").textContent =
    user.display_name + (user.is_platform_admin ? " · 平台管理员" : "");
  const switcher = document.querySelector("#tenant");
  switcher.replaceChildren(
    el("option", { value: "" }, "选择企业"),
    ...tenants.map((t) =>
      el(
        "option",
        { value: t.id },
        t.name + (t.status === "inactive" ? "（停用）" : ""),
      ),
    ),
  );
  const active = tenants.find((t) => t.status === "active");
  switcher.value = active?.id || "";
  await chooseTenant(switcher.value);
}
async function render() {
  if (!user) return;
  const current = ++epoch;
  client.setTenant(tenant);
  const key = location.hash.slice(1) || "chat";
  for (const link of document.querySelectorAll("#navigation a")) {
    if (link.dataset.page === key) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (key === "platform" && !user.is_platform_admin) {
    view.replaceChildren(message("当前账号没有平台管理权限。", "error"));
    return;
  }
  if (key !== "platform" && !role) {
    view.replaceChildren(
      heading("选择工作企业", "企业业务需要有效成员身份。"),
      message(
        user.is_platform_admin
          ? "请先在平台管理中创建企业和企业管理员，再使用企业成员账号登录。平台身份不会绕过企业授权。"
          : "当前账号暂无有效企业成员关系，请联系管理员。",
      ),
    );
    return;
  }
  if (
    ["credentials", "activity", "members", "setup", "publications"].includes(
      key,
    ) &&
    role !== "admin"
  ) {
    view.replaceChildren(message("此页面需要企业管理员权限。", "error"));
    return;
  }
  view.replaceChildren(el("p", { class: "loading" }, "正在读取数据…"));
  const ctx = {
    user,
    tenant,
    role,
    view,
    notify,
    isCurrent: () => current === epoch,
    api: (path, options) => {
      if (current !== epoch) throw new StaleResponse();
      return client.request(path, options);
    },
    refresh: () => {
      if (current === epoch) return render();
    },
    navigate: (next) => {
      if (current === epoch) location.hash = next;
    },
    refreshTenants: async () => {
      if (current === epoch) await signedIn();
    },
  };
  try {
    const result = await (pages[key]?.[1] || chatPage)(ctx);
    if (current === epoch) view.replaceChildren(result);
  } catch (error) {
    if (error.name === "StaleResponse" || error.name === "AbortError") return;
    if (current === epoch)
      view.replaceChildren(
        heading("暂时无法读取", "操作没有被自动重试。"),
        message(error.message, "error"),
        button("重新读取", () => render()),
      );
  }
}
document
  .querySelector("#login-form")
  .addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget,
      submit = form.querySelector("button");
    if (submit.disabled) return;
    submit.disabled = true;
    document.querySelector("#login-error").textContent = "";
    try {
      const values = new FormData(form);
      await client.request("/web-session", {
        method: "POST",
        body: { login: values.get("login"), password: values.get("password") },
      });
      form.elements.password.value = "";
      clearPending();
      await signedIn();
    } catch (error) {
      if (error.name !== "StaleResponse")
        document.querySelector("#login-error").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
document.querySelector("#tenant").addEventListener("change", async (event) => {
  try {
    await chooseTenant(event.target.value);
  } catch (error) {
    if (error.name !== "StaleResponse")
      view.replaceChildren(message(error.message, "error"));
  }
});
document.querySelector("#logout").addEventListener("click", async () => {
  try {
    await client.request("/auth/logout", { method: "POST" });
    clearPending();
    loggedOut();
  } catch (error) {
    if (error.name !== "StaleResponse") notify("退出未确认：" + error.message);
  }
});
window.addEventListener("hashchange", () => render());
try {
  await signedIn();
} catch (error) {
  if (error.status !== 401 && error.name !== "StaleResponse") {
    loggedOut();
    document.querySelector("#login-error").textContent = error.message;
  }
}
