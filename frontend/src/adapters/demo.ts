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
      this.state = saved ? JSON.parse(saved) : seed();
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
  private documentChunks(doc: Row): Row[] {
    doc.generation ||= 1;
    doc.is_published ??= doc.id === "demo-doc";
    const tenant = doc.tenant_id || this.tenant;
    const chunks = (this.state.tables["document-chunks"] ||= []);
    if (!chunks.some((row) => row.tenant_id === tenant && row.document_id === doc.id && row.generation === doc.generation)) {
      const id = doc.id === "demo-doc" && doc.generation === 1 ? "demo-chunk" : uuid();
      chunks.push({
        id, root_chunk_id: id, tenant_id: tenant, document_id: doc.id,
        generation: doc.generation, position: 0, revision: 1, is_current: true,
        is_deleted: false, revised_by: null, revision_reason: null, created_at: now(),
        content: "虚构演示资料。团队工作区支持文档知识库、人工协作和网站客服接入。",
        page: null, section: null,
      });
    }
    return chunks.filter((row) => row.tenant_id === tenant && row.document_id === doc.id);
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
    const checkPublicTools = (agentId: string, ids: string[]) => {
      const grants = state.grants[agentId] || [];
      if (!ids.every((id) => this.rows("tools").some((tool) => tool.id === id && tool.key !== "conversation_history" && tool.enabled && tool.execution_type === "read_only" && tool.risk_level === "low" && !tool.permissions?.includes("tenant:admin") && grants.some((grant) => grant.tool_id === id && grant.enabled))))
        fail(422, "public_tool_denied", "仅可发布已授权的低风险只读工具；会话历史不对访客开放。");
    };
    if (parts[0] === "reply-drafts" || parts[0] === "customer-exports" || (parts[0] === "conversations" && parts[2] === "drafts") || (parts[0] === "customers" && ["exports", "export-preview"].includes(parts[2])) || (parts[0] === "knowledge-bases" && ["index", "diagnostics"].includes(parts[2]))) fail(409, "product_capability_unavailable", "NOT_AVAILABLE：离线 Demo 不模拟向量索引、客户完整导出或真实 AI 草稿任务。");
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
    if (pathname === "/autonomy-policy") return {
      version: "private-autonomy-v1", levels: ["信息回答", "检索与只读查询", "可逆业务操作", "需人工审批", "禁止操作"].map((name, risk) => ({ name, risk })),
      default_max_risk: 1, maximum_configurable_risk: 2, r3_execution: "BLOCKED", model_can_grant: false,
      limits: { model_steps: 5, tool_calls: 4, seconds: 120 }, monetary_budget_enforcement: "BLOCKED",
    };
    if (pathname === "/administration") return {
      deployment_mode: "single_enterprise_private", required_revision: "0020_conversation_idempotency", storage_backend: "static_demo_no_files",
      external_models_enabled: false, automatic_migrations: false, backup_last_verified_at: null,
      backup_mode: "not_applicable_to_demo", worker: "NOT_RUN",
      retention: { conversations_days: null, visitors_days: null, calls_days: null, audit_days: null },
      capabilities: [{ name: "静态 Demo", state: "fictional", detail: "客户、工单与交接均为标签页虚构数据，不连接模型、API或数据库。" }],
    };
    if (pathname === "/administration/retention/preview") return {
      executable: false, confirmation: null, blocked_reason: "static_demo_no_operational_erasure", counts: {},
      unknown_dependencies: ["real_database_and_files"], http_execution_enabled: false,
    };
    if (parts[0] === "conversations" && parts[2] === "attachments") {
      const c = own("conversations", parts[1]);
      return this.attachments(c.id, parts[3], method, options, query, false);
    }
    if (parts[0] === "conversations" && !parts[1] && method === "POST") {
      if (typeof body.idempotency_key !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(body.idempotency_key)) fail(422, "validation_error", "新会话需要 UUID 请求标识。");
      if ((body.subject !== undefined && typeof body.subject !== "string") || (body.channel !== undefined && typeof body.channel !== "string")) fail(422, "validation_error", "会话标题和渠道必须是文字。");
      const subject = (body.subject ?? "新会话").trim(), channel = (body.channel ?? "api").trim();
      if (!subject || subject.length > 160 || !/^[a-z][a-z0-9_-]{0,39}$/.test(channel)) fail(422, "validation_error", "会话标题或渠道无效。");
      const key = body.idempotency_key.toLowerCase(), input = JSON.stringify({ subject, channel });
      const existing = this.rows("conversation-create-requests").find((row) => row.created_by === userId && row.idempotency_key === key);
      if (existing) {
        if (existing.demo_creation_input !== input) fail(409, "idempotency_conflict", "会话标识已用于其他内容。");
        const conversation = own("conversations", existing.conversation_id);
        this.audit("conversation.create_replay", "conversations", conversation.id);
        return this.conversationView(conversation);
      }
      const row = create("conversations", { subject, channel, created_by: userId, status: "open", support_state: "ai", handling_mode: "ai", priority: "normal", tags: [], version: 1 });
      state.tables["conversation-create-requests"].push({ id: uuid(), tenant_id: this.tenant, created_by: userId, idempotency_key: key, demo_creation_input: input, conversation_id: row.id });
      state.messages[row.id] = [];
      return this.conversationView(row);
    }
    if (parts[0] === "customers" || parts[0] === "tickets") {
      const table = parts[0];
      const view = (row: Row) => { const { demo_input, idempotency_key, ...rest } = row; return rest; };
      if (!parts[1] && method === "POST") {
        const input = JSON.stringify(body);
        const existing = this.rows(table).find((row) => row.idempotency_key === body.idempotency_key);
        if (existing) { if (existing.demo_input !== input) fail(409, "idempotency_conflict", "标识已用于另一组输入。"); return view(existing); }
        if (!body.idempotency_key) fail(422, "validation_error", "需要稳定请求标识。");
        if (table === "tickets" && body.conversation_id) {
          own("conversations", body.conversation_id);
          const linked = this.rows("conversation-customers").find((link) => link.conversation_id === body.conversation_id);
          if (linked && body.customer_id && body.customer_id !== linked.customer_id) fail(409, "customer_link_conflict", "客户与会话的确认关联不一致。");
          if (linked) body.customer_id = linked.customer_id;
        }
        if (table === "tickets" && body.customer_id) own("customers", body.customer_id);
        const row = create(table, table === "customers" ? { ...body, notes: body.notes || "", tags: body.tags || [], status: "active", memory_enabled: false, version: 1, demo_input: input } : { ...body, description: body.description || "", priority: body.priority || "normal", status: "open", version: 1, resolved_at: null, due_at: body.due_at || null, demo_input: input });
        if (table === "tickets") (state.tables["ticket-events"] ||= []).push({ id: uuid(), tenant_id: this.tenant, ticket_id: row.id, actor_id: userId, action: "created", details: { version: 1, status: "open" }, created_at: now() });
        return view(row);
      }
      if (!parts[1]) return this.page(this.rows(table).filter((row) => (!query.get("q") || row.name?.includes(query.get("q"))) && (!query.get("status") || row.status === query.get("status")) && (!query.get("customer_id") || row.customer_id === query.get("customer_id")) && (!query.get("conversation_id") || row.conversation_id === query.get("conversation_id"))).map(view), query);
      const row = own(table, parts[1]);
      if (table === "customers" && parts[2] === "memory-consent" && method === "PUT") {
        if (row.version !== body.expected_version) fail(409, "version_conflict", "客户资料已变化。");
        row.memory_enabled = body.enabled; row.version++; row.updated_at = now();
        if (!body.enabled) for (const memory of this.rows("customer-memories").filter((m) => m.customer_id === row.id && !m.deleted_at)) Object.assign(memory, { content: null, deleted_at: now(), version: memory.version + 1 });
        return view(row);
      }
      if (table === "customers" && parts[2] === "memories") {
        const memories = this.rows("customer-memories").filter((m) => m.customer_id === row.id);
        if (parts[3] && parts[4] === "forget" && method === "POST") {
          const memory = memories.find((m) => m.id === parts[3]) || fail(404, "not_found", "引用不存在。");
          if (memory.version !== body.expected_version) fail(409, "version_conflict", "引用已变化。");
          Object.assign(memory, { content: null, deleted_at: now(), version: memory.version + 1 }); return memory;
        }
        if (method === "POST") {
          if (!row.memory_enabled || row.status !== "active") fail(409, "customer_memory_disabled", "先启用客户记忆。");
          if (row.version !== body.expected_customer_version) fail(409, "version_conflict", "客户资料已变化。");
          const message = Object.entries(state.messages).flatMap(([cid, rows]) => rows.map((m): Row => ({ ...m, conversation_id: cid }))).find((m) => m.id === body.source_message_id) || fail(404, "not_found", "来源消息不存在。");
          own("conversations", message.conversation_id);
          const linked = this.rows("conversation-customers").some((link) => link.customer_id === row.id && link.conversation_id === message.conversation_id);
          if (!linked || message.role !== "user" || !body.content?.trim() || !message.content.includes(body.content) || body.content.length > 500 || !Number.isInteger(body.lifetime_days) || body.lifetime_days < 1 || body.lifetime_days > 365) fail(422, "memory_source_mismatch", "需要已关联会话的客户原话和有效天数。");
          // Fictional session-only digest substitutes no cryptographic or production guarantee.
          const digest = [...body.content].reduce((hash, char) => Math.imul(hash ^ char.charCodeAt(0), 16777619), 2166136261).toString(16);
          const existing = memories.find((m) => m.source_message_id === message.id && m.demo_digest === digest);
          if (existing) {
            if (existing.deleted_at || existing.expires_at <= now()) fail(409, "memory_not_restorable", "已撤回或到期的同源引用不能恢复。");
            return existing;
          }
          if (memories.filter((m) => !m.deleted_at && m.expires_at > now()).length >= 100) fail(409, "customer_memory_limit", "引用数量已达上限。");
          return create("customer-memories", { customer_id: row.id, source_conversation_id: message.conversation_id, source_message_id: message.id, content: body.content, demo_digest: digest, confirmed_by: userId, version: 1, deleted_at: null, expires_at: new Date(Date.now() + body.lifetime_days * 86400000).toISOString() });
        }
        return this.page(memories.filter((m) => row.memory_enabled && row.status === "active" && !m.deleted_at && m.expires_at > now()), query);
      }
      if (method === "DELETE") fail(409, "customer_erasure_blocked", "整体擦除需要完整的来源与历史影响计划。");
      if (table === "customers" && parts[2] === "activity") {
        const tickets = this.rows("tickets").filter((ticket) => ticket.customer_id === row.id).map((ticket) => ticket.id);
        const memories = this.rows("customer-memories").filter((memory) => memory.customer_id === row.id).map((memory) => memory.id);
        return this.page(this.rows("audit-events").filter((event) => event.target_id === row.id || (event.target_type === "tickets" && tickets.includes(event.target_id)) || (event.target_type === "customer-memories" && memories.includes(event.target_id))).map((event) => ({ id: event.id, action: event.action, actor_id: event.actor_id, resource_id: event.target_id, created_at: event.created_at })), query);
      }
      if (parts[2] === "events") return this.page(this.rows("ticket-events").filter((event) => event.ticket_id === row.id).reverse(), query);
      if (parts[2] === "conversations") return this.page(this.rows("conversation-customers").filter((link) => link.customer_id === row.id).map((link) => ({ id: link.id, conversation_id: link.conversation_id, linked_at: link.created_at, identity_method: "staff_confirmed" })), query);
      if (parts[2] === "export") return { profile: view(row), scope: "profile_only", complete_export: false };
      if (method === "PATCH") {
        if (row.version !== body.expected_version) fail(409, "version_conflict", "记录已更新，请刷新。");
        const changes = { ...body }; delete changes.expected_version;
        const note = changes.note || ""; delete changes.note;
        if (table === "tickets" && body.status && body.status !== row.status && !({ open: ["in_progress", "resolved", "closed"], in_progress: ["open", "resolved", "closed"], resolved: ["open", "in_progress", "closed"], closed: ["open"] } as Record<string, string[]>)[row.status]?.includes(body.status)) fail(409, "ticket_transition_invalid", "不能执行此状态变更。");
        Object.assign(row, changes, { version: row.version + 1, updated_at: now() });
        if (table === "tickets") (state.tables["ticket-events"] ||= []).push({ id: uuid(), tenant_id: this.tenant, ticket_id: row.id, actor_id: userId, action: "updated", details: { version: row.version, status: row.status, note }, created_at: now() });
      }
      return view(row);
    }
    if (parts[0] === "staff-notifications") {
      const rows = this.rows("staff-notifications").filter((row) => row.user_id === userId);
      if (parts[1]) { const row = rows.find((row) => row.id === parts[1]) || fail(404, "not_found", "通知不存在。"); if (method === "POST") row.read_at ||= now(); return row; }
      return this.page(rows.filter((row) => query.get("unread") !== "true" || !row.read_at), query);
    }
    if (pathname === "/workspace/feedback") {
      let rows = state.visitors.filter((visitor) => visitor.tenant_id === this.tenant && visitor.feedback)
        .map((visitor) => ({ ...visitor.feedback, id: visitor.id, conversation_id: visitor.conversation_id }))
        .filter((row) => !query.get("rating") || row.rating === query.get("rating"))
        .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
      const before = query.get("before");
      if (before) {
        const index = rows.findIndex((row) => row.id === before);
        if (index < 0) fail(404, "invalid_cursor", "评价游标不存在。");
        rows = rows.slice(index + 1);
      }
      return this.page(rows, query);
    }
    if (parts[0] === "user-memory" && parts[1] === "usage") {
      const call = this.rows("model-calls").find((c) => c.id === parts[2]);
      const saved = call?.memory_usage || [];
      const memories = this.rows("user-memories").filter((m) => m.user_id === userId && saved.some((v: Row) => v.id === m.id && v.version === m.version));
      return { call_id: parts[2], memories, submitted_at: call?.created_at || null };
    }
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
        document_published: doc.is_published !== false,
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
      if (resource === "attachments") return this.attachments(conversation.id, parts[5], method, options, query, true);
      if (resource === "messages") {
        options.onHeaders?.(
          new Headers({ "X-Conversation-Status": conversation.status, "X-Support-State": conversation.support_state }),
        );
        if (method === "POST") {
          if (!["waiting", "human"].includes(conversation.support_state)) fail(409, "human_handling_inactive", "会话状态已变化，请重试。");
          return this.turn(conversation, { ...body, agent_config_id: pub.agent_config_id }, options, visitor.id);
        }
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
          visitor.id,
        );
      fail(404, "not_found", "演示公开功能不存在。");
    }
    if (parts[0] === "agent-configs" && parts[2] === "changes") {
      own("agent-configs", parts[1]);
      return this.page(this.rows("audit-events").filter((row) => row.target_id === parts[1] && row.target_type === "agent-configs").map((row) => ({ id: row.id, actor_id: row.actor_id, action: row.action, created_at: row.created_at, request_id: row.request_id, config_version: row.details.config_version ?? null, changed_fields: row.details.changed_fields || [] })), query);
    }
    if (parts[0] === "agent-configs" && parts[2] === "knowledge-bases") {
      const agent = own("agent-configs", parts[1]);
      if (method === "PUT") {
        this.version(agent, body);
        state.bindings[agent.id] = body.knowledge_base_ids;
        agent.version++;
        this.audit("agent_config.knowledge", "agent-configs", agent.id);
        Object.assign(state.tables["audit-events"][0].details, { config_version: agent.version, changed_fields: ["knowledge_base_ids"] });
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
          generation: 1,
          is_published: false,
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
      return this.rows("documents").filter((doc) => doc.knowledge_base_id === parts[1] && doc.status === "ready" && doc.is_published !== false).flatMap((doc) => this.documentChunks(doc).filter((chunk) => chunk.generation === doc.generation && chunk.is_current && !chunk.is_deleted).map((chunk) => ({ chunk_id: chunk.id, document_id: doc.id, document_name: doc.filename, content: chunk.content, score: 1, strategy: "static-demo", page: chunk.page, section: chunk.section, generation: chunk.generation }))).slice(0, Math.min(10, Number(body.limit) || 6));
    }
    if (parts[0] === "documents" && parts[2] === "publication") {
      const doc = own("documents", parts[1]);
      if (doc.status !== "ready" || doc.generation !== body.expected_generation || doc.updated_at !== body.expected_updated_at) fail(409, "document_changed", "文档已变化，请刷新。");
      doc.is_published = body.published; doc.updated_at = now(); return doc;
    }
    if (parts[0] === "documents" && parts[2] === "chunks") {
      const doc = own("documents", parts[1]);
      const chunks = this.documentChunks(doc);
      if (parts[3]) {
        const chunk = chunks.find((row) => row.id === parts[3]) || fail(404, "not_found", "分块不存在。");
        const lineage = chunks.filter((row) => row.root_chunk_id === chunk.root_chunk_id && row.generation === chunk.generation);
        if (method === "GET" && parts[4] === "versions")
          return this.page([...lineage].sort((a, b) => b.revision - a.revision), query);
        const current = lineage.find((row) => row.is_current);
        if (!current || current.id !== body.expected_current_id || chunk.generation !== doc.generation)
          fail(409, "chunk_changed", "分块版本已变化，请刷新。");
        if (typeof body.reason !== "string" || body.reason.length > 500 || !body.reason.trim())
          fail(422, "validation_error", "请填写不超过 500 字的修改原因。");
        const restoring = parts[4] === "restore" && method === "POST";
        if (!restoring && method !== "PATCH" && method !== "DELETE")
          fail(405, "method_not_allowed", "不支持的分块操作。");
        const source = restoring
          ? lineage.find((row) => row.id === body.source_version_id && !row.is_deleted)
          : current;
        if (!source) fail(422, "invalid_chunk_version", "请选择同一分块的有效历史版本。");
        if (!restoring && current.is_deleted) fail(409, "chunk_deleted", "请先恢复分块。");
        const content = method === "PATCH" ? body.content : source.content;
        if (typeof content !== "string" || !content.trim() || content.length > 1200)
          fail(422, "validation_error", "正文应为 1–1200 字。");
        current.is_current = false;
        doc.is_published = false;
        doc.updated_at = now();
        const result = { ...source, id: uuid(), revision: current.revision + 1,
          is_current: true, is_deleted: method === "DELETE", content, revised_by: userId,
          revision_reason: body.reason, created_at: now() };
        state.tables["document-chunks"].push(result);
        doc.chunk_count = chunks.filter((row) => row.generation === doc.generation && row.is_current && !row.is_deleted).length + (result.is_deleted ? 0 : 1);
        this.audit("chunk.revision", "document_chunk", result.id);
        return result;
      }
      return this.page(chunks.filter((row) => row.generation === Number(query.get("generation") || doc.generation) && row.is_current && (!row.is_deleted || query.get("include_deleted") === "true")), query);
    }
    if (parts[0] === "documents" && parts[2] === "reprocess") {
      const doc = own("documents", parts[1]);
      this.documentChunks(doc);
      doc.generation++;
      doc.is_published = false;
      this.documentChunks(doc);
      doc.status = "ready";
      doc.chunk_count = 1;
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
      if (sub === "customer") {
        const links = (state.tables["conversation-customers"] ||= []);
        const linked = links.find((row) => row.tenant_id === this.tenant && row.conversation_id === c.id);
        if (method === "PUT") {
          if (body.expected_version !== c.version) fail(409, "version_conflict", "会话已变化。");
          const customer = own("customers", body.customer_id);
          if (customer.status !== "active") fail(409, "customer_archived", "客户已归档。");
          if ((linked && linked.customer_id !== customer.id) || this.rows("tickets").some((ticket) => ticket.conversation_id === c.id && ticket.customer_id && ticket.customer_id !== customer.id)) fail(409, "customer_link_conflict", "现有客户关联不同，需要先审查身份。");
          if (!linked) { links.push({ id: uuid(), tenant_id: this.tenant, conversation_id: c.id, customer_id: customer.id, created_at: now() }); c.version++; }
          return { customer_id: customer.id, conversation_id: c.id, conversation_version: c.version, identity_method: "staff_confirmed", visitor_identity_verified: false };
        }
        return linked ? own("customers", linked.customer_id) : null;
      }
      if (sub === "handoff") return { conversation_id: c.id, conversation_version: c.version, support_state: c.support_state, snapshot_kind: "static_demo", summary: null, reason: null, knowledge_sources: [], knowledge_sources_state: "UNKNOWN", tool_executions: [], pending_tickets: this.rows("tickets").filter((ticket) => ticket.conversation_id === c.id && ["open", "in_progress"].includes(ticket.status)), untracked_pending_tasks: "UNKNOWN", client_delivery: "UNKNOWN" };
      if (sub === "answer-feedback") {
        const notes = (state.notes[c.id] ||= []);
        const view = (row: Row) => ({ id: row.id, actor_id: row.actor_id, comment: row.content, created_at: row.created_at, ...row.details });
        if (method === "POST") {
          const answer = (state.messages[c.id] || []).find((m) => m.model_call_id === body.call_id && m.role === "assistant");
          if (!answer) fail(409, "answer_unavailable", "只能评价已保存的最终回答。");
          if (!["helpful", "not_helpful", "citation_inaccurate", "incomplete", "knowledge_missing", "other"].includes(body.category) || typeof body.comment !== "string" || body.comment.length > 1000) fail(422, "validation_error", "反馈分类或备注无效。");
          const existing = notes.find((n) => n.details?.type === "answer_feedback_v1" && n.details.message_id === answer.id && n.actor_id === userId);
          if (existing) {
            if (existing.content !== body.comment || existing.details.category !== body.category) fail(409, "feedback_exists", "此回答已经提交过你的反馈。");
            return view(existing);
          }
          const question = (state.messages[c.id] || []).filter((m) => m.model_call_id === body.call_id && m.role === "user");
          const note = { id: uuid(), actor_id: userId, kind: "note", content: body.comment, created_at: now(), details: { type: "answer_feedback_v1", call_id: body.call_id, message_id: answer.id, question_message_id: question.length === 1 ? question[0].id : null, revision: 1, category: body.category, status: "open", citation_chunk_ids: (answer.citations || []).map((hit: Row) => hit.chunk_id) } };
          notes.unshift(note);
          this.audit("answer_feedback.create", "conversation", c.id);
          return view(note);
        }
        if (method === "PATCH") {
          const row = notes.find((n) => n.id === parts[3] && n.details?.type === "answer_feedback_v1") || fail(404, "not_found", "反馈不存在。");
          if (row.details.status !== body.expected_status || (row.details.revision ?? 0) !== body.expected_revision) fail(409, "feedback_changed", "反馈已变化，请刷新。");
          if (!["open", "processing", "reviewed", "resolved"].includes(body.status)) fail(422, "validation_error", "反馈状态无效。");
          if (body.resolution_category != null && !["correct", "answer_issue", "knowledge_issue", "retrieval_issue", "citation_issue", "other"].includes(body.resolution_category)) fail(422, "validation_error", "处理分类无效。");
          if (typeof body.resolution_note === "string" && body.resolution_note.length > 1000) fail(422, "validation_error", "处理意见过长。");
          const related = body.related_chunk_ids ?? row.details.related_chunk_ids ?? [];
          if (!Array.isArray(related) || related.length > 100) fail(422, "invalid_feedback_chunks", "关联分块列表无效。");
          const docs = this.rows("documents");
          docs.forEach((doc) => this.documentChunks(doc));
          const chunks = this.rows("document-chunks");
          const sources = [...new Set<string>(related)].map((id) => {
            const chunk = chunks.find((chunk) => chunk.id === id);
            const doc = chunk && docs.find((doc) => doc.id === chunk.document_id);
            if (!chunk || !doc || doc.status !== "ready" || chunk.generation !== doc.generation || chunk.is_deleted || (!chunk.is_current && !row.details.citation_chunk_ids.includes(id)) || !chunks.some((v) => v.root_chunk_id === chunk.root_chunk_id && v.is_current && !v.is_deleted)) fail(409, "feedback_source_unavailable", "分块不存在或不可用。");
            return { chunk_id: id, document_id: doc.id, knowledge_base_id: doc.knowledge_base_id };
          });
          const changes = { status: body.status, resolution_category: "resolution_category" in body ? body.resolution_category : row.details.resolution_category ?? null, resolution_note: "resolution_note" in body ? body.resolution_note : row.details.resolution_note ?? "", related_chunk_ids: [...new Set(related)], related_sources: sources };
          if (Object.entries(changes).some(([field, value]) => JSON.stringify(row.details[field]) !== JSON.stringify(value))) Object.assign(row.details, changes, { revision: (row.details.revision ?? 0) + 1 });
          this.audit("answer_feedback.update", "conversation", c.id);
          return view(row);
        }
        let rows = notes.filter((n) => n.details?.type === "answer_feedback_v1" && (!query.get("call_id") || n.details.call_id === query.get("call_id")) && (!query.get("status") || n.details.status === query.get("status")) && (!query.get("category") || n.details.category === query.get("category")) && (query.get("mine") !== "true" || n.actor_id === userId));
        if (query.get("before")) {
          const index = rows.findIndex((n) => n.id === query.get("before"));
          if (index < 0) fail(404, "invalid_cursor", "反馈游标不存在。");
          rows = rows.slice(index + 1);
        }
        return this.page(rows, query).map(view);
      }
      if (sub === "read" && method === "POST") {
        const messages = state.messages[c.id] || [];
        if (!messages.some((m) => m.id === body.message_id)) fail(404, "not_found", "消息不存在。");
        const cursors = (state.tables["read-cursors"] ||= []);
        let cursor = cursors.find((r) => r.tenant_id === this.tenant && r.user_id === userId && r.conversation_id === c.id);
        if (!cursor) cursors.push(cursor = { id: uuid(), tenant_id: this.tenant, user_id: userId, conversation_id: c.id, message_id: body.message_id });
        if (messages.findIndex((m) => m.id === body.message_id) > messages.findIndex((m) => m.id === cursor!.message_id)) cursor.message_id = body.message_id;
        return { message_id: cursor.message_id };
      }
      if (sub === "messages") {
        if (parts[3] && method === "GET") return (state.messages[c.id] || []).find((m) => m.id === parts[3]) || fail(404, "not_found", "来源消息不存在。");
        if (method === "POST") {
          if (!body.idempotency_key) fail(422, "validation_error", "消息需要稳定的请求标识。");
          const actor = userId;
          const existing = (state.messages[c.id] || []).find((m) => m.idempotency_key === body.idempotency_key && m.created_by === actor);
          if (existing) {
            if (existing.content !== body.content || existing.role !== body.role || JSON.stringify(existing.metadata || {}) !== JSON.stringify(body.metadata || {})) fail(409, "idempotency_conflict", "消息标识已用于其他内容。");
            return existing;
          }
          if (c.status === "closed")
            fail(409, "conversation_closed", "会话已结束。");
          const m = { id: uuid(), ...body, created_by: actor, source: "manual", created_at: now() };
          (state.messages[c.id] ||= []).push(m);
          c.updated_at = m.created_at;
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
      if (sub === "runs") {
        const call = this.rows("model-calls").find(
            (call) => call.id === parts[3] && call.conversation_id === c.id,
          ) || fail(404, "not_found", "演示运行记录不存在。");
        if (parts[4] === "trace") return {
          call_id: call.id, conversation_id: c.id, request_id: call.request_id,
          agent_config_id: call.agent_config_id || agentId, config_version: call.config_version || 1,
          status: call.status, phase: call.phase || "completed", started_at: call.created_at,
          execution_state: "UNKNOWN", lease_expired: false,
          elapsed_ms: null, error_category: null, input_tokens: null, output_tokens: null, usage_complete: false,
          cost: { basis: "deployment_price_estimate_not_invoice", complete: false, unknown_steps: 1, known_subtotals: {}, total: null, currency: null },
          events: [{ kind: "audit", label: "静态演示记录（未调用模型）", status: "simulated", started_at: call.created_at, elapsed_ms: null, input_tokens: null, output_tokens: null }], truncated: false,
        };
        return call;
      }
      if (sub === "agent-turns" || sub === "chat")
        return this.turn(c, body, options);
      if (method === "PATCH") {
        Object.assign(c, body, { version: c.version + 1, updated_at: now() });
        return c;
      }
      if (!sub) return this.conversationView(c);
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
      if (method === "DELETE" && ["documents", "knowledge-bases"].includes(table) && !this.rows(table).some((row) => row.id === parts[1])) return null;
      const row = own(table, parts[1]);
      if (method === "DELETE") {
        if (table === "documents" || table === "knowledge-bases") {
          if (query.get("preview") !== "true")
            fail(409, "knowledge_reference_review_required", "物理清理已阻断；历史引用的关联影响尚未完整确认，数据与文件保留。");
          const docs = table === "documents" ? [row] : this.rows("documents").filter((d) => d.knowledge_base_id === row.id);
          const batchSize = table === "documents" ? 1 : Math.min(100, Math.max(1, Number(query.get("batch_size") || 25)));
          const selected = docs.slice(0, batchSize);
          return {
            remaining: docs.length, batch_size: batchSize, status: row.status,
            documents: selected.map((doc) => ({ id: doc.id, filename: doc.filename, status: doc.status, generation: doc.generation || 1, updated_at: doc.updated_at })),
            chunk_versions: selected.reduce((count, doc) => count + this.documentChunks(doc).length, 0),
            executable: false, blocked_reason: "knowledge_reference_review_required", confirmation: null,
            unknown_dependencies: { "model_calls.result/steps": null, "messages.metadata": null, "tool_executions.result": null, "collaboration.details": null },
            effects: { deleted: [], retained: ["documents", "document_chunks", "private_files", "knowledge_bases", "agent_knowledge_bases"], requested: ["documents", "all_generations_and_revisions", "private_files"], unknown: ["historical_answer_and_tool_visibility", "feedback_source_links"] },
          };
        }
        if (table === "publications") {
          row.revoked_at = now();
          row.available = false;
          row.enabled = false;
          return null;
        }
        state.tables[table] = state.tables[table].filter((r) => r !== row);
        return null;
      }
      if (["PUT", "PATCH"].includes(method)) {
        this.version(row, body);
        if (table === "publications" && body.enabled) {
          if (row.revoked_at) fail(409, "publication_revoked", "入口已撤销。");
          if (!own("agent-configs", row.agent_config_id).enabled) fail(409, "agent_disabled", "Agent 已停用，无法发布。");
          checkPublicTools(row.agent_config_id, row.public_tool_ids || []);
        }
        const next = { ...body };
        delete next.expected_version;
        delete next.api_key;
        delete next.password;
        const changed = Object.keys(next).filter((key) => JSON.stringify(row[key]) !== JSON.stringify(next[key]));
        Object.assign(row, next, {
          version: (row.version || 0) + 1,
          updated_at: now(),
        });
        if (table === "agent-configs") this.invalidate(row.id);
        if (table === "publications") {
          row.available = row.enabled && !row.revoked_at && own("agent-configs", row.agent_config_id).enabled;
          row.requires_republish = false;
          row.agent_version = own("agent-configs", row.agent_config_id).version;
        }
        this.audit("update", table, row.id);
        if (table === "agent-configs") Object.assign(state.tables["audit-events"][0].details, { config_version: row.version, changed_fields: changed });
        return row;
      }
      return row;
    }
    if (method === "POST") {
      const safeBody = { ...body };
      if (table === "publications") checkPublicTools(body.agent_config_id, body.public_tool_ids || []);
      delete safeBody.password;
      delete safeBody.api_key;
      const defaults =
        table === "publications"
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
      return row;
    }
    let rows = this.rows(table);
    if (table === "tools") rows = rows.map((t) => ({ ...t, runtime_bound: false, binding_error: "离线演示未绑定实际工具运行时" }));
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
      if (query.get("tag"))
        rows = rows.filter((c) => c.tags?.includes(query.get("tag")));
      if (query.get("assignee_id"))
        rows = rows.filter((c) => c.assignee_id === query.get("assignee_id"));
    }
    if (table === "conversations") {
      rows = rows.map((c) => this.conversationView(c));
      const sort = query.get("sort") || "activity";
      const priority: Record<string, number> = { urgent: 4, high: 3, normal: 2, low: 1 };
      const customerActivity = sort === "customer_activity" ? new Map(rows.map((row) => [row.id, (state.messages[row.id] || []).filter((message) => message.role === "user").at(-1)?.created_at || row.created_at])) : new Map<string, string>();
      rows = [...rows].sort((a, b) => {
        if (sort === "customer_activity") {
          return customerActivity.get(b.id)!.localeCompare(customerActivity.get(a.id)!) || b.id.localeCompare(a.id);
        }
        if (sort === "priority" && priority[a.priority] !== priority[b.priority]) return (priority[b.priority] || 0) - (priority[a.priority] || 0);
        if (sort === "sla" && a.sla_due_at !== b.sla_due_at) return String(a.sla_due_at || "9999").localeCompare(String(b.sla_due_at || "9999"));
        const field = sort === "newest" || sort === "oldest" ? "created_at" : "last_activity_at";
        const comparison = String(a[field] || a.created_at).localeCompare(String(b[field] || b.created_at)) || a.id.localeCompare(b.id);
        return sort === "oldest" ? comparison : -comparison;
      });
    }
    return this.page(rows, query);
  }
  private attachments(cid: string, _aid: string | undefined, method: string, options: RequestOptions, query: URLSearchParams, visitor: boolean) {
    const rows = this.rows("conversation-attachments").filter((row) => row.conversation_id === cid && (!visitor || row.public));
    if (options.responseType === "blob") return fail(409, "demo_file_not_stored", "Demo 不保存文件正文，不能下载模拟附件。");
    if (method !== "POST") return this.page(rows, query);
    const form = options.body as FormData, file = form.get("file") as File;
    if (!file || file.size > 5 * 1024 * 1024) fail(422, "invalid_document", "文件不合法或超过限制。");
    const key = query.get("upload_id");
    const existing = rows.find((row) => row.upload_id === key);
    if (existing) { if (existing.filename !== file.name || existing.size_bytes !== file.size) fail(409, "idempotency_conflict", "请求标识已用于其他文件。"); return existing; }
    if (rows.length >= 20) fail(409, "attachment_limit", "已达附件上限。");
    const row = { id: uuid(), tenant_id: this.tenant, conversation_id: cid, filename: file.name, size_bytes: file.size, public: visitor || form.get("public") === "true", upload_id: key, status: "demo_metadata_only", created_at: now() };
    (this.state.tables["conversation-attachments"] ||= []).push(row);
    return row;
  }
  private conversationView(c: Row) {
    const messages = this.state.messages[c.id] || [];
    const cursor = (this.state.tables["read-cursors"] || []).find((r) => r.tenant_id === this.tenant && r.user_id === userId && r.conversation_id === c.id);
    const index = messages.findIndex((m) => m.id === cursor?.message_id);
    return { ...c, last_activity_at: messages.at(-1)?.created_at || c.created_at, unread_count: messages.slice(index + 1).filter((m) => m.role === "user" && m.created_by !== userId).length };
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
    visitorSessionId?: string,
  ) {
    (this.state.tables["audit-events"] ||= []).unshift({
      id: uuid(),
      tenant_id: tenant,
      actor_id: visitorSessionId ? null : userId,
      action,
      target_type: target,
      target_id: id,
      outcome: "success",
      request_id: uuid(),
      created_at: now(),
      details: { demo: true, ...(visitorSessionId ? { visitor_session_id: visitorSessionId } : {}) },
    });
  }
  private turn(
    c: Row,
    body: Record<string, any>,
    options: RequestOptions,
    visitorId?: string,
  ) {
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
    if (c.status === "closed") fail(409, "conversation_closed", "会话已结束。");
    if (visitorId && ["waiting", "human"].includes(c.support_state)) {
      const message = {
        id: uuid(),
        role: "user",
        created_by: null,
        source: "manual",
        content: body.content,
        created_at: now(),
        metadata: { visitor_session_id: visitorId },
        citations: [],
      };
      (this.state.messages[c.id] ||= []).push(message);
      c.updated_at = now();
      const result = {
        status: "received",
        conversation_id: c.id,
        message_id: message.id,
        request_id: uuid(),
      };
      this.state.identities[key] = { id: message.id, digest, result };
      this.audit("visitor.message", "message", message.id, c.tenant_id, visitorId);
      options.onEvent?.("completed", result);
      return result;
    }
    if (c.support_state !== "ai")
      fail(
        409,
        "human_handling_active",
        "会话正由人工处理，AI 回复已暂停；人工客服仍可从工作台发送答复。",
      );
    const rows = (this.state.messages[c.id] ||= []), callId = uuid();
    rows.push({
      id: uuid(),
      role: "user",
      created_by: c.channel === "public" ? null : userId,
      source: "agent",
      model_call_id: callId,
      content: body.content,
      created_at: now(),
      citations: [],
    });
    let answer = /人工|客服接管/.test(body.content)
      ? "可以由工作台客服接管此会话。离线演示不会连接真实客服中心。"
      : /不知道|价格|退款/.test(body.content)
        ? "演示知识库没有足够资料确认这个问题，请补充信息或联系人工客服。我不会编造具体政策。"
        : "这是离线模拟回复：你可以导入通用知识资料、配置 Agent 并发布网站客服。此静态 Demo 使用确定性内容，不调用模型。";
    const consent = (this.state.tables["user-memory-consents"] || []).find((v) => v.tenant_id === c.tenant_id && v.user_id === userId && v.enabled);
    const used = c.channel !== "public" && consent ? (this.state.tables["user-memories"] || []).filter((m) => m.tenant_id === c.tenant_id && m.user_id === userId && m.expires_at > now()) : [];
    if (used.length) answer += "（离线演示参考了你的个人记忆：" + used.map((m) => m.quote).join("；") + "）";
    const allowedKnowledge = body.knowledge_base_ids || this.state.bindings[body.agent_config_id || agentId] || [];
    const citations = (this.state.tables.documents || []).filter((doc) => doc.tenant_id === c.tenant_id && doc.status === "ready" && allowedKnowledge.includes(doc.knowledge_base_id)).flatMap((doc) => this.documentChunks(doc).filter((chunk) => chunk.generation === doc.generation && chunk.is_current && !chunk.is_deleted).map((chunk) => ({ chunk_id: chunk.id, document_id: doc.id, document_name: doc.filename, quote: chunk.content.slice(0, 600) }))).slice(0, 3);
    options.onEvent?.("stage", { phase: "retrieving" });
    options.onEvent?.("stage", { phase: "generating" });
    const message = {
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
    used.forEach((m) => { m.last_used_at = now(); });
    c.updated_at = now();
    (this.state.tables["model-calls"] ||= []).push({
      ...result, memory_usage: used.map((m) => ({ id: m.id, version: m.version })),
      status: "succeeded",
      tenant_id: c.tenant_id,
      model: "static-demo",
      provider: "demo",
      created_at: now(),
          steps: [],
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
        known_cost_subtotals: {},
        cost_complete: calls.length === 0,
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
