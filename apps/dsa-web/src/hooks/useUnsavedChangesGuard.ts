import { useEffect } from 'react';

/**
 * Prompts the user before the tab is refreshed or closed while there are
 * unsaved changes. Browsers do not allow custom prompt text for security
 * reasons, so this only triggers the native "leave site?" confirmation.
 *
 * In-app (SPA) route navigation is intentionally not guarded here: the app
 * uses a classic <BrowserRouter>, where react-router's useBlocker is not
 * available.
 */
export function useUnsavedChangesGuard(isDirty: boolean): void {
  useEffect(() => {
    if (!isDirty) {
      return;
    }

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [isDirty]);
}
