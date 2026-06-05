/**
 * Normalize stock code by stripping exchange prefixes/suffixes.
 *
 * Mirrors the behavior of data_provider.base.normalize_stock_code in the backend.
 *
 *   600519      → 600519     SH600519    → 600519
 *   600519.SH   → 600519     SH.600519   → 600519
 *   SZ000001    → 000001     000001.SZ   → 000001
 *   BJ920748    → 920748     920748.BJ   → 920748
 *   HK00700     → HK00700    00700.HK    → HK00700
 *   hk1810      → HK01810    1810.HK     → HK01810
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
