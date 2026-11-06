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
        description="仅静态注册的低风险只读能力能够执行。"
      />
      <ErrorNotice error={tools.error} retry={tools.reload} />
      <DataTable
        columns={["名称 / 标识", "版本 / 类型", "状态", "操作"]}
        rows={(tools.data || []).map((t) => [
          `${t.name} / ${t.key}`,
          `${t.version} / ${t.execution_type}`,
          <Status value={t.enabled ? "active" : "inactive"} />,
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
      />
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
                isDisabled={busy}
                onPress={() =>
                  void act(async () => {
                    await api.request("/tools", {
                      method: "POST",
                      body: {
                        ...c,
                        name: c.key,
                        description: `平台内置只读能力 ${c.key}`,
                        risk_level: "low",
                        permissions: ["tools:invoke"],
                        enabled: true,
                      },
                    });
                    tools.reload();
                  })
                }
              >
                注册 {c.key}
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
                  {t.name} · {t.execution_type}
                </span>
                <Status value={enabled ? "active" : "inactive"} />
                {role === "admin" && (
                  <Button
                    variant="secondary"
                    isDisabled={busy}
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
