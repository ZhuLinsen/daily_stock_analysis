import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { systemConfigApi } from '../api/systemConfig';
import { useActiveUiLanguage } from '../contexts/UiLanguageContext';
import { includesStockCode, toAssetAwareCodeKey } from '../utils/stockCode';

type WatchlistNotice =
  | { kind: 'added' | 'removed'; stockCode: string }
  | { kind: 'failed' }
  | null;

export interface UseWatchlistReturn {
  watchlistCodes: string[];
  isLoading: boolean;
  isActioning: boolean;
  actionMessage: string | null;
  isInWatchlist: (stockCode: string) => boolean;
  addToWatchlist: (stockCode: string) => Promise<void>;
  removeFromWatchlist: (stockCode: string) => Promise<void>;
  toggleWatchlist: (stockCode: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useWatchlist(getCodeKey: (code: string) => string = toAssetAwareCodeKey): UseWatchlistReturn {
  const activeLanguage = useActiveUiLanguage();
  const [codes, setCodes] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isActioning, setIsActioning] = useState(false);
  const [actionNotice, setActionNotice] = useState<WatchlistNotice>(null);
  const messageTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const actionInFlightRef = useRef(false);
  const nextRequestSeqRef = useRef(0);
  const committedSeqRef = useRef(0);
  const inFlightRefreshSeqsRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (messageTimerRef.current !== null) {
        window.clearTimeout(messageTimerRef.current);
        messageTimerRef.current = null;
      }
    };
  }, []);

  const refresh = useCallback(async () => {
    const requestSeq = ++nextRequestSeqRef.current;
    inFlightRefreshSeqsRef.current.add(requestSeq);
    try {
      const result = await systemConfigApi.getWatchlist();
      if (mountedRef.current && requestSeq > committedSeqRef.current) {
        committedSeqRef.current = requestSeq;
        setCodes(result);
      }
    } catch {
      // Keep committed codes and do not invalidate older in-flight GET snapshots on failure.
    } finally {
      inFlightRefreshSeqsRef.current.delete(requestSeq);
    }
  }, []);

  useEffect(() => {
    setIsLoading(true);
    void refresh().finally(() => {
      if (mountedRef.current) {
        setIsLoading(false);
      }
    });
  }, [refresh]);

  const showNotice = useCallback((notice: Exclude<WatchlistNotice, null>) => {
    if (messageTimerRef.current !== null) {
      window.clearTimeout(messageTimerRef.current);
      messageTimerRef.current = null;
    }
    setActionNotice(notice);
    messageTimerRef.current = window.setTimeout(() => {
      messageTimerRef.current = null;
      if (mountedRef.current) {
        setActionNotice(null);
      }
    }, 3000);
  }, []);

  const actionMessage = useMemo(() => {
    if (!actionNotice) return null;
    const isEn = activeLanguage === 'en';
    if (actionNotice.kind === 'failed') {
      return isEn ? 'Action failed' : '操作失败';
    }
    if (actionNotice.kind === 'added') {
      return isEn
        ? `Added ${actionNotice.stockCode} to watchlist`
        : `已加入自选 ${actionNotice.stockCode}`;
    }
    return isEn
      ? `Removed ${actionNotice.stockCode} from watchlist`
      : `已从自选移除 ${actionNotice.stockCode}`;
  }, [actionNotice, activeLanguage]);

  const isInWatchlist = useCallback(
    (stockCode: string) => includesStockCode(codes, stockCode, getCodeKey),
    [codes, getCodeKey],
  );

  const runWatchlistMutation = useCallback(
    async (
      stockCode: string,
      mutate: (code: string) => Promise<string[]>,
      successKind: 'added' | 'removed',
    ) => {
      if (!stockCode || actionInFlightRef.current) return;
      actionInFlightRef.current = true;
      const mutationSeq = ++nextRequestSeqRef.current;
      setIsActioning(true);
      let shouldFollowUpRefresh = false;
      try {
        const result = await mutate(stockCode);
        if (mountedRef.current) {
          for (const seq of inFlightRefreshSeqsRef.current) {
            if (seq > mutationSeq) {
              shouldFollowUpRefresh = true;
              break;
            }
          }
          // Invalidate every GET initiated before this mutation committed so an
          // overlapping pre-write read cannot revert the committed result.
          committedSeqRef.current = Math.max(
            committedSeqRef.current,
            nextRequestSeqRef.current,
          );
          setCodes(result);
          showNotice({ kind: successKind, stockCode });
        }
      } catch {
        if (mountedRef.current) {
          showNotice({ kind: 'failed' });
        }
      } finally {
        actionInFlightRef.current = false;
        if (mountedRef.current) {
          setIsActioning(false);
          if (shouldFollowUpRefresh) {
            void refresh();
          }
        }
      }
    },
    [refresh, showNotice],
  );

  const addToWatchlist = useCallback(
    async (stockCode: string) => runWatchlistMutation(
      stockCode,
      (code) => systemConfigApi.addToWatchlist(code),
      'added',
    ),
    [runWatchlistMutation],
  );

  const removeFromWatchlist = useCallback(
    async (stockCode: string) => runWatchlistMutation(
      stockCode,
      (code) => systemConfigApi.removeFromWatchlist(code),
      'removed',
    ),
    [runWatchlistMutation],
  );

  const toggleWatchlist = useCallback(async (stockCode: string) => {
    if (isInWatchlist(stockCode)) {
      await removeFromWatchlist(stockCode);
    } else {
      await addToWatchlist(stockCode);
    }
  }, [isInWatchlist, removeFromWatchlist, addToWatchlist]);

  return {
    watchlistCodes: codes,
    isLoading,
    isActioning,
    actionMessage,
    isInWatchlist,
    addToWatchlist,
    removeFromWatchlist,
    toggleWatchlist,
    refresh,
  };
}
