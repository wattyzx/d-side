// API and session modules are bundled by Vite alongside the vanilla UI.
import { getAccount, logout, discogsLoginUrl } from './api/auth.ts';
import { getRecommendations, cancelSearch, addToWantlist, sortRecommendations } from './api/recommendations.ts';
import { session } from './session.ts';
import { createReleasePlayer, playableVideos } from './player.js';
import { createSearchStorage } from './search-storage.js';

// Accessing sessionStorage itself can throw in restricted browser contexts.
let browserStorage;
try { browserStorage = window.sessionStorage; } catch { /* Recovery unavailable. */ }
const searchStorage = createSearchStorage(browserStorage);
let restoredSearch = false;
let leavingPage = false;
let searchViewRevision = 0;
let returningHome = false;

const previewPlayer = createReleasePlayer();

const elements = Object.fromEntries([...document.querySelectorAll('[id]')].map(node => [node.id, node]));
const state = { account: null, checking: true, active: null, cancelling: false, saving: false,
  recoveringId: null,
  seller: '', searched: false, hasMore: true, records: [], wants: [], demands: [],
  tab: 'recommendations', expanded: new Set(), priceRange: {} };
const tabs = [
  { name: 'recommendations', button: 'recommendations-tab', panel: 'results-section' },
  { name: 'wantlist', button: 'wantlist-tab', panel: 'wantlist-section' },
  { name: 'demand', button: 'demand-tab', panel: 'demand-section' },
];
const loginErrors = {
  incomplete: 'Discogs login was cancelled or incomplete. Please try again.',
  expired: 'Your login expired or did not match this browser. Please try again.',
  used: 'This login has already been used. Please try again.',
  provider: 'Could not connect with Discogs. Please try again.',
};
const authError = new URLSearchParams(location.search).get('auth_error');
if (authError) elements['account-error'].textContent = loginErrors[authError] ?? loginErrors.provider;

function node(tag, text, className) {
  const value = document.createElement(tag);
  if (text !== undefined) value.textContent = text;
  if (className) value.className = className;
  return value;
}
function link(text, href, external = false) {
  const value = node('a', text);
  value.href = href;
  if (external) { value.target = '_blank'; value.rel = 'noopener noreferrer'; }
  return value;
}
function busy() { return !!state.active || state.cancelling || state.saving; }
function status(text) { elements.status.textContent = text; }

function persistSearch() {
  if (leavingPage || !state.account || !state.searched) return;
  const saved = searchStorage.save(state.account.username, {
    seller: state.seller, priceRange: state.priceRange, hasMore: state.hasMore,
    records: state.records, wants: state.wants, demands: state.demands, tab: state.tab,
    activeId: state.recoveringId ?? (state.active && !state.active.done && !state.cancelling ? state.active.id : null),
    status: elements.status.textContent, notice: elements.notice.textContent,
    error: elements.error.textContent,
  });
  elements['recovery-warning'].hidden = saved;
}

function prepareNavigation() {
  if (leavingPage) return;
  // Save the active ID before aborting. Navigation failures from the old page
  // must not turn this recoverable search into a completed/failed snapshot.
  persistSearch();
  leavingPage = true;
  state.active?.controller.abort();
}
window.addEventListener('beforeunload', prepareNavigation);
window.addEventListener('pagehide', prepareNavigation);
window.addEventListener('pageshow', () => {
  // A browser may restore this document from its back/forward cache.
  if (!leavingPage) return;
  leavingPage = false;
  state.active = null;
  state.cancelling = false;
  state.recoveringId = null;
  restoredSearch = false;
  void checkAccount();
});

function priceRange() {
  return {
    minPrice: elements['min-price'].value === '' ? undefined : elements['min-price'].valueAsNumber,
    maxPrice: elements['max-price'].value === '' ? undefined : elements['max-price'].valueAsNumber,
  };
}

function priceRangeChanged() {
  const range = priceRange();
  return range.minPrice !== state.priceRange.minPrice || range.maxPrice !== state.priceRange.maxPrice;
}

function validatePrices() {
  const { minPrice, maxPrice } = priceRange();
  elements['max-price'].setCustomValidity(minPrice !== undefined && maxPrice !== undefined && minPrice > maxPrice
    ? 'Maximum price must be at least the minimum price.' : '');
}

