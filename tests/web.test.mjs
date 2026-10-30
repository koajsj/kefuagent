import test from "node:test";
import assert from "node:assert/strict";
import { createClient, requestIdentity } from "../src/support_agent/web/api.js";

test("tenant switch cannot deliver stale data even when transport ignores cancellation", async () => {
  let finish;
  const client = createClient(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  client.setTenant("a");
  const request = client.request("/conversations");
  client.setTenant("b");
  finish({ ok: true, status: 200, json: async () => [{ tenant_id: "a" }] });
  await assert.rejects(request, { name: "StaleResponse" });
});

test("failed login retains its error when authenticated-session expiry handler changes context", async () => {
  const client = createClient(async () => ({
    ok: false,
    status: 401,
    json: async () => ({ error: { code: "invalid_credentials" } }),
  }));
  client.onUnauthorized(() => client.setTenant(""));
  await assert.rejects(
    client.request("/web-session", {
      method: "POST",
      body: { login: "wrong", password: "synthetic" },
    }),
    { code: "invalid_credentials", status: 401 },
  );
});

test("retry reuses request identity only for identical complete payload", async () => {
  const a = {
    agent_config_id: "one",
    content: "same",
    knowledge_base_ids: ["kb"],
  };
  const first = await requestIdentity(a);
  assert.equal((await requestIdentity(a, first)).key, first.key);
  assert.notEqual(
    (await requestIdentity({ ...a, agent_config_id: "two" }, first)).key,
    first.key,
  );
});

test("blocked browser storage still supports tab-local visitor and idempotency state", async () => {
  const { sessionState } = await import("../src/support_agent/web/storage.js");
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    get() {
      throw new Error("third-party storage blocked");
    },
  });
  assert.equal(sessionState.set("support.test", "scoped-value"), false);
  assert.equal(sessionState.get("support.test"), "scoped-value");
  sessionState.removePrefix("support.");
  assert.equal(sessionState.get("support.test"), null);
  delete globalThis.sessionStorage;
});
