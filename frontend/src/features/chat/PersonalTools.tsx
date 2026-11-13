import { Button } from "@heroui/react";
import { useState } from "react";
import { useApp } from "../../app/context";

type Item = { name: string; value: string };

function PersonalItems({ kind, onApply, currentValue }: { kind: "views" | "replies"; onApply: (value: string) => void; currentValue?: string }) {
  const { api, tenant, user } = useApp();
  const key = `${api.mode === "demo" ? "kefu.static-demo." : ""}support.personal.${api.mode}.${encodeURIComponent(tenant)}.${encodeURIComponent(user.id)}.${kind}`;
  const [items, setItems] = useState<Item[]>(() => {
    try {
      const value: unknown = JSON.parse((api.mode === "demo" ? sessionStorage : localStorage).getItem(key) || "[]");
      return Array.isArray(value) ? value.filter((item): item is Item => item && typeof item.name === "string" && item.name.length <= 60 && typeof item.value === "string" && item.value.length <= 4000).slice(0, 100) : [];
    } catch { return []; }
  });
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  function save(next: Item[]) {
    try { (api.mode === "demo" ? sessionStorage : localStorage).setItem(key, JSON.stringify(next)); setItems(next); setError(""); return true; }
    catch { setError("浏览器存储不可用，未保存更改。"); return false; }
  }
  return <details>
    <summary>{kind === "views" ? "个人会话视图" : "个人快捷回复"}</summary>
    <p className="note">{api.mode === "demo" ? "仅保存在当前演示标签页" : "仅保存在当前浏览器"}，按账号和工作区区分，不会同步或共享；请勿保存敏感信息。</p>
    {items.map((item, index) => <div className="actions" key={`${item.name}-${index}`}>
      <Button variant="secondary" onPress={() => onApply(item.value)}>{item.name}</Button>
      <Button variant="secondary" aria-label={`删除 ${item.name}`} onPress={() => save(items.filter((_, i) => i !== index))}>删除</Button>
    </div>)}
    <label>名称<input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} /></label>
    {kind === "replies" && <label>回复内容<textarea value={value} onChange={(e) => setValue(e.target.value)} maxLength={4000} /></label>}
    {kind === "replies" && <p className="note">支持变量 {"{{会话标题}}"}、{"{{客服姓名}}"}；插入后可编辑，需手动发送。</p>}
    <Button variant="secondary" onPress={() => {
      const nextValue = kind === "views" ? currentValue || "" : value.trim();
      if (!name.trim() || !nextValue) { setError("请填写名称和内容。"); return; }
      if (items.length >= 100) { setError("每类最多保存 100 项，请先删除不用的项目。"); return; }
      if (items.some((item) => item.name === name.trim())) { setError("名称已存在，请先删除原项。"); return; }
      if (save([...items, { name: name.trim(), value: nextValue }])) { setName(""); if (kind === "replies") setValue(""); }
    }} isDisabled={kind === "views" && !currentValue}>{kind === "views" ? "保存当前筛选" : "保存回复"}</Button>
    {error && <p className="error" role="alert">{error}</p>}
  </details>;
}

export function PersonalViews({ filters, onApply }: { filters: Record<string, string>; onApply: (filters: Record<string, string>) => void }) {
  return <ViewItems filters={filters} onApply={onApply} />;
}

function ViewItems({ filters, onApply }: { filters: Record<string, string>; onApply: (filters: Record<string, string>) => void }) {
  // The value to save is supplied by the current applied filter, not an unsubmitted form.
  return <PersonalItems kind="views" currentValue={JSON.stringify(filters)} onApply={(value) => {
    try {
      const parsed: unknown = JSON.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
      const allowed = ["q", "queue", "assignee_id", "priority", "sort", "tag"];
      onApply(Object.fromEntries(Object.entries(parsed).filter(([key, val]) => allowed.includes(key) && typeof val === "string")) as Record<string, string>);
    } catch { /* Ignore malformed browser data. */ }
  }} />;
}

export function PersonalReplies({ subject, operator, onInsert }: { subject: string; operator: string; onInsert: (value: string) => void }) {
  return <PersonalItems kind="replies" onApply={(value) => onInsert(value.replace(/\{\{(会话标题|客服姓名)\}\}/g, (_, key: string) => key === "会话标题" ? subject : operator))} />;
}
