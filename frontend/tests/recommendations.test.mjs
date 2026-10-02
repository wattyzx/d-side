import assert from "node:assert/strict";
import { test } from "node:test";
import { addToWantlist, getRecommendations } from "../src/api/recommendations.ts";

const encoder = new TextEncoder();
const result = (id, score) => ({
  listing_id: id,
  release_id: id,
  title: "Café",
  score,
  score_breakdown: { total: score },
});
const eventLine = (recommendation) =>
  JSON.stringify({ type: "recommendation", recommendation }) + "\n";

test("publishes each result before completion and returns results sorted by score", async (t) => {
  let controller;
  const body = new ReadableStream({ start(value) { controller = value; } });
  t.mock.method(globalThis, "fetch", async () => new Response(body));
  const events = [];
  let received;
  const firstEvent = new Promise((resolve) => { received = resolve; });
  const pending = getRecommendations("user", "seller", {
    onEvent(event) { events.push(event); received(); },
  });
  controller.enqueue(encoder.encode(eventLine(result(1, 0.2))));
  await firstEvent;
  assert.equal(events.length, 1);
  assert.equal(events[0].recommendation.listing_id, 1);
  controller.enqueue(encoder.encode(eventLine(result(2, 0.9))));
  controller.enqueue(encoder.encode('{"type":"done"}\n'));
  assert.deepEqual((await pending).map((item) => item.listing_id), [2, 1]);
});

test("handles fragmented JSON and UTF-8 plus a final event without a newline", async (t) => {
  const bytes = encoder.encode(eventLine(result(1, 0.5)) + '{"type":"done"}');
  const body = new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  });
  t.mock.method(globalThis, "fetch", async () => new Response(body));
  const results = await getRecommendations("user", "seller");
  assert.equal(results[0].title, "Café");
});

test("reports interrupted streams after publishing available results", async (t) => {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(eventLine(result(1, 0.5))));
      controller.close();
    },
  });
  t.mock.method(globalThis, "fetch", async () => new Response(body));
  const events = [];
  await assert.rejects(
    getRecommendations("user", "seller", { onEvent: (event) => events.push(event) }),
    /ended before completion/,
  );
  assert.equal(events[0].recommendation.listing_id, 1);
});


test("continuation requests send scored releases without limiting inventory pages", async (t) => {
  let request;
  t.mock.method(globalThis, "fetch", async (_, options) => {
    request = JSON.parse(options.body);
    return new Response('{"type":"done","has_more":false}\n');
  });
  const events = [];
  await getRecommendations("user", "seller", {
    excludeReleaseIds: [1, 2],
    onEvent: (event) => events.push(event),
  });
  assert.deepEqual(request, {
    username: "user", seller: "seller", exclude_release_ids: [1, 2],
  });
  assert.equal(events[0].has_more, false);
});

test("wantlist saves post release IDs and surface backend errors", async (t) => {
  let request;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "http://127.0.0.1:8000/wantlist");
    assert.equal(options.method, "POST");
    request = JSON.parse(options.body);
    return new Response('{"added":true}');
  });
  await addToWantlist("user", 123);
  assert.deepEqual(request, { username: "user", release_id: 123 });
  t.mock.method(globalThis, "fetch", async () => new Response(
    '{"detail":"Token belongs to another user"}', { status: 403 },
  ));
  await assert.rejects(addToWantlist("user", 123), /Token belongs to another user/);
});
