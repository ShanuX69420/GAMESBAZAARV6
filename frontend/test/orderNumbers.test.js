import { describe, expect, it } from 'vitest';
import {
  notificationOrderPath,
  orderLabel,
  orderNumber,
  orderPath,
} from '../lib/orderNumbers';

describe('order number helpers', () => {
  it('prefers public order numbers over database ids', () => {
    const order = { id: 42, order_number: 'GB-ABCD-EFGH-IJKL' };

    expect(orderNumber(order)).toBe('GB-ABCD-EFGH-IJKL');
    expect(orderLabel(order)).toBe('#GB-ABCD-EFGH-IJKL');
    expect(orderPath(order)).toBe('/order/GB-ABCD-EFGH-IJKL');
  });

  it('falls back to ids for legacy order payloads', () => {
    const order = { id: 42 };

    expect(orderNumber(order)).toBe(42);
    expect(orderLabel(order)).toBe('#42');
    expect(orderPath(order)).toBe('/order/42');
  });

  it('builds encoded notification order paths and handles missing refs', () => {
    expect(notificationOrderPath({ order_number: 'GB-ABCD+EFGH/IJKL', order_id: 42 }))
      .toBe('/order/GB-ABCD%2BEFGH%2FIJKL');
    expect(notificationOrderPath({ order_id: 42 })).toBe('/order/42');
    expect(notificationOrderPath({})).toBeNull();
  });
});
