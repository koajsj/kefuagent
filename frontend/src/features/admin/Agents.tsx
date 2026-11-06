import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { EditorModal } from "../../components/EditorModal";
import { useApp } from "../../app/context";
import {
  PageHeader,
  ErrorNotice,
  Empty,
  DataTable,
  Field,
  Status,
  Pager,
} from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import { collection } from "../../adapters/collection";
import type { Row } from "../../types";

export function Agents() {
  const { api, tenant, role, notify } = useApp();
  const [offset, setOffset] = useState(0),
    [query, setQuery] = useState(""),
    [search, setSearch] = useState(""),
    [edit, setEdit] = useState<Row | null>(null),
    [binding, setBinding] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const agents = useResource<Row[]>(
    (signal) =>
      api.request(
        `/agent-configs?limit=20&offset=${offset}${search ? `&q=${encodeURIComponent(search)}` : ""}`,
        { signal },
      ),
    [api, tenant, offset, search],
  );
  const bases = useResource<Row[]>(
    () => collection(api.request.bind(api), "/knowledge-bases"),
    [api, tenant],
  );
  const setup = useResource<Row | null>(
    (signal) =>
      role === "admin"
        ? api.request("/setup-status", { signal })
        : Promise.resolve(null),
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
  const open = (agent: Row | null) =>
    void act(async () => {
      const b = agent
        ? await api.request<Row>(`/agent-configs/${agent.id}/knowledge-bases`)
        : { id: "", knowledge_base_ids: [] };
      setBinding(b);
      setEdit(
        agent || {
          id: "",
          provider: "demo",
          model: "offline-support",
          enabled: true,
          behavior: {},
          runtime: {},
        },
      );
    });
  const save = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    void act(async () => {
      const provider = String(data.get("provider"));
      const saved = await api.request<Row>(
        edit!.id ? `/agent-configs/${edit!.id}` : "/agent-configs",
        {
          method: edit!.id ? "PUT" : "POST",
          body: {
            name: data.get("name"),
            provider,
            model: data.get("model"),
            base_url: provider === "demo" ? null : data.get("base_url") || null,
            credential_ref:
              provider === "demo" ? null : data.get("credential_ref") || null,
            enabled: data.has("enabled"),
            behavior: {
              description: data.get("description"),
              instructions: data.get("instructions"),
              language: data.get("language"),
              answer_mode: data.get("answer_mode"),
            },
            runtime: {
              temperature: Number(data.get("temperature")),
              max_output_tokens: Number(data.get("max_output_tokens")),
              max_input_tokens: Number(data.get("max_input_tokens")),
              timeout_seconds: Number(data.get("timeout_seconds")),
              supports_tools: data.has("supports_tools"),
              send_temperature: data.has("send_temperature"),
              token_parameter: data.get("token_parameter"),
              routing: JSON.parse(String(data.get("routing") || "{}")),
            },
            ...(edit!.id ? { expected_version: binding!.config_version } : {}),
          },
        },
      );
      try {
        await api.request(`/agent-configs/${saved.id}/knowledge-bases`, {
          method: "PUT",
          body: {
            knowledge_base_ids: data.getAll("base"),
            expected_version: saved.version,
          },
        });
        notify("Agent 与知识库授权已保存。配置变更后的公开入口需重新发布。");
      } catch (err) {
        notify(`Agent 已保存，知识库授权未确认：${(err as Error).message}`);
        setEdit(saved);
        setBinding({
          ...binding!,
          config_version: saved.version,
          knowledge_base_ids: data.getAll("base"),
        });
        agents.reload();
        return;
      }
      setEdit(null);
      agents.reload();
    });
  };
  return (
    <>
      <PageHeader
        title="Agent 配置"
        description="配置模型、行为与知识库。工具授权和公开发布各有独立权限检查。"
        actions={
          role === "admin" && (
            <Button onPress={() => open(null)}>创建 Agent</Button>
          )
        }
      />
      <form
        className="filter-toolbar"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(query);
          setOffset(0);
        }}
      >
        <Field label="搜索 Agent">
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </Field>
        <Button type="submit">搜索</Button>
      </form>
      <ErrorNotice error={agents.error} retry={agents.reload} />
      {agents.loading ? (
        <p>加载中…</p>
      ) : agents.data?.length ? (
        <DataTable
          columns={["名称", "Provider / 模型", "版本", "状态", "操作"]}
          rows={agents.data.map((a) => [
            a.name,
            `${a.provider} / ${a.model}`,
            a.version,
            <Status value={a.enabled ? "active" : "inactive"} />,
            role === "admin" ? (
              <Button variant="secondary" onPress={() => open(a)}>
                编辑
              </Button>
            ) : (
              "只读"
            ),
          ])}
        />
      ) : (
        <Empty>没有找到 Agent。</Empty>
      )}
      <Pager
        offset={offset}
        count={agents.data?.length || 0}
        size={20}
        onChange={setOffset}
      />
      {setup.data && (
        <p>
          外部模型{setup.data.external_models_enabled ? "已开启" : "已关闭"}
          ；凭证加密
          {setup.data.credential_encryption_ready ? "已就绪" : "未就绪"}
          ；批准主机：{setup.data.model_allowed_hosts?.join("、") || "无"}。
        </p>
      )}
      {edit && binding && (
        <EditorModal
          onClose={() => {
            if (!busy) setEdit(null);
          }}
          title={
            edit.id
              ? `编辑 · ${edit.name} · v${edit.version}`
              : "创建客服 Agent"
          }
        >
          <form onSubmit={save} key={edit.id}>
            <Field label="Agent 名称">
              <input
                name="name"
                required
                maxLength={120}
                defaultValue={edit.name}
              />
            </Field>
            <Field label="Provider">
              <select
                name="provider"
                defaultValue={edit.provider}
                onChange={(e) => setEdit({ ...edit, provider: e.target.value })}
              >
                <option value="demo">离线演示</option>
                <option value="openai_compatible">OpenAI 兼容服务</option>
                {!["demo", "openai_compatible"].includes(edit.provider) && (
                  <option value={edit.provider}>
                    {edit.provider}（当前不支持调用）
                  </option>
                )}
              </select>
            </Field>
            <Field label="Model ID">
              <input
                name="model"
                required
                maxLength={120}
                defaultValue={edit.model}
              />
            </Field>
            {edit.provider !== "demo" && (
              <>
                <Field label="Base URL">
                  <input
                    name="base_url"
                    type="url"
                    defaultValue={edit.base_url || ""}
                    required
                  />
                </Field>
                <Field label="凭证引用">
                  <input
                    name="credential_ref"
                    defaultValue={edit.credential_ref || ""}
                    required
                  />
                </Field>
              </>
            )}
            <Field label="Agent 说明">
              <textarea
                name="description"
                maxLength={2000}
                defaultValue={edit.behavior?.description || ""}
              />
            </Field>
            <Field label="客服行为指令">
              <textarea
                name="instructions"
                maxLength={12000}
                defaultValue={edit.behavior?.instructions || ""}
              />
            </Field>
            <Field label="语言">
              <input
                name="language"
                required
                defaultValue={edit.behavior?.language || "zh"}
              />
            </Field>
            <Field label="回答方式">
              <select
                name="answer_mode"
                defaultValue={edit.behavior?.answer_mode || "verified_extracts"}
              >
                <option value="verified_extracts">核验摘录</option>
                <option value="evidence_synthesis">基于证据综合回答</option>
              </select>
            </Field>
            <p className="page-description">
              综合回答保留来源校验，但不保证语义或事实正确；真实模型效果尚未验收。
            </p>
            <details>
              <summary>高级运行与路由设置</summary>
              {[
                ["temperature", "温度", 0.2, 0, 2, 0.1],
                ["max_output_tokens", "最大输出 Token", 2048, 1, 32768, 1],
                ["max_input_tokens", "输入预算", 8192, 2048, 32768, 1],
                ["timeout_seconds", "超时（秒）", 30, 1, 120, 1],
              ].map(([name, label, def, min, max, step]) => (
                <Field key={String(name)} label={String(label)}>
                  <input
                    name={String(name)}
                    type="number"
                    defaultValue={edit.runtime?.[String(name)] ?? Number(def)}
                    min={Number(min)}
                    max={Number(max)}
                    step={Number(step)}
                    required
                  />
                </Field>
              ))}
              <label>
                <input
                  type="checkbox"
                  name="supports_tools"
                  defaultChecked={edit.runtime?.supports_tools ?? false}
                />{" "}
                模型支持 Tool Calling
              </label>
              <label>
                <input
                  type="checkbox"
                  name="send_temperature"
                  defaultChecked={edit.runtime?.send_temperature ?? true}
                />{" "}
                发送温度参数
              </label>
              <Field label="输出限制参数">
                <select
                  name="token_parameter"
                  defaultValue={edit.runtime?.token_parameter || "max_tokens"}
                >
                  <option value="max_tokens">max_tokens</option>
                  <option value="max_completion_tokens">
                    max_completion_tokens
                  </option>
                </select>
              </Field>
              <Field label="任务路由与备用模型（JSON）">
                <textarea
                  name="routing"
                  defaultValue={JSON.stringify(
                    edit.runtime?.routing || {},
                    null,
                    2,
                  )}
                />
              </Field>
            </details>
            <label>
              <input
                type="checkbox"
                name="enabled"
                defaultChecked={edit.enabled}
              />{" "}
              启用 Agent
            </label>
            <fieldset>
              <legend>授权知识库（最多 10 个）</legend>
              <ErrorNotice error={bases.error} retry={bases.reload} />
              {bases.data
                ?.filter((b) => b.status === "active")
                .map((b) => (
                  <label key={b.id}>
                    <input
                      name="base"
                      type="checkbox"
                      value={b.id}
                      defaultChecked={binding.knowledge_base_ids.includes(b.id)}
                    />{" "}
                    {b.name}
                  </label>
                ))}
            </fieldset>
            <Button
              type="submit"
              isDisabled={busy || bases.loading || !!bases.error}
            >
              保存
            </Button>
            <Button variant="secondary" onPress={() => setEdit(null)}>
              取消
            </Button>
          </form>
        </EditorModal>
      )}
    </>
  );
}
