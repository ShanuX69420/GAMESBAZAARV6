// Dependent filters: a filter with `visible_when` only appears after its
// parent filter holds the triggering option (e.g., show "Region — Keys"
// only when Method = Digital Key).

export function isFilterVisible(filter, values) {
  const condition = filter.visible_when;
  if (!condition) return true;
  return values[condition.filter_id] === condition.option_value;
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
