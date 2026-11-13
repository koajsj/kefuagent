import { useState } from "react";
import { Button } from "@heroui/react";
import { AgentPicker } from "../../components/AgentPicker";
import { useApp } from "../../app/context";
import {
  PageHeader,
  Panel,
  ErrorNotice,
  DataTable,
  Status,
  JsonView,
  Loading,
} from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import { collection } from "../../adapters/collection";
import type { Row } from "../../types";
export function Tools() {
  const { api, tenant, role, notify } = useApp();
  const [agent, setAgent] = useState(""),
    [detail, setDetail] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
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
  const caps = useResource<Row[]>(
    (signal) =>
      role === "admin"
        ? api.request("/tool-capabilities", { signal })
        : Promise.resolve([]),
    [api, tenant, role],
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
  return (
    <>
      <PageHeader
        title="工具协议与授权"
        description="部署代码限定工具能力与最低风险；R2 命令还需 Agent 自治上限及资源授权，R3 保持阻断。"
      />
      <ErrorNotice error={tools.error} retry={tools.reload} />
      {tools.loading ? <Loading /> : !tools.error && <DataTable
        columns={["名称 / 标识", "版本 / 类型", "状态", "操作"]}
        rows={(tools.data || []).map((t) => [
          `${t.name} / ${t.key}`,
          `${t.version} / ${t.execution_type}`,
          <span><Status value={t.enabled ? "active" : "inactive"} /> · {t.runtime_bound ? "已绑定运行时" : "未绑定运行时"}{t.binding_error ? ` · ${t.binding_error}` : ""}</span>,
          <div className="actions">
            <Button variant="secondary" onPress={() => setDetail(t)}>
              查看协议
            </Button>
            {role === "admin" && (
              <Button
                variant="secondary"
                isDisabled={busy}
                onPress={() =>
                  void act(async () => {
                    await api.request(`/tools/${t.id}`, {
                      method: "PATCH",
                      body: { enabled: !t.enabled },
                    });
                    tools.reload();
                  })
                }
              >
                {t.enabled ? "禁用" : "启用"}
              </Button>
            )}
          </div>,
        ])}
      />}
      {detail && (
        <Panel title={detail.name}>
          <JsonView value={detail} />
        </Panel>
      )}
      {role === "admin" && (
        <Panel title="注册现有静态能力">
          <ErrorNotice error={caps.error} retry={caps.reload} />
          {caps.data
            ?.filter((c) => !tools.data?.some((t) => t.key === c.key))
            .map((c) => (
              <Button
                key={c.key}
                isDisabled={busy || tools.loading || !!tools.error}
                onPress={() =>
                  void act(async () => {
                    await api.request("/tools", {
                      method: "POST",
                      body: {
                        key: c.key, version: c.version, parameters: c.parameters,
                        output_schema: c.output_schema, execution_type: c.execution_type,
                        name: c.key,
                        description: `部署内置客服能力 ${c.key}`,
                        risk_level: c.minimum_risk >= 3 ? "high" : c.minimum_risk === 2 ? "medium" : "low",
                        permissions: ["tools:invoke"],
                        enabled: true,
                      },
                    });
                    tools.reload();
                  })
                }
              >
                注册 {c.key} · R{c.minimum_risk ?? 1}
              </Button>
            ))}
        </Panel>
      )}
      <Panel title="选择 Agent 管理授权">
        <AgentPicker value={agent} onChange={setAgent} disabled={busy} />
        <ErrorNotice error={grants.error} retry={grants.reload} />
        {agent && grants.loading && <p>正在读取授权…</p>}
        {agent &&
          !grants.loading &&
          !grants.error &&
          tools.data?.map((t) => {
            const enabled = grants.data?.some(
              (g) => g.tool_id === t.id && g.enabled,
            );
            return (
              <div key={t.id} className="actions">
                <span>
                  {t.name} · {t.execution_type} · {t.runtime_bound ? "已绑定运行时" : "未绑定运行时"}{t.binding_error ? ` · ${t.binding_error}` : ""}
                </span>
                <Status value={enabled ? "active" : "inactive"} />
                {role === "admin" && (
                  <Button
                    variant="secondary"
                    isDisabled={busy || (!enabled && !t.runtime_bound)}
                    onPress={() =>
                      void act(async () => {
                        await api.request(
                          `/agent-configs/${agent}/tools/${t.id}`,
                          { method: "PUT", body: { enabled: !enabled } },
                        );
                        grants.reload();
                      })
                    }
                  >
                    {enabled ? "撤销授权" : "授权"}
                  </Button>
                )}
              </div>
            );
          })}
      </Panel>
    </>
  );
}
