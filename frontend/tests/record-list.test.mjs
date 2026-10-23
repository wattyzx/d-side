import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRecordList } from '../src/record-list.js';

function fixture() {
  const container = {
    children: [],
    insertBefore(row, reference) {
      const previous = this.children.indexOf(row);
      if (previous !== -1) this.children.splice(previous, 1);
      const index = reference ? this.children.indexOf(reference) : this.children.length;
      this.children.splice(index, 0, row);
    },
    get lastElementChild() { return this.children.at(-1); },
  };
  const render = createRecordList(record => ({
    id: record.release_id,
    rankLabel: { textContent: '', setAttribute() {} },
    wantlistButton: {},
    remove() { container.children.splice(container.children.indexOf(this), 1); },
  }));
  return { container, render: (records, options = {}) => render(container, records,
    'recommendations', { loading: false, disabled: false, ...options }) };
}
const records = count => Array.from({ length: count }, (_, i) => ({ release_id: i + 1 }));

test('desktop and mobile page boundaries keep global ranks and clamp shrinking results', () => {
  for (const pageSize of [15, 30]) {
    const f = fixture();
    assert.deepEqual(f.render(records(pageSize), { pageSize }), { page: 1, pages: 1 });
    assert.deepEqual(f.render(records(pageSize + 1), { pageSize, page: 2 }), { page: 2, pages: 2 });
    assert.equal(f.container.children.length, 1);
    assert.equal(f.container.children[0].id, pageSize + 1);
    assert.equal(f.container.children[0].rankLabel.textContent, `${pageSize + 1}.`);
    assert.equal(f.container.start, pageSize + 1);
    assert.deepEqual(f.render(records(2), { pageSize, page: 2 }), { page: 1, pages: 1 });
    assert.deepEqual(f.container.children.map(row => row.id), [1, 2]);
    assert.deepEqual(f.render([], { pageSize, page: 2 }), { page: 1, pages: 1 });
    assert.equal(f.container.children.length, 0);
  }
});

test('streaming preserves ordering across pages and final completion applies ranking', () => {
  const f = fixture();
  f.render(records(31), { loading: true });
  const firstRow = f.container.children[0];
  const reordered = records(32).reverse();
  f.render(reordered, { loading: true });
  assert.equal(f.container.children[0], firstRow);
  f.render(reordered, { loading: true, page: 2 });
  assert.deepEqual(f.container.children.map(row => row.id), [31, 32]);
  f.render(reordered, { page: 2 });
  assert.deepEqual(f.container.children.map(row => row.id), [2, 1]);
});