function renderAccount() {
  const container = elements.account;
  container.replaceChildren();
  if (state.checking) { container.append(node('span', 'Checking your connection…')); return; }
  if (state.account) {
    container.append(node('span', state.account.username));
    const button = node('button', 'Sign out');
    button.type = 'button';
    button.disabled = busy();
    button.onclick = async () => {
      if (busy()) return;
      state.saving = true;
      render();
      try { await logout(); status('Signed out. Connect with Discogs to search.'); }
      catch (error) { elements['account-error'].textContent = error.message; }
      finally { state.saving = false; render(); }
    };
    container.append(button);
  } else {
    container.append(link('Connect with Discogs', discogsLoginUrl));
    const retry = node('button', 'Refresh connection');
    retry.type = 'button';
    retry.onclick = checkAccount;
    container.append(retry);
  }
}

function demandText(record) {
  const want = record.community_want;
  const have = record.community_have;
  if (!Number.isFinite(want) || !Number.isFinite(have) || want < 0 || have < 0) {
    return 'W/H —';
  }
  return `W/H ${want.toFixed(0)}/${have.toFixed(0)}`;
}

function shortCondition(condition) {
  if (!condition) return '';
  const codes = {
    Mint: 'M', 'Near Mint': 'NM', 'Very Good Plus': 'VG+',
    'Very Good': 'VG', 'Good Plus': 'G+', Good: 'G', Fair: 'F', Poor: 'P',
  };
  const name = condition.split(' (')[0];
  return codes[name] ?? condition;
}

function formatPrice(price, currency) {
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency', currency, currencyDisplay: 'narrowSymbol',
    }).format(price);
  } catch {
    return `${price} ${currency}`;
  }
}

function recordRow(record, recommend, demandRanked = false, rank) {
  const row = node('li', undefined, 'record-row');
  if (rank !== undefined) {
    row.className += ' ranked';
    const number = node('span', `${rank}.`, 'record-rank');
    number.setAttribute('aria-label', `Rank ${rank}`);
    row.append(number);
  }
  const canPlay = playableVideos(record).length > 0;
  const cover = node(canPlay ? 'button' : 'div', undefined, 'cover');
  if (canPlay) {
    cover.type = 'button';
    cover.title = `Play ${record.title}`;
    cover.setAttribute('aria-label', `Play preview of ${record.title}`);
    cover.onclick = () => { void previewPlayer.play(record); };
    cover.append(node('span', '▶', 'cover-play'));
  }
  const placeholder = node('span', '','cover-placeholder');
  cover.append(placeholder);
  if (typeof record.thumbnail_url === 'string' && /^https?:\/\//.test(record.thumbnail_url)) {
    const image = node('img');
    image.alt = ''; // The adjacent title identifies this record.
    image.width = 48;
    image.height = 48;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.referrerPolicy = 'no-referrer';
    image.onload = () => { placeholder.hidden = true; };
    image.onerror = () => { image.remove(); placeholder.hidden = false; };
    image.src = record.thumbnail_url;
    cover.append(image);
  }
  const details = node('div', undefined, 'record-content');
  const heading = node('div', undefined, 'heading');
  const title = [record.artists.join(', '), record.title].filter(Boolean).join(' — ');
  const release = link(title, `https://www.discogs.com/release/${Number(record.release_id)}`, true);
  release.className = 'title';
  const price = node('span', formatPrice(record.price, record.currency), 'price');
  price.title = record.currency;
  heading.append(release, price);
  details.append(heading, node('p', [record.labels.join(', '), record.year, record.styles.join(', '),
    shortCondition(record.condition)].filter(Boolean).join(' · '), 'metadata'));
  const links = node('div', undefined, 'links');
  const demand = node('span', demandText(record), 'demand');
  if (Number.isFinite(record.community_want) && Number.isFinite(record.community_have)) {
    demand.title = `${record.community_want} want / ${record.community_have} have`;
    demand.setAttribute('aria-label', `${demand.textContent}; ${demand.title}`);
  }
  links.append(demand);
  const buy = link('🛒 ↗', `https://www.discogs.com/sell/item/${Number(record.listing_id)}`, true);
  buy.title = 'Open this listing to add it to your cart on Discogs';
  buy.setAttribute('aria-label', `Buy ${title} on Discogs (opens a new tab)`);
  links.append(buy);
  if (recommend) {
    const button = node('button', '+ Wantlist');
    button.type = 'button';
    button.disabled = busy() || !state.account;
    button.setAttribute('aria-label', `Add ${title} to wantlist`);
    button.onclick = () => saveRecord(record);
    links.append(node('span', demandRanked
      ? `Demand ${record.demand_score.toFixed(2)}` : `Score ${record.score.toFixed(2)}`));
    links.append(button);
    const explanation = node('details', undefined, 'match-details');
    explanation.hidden = true;
    explanation.open = state.expanded.has(record.release_id);
    explanation.ontoggle = () => {
      if (!explanation.isConnected) return;
      if (explanation.open) state.expanded.add(record.release_id);
      else state.expanded.delete(record.release_id);
    };
    explanation.append(node('summary', 'Why this?'));
    const panel = node('div', undefined, 'match-info');
    panel.append(node('p', `Match score ${record.score.toFixed(2)}`));
    panel.append(node('p', 'Based on the styles, artists, labels, and years in your collection.'));
    const breakdown = node('dl');
    for (const [key, label] of [['musical_match', 'Musical match'], ['artists', 'Artist preference'],
      ['labels', 'Label preference'], ['year', 'Year preference']]) {
      const value = record.score_breakdown?.[key];
      if (Number.isFinite(value)) breakdown.append(node('dt', label), node('dd', value.toFixed(2)));
    }
    panel.append(breakdown);
    explanation.append(panel);
    links.append(explanation);
  }
  details.append(links);
  row.append(cover, details);
  return row;
}

