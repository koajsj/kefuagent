import type { Adapter, RequestOptions, Row } from "../types";
import { sessionState } from "./storage";
const KEY = "kefu.react.demo.v1";
import {
  uuid,
  now,
  fail,
  seed,
  tenantId,
  userId,
  agentId,
  kbId,
  type State,
} from "./demo-data";
class DemoAdapter implements Adapter {
  readonly mode = "demo";
  private state: State = seed();
  private tenant = tenantId;
  private generation = 0;
  constructor() {
    this.restore();
  }
  private restore() {
    try {
      const saved = sessionState.get(KEY);
      if (saved) this.state = JSON.parse(saved);
    } catch {
      /* Corrupt demo state resets only fictional session data. */
    }
  }
  setTenant(id: string) {
    this.tenant = id;
    this.generation++;
  }
  onUnauthorized(_callback: () => void) {}
  private save() {
    sessionState.set(KEY, JSON.stringify(this.state));
  }
  private rows(table: string) {
    return (this.state.tables[table] ||= []).filter(
      (r) => !r.tenant_id || r.tenant_id === this.tenant,
    );
  }
  async request<T = any>(
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    if (!path.startsWith("/") || path.startsWith("//") || /https?:/i.test(path))
      fail(400, "demo_network_denied", "Demo 不接受外部 API 地址。");
    if (options.signal?.aborted)
      throw new DOMException("Aborted", "AbortError");
    const epoch = this.generation,
      publicPath = path.startsWith("/public/");
    // Same-origin Widget frames share sessionStorage, but have separate adapters.
    // Read, mutate and persist synchronously so polling cannot overwrite new data.
    this.restore();
    const value = this.route(path, options);
    this.save();
    if (options.signal?.aborted)
      throw new DOMException("Aborted", "AbortError");
    if (!publicPath && epoch !== this.generation)
      throw Object.assign(new Error("上下文已切换"), { name: "StaleResponse" });
    return structuredClone(value) as T;
  }
  private page(rows: Row[], query: URLSearchParams) {
    const offset = Number(query.get("offset") || 0),
      limit = Number(query.get("limit") || 50);
    return rows.slice(offset, offset + limit);
  }
  private route(path: string, options: RequestOptions): any {
    const [pathname, search = ""] = path.split("?"),
      parts = pathname.split("/").filter(Boolean),
      query = new URLSearchParams(search),
      method = options.method || "GET",
      body = (options.body || {}) as Record<string, any>,
      state = this.state;
    const own = (table: string, id: string) =>
      this.rows(table).find((r) => r.id === id) ||
      fail(404, "not_found", "演示资源不存在或不属于当前工作区。");
    const create = (table: string, values: Record<string, any>) => {
      const row = {
        id: uuid(),
        tenant_id: this.tenant,
        created_at: now(),
        updated_at: now(),
        ...values,
      };
      (state.tables[table] ||= []).push(row);
      this.audit("create", table, row.id);
      return row;
    };
    if (pathname === "/web-session" || pathname === "/auth/logout") return null;
    if (pathname === "/auth/me") return state.tables.users[0];
    if (pathname === "/health")
      return { status: "ok", database: "static-demo" };
    if (pathname === "/workspace")
      return {
        tenant_id: this.tenant,
        user_id: userId,
        role: "admin",
        external_models_enabled: false,
      };
    if (parts[0] === "user-memory") return this.memory(parts[1], method, body);
    if (pathname === "/setup-status")
      return {
        external_models_enabled: false,
        credential_encryption_ready: false,
        public_rate_key_ready: true,
        model_allowed_hosts: [],
        enabled_credentials: 0,
        enabled_agents: this.rows("agent-configs").filter((a) => a.enabled)
          .length,
        demo_agents: this.rows("agent-configs").filter(
          (a) => a.provider === "demo",
        ).length,
        web_origin: location.origin,
        real_model_verified: false,
      };
    if (pathname === "/workspace/demo") {
      let base = this.rows("knowledge-bases").find(
        (b) => b.demo_import === true || b.id === kbId,
      );
      let agent = this.rows("agent-configs").find(
        (a) => a.demo_import === true || a.id === agentId,
      );
      const created = !base || !agent;
      if (!base)
        base = create("knowledge-bases", {
          name: "虚构服务指南",
          description: "静态演示资料",
          status: "active",
          demo_import: true,
        });
      let doc = this.rows("documents").find(
        (d) => d.knowledge_base_id === base!.id,
      );
      if (!doc)
        doc = create("documents", {
          knowledge_base_id: base.id,
          filename: "演示指南.md",
          status: "ready",
          chunk_count: 1,
        });
      if (!agent)
        agent = create("agent-configs", {
          ...seed().tables["agent-configs"][0],
          id: uuid(),
          tenant_id: this.tenant,
          demo_import: true,
        });
      state.bindings[agent.id] ||= [base.id];
      return {
        knowledge_base_id: base.id,
        document_id: doc.id,
        agent_config_id: agent.id,
        document_status: doc.status,
        created,
        offline: true,
      };
    }
    if (pathname === "/workspace/operators")
      return state.tables.users
        .filter((u) =>
          this.rows("memberships").some(
            (m) => m.user_id === u.id && m.status === "active",
          ),
        )
        .map((u) => ({ id: u.id, display_name: u.display_name }));
    if (pathname === "/workspace/statistics")
      return {
        agents: this.rows("agent-configs").length,
        conversations: this.rows("conversations").length,
        documents: this.rows("documents").length,
        tool_executions: this.rows("tool-executions").length,
        model_calls: this.rows("model-calls").length,
        known_input_tokens: 0,
        known_output_tokens: 0,
        calls_with_unknown_usage: this.rows("model-calls").length,
        failed_calls: 0,
        cost: null,
      };
    if (pathname === "/workspace/analytics") return this.analytics(query);
    if (pathname === "/usage-limits")
      return {
        demo: true,
        external_models_enabled: false,
        tenant: { requests_per_minute: 20, max_concurrent: 2 },
        note: "静态演示，无真实用量或费用。",
      };
    if (pathname === "/tool-capabilities")
      return this.rows("tools").map(({ id, tenant_id, ...t }) => t);
    if (parts[0] === "public") {
      const pub = (state.tables.publications || []).find(
        (p) => p.id === parts[1],
      );
      if (
        !pub ||
        !pub.enabled ||
        pub.revoked_at ||
        !pub.available ||
        pub.requires_republish
      )
        fail(
          403,
          "visitor_access_revoked",
          "演示入口已下线、撤销或配置发生变化。",
        );
      if (parts.length === 2)
        return {
          id: pub.id,
          name: pub.name,
          version: pub.version,
          mode: "demo",
        };
      if (parts.length === 3 && parts[2] === "sessions" && method === "POST") {
        const visitor = {
          id: uuid(),
          token: uuid() + uuid(),
          expires_at: new Date(Date.now() + 3600000).toISOString(),
          publication_id: pub.id,
          version: pub.version,
          conversation_id: uuid(),
          tenant_id: pub.tenant_id,
        };
        state.visitors.push(visitor);
        state.tables.conversations.push({
          id: visitor.conversation_id,
          tenant_id: pub.tenant_id,
          subject: "来自公开入口的演示访客",
          channel: "public",
          status: "open",
          support_state: "ai",
          handling_mode: "ai",
          priority: "normal",
          version: 1,
          tags: [],
          created_at: now(),
        });
        state.messages[visitor.conversation_id] = [];
        return {
          id: visitor.id,
          token: visitor.token,
          expires_at: visitor.expires_at,
        };
      }
      const visitor = state.visitors.find(
        (v) =>
          v.id === parts[3] &&
          v.publication_id === pub.id &&
          v.token === options.visitorToken &&
          v.version === pub.version &&
          v.expires_at > now(),
      );
      if (!visitor)
        fail(
          401,
          "visitor_authentication_required",
          "演示访客会话已失效，请重新开始。",
        );
      const conversation = state.tables.conversations.find(
        (c) => c.id === visitor.conversation_id,
      )!;
      const resource = parts[4];
      if (resource === "messages") {
        options.onHeaders?.(
          new Headers({ "X-Conversation-Status": conversation.status }),
        );
        return this.history(conversation.id, query).map(
          ({ metadata, ...m }) => m,
        );
      }
      if (resource === "end") {
        visitor.expires_at = now();
        conversation.status = "closed";
        return null;
      }
      if (resource === "feedback") {
        if (method === "POST")
          visitor.feedback = { ...body, created_at: now() };
        return visitor.feedback || null;
      }
      if (resource === "status")
        return (
          this.rowsForTenant("model-calls", pub.tenant_id)
            .filter((c) => c.conversation_id === conversation.id)
            .at(-1) || null
        );
      if (resource === "turns")
        return this.turn(
          conversation,
          { ...body, agent_config_id: pub.agent_config_id },
          options,
        );
      fail(404, "not_found", "演示公开功能不存在。");
    }
    if (parts[0] === "agent-configs" && parts[2] === "knowledge-bases") {
      const agent = own("agent-configs", parts[1]);
      if (method === "PUT") {
        this.version(agent, body);
        state.bindings[agent.id] = body.knowledge_base_ids;
        agent.version++;
        this.invalidate(agent.id);
      }
      return {
        knowledge_base_ids: state.bindings[agent.id] || [],
        config_version: agent.version,
      };
    }
    if (parts[0] === "agent-configs" && parts[2] === "tools") {
      const agent = own("agent-configs", parts[1]);
      const grants = (state.grants[agent.id] ||= []);
      if (method === "PUT") {
        own("tools", parts[3]);
        const grant = grants.find((g) => g.tool_id === parts[3]);
        if (grant) grant.enabled = body.enabled;
        else
          grants.push({
            id: uuid(),
            tool_id: parts[3],
            agent_config_id: agent.id,
            enabled: body.enabled,
          });
        this.invalidate(agent.id);
      }
      return parts[3] ? grants.find((g) => g.tool_id === parts[3]) : grants;
    }
    if (parts[0] === "agent-configs" && parts[2] === "test-connection")
      fail(
        403,
        "demo_external_disabled",
        "静态 Demo 不连接模型，连接测试仅在正式模式可用。",
      );
    if (parts[0] === "knowledge-bases" && parts[2] === "documents") {
      own("knowledge-bases", parts[1]);
      if (method === "POST") {
        const file = (options.body as FormData).get("file") as File;
        if (!file || file.size > 5 * 1024 * 1024)
          fail(422, "invalid_file", "请选择不超过 5 MiB 的演示文件。");
        return create("documents", {
          knowledge_base_id: parts[1],
          filename: file.name,
          status: "ready",
          chunk_count: 1,
          error_category: null,
          demo_notice: "仅演示上传状态，不解析文件正文。",
        });
      }
      return this.page(
        this.rows("documents").filter((d) => d.knowledge_base_id === parts[1]),
        query,
      );
    }
    if (parts[0] === "knowledge-bases" && parts[2] === "search") {
      own("knowledge-bases", parts[1]);
      return [
        {
          chunk_id: "demo-chunk",
          document_id: "demo-doc",
          document_name: "星河服务指南.md",
          content:
            "这是虚构演示资料：团队工作区支持导入 TXT、Markdown、PDF 和 DOCX，资料不足时请联系人工客服。",
          score: 1,
          strategy: "static-demo",
          page: null,
        },
      ];
    }
    if (parts[0] === "documents" && parts[2] === "chunks") {
      const doc = own("documents", parts[1]);
      return [
        {
          id: "demo-chunk",
          document_id: doc.id,
          position: 0,
          content:
            "虚构演示资料。团队工作区支持文档知识库、人工协作和网站客服接入。",
          page: null,
        },
      ];
    }
    if (parts[0] === "documents" && parts[2] === "reprocess") {
      const doc = own("documents", parts[1]);
      doc.status = "ready";
      return doc;
    }
    if (parts[0] === "model-calls" && parts[2] === "cost") {
      const call = own("model-calls", parts[1]);
      return {
        call_id: call.id,
        kind: call.kind || "agent",
        basis: "deployment_price_estimate_not_invoice",
        complete: false,
        unknown_steps: 1,
        known_subtotals: {},
        total: null,
        currency: null,
        steps: [
          {
            index: 0,
            model: "static-demo",
            provider: "demo",
            purpose: "agent",
            input_tokens: null,
            output_tokens: null,
            usage_complete: false,
            amount: null,
            currency: null,
            price_source: null,
            status: "unknown_usage",
          },
        ],
        demo_notice: "静态模拟没有真实 Token 或账单。",
      };
    }
    if (parts[0] === "conversations" && parts[1]) {
      const c = own("conversations", parts[1]),
        sub = parts[2];
      if (sub === "messages") {
        if (method === "POST") {
          if (c.status === "closed")
            fail(409, "conversation_closed", "会话已结束。");
          const m = { id: uuid(), ...body, created_at: now() };
          (state.messages[c.id] ||= []).push(m);
          this.audit("message", "conversation", c.id);
          return m;
        }
        return this.history(c.id, query);
      }
      if (sub === "collaboration") {
        const notes = (state.notes[c.id] ||= []);
        if (method === "POST") {
          const note = {
            id: uuid(),
            kind: "note",
            actor_id: userId,
            ...body,
            details: {},
            created_at: now(),
          };
          notes.unshift(note);
          return note;
        }
        let rows = notes;
        const before = query.get("before");
        if (before) {
          const index = rows.findIndex((n) => n.id === before);
          if (index < 0) fail(404, "invalid_cursor", "协作游标不存在。");
          rows = rows.slice(index + 1);
        }
        return this.page(rows, query);
      }
      if (sub === "summary")
        return {
          id: "demo-summary",
          version: 1,
          content: JSON.stringify([
            {
              message_id: state.messages[c.id]?.[0]?.id,
              quote: state.messages[c.id]?.[0]?.content,
              kind: "user_report",
            },
          ]),
          source_count: 1,
          created_at: now(),
        };
      if (sub === "operations") {
        this.version(c, body);
        Object.assign(c, body, { version: c.version + 1, updated_at: now() });
        delete c.expected_version;
        this.audit("operations", "conversation", c.id);
        return c;
      }
      if (sub === "handling") {
        this.version(c, body);
        c.support_state = body.state;
        c.handling_mode = body.state === "ai" ? "ai" : "human";
        c.status = body.state === "resolved" ? "closed" : "open";
        c.version++;
        return c;
      }
      if (sub === "calls")
        return this.page(
          this.rows("model-calls")
            .filter((call) => call.conversation_id === c.id)
            .reverse(),
          query,
        );
      if (sub === "runs")
        return (
          this.rows("model-calls").find(
            (call) => call.id === parts[3] && call.conversation_id === c.id,
          ) || null
        );
      if (sub === "agent-turns" || sub === "chat")
        return this.turn(c, body, options);
      if (method === "PATCH") {
        Object.assign(c, body, { version: c.version + 1, updated_at: now() });
        return c;
      }
      if (!sub) return c;
    }
    const table = parts[0];
    if (
      ![
        "users",
        "tenants",
        "memberships",
        "agent-configs",
        "knowledge-bases",
        "documents",
        "tools",
        "publications",
        "conversations",
        "model-calls",
        "tool-executions",
        "audit-events",
        "model-credentials",
      ].includes(table)
    )
      fail(404, "demo_not_implemented", "静态 Demo 不支持此操作：" + pathname);
    if (parts[1]) {
      const row = own(table, parts[1]);
      if (method === "DELETE") {
        if (query.get("preview") === "true")
          return {
            remaining: this.rows("documents").filter(
              (d) => d.knowledge_base_id === row.id,
            ).length,
            batch_size: 50,
          };
        if (table === "publications") {
          row.revoked_at = now();
          row.available = false;
          row.enabled = false;
          return null;
        }
        state.tables[table] = state.tables[table].filter((r) => r !== row);
        if (table === "knowledge-bases")
          state.tables.documents = state.tables.documents.filter(
            (d) => d.knowledge_base_id !== row.id,
          );
        return null;
      }
      if (["PUT", "PATCH"].includes(method)) {
        this.version(row, body);
        const next = { ...body };
        delete next.expected_version;
        delete next.api_key;
        delete next.password;
        Object.assign(row, next, {
          version: (row.version || 0) + 1,
          updated_at: now(),
        });
        if (table === "agent-configs") this.invalidate(row.id);
        if (table === "publications") {
          row.available = row.enabled && !row.revoked_at;
          row.requires_republish = false;
          row.agent_version = own("agent-configs", row.agent_config_id).version;
        }
        this.audit("update", table, row.id);
        return row;
      }
      return row;
    }
    if (method === "POST") {
      const safeBody = { ...body };
      delete safeBody.password;
      delete safeBody.api_key;
      const defaults =
        table === "conversations"
          ? {
              status: "open",
              support_state: "ai",
              handling_mode: "ai",
              priority: "normal",
              tags: [],
              version: 1,
            }
          : table === "publications"
            ? {
                enabled: false,
                available: false,
                version: 1,
                agent_version: own("agent-configs", body.agent_config_id)
                  .version,
                requires_republish: false,
                revoked_at: null,
              }
            : table === "agent-configs"
              ? { version: 1, enabled: true }
              : table === "knowledge-bases" ||
                  table === "tenants" ||
                  table === "users" ||
                  table === "memberships"
                ? { status: "active" }
                : {};
      const row = create(table, { ...defaults, ...safeBody });
      if (table === "tenants" && body.admin_user_id)
        state.tables.memberships.push({
          id: uuid(),
          tenant_id: row.id,
          user_id: body.admin_user_id,
          role: "admin",
          status: "active",
        });
      if (table === "conversations") state.messages[row.id] = [];
      return row;
    }
    let rows = this.rows(table);
    const q = (query.get("q") || "").toLowerCase();
    if (q)
      rows = rows.filter((r) =>
        `${r.name || r.subject || r.login || ""}`.toLowerCase().includes(q),
      );
    if (table === "conversations") {
      const queue = query.get("queue");
      if (queue === "resolved")
        rows = rows.filter((c) => c.status === "closed");
      else if (queue === "unassigned")
        rows = rows.filter((c) => !c.assignee_id && c.status === "open");
      else if (queue === "mine")
        rows = rows.filter((c) => c.assignee_id === userId);
      else if (queue && queue !== "all")
        rows = rows.filter(
          (c) => c.support_state === (queue === "pending" ? "waiting" : queue),
        );
      if (query.get("priority"))
        rows = rows.filter((c) => c.priority === query.get("priority"));
      if (query.get("assignee_id"))
        rows = rows.filter((c) => c.assignee_id === query.get("assignee_id"));
    }
    if (table === "conversations")
      rows = [...rows].sort((a, b) => {
        const comparison =
          String(a.created_at).localeCompare(String(b.created_at)) ||
          a.id.localeCompare(b.id);
        return query.get("sort") === "oldest" ? comparison : -comparison;
      });
    return this.page(rows, query);
  }
  private history(id: string, q: URLSearchParams) {
    let rows = this.state.messages[id] || [];
    const after = q.get("after"),
      before = q.get("before");
    if (after) {
      const index = rows.findIndex((m) => m.id === after);
      if (index < 0) fail(404, "invalid_cursor", "消息游标不存在。");
      rows = rows.slice(index + 1);
    }
    if (before) {
      const index = rows.findIndex((m) => m.id === before);
      if (index < 0) fail(404, "invalid_cursor", "消息游标不存在。");
      rows = rows.slice(0, index);
    }
    const size = Number(q.get("limit") || 50),
      offset = Number(q.get("offset") || 0);
    if (
      before ||
      q.get("newest") === "true" ||
      (!after && id && q.get("newest") !== "false")
    )
      return rows.slice(
        Math.max(0, rows.length - offset - size),
        rows.length - offset,
      );
    return rows.slice(offset, offset + size);
  }
  private memory(
    key: string | undefined,
    method: string,
    body: Record<string, any>,
  ) {
    const state = this.state;
    const own = (row: Row) =>
      row.tenant_id === this.tenant && row.user_id === userId;
    const consents = (state.tables["user-memory-consents"] ||= []);
    let consent = consents.find(own);
    const memories = (state.tables["user-memories"] ||= []);
    const clear = (predicate: (row: Row) => boolean) => {
      state.tables["user-memories"] = memories.filter(
        (row) => !own(row) || !predicate(row),
      );
    };
    if (key === "consent") {
      if (method === "PUT") {
        if (typeof body.enabled !== "boolean")
          fail(422, "validation_error", "请选择记忆授权状态。");
        if (!consent) {
          consent = {
            id: uuid(),
            tenant_id: this.tenant,
            user_id: userId,
            enabled: false,
            version: 1,
          };
          consents.push(consent);
        }
        if (consent.enabled !== body.enabled) consent.version++;
        consent.enabled = body.enabled;
        if (!consent.enabled) clear(() => true);
        this.audit("user_memory.consent", "user_memory", consent.id);
      }
      return {
        enabled: consent?.enabled || false,
        version: consent?.version || 0,
      };
    }
    if (key === "cleanup" && method === "POST") {
      const expired = memories
        .filter((row) => own(row) && row.expires_at <= now())
        .slice(0, 100);
      clear((row) => expired.includes(row));
      return { deleted: expired.length };
    }
    if (method === "DELETE") {
      if (key && !memories.some((row) => own(row) && row.memory_key === key))
        fail(404, "not_found", "演示记忆不存在。");
      clear((row) => !key || row.memory_key === key);
      this.audit(
        key ? "user_memory.delete" : "user_memory.clear",
        "user_memory",
        userId,
      );
      return null;
    }
    if (!key && method === "GET")
      return consent?.enabled
        ? memories.filter((row) => own(row) && row.expires_at > now())
        : [];
    if (key && method === "PUT") {
      if (!consent?.enabled)
        fail(409, "user_memory_consent_required", "请先明确启用本人记忆。");
      if (
        !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/.test(key) ||
        typeof body.quote !== "string" ||
        !body.quote.length ||
        body.quote.length > 300
      )
        fail(422, "validation_error", "记忆标识或原文长度不符合要求。");
      const days = body.retention_days ?? 30;
      if (!Number.isInteger(days) || days < 1 || days > 365)
        fail(422, "validation_error", "保留期限须为 1–365 天。");
      const conversation = this.rows("conversations").find(
        (c) =>
          c.channel !== "public" &&
          state.messages[c.id]?.some(
            (m) =>
              m.id === body.source_message_id &&
              m.role === "user" &&
              m.created_by === userId &&
              ["rag", "agent"].includes(m.source) &&
              m.content.includes(body.quote),
          ),
      );
      // This local demonstration is deliberately conservative, not a production DLP claim.
      const source =
        conversation &&
        state.messages[conversation.id].find(
          (m) => m.id === body.source_message_id,
        );
      if (
        !source ||
        /(?:sk-[a-zA-Z0-9_-]{8,}|password\s*[:=]|api[_-]?key\s*[:=]|密码\s*[:：])/i.test(
          source.content,
        )
      )
        fail(
          422,
          "invalid_memory_source",
          "仅可引用本人内部会话中的非敏感用户原文。",
        );
      const existing = memories.find(
        (row) => own(row) && row.memory_key === key,
      );
      if (
        existing
          ? existing.version !== body.expected_version
          : body.expected_version != null
      )
        fail(409, "version_conflict", "记忆已变化，请刷新后重新保存。");
      if (
        (!existing || existing.expires_at <= now()) &&
        memories.filter((row) => own(row) && row.expires_at > now()).length >=
          20
      )
        fail(409, "user_memory_limit", "最多保留 20 条有效记忆。");
      const entry = existing || {
        id: uuid(),
        tenant_id: this.tenant,
        user_id: userId,
        memory_key: key,
        version: 0,
        created_at: now(),
      };
      Object.assign(entry, {
        quote: body.quote,
        source_conversation_id: conversation!.id,
        source_message_id: source.id,
        version: entry.version + 1,
        updated_at: now(),
        expires_at: new Date(Date.now() + days * 86400000).toISOString(),
      });
      if (!existing) memories.push(entry);
      this.audit("user_memory.save", "user_memory", entry.id);
      return entry;
    }
    fail(404, "demo_not_implemented", "演示记忆操作不存在。");
  }
  private rowsForTenant(table: string, tenant: string) {
    return (this.state.tables[table] || []).filter(
      (r) => r.tenant_id === tenant,
    );
  }
  private version(row: Row, body: Record<string, any>) {
    if (
      body.expected_version !== undefined &&
      body.expected_version !== row.version
    )
      fail(409, "version_conflict", "演示配置已变化，请刷新后重试。");
  }
  private invalidate(id: string) {
    for (const p of this.state.tables.publications)
      if (p.agent_config_id === id) {
        p.available = false;
        p.requires_republish = true;
      }
  }
  private audit(
    action: string,
    target: string,
    id: string,
    tenant = this.tenant,
  ) {
    (this.state.tables["audit-events"] ||= []).unshift({
      id: uuid(),
      tenant_id: tenant,
      actor_id: userId,
      action,
      target_type: target,
      target_id: id,
      outcome: "success",
      request_id: uuid(),
      created_at: now(),
      details: { demo: true },
    });
  }
  private turn(c: Row, body: Record<string, any>, options: RequestOptions) {
    if (c.status === "closed") fail(409, "conversation_closed", "会话已结束。");
    const key = c.id + ":" + body.idempotency_key,
      existing = this.state.identities[key];
    const digest = JSON.stringify({
      content: body.content,
      agent_config_id: body.agent_config_id,
    });
    if (existing) {
      if (existing.digest !== digest)
        fail(409, "idempotency_conflict", "同一请求标识不能用于不同输入。");
      return existing.result;
    }
    if (c.support_state !== "ai")
      fail(
        409,
        "human_handling_active",
        "会话正由人工处理，AI 回复已暂停；人工客服仍可从工作台发送答复。",
      );
    const rows = (this.state.messages[c.id] ||= []);
    rows.push({
      id: uuid(),
      role: "user",
      created_by: c.channel === "public" ? null : userId,
      source: "agent",
      content: body.content,
      created_at: now(),
      citations: [],
    });
    const answer = /人工|客服接管/.test(body.content)
      ? "可以由工作台客服接管此会话。离线演示不会连接真实客服中心。"
      : /不知道|价格|退款/.test(body.content)
        ? "演示知识库没有足够资料确认这个问题，请补充信息或联系人工客服。我不会编造具体政策。"
        : "这是离线模拟回复：你可以导入通用知识资料、配置 Agent 并发布网站客服。此静态 Demo 使用确定性内容，不调用模型。";
    const citations = [
      {
        chunk_id: "demo-chunk",
        document_id: "demo-doc",
        document_name: "星河服务指南.md",
        quote: "团队服务支持创建工作区、导入知识文档和发布客服入口。",
      },
    ];
    options.onEvent?.("stage", { phase: "retrieving" });
    options.onEvent?.("stage", { phase: "generating" });
    const callId = uuid(),
      message = {
        id: uuid(),
        role: "assistant",
        content: answer,
        created_at: now(),
        citations,
        tool_results: [],
        model_call_id: callId,
        metadata: { source: "agent" },
      };
    rows.push(message);
    const result = {
      id: callId,
      model_call_id: callId,
      call_id: callId,
      request_id: uuid(),
      conversation_id: c.id,
      message_id: message.id,
      status: "answered",
      phase: "completed",
      content: answer,
      answer,
      assistant_message: message,
      citations,
      tool_results: [],
      input_tokens: null,
      output_tokens: null,
      grounded: false,
    };
    (this.state.tables["model-calls"] ||= []).push({
      ...result,
      status: "succeeded",
      tenant_id: c.tenant_id,
      model: "static-demo",
      provider: "demo",
      created_at: now(),
      steps: 1,
    });
    this.state.identities[key] = { id: callId, digest, result };
    options.onEvent?.("delta", { text: answer });
    options.onEvent?.("completed", result);
    this.audit("demo_turn", "conversation", c.id, c.tenant_id);
    return result;
  }
  private analytics(q: URLSearchParams) {
    const cs = this.rows("conversations"),
      calls = this.rows("model-calls"),
      feedback = this.state.visitors
        .filter((v) => v.tenant_id === this.tenant)
        .map((v) => v.feedback)
        .filter(Boolean);
    const closed = cs.filter((c) => c.status === "closed").length,
      satisfied = feedback.filter((f) => f.rating === "satisfied").length;
    return {
      start: q.get("start") || now(),
      end: q.get("end") || now(),
      conversations: {
        total: cs.length,
        pending: cs.length - closed,
        resolved: closed,
        avg_first_response_seconds: null,
        avg_resolution_seconds: null,
        handoff_rate: cs.length
          ? cs.filter((c) => c.support_state === "human").length / cs.length
          : null,
        overdue: 0,
        ai_resolved: closed,
        ai_to_human: cs.filter((c) => c.support_state === "human").length,
        ai_unresolved: cs.length - closed,
      },
      ai: {
        retrieval_use_rate: null,
        valid_citation_rate: null,
        tool_success_rate: null,
      },
      usage: {
        calls: calls.length,
        failed: 0,
        input_tokens: 0,
        output_tokens: 0,
        unknown_usage_calls: calls.length,
        known_cost: null,
        unknown_cost_calls: calls.length,
        models: [
          {
            model: "static-demo",
            calls: calls.length,
            input_tokens: 0,
            output_tokens: 0,
            unknown_usage_calls: calls.length,
          },
        ],
      },
      trend: Array.from({ length: 7 }, (_, i) => ({
        day: new Date(Date.now() - (6 - i) * 86400000)
          .toISOString()
          .slice(0, 10),
        conversations: i === 6 ? cs.length : 0,
        ai: i === 6 ? cs.filter((c) => c.support_state === "ai").length : 0,
        human:
          i === 6 ? cs.filter((c) => c.support_state === "human").length : 0,
        calls: i === 6 ? calls.length : 0,
        input_tokens: 0,
        output_tokens: 0,
        unknown_usage_calls: i === 6 ? calls.length : 0,
      })),
      feedback: {
        satisfied,
        dissatisfied: feedback.length - satisfied,
        unrated: cs.length - feedback.length,
        satisfaction_rate: feedback.length ? satisfied / feedback.length : null,
      },
      categories: [{ category: "产品咨询", count: cs.length }],
      unresolved: cs
        .filter((c) => c.status !== "closed")
        .map((c) => ({ id: c.id, subject: c.subject })),
    };
  }
}
export const adapter: Adapter = new DemoAdapter();
