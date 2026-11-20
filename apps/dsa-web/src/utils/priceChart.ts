import type { StockKLineItem } from '../api/stocks';

export interface PriceChartDatum {
  date: string;
  shortDate: string;
  close: number;
  high: number;
  low: number;
  ma5: number | null;
  ma20: number | null;
}

/** Extract first finite positive number from strategy strings like "1480元", "$210.50", "1,480 - 1,500". */
export function parseStrategyPriceLevel(raw?: string | null): number | null {
  if (!raw || typeof raw !== 'string') {
    return null;
  }
  const cleaned = raw.replace(/,/g, '').trim();
  if (!cleaned || cleaned === '--' || cleaned === '—' || /^n\/?a$/i.test(cleaned)) {
    return null;
  }
  const match = cleaned.match(/\d+(?:\.\d+)?/);
  if (!match) {
    return null;
  }
  const value = Number(match[0]);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Enrich chronological daily bars with rolling MA5 / MA20 close overlays. */
export function enrichBarsWithMovingAverages(bars: StockKLineItem[]): PriceChartDatum[] {
  const sorted = [...bars]
    .filter((b) => b && Number.isFinite(Number(b.close)) && Number(b.close) > 0)
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));

  return sorted.map((bar, idx) => {
    const close = Number(bar.close);
    const high = Number.isFinite(Number(bar.high)) && Number(bar.high) > 0 ? Number(bar.high) : close;
    const low = Number.isFinite(Number(bar.low)) && Number(bar.low) > 0 ? Number(bar.low) : close;

    let ma5: number | null = null;
    if (idx >= 4) {
      let sum5 = 0;
      for (let i = idx - 4; i <= idx; i += 1) {
        sum5 += Number(sorted[i].close);
      }
      ma5 = Number((sum5 / 5).toFixed(2));
    }

    let ma20: number | null = null;
    if (idx >= 19) {
      let sum20 = 0;
      for (let i = idx - 19; i <= idx; i += 1) {
        sum20 += Number(sorted[i].close);
      }
      ma20 = Number((sum20 / 20).toFixed(2));
    }

    return {
      date: bar.date,
      shortDate: bar.date.length >= 10 ? bar.date.slice(5, 10) : bar.date,
      close,
      high,
      low,
      ma5,
      ma20,
    };
  });
}
