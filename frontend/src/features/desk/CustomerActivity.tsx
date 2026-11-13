import { Link } from "react-router-dom";
import { useState } from "react";
import { useApp } from "../../app/context";
import { DataTable, ErrorNotice, Loading, Pager, Panel } from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";

export function CustomerActivity({ customer }: { customer: Row }) {
  const { api, tenant } = useApp();
  const [offset, setOffset] = useState(0);
  const activity = useResource<Row[]>((signal) => api.request(`/customers/${customer.id}/activity?limit=10&offset=${offset}`, { signal }), [api, tenant, customer.id, customer.version, offset]);
  const tickets = useResource<Row[]>((signal) => api.request(`/tickets?customer_id=${customer.id}&limit=10`, { signal }), [api, tenant, customer.id]);
  return <div className="desk-detail-grid"><Panel title="客户活动 · 审计元数据">
    <ErrorNotice error={activity.error} retry={activity.reload} />
    {activity.loading ? <Loading /> : !activity.error && <DataTable columns={["动作", "时间", "操作者"]} rows={(activity.data || []).map((row) => [row.action, new Date(row.created_at).toLocaleString(), row.actor_id || "系统"])} />}
    <Pager offset={offset} count={activity.data?.length || 0} size={10} onChange={setOffset} />
    <small>受审计保留策略影响；不是完整业务或隐私导出。</small>
  </Panel><Panel title="近期工单">
    <ErrorNotice error={tickets.error} retry={tickets.reload} />
    {tickets.loading ? <Loading /> : !tickets.error && <DataTable columns={["工单", "状态"]} rows={(tickets.data || []).map((row) => [<Link to="/tickets" state={{ ticketId: row.id }}>{row.title}</Link>, row.status])} />}
    <Link to="/tickets">打开全部工单</Link>
  </Panel></div>;
}
