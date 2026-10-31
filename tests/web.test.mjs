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

test("SSE preserves split UTF-8, returns only terminal results and rejects interrupted delivery", async () => {
  const { readEvents } = await import("../src/support_agent/web/stream.js");
  const raw = new TextEncoder().encode('event: delta\ndata: {"text":"中文"}\n\nevent: completed\ndata: {"status":"answered","answer":"中文"}\n\n');
  const make = (bytes) => new Response(new ReadableStream({start(c) { for (const byte of bytes) c.enqueue(Uint8Array.of(byte)); c.close(); }}), {headers: {"content-type":"text/event-stream"}});
  const events = [];
  assert.equal((await readEvents(make(raw), (e, d) => events.push([e, d]))).answer, "中文");
  assert.equal(events[0][1].text, "中文");
  let discarded = false;
  await assert.rejects(readEvents(make(raw.slice(0, 20)), (e) => { if (e === "discard") discarded = true; }), /未知/);
  assert.equal(discarded, true);
});
