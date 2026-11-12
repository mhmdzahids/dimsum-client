import { describe, it, expect } from 'vitest';
import { isValidOptionalEmail } from '../emailValidation';
describe('optional checkout email', () => {
  it.each(['nama', 'nama@domain', 'nama.domain.com', 'nama@@domain.com', 'nama@.com', 'nama@domain.', 'nama@-domain.com', 'nama..lain@domain.com', 'nama @domain.com'])('rejects %s', (email) => {
    expect(isValidOptionalEmail(email)).toBe(false);
  });
  it.each(['', '  ', 'nama@domain.com', 'nama.lain+tag@sub.domain.co.id', ' nama@domain.com '])('accepts %s', (email) => {
    expect(isValidOptionalEmail(email)).toBe(true);
  });
});
