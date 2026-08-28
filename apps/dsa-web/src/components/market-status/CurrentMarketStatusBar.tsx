import type React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Clock3 } from 'lucide-react';
import { marketStatusApi } from '../../api/marketStatus';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { MarketPhaseValue } from '../../types/analysis';
import type { MarketStatusItem, MarketStatusRegion, MarketStatusResponse } from '../../types/marketStatus';
import { cn } from '../../utils/cn';

const REFRESH_INTERVAL_MS = 60_000;

const MARKET_TIMEZONES: Record<MarketStatusRegion, string> = {
  cn: 'Asia/Shanghai',
  hk: 'Asia/Hong_Kong',
  us: 'America/New_York',
  jp: 'Asia/Tokyo',
  kr: 'Asia/Seoul',
};

const PHASE_TONE: Record<MarketPhaseValue, string> = {
  intraday: 'bg-success',
  closing_auction: 'bg-warning',
  lunch_break: 'bg-warning',
  premarket: 'bg-info',
  postmarket: 'bg-muted-text/55',
  non_trading: 'bg-muted-text/55',
  unknown: 'bg-muted-text/35',
};

const PHASE_LABEL_KEYS: Record<MarketPhaseValue, Parameters<ReturnType<typeof useUiLanguage>['t']>[0]> = {
  intraday: 'home.marketStatusTrading',
  closing_auction: 'home.marketStatusClosingAuction',
  lunch_break: 'home.marketStatusLunchBreak',
  premarket: 'home.marketStatusPremarket',
  postmarket: 'home.marketStatusClosed',
  non_trading: 'home.marketStatusNonTrading',
  unknown: 'home.marketStatusUnknown',
};

const formatMarketTime = (item: MarketStatusItem, language: 'zh' | 'en') => {
  const value = new Date(item.marketLocalTime);
  if (Number.isNaN(value.getTime())) return '--:--';
  return new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: MARKET_TIMEZONES[item.market],
  }).format(value);
};

const formatNextOpen = (item: MarketStatusItem, language: 'zh' | 'en') => {
  if (!item.nextSessionOpen) return null;
  const value = new Date(item.nextSessionOpen);
  if (Number.isNaN(value.getTime())) return null;
  return new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-CN', {
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: MARKET_TIMEZONES[item.market],
  }).format(value);
};

export const CurrentMarketStatusBar: React.FC = () => {
  const { language, t } = useUiLanguage();
  const [status, setStatus] = useState<MarketStatusResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const hasDataRef = useRef(false);

  useEffect(() => {
    let active = true;

    const refresh = async () => {
      try {
        const next = await marketStatusApi.getStatus();
        if (active) {
          hasDataRef.current = true;
          setStatus(next);
          setFailed(false);
        }
      } catch {
        if (active && !hasDataRef.current) setFailed(true);
      }
    };

    void refresh();
    const intervalId = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const orderedMarkets = useMemo(() => status?.markets ?? [], [status]);
  if (failed || orderedMarkets.length === 0) return null;

  const marketLabels: Record<MarketStatusRegion, string> = {
    cn: t('home.marketRegionCn'),
    hk: t('home.marketRegionHk'),
    us: t('home.marketRegionUs'),
    jp: t('home.marketRegionJp'),
    kr: t('home.marketRegionKr'),
  };

  return (
    <section
      aria-label={t('home.marketStatusTitle')}
      className="mx-2 mt-2 flex min-h-11 items-stretch overflow-hidden rounded-xl border border-subtle bg-card md:mx-0"
    >
      <div className="hidden flex-shrink-0 items-center gap-2 border-r border-subtle px-3 lg:flex">
        <Activity className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        <span className="label-uppercase whitespace-nowrap">{t('home.marketStatusTitle')}</span>
      </div>
      <div className="market-status-scroll flex min-w-0 flex-1 items-stretch overflow-x-auto">
        {orderedMarkets.map((item) => {
          const nextOpen = formatNextOpen(item, language);
          const detail = item.minutesToOpen != null
            ? t('home.marketStatusMinutesToOpen', { minutes: item.minutesToOpen })
            : item.minutesToClose != null
              ? t('home.marketStatusMinutesToClose', { minutes: item.minutesToClose })
              : nextOpen
                ? t('home.marketStatusNextOpen', { time: nextOpen })
                : t(PHASE_LABEL_KEYS[item.phase]);

          return (
            <div
              key={item.market}
              className="flex min-w-[7.25rem] flex-1 items-center gap-1.5 border-r border-subtle px-2 py-2 sm:min-w-[8rem] sm:px-3 last:border-r-0"
              aria-label={`${marketLabels[item.market]} · ${t(PHASE_LABEL_KEYS[item.phase])} · ${detail}`}
            >
              <span className={cn('h-1.5 w-1.5 flex-shrink-0 rounded-full', PHASE_TONE[item.phase])} aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 whitespace-nowrap text-[12px] font-medium text-foreground">
                  {marketLabels[item.market]}
                  <span className="font-mono text-[10px] font-normal text-muted-text">{formatMarketTime(item, language)}</span>
                </span>
                <span className="mt-0.5 flex items-center gap-1 truncate text-[10px] text-muted-text">
                  <Clock3 className="h-2.5 w-2.5 flex-shrink-0" aria-hidden="true" />
                  <span className="font-medium text-secondary-text">{t(PHASE_LABEL_KEYS[item.phase])}</span>
                  <span aria-hidden="true">·</span>
                  <span className="truncate">{detail}</span>
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
};
