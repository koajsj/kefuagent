import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { useApp } from "../../app/context";
import { DataTable, Empty, ErrorNotice, Field, JsonView, Loading, PageHeader, Pager, Panel, Status } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";

export function SecurityControls({ page }: { page: string }) {
  const { api } = useApp();
  if (api.mode === "demo") return <><PageHeader title="安全执行控制" /><Empty>NOT_AVAILABLE：离线 Demo 不模拟审批授权、金额账本或网站身份。请连接正式 API 管理。</Empty></>;
  return <SecurityPage key={page} page={page} />;
}

function SecurityPage({ page }: { page: string }) {
  const { api, tenant, user, role } = useApp();
  const [offset, setOffset] = useState(0), [error, setError] = useState<unknown>(), [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<any>(null), [assessment, setAssessment] = useState<any>(null), [created, setCreated] = useState<any>(null);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const titles: Record<string, string> = { erasure: "数据擦除管理", approvals: "R3 审批中心", budget: "金额预算与账本", "widget-sites": "可信 Widget 网站" };
  const resource = useResource<any>((signal) => api.request(`/security/${page}${page === "budget" ? "" : `?limit=25&offset=${offset}`}`, { signal }), [api, tenant, page, offset]);
  const costs = useResource<Row[]>((signal) => page === "budget" ? api.request(`/security/costs?limit=25&offset=${offset}`, { signal }) : Promise.resolve([]), [api, tenant, page, offset]);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true); setError(undefined);
    try { await fn(); resource.reload(); if (page === "budget") costs.reload(); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  }
  async function erase(event: FormEvent<HTMLFormElement>, preview: boolean) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = { subject_type: form.get("subject_type"), subject_id: form.get("subject_id") };
    await action(async () => { const result = await api.request(`/security/erasure${preview ? "/preview" : ""}`, { method: "POST", body }); setAssessment(preview ? result : result.assessment); });
  }
  async function proposal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    await action(async () => {
      await api.request("/security/approvals", { method: "POST", body: { tool_id: form.get("tool_id"), conversation_id: form.get("conversation_id"), agent_config_id: form.get("agent_config_id"), arguments: JSON.parse(String(form.get("arguments"))), idempotency_key: requestKey, expires_in_minutes: 30 } });
      setRequestKey(crypto.randomUUID());
    });
  }
  async function decision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    await action(async () => { await api.request(`/security/approvals/${selected.approval.id}/decision`, { method: "POST", body: { expected_digest: selected.approval.payload_digest, decision: form.get("decision"), reason: form.get("reason") } }); setSelected(null); });
  }
  async function budget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    await action(() => api.request("/security/budget", { method: "PUT", body: { expected_version: resource.data?.policy?.version || 0, enabled: form.has("enabled"), currency: form.get("currency"), ...Object.fromEntries(["run_limit", "daily_limit", "monthly_limit", "total_limit"].map(k => [k, form.get(k)])), agent_limits: JSON.parse(String(form.get("agent_limits"))) } }));
  }
  async function site(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    await action(async () => { setCreated(await api.request("/security/widget-sites", { method: "POST", body: { publication_id: form.get("publication_id"), origin: form.get("origin") } })); });
  }
  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    await action(async () => { await api.request(`/security/widget-sites/${selected.id}/verify`, { method: "POST", body: { challenge: form.get("challenge") } }); setSelected(null); });
  }
  return <>
    <PageHeader title={titles[page]} description="服务端权限、资源版本和事务执行控制；当前运行时验收 NEEDS_RUNTIME_VERIFICATION。" actions={<Button variant="secondary" isDisabled={busy} onPress={() => { setSelected(null); resource.reload(); costs.reload(); }}>刷新</Button>} />
    <ErrorNotice error={error} /><ErrorNotice error={resource.error} retry={resource.reload} />
    {resource.loading ? <Loading /> : !resource.error && resource.data && <>
      {page === "erasure" && <>
        <Panel title="删除影响预览与阻断登记"><p>完整擦除 BLOCKED。依赖未确认的请求不会获准清理或阻断访问，不执行局部删除；登记和重试只重新评估，不代表已受理擦除。</p>
          <form onSubmit={e => erase(e, true)} className="form-grid"><Field label="数据主体"><select name="subject_type"><option value="conversation">会话</option><option value="customer">客户</option><option value="user">用户</option></select></Field><Field label="主体 ID"><input name="subject_id" required /></Field><div className="form-actions"><Button type="submit" isDisabled={busy}>预览影响</Button></div></form>
          {assessment && <><JsonView value={assessment} /><Button variant="secondary" isDisabled={busy} onPress={() => action(async () => { const r = await api.request("/security/erasure", { method: "POST", body: { subject_type: assessment.subject_type, subject_id: assessment.subject_id } }); setAssessment(r.assessment); })}>登记 / 重新评估此请求</Button></>}
        </Panel>
        <DataTable columns={["主体", "ID", "状态", "评估次数", "详情"]} rows={resource.data.map((r: Row) => [r.subject_type, r.subject_id, <Status value={r.status} />, r.attempts, <Button variant="secondary" isDisabled={busy} onPress={() => setAssessment(r.assessment)}>阻断原因</Button>])} />
      </>}
      {page === "approvals" && <>
        <Panel title="申请具体操作"><p>仅支持已授权且声明为高风险的固定工单/交接/站内提醒工具。有效期 30 分钟；任何参数、策略或资源版本变化均不能沿用批准。</p><form onSubmit={proposal} className="form-grid">{["tool_id", "agent_config_id", "conversation_id"].map(k => <Field key={k} label={k}><input name={k} required /></Field>)}<Field label="精确工具参数 JSON"><textarea name="arguments" required defaultValue="{}" rows={5} /></Field><Button type="submit" isDisabled={busy}>提交审批申请</Button></form></Panel>
        <DataTable columns={["申请", "申请人", "状态", "有效期", "详情"]} rows={resource.data.map((r: Row) => [r.id, r.requested_by, <Status value={r.status} />, r.expires_at, <Button variant="secondary" isDisabled={busy} onPress={() => action(async () => setSelected(await api.request(`/security/approvals/${r.id}`)))}>审阅操作</Button>])} />
        {selected?.approval && <Panel title="操作审阅"><JsonView value={selected} /><p>审批只对上方精确摘要与资源版本有效；执行会再次检查双方权限。审批理由不要填写客户正文或秘密。</p>
          {role === "admin" && selected.approval.requested_by !== user.id && ["PENDING_APPROVAL", "APPROVED"].includes(selected.approval.status) && <form onSubmit={decision} className="form-grid"><Field label="决定"><select name="decision">{selected.approval.status === "PENDING_APPROVAL" && <><option value="APPROVED">批准</option><option value="REJECTED">拒绝</option></>}<option value="REVOKED">撤销</option></select></Field><Field label="审批理由"><textarea name="reason" required maxLength={1000} /></Field><Button type="submit" isDisabled={busy}>提交决定</Button></form>}
          {selected.approval.requested_by === user.id && selected.approval.status === "APPROVED" && <Button isDisabled={busy} onPress={() => action(async () => { const r = await api.request(`/security/approvals/${selected.approval.id}/execute`, { method: "POST" }); setSelected({ ...(await api.request(`/security/approvals/${selected.approval.id}`)), execution_result: r }); })}>执行已批准操作</Button>}
        </Panel>}
      </>}
      {page === "budget" && <>
        <Panel title="执行层金额限额"><p>未配置或关闭时禁止付费调用。日/月按 UTC；未知用量跨期持续占用。限额为内部定价控制，不是供应商最终账单保证。价格需由部署者确认成本上界和有效期；保存即审阅并绑定当前价格目录。</p><Status value={resource.data.admission_state} /><JsonView value={{ remaining: resource.data.remaining, usage: resource.data.usage, currency: resource.data.policy?.currency ?? "UNKNOWN", price_catalog_digest: resource.data.price_catalog_digest }} />
          <form key={resource.data.policy?.version || 0} onSubmit={budget} className="form-grid"><Field label="启用付费调用"><input name="enabled" type="checkbox" defaultChecked={resource.data.policy?.enabled || false} /></Field><Field label="币种（已有账本后不可变）"><input name="currency" required pattern="[A-Z]{3}" defaultValue={resource.data.policy?.currency || ""} /></Field>{[["run_limit", "单次 Run"], ["daily_limit", "单日"], ["monthly_limit", "单月"], ["total_limit", "系统累计"]].map(([k,l]) => <Field key={k} label={l + "金额上限"}><input name={k} required inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,12})?" defaultValue={resource.data.policy?.[k] ?? ""} /></Field>)}<Field label="Agent 独立累计限额（ID → 金额字符串 JSON）"><textarea name="agent_limits" defaultValue={JSON.stringify(resource.data.policy?.agent_limits || {})} rows={3} /></Field><Button type="submit" isDisabled={busy}>保存限额与价格目录版本</Button></form><JsonView value={resource.data.prices} />
        </Panel><ErrorNotice error={costs.error} retry={costs.reload} />{costs.loading ? <Loading /> : !costs.error && <DataTable columns={["调用 / 步骤", "状态", "预留", "占用 / 结算", "币种", "时间"]} numericColumns={[2,3]} rows={(costs.data || []).map(r => [`${r.model_call_id} / ${r.step_index}`, <Status value={r.status} />, r.reserved, r.charged, r.currency, r.created_at])} />}
      </>}
      {page === "widget-sites" && <>
        <Panel title="登记 HTTPS 网站"><p>域名文件验证与网站后端 HMAC 签名共同约束来源。公共 ID 不是秘密；签名密钥只能放在网站后端。未验证、停用、过期或版本变化会拒绝旧会话。</p><form onSubmit={site} className="form-grid"><Field label="发布 ID"><input name="publication_id" required /></Field><Field label="精确 HTTPS 来源"><input name="origin" type="url" required placeholder="https://support.example.com" /></Field><Button type="submit" isDisabled={busy}>登记网站</Button></form></Panel>
        {created && <Panel title="仅本次显示的网站密钥（登记回执）"><p>将 challenge 作为纯文本发布到 verification_url。server_secret 只保存至网站后端密钥配置，禁止进入 HTML、前端配置或日志。关闭本页后不会再次返回。回执不是当前签名模板；启用后重新获取接入配置。</p><JsonView value={created} /><Button variant="secondary" onPress={() => setCreated(null)}>清除本页显示</Button></Panel>}
        <DataTable columns={["网站 / ID", "启用", "验证有效期", "版本", "操作"]} rows={resource.data.map((r: Row) => [`${r.origin} / ${r.id}`, r.enabled ? "启用" : "停用", r.verification_expires_at || "未验证", r.version, <div className="form-actions"><Button variant="secondary" isDisabled={busy} onPress={() => action(async () => setSelected({ ...r, integration: await api.request(`/security/widget-sites/${r.id}/integration`) }))}>验证 / 接入</Button><Button variant="secondary" isDisabled={busy || (!r.enabled && (!r.verification_expires_at || new Date(r.verification_expires_at) <= new Date()))} onPress={() => action(async () => { await api.request(`/security/widget-sites/${r.id}`, { method: "PATCH", body: { expected_version: r.version, enabled: !r.enabled } }); setSelected(null); })}>{r.enabled ? "停用并撤销会话" : "启用"}</Button><Button variant="secondary" isDisabled={busy} onPress={() => action(async () => { setCreated(await api.request(`/security/widget-sites/${r.id}/challenge`, { method: "POST" })); setSelected(null); })}>轮换密钥 / 重新验证</Button></div>])} />
        {selected?.origin && <Panel title={`验证与接入 ${selected.origin}`}><JsonView value={selected.integration} /><p>网站后端用以上配置和仅显示一次的密钥签发 60 秒内的 HMAC 断言；nonce 每次随机生成且不能重复。签发接口必须执行网站自身的可信会话、CSRF 和滥用防护。</p><SiteEmbed config={selected.integration} /><form onSubmit={verify} className="form-grid"><Field label="已发布的 challenge"><input name="challenge" required minLength={40} maxLength={100} autoComplete="off" defaultValue={created?.site?.id === selected.id ? created.challenge : ""} /></Field><Button type="submit" isDisabled={busy}>验证 HTTPS 文件</Button></form></Panel>}
      </>}
      {page !== "budget" && <Pager offset={offset} size={25} count={resource.data.length} onChange={setOffset} />}
      {page === "budget" && <Pager offset={offset} size={25} count={costs.data?.length || 0} onChange={setOffset} />}
    </>}
  </>;
}

function SiteEmbed({ config }: { config: any }) {
  const [path, setPath] = useState("");
  if (!config) return null;
  const valid = /^\/(?!\/)[A-Za-z0-9_/-]+$/.test(path);
  return <><Field label="网站已实现的同源签发接口路径"><input value={path} onChange={e => setPath(e.target.value)} placeholder="/api/support/bootstrap" /></Field>{valid && <Field label="网站嵌入代码（保存配置后重新获取版本）"><textarea readOnly rows={4} value={`<script src="${config.aud}/widget.js" data-agent="${config.publication_id}" data-site="${config.site_id}" data-bootstrap-url="${path}" defer></script>`} /></Field>}</>;
}
