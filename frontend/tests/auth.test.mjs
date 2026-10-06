import assert from "node:assert/strict";
import { test } from "node:test";
import { getAccount, logout } from "../src/api/auth.ts";

test("checks identity with cookies and treats expired sessions as signed out", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/auth/me");
    assert.equal(options.credentials, "include");
    assert.equal(options.cache, "no-store");
    return new Response('{"authenticated":true,"username":"recordlover"}');
  });
  assert.equal((await getAccount()).username, "recordlover");
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 401 }));
  assert.equal(await getAccount(), null);
});

test("surfaces configuration failures instead of presenting them as signed out", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(
    '{"detail":"Discogs login is not configured"}', { status: 503 },
  ));
  await assert.rejects(getAccount(), /login is not configured/);
});

test("logout posts with credentials and surfaces failure", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/auth/logout");
    assert.equal(options.method, "POST");
    assert.equal(options.credentials, "include");
    return new Response('{"authenticated":false}');
  });
  await logout();
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 502 }));
  await assert.rejects(logout(), /Could not sign out/);
});
