import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import {
  PageHeader,
  Panel,
  ErrorNotice,
  Empty,
  DataTable,
  Field,
  Status,
  JsonView,
  Pager,
  Loading,
} from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import { collection } from "../../adapters/collection";
import type { Row } from "../../types";

export function Operations({ page }: { page: string }) {
  const { api, tenant, notify, refreshSession, user } = useApp();
  const [offset, setOffset] = useState(0),
    [kind, setKind] = useState("calls"),
    [detail, setDetail] = useState<Row | null>(null),
    [editing, setEditing] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const paths: Record<string, string> = {
    setup: "/setup-status",
    members: "/memberships",
    credentials: "/model-credentials",
    activity: (
      {
        calls: "/model-calls",
        tools: "/tool-executions",
        audit: "/audit-events",
      } as Record<string, string>
    )[kind],
    platform: "/users",
  };
  const resource = useResource<any>(
    (signal) =>
      ["members", "credentials", "platform"].includes(page)
        ? collection(api.request.bind(api), paths[page])
        : api.request(
            `${paths[page]}${page === "activity" ? `?limit=20&offset=${offset}` : ""}`,
            { signal },
          ),
    [api, tenant, page, offset, kind],
  );
  const extra = useResource<any>(
    (signal) =>
      page === "setup"
        ? api.request("/health", { signal })
        : page === "platform"
          ? collection(api.request.bind(api), "/tenants")
          : page === "credentials"
            ? api.request("/setup-status", { signal })
            : page === "activity"
              ? api.request("/usage-limits", { signal })
              : Promise.resolve(null),
    [api, tenant, page],
  );
  const cost = useResource<Row | null>(
    (signal) =>
      page === "activity" && kind === "calls" && detail
        ? api.request(`/model-calls/${detail.id}/cost`, { signal })
        : Promise.resolve(null),
    [api, tenant, page, kind, detail?.id],
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
  const submit =
    (path: string, method = "POST") =>
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const form = e.currentTarget,
        data = Object.fromEntries(new FormData(form));
      void act(async () => {
        await api.request(path, { method, body: data });
        form.reset();
        setEditing(null);
        resource.reload();
        extra.reload();
        if (page === "platform") await refreshSession();
      });
    };
  const update = (path: string, body: object, confirmText?: string) => {
    if (confirmText && !confirm(confirmText)) return;
    void act(async () => {
      await api.request(path, { method: "PATCH", body });
      resource.reload();
      extra.reload();
      if (page === "platform") await refreshSession();
    });
  };
  const title: Record<string, string> = {
    setup: "运行检查",
    members: "企业成员",
    credentials: "模型凭证",
    activity: "用量与审计",
    platform: "平台管理",
  };
  if (resource.loading || resource.error)
    return (
      <>
        <PageHeader title={title[page]} />
        {resource.loading ? (
          <Loading />
        ) : (
          <ErrorNotice error={resource.error} retry={resource.reload} />
        )}
      </>
    );
  return (
    <>
      <PageHeader
        title={title[page]}
        description={
          page === "activity"
            ? "费用基于部署方价格估算，并非账单；未知用量或价格不会按零计。"
            : page === "setup"
              ? "检查当前配置与数据库状态，不会连接外部模型。"
              : undefined
        }
      />
      <ErrorNotice error={resource.error} retry={resource.reload} />
      <ErrorNotice error={extra.error} retry={extra.reload} />
      {page === "setup" && resource.data && (
        <>
          <Panel title="服务状态">
            <p>
              数据库：{extra.data?.database} · Web Origin：
              {resource.data.web_origin}
            </p>
            <p>
              外部模型：
              {resource.data.external_models_enabled ? "已开启" : "已关闭"}
              ；凭证加密：
              {resource.data.credential_encryption_ready ? "已就绪" : "未就绪"}
              ；匿名访客限流密钥：
              {resource.data.public_rate_key_ready ? "已配置" : "未配置"}
            </p>
            <p>
              批准主机：{resource.data.model_allowed_hosts?.join("、") || "无"}
            </p>
            <p>
              有效凭证 {resource.data.enabled_credentials} · 已启用 Agent{" "}
              {resource.data.enabled_agents} · 离线演示{" "}
              {resource.data.demo_agents}
            </p>
          </Panel>
          <p>真实模型效果与生产环境尚未验收。</p>
        </>
      )}
      {page === "activity" && (
        <>
          <details>
            <summary>请求限制与保守预算</summary>
            <JsonView value={extra.data} />
          </details>
          <Field label="记录类型">
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setOffset(0);
                setDetail(null);
              }}
            >
              <option value="calls">模型调用</option>
              <option value="tools">工具执行</option>
              <option value="audit">审计事件</option>
            </select>
          </Field>
          {resource.data?.length ? (
            <DataTable
              columns={["名称 / 操作", "状态", "原因", "时间", "详情"]}
              rows={resource.data.map((r: Row) => [
                r.model || r.tool_name || r.action,
                <Status value={r.status || r.outcome} />,
                r.error_category || r.delivery_error || r.reason || "—",
                r.created_at || r.started_at,
                <Button variant="secondary" onPress={() => setDetail(r)}>
                  查看
                </Button>,
              ])}
            />
          ) : (
            <Empty>本页暂无记录。</Empty>
          )}
          <Pager
            offset={offset}
            count={resource.data?.length || 0}
            size={20}
            onChange={setOffset}
          />
          {detail && (
            <Panel title="记录详情">
              <JsonView value={detail} />
              {kind === "calls" && (
                <section aria-label="费用估算">
                  <h3>费用估算</h3>
                  <p>
                    基于部署方价格快照估算，并非供应商账单；未知部分不计为零。
                  </p>
                  {cost.loading ? (
                    <p>正在加载费用…</p>
                  ) : cost.error ? (
                    <ErrorNotice error={cost.error} retry={cost.reload} />
                  ) : (
                    cost.data && (
                      <>
                        <p>
                          总额：
                          {cost.data.total == null
                            ? "未知"
                            : `${cost.data.total} ${cost.data.currency || ""}`}{" "}
                          · 未知步骤：{cost.data.unknown_steps}
                        </p>
                        <p>
                          已知小计：
                          {Object.entries(cost.data.known_subtotals || {})
                            .map(
                              ([currency, amount]) => `${amount} ${currency}`,
                            )
                            .join("、") || "无"}
                        </p>
                        <JsonView value={cost.data.steps} />
                      </>
                    )
                  )}
                </section>
              )}
            </Panel>
          )}
        </>
      )}
      {page === "members" && (
        <>
          <Panel title="添加成员">
            <form onSubmit={submit("/memberships")}>
              <Field label="用户 UUID">
                <input name="user_id" required />
              </Field>
              <Field label="角色">
                <select name="role">
                  <option value="member">普通成员</option>
                  <option value="admin">企业管理员</option>
                </select>
              </Field>
              <Button type="submit" isDisabled={busy}>
                添加
              </Button>
            </form>
          </Panel>
          <DataTable
            columns={["用户 UUID", "角色", "状态", "操作"]}
            rows={(resource.data || []).map((m: Row) => [
              m.user_id,
              m.role,
              <Status value={m.status} />,
              <div className="actions">
                <Button variant="secondary" onPress={() => setEditing(m)}>
                  修改角色
                </Button>
                <Button
                  variant="secondary"
                  onPress={() =>
                    update(
                      `/memberships/${m.id}`,
                      { status: m.status === "active" ? "inactive" : "active" },
                      "确认更改此成员状态？最后一位管理员受到服务端保护。",
                    )
                  }
                >
                  {m.status === "active" ? "停用" : "启用"}
                </Button>
              </div>,
            ])}
          />
          {editing && (
            <Panel title="更新成员">
              <form onSubmit={submit(`/memberships/${editing.id}`, "PATCH")}>
                <Field label="角色">
                  <select name="role" defaultValue={editing.role}>
                    <option value="member">普通成员</option>
                    <option value="admin">企业管理员</option>
                  </select>
                </Field>
                <Button type="submit" isDisabled={busy}>
                  保存
                </Button>
              </form>
            </Panel>
          )}
        </>
      )}
      {page === "credentials" && (
        <>
          <p>
            {extra.data?.credential_encryption_ready
              ? "主密钥配置有效。"
              : "凭证加密尚未就绪。"}{" "}
            界面不会读取或显示 API Key。批准主机：
            {extra.data?.model_allowed_hosts?.join("、") || "无"}。
          </p>
          <Button onPress={() => setEditing({ id: "", enabled: true })}>
            新增凭证
          </Button>
          <DataTable
            columns={["引用", "状态", "更新时间", "操作"]}
            rows={(resource.data || []).map((r: Row) => [
              r.ref,
              <Status value={r.enabled ? "active" : "inactive"} />,
              r.updated_at,
              <div className="actions">
                <Button variant="secondary" onPress={() => setEditing(r)}>
                  更新/停用
                </Button>
                <Button
                  variant="danger"
                  onPress={() => {
                    if (
                      confirm(
                        "删除凭证后，引用它的 Agent 将无法继续真实调用。确认删除？",
                      )
                    )
                      void act(async () => {
                        await api.request(`/model-credentials/${r.id}`, {
                          method: "DELETE",
                        });
                        resource.reload();
                      });
                  }}
                >
                  删除
                </Button>
              </div>,
            ])}
          />
          {editing && (
            <Panel title={editing.id ? "轮换凭证内容" : "新增第三方凭证"}>
              <form
                key={editing.id}
                onSubmit={(e) => {
                  e.preventDefault();
                  const form = e.currentTarget,
                    d = new FormData(form);
                  void act(async () => {
                    await api.request(
                      editing.id
                        ? `/model-credentials/${editing.id}`
                        : "/model-credentials",
                      {
                        method: editing.id ? "PUT" : "POST",
                        body: {
                          ref: d.get("ref"),
                          api_key: d.get("api_key"),
                          enabled: d.has("enabled"),
                        },
                      },
                    );
                    form.reset();
                    setEditing(null);
                    resource.reload();
                    notify(
                      api.mode === "demo"
                        ? "仅保存了虚构凭证引用，输入的 Key 不会保留或使用。"
                        : "凭证已加密保存。",
                    );
                  });
                }}
              >
                <Field label="凭证引用">
                  <input
                    name="ref"
                    defaultValue={editing.ref || ""}
                    readOnly={!!editing.id}
                    required
                    pattern={"cred_[a-z0-9][a-z0-9_\\-]*"}
                  />
                </Field>
                <Field
                  label={
                    api.mode === "demo"
                      ? "模拟 Key（请勿输入真实密钥）"
                      : "API Key（只写入，不会回显）"
                  }
                >
                  <input
                    name="api_key"
                    type="password"
                    required
                    maxLength={4096}
                    autoComplete="off"
                  />
                </Field>
                <label>
                  <input
                    type="checkbox"
                    name="enabled"
                    defaultChecked={editing.enabled}
                  />{" "}
                  启用凭证
                </label>
                <Button type="submit" isDisabled={busy}>
                  保存
                </Button>
              </form>
            </Panel>
          )}
        </>
      )}
      {page === "platform" && (
        <>
          <Panel title="创建用户">
            <form onSubmit={submit("/users")}>
              <Field label="登录名">
                <input
                  name="login"
                  required
                  pattern="[a-z0-9][a-z0-9@._+\-]*"
                />
              </Field>
              <Field label="显示名称">
                <input name="display_name" required />
              </Field>
              <Field label="初始密码（至少 12 位）">
                <input
                  name="password"
                  type="password"
                  required
                  minLength={12}
                  maxLength={128}
                />
              </Field>
              <Button type="submit" isDisabled={busy}>
                创建用户
              </Button>
            </form>
          </Panel>
          <Panel title="创建企业">
            <form onSubmit={submit("/tenants")}>
              <Field label="企业名称">
                <input name="name" required />
              </Field>
              <Field label="唯一标识">
                <input
                  name="slug"
                  required
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                />
              </Field>
              <Field label="企业管理员">
                <select name="admin_user_id" required>
                  <option value="">选择用户</option>
                  {resource.data
                    ?.filter((u: Row) => u.status === "active")
                    .map((u: Row) => (
                      <option key={u.id} value={u.id}>
                        {u.display_name} · {u.login}
                      </option>
                    ))}
                </select>
              </Field>
              <Button type="submit" isDisabled={busy}>
                创建企业
              </Button>
            </form>
          </Panel>
          <Panel title="企业">
            <DataTable
              columns={["名称", "标识", "状态", "操作"]}
              rows={(extra.data || []).map((t: Row) => [
                t.name,
                t.slug,
                <Status value={t.status} />,
                <Button
                  variant="secondary"
                  onPress={() =>
                    update(
                      `/tenants/${t.id}`,
                      { status: t.status === "active" ? "inactive" : "active" },
                      "更改企业状态将影响全部成员和公开客服入口，确认？",
                    )
                  }
                >
                  {t.status === "active" ? "停用" : "启用"}
                </Button>,
              ])}
            />
          </Panel>
          <Panel title="用户">
            <DataTable
              columns={["名称 / 登录", "UUID", "状态", "操作"]}
              rows={(resource.data || []).map((u: Row) => [
                `${u.display_name} / ${u.login}`,
                u.id,
                <Status value={u.status} />,
                <Button
                  variant="secondary"
                  onPress={() =>
                    update(
                      `/users/${u.id}`,
                      { status: u.status === "active" ? "inactive" : "active" },
                      "确认更改用户状态？",
                    )
                  }
                >
                  {u.status === "active" ? "停用" : "启用"}
                </Button>,
              ])}
            />
          </Panel>
          <p>平台身份不自动获得企业业务权限。当前用户：{user.display_name}</p>
        </>
      )}
    </>
  );
}
