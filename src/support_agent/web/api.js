import { readEvents } from "./stream.js";
const errors = {
  public_rate_key_unavailable:
    "部署管理员尚未配置 PUBLIC_RATE_KEY，暂不能创建访客会话。",
  invalid_provider_url:
    "模型地址必须为批准白名单中的 HTTPS 主机，不允许私网、IP、查询参数或用户信息。",
  visitor_authentication_required: "访客会话已过期或无效，请重新开始会话。",
  visitor_limit_exceeded: "访客访问达到限制，请稍后再试。",
  public_tool_denied: "此工具未获公开使用授权。",
  publication_revoked: "入口已撤销，请创建新入口。",
  conversation_closed: "会话已结束，请重新开始。",
  base_url_not_allowed:
    "模型地址未被部署方批准。请检查 HTTPS 地址和主机白名单。",
  authentication_required: "登录已过期，请重新登录。",
  invalid_credentials: "账号或密码错误，或账号暂时被锁定。",
  permission_denied: "当前账号没有此操作权限。",
  origin_denied: "当前浏览器地址与 WEB_ORIGIN 不一致，请按部署配置的地址访问。",
  external_models_disabled:
    "外部模型调用已关闭。可使用离线演示 Agent；真实调用须另行授权。",
  credential_key_unavailable: "服务器未配置有效的凭证主密钥。",
  credential_unavailable: "凭证不可用，请由管理员检查。",
  version_conflict: "配置已被更新，请重新打开后保存。",
  conversation_busy: "该会话仍在执行，请等待后使用原请求重试。",
  human_handling_active: "当前会话正在等待或由人工处理，AI 回复已暂停。",
  token_budget_exceeded: "保守 Token 预算不足，请检查用量限制。",
  request_limit_exceeded: "请求过于频繁，请稍后重试。",
  concurrency_limit_exceeded: "并发调用已达上限，请等待已有调用结束。",
  insufficient_evidence: "资料不足，无法确认答案。",
  conflicting_evidence: "资料存在冲突，请联系人工核实。",
  interrupted_result_unknown:
    "执行中断，结果未知。请检查记录，不要盲目创建新请求。",
  resource_conflict: "资源已存在或关联冲突，请刷新列表。",
};
export function explain(code, fallback = "") {
  return errors[code] || fallback || code || "请求失败，请检查服务状态。";
}
export class StaleResponse extends Error {
  constructor() {
    super("上下文已切换");
    this.name = "StaleResponse";
  }
}
export function createClient(fetcher = globalThis.fetch.bind(globalThis)) {
  let tenant = "",
    generation = 0,
    unauthorized = () => {};
  const pending = new Set();
  return {
    setTenant(value) {
      tenant = value || "";
      generation++;
      for (const c of pending) c.abort();
      pending.clear();
    },
    onUnauthorized(fn) {
      unauthorized = fn;
    },
    async request(path, options = {}) {
      const epoch = generation,
        controller = new AbortController();
      pending.add(controller);
      const headers = { ...options.headers };
      if (tenant) headers["X-Tenant-ID"] = tenant;
      let body = options.body;
      if (body && !(body instanceof FormData)) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(body);
      }
      try {
        const response = await fetcher("/api/v1" + path, {
          ...options,
          body,
          headers,
          signal: controller.signal,
          credentials: "same-origin",
          cache: "no-store",
        });
        if (epoch !== generation) throw new StaleResponse();
        if (response.ok && options.onEvent) {
          const result = await readEvents(response, (event, value) => {
            if (epoch !== generation) throw new StaleResponse();
            options.onEvent(event, value);
          });
          if (epoch !== generation) throw new StaleResponse();
          return result;
        }
        const value = response.status === 204 ? null : await response.json();
        if (epoch !== generation) throw new StaleResponse();
        if (!response.ok) {
          const error = new Error(
            explain(value?.error?.code, value?.error?.message),
          );
          error.status = response.status;
          error.code = value?.error?.code;
          error.requestId = value?.request_id;
          if (response.status === 401 && path !== "/web-session")
            unauthorized();
          throw error;
        }
        return value;
      } catch (error) {
        if (error.code === "authentication_required") unauthorized();
        if (epoch !== generation) throw new StaleResponse();
        if (error instanceof TypeError)
          throw new Error(
            "网络连接中断，操作结果可能未知。请检查记录，重试发送将复用原请求标识。",
          );
        throw error;
      } finally {
        pending.delete(controller);
      }
    },
  };
}
export async function requestIdentity(payload, previous) {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
  return previous?.digest === digest
    ? previous
    : { digest, key: crypto.randomUUID() };
}
