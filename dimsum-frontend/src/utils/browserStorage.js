// Keep credentials and personal/order data within the current tab session.
// This limits persistence; sessionStorage is still readable by same-origin JS.
const privateKeys = new Set([
  'adminToken', 'adminUser', 'admin-auth-store', 'customer-auth-store',
  'dimsum_customer_token', 'dimsum_customer_user', 'dimsum_customer_name',
  'dimsum_customer_email', 'dimsum_customer_phone', 'dimsum_customer_coins',
  'dimsum_current_order_token', 'dimsum_pending_order', 'dimsum_order_history',
  'dimsum_delivery_address', 'dimsum_delivery_notes', 'dimsum_delivery_coords',
  'dimsum_order_notes', 'dimsum_pos_customer_name', 'dimsum_pos_customer_phone', 'dimsum_pos_order_notes',
]);
function storage(key) {
  if (privateKeys.has(key)) {
    // Discard insecure legacy copies, never silently revive old sessions.
    globalThis.localStorage.removeItem(key);
    return globalThis.sessionStorage;
  }
  return globalThis.localStorage;
}
export const browserStorage = {
  getItem: (key) => storage(key).getItem(key),
  setItem: (key, value) => storage(key).setItem(key, value),
  removeItem: (key) => {
    storage(key).removeItem(key);
    if (key === 'adminToken') {
      storage('admin-auth-store').removeItem('admin-auth-store');
      storage('adminUser').removeItem('adminUser');
    }
    if (key === 'dimsum_customer_token') {
      for (const item of privateKeys) {
        if (!item.startsWith('admin')) storage(item).removeItem(item);
      }
    }
  },
  clear: () => { globalThis.localStorage.clear(); globalThis.sessionStorage.clear(); },
};
export function clearPrivateSession() {
  for (const key of privateKeys) browserStorage.removeItem(key);
}
export function discardLegacyPrivateStorage() {
  for (const key of privateKeys) globalThis.localStorage.removeItem(key);
}
