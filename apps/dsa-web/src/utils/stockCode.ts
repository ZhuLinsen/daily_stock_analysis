/**
 * Normalize stock code by stripping exchange prefixes/suffixes.
 *
 * Mirrors the behavior of data_provider.base.normalize_stock_code in the backend.
 *
 *   600519      → 600519     SH600519    → 600519
 *   600519.SH   → 600519     SH.600519   → 600519
 *   SZ000001    → 000001     000001.SZ   → 000001
 *   BJ920748    → 920748     920748.BJ   → 920748
 *   HK00700     → HK00700    00700       → HK00700
 *   00700.HK    → HK00700
 *   hk1810      → HK01810    1810.HK     → HK01810
 *   7203.T      → 7203.T     005930.KS   → 005930.KS
 *   AAPL        → AAPL       TSLA        → TSLA
 */
export function normalizeStockCode(stockCode: string): string {
  const code = stockCode.trim();
  const upper = code.toUpperCase();

  // Normalize HK prefix to a canonical 5-digit form (e.g. hk1810 → HK01810)
  if (upper.startsWith('HK') && !upper.startsWith('HK.')) {
    const candidate = upper.slice(2);
    if (/^\d{1,5}$/.test(candidate) && candidate.length >= 1 && candidate.length <= 5) {
      return `HK${candidate.padStart(5, '0')}`;
    }
  }

  // Pure 5-digit codes are HK stocks by validateStockCode() contract.
  if (/^\d{5}$/.test(upper)) {
    return `HK${upper}`;
  }

  // Strip SH/SZ prefix (e.g. SH600519 → 600519)
  if ((upper.startsWith('SH') || upper.startsWith('SZ')) && !upper.startsWith('SH.') && !upper.startsWith('SZ.')) {
    const candidate = code.slice(2);
    if (/^\d{5,6}$/.test(candidate)) {
      return candidate;
    }
  }

  // Strip dotted SH/SZ prefix (e.g. SH.600519 → 600519)
  if (upper.startsWith('SH.') || upper.startsWith('SZ.')) {
    const candidate = code.slice(3);
    if (/^\d{5,6}$/.test(candidate)) {
      return candidate;
    }
  }

  // Strip BJ prefix (e.g. BJ920748 → 920748)
  if (upper.startsWith('BJ') && !upper.startsWith('BJ.')) {
    const candidate = code.slice(2);
    if (/^\d{6}$/.test(candidate)) {
      return candidate;
    }
  }

  // Strip dotted BJ prefix (e.g. BJ.920748 → 920748)
  if (upper.startsWith('BJ.')) {
    const candidate = code.slice(3);
    if (/^\d{6}$/.test(candidate)) {
      return candidate;
    }
  }

  // Strip .SH/.SZ/.BJ suffix and .HK suffix with HK-prefix canonicalization
  if (code.includes('.')) {
    const dotIndex = code.lastIndexOf('.');
    const base = code.slice(0, dotIndex);
    const suffix = code.slice(dotIndex + 1).toUpperCase();

    // JP/KR Yahoo suffix-only codes are canonical as uppercase suffix forms.
    if (suffix === 'T' && /^\d{4,5}$/.test(base)) {
      return `${base}.${suffix}`;
    }
    if ((suffix === 'KS' || suffix === 'KQ') && /^\d{6}$/.test(base)) {
      return `${base}.${suffix}`;
    }
    // TW Yahoo suffix-only codes (TWSE `.TW` / TPEx `.TWO`), base 4-6 digits.
    if ((suffix === 'TW' || suffix === 'TWO') && /^\d{4,6}$/.test(base)) {
      return `${base}.${suffix}`;
    }

    // 00700.HK → HK00700
    if (suffix === 'HK' && /^\d{1,5}$/.test(base)) {
      return `HK${base.padStart(5, '0')}`;
    }

    // 600519.SH → 600519
    if ((suffix === 'SH' || suffix === 'SS' || suffix === 'SZ' || suffix === 'BJ') && /^\d+$/.test(base)) {
      return base;
    }
  }

  return code;
}

function stockCodeMatchKey(stockCode: string): string {
  return normalizeStockCode(stockCode).toUpperCase();
}

export function areStockCodesEquivalent(left: string, right: string): boolean {
  if (!left.trim() || !right.trim()) return false;
  return stockCodeMatchKey(left) === stockCodeMatchKey(right);
}

export function findMatchingStockCode(codes: string[], stockCode: string): string | undefined {
  if (!stockCode.trim()) return undefined;
  const targetKey = stockCodeMatchKey(stockCode);
  return codes.find((code) => code.trim() && stockCodeMatchKey(code) === targetKey);
}

