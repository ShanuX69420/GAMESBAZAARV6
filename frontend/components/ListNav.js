'use client';

import { useListClickNavigation } from '@/lib/listNavigation';

// A grid of plain <a> rows that still navigates client-side: one delegated
// click handler instead of a next/link per row (see lib/listNavigation.js).
// Used where the rows are rendered by a server component (/games, the home
// fallback grid); SectionGameList applies the same hook directly.
export default function ListNav({ as: Tag = 'div', children, ...rest }) {
  const onClick = useListClickNavigation();
  return (
    <Tag {...rest} onClick={onClick}>
      {children}
    </Tag>
  );
}
