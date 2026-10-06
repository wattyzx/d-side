import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { accountQueryKey, bindSessionToQueryClient, createSession, session } from "../src/session.ts";
import { getAccount, logout } from "../src/api/auth.ts";
import { addToWantlist, getRecommendations } from "../src/api/recommendations.ts";
import { SessionChangedError, SessionExpiredError } from "../src/api/http.ts";

beforeEach(() => session.signOut());

test("an anonymous identity check stays signed out without an expiry prompt", async (t) => {
  const revision = session.getSnapshot().revision;
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 401 }));
  assert.equal(await getAccount(), null);
  assert.deepEqual(session.getSnapshot(), { revision, expired: false });
});

test("an expired identity check clears a previously authenticated session", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response('{"authenticated":true,"username":"Alice"}'));
  await getAccount();
  const oldSignal = session.getSignal();
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 401 }));
  assert.equal(await getAccount(), null);
  assert.equal(session.getSnapshot().expired, true);
  assert.equal(oldSignal.aborted, true);
});

test("all protected requests handle 401 consistently", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response('{"detail":"Sign in"}', { status: 401 }));
  for (const operation of [() => getRecommendations("shop"), () => addToWantlist(123), logout]) {
    session.signOut();
    await assert.rejects(operation(), SessionExpiredError);
    assert.equal(session.getSnapshot().expired, true);
  }
});

test("ordinary server failures preserve the account and do not expire its session", async (t) => {
  session.signIn();
  const snapshot = session.getSnapshot();
  const signal = session.getSignal();
  t.mock.method(globalThis, "fetch", async () => new Response('{"detail":"Discogs is unavailable"}', { status: 502 }));
  await assert.rejects(addToWantlist(123), /Discogs is unavailable/);
  assert.equal(session.getSnapshot(), snapshot);
  assert.equal(signal.aborted, false);
});

test("expiry clears the query cache and prevents a delayed identity response restoring it", async (t) => {
  const client = new QueryClient();
  t.after(() => client.clear());
  t.after(bindSessionToQueryClient(client));
  client.setQueryData(accountQueryKey, { authenticated: true, username: "Alice" });
  session.signIn();
  let resolveIdentity;
  t.mock.method(globalThis, "fetch", (url) => url === "/auth/me"
    ? new Promise((resolve) => { resolveIdentity = resolve; })
    : Promise.resolve(new Response(null, { status: 401 })));
  const pending = client.fetchQuery({ queryKey: accountQueryKey, queryFn: getAccount, retry: false }).catch(() => null);
  await assert.rejects(addToWantlist(123), SessionExpiredError);
  assert.equal(client.getQueryData(accountQueryKey), null);
  resolveIdentity(new Response('{"authenticated":true,"username":"Alice"}'));
  await pending;
  assert.equal(client.getQueryData(accountQueryKey), null);
  assert.equal(session.getSnapshot().expired, true);
});

test("late successful saves cannot update results after session expiry", async (t) => {
  let resolveSave;
  t.mock.method(globalThis, "fetch", (url) => url === "/wantlist"
    ? new Promise((resolve) => { resolveSave = resolve; })
    : Promise.resolve(new Response(null, { status: 401 })));
  const pending = addToWantlist(123);
  const rejected = assert.rejects(pending, SessionExpiredError);
  await assert.rejects(getRecommendations("shop"), SessionExpiredError);
  resolveSave(new Response('{"added":true}'));
  await rejected;
});

test("stream events received after expiry are discarded and the reader is cancelled", async (t) => {
  let controller;
  let cancelled = false;
  let firstEvent;
  const received = new Promise((resolve) => { firstEvent = resolve; });
  const body = new ReadableStream({
    start(value) { controller = value; },
    cancel() { cancelled = true; },
  });
  t.mock.method(globalThis, "fetch", async (url) => url === "/recommend/stream"
    ? new Response(body) : new Response(null, { status: 401 }));
  const events = [];
  const pending = getRecommendations("shop", { onEvent(event) { events.push(event); firstEvent(); } });
  const rejected = assert.rejects(pending, SessionExpiredError);
  controller.enqueue(new TextEncoder().encode('{"type":"status","message":"Scanning"}\n'));
  await received;
  await assert.rejects(addToWantlist(123), SessionExpiredError);
  controller.enqueue(new TextEncoder().encode('{"type":"recommendation","recommendation":{"release_id":123}}\n'));
  await rejected;
  assert.equal(events.length, 1);
  assert.equal(cancelled, true);
});

test("logout clears cached identity and pending requests without an expiry prompt", async (t) => {
  const client = new QueryClient();
  t.after(() => client.clear());
  t.after(bindSessionToQueryClient(client));
  client.setQueryData(accountQueryKey, { authenticated: true, username: "Alice" });
  session.signIn();
  let resolveSave;
  t.mock.method(globalThis, "fetch", (url) => url === "/wantlist"
    ? new Promise((resolve) => { resolveSave = resolve; })
    : Promise.resolve(new Response('{"authenticated":false}')));
  const pending = addToWantlist(123);
  const rejected = assert.rejects(pending, SessionChangedError);
  await logout();
  assert.equal(client.getQueryData(accountQueryKey), null);
  assert.equal(session.getSnapshot().expired, false);
  resolveSave(new Response('{"added":true}'));
  await rejected;
});

test("repeated expiry is handled once and a confirmed account clears the prompt", () => {
  const state = createSession();
  let ended = 0;
  state.onEnd(() => { ended++; });
  state.expire();
  state.expire();
  assert.equal(ended, 1);
  assert.equal(state.getSnapshot().expired, true);
  state.signIn();
  assert.equal(state.getSnapshot().expired, false);
});
