// Email is optional; an entered address must include a dotted domain.
const EMAIL_PATTERN = /^[A-Za-z0-9_+\-]+(?:[.][A-Za-z0-9_+\-]+)*@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(?:[.][A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+$/;
export function isValidOptionalEmail(value) {
  const email = value.trim();
  return !email || (email.length <= 255 && email.split('@')[0].length <= 64 && EMAIL_PATTERN.test(email));
}
