// These modules contain no React runtime code. Both frontends share the API contract.
import { getAccount, logout, discogsLoginUrl } from '../../frontend/src/api/auth.ts';
import { getRecommendations, cancelSearch, addToWantlist, sortRecommendations } from '../../frontend/src/api/recommendations.ts';
import { session } from '../../frontend/src/session.ts';

const elements = Object.fromEntries([...document.querySelectorAll('[id]')].map(node => [node.id, node]));
const state = { account: null, checking: true, active: null, cancelling: false, saving: false,
  seller: '', searched: false, hasMore: true, records: [], wants: [], expanded: new Set() };
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
  const ratio = have > 0 ? (want / have).toFixed(1) : want > 0 ? '∞' : 'N/A';
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

function recordRow(record, recommend) {
  const row = node('li', undefined, 'record-row');
  const cover = node('div', undefined, 'cover');
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
  const title = `${record.artists.join(', ')} — ${record.title}`;
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
  links.append(link('Listing ↗', `https://www.discogs.com/sell/item/${Number(record.listing_id)}`, true));
  if (recommend) {
    const button = node('button', '+ Wantlist');
    button.type = 'button';
    button.disabled = busy() || !state.account;
    button.setAttribute('aria-label', `Add ${title} to wantlist`);
    button.onclick = () => saveRecord(record);
    links.append(node('span', `Score ${record.score.toFixed(2)}`));
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
  elements.cancel.hidden = !state.active && !state.cancelling;
  elements.cancel.disabled = state.cancelling;
  elements.cancel.textContent = state.cancelling ? 'Cancelling…' : 'Cancel search';
  const visible = sortRecommendations(state.records).filter(record => record.score > 0.1);
  elements['results-section'].hidden = !state.account || !state.searched;
  elements['wantlist-section'].hidden = !state.account || !state.wants.length;
  elements['results-count'].textContent = `(${visible.length})`;
  elements['wantlist-count'].textContent = `(${state.wants.length})`;
  elements.results.replaceChildren(...visible.map(record => recordRow(record, true)));
  elements.wantlist.replaceChildren(...state.wants.map(record => recordRow(record, false)));
  elements.empty.hidden = !!visible.length || !!state.active;
  elements.more.disabled = busy() || !state.hasMore || !state.account;
  elements.more.textContent = state.hasMore ? 'Search more' : 'No more accessible records';
}

session.onEnd(() => {
  state.expanded.clear();
  state.active?.controller.abort();
  Object.assign(state, { account: null, active: null, cancelling: false, saving: false,
    records: [], wants: [], seller: '', searched: false, hasMore: true });
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
    status(state.account ? 'Enter a seller to find records.' : 'Connect with Discogs to search. After login, open this tab and refresh your connection.');
  } catch (error) { elements['account-error'].textContent = error.message; }
  finally { state.checking = false; render(); }
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
    case 'done':
      state.hasMore = event.has_more ?? false;
      status(state.hasMore ? 'Done — more records available' : event.inventory_truncated
        ? 'Done — all accessible records searched' : 'Done — all available records searched');
      break;
    case 'error': elements.error.textContent = event.message ?? 'Search failed.'; break;
  }
  render();
}

async function search(more = false) {
  if (!state.account || busy()) return;
  const seller = more ? state.seller : elements.seller.value.trim();
  if (!seller || (more && !state.hasMore)) return;
  if (!more) {
    state.expanded.clear();
    Object.assign(state, { seller, records: [], wants: [], searched: true, hasMore: true });
    elements.notice.textContent = '';
  }
  elements.error.textContent = '';
  const request = { id: crypto.randomUUID(), controller: new AbortController() };
  state.active = request;
  status(more ? 'Searching for more records…' : 'Starting…');
  render();
  try {
    await getRecommendations(seller, {
      searchId: request.id, signal: request.controller.signal,
      excludeReleaseIds: [...state.records, ...state.wants].map(record => record.release_id),
      onEvent: event => { if (state.active === request && !state.cancelling) handleEvent(event); },
    });
  } catch (error) {
    if (!request.controller.signal.aborted && state.active === request) {
      elements.error.textContent = error.message;
      status('Stopped before completion. Search more to continue.');
    }
  } finally {
    if (state.active === request && !state.cancelling) state.active = null;
    render();
  }
}

elements['search-form'].onsubmit = event => { event.preventDefault(); void search(); };
elements.more.onclick = () => search(true);
elements.cancel.onclick = async () => {
  const request = state.active;
  if (!request || state.cancelling) return;
  state.cancelling = true;
  request.controller.abort();
  status('Cancelling search…');
  render();
  try {
    await cancelSearch(request.id);
    if (state.active === request) status('Search cancelled. Search more to continue.');
  } catch (error) {
    if (state.active === request) { elements.error.textContent = error.message; status('Could not confirm cancellation. Wait a moment before searching again.'); }
  } finally {
    if (state.active === request) { state.cancelling = false; state.active = null; }
    render();
  }
};

async function saveRecord(record) {
  if (!state.account || busy()) return;
  state.saving = true;
  elements.error.textContent = '';
  const revision = session.getSnapshot().revision;
  render();
  try {
    await addToWantlist(record.release_id);
    if (session.getSnapshot().revision !== revision) return;
    state.wants = upsert(state.wants, record);
    state.records = state.records.filter(item => item.release_id !== record.release_id);
    status('Added to your wantlist.');
  } catch (error) {
    if (session.getSnapshot().revision === revision) elements.error.textContent = error.message;
  } finally { state.saving = false; render(); }
}

void checkAccount();
