'use client';

import Select from '@/components/Select';

// Method + Region + Sort dropdowns on a View All section page (/keys).
// Picking a value hands the whole selection back to SectionGameList, which
// refetches the section in place and rewrites the URL — the page itself is a
// cached copy that never varies by query, so there is nothing to navigate to.
export default function SectionFilters({
  methods, regions, sorts = [], method, region, sort = '', onChange,
}) {
  const select = (next) => onChange({ method, region, sort, ...next });

  return (
    <div className="section-filter-bar">
      {methods.length > 0 && (
        <div className="section-filter-group">
          <label className="section-filter-label" htmlFor="section-method-filter">
            Method
          </label>
          <div className="section-filter-select">
            <Select
              id="section-method-filter"
              value={method || ''}
              onChange={(next) => select({ method: next })}
              options={[
                { value: '', label: 'All Methods' },
                ...methods.map((choice) => ({ value: choice.value, label: choice.label })),
              ]}
              ariaLabel="Filter games by delivery method"
            />
          </div>
        </div>
      )}
      {regions.length > 0 && (
        <div className="section-filter-group">
          <label className="section-filter-label" htmlFor="section-region-filter">
            Region
          </label>
          <div className="section-filter-select">
            <Select
              id="section-region-filter"
              value={region || ''}
              onChange={(next) => select({ region: next })}
              options={[
                { value: '', label: 'All Regions' },
                ...regions.map((choice) => ({ value: choice.value, label: choice.label })),
              ]}
              ariaLabel="Filter games by region"
            />
          </div>
        </div>
      )}
      {sorts.length > 0 && (
        <div className="section-filter-group">
          <label className="section-filter-label" htmlFor="section-sort-filter">
            Sort by
          </label>
          <div className="section-filter-select">
            <Select
              id="section-sort-filter"
              value={sort || ''}
              onChange={(next) => select({ sort: next })}
              options={sorts.map((choice) => ({
                value: choice.value, label: choice.label,
              }))}
              ariaLabel="Sort games"
            />
          </div>
        </div>
      )}
      {(method || region || sort) && (
        <button
          type="button"
          className="btn btn-sm btn-outline"
          onClick={() => onChange({ method: '', region: '', sort: '' })}
        >
          Reset filters
        </button>
      )}
    </div>
  );
}
