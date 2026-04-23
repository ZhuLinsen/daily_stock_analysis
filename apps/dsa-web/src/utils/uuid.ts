/**
 * Generate a UUID v4. Uses crypto.randomUUID when available (secure context: HTTPS/localhost),
 * otherwise falls back to a Math.random-based implementation for non-secure HTTP contexts.
 * See: https://developer.mozilla.org/en-US/docs/Web/API/Crypto/randomUUID
 */
export function generateUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
