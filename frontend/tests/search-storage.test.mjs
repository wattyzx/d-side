import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createSearchStorage } from '../src/search-storage.js';

function fixture() {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const search = {
    seller: 'shop', priceRange: { minPrice: 0, maxPrice: 30 }, hasMore: true,
    records: [{ release_id: 1, listing_id: 2, title: 'Record', artists: [],
      labels: [], styles: [], score: 0.5, score_breakdown: {} }],
    wants: [], demands: [], tab: 'recommendations',
    activeId: '00000000-0000-0000-0000-000000000001',
  };
  return { storage, search, values };
}

test('restores results, filters and interrupted search ID after a page reload', () => {
  const { storage, search } = fixture();
  assert.equal(createSearchStorage(storage).save('alice', search), true);
  assert.deepEqual(createSearchStorage(storage).load('alice'), search);
});

test('does not restore another account’s results and clears them', () => {
  const { storage, search, values } = fixture();
  const store = createSearchStorage(storage);
  store.save('alice', search);
  assert.equal(store.load('bob'), null);
  assert.equal(values.size, 0);
});

test('expired, corrupt and malformed saved results are discarded', () => {
  const { storage, search } = fixture();
  createSearchStorage(storage, () => 0).save('alice', search);
  assert.equal(createSearchStorage(storage, () => 86400001).load('alice'), null);
  storage.setItem('dside.search.v1', '{');
  assert.equal(createSearchStorage(storage).load('alice'), null);
  createSearchStorage(storage).save('alice', { ...search, records: [{}] });
  assert.equal(createSearchStorage(storage).load('alice'), null);
});

test('quota errors clear stale snapshots and disabled storage does not break searching', () => {
  const { storage, search, values } = fixture();
  const store = createSearchStorage(storage);
  store.save('alice', search);
  storage.setItem = () => { throw new Error('quota'); };
  assert.equal(store.save('alice', { ...search, seller: 'new-shop' }), false);
  assert.equal(values.size, 0);
  assert.equal(createSearchStorage(undefined).save('alice', search), false);
  assert.equal(createSearchStorage(undefined).load('alice'), null);
});

test('completed searches restore without automatic resume and logout clears the snapshot', () => {
  const { storage, search } = fixture();
  const store = createSearchStorage(storage);
  store.save('alice', { ...search, activeId: null, hasMore: false });
  assert.equal(store.load('alice').activeId, null);
  assert.equal(store.load('alice').hasMore, false);
  store.clear();
  assert.equal(store.load('alice'), null);
});
