export function isEmailGroupKey(key: string): boolean {
  return /^(STOCK|EMAIL)_GROUP_\d+$/.test(key);
}
