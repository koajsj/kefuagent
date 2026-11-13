import { adapter } from "../../adapters";
import type { Row } from "../../types";

export async function websiteBootstrap(pid: string): Promise<string> {
  if (adapter.mode === "demo") return "offline-demo";
  const site = new URL(location.href).searchParams.get("site");
  if (parent === window || !/^[0-9a-f-]{36}$/i.test(site || "")) throw new Error("请从已验证的网站打开客服。");
  const requestId = crypto.randomUUID();
  const received = await new Promise<{ assertion: Row; origin: string }>((resolve, reject) => {
    const timer = setTimeout(() => { window.removeEventListener("message", receive); reject(new Error("网站身份凭证未就绪，请检查网站后端接入。")); }, 15000);
    function receive(event: MessageEvent) {
      const value = event.data;
      if (event.source !== parent || value?.type !== "kefuagent.assertion" || value.requestId !== requestId || value.assertion?.site_id !== site) return;
      clearTimeout(timer); window.removeEventListener("message", receive);
      resolve({ assertion: value.assertion, origin: event.origin });
    }
    window.addEventListener("message", receive);
    parent.postMessage({ type: "kefuagent.bootstrap-request", requestId, site, publicationId: pid }, "*");
  });
  const grant = await adapter.request<Row>(`/public/${pid}/bootstrap`, { method: "POST", body: received.assertion });
  if (grant.origin !== received.origin) throw new Error("网站来源与签名身份不一致。");
  return grant.token;
}