function render() {
  renderAccount();
  elements.search.disabled = !state.account || busy();
  elements.search.textContent = state.active ? 'Finding records…' : 'Find records';
  elements.search.setAttribute('aria-busy', String(!!state.active));
  elements.seller.disabled = busy();
  elements['min-price'].disabled = busy();
  elements['max-price'].disabled = busy();
  elements.cancel.hidden = !state.active && !state.cancelling;
  elements.cancel.disabled = state.cancelling;
  elements.cancel.textContent = state.cancelling ? 'Cancelling…' : 'Cancel search';
  const visible = sortRecommendations(state.records).filter(record => record.score > 0.1);
  const wanted = new Set(state.wants.map(record => record.release_id));
  const demandRecords = state.demands.filter(record => !wanted.has(record.release_id))
    .sort((a, b) => b.demand_score - a.demand_score || a.release_id - b.release_id);
  elements['results-layout'].hidden = !state.account || !state.searched;
  for (const tab of tabs) {
    const selected = tab.name === state.tab;
    elements[tab.panel].hidden = !selected;
    elements[tab.button].setAttribute('aria-selected', String(selected));
    elements[tab.button].tabIndex = selected ? 0 : -1;
  }
  elements['results-count'].textContent = `(${visible.length})`;
  elements['wantlist-count'].textContent = `(${state.wants.length})`;
  elements['demand-count'].textContent = `(${demandRecords.length})`;
  elements.results.replaceChildren(...visible.map((record, index) => recordRow(record, true, false, index + 1)));
  elements.wantlist.replaceChildren(...state.wants.map(record => recordRow(record, false)));
  elements['demand-results'].replaceChildren(...demandRecords.map((record, index) => recordRow(record, true, true, index + 1)));
  elements['wantlist-empty'].hidden = state.wants.length > 0;
  elements['demand-empty'].hidden = demandRecords.length > 0;
  elements.empty.hidden = !!visible.length || !!state.active;
  elements.more.disabled = busy() || !state.hasMore || !state.account || priceRangeChanged();
  elements.more.textContent = priceRangeChanged() ? 'Use Find records to apply new prices'
    : state.hasMore ? 'Search more' : 'No more accessible records';
}

session.onEnd(() => {
  searchStorage.clear();
  elements['recovery-warning'].hidden = true;
  previewPlayer.close();
  state.expanded.clear();
  state.active?.controller.abort();
  Object.assign(state, { account: null, active: null, cancelling: false, saving: false,
    recoveringId: null,
    records: [], wants: [], demands: [], tab: 'recommendations', seller: '', searched: false, hasMore: true });
  elements.notice.textContent = '';
  elements.error.textContent = '';
  status(session.getSnapshot().expired ? 'Your session expired. Connect with Discogs again.' : 'Signed out.');
  render();
});

