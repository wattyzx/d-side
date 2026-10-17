import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { createSearchStorage } from '../src/search-storage.js';
import { session } from '../src/session.ts';

const record = id => ({ release_id: id, listing_id: id + 100, title: `Record ${id}`,
  artists: ['Artist'], labels: [], styles: [], score: 0.5, score_breakdown: { total: 0.5 },
  price: 10, currency: 'EUR', videos: [] });

async function until(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('Expected UI operation did not finish');
}

function fixture(t) {
  function element(id = '') {
    return { id, value: '', textContent: '', children: [], attributes: {},
      get valueAsNumber() { return Number(this.value); },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      setAttribute(key, value) { this.attributes[key] = value; },
      setCustomValidity() {}, reportValidity() { return true; },
      classList: { toggle() {} },
    };
  }
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)]
    .map(([, id]) => [id, element(id)]));
  const values = new Map();
  const storage = { getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const listeners = {};
  const globals = {
    document: { getElementById: id => elements[id], querySelectorAll: () => Object.values(elements),
      createElement: () => element(), body: element() },
    window: { sessionStorage: storage, addEventListener: (event, listener) => { listeners[event] = listener; } },
    location: { search: '' },
  };
  for (const [key, value] of Object.entries(globals)) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    t.after(() => {
      if (original) Object.defineProperty(globalThis, key, original);
      else delete globalThis[key];
    });
  }
  return { elements, store: createSearchStorage(storage), listeners };
}

test('reload restores results, waits for old search cancellation, resumes, and clears on logout', async t => {
  const { elements, store } = fixture(t);
  const oldId = '00000000-0000-0000-0000-000000000001';
  store.save('Alice', { seller: 'shop', priceRange: { minPrice: 0, maxPrice: 20 },
    records: [record(1)], wants: [], demands: [], tab: 'recommendations',
    hasMore: true, activeId: oldId });
  let acknowledgeCancel;
  const cancelled = new Promise(resolve => { acknowledgeCancel = resolve; });
  let controller;
  const body = new ReadableStream({ start(value) { controller = value; } });
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    if (url === '/auth/me') return Response.json({ username: 'Alice', authenticated: true });
    if (url === '/recommend/cancel') { await cancelled; return Response.json({ cancelled: true }); }
    if (url === '/recommend/stream') return new Response(body);
    if (url === '/auth/logout') return Response.json({ authenticated: false });
    throw new Error(`Unexpected request ${url}`);
  });
  await import('../src/main.js?recovery-test');
  await until(() => calls.some(call => call.url === '/recommend/cancel'));
  assert.equal(elements.results.children.length, 1);
  assert.equal(elements.seller.value, 'shop');
  assert.equal(calls.some(call => call.url === '/recommend/stream'), false);
  assert.equal(store.load('Alice').activeId, oldId);
  acknowledgeCancel();
  await until(() => calls.some(call => call.url === '/recommend/stream'));
  const request = JSON.parse(calls.find(call => call.url === '/recommend/stream').options.body);
  assert.deepEqual(request.exclude_release_ids, [1]);
  assert.equal(request.min_price, 0);
  assert.equal(request.max_price, 20);
  assert.notEqual(request.search_id, oldId);
  const encoder = new TextEncoder();
  controller.enqueue(encoder.encode(JSON.stringify({ type: 'recommendation', recommendation: record(2) }) + '\n'));
  controller.enqueue(encoder.encode('{"type":"done","has_more":false}\n'));
  await until(() => elements.results.children.length === 2 && !elements.search.disabled);
  assert.equal(store.load('Alice').activeId, null);
  assert.equal(store.load('Alice').hasMore, false);
  function descendants(item) { return [item, ...item.children.flatMap(descendants)]; }
  const buy = elements.results.children.flatMap(descendants)
    .find(item => item.textContent === '🛒 ↗');
  assert.equal(buy.href, 'https://www.discogs.com/sell/item/101');
  assert.equal(buy.target, '_blank');
  await elements.account.children.find(item => item.textContent === 'Sign out').onclick();
  assert.equal(store.load('Alice'), null);
  assert.equal(elements['results-layout'].hidden, true);
  assert.equal(session.getSnapshot().expired, false);
});

for (const navigationEvent of ['beforeunload', 'pagehide']) {
  test(`${navigationEvent} preserves the active search when the departing request reports a network error`, async t => {
    const { elements, store, listeners } = fixture(t);
    store.save('Alice', { seller: 'shop', priceRange: {}, records: [record(1)],
      wants: [], demands: [], tab: 'recommendations', hasMore: true, activeId: null });
    let rejectRequest;
    let request;
    t.mock.method(globalThis, 'fetch', async (url, options) => {
      if (url === '/auth/me') return Response.json({ username: 'Alice', authenticated: true });
      if (url === '/recommend/stream') {
        request = JSON.parse(options.body);
        return new Promise((_, reject) => { rejectRequest = reject; });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    await import(`../src/main.js?navigation-${navigationEvent}`);
    await until(() => !elements.search.disabled && elements.results.children.length === 1);
    const pending = elements.more.onclick();
    await until(() => rejectRequest);
    listeners[navigationEvent]();
    const snapshot = store.load('Alice');
    assert.equal(snapshot.activeId, request.search_id);
    rejectRequest(new TypeError('network error'));
    await pending;
    assert.deepEqual(store.load('Alice'), snapshot);
    assert.equal(elements.error.textContent, '');
    assert.equal(elements.status.textContent.includes('Stopped before completion'), false);
  });
}

test('logo clears results and cancels recovery without restarting the search', async t => {
  const { elements, store, listeners } = fixture(t);
  const oldId = '00000000-0000-0000-0000-000000000001';
  store.save('Alice', { seller: 'shop', priceRange: { minPrice: 5 },
    records: [record(1)], wants: [], demands: [], tab: 'recommendations',
    hasMore: true, activeId: oldId });
  let finishCancel;
  const cancelled = new Promise(resolve => { finishCancel = resolve; });
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push(url);
    if (url === '/auth/me') return Response.json({ username: 'Alice', authenticated: true });
    if (url === '/recommend/cancel') {
      assert.equal(JSON.parse(options.body).search_id, oldId);
      await cancelled;
      return Response.json({ cancelled: true });
    }
    throw new Error(`Unexpected request ${url}`);
  });
  await import('../src/main.js?home-reset-test');
  await until(() => calls.includes('/recommend/cancel'));
  let prevented = false;
  const reset = elements.home.onclick({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(elements['results-layout'].hidden, true);
  assert.equal(elements.seller.value, '');
  assert.equal(elements['min-price'].value, '');
  assert.equal(store.load('Alice'), null);
  finishCancel();
  await reset;
  await until(() => !elements.search.disabled);
  assert.equal(calls.includes('/recommend/stream'), false);
  assert.equal(elements.error.textContent, '');
  assert.equal(elements.account.children[0].textContent, 'Alice');
  listeners.pagehide();
  assert.equal(store.load('Alice'), null);
});
