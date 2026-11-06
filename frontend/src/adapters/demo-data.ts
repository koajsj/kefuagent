import type { Row } from "../types";
export const uuid = () => crypto.randomUUID(),
  now = () => new Date().toISOString();
export function fail(status: number, code: string, message: string): never {
  throw Object.assign(new Error(message), { status, code });
}
export type State = {
  tenant: string;
  tables: Record<string, Row[]>;
  messages: Record<string, Row[]>;
  notes: Record<string, Row[]>;
  bindings: Record<string, string[]>;
  grants: Record<string, Row[]>;
  visitors: Row[];
  identities: Record<string, Row>;
};
export const tenantId = "10000000-0000-4000-8000-000000000001",
  userId = "20000000-0000-4000-8000-000000000001",
  agentId = "30000000-0000-4000-8000-000000000001",
  kbId = "40000000-0000-4000-8000-000000000001",
  publicationId = "50000000-0000-4000-8000-000000000001";
export function seed(): State {
  const conversations = [
    "开通团队工作区",
    "如何导入服务资料？",
    "需要人工协助配置模型",
    "发票申请需要什么资料？",
    "公开客服接入咨询",
    "文档更新后的检索",
  ].map((subject, i) => ({
    id: `60000000-0000-4000-8000-00000000000${i + 1}`,
    tenant_id: tenantId,
    subject,
    channel: i < 3 ? "public" : "web",
    status: i === 3 ? "closed" : "open",
    handling_mode: i === 2 ? "human" : "ai",
    support_state: i === 3 ? "resolved" : i === 2 ? "human" : "ai",
    priority: i === 2 ? "high" : "normal",
    tags: i === 2 ? ["配置咨询"] : [],
    category: "产品咨询",
    assignee_id: i === 2 ? userId : null,
    version: 1,
    created_at: now(),
    updated_at: now(),
    first_response_at: now(),
    resolved_at: i === 3 ? now() : null,
    sla_due_at: null,
  }));
  const messages: Record<string, Row[]> = {};
  for (const [i, c] of conversations.entries())
    messages[c.id] = [
      {
        id: uuid(),
        role: "user",
        created_by: userId,
        source: "agent",
        content: [
          "你好，团队版如何开通？",
          "可以导入 Markdown 文档吗？",
          "模型配置遇到了问题，想找人工客服。",
          "开具发票需要提供什么？",
          "怎样把客服放到网站上？",
          "更新资料后会立即生效吗？",
        ][i],
        created_at: now(),
        metadata: {},
        citations: [],
      },
      {
        id: uuid(),
        role: "assistant",
        content:
          "你好，这里是离线演示客服。星河团队服务支持创建工作区、导入知识文档和发布客服入口。所有数据均为虚构，不会调用真实模型。",
        created_at: now(),
        metadata: {},
        citations: [
          {
            chunk_id: "demo-chunk",
            document_id: "demo-doc",
            document_name: "星河服务指南.md",
            quote: "团队服务支持创建工作区、导入知识文档和发布客服入口。",
            content: "团队服务支持创建工作区、导入知识文档和发布客服入口。",
          },
        ],
      },
    ];
  return {
    tenant: tenantId,
    tables: {
      tenants: [
        {
          id: tenantId,
          name: "星河团队 · 演示空间",
          slug: "starlight-demo",
          status: "active",
          created_at: now(),
        },
      ],
      users: [
        {
          id: userId,
          login: "demo@kefuagent.local",
          display_name: "演示管理员",
          is_platform_admin: true,
          status: "active",
        },
      ],
      memberships: [
        {
          id: uuid(),
          user_id: userId,
          tenant_id: tenantId,
          role: "admin",
          status: "active",
        },
      ],
      "agent-configs": [
        {
          id: agentId,
          tenant_id: tenantId,
          name: "星河服务助手",
          provider: "demo",
          model: "offline-demo",
          enabled: true,
          version: 1,
          credential_ref: null,
          base_url: null,
          behavior: {
            description: "通用产品服务演示",
            instructions:
              "仅根据虚构服务资料提供帮助。资料不足时澄清并建议人工服务。",
            language: "zh-CN",
          },
          runtime: {
            temperature: 0.2,
            max_input_tokens: 16000,
            max_output_tokens: 1000,
            timeout_seconds: 30,
            supports_tools: true,
            token_parameter: "max_completion_tokens",
            send_temperature: false,
            routing: {},
          },
          created_at: now(),
          updated_at: now(),
        },
      ],
      "knowledge-bases": [
        {
          id: kbId,
          tenant_id: tenantId,
          name: "星河产品服务指南",
          description: "虚构服务、使用流程及常见问题",
          status: "active",
          created_at: now(),
        },
      ],
      documents: [
        {
          id: "demo-doc",
          tenant_id: tenantId,
          knowledge_base_id: kbId,
          filename: "星河服务指南.md",
          status: "ready",
          chunk_count: 3,
          error_category: null,
          created_at: now(),
        },
      ],
      tools: [
        {
          id: "70000000-0000-4000-8000-000000000001",
          tenant_id: tenantId,
          key: "workspace_info",
          name: "工作区信息",
          description: "静态只读能力演示",
          version: 1,
          enabled: true,
          execution_type: "read_only",
          risk_level: "low",
          permissions: ["tools:invoke"],
          input_schema: {
            type: "object",
            properties: {},
            additionalProperties: false,
          },
          output_schema: { type: "object" },
        },
      ],
      publications: [
        {
          id: publicationId,
          tenant_id: tenantId,
          agent_config_id: agentId,
          name: "星河在线客服",
          enabled: true,
          available: true,
          version: 1,
          agent_version: 1,
          public_tool_ids: [],
          requires_republish: false,
          revoked_at: null,
          created_at: now(),
        },
      ],
      conversations,
      "model-calls": [],
      "tool-executions": [],
      "audit-events": [],
      "model-credentials": [],
    },
    messages,
    notes: Object.fromEntries(
      conversations.map((c) => [
        c.id,
        [
          {
            id: uuid(),
            kind: "note",
            actor_id: userId,
            content: "这是内部协作记录，不会出现在访客端。",
            details: {},
            created_at: now(),
          },
        ],
      ]),
    ),
    bindings: { [agentId]: [kbId] },
    grants: {},
    visitors: [],
    identities: {},
  };
}
