import { Button } from "@heroui/react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useApp } from "../../app/context";
import { useResource } from "../../hooks/useResource";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { MemoryConsent, UserMemory as Memory } from "../../types";
import { date } from "../chat/shared";

export function UserMemory() {
  const { api, tenant, notify } = useApp();
  const location = useLocation();
  const [source] = useState<{ source?: string; quote?: string }>(
    () => location.state || {},
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(),
    [editing, setEditing] = useState<Memory | null>(null);
  const consent = useResource(
    (signal) => api.request<MemoryConsent>("/user-memory/consent", { signal }),
    [api, tenant],
  );
  const memories = useResource(
    (signal) => api.request<Memory[]>("/user-memory", { signal }),
    [api, tenant],
  );
  async function action(task: () => Promise<unknown>, message: string) {
    if (busy) return;
    setBusy(true);
    setError(undefined);
    try {
      await task();
      setEditing(null);
      consent.reload();
      memories.reload();
      notify(message);
    } catch (e: any) {
      setError(
        e?.code === "version_conflict"
          ? new Error("记忆已变更，请刷新列表后重新编辑。")
          : e,
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader
        title="个人记忆"
        description="由你明确选择的原文可用于同一企业的后续会话。公开访客不会使用这些记忆。"
      />
      <ErrorNotice error={error} />
      <Panel title="使用同意">
        {consent.loading ? (
          <Loading />
        ) : consent.error ? (
          <ErrorNotice error={consent.error} retry={consent.reload} />
        ) : (
          <>
            <p>
              当前：
              <strong>{consent.data?.enabled ? "已开启" : "已关闭"}</strong>
              。记忆是用户提供的内容，不能替代企业事实或授权。
            </p>
            <p className="page-description">
              关闭会同时删除你在当前企业的全部记忆。已发送的模型请求和已交付的内容无法撤回。
            </p>
            <Button
              variant="secondary"
              isDisabled={busy || consent.loading}
              onPress={() => {
                const enabled = !consent.data?.enabled;
                if (
                  !enabled &&
                  !window.confirm("关闭并删除当前企业的全部个人记忆？")
                )
                  return;
                void action(
                  () =>
                    api.request("/user-memory/consent", {
                      method: "PUT",
                      body: { enabled },
                    }),
                  enabled ? "已开启个人记忆" : "已关闭并删除个人记忆",
                );
              }}
            >
              {consent.data?.enabled ? "关闭并删除记忆" : "开启个人记忆"}
            </Button>
          </>
        )}
      </Panel>
      <Panel title="已保存的记忆">
        {memories.loading ? (
          <Loading />
        ) : memories.error ? (
          <ErrorNotice error={memories.error} retry={memories.reload} />
        ) : !memories.data?.length ? (
          <Empty>暂无有效记忆。</Empty>
        ) : (
          <div className="memory-list">
            {memories.data.map((item) => (
              <article key={item.id} className="memory-entry">
                <div>
                  <strong>{item.memory_key}</strong>
                  <p>{item.quote}</p>
                  <small>
                    来源消息 {item.source_message_id} · 到期{" "}
                    {date(item.expires_at)} · 版本 {item.version}
                  </small>
                </div>
                <div className="actions">
                  <Button
                    variant="secondary"
                    isDisabled={busy || !consent.data?.enabled}
                    onPress={() => setEditing(item)}
                  >
                    修改
                  </Button>
                  <Button
                    variant="secondary"
                    isDisabled={busy}
                    onPress={() => {
                      if (window.confirm(`删除记忆“${item.memory_key}”？`))
                        void action(
                          () =>
                            api.request(
                              `/user-memory/${encodeURIComponent(item.memory_key)}`,
                              { method: "DELETE" },
                            ),
                          "记忆已删除",
                        );
                    }}
                  >
                    删除
                  </Button>
                </div>
              </article>
            ))}
          </div>
        )}
        <div className="actions memory-actions">
          <Button
            variant="secondary"
            isDisabled={busy || !memories.data?.length}
            onPress={() => {
              if (window.confirm("删除当前企业的全部个人记忆？"))
                void action(
                  () => api.request("/user-memory", { method: "DELETE" }),
                  "记忆已清空",
                );
            }}
          >
            清空全部
          </Button>
          <Button
            variant="secondary"
            isDisabled={busy}
            onPress={() =>
              void action(
                () => api.request("/user-memory/cleanup", { method: "POST" }),
                "已请求清理过期记忆",
              )
            }
          >
            清理过期项
          </Button>
        </div>
      </Panel>
      {consent.data?.enabled && (
        <Panel title={editing ? `修改记忆：${editing.memory_key}` : "保存记忆"}>
          <p className="page-description">
            仅可引用本人内部 AI
            会话中已有用户消息的连续原文，不接受访客消息或敏感内容。最多保存 20
            条有效记忆。可从会话中的本人消息选择原文，也可输入来源消息 ID。
          </p>
          <form
            className="memory-form"
            key={editing?.id || "new"}
            onSubmit={(event) => {
              event.preventDefault();
              const values = new FormData(event.currentTarget);
              const key =
                editing?.memory_key || String(values.get("key") || "").trim();
              void action(
                () =>
                  api.request(`/user-memory/${encodeURIComponent(key)}`, {
                    method: "PUT",
                    body: {
                      source_message_id: String(
                        values.get("source") || "",
                      ).trim(),
                      quote: String(values.get("quote") || ""),
                      retention_days: Number(values.get("days")),
                      expected_version: editing?.version ?? null,
                    },
                  }),
                "记忆已保存",
              );
            }}
          >
            {!editing && (
              <label>
                记忆标识
                <input
                  name="key"
                  required
                  maxLength={80}
                  pattern={"[a-zA-Z0-9][a-zA-Z0-9._\\-]*"}
                  title="以字母或数字开头，只能使用字母、数字、点、下划线或连字符"
                />
              </label>
            )}
            <label>
              来源消息 ID
              <input
                name="source"
                required
                defaultValue={editing?.source_message_id || source.source || ""}
                placeholder="内部会话中的用户消息 ID"
              />
            </label>
            <label>
              原文摘录
              <textarea
                name="quote"
                required
                maxLength={300}
                defaultValue={editing?.quote || source.quote || ""}
              />
            </label>
            <label>
              保留天数
              <input
                name="days"
                type="number"
                min={1}
                max={365}
                defaultValue={30}
                required
              />
            </label>
            <div className="actions">
              <Button type="submit" variant="primary" isDisabled={busy}>
                {busy ? "保存中…" : "保存记忆"}
              </Button>
              {editing && (
                <Button
                  variant="secondary"
                  isDisabled={busy}
                  onPress={() => setEditing(null)}
                >
                  取消修改
                </Button>
              )}
            </div>
          </form>
        </Panel>
      )}
    </>
  );
}