async function checkAccount() {
  state.checking = true;
  renderAccount();
  try {
    state.account = await getAccount();
    elements['account-error'].textContent = authError ? loginErrors[authError] ?? loginErrors.provider : '';
    status(state.account ? 'Enter a seller to find records.' : 'Connect with Discogs to search.');
    if (!state.account) searchStorage.clear();
    else if (!restoredSearch) {
      restoredSearch = true;
      state.checking = false;
      await restoreSearch();
    }
  } catch (error) { elements['account-error'].textContent = error.message; }
  finally { state.checking = false; render(); }
}

async function restoreSearch() {
  const viewRevision = searchViewRevision;
  const saved = searchStorage.load(state.account.username);
  if (!saved) return;
  Object.assign(state, { seller: saved.seller, priceRange: saved.priceRange,
    hasMore: saved.hasMore, records: saved.records, wants: saved.wants,
    demands: saved.demands, tab: saved.tab, searched: true });
  elements.seller.value = saved.seller;
  elements['min-price'].value = saved.priceRange.minPrice ?? '';
  elements['max-price'].value = saved.priceRange.maxPrice ?? '';
  elements.notice.textContent = saved.notice ?? '';
  elements.error.textContent = saved.error ?? '';
  status(saved.status ?? 'Previous results restored.');
  if (!saved.activeId) return;
  const revision = session.getSnapshot().revision;
  state.cancelling = true;
  state.recoveringId = saved.activeId;
  // Retain the old ID if this page is refreshed again during recovery.
  status('Restoring results and resuming search…');
  render();
  try {
    await cancelSearch(saved.activeId);
    if (leavingPage || searchViewRevision !== viewRevision || session.getSnapshot().revision !== revision) return;
    state.cancelling = false;
    state.recoveringId = null;
    state.hasMore = true;
    await search(true);
  } catch (error) {
    if (leavingPage || searchViewRevision !== viewRevision || session.getSnapshot().revision !== revision) return;
    elements.error.textContent = error.message;
    status('Results restored. Use Search more to try continuing.');
  } finally {
    if (!leavingPage && searchViewRevision === viewRevision && session.getSnapshot().revision === revision) {
      state.cancelling = false;
      state.recoveringId = null;
    }
  }
}

function upsert(records, record) {
  return [...records.filter(item => item.release_id !== record.release_id), record];
}
function handleEvent(event) {
  switch (event.type) {
    case 'start':
      elements.notice.textContent = event.inventory_truncated
        ? `Discogs allows access to the first 100 of ${event.reported_pages} inventory pages. Results cover only those accessible pages.` : '';
      break;
    case 'status': status(event.message ?? ''); break;
    case 'progress': status(`Reading inventory: page ${event.page} of ${event.pages} (${event.listings} listings)`); break;
    case 'pre_rank_complete': status(`Scoring ${event.candidates} recommendations`); break;
    case 'recommendation':
      if (event.recommendation) state.records = upsert(state.records, event.recommendation);
      status(event.inventory_scanning ? `Scored ${event.processed} recommendations — continuing inventory scan`
        : `Scored ${event.processed} of ${event.candidates} recommendations`);
      break;
    case 'wantlist':
      if (event.recommendation) state.wants = upsert(state.wants, event.recommendation);
      break;
    case 'demand_results':
      if (Array.isArray(event.records)) state.demands = event.records;
      break;
    case 'done':
      if (state.active) state.active.done = true;
      state.hasMore = event.has_more ?? false;
      status(state.hasMore ? 'Done — more records available' : event.inventory_truncated
        ? 'Done — all accessible records searched' : 'Done — all available records searched');
      break;
    case 'error':
      if (state.active) state.active.done = true;
      elements.error.textContent = event.message ?? 'Search failed.';
      break;
  }
  render();
  persistSearch();
}

