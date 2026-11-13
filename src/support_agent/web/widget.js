/* Public iframe loader: no management credentials, API keys or cross-origin API access. */
(() => {
  const script = document.currentScript;
  const id = script?.dataset.agent;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id || "")) return;
  const origin = new URL(script.src).origin;
  const site = script.dataset.site;
  const bootstrapPath = script.dataset.bootstrapUrl;
  if (!/^[0-9a-f-]{36}$/i.test(site || "") || !bootstrapPath) return;
  const signer = new URL(bootstrapPath, location.href);
  if (signer.origin !== location.origin || location.protocol !== "https:") return;
  if ([...document.querySelectorAll("[data-support-widget-origin][data-support-widget-agent]")].some(
    (element) => element.dataset.supportWidgetOrigin === origin && element.dataset.supportWidgetAgent === id
  )) return;
  const host = document.createElement("aside");
  host.dataset.supportWidgetOrigin = origin;
  host.dataset.supportWidgetAgent = id;
  Object.assign(host.style, {
    position: "fixed",
    right: "20px",
    bottom: "20px",
    zIndex: "2147483000",
  });
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.textContent = "在线客服";
  toggle.setAttribute("aria-expanded", "false");
  Object.assign(toggle.style, {
    background: "#176b58",
    color: "white",
    border: 0,
    borderRadius: "24px",
    padding: "14px 20px",
    font: "16px system-ui",
    cursor: "pointer",
  });
  const frame = document.createElement("iframe");
  frame.title = "在线客服";
  const chatUrl = origin + "/chat/" + id + "?site=" + encodeURIComponent(site);
  frame.src = "about:blank";
  frame.hidden = true;
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms allow-downloads");
  frame.referrerPolicy = "no-referrer";
  Object.assign(frame.style, {
    width: "min(420px, calc(100vw - 40px))",
    height: "min(650px, calc(100dvh - 110px))",
    border: "1px solid #dce2dc",
    borderRadius: "16px",
    background: "white",
    display: "none",
    marginBottom: "12px",
    boxShadow: "0 12px 40px #0002",
  });
  let signing = null;
  let generation = 0;
  window.addEventListener("message", async (event) => {
    const value = event.data;
    if (frame.hidden || signing || event.source !== frame.contentWindow || event.origin !== origin || value?.type !== "kefuagent.bootstrap-request" || value.site !== site || value.publicationId !== id || typeof value.requestId !== "string") return;
    const controller = new AbortController();
    const currentGeneration = generation;
    signing = controller;
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(signer, { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ site_id: site, publication_id: id }), signal: controller.signal });
      if (!response.ok) throw new Error("Website signer unavailable");
      const assertion = await response.json();
      if (!frame.hidden && generation === currentGeneration && !controller.signal.aborted) frame.contentWindow.postMessage({ type: "kefuagent.assertion", requestId: value.requestId, assertion }, origin);
    } catch {
      // Credential issuance failed; the iframe shows its bounded timeout error.
      if (generation === currentGeneration && !frame.hidden) toggle.textContent = "网站身份暂不可用";
    } finally {
      clearTimeout(timeout);
      if (signing === controller) signing = null;
    }
  });
  toggle.addEventListener("click", () => {
    generation += 1;
    signing?.abort();
    signing = null;
    frame.hidden = !frame.hidden;
    // Unloading the frame stops polling and client work; a tab-scoped visitor can resume.
    frame.src = frame.hidden ? "about:blank" : chatUrl;
    frame.style.display = frame.hidden ? "none" : "block";
    toggle.setAttribute("aria-expanded", String(!frame.hidden));
    toggle.textContent = frame.hidden ? "在线客服" : "关闭客服";
  });
  host.append(frame, toggle);
  if (document.body) {
    document.body.append(host);
  } else {
    // Reserve the instance before DOMContentLoaded so another script cannot duplicate it.
    document.documentElement.append(host);
    document.addEventListener("DOMContentLoaded", () => {
      if (host.isConnected && document.body) document.body.append(host);
    }, { once: true });
  }
})();
