import { notificationOrderPath } from './orderNumbers';

export const WALLET_NOTIFICATION_TYPES = new Set([
  'topup_approved',
  'topup_rejected',
  'withdraw_approved',
  'withdraw_rejected',
]);

export function notificationDestinationPath(notification) {
  if (WALLET_NOTIFICATION_TYPES.has(notification?.notification_type)) {
    return '/wallet';
  }

  if (notification?.notification_type === 'admin_message') {
    return '/inbox';
  }

  if (notification?.notification_type === 'seller_approved') {
    return '/dashboard';
  }

  if (notification?.notification_type === 'seller_rejected') {
    return '/seller/apply';
  }

  return notificationOrderPath(notification);
}
