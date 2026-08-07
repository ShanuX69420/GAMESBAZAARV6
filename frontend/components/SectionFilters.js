'use client';

import { useRouter } from 'next/navigation';
import Select from '@/components/Select';

// Method + Region + Sort dropdowns on a View All section page (/keys).
// Picking a value reloads the page with ?method= / ?region= / ?sort= so the
// server component refetches the section narrowed and ordered to match.
export default function SectionFilters({
  basePath, methods, regions, sorts = [], method, region, sort = '',
}) {
  const router = useRouter();

  const navigate = (nextMethod, nextRegion, nextSort) => {
    const params = new URLSearchParams();
    if (nextMethod) params.set('method', nextMethod);
    if (nextRegion) params.set('region', nextRegion);
    if (nextSort) params.set('sort', nextSort);
    const query = params.toString();
    router.push(query ? `${basePath}?${query}` : basePath, { scroll: false });
  };

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
              onChange={(next) => navigate(next, region, sort)}
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
              onChange={(next) => navigate(method, next, sort)}
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
              onChange={(next) => navigate(method, region, next)}
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
          onClick={() => router.push(basePath, { scroll: false })}
        >
          Reset filters
        </button>
      )}
    </div>
  );
}
