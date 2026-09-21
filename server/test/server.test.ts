import assert from "node:assert/strict";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { CanvasClient } from "../src/canvas-client.js";
import { createServer } from "../src/server.js";

async function connectedClient(fetchImpl: typeof fetch) {
  const server = createServer(new CanvasClient("https://bcourses.berkeley.edu", "test-token", fetchImpl));
  const client = new Client({ name: "test-client", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

test("tool list contains student actions and excludes instructor creation", async () => {
  const fakeFetch: typeof fetch = async () => new Response("{}", { status: 200 });
  const { client, server } = await connectedClient(fakeFetch);
  const tools = await client.listTools();
  const names = new Set(tools.tools.map(tool => tool.name));

  assert.equal(names.has("submit_assignment"), true);
  assert.equal(names.has("post_discussion_entry"), true);
  assert.equal(names.has("create_personal_calendar_event"), true);
  assert.equal(names.has("create_assignment"), false);
  assert.equal(names.has("create_page"), false);
  assert.equal(names.has("grade_submission"), false);
  await Promise.all([client.close(), server.close()]);
});

test("send_message rejects course-wide recipients before calling Canvas", async () => {
  let calls = 0;
  const fakeFetch: typeof fetch = async () => {
    calls += 1;
    return new Response("{}", { status: 200 });
  };
  const { client, server } = await connectedClient(fakeFetch);
  const response = await client.callTool({
    name: "send_message",
    arguments: { recipientIds: ["course_123"], subject: "Hello", body: "No bulk messages" },
  });

  assert.equal(response.isError, true);
  assert.equal(calls, 0);
  await Promise.all([client.close(), server.close()]);
});

test("edit_own_discussion_entry rejects entries owned by someone else", async () => {
  const fakeFetch: typeof fetch = async input => {
    const url = String(input);
    if (url.endsWith("/users/self/profile")) return new Response(JSON.stringify({ id: 1 }), { status: 200 });
    if (url.includes("/entry_list")) return new Response(JSON.stringify([{ user_id: 2 }]), { status: 200 });
    return new Response("{}", { status: 200 });
  };
  const { client, server } = await connectedClient(fakeFetch);
  const response = await client.callTool({
    name: "edit_own_discussion_entry",
    arguments: { courseId: "1", topicId: "2", entryId: "9", message: "edited" },
  });

  assert.equal(response.isError, true);
  await Promise.all([client.close(), server.close()]);
});
