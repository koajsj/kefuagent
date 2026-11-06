import type { RequestOptions } from "../types";
export async function readEvents(
  response: Response,
  onEvent: NonNullable<RequestOptions["onEvent"]>,
) {
  if (
    !response.headers.get("content-type")?.includes("text/event-stream") ||
    !response.body
  )
    throw new Error("服务器未返回 SSE；结果可能未知，请核实记录。");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    terminal = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      if (buffer.length > 262144) throw new Error("流式响应超出安全大小限制。");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let event = "message";
        const data: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        }
        if (!data.length) continue;
        const payload = JSON.parse(data.join("\n"));
        if (["failed", "timed_out"].includes(event))
          throw Object.assign(
            new Error(
              "调用失败或结果未知：" + (payload.error_category || event),
            ),
            { code: payload.error_category || event },
          );
        onEvent(event, payload);
        if (event === "completed" || event === "pending") {
          terminal = true;
          return event === "pending"
            ? { ...payload, status: "running" }
            : payload;
        }
      }
      if (done) break;
    }
    throw new Error("连接中断，结果未知。请刷新记录，重试时保留原请求标识。");
  } finally {
    try {
      if (!terminal) onEvent("discard", {});
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}
