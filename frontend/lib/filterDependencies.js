// Dependent filters: a filter with `visible_when` only appears after another
// filter holds one of the triggering options (e.g., show "Region — Gift" when
// Method = As a Gift OR By logging into account).

export function isFilterVisible(filter, values) {
  const condition = filter.visible_when;
  if (!condition) return true;
  // Tolerate the legacy single-object shape from briefly cached API responses.
  const conditions = Array.isArray(condition) ? condition : [condition];
  if (conditions.length === 0) return true;
  return conditions.some((c) => c && values[c.filter_id] === c.option_value);
}

// Returns `values` with selections removed for filters that are no longer
// visible. Clearing a parent can hide its child, which may in turn hide a
// grandchild — repeat until nothing more is removed.
export function pruneHiddenFilterValues(filters, values) {
  let next = values;
  let changed = true;
  while (changed) {
    changed = false;
    for (const filter of filters) {
      if (next[filter.id] !== undefined && !isFilterVisible(filter, next)) {
        next = { ...next, [filter.id]: undefined };
        changed = true;
      }
    }
  }
  return next;
}
