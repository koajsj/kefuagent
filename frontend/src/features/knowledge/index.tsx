import { useState, type FormEvent } from "react";
import { Button } from "@heroui/react";
import { ChunkVersions } from "./ChunkVersions";
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
import { explain } from "../../adapters/errors";

function documentNotice(doc: Row, demo: boolean) {
  if (doc.status === "failed") return `文档处理失败：${explain(doc.error_category || "")} 请检查文档状态和原因。`;
  if (doc.status === "ready") return demo ? "演示状态已更新；未解析或保存文件正文。" : "文档处理完成，请检查发布状态。";
  return `文档当前状态：${doc.status || "未知"}，请查看文档列表。`;
}

export function KnowledgePage({ mode }: { mode?: "documents" | "retrieval" }) {
  const { api, role, tenant, notify } = useApp();
  const [base, setBase] = useState<Row | null>(null),
    [offset, setOffset] = useState(0),
    [document, setDocument] = useState<Row | null>(null),
    [part, setPart] = useState(0),
    [generation, setGeneration] = useState(""),
    [result, setResult] = useState<Row[] | null>(null),
    [searchedQuery, setSearchedQuery] = useState(""),
    [detail, setDetail] = useState<Row | null>(null),
    [deletionPlan, setDeletionPlan] = useState<Row | null>(null),
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
            `/documents/${document.id}/chunks?limit=20&offset=${part}${role === "admin" ? `&include_deleted=true${generation ? `&generation=${generation}` : ""}` : ""}`,
            { signal },
          )
        : Promise.resolve([]),
    [api, tenant, document?.id, part, role, generation],
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
      const doc = await api.request<Row>(`/knowledge-bases/${base!.id}/documents`, {
        method: "POST",
        body: data,
      });
      form.reset();
      notify(documentNotice(doc, api.mode === "demo"));
      docs.reload();
    });
  };
  const search = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget),
      query = String(data.get("query") || "").trim(),
      limit = Number(data.get("limit"));
    if (!query) {
      notify("请输入检索内容。");
      return;
    }
    setResult(null);
    setSearchedQuery("");
    void act(async () => {
      setResult(
        await api.request(`/knowledge-bases/${base!.id}/search`, {
          method: "POST",
          body: { query, limit },
        }),
      );
      setSearchedQuery(query);
      setDocument(null);
      setDetail(null);
    });
  };
  const previewDeletion = (path: string) =>
    void act(async () => {
      setDeletionPlan(null);
      const plan = await api.request<Row | null>(`${path}?preview=true`, {
        method: "DELETE",
      });
      if (!plan) {
        notify("对象已不存在，请刷新列表。");
        bases.reload();
        docs.reload();
        return;
      }
      setDeletionPlan(plan);
    });
  return (
    <>
      <PageHeader
        title={mode === "documents" ? "文档与分块" : mode === "retrieval" ? "检索诊断" : "知识库"}
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
                  onPress={() => previewDeletion(`/knowledge-bases/${b.id}`)}
                >
                  删除影响
                </Button>
              )}
            </div>,
          ])}
        />
      )}
      {deletionPlan && (
        <Panel title="删除影响预览">
          <p role="status">物理清理已阻断：历史回答、工具记录和反馈的关联影响尚未完整确认。当前未删除任何文档、分块版本或文件。</p>
          <p>候选文档共 {deletionPlan.remaining} 个，本页展示 {deletionPlan.documents.length} 个；这些文档包含 {deletionPlan.chunk_versions} 个分块版本。</p>
          <p>关联历史记录数量：未知。知识库授权与已有数据保留；分块逻辑删除及版本恢复仍可使用。</p>
          {deletionPlan.documents.length > 0 && <DataTable
            columns={["文档", "状态", "代次"]}
            rows={deletionPlan.documents.map((d: Row) => [d.filename, <Status value={d.status} />, d.generation])}
          />}
          <Button variant="secondary" onPress={() => setDeletionPlan(null)}>关闭预览</Button>
        </Panel>
      )}
      {base && (
        <Panel title={base.name}>
          <p>{base.description}</p>
          {role === "admin" && (
            <form onSubmit={upload}>
              <Field label="上传资料（PDF / DOCX / TXT / Markdown / HTML，最大 5 MiB）">
                <input
                  type="file"
                  name="file"
                  required
                  accept=".pdf,.docx,.txt,.md,.html"
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
                <span>{d.chunk_count} · {d.is_published ? "已发布" : "已撤回 / 未发布"}</span>,
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
                      setGeneration("");
                      setPart(0);
                      setDetail(null);
                      setResult(null);
                    }}
                  >
                    查看分块
                  </Button>
                  {role === "admin" && (
                    <>
                      <Button variant="secondary" isDisabled={busy || (!d.is_published && d.status !== "ready")} onPress={() => void act(async () => {
                        if (!confirm(d.is_published ? "撤回后将停止检索并遮蔽关联历史来源；版本与原文件保留。继续？" : "将此代次当前有效分块发布给已授权 Agent？")) return;
                        await api.request(`/documents/${d.id}/publication`, { method: "POST", body: { expected_generation: d.generation, expected_updated_at: d.updated_at, published: !d.is_published } });
                        setDocument(null); setDetail(null); setResult(null); docs.reload();
                      })}>{d.is_published ? "撤回" : "发布"}</Button>
                      <Button
                        variant="secondary"
                        isDisabled={busy}
                        onPress={() =>
                          void act(async () => {
                            if (!confirm("重新处理会生成新代次，当前人工修订不会自动合并；已有代次保留供管理员查阅。继续？")) return;
                            const updated = await api.request<Row>(`/documents/${d.id}/reprocess`, {
                              method: "POST",
                            });
                            notify(documentNotice(updated, api.mode === "demo"));
                            setDocument(null);
                            setDetail(null);
                            setResult(null);
                            docs.reload();
                          })
                        }
                      >
                        重新处理
                      </Button>
                      <Button
                        variant="danger"
                        isDisabled={busy}
                        onPress={() => previewDeletion(`/documents/${d.id}`)}
                      >
                        删除影响
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
            <Field label="检索预览（中文或英文）">
              <input name="query" required maxLength={1000} />
            </Field>
            <Field label="最多返回分块数（1–10）">
              <input
                name="limit"
                type="number"
                min={1}
                max={10}
                defaultValue={6}
                required
              />
            </Field>
            <Button type="submit" isDisabled={busy}>
              检索
            </Button>
          </form>
          <p>
            {api.mode === "demo"
              ? "演示结果为固定虚构内容，不反映查询或上传的文档。"
              : "仅展示最终命中；分数用于当前查询内排序，不代表答案正确率。候选和过滤原因未提供。"}
          </p>
          {detail && <JsonView value={detail} />}
          {document && (
            <>
              <h3>{document.filename} · 分块</h3>
              {role === "admin" && document.generation >= 1 && <Field label={`查看代次（留空为当前代次 ${document.generation}）`}>
                <input type="number" min={1} max={document.generation} value={generation} onChange={(e) => {
                  const value = e.target.value;
                  if (!value || (Number(value) >= 1 && Number(value) <= document.generation)) { setGeneration(value); setPart(0); }
                }} />
              </Field>}
              <ErrorNotice error={chunks.error} retry={chunks.reload} />
              {chunks.loading && <p>分块加载中…</p>}
              {!chunks.loading && !chunks.error && !chunks.data?.length && (
                <Empty>当前没有可查看的分块，请检查文档处理状态。</Empty>
              )}
              {chunks.data?.map((c) => (
                <Panel
                  key={c.id}
                  title={`第 ${c.position + 1} 块${c.page ? ` · 页 ${c.page}` : ""}${c.generation != null ? ` · 代次 ${c.generation}` : ""}`}
                >
                  <p>{c.is_deleted ? "此分块已删除，不参与检索。" : c.content}</p>
                  <small>修订 {c.revision ?? "未知"} · 分块 ID {c.id}</small>
                  {role === "admin" && <ChunkVersions key={`${tenant}-${document.id}-${c.id}`} documentId={document.id} chunk={c} onChanged={chunks.reload} readOnly={!!generation && Number(generation) !== Number(document.generation)} />}
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
          {result && (
            <h3>“{searchedQuery}”的检索结果 · {result.length} 条</h3>
          )}
          {result &&
            (result.length ? (
              result.map((h, index) => (
                <Panel key={h.chunk_id} title={h.document_name}>
                  <p>{h.content}</p>
                  <small>
                    排名 {index + 1} · 分块 {h.chunk_id} · 策略 {h.strategy}
                    {typeof h.score === "number"
                      ? ` · 分数 ${h.score.toPrecision(4)}`
                      : ""}
                    {h.generation != null ? ` · 版本 ${h.generation}` : ""}
                    {h.page ? ` · 页 ${h.page}` : ""}
                    {h.section ? ` · ${h.section}` : ""}
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
