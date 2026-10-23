// Preserve covers and focused controls across streaming progress updates.
export function createRecordList(createRow) {
  const lists = new WeakMap();
  return (container, records, kind, { loading, disabled, page = 1, pageSize = 30 }) => {
    const saved = lists.get(container);
    const previous = saved?.rows ?? new Map();
    const previousIds = new Set(saved?.ids ?? []);
    const incoming = new Map(records.map(record => [record.release_id, record]));
    const ids = loading
      ? (saved?.ids ?? []).filter(id => incoming.has(id))
        .concat([...incoming.keys()].filter(id => !previousIds.has(id)))
      : [...incoming.keys()];
    const pages = Math.max(1, Math.ceil(ids.length / pageSize));
    page = Math.max(1, Math.min(page, pages));
    const offset = (page - 1) * pageSize;
    const visibleIds = ids.slice(offset, offset + pageSize);
    const next = new Map();
    visibleIds.forEach((id, index) => {
      const record = incoming.get(id);
      const signature = JSON.stringify(record);
      const rank = kind === 'wantlist' ? undefined : offset + index + 1;
      const cached = previous.get(id);
      const row = cached?.signature === signature ? cached.row : createRow(record, kind, rank);
      if (row.rankLabel) {
        row.rankLabel.textContent = `${rank}.`;
        row.rankLabel.setAttribute('aria-label', `Rank ${rank}`);
      }
      if (row.wantlistButton) row.wantlistButton.disabled = disabled;
      next.set(id, { row, signature });
      if (container.children[index] !== row) container.insertBefore(row, container.children[index] ?? null);
    });
    while (container.children.length > visibleIds.length) container.lastElementChild.remove();
    container.start = offset + 1;
    lists.set(container, { rows: next, ids });
    return { page, pages };
  };
}
