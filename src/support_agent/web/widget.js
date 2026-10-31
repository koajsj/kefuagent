/* Public iframe loader: no management credentials, API keys or cross-origin API access. */
(() => {
  const script = document.currentScript;
  const id = script?.dataset.agent;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id || "")) return;
  const origin = new URL(script.src).origin;
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
  frame.src = origin + "/chat/" + id;
  frame.hidden = true;
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
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
  toggle.addEventListener("click", () => {
    frame.hidden = !frame.hidden;
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
