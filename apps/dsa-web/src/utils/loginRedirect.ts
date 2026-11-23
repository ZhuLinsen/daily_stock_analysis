/** Resolve the shared post-login destination without allowing external URLs or login loops. */
export function resolveLoginRedirect(rawRedirect: string | null): string {
  if (!rawRedirect?.startsWith('/') || rawRedirect.startsWith('//') || rawRedirect.includes('\\')) {
    return '/';
  }

  try {
    const target = new URL(rawRedirect, window.location.origin);
    const pathname = decodeURIComponent(target.pathname);
    if (
      target.origin !== window.location.origin
      || pathname.startsWith('//')
      || pathname.includes('\\')
      || /^\/login\/?$/i.test(pathname)
    ) {
      return '/';
    }
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return '/';
  }
}
