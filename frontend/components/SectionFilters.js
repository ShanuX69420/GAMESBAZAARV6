'use client';

import { useRouter } from 'next/navigation';
import Select from '@/components/Select';

// Method + Region dropdowns on a View All section page (/keys). Picking a
// value reloads the page with ?method= / ?region= so the server component
// refetches the section narrowed to that selection.
export default function SectionFilters({ basePath, methods, regions, method, region }) {
  const router = useRouter();

  const navigate = (nextMethod, nextRegion) => {
    const params = new URLSearchParams();
    if (nextMethod) params.set('method', nextMethod);
    if (nextRegion) params.set('region', nextRegion);
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
              onChange={(next) => navigate(next, region)}
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
              onChange={(next) => navigate(method, next)}
              options={[
                { value: '', label: 'All Regions' },
                ...regions.map((choice) => ({ value: choice.value, label: choice.label })),
              ]}
              ariaLabel="Filter games by region"
            />
          </div>
        </div>
      )}
      {(method || region) && (
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
