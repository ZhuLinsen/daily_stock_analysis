const ROUTE_CHUNK_RECOVERY_KEY = 'dsa.routeChunkRecovery';

type RecoveryStorage = Pick<Storage, 'getItem' | 'setItem'>;

type RouteChunkRecoveryDependencies = {
  storage?: RecoveryStorage;
  reload?: () => void;
};

function getChunkFailureSignature(error: unknown): string | null {
  const name = error instanceof Error ? error.name : '';
  const message = error instanceof Error ? error.message : String(error ?? '');
  const text = `${name}: ${message}`;
  const isChunkFailure = /failed to fetch dynamically imported module/i.test(text)
    || /loading (?:css )?chunk [^ ]+ failed/i.test(text)
    || /chunkloaderror/i.test(text);
  if (!isChunkFailure) return null;

  const assetUrl = message.match(/https?:\/\/\S+\/assets\/\S+/i)?.[0];
  return assetUrl ?? text;
}

export function attemptRouteChunkRecovery(
  error: unknown,
  dependencies: RouteChunkRecoveryDependencies = {},
): boolean {
  const signature = getChunkFailureSignature(error);
  if (!signature) return false;

  try {
    const storage = dependencies.storage ?? window.sessionStorage;
    if (storage.getItem(ROUTE_CHUNK_RECOVERY_KEY) === signature) return false;
    storage.setItem(ROUTE_CHUNK_RECOVERY_KEY, signature);
    (dependencies.reload ?? (() => window.location.reload()))();
    return true;
  } catch {
    return false;
  }
}
