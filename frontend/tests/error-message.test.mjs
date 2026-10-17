import assert from 'node:assert/strict';
import { test } from 'node:test';
import { errorMessage } from '../src/error-message.js';

test('browser network errors explain how to recover', () => {
  for (const text of ['network error', 'Failed to fetch', 'Load failed',
    'NetworkError when attempting to fetch resource.', 'The network connection was lost.']) {
    assert.match(errorMessage(new TypeError(text)), /Check your internet connection/);
  }
});

test('interrupted streams explain that results are retained', () => {
  assert.match(errorMessage(new Error('Recommendation stream ended before completion')),
    /results are kept; choose Search more/);
});

test('specific validation messages are preserved and missing errors have a fallback', () => {
  const message = 'Enter a seller username or a Discogs shop/profile URL.';
  assert.equal(errorMessage(new Error(message)), message);
  assert.equal(errorMessage(message), message);
  assert.equal(errorMessage(null), 'Something went wrong. Please try again.');
});
