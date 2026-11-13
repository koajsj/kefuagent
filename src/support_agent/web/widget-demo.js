// Fictional offline Widget only. This asset is emitted solely by the Demo build.
(() => {
  const script = document.currentScript;
  const id = script?.dataset.agent;
  if (!/^[0-9a-f-]{36}$/i.test(id || "")) return;
  const host = document.createElement("aside");
  host.dataset.supportWidgetOrigin = new URL(script.src).origin;
  host.dataset.supportWidgetAgent = id;
  Object.assign(host.style, { position: "fixed", right: "20px", bottom: "20px", zIndex: "2147483000" });
  const toggle = document.createElement("button");
  toggle.type = "button"; toggle.textContent = "离线演示客服"; toggle.setAttribute("aria-expanded", "false");
  const frame = document.createElement("iframe");
  frame.title = "虚构 Demo · 不承接真实客户";
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
  frame.referrerPolicy = "no-referrer";
  Object.assign(frame.style, { width: "min(420px, calc(100vw - 40px))", height: "min(650px, calc(100dvh - 110px))", display: "none" });
  let open = false;
  toggle.addEventListener("click", () => {
    open = !open;
    frame.src = open ? new URL("./", script.src).href + "#/chat/" + id : "about:blank";
    frame.style.display = open ? "block" : "none";
    toggle.setAttribute("aria-expanded", String(open));
  });
  host.append(frame, toggle);
  (document.body || document.documentElement).append(host);
})();
