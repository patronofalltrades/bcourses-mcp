import assert from "node:assert/strict";
import test from "node:test";
import { CanvasClient, CanvasApiError } from "../src/canvas-client.js";

test("CanvasClient sends the token only in the Authorization header", async () => {
  let observedUrl = "";
  let observedAuthorization = "";
  const fakeFetch: typeof fetch = async (input, init) => {
    observedUrl = String(input);
    observedAuthorization = new Headers(init?.headers).get("authorization") || "";
    return new Response(JSON.stringify({ id: 7 }), { status: 200, headers: { "content-type": "application/json" } });
  };

  const client = new CanvasClient("https://bcourses.berkeley.edu", "secret-token", fakeFetch);
  const result = await client.request<{ id: number }>("GET", "/api/v1/users/self/profile");

  assert.equal(result.id, 7);
  assert.equal(observedAuthorization, "Bearer secret-token");
  assert.equal(observedUrl.includes("secret-token"), false);
});

test("CanvasClient blocks arbitrary non-Canvas paths", async () => {
  const client = new CanvasClient("https://bcourses.berkeley.edu", "secret-token");
  await assert.rejects(() => client.request("GET", "/login"), /must begin with \/api\/v1\//);
});

test("CanvasClient returns sanitized Canvas errors", async () => {
  const fakeFetch: typeof fetch = async () => new Response(JSON.stringify({ errors: [{ message: "not allowed" }] }), { status: 403 });
  const client = new CanvasClient("https://bcourses.berkeley.edu", "secret-token", fakeFetch);
  await assert.rejects(
    () => client.request("GET", "/api/v1/courses"),
    (error: unknown) => error instanceof CanvasApiError && error.status === 403 && error.message === "not allowed",
  );
});