export function includesStockCode(codes: string[], stockCode: string): boolean {
  return findMatchingStockCode(codes, stockCode) !== undefined;
}

// ============ Asset-aware identity key (PR #2312) ============
//
// Dashboard grouping must not fold a registered index (`sh000016`) with the
// same-code bare stock (`000016`). The backend now exposes an optional
// `asset_type` on tasks / history items / stock-bar rows and reports; the Web
// trusts that field first and only falls back to the loaded stock index
// registry for raw watchlist strings that carry no type. `normalizeStockCode`
// is deliberately NOT changed and is NOT applied to index identities — it
// would strip the `sh`/`sz`/`csi` prefix and re-fold the index with its stock.

export type AssetAwareAssetType = 'stock' | 'index';

export interface RegisteredIndexIdentity {
  canonicalCode: string;
  displayCode: string;
  aliases?: string[];
  assetType?: string;
}

/**
 * Fold an already-identified index code into its lowercase identity namespace.
 *
 * The backend guarantees that any API/task/report code tagged ``assetType=index``
 * is already the parser canonical (``sh000016`` / ``csi930955``) — including
 * legacy uppercase persisted forms (``SH000016`` / ``CSI930955``, folded by
 * case). The frontend therefore only case-folds; it must NEVER derive a
 * canonical from prefixes/suffixes, because registry aliases such as
 * ``000300.CSI`` and ``sz399300`` belong to ``sh000300`` and would be
 * fabricated into ``csi000300`` / ``sz399300`` by a regex guess. Only
 * ``resolveRegisteredIndexCanonical`` (exact registry hit) maps aliases, and
 * it is used solely for raw watchlist strings that carry no asset type.
 */
function foldIndexKey(code: string): string {
  // Locale-independent: `toLocaleLowerCase()` under the Turkish locale maps
  // `I` to dotless `ı`, which would break `CSI930955` -> `csi930955`. The
  // canonical namespace is plain ASCII, so `toLowerCase()` is always correct.
  return code.trim().toLowerCase();
}

/**
 * Asset-aware identity key shared by stock-bar, watchlist fallback, active
 * task, completed-refresh and batch-dedupe grouping.
 *
 * - `assetType === 'index'` -> case-folded canonical bucket (never runs stock
 *   normalization, so `sh000016` stays distinct from stock `000016`; never
 *   regex-derives a canonical from an alias form).
 * - otherwise (stock or unknown) -> existing stock normalization semantics.
 */
export function toAssetAwareCodeKey(
  code: string | null | undefined,
  assetType?: AssetAwareAssetType | null,
): string {
  const trimmed = (code ?? '').trim();
  if (!trimmed) return '';
  if (assetType === 'index') {
    return foldIndexKey(trimmed);
  }
  return normalizeStockCode(trimmed).toUpperCase();
}

/**
 * Exact registry hit used only for raw codes WITHOUT an asset type (e.g. raw
 * watchlist strings). Only an `assetType=index` row whose canonical/display/
 * explicit alias matches the code *exactly* (case-insensitive, no
 * normalization, no prefix guessing) buckets it as an index. Returns the
 * matched row's canonical (in lowercase canonical form) or null.
 */
export function resolveRegisteredIndexCanonical(
  index: ReadonlyArray<RegisteredIndexIdentity>,
  code: string | null | undefined,
): string | null {
  const trimmed = (code ?? '').trim();
  if (!trimmed) return null;
  const folded = trimmed.toLowerCase();
  for (const item of index) {
    if (!item || item.assetType !== 'index') continue;
    const candidates = [item.canonicalCode, item.displayCode, ...(item.aliases ?? [])];
    for (const candidate of candidates) {
      if (candidate && candidate.trim().toLowerCase() === folded) {
        const canonical = (item.canonicalCode ?? '').trim();
        return canonical ? canonical.toLowerCase() : null;
      }
    }
  }
  return null;
}

/**
 * Asset-aware equivalence used by row selection / notice matching: an index
 * row never matches a same-code stock row, because each side carries its own
 * asset type.
 */
export function areAssetAwareCodesEquivalent(
  left: string | null | undefined,
  leftAssetType: AssetAwareAssetType | null | undefined,
  right: string | null | undefined,
  rightAssetType: AssetAwareAssetType | null | undefined,
): boolean {
  const leftKey = toAssetAwareCodeKey(left, leftAssetType);
  const rightKey = toAssetAwareCodeKey(right, rightAssetType);
  return Boolean(leftKey && rightKey && leftKey === rightKey);
}
