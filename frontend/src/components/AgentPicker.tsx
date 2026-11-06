import { useEffect, useState } from "react";
import { useApp } from "../app/context";
import { useResource } from "../hooks/useResource";
import { ErrorNotice, Field, Pager } from "./ui";
import type { Agent } from "../types";
export function AgentPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const { api, tenant } = useApp();
  const [query, setQuery] = useState(""),
    [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Agent | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(query.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);
  const resource = useResource<Agent[]>(
    (signal) =>
      api.request(
        `/agent-configs?${new URLSearchParams({ q: search, limit: "50", offset: String(offset) })}`,
        { signal },
      ),
    [api, tenant, search, offset],
  );
  const rows = resource.data || [],
    options =
      selected && selected.id === value && !rows.some((a) => a.id === value)
        ? [selected, ...rows]
        : rows;
  return (
    <div className="agent-picker">
      <Field label="搜索 Agent">
        <input
          maxLength={120}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="按名称搜索"
          disabled={disabled}
        />
      </Field>
      <Field label="Agent">
        <select
          value={value}
          disabled={disabled}
          onChange={(e) => {
            setSelected(options.find((a) => a.id === e.target.value) || null);
            onChange(e.target.value);
          }}
        >
          <option value="">选择 Agent</option>
          {value && !options.some((a) => a.id === value) && (
            <option value={value}>{value}（已选择）</option>
          )}
          {options.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} · {a.provider}
              {a.enabled ? "" : "（已停用）"}
            </option>
          ))}
        </select>
      </Field>
      {resource.loading && <p role="status">正在读取 Agent…</p>}
      <ErrorNotice error={resource.error} retry={resource.reload} />
      <Pager
        offset={offset}
        count={rows.length}
        size={50}
        onChange={setOffset}
      />
    </div>
  );
}
