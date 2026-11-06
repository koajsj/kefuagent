export type Row = { id: string; [key: string]: any };
export type RequestOptions = {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  onEvent?: (event: string, value: any) => void;
  visitorToken?: string;
  onHeaders?: (headers: Headers) => void;
};
export interface Adapter {
  readonly mode: "api" | "demo";
  request<T = any>(path: string, options?: RequestOptions): Promise<T>;
  setTenant(id: string): void;
  onUnauthorized(callback: () => void): void;
}
export type Session = {
  user: Row;
  tenant: string;
  role: string;
  workspace: Row | null;
};

export interface MemoryConsent {
  enabled: boolean;
  version: number;
}
export interface UserMemory extends Row {
  memory_key: string;
  quote: string;
  source_conversation_id: string;
  source_message_id: string;
  version: number;
  expires_at: string;
  created_at: string;
  updated_at: string;
}
export interface MemoryInput {
  source_message_id: string;
  quote: string;
  expected_version?: number | null;
  retention_days: number;
}

// Wire names intentionally match FastAPI's schemas; authorization remains server-side.
export type SupportState = "ai" | "waiting" | "human" | "resolved";
export type Priority = "low" | "normal" | "high" | "urgent";
export interface Conversation extends Row {
  tenant_id: string;
  subject: string;
  channel: string;
  status: "open" | "closed";
  support_state: SupportState;
  assignee_id: string | null;
  version: number;
  priority: Priority;
  tags: string[];
  category: string;
  created_at: string;
  updated_at: string;
  sla: Record<string, string | number | null>;
}
export interface Agent extends Row {
  name: string;
  enabled: boolean;
  provider: string;
  model: string;
  version: number;
  base_url: string | null;
  credential_ref: string | null;
  behavior: { description: string; instructions: string; language: string };
  runtime: {
    max_input_tokens: number;
    max_output_tokens: number;
    timeout_seconds: number;
    supports_tools: boolean;
    [key: string]: unknown;
  };
}
export interface MessageRecord extends Row {
  role: "user" | "assistant" | "tool";
  content: string;
  created_at: string;
  model_call_id?: string | null;
  tool_call_id?: string | null;
}
export interface TurnOutcome {
  conversation_id: string;
  call_id: string;
  request_id: string;
  status: "running" | "answered" | "failed" | "unresolved";
  answer: string;
  error_category: string | null;
  executions: Row[];
  grounded: boolean;
  citations: Row[];
}
