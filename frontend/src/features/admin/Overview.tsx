import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import {
  PageHeader,
  Panel,
  ErrorNotice,
  Field,
  DataTable,
  Empty,
} from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";
const day = (d: Date) => d.toISOString().slice(0, 10);
const number = (value: number | null | undefined) =>
  value == null ? "未知" : value.toLocaleString("zh-CN");
const percent = (value: number | null | undefined) =>
  value == null ? "未知" : `${(value * 100).toFixed(1)}%`;
const seconds = (value: number | null | undefined) =>
  value == null ? "未知" : `${Math.round(value)} 秒`;

export function Dashboard() {
  const { api, tenant, notify } = useApp();
  const end = day(new Date(Date.now() + 86400000));
  const [range, setRange] = useState({
    start: day(new Date(Date.now() - 6 * 86400000)),
    end,
  });
  const data = useResource<Row>(
    (signal) =>
      api.request(
        `/workspace/analytics?${new URLSearchParams({ start: new Date(range.start + "T00:00:00Z").toISOString(), end: new Date(range.end + "T00:00:00Z").toISOString() })}`,
        { signal },
      ),
    [api, tenant, range],
  );
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const d = new FormData(e.currentTarget),
      start = String(d.get("start")),
      end = String(d.get("end"));
    const diff = Date.parse(end) - Date.parse(start);
    if (!Number.isFinite(diff) || diff <= 0 || diff > 90 * 86400000) {
      notify("请选择不超过 90 天的有效 UTC 区间，结束日期不包含在内。");
      return;
    }
    setRange({ start, end });
  };
  const s = data.data,
    c = s?.conversations,
    ai = s?.ai,
    u = s?.usage,
    f = s?.feedback;
  const maxTrend = Math.max(
    1,
    ...(s?.trend || []).map((t: Row) => t.conversations),
  );
  return (
    <>
      <PageHeader
        title="运营概览"
        description="按 UTC 半开区间统计，最多查询 90 天。"
      />
      <form className="filter-toolbar" onSubmit={submit}>
        <Field label="开始日期（UTC，含）">
          <input name="start" type="date" defaultValue={range.start} required />
        </Field>
        <Field label="结束日期（UTC，不含）">
          <input name="end" type="date" defaultValue={range.end} required />
        </Field>
        <Button type="submit">查询</Button>
      </form>
      <ErrorNotice error={data.error} retry={data.reload} />
      {data.loading ? (
        <p>加载中…</p>
      ) : (
        s && (
          <>
            <div className="kpi-row">
              {[
                ["会话", c.total],
                ["待处理", c.pending],
                ["已解决", c.resolved],
                ["超时", c.overdue],
                ["模型调用", u.calls],
                ["失败调用", u.failed],
              ].map(([label, value]) => (
                <Panel key={String(label)} title={String(label)}>
                  <strong className="kpi">{number(value as number)}</strong>
                </Panel>
              ))}
            </div>
            <Panel title="服务与 AI">
              <p>
                平均首次响应 {seconds(c.avg_first_response_seconds)} · 平均解决{" "}
                {seconds(c.avg_resolution_seconds)} · 转人工率{" "}
                {percent(c.handoff_rate)}
              </p>
              <p>
                AI 解决 {number(c.ai_resolved)} · 转人工 {number(c.ai_to_human)}{" "}
                · 未解决 {number(c.ai_unresolved)}
              </p>
              <p>
                检索使用率 {percent(ai.retrieval_use_rate)} · 引用验证率{" "}
                {percent(ai.valid_citation_rate)} · 工具成功率{" "}
                {percent(ai.tool_success_rate)}
              </p>
              <p>引用验证仅表示引用有效，不代表回答正确。</p>
            </Panel>
            <Panel title="每日趋势（UTC）">
              {s.trend.length ? (
                <>
                  <div aria-label="每日会话趋势">
                    {s.trend.map((t: Row) => (
                      <div
                        key={t.day}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "7rem 1fr 4rem",
                          alignItems: "center",
                          gap: "0.75rem",
                          margin: "0.5rem 0",
                        }}
                      >
                        <span>{t.day}</span>
                        <div
                          aria-hidden="true"
                          style={{
                            height: "0.65rem",
                            background: "var(--surface-secondary, #e8e8e8)",
                            borderRadius: "1rem",
                            overflow: "hidden",
                          }}
                        >
                          <div
                            style={{
                              width: `${(t.conversations / maxTrend) * 100}%`,
                              height: "100%",
                              background: "var(--accent, #3b6f66)",
                              borderRadius: "inherit",
                            }}
                          />
                        </div>
                        <span>{number(t.conversations)} 会话</span>
                      </div>
                    ))}
                  </div>
                  <DataTable
                    columns={[
                      "日期",
                      "会话",
                      "AI",
                      "人工",
                      "调用",
                      "已知输入 Token",
                      "已知输出 Token",
                      "用量未知",
                    ]}
                    rows={s.trend.map((t: Row) => [
                      t.day,
                      number(t.conversations),
                      number(t.ai),
                      number(t.human),
                      number(t.calls),
                      number(t.input_tokens),
                      number(t.output_tokens),
                      number(t.unknown_usage_calls),
                    ])}
                  />
                </>
              ) : (
                <Empty>该区间暂无趋势数据。</Empty>
              )}
            </Panel>
            <Panel title="用量与费用">
              <p>
                已知输入 {number(u.input_tokens)} · 已知输出{" "}
                {number(u.output_tokens)} Token ·{" "}
                {number(u.unknown_usage_calls)} 次用量未知
              </p>
              <p>
                已知费用 {number(u.known_cost)} · {number(u.unknown_cost_calls)}{" "}
                次费用未知
              </p>
              {u.models.length ? (
                <DataTable
                  columns={[
                    "模型",
                    "调用",
                    "已知输入 Token",
                    "已知输出 Token",
                    "用量未知",
                  ]}
                  rows={u.models.map((m: Row) => [
                    m.model,
                    number(m.calls),
                    number(m.input_tokens),
                    number(m.output_tokens),
                    number(m.unknown_usage_calls),
                  ])}
                />
              ) : (
                <Empty>暂无模型用量。</Empty>
              )}
            </Panel>
            <Panel title="分类与未解决会话">
              {s.categories.length ? (
                <DataTable
                  columns={["分类", "会话数"]}
                  rows={s.categories.map((x: Row) => [
                    x.category || "未分类",
                    number(x.count),
                  ])}
                />
              ) : (
                <Empty>暂无分类。</Empty>
              )}
              {s.unresolved.length ? (
                <DataTable
                  columns={["未解决会话", "编号"]}
                  rows={s.unresolved.map((x: Row) => [x.subject, x.id])}
                />
              ) : (
                <Empty>暂无未解决会话。</Empty>
              )}
            </Panel>
            <Panel title="访客反馈">
              <p>
                满意 {number(f.satisfied)} · 不满意 {number(f.dissatisfied)} ·
                未评价 {number(f.unrated)} · 满意率{" "}
                {percent(f.satisfaction_rate)}
              </p>
            </Panel>
          </>
        )
      )}
    </>
  );
}
export function Onboarding() {
  const { api, tenant, role, user, notify, refreshSession } = useApp();
  const [busy, setBusy] = useState(false),
    [result, setResult] = useState<Row | null>(null);
  const status = useResource<Row[]>(
    (signal) =>
      role === "admin"
        ? Promise.all(
            ["/workspace", "/setup-status", "/workspace/statistics"].map(
              (path) => api.request<Row>(path, { signal }),
            ),
          )
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
        title="使用向导"
        description="按需完成配置；进度依据当前企业资源。"
      />
      {role === "admin" ? (
        <>
          <ErrorNotice error={status.error} retry={status.reload} />
          <Panel title="快速体验：通用虚构服务资料">
            <p>
              导入内置离线演示知识库、文档和
              Agent，不调用外部模型，也不创建会话或公开入口。
            </p>
            <Button
              isDisabled={busy}
              onPress={() =>
                void act(async () => {
                  setResult(
                    await api.request("/workspace/demo", { method: "POST" }),
                  );
                  status.reload();
                })
              }
            >
              导入离线演示
            </Button>
            {result && (
              <p>
                {result.created ? "已创建" : "已找到"}离线演示资源。文档状态：
                {result.document_status}；知识库 {result.knowledge_base_id}
                ；文档 {result.document_id}；Agent {result.agent_config_id}。
              </p>
            )}
          </Panel>
          <ol className="onboarding-steps">
            {[
              [
                "运行环境",
                "setup",
                status.data?.[1]
                  ? "状态已读取，可查看缺失配置"
                  : "请先检查环境状态",
              ],
              ["企业工作区", "members", "已验证当前企业成员权限，可管理成员"],
              [
                "Provider 与模型",
                "credentials",
                status.data?.[1]?.demo_agents
                  ? "已有离线 Agent；真实 Provider 需单独配置"
                  : "离线体验无需凭证；真实调用需安全配置",
              ],
              [
                "知识与文档",
                "knowledge",
                status.data?.[2]?.documents
                  ? "已有文档，请核对处理状态和检索结果"
                  : "创建知识库并导入资料",
              ],
              [
                "Agent 与授权",
                "agents",
                status.data?.[1]?.enabled_agents
                  ? "已有启用 Agent，请核对知识库与工具授权"
                  : "创建 Agent 并配置授权",
              ],
              [
                "体验客服会话",
                "chat",
                status.data?.[2]?.conversations
                  ? "已有会话，可以继续体验"
                  : "创建会话并发送问题",
              ],
              [
                "发布与网站接入",
                "publications",
                "检查发布状态，再复制公开链接或嵌入代码",
              ],
            ].map(([title, path, description], index) => (
              <li key={path}>
                <span className="step-number">{index + 1}</span>
                <div>
                  <strong>{title}</strong>
                  <p>{description}</p>
                </div>
                <Link to={"/" + path}>查看 →</Link>
              </li>
            ))}
          </ol>
          {status.data?.[1] && (
            <Panel title="工作区状态">
              <p>
                外部模型
                {status.data[1].external_models_enabled ? "已开启" : "已关闭"}
                ；有效凭证 {status.data[1].enabled_credentials}；启用 Agent{" "}
                {status.data[1].enabled_agents}；离线演示{" "}
                {status.data[1].demo_agents}。
              </p>
              <p>
                文档 {status.data[2]?.documents}；会话{" "}
                {status.data[2]?.conversations}。请依次准备知识、配置
                Agent、体验会话并手动发布。
              </p>
            </Panel>
          )}
        </>
      ) : user.is_platform_admin ? (
        <Panel title="创建企业">
          <p>
            平台管理员身份不会自动赋予企业权限。已有企业请先选择有成员权限的企业。
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const d = new FormData(e.currentTarget);
              void act(async () => {
                const created = await api.request<Row>("/tenants", {
                  method: "POST",
                  body: {
                    name: d.get("name"),
                    slug: d.get("slug"),
                    admin_user_id: user.id,
                  },
                });
                await refreshSession(created.id);
              });
            }}
          >
            <Field label="企业名称">
              <input name="name" required maxLength={120} />
            </Field>
            <Field label="唯一标识">
              <input
                name="slug"
                required
                minLength={3}
                maxLength={80}
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
              />
            </Field>
            <Button type="submit" isDisabled={busy}>
              创建企业并进入
            </Button>
          </form>
        </Panel>
      ) : (
        <p>使用向导需要企业管理员权限。</p>
      )}
    </>
  );
}
