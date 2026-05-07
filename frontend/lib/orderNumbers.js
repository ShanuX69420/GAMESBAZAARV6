export function orderNumber(order) {
  return order?.order_number || order?.id;
}

export function orderLabel(order) {
  return `#${orderNumber(order)}`;
}

export function orderPath(order) {
  return `/order/${encodeURIComponent(orderNumber(order))}`;
}

export function notificationOrderPath(notification) {
  const ref = notification?.order_number || notification?.order_id;
  return ref ? `/order/${encodeURIComponent(ref)}` : null;
}
