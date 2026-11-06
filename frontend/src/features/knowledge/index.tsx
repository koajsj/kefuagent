import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { EditorModal } from "../../components/EditorModal";
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
} from "../../components/ui";
import { useResource } from "../../hooks/useResource";
import type { Row } from "../../types";
import { collection } from "../../adapters/collection";

export function KnowledgePage() {
  const { api, role, tenant, notify } = useApp();
  const [base, setBase] = useState<Row | null>(null),
    [offset, setOffset] = useState(0),
    [document, setDocument] = useState<Row | null>(null),
    [part, setPart] = useState(0),
    [result, setResult] = useState<Row[] | null>(null),
    [detail, setDetail] = useState<Row | null>(null),
    [creating, setCreating] = useState(false),
    [busy, setBusy] = useState(false);
  const bases = useResource<Row[]>(
    () => collection(api.request.bind(api), "/knowledge-bases"),
    [api, tenant],
  );
  const docs = useResource<Row[]>(
    (signal) =>
      base
        ? api.request(
            `/knowledge-bases/${base.id}/documents?limit=20&offset=${offset}`,
            { signal },
          )
        : Promise.resolve([]),
    [api, tenant, base?.id, offset],
  );
  const chunks = useResource<Row[]>(
    (signal) =>
      document
        ? api.request(
            `/documents/${document.id}/chunks?limit=20&offset=${part}`,
            { signal },
          )
        : Promise.resolve([]),
    [api, tenant, document?.id, part],
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
  const create = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget,
      data = new FormData(form);
    void act(async () => {
      await api.request("/knowledge-bases", {
        method: "POST",
        body: { name: data.get("name"), description: data.get("description") },
      });
      setCreating(false);
      bases.reload();
    });
  };
  const upload = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget,
      data = new FormData(form),
      file = data.get("file") as File;
    if (file.size > 5 * 1024 * 1024) {
      notify("文件超过 5 MiB。");
      return;
    }
    void act(async () => {
      await api.request(`/knowledge-bases/${base!.id}/documents`, {
        method: "POST",
        body: data,
      });
      form.reset();
      notify("文档已上传并处理，请检查处理状态。");
      docs.reload();
    });
  };
  const search = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const query = new FormData(e.currentTarget).get("query");
    void act(async () => {
      setResult(
        await api.request(`/knowledge-bases/${base!.id}/search`, {
          method: "POST",
          body: { query },
        }),
      );
      setDocument(null);
      setDetail(null);
    });
  };
  const removeBase = (b: Row) =>
    void act(async () => {
      const preview = await api.request<Row>(
        `/knowledge-bases/${b.id}?preview=true`,
        { method: "DELETE" },
      );
      if (
        !confirm(
          `确认删除整个知识库及其文档？剩余 ${preview.remaining} 个文档，本次最多清理 ${preview.batch_size} 个。`,
        )
      )
        return;
      let progress: Row | null;
      try {
        progress = await api.request<Row | null>(`/knowledge-bases/${b.id}`, {
          method: "DELETE",
        });
      } catch (error: any) {
        if (error.status === 503) {
          setBase(null);
          bases.reload();
          notify(
            "清理未完成，资料不会重新进入检索。请稍后使用「继续清理」恢复。",
          );
          return;
        }
        throw error;
      }
      notify(
        progress
          ? `本次已清理 ${progress.deleted} 个文档，剩余 ${progress.remaining} 个。请继续清理。`
          : "知识库已删除。",
      );
      setBase(null);
      bases.reload();
    });
  return (
    <>
      <PageHeader
        title="知识库"
        description={
          api.mode === "demo"
            ? "虚构资料演示；上传只模拟状态，不解析或保存文件正文。"
            : "资料按企业隔离，支持文档处理与检索预览。"
        }
        actions={
          role === "admin" && (
            <Button onPress={() => setCreating(!creating)}>创建知识库</Button>
          )
        }
      />
      {creating && (
        <EditorModal
          title="新建知识库"
          onClose={() => {
            if (!busy) setCreating(false);
          }}
        >
          <form onSubmit={create}>
            <Field label="名称">
              <input name="name" required maxLength={120} />
            </Field>
            <Field label="说明">
              <textarea name="description" maxLength={2000} />
            </Field>
            <Button type="submit" isDisabled={busy}>
              创建
            </Button>
          </form>
        </EditorModal>
      )}
      <ErrorNotice error={bases.error} retry={bases.reload} />
      {bases.loading ? (
        <p>加载中…</p>
      ) : !bases.data?.length ? (
        <Empty>还没有知识库。</Empty>
      ) : (
        <DataTable
          columns={["名称", "状态", "操作"]}
          rows={bases.data.map((b) => [
            b.name,
            <Status value={b.status} />,
            <div className="actions">
              {b.status !== "deleting" && (
                <Button
                  variant="secondary"
                  isDisabled={busy}
                  onPress={() => {
                    setBase(b);
                    setOffset(0);
                    setDocument(null);
                    setResult(null);
                    setDetail(null);
                  }}
                >
                  查看资料
                </Button>
              )}
              {role === "admin" && (
                <Button
                  variant="danger"
                  isDisabled={busy}
                  onPress={() => removeBase(b)}
                >
                  {b.status === "deleting" ? "继续清理" : "删除知识库"}
                </Button>
              )}
            </div>,
          ])}
        />
      )}
      {base && (
        <Panel title={base.name}>
          <p>{base.description}</p>
          {role === "admin" && (
            <form onSubmit={upload}>
              <Field label="上传资料（PDF / DOCX / TXT / Markdown，最大 5 MiB）">
                <input
                  type="file"
                  name="file"
                  required
                  accept=".pdf,.docx,.txt,.md,.markdown"
                />
              </Field>
              <Button type="submit" isDisabled={busy}>
                上传并解析
              </Button>
            </form>
          )}
          <ErrorNotice error={docs.error} retry={docs.reload} />
          {docs.loading ? (
            <p>加载中…</p>
          ) : docs.data?.length ? (
            <DataTable
              columns={["文档", "处理状态", "分块", "原因", "操作"]}
              rows={docs.data.map((d) => [
                d.filename,
                <Status value={d.status} />,
                d.chunk_count,
                d.error_category || "—",
                <div className="actions">
                  <Button
                    variant="secondary"
                    isDisabled={busy}
                    onPress={() => {
                      setDetail(d);
                      setDocument(null);
                      setResult(null);
                    }}
                  >
                    信息
                  </Button>
                  <Button
                    variant="secondary"
                    isDisabled={busy}
                    onPress={() => {
                      setDocument(d);
                      setPart(0);
                      setDetail(null);
                      setResult(null);
                    }}
                  >
                    查看分块
                  </Button>
                  {role === "admin" && (
                    <>
                      <Button
                        variant="secondary"
                        isDisabled={busy}
                        onPress={() =>
                          void act(async () => {
                            await api.request(`/documents/${d.id}/reprocess`, {
                              method: "POST",
                            });
                            docs.reload();
                          })
                        }
                      >
                        重新处理
                      </Button>
                      <Button
                        variant="danger"
                        isDisabled={busy}
                        onPress={() => {
                          if (
                            confirm(`删除 ${d.filename}？删除后立即停止检索。`)
                          )
                            void act(async () => {
                              await api.request(`/documents/${d.id}`, {
                                method: "DELETE",
                              });
                              docs.reload();
                            });
                        }}
                      >
                        删除
                      </Button>
                    </>
                  )}
                </div>,
              ])}
            />
          ) : (
            <Empty>尚未上传文档。</Empty>
          )}
          <Pager
            offset={offset}
            count={docs.data?.length || 0}
            size={20}
            onChange={setOffset}
          />
          <form onSubmit={search}>
            <Field label="中文检索预览">
              <input name="query" required maxLength={1000} />
            </Field>
            <Button type="submit" isDisabled={busy}>
              检索
            </Button>
          </form>
          {detail && <JsonView value={detail} />}
          {document && (
            <>
              <h3>{document.filename} · 分块</h3>
              <ErrorNotice error={chunks.error} retry={chunks.reload} />
              {chunks.data?.map((c) => (
                <Panel
                  key={c.id}
                  title={`第 ${c.position + 1} 块${c.page ? ` · 页 ${c.page}` : ""}`}
                >
                  <p>{c.content}</p>
                </Panel>
              ))}
              <Pager
                offset={part}
                count={chunks.data?.length || 0}
                size={20}
                onChange={setPart}
              />
            </>
          )}
          {result &&
            (result.length ? (
              result.map((h) => (
                <Panel key={h.chunk_id} title={h.document_name}>
                  <p>{h.content}</p>
                  <small>
                    分块 {h.chunk_id} · {h.strategy}
                    {h.page ? ` · 页 ${h.page}` : ""}
                  </small>
                </Panel>
              ))
            ) : (
              <Empty>没有找到相关来源。</Empty>
            ))}
        </Panel>
      )}
    </>
  );
}
