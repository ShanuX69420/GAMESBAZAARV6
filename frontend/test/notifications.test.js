import { describe, expect, it } from 'vitest';
import {
  WALLET_NOTIFICATION_TYPES,
  notificationDestinationPath,
} from '../lib/notifications';

describe('notification routing helpers', () => {
  it('routes wallet status notifications to the wallet page', () => {
    for (const notificationType of WALLET_NOTIFICATION_TYPES) {
      expect(notificationDestinationPath({ notification_type: notificationType }))
        .toBe('/wallet');
    }
  });

  it('routes admin messages to the inbox', () => {
    expect(notificationDestinationPath({ notification_type: 'admin_message' }))
      .toBe('/inbox');
  });

  it('falls back to order destinations for order notifications', () => {
    expect(notificationDestinationPath({
      notification_type: 'new_order',
      order_number: 'GB-ABCD+EFGH/IJKL',
      order_id: 42,
    })).toBe('/order/GB-ABCD%2BEFGH%2FIJKL');
  });

  it('returns null when a notification has no destination', () => {
    expect(notificationDestinationPath({ notification_type: 'new_review' })).toBeNull();
    expect(notificationDestinationPath(null)).toBeNull();
  });
});
