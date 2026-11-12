import { browserStorage } from './browserStorage';
/**
 * Customer Authentication & Coins State Manager
 * Handles persistent session, dummy rewards coins, and cross-component sync.
 */
import api from '../api/client';

const TOKEN_KEY = 'dimsum_customer_token';
const USER_KEY = 'dimsum_customer_user';
const COINS_KEY = 'dimsum_customer_coins';
const AUTH_EVENT = 'dimsum_customer_auth_changed';

export function getCustomerToken() {
  try {
    return browserStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function getCustomerUser() {
  try {
    const raw = browserStorage.getItem(USER_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function isCustomerLoggedIn() {
  const token = getCustomerToken();
  const user = getCustomerUser();
  return Boolean(token && user);
}

export function getCustomerCoins() {
  if (!isCustomerLoggedIn()) {
    return 0;
  }
  try {
    const saved = browserStorage.getItem(COINS_KEY);
    if (saved !== null) {
      const parsed = parseInt(saved, 10);
      return isNaN(parsed) ? 1500 : parsed;
    }
    // Default initial reward upon login: 1.500 Coins
    browserStorage.setItem(COINS_KEY, '1500');
    return 1500;
  } catch {
    return 1500;
  }
}

export function setCustomerCoins(coins) {
  try {
    browserStorage.setItem(COINS_KEY, String(coins));
    window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: { coins } }));
  } catch (e) {
    console.error('Error setting coins:', e);
  }
}

export function loginCustomer(token, user, initialCoins = 1500) {
  try {
    if (token) {
      browserStorage.setItem(TOKEN_KEY, token);
    }
    if (user) {
      browserStorage.setItem(USER_KEY, JSON.stringify(user));
      if (user.full_name) {
        browserStorage.setItem('dimsum_customer_name', user.full_name);
      }
      if (user.email) {
        if (user.email.includes('@')) {
          browserStorage.setItem('dimsum_customer_email', user.email);
        } else {
          browserStorage.setItem('dimsum_customer_phone', user.email);
        }
      }
    }
    const currentCoins = browserStorage.getItem(COINS_KEY);
    if (!currentCoins) {
      browserStorage.setItem(COINS_KEY, String(initialCoins));
    }

    window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: { loggedIn: true, user } }));
  } catch (err) {
    console.error('Failed to save customer login session:', err);
  }
}

export function updateCustomerUser(updatedUser) {
  try {
    if (!updatedUser) return;
    browserStorage.setItem(USER_KEY, JSON.stringify(updatedUser));
    if (updatedUser.full_name) {
      browserStorage.setItem('dimsum_customer_name', updatedUser.full_name);
    }
    if (updatedUser.email && updatedUser.email.includes('@')) {
      browserStorage.setItem('dimsum_customer_email', updatedUser.email);
    }
    if (updatedUser.phone) {
      browserStorage.setItem('dimsum_customer_phone', updatedUser.phone);
    } else if (updatedUser.email && !updatedUser.email.includes('@')) {
      browserStorage.setItem('dimsum_customer_phone', updatedUser.email);
    }
    window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: { loggedIn: true, user: updatedUser } }));
  } catch (err) {
    console.error('Failed to update customer user session:', err);
  }
}

export function logoutCustomer() {
  try {
    const token = getCustomerToken();
    if (token) {
      // Call backend logout asynchronously using centralized api client
      api.post('/api/auth/logout').catch(() => {});
    }

    browserStorage.removeItem(TOKEN_KEY);
    browserStorage.removeItem(USER_KEY);
    window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: { loggedIn: false } }));
  } catch (err) {
    console.error('Failed to logout customer:', err);
  }
}

export function subscribeCustomerAuth(callback) {
  const handler = (e) => callback(e.detail);
  window.addEventListener(AUTH_EVENT, handler);
  return () => window.removeEventListener(AUTH_EVENT, handler);
}
