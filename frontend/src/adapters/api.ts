import type { Adapter, RequestOptions } from "../types";
import { readEvents } from "./sse";
import { explain } from "./errors";
export class StaleResponse extends Error {
  constructor() {
    super("上下文已切换");
    this.name = "StaleResponse";
  }
}
class ApiAdapter implements Adapter {
  readonly mode = "api";
  private tenant = "";
  private generation = 0;
  private unauthorized = () => {};
  private pending = new Set<AbortController>();
  setTenant(id: string) {
    this.tenant = id;
    this.generation++;
    for (const controller of this.pending) controller.abort();
    this.pending.clear();
  }
  onUnauthorized(callback: () => void) {
    this.unauthorized = callback;
  }
  async request<T = any>(
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\"))
      throw new Error("无效 API 路径。");
    const publicPath = path.startsWith("/public/"),
      epoch = this.generation;
    if (options.visitorToken && !publicPath)
      throw new Error("访客身份不能访问管理接口。");
    const controller = new AbortController(),
      abort = () => controller.abort();
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener("abort", abort, { once: true });
    // A public iframe has independent identity and lifecycle; tenant changes only cancel admin requests.
    if (!publicPath) this.pending.add(controller);
    const headers: Record<string, string> = {};
    if (!publicPath && this.tenant) headers["X-Tenant-ID"] = this.tenant;
    if (publicPath && options.visitorToken)
      headers["Authorization"] = "Visitor " + options.visitorToken;
    let body: BodyInit | undefined;
    if (options.body instanceof FormData) body = options.body;
    else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }
    const assertCurrent = () => {
      if (!publicPath && epoch !== this.generation) throw new StaleResponse();
      if (controller.signal.aborted)
        throw new DOMException("请求已取消，结果可能未知。", "AbortError");
    };
    try {
      const response = await fetch("/api/v1" + path, {
        method: options.method || "GET",
        body,
        headers,
        signal: controller.signal,
        credentials: publicPath ? "omit" : "same-origin",
        cache: "no-store",
      });
      assertCurrent();
      options.onHeaders?.(response.headers);
      if (response.ok && options.responseType === "blob") {
        if (!response.headers.get("content-type")?.includes("application/octet-stream")) throw new Error("文件响应格式错误。");
        const blob = await response.blob(); assertCurrent(); return blob as T;
      }
      if (response.ok && options.onEvent) {
        const result = await readEvents(response, (event, value) => {
          assertCurrent();
          options.onEvent!(event, value);
        });
        assertCurrent();
        return result as T;
      }
      if (
        response.status !== 204 &&
        !response.headers.get("content-type")?.includes("application/json")
      )
        throw new Error(
          "API 响应格式错误，请检查反向代理和 /api/v1 路径；操作结果可能未知。",
        );
      const value = response.status === 204 ? null : await response.json();
      assertCurrent();
      if (!response.ok) {
        const error = Object.assign(
          new Error(explain(value?.error?.code || "", value?.error?.message)),
          {
            status: response.status,
            code: value?.error?.code,
            requestId: value?.request_id,
          },
        );
        if (!publicPath && response.status === 401 && path !== "/web-session")
          this.unauthorized();
        throw error;
      }
      return value as T;
    } catch (error) {
      assertCurrent();
      if (error instanceof TypeError)
        throw new Error(
          "网络连接中断，结果可能未知。请检查记录并保留原请求标识。",
        );
      throw error;
    } finally {
      this.pending.delete(controller);
      options.signal?.removeEventListener("abort", abort);
    }
  }
}
export const adapter: Adapter = new ApiAdapter();
