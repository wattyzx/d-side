import assert from 'node:assert/strict';
import { test } from 'node:test';
import { youtubeVideoId, playableVideos, createReleasePlayer } from '../src/player.js';

const first = { uri: 'https://www.youtube.com/watch?v=abcdefghijk', title: 'First song', embed: true };
const second = { uri: 'https://youtu.be/lmnopqrstuv', title: 'Second song', embed: true };
const record = { title: 'Album', artists: ['Artist'], videos: [first, second] };
const flush = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };

function fixture({ delayedApi = false } = {}) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, disabled: false, textContent: '', attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; },
    });
    return elements.get(id);
  };
  const classes = new Set();
  const scripts = [];
  const document = {
    getElementById: element,
    body: { classList: { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); } } },
    head: { append(script) { scripts.push(script); } },
    createElement() { return { remove() { this.removed = true; } }; },
  };
  let player;
  const api = { Player: class {
    constructor(_, options) {
      player = this;
      this.events = options.events;
      this.loaded = [];
      this.iframe = element('iframe');
      queueMicrotask(() => this.events.onReady({ target: this }));
    }
    getIframe() { return this.iframe; }
    loadVideoById(id) { this.loaded.push(id); }
    playVideo() { this.events.onStateChange({ data: 1 }); }
    pauseVideo() { this.events.onStateChange({ data: 2 }); }
    stopVideo() { this.stopped = true; }
  } };
  const window = { location: { origin: 'http://localhost:5174' },
    setTimeout() { return 1; }, clearTimeout() {},
    ...(delayedApi ? {} : { YT: api }),
  };
  const controller = createReleasePlayer({ document, window });
  return { controller, element, classes, scripts, window, get player() { return player; },
    finishApi() { window.YT = api; window.onYouTubeIframeAPIReady(); } };
}

test('extracts supported video URLs and rejects other hosts or invalid IDs', () => {
  for (const uri of [first.uri, 'https://youtu.be/abcdefghijk?t=3',
    'https://www.youtube.com/embed/abcdefghijk', 'https://www.youtube.com/shorts/abcdefghijk']) {
    assert.equal(youtubeVideoId(uri), 'abcdefghijk');
  }
  for (const uri of ['javascript:alert(1)', 'https://youtube.com.example.org/watch?v=abcdefghijk',
    'https://www.youtube.com/watch?v=short', 'not a URL']) assert.equal(youtubeVideoId(uri), null);
});

test('preserves playable video order, skips non-embeddable entries, and deduplicates IDs', () => {
  assert.deepEqual(playableVideos({ videos: [{ ...first, embed: false }, second, second] }).map(video => video.id), ['lmnopqrstuv']);
  assert.deepEqual(playableVideos({}), []);
});

test('starts the first song, advances, handles pause and blocked playback, and closes', async () => {
  const f = fixture();
  assert.equal(f.element('player-bar').hidden, true);
  await f.controller.play(record);
  assert.deepEqual(f.player.loaded, ['abcdefghijk']);
  assert.equal(f.element('player-title').textContent, 'First song');
  assert.equal(f.element('player-position').textContent, '1/2');
  assert.equal(f.element('player-video').hidden, false);
  f.element('player-toggle').onclick();
  assert.equal(f.element('player-toggle').textContent, '⏸');
  f.element('player-toggle').onclick();
  assert.equal(f.element('player-toggle').textContent, '▶');
  f.element('player-next').onclick();
  assert.deepEqual(f.player.loaded, ['abcdefghijk', 'lmnopqrstuv']);
  assert.equal(f.element('player-position').textContent, '2/2');
  assert.equal(f.element('player-next').disabled, true);
  f.player.events.onAutoplayBlocked();
  assert.equal(f.element('player-message').textContent, 'Press Play to start.');
  f.player.events.onError();
  assert.match(f.element('player-message').textContent, /unavailable/);
  f.controller.close();
  assert.equal(f.player.stopped, true);
  assert.equal(f.element('player-video').hidden, true);
  assert.equal(f.classes.has('player-open'), false);
});

test('automatically advances on completion and switches releases without another player', async () => {
  const f = fixture();
  await f.controller.play(record);
  const instance = f.player;
  f.player.events.onStateChange({ data: 0 });
  assert.equal(f.element('player-title').textContent, 'Second song');
  await f.controller.play({ ...record, videos: [second] });
  assert.equal(f.player, instance);
  assert.equal(f.element('player-position').textContent, '1/1');
});

test('only the latest cover click starts playback while the API is loading', async () => {
  const f = fixture({ delayedApi: true });
  const a = f.controller.play(record);
  const b = f.controller.play({ ...record, videos: [second] });
  assert.equal(f.scripts.length, 1);
  f.finishApi();
  await Promise.all([a, b]);
  assert.deepEqual(f.player.loaded, ['lmnopqrstuv']);
});

test('closing before API initialization prevents delayed playback', async () => {
  const f = fixture({ delayedApi: true });
  const pending = f.controller.play(record);
  f.controller.close();
  f.finishApi();
  await pending;
  assert.equal(f.player, undefined);
  assert.equal(f.element('player-bar').hidden, true);
  await f.controller.play(record);
  assert.deepEqual(f.player.loaded, ['abcdefghijk']);
});

test('script failures show a retryable error and reopening can succeed', async () => {
  const f = fixture({ delayedApi: true });
  const pending = f.controller.play(record);
  f.scripts[0].onerror();
  await pending;
  assert.match(f.element('player-message').textContent, /Could not load YouTube/);
  const retry = f.controller.play(record);
  await flush();
  f.finishApi();
  await retry;
  assert.deepEqual(f.player.loaded, ['abcdefghijk']);
});
