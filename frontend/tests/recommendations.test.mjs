import assert from "node:assert/strict";
import { test } from "node:test";
import { addToWantlist, cancelSearch, getRecommendations } from "../src/api/recommendations.ts";

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

test("price bounds including zero are sent with continuation exclusions", async (t) => {
  t.mock.method(globalThis, "fetch", async (_, options) => {
    assert.deepEqual(JSON.parse(options.body), {
      seller: "shop", min_price: 0, max_price: 20.5, exclude_release_ids: [123],
    });
    return new Response('{"type":"done"}\n');
  });
  await getRecommendations("shop", { minPrice: 0, maxPrice: 20.5, excludeReleaseIds: [123] });
});

test("publishes each result before completion and returns results sorted by score", async (t) => {
  let controller;
  const body = new ReadableStream({ start(value) { controller = value; } });
  t.mock.method(globalThis, "fetch", async () => new Response(body));
  const events = [];
  let received;
  const firstEvent = new Promise((resolve) => { received = resolve; });
  const pending = getRecommendations("seller", {
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
  const results = await getRecommendations("seller");
  assert.equal(results[0].title, "Café");
});

test("ignores blank heartbeat lines between recommendation events", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(
    '\n' + eventLine(result(1, 0.5)) + '\n\n' + '{"type":"done"}\n',
  ));
  const events = [];
  const results = await getRecommendations("seller", { onEvent: event => events.push(event) });
  assert.equal(results.length, 1);
  assert.deepEqual(events.map(event => event.type), ["recommendation", "done"]);
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
    getRecommendations("seller", { onEvent: (event) => events.push(event) }),
    /ended before completion/,
  );
  assert.equal(events[0].recommendation.listing_id, 1);
});


test("continuation requests send scored releases without limiting inventory pages", async (t) => {
  let request;
  t.mock.method(globalThis, "fetch", async (_, options) => {
    assert.equal(options.credentials, "include");
    request = JSON.parse(options.body);
    return new Response('{"type":"done","has_more":false}\n');
  });
  const events = [];
  await getRecommendations("seller", {
    excludeReleaseIds: [1, 2],
    onEvent: (event) => events.push(event),
  });
  assert.deepEqual(request, {
    seller: "seller", exclude_release_ids: [1, 2],
  });
  assert.equal(events[0].has_more, false);
});

test("demand inventory is opt-in and its snapshots reach the UI", async (t) => {
  const records = [{ ...result(99, 0), demand_score: 2.5 }];
  t.mock.method(globalThis, "fetch", async (_, options) => {
    assert.equal(JSON.parse(options.body).include_demand, true);
    return new Response(JSON.stringify({ type: "demand_results", records }) + '\n' +
      '{"type":"done"}\n');
  });
  const events = [];
  assert.deepEqual(await getRecommendations("seller", {
    includeDemand: true, onEvent: event => events.push(event),
  }), []);
  assert.deepEqual(events[0].records, records);
});

test("wantlist saves post release IDs and surface backend errors", async (t) => {
  let request;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/wantlist");
    assert.equal(options.method, "POST");
    assert.equal(options.credentials, "include");
    request = JSON.parse(options.body);
    return new Response('{"added":true}');
  });
  await addToWantlist(123);
  assert.deepEqual(request, { release_id: 123 });
  t.mock.method(globalThis, "fetch", async () => new Response(
    '{"detail":"Token belongs to another user"}', { status: 403 },
  ));
  await assert.rejects(addToWantlist(123), /Token belongs to another user/);
});

test("cancelling retains published events, discards buffered events, and closes the reader", async (t) => {
  const controller = new AbortController();
  let cancelled = false;
  const body = new ReadableStream({
    start(stream) {
      stream.enqueue(encoder.encode(eventLine(result(1, 0.5)) + eventLine(result(2, 0.7))));
    },
    cancel() { cancelled = true; },
  });
  t.mock.method(globalThis, "fetch", async (_, options) => {
    assert.equal(JSON.parse(options.body).search_id, "search-123");
    return new Response(body);
  });
  const events = [];
  await assert.rejects(getRecommendations("shop", {
    searchId: "search-123", signal: controller.signal,
    onEvent(event) { events.push(event); controller.abort(); },
  }), { name: "AbortError" });
  assert.equal(events.length, 1);
  assert.equal(events[0].recommendation.release_id, 1);
  assert.equal(cancelled, true);
});

test("a search cancelled before starting makes no request", async (t) => {
  const controller = new AbortController();
  controller.abort();
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("Unexpected request"); });
  await assert.rejects(getRecommendations("shop", { signal: controller.signal }), { name: "AbortError" });
  assert.equal(fetch.mock.callCount(), 0);
});

test("the cancellation request identifies its own search and preserves backend conflict messages", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/recommend/cancel");
    assert.equal(options.credentials, "include");
    assert.deepEqual(JSON.parse(options.body), { search_id: "search-123" });
    return new Response('{"cancelled":true}');
  });
  await cancelSearch("search-123");
  t.mock.method(globalThis, "fetch", async () => new Response(
    '{"detail":"A search is already running for your account"}', { status: 409 },
  ));
  await assert.rejects(getRecommendations("shop"), /already running/);
});
