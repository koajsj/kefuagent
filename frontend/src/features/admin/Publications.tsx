import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { AgentPicker } from "../../components/AgentPicker";
import { useApp } from "../../app/context";
import {
  PageHeader,
  Panel,
  ErrorNotice,
  Empty,
  DataTable,
  Field,
} from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import { collection } from "../../adapters/collection";
import type { Row } from "../../types";
export function Publications() {
  const { api, tenant, notify } = useApp();
  const [editing, setEditing] = useState(false),
    [agent, setAgent] = useState(""),
    [share, setShare] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const rows = useResource<Row[]>(
    () => collection(api.request.bind(api), "/publications"),
    [api, tenant],
  );
  const tools = useResource<Row[]>(
    () => collection(api.request.bind(api), "/tools"),
    [api, tenant],
  );
  const grants = useResource<Row[]>(
    (signal) =>
      agent
        ? api.request(`/agent-configs/${agent}/tools`, { signal })
        : Promise.resolve([]),
    [api, tenant, agent],
  );
  const setup = useResource<Row>(
    (signal) => api.request("/setup-status", { signal }),
    [api, tenant],
  );
  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      if (!["AbortError", "StaleResponse"].includes((e as Error).name))
        notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const create = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    void act(async () => {
      await api.request("/publications", {
        method: "POST",
        body: {
          name: d.get("name"),
          agent_config_id: agent,
          public_tool_ids: d.getAll("tools"),
        },
      });
      setEditing(false);
      rows.reload();
    });
  };
  let url = "",
    widget = "";
  if (share && setup.data) {
    try {
      const parsed = new URL(setup.data.web_origin);
      const local =
        parsed.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
      if (
        (!local && parsed.protocol !== "https:") ||
        parsed.username ||
        parsed.password ||
        parsed.search ||
        parsed.hash ||
        !["", "/"].includes(parsed.pathname) ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          share.id,
        )
      )
        throw Error();
      const base =
        api.mode === "demo"
          ? new URL(import.meta.env.BASE_URL, location.origin).href
          : parsed.origin + "/";
      url =
        api.mode === "demo"
          ? `${base}#/chat/${share.id}`
          : `${parsed.origin}/chat/${share.id}`;
      widget = `<script src="${base}widget.js" data-agent="${share.id}" defer></script>`;
    } catch {}
  }
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      notify("已复制。");
    } catch {
      notify("当前环境不允许自动复制，请选中内容手动复制。");
    }
  }
  return (
    <>
      <PageHeader
        title="公开客服入口"
        description="草稿创建后手动发布；修改 Agent 后必须重新发布。"
        actions={<Button onPress={() => setEditing(!editing)}>创建入口</Button>}
      />
      <ErrorNotice error={rows.error} retry={rows.reload} />
      {editing && (
        <Panel title="创建公开入口草稿">
          <form onSubmit={create}>
            <Field label="公开客服名称">
              <input name="name" required maxLength={120} />
            </Field>
            <AgentPicker value={agent} onChange={setAgent} disabled={busy} />
            <fieldset key={agent}>
              <legend>允许公开访客使用的工具（默认无）</legend>
              <ErrorNotice error={grants.error} retry={grants.reload} />
              {tools.data
                ?.filter(
                  (t) =>
                    t.enabled &&
                    t.execution_type === "read_only" &&
                    t.risk_level === "low" &&
                    !t.permissions.includes("tenant:admin") &&
                    grants.data?.some((g) => g.tool_id === t.id && g.enabled),
                )
                .map((t) => (
                  <label key={t.id}>
                    <input type="checkbox" name="tools" value={t.id} /> {t.name}
                  </label>
                ))}
            </fieldset>
            <Button
              type="submit"
              isDisabled={busy || !agent || grants.loading || !!grants.error}
            >
              创建草稿
            </Button>
          </form>
        </Panel>
      )}
      {rows.data?.length ? (
        <DataTable
          columns={["名称 / Agent 版本", "状态 / 发布版本", "操作"]}
          rows={rows.data.map((r) => [
            `${r.name} · Agent v${r.agent_version}`,
            `${r.revoked_at ? "已撤销" : r.available ? "公开可用" : r.requires_republish ? "配置变更，需重新发布" : r.enabled ? "关联 Agent 或发布者已停用" : "草稿 / 已下线"} · v${r.version}`,
            <div className="actions">
              {r.available && !r.revoked_at && !r.requires_republish && (
                <Button variant="secondary" onPress={() => setShare(r)}>
                  链接与嵌入
                </Button>
              )}
              {!r.revoked_at && (
                <Button
                  variant="secondary"
                  isDisabled={busy}
                  onPress={() =>
                    void act(async () => {
                      const saved = await api.request<Row>(
                        `/publications/${r.id}`,
                        {
                          method: "PATCH",
                          body: { enabled: true, expected_version: r.version },
                        },
                      );
                      rows.reload();
                      if (saved.available) setShare(saved);
                    })
                  }
                >
                  {r.enabled ? "重新发布" : "发布"}
                </Button>
              )}
              {r.enabled && (
                <Button
                  variant="secondary"
                  onPress={() =>
                    void act(async () => {
                      await api.request(`/publications/${r.id}`, {
                        method: "PATCH",
                        body: { enabled: false, expected_version: r.version },
                      });
                      setShare(null);
                      rows.reload();
                    })
                  }
                >
                  下线
                </Button>
              )}
              {!r.revoked_at && (
                <Button
                  variant="danger"
                  onPress={() => {
                    if (confirm("撤销不可恢复，链接将失效。确认？"))
                      void act(async () => {
                        await api.request(`/publications/${r.id}`, {
                          method: "DELETE",
                        });
                        setShare(null);
                        rows.reload();
                      });
                  }}
                >
                  撤销入口
                </Button>
              )}
            </div>,
          ])}
        />
      ) : (
        <Empty>还没有公开入口。</Empty>
      )}
      {share && (
        <Panel title="分享与嵌入">
          {url ? (
            <>
              <Field label="公开链接">
                <input
                  readOnly
                  value={url}
                  onFocus={(e) => e.target.select()}
                />
              </Field>
              <a href={url} target="_blank" rel="noopener noreferrer">
                在独立窗口打开客服
              </a>
              <Field label="网站嵌入代码">
                <textarea
                  readOnly
                  value={widget}
                  onFocus={(e) => e.target.select()}
                />
              </Field>
              <div className="actions">
                <Button variant="secondary" onPress={() => copy(url)}>
                  复制客服链接
                </Button>
                <Button onPress={() => copy(widget)}>复制嵌入代码</Button>
              </div>
              <details>
                <summary>Widget 预览</summary>
                <iframe
                  title="客服 Widget 预览"
                  src={url}
                  sandbox="allow-scripts allow-same-origin allow-forms"
                  referrerPolicy="no-referrer"
                  className="widget-preview"
                />
              </details>
              <p>
                HTML：放在页面结束前；React / Vue：放入入口
                HTML；WordPress：使用允许脚本的主题区域。宿主网站 CSP
                需允许客服域名的 script-src 与 frame-src。
              </p>
              <p>配置或授权变更可能要求重新发布；预览使用独立访客身份。</p>
            </>
          ) : (
            <p>
              服务器公开地址或入口标识无效，请联系部署管理员检查 WEB_ORIGIN。
            </p>
          )}
        </Panel>
      )}
    </>
  );
}
