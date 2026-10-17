const KEY = 'dside.search.v1';
const MAX_AGE = 24 * 60 * 60 * 1000;

// Only search display state is stored here, never login credentials.
export function createSearchStorage(storage, now = Date.now) {
  function clear() {
    try { storage.removeItem(KEY); } catch { /* Storage can be disabled. */ }
  }
  return {
    clear,
    save(username, search) {
      try {
        storage.setItem(KEY, JSON.stringify({ username, savedAt: now(), search }));
        return true;
      } catch {
        // Do not restore an older search if the current one exceeds the quota.
        clear();
        return false;
      }
    },
    load(username) {
      try {
        const saved = JSON.parse(storage.getItem(KEY));
        if (!saved) return null;
        const search = saved.search;
        const validRecord = record => record && Number.isSafeInteger(record.release_id)
          && Number.isSafeInteger(record.listing_id) && typeof record.title === 'string'
          && ['artists', 'labels', 'styles'].every(key => Array.isArray(record[key]))
          && Number.isFinite(record.score) && record.score_breakdown;
        if (saved.username !== username || !Number.isFinite(saved.savedAt)
            || now() - saved.savedAt > MAX_AGE || saved.savedAt > now()
            || !search || typeof search.seller !== 'string'
            || !['records', 'wants', 'demands'].every(key => Array.isArray(search[key])
              && search[key].every(validRecord))
            || !search.priceRange || typeof search.hasMore !== 'boolean'
            || !['recommendations', 'wantlist', 'demand'].includes(search.tab)
            || (search.activeId !== null && !/^[0-9a-f-]{36}$/i.test(search.activeId))) {
          clear();
          return null;
        }
        return search;
      } catch {
        clear();
        return null;
      }
    },
  };
}