async function search(more = false) {
  if (!state.account || busy()) return;
  if (more && priceRangeChanged()) return;
  if (!more) {
    validatePrices();
    if (!elements['search-form'].reportValidity()) return;
  }
  const seller = more ? state.seller : elements.seller.value.trim();
  if (!seller || (more && !state.hasMore)) return;
  if (!more) {
    state.priceRange = priceRange();
    state.expanded.clear();
    Object.assign(state, { seller, records: [], wants: [], demands: [], tab: 'recommendations', searched: true, hasMore: true });
    elements.notice.textContent = '';
  }
  elements.error.textContent = '';
  const request = { id: crypto.randomUUID(), controller: new AbortController() };
  state.active = request;
  status(more ? 'Searching for more records…' : 'Starting…');
  render();
  persistSearch();
  try {
    await getRecommendations(seller, {
      searchId: request.id, signal: request.controller.signal,
      includeDemand: true,
      ...state.priceRange,
      excludeReleaseIds: [...state.records, ...state.wants].map(record => record.release_id),
      onEvent: event => { if (!leavingPage && state.active === request && !state.cancelling) handleEvent(event); },
    });
  } catch (error) {
    if (!leavingPage && !request.controller.signal.aborted && state.active === request) {
      elements.error.textContent = error.message;
      status('Stopped before completion. Search more to continue.');
    }
  } finally {
    if (!leavingPage) {
      if (state.active === request && !state.cancelling) state.active = null;
      render();
      persistSearch();
    }
  }
}

function selectTab(index, focus = false) {
  const tab = tabs[(index + tabs.length) % tabs.length];
  state.tab = tab.name;
  render();
  persistSearch();
  if (focus) elements[tab.button].focus();
}
tabs.forEach((tab, index) => {
  elements[tab.button].onclick = () => selectTab(index);
  elements[tab.button].onkeydown = event => {
    let next;
    if (event.key === 'ArrowRight') next = index + 1;
    if (event.key === 'ArrowLeft') next = index - 1;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) { event.preventDefault(); selectTab(next, true); }
  };
});

for (const id of ['min-price', 'max-price']) {
  elements[id].oninput = () => { validatePrices(); render(); };
}
elements['search-form'].onsubmit = event => { event.preventDefault(); void search(); };
elements.home.onclick = async event => {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  if (returningHome) return;
  returningHome = true;
  searchViewRevision++;
  restoredSearch = true;
  const revision = session.getSnapshot().revision;
  const searchId = state.active?.id ?? state.recoveringId;
  state.active?.controller.abort();
  previewPlayer.close();
  searchStorage.clear();
  state.expanded.clear();
  Object.assign(state, { active: null, recoveringId: null, cancelling: !!searchId,
    saving: false, seller: '', searched: false, hasMore: true, records: [],
    wants: [], demands: [], tab: 'recommendations', priceRange: {} });
  for (const id of ['seller', 'min-price', 'max-price']) elements[id].value = '';
  validatePrices();
  elements.notice.textContent = '';
  elements.error.textContent = '';
  elements['recovery-warning'].hidden = true;
  status(searchId ? 'Stopping search…' : state.account
    ? 'Enter a seller to find records.' : 'Connect with Discogs to search.');
  render();
  try {
    if (searchId) await cancelSearch(searchId);
    if (session.getSnapshot().revision === revision) {
      status(state.account ? 'Enter a seller to find records.' : 'Connect with Discogs to search.');
    }
  } catch (error) {
    if (session.getSnapshot().revision === revision) elements.error.textContent = error.message;
  } finally {
    returningHome = false;
    if (session.getSnapshot().revision === revision) state.cancelling = false;
    render();
  }
};
elements.more.onclick = () => search(true);
elements.cancel.onclick = async () => {
  const request = state.active;
  if (!request || state.cancelling) return;
  state.cancelling = true;
  request.controller.abort();
  status('Cancelling search…');
  render();
  persistSearch();
  try {
    await cancelSearch(request.id);
    if (state.active === request) status('Search cancelled. Search more to continue.');
  } catch (error) {
    if (state.active === request) { elements.error.textContent = error.message; status('Could not confirm cancellation. Wait a moment before searching again.'); }
  } finally {
    if (state.active === request) { state.cancelling = false; state.active = null; }
    render();
    persistSearch();
  }
};

async function saveRecord(record) {
  if (!state.account || busy()) return;
  state.saving = true;
  elements.error.textContent = '';
  const revision = session.getSnapshot().revision;
  const viewRevision = searchViewRevision;
  render();
  try {
    await addToWantlist(record.release_id);
    if (searchViewRevision !== viewRevision || session.getSnapshot().revision !== revision) return;
    state.wants = upsert(state.wants, record);
    state.records = state.records.filter(item => item.release_id !== record.release_id);
    status('Added to your wantlist.');
  } catch (error) {
    if (searchViewRevision === viewRevision && session.getSnapshot().revision === revision) elements.error.textContent = error.message;
  } finally {
    if (searchViewRevision === viewRevision) { state.saving = false; render(); persistSearch(); }
  }
}

void checkAccount();
