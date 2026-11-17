import type React from 'react';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  Bookmark,
  Building2,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Droplet,
  Factory,
  Flame,
  Gem,
  Landmark,
  Pickaxe,
  Plane,
  Play,
  PlusCircle,
  RefreshCw,
  Search,
  Shield,
  SlidersHorizontal,
  Stethoscope,
  Trees,
  Utensils,
  Wrench,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import {
  screeningApi,
  type ScreeningCandidate,
  type ScreeningExplanationItem,
  type ScreeningHotspotDetail,
  type ScreeningHotspot,
  type ScreeningHotspotsResponse,
  type ScreeningRunSummary,
  type ScreeningScreenResponse,
  type ScreeningScreenTaskStatus,
  type ScreeningStrategy,
} from '../api/screening';
import { getParsedApiError, toApiErrorMessage, type ParsedApiError } from '../api/error';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiLanguage } from '../i18n/uiText';
import { SCREENING_TEXT, screeningText, type ScreeningTextKey } from '../locales/screening';
import { AppPage, Button, InlineAlert, Select } from '../components/common';

const MARKET_IDS = ['cn'];
const SCREEN_TASK_STORAGE_KEY = 'dsa.screening.activeScreenTask.v1';
const SCREEN_TASK_POLL_INTERVAL_MS = 2000;
const CUSTOM_STRATEGY_OPTION_VALUE = '__custom_strategy__';
const STRATEGY_CATEGORY_LABELS: Record<string, ScreeningTextKey> = {
  framework: 'framework',
  income: 'income',
  momentum: 'momentum',
  quality: 'quality',
  reversal: 'reversal',
  trend: 'trend',
  value: 'value',
};

const formatStrategyCategory = (language: UiLanguage, value?: string) => {
  const normalized = value?.trim();
  if (!normalized) {
    return SCREENING_TEXT[language].custom;
  }
  return SCREENING_TEXT[language][STRATEGY_CATEGORY_LABELS[normalized.toLowerCase()]] || normalized;
};

type PersistedScreenTask = {
  taskId: string;
  runId?: string;
  market: string;
  strategy: string;
  maxResults: number;
};

const formatRunCreatedAt = (language: UiLanguage, value: string | null | undefined) => {
  if (!value) {
    return SCREENING_TEXT[language].unknownTime;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
};

// Retain the stored strategy ID when a strategy is no longer in the catalog.
const formatHistoryStrategyName = (language: UiLanguage, strategyId: string, strategies: ScreeningStrategy[]): string => {
  const matched = strategies.find((item) => item.id === strategyId);
  return matched?.name || matched?.title || strategyId || SCREENING_TEXT[language].unknownStrategy;
};

const formatHistoryMarketLabel = (language: UiLanguage, marketId: string | null | undefined): string =>
  marketId === 'cn' ? SCREENING_TEXT[language].marketA : marketId || 'cn';

const readPersistedScreenTask = (): PersistedScreenTask | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(SCREEN_TASK_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<PersistedScreenTask>;
    if (typeof parsed.taskId !== 'string' || !parsed.taskId.trim()) {
      return null;
    }
    const restoredMaxResults = Number(parsed.maxResults);
    return {
      taskId: parsed.taskId,
      runId: typeof parsed.runId === 'string' && parsed.runId.trim() ? parsed.runId : undefined,
      market: typeof parsed.market === 'string' && parsed.market.trim() ? parsed.market : 'cn',
      strategy: typeof parsed.strategy === 'string' && parsed.strategy.trim() ? parsed.strategy : 'dual_low',
      maxResults: Number.isFinite(restoredMaxResults) ? Math.min(100, Math.max(1, restoredMaxResults)) : 3,
    };
  } catch {
    return null;
  }
};

const persistScreenTask = (task: PersistedScreenTask) => {
  try {
    window.sessionStorage.setItem(SCREEN_TASK_STORAGE_KEY, JSON.stringify(task));
  } catch {
    // Session storage is best-effort; polling still works while the page stays mounted.
  }
};

const clearPersistedScreenTask = () => {
  try {
    window.sessionStorage.removeItem(SCREEN_TASK_STORAGE_KEY);
  } catch {
    // Ignore storage cleanup failures.
  }
};

const isUnrecoverableScreenTaskError = (error: ParsedApiError) =>
  error.code === 'screening_screen_task_not_found';

const formatRecoverableScreenTaskPollingError = (language: UiLanguage, error: ParsedApiError) => {
  if (error.category === 'upstream_timeout') {
    return SCREENING_TEXT[language].pollTimeout;
  }
  if (error.category === 'upstream_network' || error.category === 'local_connection_failed') {
    return SCREENING_TEXT[language].pollNetwork;
  }
  return formatScreeningApiError(language, error, SCREENING_TEXT[language].pollRetry);
};

const formatScore = (score: ScreeningCandidate['score']) => {
  if (score == null || Number.isNaN(Number(score))) {
    return '-';
  }
  return Number(score).toFixed(2);
};

const formatNumber = (value: unknown, digits = 2) => {
  if (value == null || value === '' || Number.isNaN(Number(value))) {
    return '-';
  }
  return Number(value).toFixed(digits);
};

const formatAmount = (language: UiLanguage, value: unknown) => {
  if (value == null || value === '' || Number.isNaN(Number(value))) {
    return '-';
  }
  const amount = Number(value);
  if (language === 'en') {
    for (const [divisor, suffix] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']] as const) {
      if (Math.abs(amount) >= divisor) return `${(amount / divisor).toFixed(2)} ${suffix}`;
    }
    return amount.toFixed(2);
  }
  if (Math.abs(amount) >= 100_000_000) {
    return `${(amount / 100_000_000).toFixed(2)} 亿`;
  }
  if (Math.abs(amount) >= 10_000) {
    return `${(amount / 10_000).toFixed(2)} 万`;
  }
  return amount.toFixed(2);
};

const formatPercent = (value: unknown) => {
  if (value == null || value === '' || Number.isNaN(Number(value))) {
    return '-';
  }
  return `${(Number(value) * 100).toFixed(0)}%`;
};

const FACTOR_LABELS: Record<string, ScreeningTextKey> = {
  value: 'valuation',
  liquidity: 'liquidity',
  momentum: 'momentum',
  reversal: 'reversal',
  activity: 'activity',
  stability: 'stability',
  size: 'size',
  themeHeat: 'themeHeat',
  theme_heat: 'themeHeat',
  topicAlignment: 'topicAlignment',
  topic_alignment: 'topicAlignment',
};

const HOTSPOT_QUALITY_LABELS: Record<string, ScreeningTextKey> = {
  available: 'available',
  failed: 'unavailable',
  partial: 'partial',
  stale: 'cached',
};

const HOTSPOT_STAGE_LABELS: Record<string, ScreeningTextKey> = {
  accelerating: 'accelerating',
  cooling: 'cooling',
  diverging: 'diverging',
  initial: 'initial',
  persistent_hot: 'warming',
  warming: 'warming',
  weakening: 'cooling',
};

const HOTSPOT_ROLE_LABELS: Record<string, ScreeningTextKey> = {
  core_leader: 'leader',
  follower: 'follower',
  laggard: 'laggard',
  leader: 'leader',
  secondary: 'secondary',
};

const HOTSPOT_MISSING_FIELD_LABELS: Record<string, ScreeningTextKey> = {
  canonical_topic: 'canonicalTopic',
  hotspot_constituents: 'constituents',
  leader_stocks: 'leaders',
  live_stocks: 'liveStocks',
  route: 'route',
  source: 'dataSource',
  stocks: 'constituents',
  timeline: 'timeline',
};

const getHotspotStageLabel = (language: UiLanguage, value: unknown) => {
  const text = String(value || '').trim();
  if (!text) {
    return '';
  }
  return SCREENING_TEXT[language][HOTSPOT_STAGE_LABELS[text.toLowerCase()]] || text;
};

const getHotspotRoleLabel = (language: UiLanguage, value: unknown) => {
  const text = String(value || '').trim();
  if (!text) {
    return SCREENING_TEXT[language].themeStocks;
  }
  return SCREENING_TEXT[language][HOTSPOT_ROLE_LABELS[text.toLowerCase()]] || text;
};

const getHotspotQualityLabel = (language: UiLanguage, value: unknown) => {
  const text = String(value || '').trim();
  return SCREENING_TEXT[language][HOTSPOT_QUALITY_LABELS[text.toLowerCase()]] || SCREENING_TEXT[language].unconfirmed;
};

const getCandidateReason = (language: UiLanguage, item: ScreeningCandidate) => {
  if (item.llmThesis || item.llmScore != null) {
    return item.reason || item.llmThesis || SCREENING_TEXT[language].llmDone;
  }
  if (item.reason) {
    return item.reason;
  }
  const summaries = item.postAnalysisSummaries || {};
  const summary = Object.values(summaries).find((value) => typeof value === 'string' && value.trim());
  if (typeof summary === 'string') {
    return summary;
  }
  return SCREENING_TEXT[language].noSummary;
};

const getSignal = (language: UiLanguage, item: ScreeningCandidate) => {
  const rawSignal = item.raw.action ?? item.raw.signal ?? item.raw.recommendation;
  return typeof rawSignal === 'string' && rawSignal.trim() ? rawSignal : SCREENING_TEXT[language].watch;
};

const getFactorEntries = (item: ScreeningCandidate) =>
  Object.entries(item.factorScores || {})
    .filter(([, value]) => typeof value === 'number')
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 6);

const getSelectionExplanations = (language: UiLanguage, item: ScreeningCandidate): ScreeningExplanationItem[] => {
  if (item.whySelected?.length) return item.whySelected;
  // Legacy runs lack provenance. Retain every stored summary as unknown rather
  // than re-scoring historical factors or asserting it was observed.
  const summaries = Array.from(new Set(
    [item.reason, item.llmThesis, ...Object.values(item.postAnalysisSummaries || {})]
      .filter((value): value is string => typeof value === 'string' && Boolean(value.trim()))
      .map((value) => value.trim()),
  ));
  return summaries.map((summary) => ({
    code: 'legacy_summary',
    text: screeningText(language, 'legacySummary', { summary }),
    source: 'legacy_result',
    quality: 'unknown',
  }));
};

const ExplanationItems = ({ items, emptyText }: { items?: ScreeningExplanationItem[]; emptyText: string }) => {
  const { language } = useUiLanguage();
  if (!items?.length) return <p className="mt-1 text-sm leading-6 text-foreground">{emptyText}</p>;
  return (
    <ul className="mt-2 space-y-2">
      {items.map((item, index) => (
        <li key={`${item.code}-${item.source}-${index}`} className="rounded-lg border border-border/50 bg-background/30 p-2">
          <p className="text-sm leading-6 text-foreground">{item.text}</p>
          <p className="mt-1 text-xs text-secondary-text">
            {SCREENING_TEXT[language].sourceLabel}{item.source || 'unknown'} {SCREENING_TEXT[language].qualityLabel}{item.quality || 'unknown'}
          </p>
        </li>
      ))}
    </ul>
  );
};

const toMessageList = (values: string[] | undefined) =>
  Array.isArray(values) ? values.map((value) => String(value).trim()).filter(Boolean) : [];

const KNOWN_SNAPSHOT_SOURCES = new Set(['tushare', 'sina', 'efinance', 'akshare_em', 'em_datacenter', 'baostock']);
const MAX_MESSAGE_DETAIL_LENGTH = 96;

const truncateMessageDetail = (value: string, maxLength = MAX_MESSAGE_DETAIL_LENGTH) => {
  const text = value.replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1)}…`;
};

const summarizeScreeningDiagnostic = (language: UiLanguage, detail: string) => {
  if (/no_json_found|invalid_response|coverage below threshold/i.test(detail)) {
    return SCREENING_TEXT[language].invalidRanking;
  }
  if (/call_failed/i.test(detail)) {
    return SCREENING_TEXT[language].modelFailed;
  }
  if (/trade_cal returned no open trading days/i.test(detail)) {
    return SCREENING_TEXT[language].calendarEmpty;
  }
  if (/too many requests|rate limit|http\s*429/i.test(detail)) {
    return SCREENING_TEXT[language].rateLimited;
  }
  if (/403 forbidden|forbidden|access denied/i.test(detail)) {
    return SCREENING_TEXT[language].accessDenied;
  }
  if (/timeout|timed out/i.test(detail)) {
    return SCREENING_TEXT[language].timeout;
  }
  if (/RemoteDisconnected|Connection aborted|ProtocolError|ConnectionPool|Max retries exceeded|ProxyError|NameResolutionError/i.test(detail)) {
    return SCREENING_TEXT[language].networkInterrupted;
  }
  if (/missing .*api key|GEMINI_API_KEY|GOOGLE_API_KEY|gemini_api_key/i.test(detail)) {
    return SCREENING_TEXT[language].missingLlmKey;
  }
  if (/returned no data|empty/i.test(detail)) {
    return SCREENING_TEXT[language].noData;
  }

  const withoutUrl = detail
    .replace(/https?:\/\/\S+/gi, 'URL')
    .replace(/\bwith url:\s*\S+/gi, 'with url: URL')
    .replace(/\burl:\s*\S+/gi, 'url: URL');
  return truncateMessageDetail(withoutUrl);
};

const parseSourceDiagnostic = (value: string) => {
  const match = value.match(/^([a-zA-Z0-9_-]+)\s*[:：]\s*(.+)$/);
  if (!match) {
    return null;
  }
  return {
    source: match[1],
    detail: match[2],
  };
};

const normalizeScreenMessageKey = (language: UiLanguage, value: string) => {
  const formatted = formatScreenMessage(language, value);
  return formatted ? formatted.trim().toLowerCase() : value.trim().toLowerCase();
};

const formatEnrichmentSummary = (language: UiLanguage, value: string) =>
  value
    .replace(/DSA行情\s*[:：]\s*/gi, SCREENING_TEXT[language].quotePrefix)
    .replace(/DSA新闻\s*[:：]\s*/gi, SCREENING_TEXT[language].newsPrefix)
    .replace(/DSA事件\s*[:：]\s*/gi, SCREENING_TEXT[language].eventPrefix);

const formatScreenMessage = (language: UiLanguage, value: string) => {
  if (/^DSA provider context applied \d+ of \d+ candidates/i.test(value)) {
    return '';
  }
  if (/^LLM ranking skipped:\s*no LLM config/i.test(value)) {
    return SCREENING_TEXT[language].llmNotConfigured;
  }
  if (/^LLM ranking failed/i.test(value)) {
    return screeningText(language, 'rankingFailed', { detail: summarizeScreeningDiagnostic(language, value) });
  }
  if (/no_json_found|invalid_response|coverage below threshold|call_failed/i.test(value)) {
    return screeningText(language, 'rankingFailed', { detail: summarizeScreeningDiagnostic(language, value) });
  }
  if (/^(?:LLM ranking prompt|LLM context) truncated:/i.test(value)) {
    return '';
  }
  if (/^(?:Remote post-analysis cap|Risk veto excluded|Snapshot hard-filter waterfall|Daily hard-filter waterfall|Daily hard-filter rejections|Candidate context collected rows=)/i.test(value)) {
    return '';
  }
  if (/^Daily K-line (?:enrichment attempted|sources|quality flags|source ordering|source health):?/i.test(value)) {
    return '';
  }
  if (/^Daily K-line enrichment row errors:/i.test(value)) {
    return SCREENING_TEXT[language].dailyPartial;
  }
  if (/^Daily K-line enrichment skipped:/i.test(value)) {
    return SCREENING_TEXT[language].dailySkipped;
  }
  if (/^Candidate context row errors:/i.test(value)) {
    return SCREENING_TEXT[language].contextPartial;
  }
  if (/^Industry\/concepts enrichment:/i.test(value)) {
    return SCREENING_TEXT[language].industryPartial;
  }
  if (/^DSA deep analysis failed for /i.test(value)) {
    return SCREENING_TEXT[language].analysisPartial;
  }

  const snapshotFallback = value.match(/^Snapshot source fallback:\s*(.+)$/i);
  if (snapshotFallback) {
    const parsed = parseSourceDiagnostic(snapshotFallback[1]);
    if (parsed) {
      return screeningText(language, 'sourceFallback', { source: parsed.source, detail: summarizeScreeningDiagnostic(language, parsed.detail) });
    }
    return screeningText(language, 'sourceFallbackDetail', { detail: summarizeScreeningDiagnostic(language, snapshotFallback[1]) });
  }

  const parsed = parseSourceDiagnostic(value);
  if (parsed && KNOWN_SNAPSHOT_SOURCES.has(parsed.source.toLowerCase())) {
    return screeningText(language, 'sourceFallback', { source: parsed.source, detail: summarizeScreeningDiagnostic(language, parsed.detail) });
  }
  return truncateMessageDetail(value);
};

const getScreenMessages = (language: UiLanguage, meta: ScreeningScreenResponse | null) => {
  if (!meta) {
    return [];
  }
  const messages: string[] = [];
  const seen = new Set<string>();
  [...toMessageList(meta.warnings), ...toMessageList(meta.sourceErrors), ...toMessageList(meta.llmParseErrors)].forEach(
    (value) => {
      const key = normalizeScreenMessageKey(language, value);
      if (seen.has(key)) {
        return;
      }
      const message = formatScreenMessage(language, value);
      if (!message) {
        return;
      }
      seen.add(key);
      messages.push(message);
    },
  );
  return messages;
};

const isRunningScreenTask = (status: string | undefined | null) => status === 'pending' || status === 'processing';

const formatScreenTaskFailure = (language: UiLanguage, value: string | null | undefined) => {
  const text = String(value || '').trim();
  if (!text) {
    return SCREENING_TEXT[language].taskFailed;
  }
  return screeningText(language, 'taskFailureDetail', { detail: summarizeScreeningDiagnostic(language, text) });
};

const SCREENING_HOTSPOT_NO_CACHE_HINT = 'No cached Screening hotspot snapshot. Click refresh to fetch live hotspots.';
const SCREENING_HOTSPOT_UNAVAILABLE_CODE = 'eastmoney_hotspot_unavailable';

const formatHotspotEmptyMessage = (language: UiLanguage, result: ScreeningHotspotsResponse) => {
  const message = String(result.message || '').trim();
  const sourceErrors = result.sourceErrors || [];
  if (message && sourceErrors.includes(SCREENING_HOTSPOT_UNAVAILABLE_CODE)) {
    return language === 'en' && message === '热点源连接中断，暂无可用缓存。'
      ? SCREENING_TEXT.en.hotspotOffline : message;
  }
  if (message === SCREENING_HOTSPOT_NO_CACHE_HINT) {
    return SCREENING_TEXT[language].noHotspotCache;
  }
  const sourceError = sourceErrors[0];
  if (sourceError) {
    return screeningText(language, 'hotspotEmptyDetail', { detail: summarizeScreeningDiagnostic(language, sourceError) });
  }
  return SCREENING_TEXT[language].noHotspots;
};

const ScreenAlertMessage: React.FC<{ messages: string[] }> = ({ messages }) => {
  if (messages.length <= 1) {
    return <span>{messages[0]}</span>;
  }
  return (
    <ul className="list-disc space-y-1 pl-4">
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
};

const hasLlmInsight = (item: ScreeningCandidate) =>
  Boolean(
    item.llmThesis ||
      item.llmSector ||
      item.llmTheme ||
      item.llmConfidence != null ||
      item.llmWatchItems?.length ||
      item.llmCatalysts?.length,
  );

const getRiskClassName = (riskLevel: string | undefined) => {
  if (riskLevel === 'high') {
    return 'bg-danger/10 text-danger';
  }
  if (riskLevel === 'medium') {
    return 'bg-warning/10 text-warning';
  }
  if (riskLevel === 'low') {
    return 'bg-success/10 text-success';
  }
  return 'bg-surface text-secondary-text';
};

const getRiskLabel = (language: UiLanguage, riskLevel: string | undefined) => {
  if (riskLevel === 'high') return SCREENING_TEXT[language].highRisk;
  if (riskLevel === 'medium') return SCREENING_TEXT[language].mediumRisk;
  if (riskLevel === 'low') return SCREENING_TEXT[language].lowRisk;
  return SCREENING_TEXT[language].riskUnknown;
};

const getRouteTimeLabel = (language: UiLanguage, item: ScreeningHotspotDetail['route'][number]) => {
  const rawTime = item.publishedAt || item.date || item.time || '';
  if (!rawTime) {
    return SCREENING_TEXT[language].timeUnconfirmed;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(rawTime)) {
    return rawTime;
  }
  const parsed = new Date(rawTime);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  }
  return rawTime;
};

const formatHotspotRouteTitle = (language: UiLanguage, value: string) => {
  const text = String(value || '').trim();
  const normalized = text.toLowerCase();
  if (normalized === 'current fermentation') {
    return SCREENING_TEXT[language].currentActivity;
  }
  if (normalized === 'news catalyst') {
    return SCREENING_TEXT[language].newsCatalyst;
  }
  return text || SCREENING_TEXT[language].hotspotChange;
};

const formatHotspotRouteDescription = (language: UiLanguage, value: string) => {
  const text = String(value || '').trim();
  if (!text) {
    return SCREENING_TEXT[language].noDescription;
  }
  const parts = text.split(/\s*;\s*/).map((part) => part.trim()).filter(Boolean);
  if (parts.some((part) => /\b(?:heat|stage|leaders?)\b/i.test(part))) {
    const localized = parts.map((part) => {
      const heat = part.match(/^(.*?)\s+heat\s+(-?\d+(?:\.\d+)?)$/i);
      if (heat) {
        return screeningText(language, 'topicHeat', { topic: heat[1], heat: formatNumber(heat[2], 1) });
      }
      const stage = part.match(/^stage\s+(.+)$/i);
      if (stage) {
        return screeningText(language, 'stageValue', { stage: getHotspotStageLabel(language, stage[1]) });
      }
      const leaders = part.match(/^leaders?\s+(.+)$/i);
      if (leaders) {
        return screeningText(language, 'leadersValue', { leaders: leaders[1].split(/\s*,\s*/).filter(Boolean).join(language === 'en' ? ', ' : '、') });
      }
      return part;
    });
    return language === 'en' ? `${localized.join(', ')}.` : `${localized.join('，')}。`;
  }
  if (/Dsa[A-Z]|Provider\b|stock_board_|concept_constituents|leader_stocks|last_good_cache/i.test(text)) {
    return SCREENING_TEXT[language].hotspotUpdated;
  }
  return text;
};

const getHotspotMissingFieldLabels = (language: UiLanguage, values: string[] | undefined) => {
  const labels = (values || []).map((value) => SCREENING_TEXT[language][HOTSPOT_MISSING_FIELD_LABELS[String(value).trim().toLowerCase()]] || SCREENING_TEXT[language].partialDetails);
  return [...new Set(labels)];
};

const formatHotspotDiagnostic = (language: UiLanguage, value: string) => {
  const text = String(value || '').trim();
  const timeoutSeconds = text.match(/timed out after\s*(\d+(?:\.\d+)?)s/i);
  if (timeoutSeconds) {
    return screeningText(language, 'hotspotTimeoutSeconds', { seconds: timeoutSeconds[1] });
  }
  if (/timeout|timed out/i.test(text)) {
    return SCREENING_TEXT[language].hotspotTimeout;
  }
  if (/RemoteDisconnected|Connection aborted|ProtocolError|ConnectionPool|Max retries exceeded|ProxyError|NameResolutionError/i.test(text)) {
    return SCREENING_TEXT[language].hotspotConnection;
  }
  if (/eastmoney_hotspot_unavailable|returned no data|no live hotspot rows|\bempty\b/i.test(text)) {
    return SCREENING_TEXT[language].hotspotSourceEmpty;
  }
  if (/rate limit|too many requests|http\s*429/i.test(text)) {
    return SCREENING_TEXT[language].hotspotRateLimit;
  }
  if (/Dsa[A-Z]|Provider\b|stock_board_|concept_constituents|leader_stocks|last_good_cache|^[a-z0-9_.:-]+$/i.test(text)) {
    return SCREENING_TEXT[language].hotspotPartial;
  }
  if (/[\u0080-\uFFFF]/.test(text)) {
    return truncateMessageDetail(text);
  }
  return SCREENING_TEXT[language].hotspotPartial;
};

const getHotspotDiagnosticMessages = (language: UiLanguage, values: string[] | undefined) =>
  [...new Set((values || []).map((value) => formatHotspotDiagnostic(language, value)).filter(Boolean))].slice(0, 4);

const hasHotspotDetailDegradation = (detail: ScreeningHotspotDetail) => {
  if ((detail.missingFields || []).length > 0) {
    return true;
  }
  const qualityStatus = String(detail.qualityStatus || '').trim().toLowerCase();
  if (qualityStatus) {
    return qualityStatus !== 'available';
  }
  return (detail.sourceErrors || []).length > 0;
};

const getHotspotFallbackLabel = (language: UiLanguage, detail: ScreeningHotspotDetail) => {
  if (detail.stale || detail.cacheUsed) {
    return detail.staleAgeHours != null
      ? screeningText(language, 'cacheAge', { hours: formatNumber(detail.staleAgeHours, 1) })
      : SCREENING_TEXT[language].cacheFallback;
  }
  return SCREENING_TEXT[language].backupSource;
};

const getHotspotSummaryText = (language: UiLanguage, detail: ScreeningHotspotDetail, hotspot?: ScreeningHotspot) => {
  const summaryDetail = detail.summaryDetail || {};
  const heatScore = summaryDetail.heatScore ?? summaryDetail.heat_score ?? hotspot?.heatScore;
  const stage = summaryDetail.stage ?? hotspot?.stage ?? hotspot?.state;
  const rawLeaders = summaryDetail.leaders ?? hotspot?.leaders;
  const leaders = Array.isArray(rawLeaders)
    ? rawLeaders.map((value) => String(value).trim()).filter(Boolean).slice(0, 3)
    : [];
  const parts: string[] = [];
  if (heatScore != null && !Number.isNaN(Number(heatScore))) {
    parts.push(screeningText(language, 'heatValue', { heat: formatNumber(heatScore, 1) }));
  }
  if (stage) {
    parts.push(screeningText(language, 'stageValue', { stage: getHotspotStageLabel(language, stage) }));
  }
  if (leaders.length > 0) {
    parts.push(screeningText(language, 'leadersValue', { leaders: leaders.join(language === 'en' ? ', ' : '、') }));
  }
  if (parts.length > 0) {
    const topic = detail.name || detail.canonicalTopic || detail.topic;
    return language === 'en' ? `${topic}: ${parts.join(', ')}.` : `${topic}：${parts.join('，')}。`;
  }
  const summary = String(detail.summary || '').trim();
  if (summary && !/\b(?:heat|stage|leaders?|quality status|available|partial|stale|failed)\b|Dsa[A-Z]|Provider\b|stock_board_/i.test(summary)) {
    return summary;
  }
  return SCREENING_TEXT[language].hotspotLoaded;
};

const buildHotspotPreviewDetail = (hotspot: ScreeningHotspot): ScreeningHotspotDetail => {
  const leaders = (hotspot.leaders || []).map((value) => String(value).trim()).filter(Boolean);
  const stage = hotspot.stage || hotspot.state || '';
  const heat = formatNumber(hotspot.heatScore, 1);
  const descriptionParts = heat === '-' ? [] : [`${hotspot.name || hotspot.topic} heat ${heat}`];
  if (stage) {
    descriptionParts.push(`stage ${stage}`);
  }
  if (leaders.length > 0) {
    descriptionParts.push(`leaders ${leaders.slice(0, 3).join(', ')}`);
  }
  const stocks = (hotspot.leaderStocks || []).slice(0, 10);
  return {
    enabled: true,
    provider: 'akshare',
    topic: hotspot.topic,
    name: hotspot.name || hotspot.topic,
    canonicalTopic: hotspot.topic,
    summaryDetail: {
      heatScore: hotspot.heatScore,
      stage: hotspot.stage || hotspot.state,
      leaders,
    },
    route: [{ title: 'current fermentation', description: descriptionParts.join('; ') }],
    stocks,
    stockCount: hotspot.sampleStockCount ?? stocks.length,
    sourceErrors: hotspot.sourceErrors,
    qualityStatus: hotspot.qualityStatus,
    missingFields: hotspot.missingFields,
    fallbackUsed: hotspot.fallbackUsed,
    stale: hotspot.stale,
    staleAgeHours: hotspot.staleAgeHours,
    cacheUsed: hotspot.cacheUsed,
    cachedAt: hotspot.cachedAt,
  };
};

const stripHotspotSearchAugmentation = (detail: ScreeningHotspotDetail): ScreeningHotspotDetail => {
  const baseDetail: ScreeningHotspotDetail = {
    ...detail,
    route: (detail.route || []).filter((item) => !item.searchResult),
    ...(detail.timeline
      ? { timeline: detail.timeline.filter((item) => !item.searchResult) }
      : {}),
  };
  delete baseDetail.newsSearchRequested;
  delete baseDetail.newsSearchStatus;
  return baseDetail;
};

const stripHotspotSearchAugmentationByTopic = (
  details: Record<string, ScreeningHotspotDetail>,
) => Object.fromEntries(
  Object.entries(details).map(([topic, detail]) => [topic, stripHotspotSearchAugmentation(detail)]),
) as Record<string, ScreeningHotspotDetail>;

const getHotspotRouteItems = (detail: ScreeningHotspotDetail) => {
  const route = detail.route || [];
  if (route.length > 0) {
    return route;
  }
  return detail.timeline || [];
};

const formatHotspotMetric = (language: UiLanguage, value: unknown, digits = 1) => {
  const formatted = formatNumber(value, digits);
  return formatted === '-' ? SCREENING_TEXT[language].watching : formatted;
};

const getHotspotLeadersText = (language: UiLanguage, item: ScreeningHotspot) => {
  const leaders = (item.leaders || []).map((value) => String(value).trim()).filter(Boolean);
  if (leaders.length > 0) {
    return leaders.slice(0, 2).join(language === 'en' ? ', ' : '、');
  }
  return SCREENING_TEXT[language].watching;
};

const getHotspotSampleText = (language: UiLanguage, item: ScreeningHotspot) => {
  if (item.sampleStockCount == null || Number.isNaN(Number(item.sampleStockCount))) {
    return SCREENING_TEXT[language].watchingStocks;
  }
  return screeningText(language, 'coveredStocks', { count: item.sampleStockCount });
};

const formatStockChangeText = (language: UiLanguage, value: unknown) => {
  const formatted = formatNumber(value);
  return formatted === '-' ? SCREENING_TEXT[language].noQuote : `${formatted}%`;
};

const formatHotspotUpdatedAt = (language: UiLanguage, value: string | null) => {
  if (!value) {
    return SCREENING_TEXT[language].needsRefresh;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
};

const getHotspotStrength = (language: UiLanguage, item: ScreeningHotspot, index: number) => {
  const heat = Number(item.heatScore ?? 0);
  const changePct = Number(item.changePct ?? 0);
  if (index === 0 || heat >= 90 || changePct >= 8) {
    return { label: SCREENING_TEXT[language].leadingStrength, className: 'bg-red-500/10 text-red-500' };
  }
  if (heat >= 80 || changePct >= 5) {
    return { label: SCREENING_TEXT[language].strong, className: 'bg-blue-500/10 text-blue-500' };
  }
  return { label: SCREENING_TEXT[language].moderateStrength, className: 'bg-cyan/10 text-cyan' };
};

const HOTSPOT_ICON_RULES: Array<{
  pattern: RegExp;
  icon: React.ComponentType<{ className?: string }>;
  className: string;
}> = [
  { pattern: /金|银|铜|铝|铅|锌|钼|钴|镍|贵金属|矿|有色/, icon: Pickaxe, className: 'bg-orange-500/10 text-orange-500' },
  { pattern: /黄金|珠宝/, icon: Gem, className: 'bg-amber-500/10 text-amber-500' },
  { pattern: /油|气|能源|煤/, icon: Droplet, className: 'bg-yellow-700/10 text-yellow-700' },
  { pattern: /金融|券商|银行|保险|资本/, icon: Landmark, className: 'bg-orange-500/10 text-orange-500' },
  { pattern: /航空|机场|航天|运输/, icon: Plane, className: 'bg-blue-500/10 text-blue-500' },
  { pattern: /林业|农业|种植/, icon: Trees, className: 'bg-emerald-500/10 text-emerald-500' },
  { pattern: /医疗|诊断|卫生|医药/, icon: Stethoscope, className: 'bg-teal-500/10 text-teal-500' },
  { pattern: /食品|餐饮|酒/, icon: Utensils, className: 'bg-violet-500/10 text-violet-500' },
  { pattern: /工业|制造|修理|机械|设备/, icon: Wrench, className: 'bg-blue-500/10 text-blue-500' },
  { pattern: /租赁|地产|建筑/, icon: Building2, className: 'bg-emerald-500/10 text-emerald-500' },
  { pattern: /电|芯片|算力|AI|机器人/, icon: Factory, className: 'bg-indigo-500/10 text-indigo-500' },
  { pattern: /保险|安全/, icon: Shield, className: 'bg-blue-500/10 text-blue-500' },
];

const getHotspotIcon = (topic: string) => {
  const match = HOTSPOT_ICON_RULES.find((rule) => rule.pattern.test(topic));
  return match || { icon: Activity, className: 'bg-cyan/10 text-cyan' };
};

const MiniSparkline: React.FC<{ score?: number | null; selected?: boolean }> = ({ score, selected }) => {
  const normalizedScore = Number.isFinite(Number(score)) ? Math.max(0, Math.min(100, Number(score))) : 65;
  const lift = Math.max(0, Math.min(16, normalizedScore / 7));
  const path = `M2 35 C12 ${32 - lift / 4}, 16 ${34 - lift / 2}, 24 ${28 - lift / 3} S38 ${29 - lift}, 46 ${23 - lift / 2} S62 ${24 - lift}, 72 ${16 - lift / 3} S86 ${15 - lift}, 94 ${7}`;
  return (
    <svg className="h-8 w-20" viewBox="0 0 96 40" aria-hidden="true">
      <path d={`${path} L94 40 L2 40 Z`} fill={selected ? 'rgba(249,115,22,0.14)' : 'rgba(59,130,246,0.12)'} />
      <path d={path} fill="none" stroke={selected ? '#f97316' : '#3b82f6'} strokeLinecap="round" strokeWidth="2" />
    </svg>
  );
};


// Store message renderers rather than translated strings. Async callbacks remain
// independent of UI language, so toggling it never restarts requests or polling.
type ScreeningMessage = (language: UiLanguage) => string;
const useScreeningMessage = (language: UiLanguage, initial?: ScreeningMessage) => {
  const [message, setMessage] = useState<{ render: ScreeningMessage } | null>(() => initial ? { render: initial } : null);
  const update = useCallback((next: ScreeningMessage | null) => {
    setMessage(next ? { render: next } : null);
  }, []);
  return [message?.render(language) || '', update] as const;
};

const formatScreeningApiError = (language: UiLanguage, error: unknown, fallback: string): string => {
  if (language === 'zh') return toApiErrorMessage(error, fallback);
  const parsed = getParsedApiError(error);
  if (parsed.code === 'screening_screen_task_not_found') return SCREENING_TEXT[language].taskMissing;
  if (parsed.code === 'screening_unavailable') return SCREENING_TEXT[language].screeningNotReady;
  if (parsed.code === 'screening_screen_failed') return SCREENING_TEXT[language].screeningRequestFailed;
  if (parsed.category === 'upstream_timeout') return SCREENING_TEXT[language].requestTimeout;
  if (parsed.category === 'upstream_network' || parsed.category === 'local_connection_failed') {
    return SCREENING_TEXT[language].requestNetwork;
  }
  // Unknown server details are data, not translation keys. Preserve them.
  return parsed.rawMessage ? `${fallback}: ${parsed.rawMessage}` : fallback;
};

const formatScreenTaskMessage = (language: UiLanguage, message: string | null | undefined, status: string) => {
  if (language === 'zh') return message || '';
  // Built-in task progress strings have no language field in the API. Match only
  // known messages; provider-written messages remain untouched.
  const progress: Record<string, string> = {
    '选股任务已提交': 'Screening task submitted',
    '任务执行中': 'Screening is in progress',
    '正在执行选股，外部数据源较慢时会持续后台运行': 'Screening will continue in the background while data sources respond',
    '正在补充入选股票的新闻与事件': 'Loading news and events for selected stocks',
    '任务执行完成': 'Task completed',
    '正在读取全市场快照': 'Loading the market snapshot',
    '正在补充候选行情与基本面': 'Enriching candidate quotes and fundamentals',
    '正在执行 LLM 候选重排': 'Reranking candidates with the LLM',
    '正在执行最终评分与风险校验': 'Applying final scores and risk checks',
    '选股核心流程完成': 'Core screening completed',
  };
  if (message && Object.hasOwn(progress, message)) return progress[message];
  const filtered = message?.match(/^快照筛选完成，保留 (\d+) 条候选$/);
  if (filtered) return `Snapshot filtering completed; ${filtered[1]} candidates retained`;
  const preparing = message?.match(/^选股已完成，正在整理 (\d+) 条候选$/);
  if (preparing) return `Screening complete. Preparing ${preparing[1]} candidates.`;
  if (message) return message;
  return screeningText(language, status === 'pending' ? 'taskPending' : status === 'processing' ? 'taskProcessing' : 'completed');
};

const StockScreeningPage: React.FC = () => {
  const { language } = useUiLanguage();
  const navigate = useNavigate();
  const [restoredTask] = useState<PersistedScreenTask | null>(() => readPersistedScreenTask());
  const [statusState, setStatusState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [statusError, setStatusError] = useScreeningMessage(language);
  const [statusAttempt, setStatusAttempt] = useState(0);
  const [enabled, setEnabled] = useState(false);
  const [available, setAvailable] = useState(false);
  const [market, setMarket] = useState(restoredTask?.market || 'cn');
  const [strategy, setStrategy] = useState(restoredTask?.strategy || 'dual_low');
  const [strategies, setStrategies] = useState<ScreeningStrategy[]>([]);
  const [maxResults, setMaxResults] = useState(restoredTask?.maxResults || 3);
  const [candidates, setCandidates] = useState<ScreeningCandidate[]>([]);
  const [hotspots, setHotspots] = useState<ScreeningHotspot[]>([]);
  const [hotspotsUpdatedAt, setHotspotsUpdatedAt] = useState<string | null>(null);
  const [hotspotsExpanded, setHotspotsExpanded] = useState(false);
  const [selectedHotspotTopic, setSelectedHotspotTopic] = useState<string | null>(null);
  const selectedHotspotTopicRef = useRef<string | null>(null);
  const hotspotDetailRequestIdRef = useRef(0);
  const hotspotDetailsByTopicRef = useRef<Record<string, ScreeningHotspotDetail>>({});
  const historyRunRequestIdRef = useRef(0);
  const [hotspotDetail, setHotspotDetail] = useState<ScreeningHotspotDetail | null>(null);
  const [loadingHotspotDetail, setLoadingHotspotDetail] = useState(false);
  const [searchingHotspotNews, setSearchingHotspotNews] = useState(false);
  const [hotspotDetailError, setHotspotDetailError] = useScreeningMessage(language);
  const [loadingHotspots, setLoadingHotspots] = useState(false);
  const [hotspotError, setHotspotError] = useScreeningMessage(language);
  const [screenMeta, setScreenMeta] = useState<ScreeningScreenResponse | null>(null);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(restoredTask?.taskId));
  const [enabling, setEnabling] = useState(false);
  const [historyRuns, setHistoryRuns] = useState<ScreeningRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useScreeningMessage(language);
  const [restoreResolved, setRestoreResolved] = useState(() => !restoredTask?.runId);
  // 标记当前 strategy 是否来自历史 run（刷新自动恢复或手动历史选择）的上下文同步。
  // 为 true 时 loadStrategies 跳过“不在列表则回退第一项”的归一化，
  // 防止迟到的 /strategies 响应把历史上下文改写回默认策略。
  const historyContextStrategyRef = useRef(false);
  const [loadingStrategies, setLoadingStrategies] = useState(false);
  const [error, setError] = useScreeningMessage(language);
  const [strategyLoadError, setStrategyLoadError] = useScreeningMessage(language);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(restoredTask?.taskId ?? null);
  const [taskProgress, setTaskProgress] = useState(restoredTask?.taskId ? 10 : 0);
  const [taskMessage, setTaskMessage] = useScreeningMessage(language, (language) => restoredTask?.taskId ? SCREENING_TEXT[language].restoringTask : '');

  const copy = SCREENING_TEXT[language];
  const selectedStrategy = useMemo(() => strategies.find((item) => item.id === strategy), [strategies, strategy]);
  const selectedStrategyTitle = selectedStrategy?.name || selectedStrategy?.title || copy.customStrategy;
  const selectedStrategyTag = formatStrategyCategory(language,
    selectedStrategy?.category || selectedStrategy?.tag || selectedStrategy?.tags?.[0],
  );
  const displayedStrategy = selectedStrategy ? selectedStrategyTitle : screeningText(language, 'customStrategyValue', { strategy });
  const screenMessages = useMemo(() => getScreenMessages(language, screenMeta), [language, screenMeta]);
  const selectedHotspot = useMemo(
    () => hotspots.find((item) => item.topic === selectedHotspotTopic),
    [hotspots, selectedHotspotTopic],
  );
  const factorRanking = Boolean(screenMeta && (screenMeta.rankingMode === 'factor' || screenMeta.llmRanked === false));
  const llmFailed = Boolean(factorRanking && screenMeta?.llmFailureReason);
  const alertMessages = llmFailed
    ? screenMessages.length > 0
      ? screenMessages
      : [copy.factorFallback]
    : screenMessages;
  const isScreeningEnabled = statusState === 'ready' && enabled && available;
  const statusText = statusState === 'loading'
    ? copy.checkingStatus
    : statusState === 'error'
      ? copy.unknownStatus
      : !enabled
        ? copy.disabled
        : available ? copy.enabled : copy.screeningUnavailable;

  const applyScreenResult = useCallback((result: ScreeningScreenResponse) => {
    const nextCandidates = result.candidates || [];
    setScreenMeta(result);
    setCandidates(nextCandidates);
    setExpandedCode(nextCandidates[0]?.code ?? null);
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const result = await screeningApi.getHistory({ limit: 10 });
      setHistoryRuns(result.runs || []);
    } catch (err) {
      setHistoryError((language) => formatScreeningApiError(language, err, SCREENING_TEXT[language].historyLoadFailed));
    } finally {
      setHistoryLoading(false);
    }
  }, [setHistoryError]);

  const handleHistoryRunSelect = useCallback(async (runId: string) => {
    // 竞态防护：快速切换历史条目时，只应用最新一次请求的响应
    const requestId = historyRunRequestIdRef.current + 1;
    historyRunRequestIdRef.current = requestId;
    const isCurrentRequest = () => historyRunRequestIdRef.current === requestId;
    // 与运行中的选股任务互斥：手动选择历史记录后，暂停/取消后台任务轮询，
    // 避免任务完成后把当前任务的候选结果回写到历史上下文中。
    setActiveTaskId(null);
    setHistoryError(null);
    setLoading(true);
    try {
      const detail = await screeningApi.getRun(runId);
      if (!isCurrentRequest()) {
        return;
      }
      if (detail?.result) {
        applyScreenResult(detail.result);
        historyContextStrategyRef.current = true;
        // 同步持久化恢复指针：刷新后应恢复用户刚选中的历史 run，
        // 而不是停留在更早的 task/run。历史详情不携带 taskId，以 runId
        // 作为占位——正常路径刷新走 getRun(runId) 恢复、不会触发轮询；
        // 若该 run 恢复失败，占位轮询会命中不可恢复错误并清理过期指针。
        persistScreenTask({
          taskId: runId,
          runId,
          market: detail.market || market,
          strategy: detail.strategy || strategy,
          maxResults,
        });
        // 同步历史 run 的策略与市场上下文，确保结果区文案和后续深度分析
        // 使用该历史 run 对应的 strategy/market，而不是当前表单的选择
        if (detail.strategy) {
          setStrategy(detail.strategy);
        }
        if (detail.market) {
          setMarket(detail.market);
        }
        setError(null);
        setTaskProgress(100);
        setTaskMessage((language) => SCREENING_TEXT[language].historyLoaded);
      } else {
        setError((language) => SCREENING_TEXT[language].historyMissing);
      }
    } catch (err) {
      if (!isCurrentRequest()) {
        return;
      }
      setError((language) => formatScreeningApiError(language, err, SCREENING_TEXT[language].historyResultFailed));
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [setError, setHistoryError, setTaskMessage, applyScreenResult, market, maxResults, strategy]);

  const clearScreeningResults = () => {
    setCandidates([]);
    setScreenMeta(null);
    setExpandedCode(null);
  };

  const loadHotspotDetail = useCallback(async (
    topic: string,
    options: { refresh?: boolean; includeSearch?: boolean } = {},
  ) => {
    if (!topic) {
      return;
    }
    const cachedDetail = !options.refresh && !options.includeSearch
      ? hotspotDetailsByTopicRef.current[topic]
      : null;
    if (cachedDetail) {
      setHotspotDetail(cachedDetail);
      setHotspotDetailError(null);
      setLoadingHotspotDetail(false);
      return;
    }
    const requestId = hotspotDetailRequestIdRef.current + 1;
    hotspotDetailRequestIdRef.current = requestId;
    const isCurrentRequest = () => hotspotDetailRequestIdRef.current === requestId;
    const canApplyRequest = () => isCurrentRequest() && selectedHotspotTopicRef.current === topic;
    setLoadingHotspotDetail(!options.includeSearch);
    setSearchingHotspotNews(Boolean(options.includeSearch));
    setHotspotDetail((currentDetail) => (currentDetail?.topic === topic ? currentDetail : null));
    setHotspotDetailError(null);
    try {
      const detail = await screeningApi.getHotspotDetail({
        topic,
        provider: 'akshare',
        refresh: options.refresh ?? false,
        ...(options.includeSearch ? { includeSearch: true } : {}),
      });
      if (!canApplyRequest()) {
        return;
      }
      const cacheableDetail = options.includeSearch
        ? hotspotDetailsByTopicRef.current[topic] || stripHotspotSearchAugmentation(detail)
        : stripHotspotSearchAugmentation(detail);
      hotspotDetailsByTopicRef.current = {
        ...hotspotDetailsByTopicRef.current,
        [topic]: cacheableDetail,
      };
      setHotspotDetail(options.includeSearch ? detail : cacheableDetail);
      if (options.includeSearch && detail.newsSearchStatus === 'no_results') {
        setHotspotDetailError((language) => SCREENING_TEXT[language].noSearchResults);
      } else if (options.includeSearch && detail.newsSearchStatus !== 'available') {
        setHotspotDetailError((language) => SCREENING_TEXT[language].searchFailed);
      }
    } catch (err) {
      if (!canApplyRequest()) {
        return;
      }
      if (!options.includeSearch) {
        setHotspotDetail(null);
      }
      setHotspotDetailError((language) => formatScreeningApiError(language,
        err,
        options.includeSearch ? SCREENING_TEXT[language].searchFailed : SCREENING_TEXT[language].detailFailed,
      ));
    } finally {
      if (isCurrentRequest()) {
        setLoadingHotspotDetail(false);
        setSearchingHotspotNews(false);
      }
    }
  }, [setHotspotDetailError]);

  const loadStrategies = useCallback(async () => {
    setLoadingStrategies(true);
    try {
      setStrategyLoadError(null);
      const result = await screeningApi.getStrategies();
      const loadedStrategies = result.strategies || [];
      setStrategies(loadedStrategies);
      // 历史 run 的自定义/下线策略不在当前列表属预期行为，不做“回退第一项”的归一化，
      // 否则迟到的策略列表会把刚恢复好的上下文改写回默认策略。
      if (loadedStrategies.length > 0 && !historyContextStrategyRef.current) {
        setStrategy((currentStrategy) =>
          loadedStrategies.some((item) => item.id === currentStrategy) ? currentStrategy : loadedStrategies[0].id,
        );
      }
    } catch (err) {
      setStrategies([]);
      setStrategyLoadError((language) => language === 'zh' && err instanceof Error ? err.message : formatScreeningApiError(language, err, SCREENING_TEXT[language].strategiesFailed));
    } finally {
      setLoadingStrategies(false);
    }
  }, [setStrategyLoadError]);

  const loadHotspots = useCallback(async (refresh = false) => {
    setLoadingHotspots(true);
    setHotspotError(null);
    try {
      const result = await screeningApi.getHotspots({ provider: 'akshare', top: 12, refresh });
      const nextHotspots = result.hotspots || [];
      const nextDetails = stripHotspotSearchAugmentationByTopic(result.details || {});
      hotspotDetailsByTopicRef.current = {
        ...hotspotDetailsByTopicRef.current,
        ...nextDetails,
      };
      const currentTopic = selectedHotspotTopicRef.current;
      const retainedTopic = Boolean(currentTopic && nextHotspots.some((item) => item.topic === currentTopic));
      const nextTopic = retainedTopic ? currentTopic : null;
      setHotspots(nextHotspots);
      setHotspotsUpdatedAt(result.cachedAt || (nextHotspots.length > 0 ? new Date().toISOString() : null));
      setSelectedHotspotTopic(nextTopic);
      selectedHotspotTopicRef.current = nextTopic;
      setHotspotDetailError(null);
      if (nextTopic && nextDetails[nextTopic]) {
        setHotspotDetail(nextDetails[nextTopic]);
        setLoadingHotspotDetail(false);
      } else if (!retainedTopic) {
        setHotspotDetail(null);
      } else if (refresh && nextTopic) {
        // A refreshed list and a retained detail must describe the same source
        // snapshot. The list endpoint intentionally omits details by default,
        // so explicitly bypass the detail cache for the retained topic.
        await loadHotspotDetail(nextTopic, { refresh: true });
      }
      if (nextHotspots.length === 0) {
        setHotspotError((language) => formatHotspotEmptyMessage(language, result));
      }
    } catch (err) {
      setHotspotError((language) => formatScreeningApiError(language, err, SCREENING_TEXT[language].hotspotsFailed));
    } finally {
      setLoadingHotspots(false);
    }
  }, [setHotspotDetailError, setHotspotError, loadHotspotDetail]);

  const handleHotspotSelect = useCallback((topic: string) => {
    selectedHotspotTopicRef.current = topic;
    setSelectedHotspotTopic(topic);
    const cachedDetail = hotspotDetailsByTopicRef.current[topic];
    if (cachedDetail) {
      setHotspotDetail(cachedDetail);
      setHotspotDetailError(null);
      setLoadingHotspotDetail(false);
    } else {
      const preview = hotspots.find((item) => item.topic === topic);
      setHotspotDetail((currentDetail) => (
        currentDetail?.topic === topic ? currentDetail : preview ? buildHotspotPreviewDetail(preview) : null
      ));
    }
  }, [setHotspotDetailError, hotspots]);

  const toggleHotspotsExpanded = useCallback(() => {
    setHotspotsExpanded((expanded) => {
      const nextExpanded = !expanded;
      if (!nextExpanded) {
        selectedHotspotTopicRef.current = null;
        setSelectedHotspotTopic(null);
        setHotspotDetail(null);
        setHotspotDetailError(null);
      }
      return nextExpanded;
    });
  }, [setHotspotDetailError]);

  const handleAnalyzeHotspotStock = useCallback((stock: ScreeningHotspotDetail['stocks'][number]) => {
    const stockCode = String(stock.code || '').trim();
    if (!stockCode) {
      return;
    }
    const stockName = String(stock.name || stockCode).trim();
    navigate('/', {
      state: {
        stockCode,
        stockName,
        autoAnalyze: true,
        selectionSource: 'screening_hotspot',
        skills: ['hot_theme'],
      },
    });
  }, [navigate]);

  const handleAnalyzeCandidate = useCallback((candidate: ScreeningCandidate) => {
    const stockCode = String(candidate.code || '').trim();
    if (!stockCode) {
      return;
    }
    const stockName = String(candidate.name || stockCode).trim();
    const analysisSkills = (selectedStrategy?.analysisSkills || []).filter(Boolean);
    navigate('/', {
      state: {
        stockCode,
        stockName,
        autoAnalyze: true,
        selectionSource: 'screening_result',
        ...(analysisSkills.length > 0 ? { skills: analysisSkills } : {}),
      },
    });
  }, [navigate, selectedStrategy]);

  useEffect(() => {
    selectedHotspotTopicRef.current = selectedHotspotTopic;
  }, [selectedHotspotTopic]);

  useEffect(() => {
    if (!selectedHotspotTopic) {
      return;
    }
    void loadHotspotDetail(selectedHotspotTopic);
  }, [loadHotspotDetail, selectedHotspotTopic]);

  useEffect(() => {
    let active = true;
    screeningApi
      .getStatus()
      .then((status) => {
        if (!active) {
          return;
        }
        setEnabled(status.enabled);
        setAvailable(status.available);
        setStatusState('ready');
        if (status.enabled && status.available) {
          void loadStrategies();
          void loadHotspots(false);
          void loadHistory();
        }
      })
      .catch((err) => {
        if (active) {
          setStatusError((language) => formatScreeningApiError(language, err, SCREENING_TEXT[language].statusFailed));
          setStatusState('error');
        }
      });
    return () => {
      active = false;
    };
  }, [loadHistory, loadHotspots, loadStrategies, setStatusError, statusAttempt]);

  // 刷新后优先从 history API 按 run_id 恢复结果；恢复失败再回退到 task 轮询
  useEffect(() => {
    const runId = restoredTask?.runId;
    if (!runId) {
      setRestoreResolved(true);
      return undefined;
    }
    let active = true;
    setLoading(true);
    // 记录自动恢复的请求基准：若在自动恢复返回前用户手动点开了历史记录
    // （historyRunRequestIdRef 被 handleHistoryRunSelect 递增），则放弃本次自动恢复响应，
    // 避免较晚返回的自动恢复把页面切回旧 run，覆盖用户最新一次的历史选择。
    const restoreRequestBase = historyRunRequestIdRef.current;
    screeningApi
      .getRun(runId)
      .then((detail) => {
        if (!active || historyRunRequestIdRef.current !== restoreRequestBase) {
          return;
        }
        if (detail?.result) {
          applyScreenResult(detail.result);
          historyContextStrategyRef.current = true;
          // 同步恢复该历史 run 的策略与市场上下文，避免结果区展示和
          // 深度分析沿用当前表单策略（与 handleHistoryRunSelect 一致）
          if (detail.strategy) {
            setStrategy(detail.strategy);
          }
          if (detail.market) {
            setMarket(detail.market);
          }
          setError(null);
          setTaskProgress(100);
          setTaskMessage((language) => SCREENING_TEXT[language].historyRestored);
          setActiveTaskId(null);
        }
      })
      .catch(() => {
        // 历史记录恢复失败（run 不存在或服务重启），回退到 task 轮询；
        // 若用户已手动选择了历史记录，则不再回退，保持用户的选择。
        if (active && historyRunRequestIdRef.current === restoreRequestBase) {
          setActiveTaskId(restoredTask?.taskId ?? null);
        }
      })
      .finally(() => {
        // 无论结果是否过期都要解除自动恢复门闩，否则新任务的轮询会被阻塞到旧请求超时。
        if (active) {
          setRestoreResolved(true);
        }
        // 过期的自动恢复不得触碰共享 loading：用户手动选择的历史详情请求可能仍在飞行，
        // 提前清掉会重新放开“运行选股”入口，随后迟到的历史响应会覆盖新任务状态。
        if (active && historyRunRequestIdRef.current === restoreRequestBase) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [applyScreenResult, restoredTask, setError, setTaskMessage]);

  useEffect(() => {
    if (!activeTaskId || !restoreResolved) {
      return undefined;
    }

    const pollingTaskId = activeTaskId;
    let active = true;
    let timer: ReturnType<typeof window.setTimeout> | undefined;

    function finishTask() {
      setActiveTaskId(null);
      setLoading(false);
    }

    function applyTaskStatus(task: ScreeningScreenTaskStatus) {
      const nextProgress = Number(task.progress ?? 0);
      setTaskProgress(Number.isFinite(nextProgress) ? nextProgress : 0);
      setTaskMessage((language) => formatScreenTaskMessage(language, task.message, task.status));

      if (task.status === 'completed') {
        if (task.result) {
          applyScreenResult(task.result);
          setError(null);
          // 持久化 runId：刷新后优先从 history API 恢复结果，而非依赖内存 task
          const completedRunId = task.result.runId || screenMeta?.runId;
          if (completedRunId) {
            persistScreenTask({
              taskId: pollingTaskId,
              runId: completedRunId,
              market,
              strategy,
              maxResults,
            });
          }
        } else {
          setError((language) => SCREENING_TEXT[language].completedWithoutResult);
          setCandidates([]);
          setScreenMeta(null);
        }
        finishTask();
        return;
      }

      if (task.status === 'failed') {
        setCandidates([]);
        setScreenMeta(null);
        setExpandedCode(null);
        setError((language) => formatScreenTaskFailure(language, task.error || task.message));
        clearPersistedScreenTask();
        finishTask();
        return;
      }

      if (isRunningScreenTask(task.status)) {
        setLoading(true);
        timer = window.setTimeout(pollTask, SCREEN_TASK_POLL_INTERVAL_MS);
        return;
      }

      setError((language) => screeningText(language, 'unknownTaskStatus', { status: task.status || 'unknown' }));
      clearPersistedScreenTask();
      finishTask();
    }

    async function pollTask() {
      try {
        const task = await screeningApi.getScreenTask(pollingTaskId);
        if (!active) {
          return;
        }
        applyTaskStatus(task);
      } catch (err) {
        if (!active) {
          return;
        }
        const parsedError = getParsedApiError(err);
        if (isUnrecoverableScreenTaskError(parsedError)) {
          setError((language) => formatScreeningApiError(language, parsedError, SCREENING_TEXT[language].resubmitTask));
          setCandidates([]);
          setScreenMeta(null);
          clearPersistedScreenTask();
          finishTask();
          return;
        }
        setError((language) => formatRecoverableScreenTaskPollingError(language, parsedError));
        setLoading(true);
        timer = window.setTimeout(pollTask, SCREEN_TASK_POLL_INTERVAL_MS);
      }
    }

    void pollTask();

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [activeTaskId, applyScreenResult, restoreResolved, market, strategy, maxResults, screenMeta?.runId, setError, setTaskMessage]);

  const handleEnable = async () => {
    setEnabling(true);
    setError(null);
    try {
      await screeningApi.enable();
      setEnabled(true);
      setAvailable(true);
      await loadStrategies();
    } catch (err) {
      try {
        const status = await screeningApi.getStatus();
        setEnabled(status.enabled);
        setAvailable(status.available);
        setStatusState('ready');
      } catch (statusErr) {
        setStatusError((language) => formatScreeningApiError(language, statusErr, SCREENING_TEXT[language].statusFailed));
        setStatusState('error');
      }
      setError((language) => language === 'zh' && err instanceof Error ? err.message : formatScreeningApiError(language, err, SCREENING_TEXT[language].enableFailed));
    } finally {
      setEnabling(false);
    }
  };

  const handleStrategyChange = (nextStrategy: string) => {
    if (nextStrategy !== strategy) {
      clearScreeningResults();
    }
    setStrategy(nextStrategy);
  };

  const handleMarketChange = (nextMarket: string) => {
    if (nextMarket !== market) {
      clearScreeningResults();
    }
    setMarket(nextMarket);
  };

  const handleMaxResultsChange = (nextMaxResults: number) => {
    if (nextMaxResults !== maxResults) {
      clearScreeningResults();
    }
    setMaxResults(nextMaxResults);
  };

  const handleSubmit = async () => {
    // 新任务提交即代表用户放弃当前历史/恢复上下文：
    // 递增请求代号作废飞行中的历史详情与自动恢复响应；
    // 解除自动恢复门闩，保证刚提交的任务轮询立即可启动。
    historyRunRequestIdRef.current += 1;
    setRestoreResolved(true);
    setLoading(true);
    setError(null);
    setScreenMeta(null);
    setTaskProgress(0);
    setTaskMessage((language) => SCREENING_TEXT[language].submitting);
    try {
      const task = await screeningApi.startScreen({ market, strategy, maxResults });
      persistScreenTask({
        taskId: task.taskId,
        market,
        strategy,
        maxResults,
      });
      setActiveTaskId(task.taskId);
      setTaskProgress(0);
      setTaskMessage((language) => formatScreenTaskMessage(language, task.message, 'pending') || SCREENING_TEXT[language].submitted);
    } catch (err) {
      setCandidates([]);
      setLoading(false);
      setError((language) => formatScreeningApiError(language, err, SCREENING_TEXT[language].submitFailed));
    }
  };

  return (
    <AppPage className="min-w-0 max-w-6xl space-y-6 pb-12 pt-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid h-7 w-7 place-items-center rounded-full border-2 border-cyan text-cyan shadow-[0_0_24px_hsl(var(--primary)/0.18)]">
            <PlusCircle className="h-4 w-4" />
          </span>
          <h1 className="text-2xl font-bold tracking-normal text-foreground">{copy.title}</h1>
        </div>

        <div className="inline-flex w-fit items-center gap-2 rounded-2xl border border-border/70 bg-card/80 px-4 py-2 text-sm shadow-soft-card">
          <span className={`h-2.5 w-2.5 rounded-full ${isScreeningEnabled ? 'bg-success' : 'bg-warning'}`} />
          <span className="font-medium text-secondary-text">{statusText}</span>
        </div>
      </div>

      {statusState === 'loading' ? (
        <InlineAlert variant="info" message={copy.loadingConfig} />
      ) : null}

      {statusState === 'error' ? (
        <InlineAlert
          variant="warning"
          title={copy.statusLoadFailed}
          message={statusError}
          action={
            <Button size="sm" onClick={() => {
              setStatusState('loading');
              setStatusError(null);
              setStatusAttempt((attempt) => attempt + 1);
            }}>
              {copy.retry}
            </Button>
          }
        />
      ) : null}

      {statusState === 'ready' && !enabled ? (
        <InlineAlert
          variant="info"
          title={copy.disabled}
          message={copy.enableHint}
          action={
            <Button size="sm" isLoading={enabling} loadingText={copy.enabling} onClick={() => void handleEnable()}>
              {copy.enable}
            </Button>
          }
        />
      ) : null}

      {statusState === 'ready' && enabled && !available ? (
        <InlineAlert
          variant="warning"
          title={copy.screeningUnavailable}
          message={copy.unavailableHint}
        />
      ) : null}

      {error ? <InlineAlert variant="danger" title={copy.requestFailed} message={error} /> : null}

      <section className="rounded-2xl border border-border/80 bg-card/95 p-4 shadow-soft-card">
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-orange-500/10 text-orange-500 shadow-[0_10px_30px_rgba(249,115,22,0.16)]">
              <Flame className="h-5 w-5" />
            </span>
            <h2 className="text-lg font-bold tracking-normal text-foreground">{copy.hotspots}</h2>
          </div>
          <div className="flex flex-col items-start gap-2 lg:items-end">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={!isScreeningEnabled}
                onClick={toggleHotspotsExpanded}
              >
                <Bookmark className="h-4 w-4" />
                {hotspotsExpanded ? copy.collapseHotspots : screeningText(language, 'expandHotspots', { count: hotspots.length ? (language === 'en' ? ` (${hotspots.length})` : `（${hotspots.length}）`) : '' })}
                <ChevronDown className={`h-4 w-4 transition-transform ${hotspotsExpanded ? 'rotate-180' : ''}`} />
              </Button>
              {hotspotsExpanded ? (
              <Button
                size="sm"
                variant="secondary"
                isLoading={loadingHotspots}
                loadingText={copy.refreshing}
                disabled={!isScreeningEnabled || loadingHotspots}
                onClick={() => void loadHotspots(true)}
              >
                <RefreshCw className="h-4 w-4" />
                {copy.refreshHotspots}
              </Button>
              ) : null}
            </div>
            {hotspotsUpdatedAt ? (
              <p className="text-xs text-secondary-text">{copy.updatedAt} {formatHotspotUpdatedAt(language, hotspotsUpdatedAt)}</p>
            ) : null}
          </div>
        </div>

        {hotspotsExpanded && hotspotError ? (
          <p className="mb-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
            {hotspotError}
          </p>
        ) : null}

        {!hotspotsExpanded ? null : hotspots.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-surface/70 px-4 py-6 text-sm text-secondary-text">
            {copy.emptyHotspots}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {hotspots.map((item, index) => {
              const selected = selectedHotspotTopic === item.topic;
              const strength = getHotspotStrength(language, item, index);
              const iconMeta = getHotspotIcon(item.name || item.topic);
              const Icon = iconMeta.icon;
              return (
              <button
                key={`${item.topic}-${item.rank ?? ''}`}
                className={`group relative min-h-[116px] overflow-hidden rounded-xl border px-3 py-3 text-left transition-all ${
                  selected
                    ? 'border-orange-400 bg-gradient-to-br from-orange-500/10 via-card to-card shadow-[0_0_0_1px_rgba(249,115,22,0.16),0_18px_44px_rgba(249,115,22,0.14)]'
                    : 'border-border/80 bg-card hover:-translate-y-0.5 hover:border-orange-300/70 hover:shadow-soft-card'
                }`}
                type="button"
                onClick={() => handleHotspotSelect(item.topic)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <span
                      className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ${
                        index < 3 ? 'bg-orange-500 text-white shadow-[0_8px_24px_rgba(249,115,22,0.24)]' : 'bg-surface text-secondary-text'
                      }`}
                    >
                      {index + 1}
                    </span>
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${iconMeta.className}`}>
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold text-foreground">{item.name || item.topic}</p>
                      <span className={`mt-1 inline-flex rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${strength.className}`}>
                        {strength.label}
                      </span>
                    </div>
                  </div>
                  <span className="shrink-0 text-2xl font-black leading-none text-orange-500">
                    {formatNumber(item.heatScore, 0)}
                  </span>
                </div>
                <div className="mt-4 grid max-w-[72%] gap-1 text-[11px] text-secondary-text">
                  <span>{copy.change} <strong className="font-semibold text-foreground">{formatHotspotMetric(language, item.changePct)}%</strong></span>
                  <span>{copy.trend} <strong className="font-semibold text-foreground">{formatHotspotMetric(language, item.trendScore)}</strong> {copy.persistenceLabel} <strong className="font-semibold text-foreground">{formatHotspotMetric(language, item.persistenceScore)}</strong></span>
                  <span>{getHotspotSampleText(language, item)} {copy.leaderLabel} {getHotspotLeadersText(language, item)}</span>
                </div>
                <div className="absolute bottom-3 right-3 opacity-95 transition-transform group-hover:scale-105">
                  <MiniSparkline score={item.heatScore} selected={selected} />
                </div>
              </button>
              );
            })}
          </div>
        )}

        {hotspotsExpanded && selectedHotspotTopic ? (
          <div className="mt-4 rounded-xl border border-border/80 bg-surface/80 p-4">
            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  {hotspotDetail?.name || selectedHotspotTopic}
                </h3>
                <p className="mt-1 text-xs leading-5 text-secondary-text">
                  {hotspotDetail
                    ? getHotspotSummaryText(language, hotspotDetail, selectedHotspot)
                    : loadingHotspotDetail
                      ? copy.loadingRoute
                      : copy.selectTopicHint}
                </p>
                {hotspotDetail?.canonicalTopic && hotspotDetail.canonicalTopic !== selectedHotspotTopic ? (
                  <p className="mt-1 text-[11px] text-secondary-text">{copy.canonicalTopicLabel}{hotspotDetail.canonicalTopic}</p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  isLoading={searchingHotspotNews}
                  loadingText={copy.searching}
                  disabled={loadingHotspotDetail || searchingHotspotNews}
                  onClick={() => void loadHotspotDetail(selectedHotspotTopic, { includeSearch: true })}
                >
                  <Search className="h-3.5 w-3.5" />
                  {copy.searchNews}
                </Button>
                {loadingHotspotDetail ? (
                  <span className="w-fit rounded-full bg-cyan/10 px-3 py-1 text-xs font-semibold text-cyan">
                    {copy.loadingDetails}
                  </span>
                ) : null}
                {hotspotDetail?.qualityStatus ? (
                  <span className="w-fit rounded-full bg-warning/10 px-3 py-1 text-xs font-semibold text-warning">
                    {copy.quality} {getHotspotQualityLabel(language, hotspotDetail.qualityStatus)}
                  </span>
                ) : null}
                {hotspotDetail?.fallbackUsed || hotspotDetail?.stale ? (
                  <span className="w-fit rounded-full bg-warning/10 px-3 py-1 text-xs font-semibold text-warning">
                    {getHotspotFallbackLabel(language, hotspotDetail)}
                  </span>
                ) : null}
                {hotspotDetail?.stockCount != null ? (
                  <span className="w-fit rounded-full bg-orange-500/10 px-3 py-1 text-xs font-semibold text-orange-500">
                    {copy.themeStocks} {hotspotDetail.stockCount}
                  </span>
                ) : null}
              </div>
            </div>

            {hotspotDetailError ? (
              <p className="mb-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                {hotspotDetailError}
              </p>
            ) : null}

            {hotspotDetail && hasHotspotDetailDegradation(hotspotDetail) ? (
              <details className="mb-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                <summary className="cursor-pointer font-semibold">{copy.degradedDetails}</summary>
                <div className="mt-2 space-y-1 leading-5">
                  {(hotspotDetail.missingFields || []).length > 0 ? (
                    <p>{copy.missingLabel}{getHotspotMissingFieldLabels(language, hotspotDetail.missingFields).join(language === 'en' ? ', ' : '、')}</p>
                  ) : null}
                  {getHotspotDiagnosticMessages(language, hotspotDetail.sourceErrors).map((message, index) => (
                    <p key={`${message}-${index}`}>{message}</p>
                  ))}
                </div>
              </details>
            ) : null}

            {hotspotDetail ? (
              <div className="grid gap-4 lg:grid-cols-[1fr_1.3fr]">
                <div>
                  <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-secondary-text">
                    <Clock3 className="h-3.5 w-3.5 text-orange-500" />
                    {copy.timeline}
                  </p>
                  <div className="relative space-y-0 pl-4 before:absolute before:bottom-3 before:left-[5px] before:top-2 before:w-px before:bg-border">
                    {getHotspotRouteItems(hotspotDetail).map((item, index) => (
                      <div key={`${item.title}-${index}`} className="relative pb-4 last:pb-0">
                        <span className="absolute -left-4 top-1 h-2.5 w-2.5 rounded-full border border-orange-400 bg-card" />
                        <div className="rounded-lg border border-border/70 bg-card/80 p-3">
                          <p className="text-[11px] font-semibold text-orange-500">{getRouteTimeLabel(language, item)}</p>
                          <p className="mt-1 text-xs font-semibold text-foreground">{formatHotspotRouteTitle(language, item.title)}</p>
                          <p className="mt-1 text-xs leading-5 text-secondary-text">{formatHotspotRouteDescription(language, item.description)}</p>
                          {item.url ? (
                            <a
                              className="mt-2 inline-flex text-[11px] font-semibold text-cyan hover:text-foreground"
                              href={item.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {copy.viewNews}
                            </a>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="mb-2 text-xs font-semibold text-secondary-text">{copy.themeStocks}</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {(hotspotDetail.stocks || []).slice(0, 10).map((stock) => (
                      <div key={`${stock.code || stock.name}`} className="rounded-lg border border-border/70 bg-card/80 p-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-xs font-semibold text-foreground">{stock.name || stock.code || '-'}</p>
                            <p className="mt-1 text-[11px] text-secondary-text">{stock.code || '-'}</p>
                          </div>
                          <div className="flex shrink-0 items-center gap-1">
                            <span className="rounded-full bg-cyan/10 px-2 py-1 text-[11px] font-semibold text-cyan">
                              {getHotspotRoleLabel(language, stock.role)}
                            </span>
                            {stock.code ? (
                              <button
                                type="button"
                                aria-label={screeningText(language, 'analyzeStock', { name: stock.name || stock.code || '' })}
                                className="inline-flex h-7 items-center gap-1 rounded-full border border-cyan/30 bg-cyan/10 px-2 text-[11px] font-semibold text-cyan transition-colors hover:border-cyan hover:bg-cyan/15 hover:text-foreground"
                                onClick={() => handleAnalyzeHotspotStock(stock)}
                              >
                                <Play className="h-3 w-3" />
                                {copy.analyze}
                              </button>
                            ) : null}
                          </div>
                        </div>
                        <p className="mt-2 text-[11px] text-secondary-text">
                          {copy.change} {formatStockChangeText(language, stock.changePct)} {copy.heatLabel} {formatNumber(stock.hotStockScore, 0)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="rounded-2xl border border-cyan/35 bg-card/95 p-4 shadow-soft-card">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SlidersHorizontal className="h-4 w-4 text-cyan" />
            {copy.run}
          </div>
          <span className="rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1 text-xs font-semibold text-cyan">
            {selectedStrategyTag}
          </span>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr_180px_auto] lg:items-end">
          <label className="space-y-2 text-xs font-medium text-secondary-text">
            {copy.market}<select
              className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-sm text-foreground outline-none transition-colors focus:border-cyan"
              value={market}
              disabled={loading}
              onChange={(event) => handleMarketChange(event.target.value)}
            >
              {MARKET_IDS.map((id) => (
                <option key={id} value={id}>
                  {formatHistoryMarketLabel(language, id)}
                </option>
              ))}
            </select>
          </label>

          <div className="space-y-2 text-xs font-medium text-secondary-text">
            <label htmlFor="screening-strategy">{copy.strategy}</label>
            <Select
              id="screening-strategy"
              value={selectedStrategy ? strategy : CUSTOM_STRATEGY_OPTION_VALUE}
              disabled={loading || loadingStrategies}
              placeholder=""
              options={[
                ...strategies.map((item) => ({
                  value: item.id,
                  label: item.name || item.title || item.id,
                })),
                { value: CUSTOM_STRATEGY_OPTION_VALUE, label: copy.customStrategyOption },
              ]}
              onChange={(value) =>
                handleStrategyChange(
                  value === CUSTOM_STRATEGY_OPTION_VALUE ? '' : value,
                )
              }
            />
          </div>

          {!selectedStrategy && !loadingStrategies ? (
            <label className="space-y-2 text-xs font-medium text-secondary-text lg:col-start-2">
              {copy.customStrategyId}<input
                aria-label={copy.customStrategyId}
                className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-sm text-foreground outline-none transition-colors focus:border-cyan"
                value={strategy}
                disabled={loading}
                placeholder={copy.strategyPlaceholder}
                onChange={(event) => handleStrategyChange(event.target.value)}
              />
            </label>
          ) : null}

          <label className="space-y-2 text-xs font-medium text-secondary-text">
            {copy.resultLimit}<input
              className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-sm text-foreground outline-none transition-colors focus:border-cyan"
              type="number"
              min={1}
              max={100}
              value={maxResults}
              disabled={loading}
              onChange={(event) => handleMaxResultsChange(Number(event.target.value))}
            />
          </label>

          <Button
            className="h-11 min-w-40"
            isLoading={loading}
            loadingText={copy.screening}
            disabled={!isScreeningEnabled || loading || !strategy.trim()}
            onClick={() => void handleSubmit()}
          >
            <Play className="h-4 w-4" />
            {copy.run}
          </Button>
        </div>

        <div className="mt-3 rounded-xl border border-border/75 bg-surface/55 px-3 py-2 text-xs leading-5 text-secondary-text">
          {strategyLoadError
            ? strategyLoadError
            : selectedStrategy?.description || copy.strategyHint}
        </div>
      </section>

      {loading || screenMeta ? (
        <section className="rounded-2xl border border-border bg-card/95 p-4 shadow-soft-card">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-3">
              <span className={`grid h-7 w-7 place-items-center rounded-full ${loading ? 'text-cyan' : 'text-success'}`}>
                {loading ? <CircleAlert className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
              </span>
              <div>
                <h2 className="text-sm font-semibold text-foreground">{loading ? copy.running : copy.completed}</h2>
                <p className="mt-1 text-xs text-secondary-text">
                  {loading
                    ? `${taskMessage || copy.executing} · ${taskProgress}%`
                    : `${displayedStrategy} · ${formatHistoryMarketLabel(language, market)}`}
                </p>
              </div>
            </div>
          </div>

          <details className="mt-3 border-t border-border/70 pt-3 text-xs text-secondary-text">
            <summary className="w-fit cursor-pointer font-medium text-secondary-text">{copy.runDetails}</summary>
            <div className="mt-2 grid gap-1">
              <span>{copy.taskLabel}{activeTaskId ? activeTaskId.slice(0, 12) : '-'}</span>
              <span>{language === 'en' ? 'Run ID: ' : 'Run ID：'}{screenMeta?.runId || '-'}</span>
              <span>
                {copy.snapshot} {screenMeta?.snapshotCount ?? '-'} {copy.filteredLabel} {screenMeta?.afterFilterCount ?? '-'} {copy.candidatesLabel} {screenMeta?.candidateCount ?? candidates.length}
              </span>
              <span>
                {copy.rankingLabel}{screenMeta?.llmRanked ? copy.reranking : screenMeta ? copy.deterministicFactors : '-'}
                {screenMeta?.llmModelUsed ? ` · ${screenMeta.llmModelUsed}` : ''}
                {screenMeta?.llmCoverage != null ? screeningText(language, 'coverage', { percent: formatPercent(screenMeta.llmCoverage) }) : ''}
              </span>
              {screenMeta?.resultVariantPoolSize ? (
                <span>
                  {copy.variantPool} {screenMeta.resultVariantPoolSize} ·{' '}
                  {screenMeta.resultVariantApplied
                    ? screeningText(language, 'rotatedSlots', { count: screenMeta.resultVariantRotatedSlots ?? 0 })
                    : copy.baselineRetained}
                </span>
              ) : null}
              <span>
                {copy.enrichmentLabel}{screenMeta?.dsaEnrichment?.enrichedCount ?? '-'} / {screenMeta?.dsaEnrichment?.requestedCount ?? '-'}
              </span>
            </div>
          </details>
        </section>
      ) : null}

      {screenMeta && alertMessages.length > 0 ? (
        <InlineAlert
          variant={llmFailed ? 'warning' : 'info'}
          title={llmFailed ? copy.usingFactors : copy.screeningNotice}
          message={<ScreenAlertMessage messages={alertMessages} />}
        />
      ) : null}

      {screenMeta ? (
        <section className="rounded-2xl border border-border bg-card/95 p-4 shadow-soft-card">
          <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <h2 className="text-base font-semibold text-foreground">{copy.results}</h2>
          <div className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-2 text-xs text-secondary-text">
            <Search className="h-4 w-4 text-cyan" />
            {screeningText(language, 'candidateCount', { count: candidates.length })}</div>
          </div>

        {candidates.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-surface/70 px-5 py-10 text-center">
            <p className="text-sm font-medium text-foreground">{copy.emptyCandidates}</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[860px] border-collapse text-sm">
              <thead className="bg-surface text-left text-xs text-secondary-text">
                <tr>
                  <th className="w-14 px-4 py-3 font-semibold">#</th>
                  <th className="px-4 py-3 font-semibold">{copy.code}</th>
                  <th className="px-4 py-3 font-semibold">{copy.name}</th>
                  <th className="px-4 py-3 font-semibold">{copy.industry}</th>
                  <th className="px-4 py-3 font-semibold">{copy.price}</th>
                  <th className="px-4 py-3 font-semibold">{copy.change}</th>
                  <th className="px-4 py-3 font-semibold">{copy.score}</th>
                  <th className="px-4 py-3 font-semibold">{copy.rankingBasis}</th>
                  <th className="px-4 py-3 font-semibold">{copy.risk}</th>
                  <th className="px-4 py-3 font-semibold">{copy.details}</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((item) => {
                  const expanded = expandedCode === item.code;
                  const factors = getFactorEntries(item);
                  const selectionExplanations = getSelectionExplanations(language, item);
                  const selectionQuality = item.whySelected?.length
                    ? item.explanationQuality?.whySelected || 'unknown'
                    : 'unknown';
                  const llmInsightAvailable = hasLlmInsight(item);
                  const dsaWarnings = item.dsaContext?.warnings || [];
                  const dsaNews = item.dsaNews || [];
                  const dsaEvents = item.dsaEvents || [];
                  return (
                    <Fragment key={`${item.rank}-${item.code}`}>
                      <tr className="border-t border-border align-top transition-colors hover:bg-hover/50">
                        <td className="px-4 py-3 text-secondary-text">{item.rank}</td>
                        <td className="px-4 py-3 font-mono font-semibold text-foreground">{item.code}</td>
                        <td className="px-4 py-3 font-semibold text-foreground">{item.name || '-'}</td>
                        <td className="px-4 py-3 text-secondary-text">{item.industry || '-'}</td>
                        <td className="px-4 py-3 text-secondary-text">{formatNumber(item.price)}</td>
                        <td className="px-4 py-3 text-secondary-text">{formatNumber(item.changePct)}%</td>
                        <td className="px-4 py-3 font-bold text-cyan">{formatScore(item.score)}</td>
                        <td className="px-4 py-3 text-secondary-text">{factorRanking ? copy.factorRanking : formatScore(item.llmScore)}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${getRiskClassName(item.riskLevel)}`}>
                            {getRiskLabel(language, item.riskLevel)}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <button
                            className="text-sm font-semibold text-cyan transition-colors hover:text-foreground"
                            type="button"
                            onClick={() => setExpandedCode(expanded ? null : item.code)}
                          >
                            {expanded ? copy.collapse : copy.expand}
                          </button>
                        </td>
                      </tr>
                      {expanded ? (
                        <tr className="border-t border-border bg-surface/45">
                          <td colSpan={10} className="px-4 py-4">
                            <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
                              <div className="space-y-3">
                                <div className="grid gap-3 md:grid-cols-2">
                                  <div className="rounded-xl border border-cyan/25 bg-cyan/5 px-3 py-2.5">
                                    <p className="text-xs font-semibold text-cyan">{copy.whySelected}</p>
                                    <ExplanationItems items={selectionExplanations} emptyText={copy.noSelectionEvidence} />
                                    {selectionExplanations.length > 0 ? (
                                      <p className="mt-2 text-xs text-secondary-text">{copy.overallQuality}{selectionQuality}</p>
                                    ) : null}
                                  </div>
                                  <div className="rounded-xl border border-orange-400/25 bg-orange-500/5 px-3 py-2.5">
                                    <p className="text-xs font-semibold text-orange-500">{copy.whyNow}</p>
                                    <ExplanationItems items={item.whyNow} emptyText={copy.noTimingEvidence} />
                                    {item.whyNow?.length ? (
                                      <p className="mt-2 text-xs text-secondary-text">{copy.overallQuality}{item.explanationQuality?.whyNow || 'unknown'}</p>
                                    ) : null}
                                  </div>
                                </div>
                                <div>
                                  <p className="text-xs font-semibold text-secondary-text">{copy.summary}</p>
                                  <p className="mt-1 text-sm leading-6 text-foreground">{getCandidateReason(language, item)}</p>
                                </div>
                                <div>
                                  <p className="text-xs font-semibold text-secondary-text">{copy.signal}</p>
                                  <p className="mt-1 text-sm text-foreground">{getSignal(language, item)}</p>
                                  <button
                                    className="mt-2 rounded-lg border border-cyan/40 px-3 py-1.5 text-xs font-semibold text-cyan transition-colors hover:bg-cyan/10"
                                    type="button"
                                    onClick={() => handleAnalyzeCandidate(item)}
                                  >
                                    {copy.deepAnalysis}
                                  </button>
                                </div>
                                {item.dsaAnalysisSummary ? (
                                  <div>
                                    <p className="text-xs font-semibold text-secondary-text">{copy.enrichedSummary}</p>
                                    <p className="mt-1 text-sm leading-6 text-foreground">
                                      {formatEnrichmentSummary(language, item.dsaAnalysisSummary)}
                                    </p>
                                  </div>
                                ) : null}
                                {llmInsightAvailable ? (
                                  <div>
                                    <p className="text-xs font-semibold text-secondary-text">{copy.llmInsights}</p>
                                    <p className="mt-1 text-sm leading-6 text-foreground">{item.llmThesis || item.reason}</p>
                                    <p className="mt-1 text-xs text-secondary-text">
                                      {copy.sector} {item.llmSector || '-'} {copy.themeLabel} {item.llmTheme || '-'} {copy.confidenceLabel} {formatPercent(item.llmConfidence)}
                                    </p>
                                  </div>
                                ) : null}
                                <div>
                                  <p className="text-xs font-semibold text-secondary-text">{copy.riskFlags}</p>
                                  <p className="mt-1 text-sm text-foreground">
                                    {[...(item.riskFlags || []), ...(item.llmRisks || [])].length
                                      ? [...(item.riskFlags || []), ...(item.llmRisks || [])].join(language === 'en' ? ', ' : '，')
                                      : copy.none}
                                  </p>
                                </div>
                                {item.riskSummary ? (
                                  <div>
                                    <p className="text-xs font-semibold text-secondary-text">{copy.riskSummary}</p>
                                    <p className="mt-1 text-sm text-foreground">{item.riskSummary}</p>
                                  </div>
                                ) : null}
                              </div>
                              <div className="space-y-3">
                                <div>
                                  <p className="text-xs font-semibold text-secondary-text">{copy.factors}</p>
                                  <div className="mt-2 grid grid-cols-2 gap-2">
                                    {factors.length > 0 ? (
                                      factors.map(([key, value]) => (
                                        <div key={key} className="rounded-lg border border-border bg-card px-3 py-2">
                                          <span className="block text-xs text-secondary-text">{copy[FACTOR_LABELS[key]] || key}</span>
                                          <span className="text-sm font-semibold text-foreground">{formatNumber(value)}</span>
                                        </div>
                                      ))
                                    ) : (
                                      <span className="text-sm text-secondary-text">{copy.noFactors}</span>
                                    )}
                                  </div>
                                </div>
                                <div>
                                  <p className="text-xs font-semibold text-secondary-text">{copy.amount}</p>
                                  <p className="mt-1 text-sm text-foreground">{formatAmount(language, item.amount)}</p>
                                </div>
                                {item.llmWatchItems?.length ? (
                                  <div>
                                    <p className="text-xs font-semibold text-secondary-text">{copy.watchItems}</p>
                                    <p className="mt-1 text-sm text-foreground">{item.llmWatchItems.join(language === 'en' ? ', ' : '，')}</p>
                                  </div>
                                ) : null}
                                {item.llmCatalysts?.length ? (
                                  <div>
                                    <p className="text-xs font-semibold text-secondary-text">{copy.catalysts}</p>
                                    <p className="mt-1 text-sm text-foreground">{item.llmCatalysts.join(language === 'en' ? ', ' : '，')}</p>
                                  </div>
                                ) : null}
                                <div>
                                  <p className="text-xs font-semibold text-secondary-text">{copy.relatedNews}</p>
                                  {dsaNews.length > 0 ? (
                                    <ul className="mt-1 space-y-1 text-sm text-foreground">
                                      {dsaNews.slice(0, 3).map((newsItem, newsIndex) => (
                                        <li key={`${item.code}-dsa-news-${newsIndex}`}>
                                          {newsItem.title || newsItem.snippet || '-'}
                                        </li>
                                      ))}
                                    </ul>
                                  ) : (
                                    <p className="mt-1 text-sm text-secondary-text">{copy.none}</p>
                                  )}
                                </div>
                                <div>
                                  <p className="text-xs font-semibold text-secondary-text">{copy.events}</p>
                                  {dsaEvents.length > 0 ? (
                                    <ul className="mt-1 space-y-1 text-sm text-foreground">
                                      {dsaEvents.slice(0, 3).map((eventItem, eventIndex) => (
                                        <li key={`${item.code}-dsa-event-${eventIndex}`}>
                                          {eventItem.title || eventItem.snippet || '-'}
                                        </li>
                                      ))}
                                    </ul>
                                  ) : (
                                    <p className="mt-1 text-sm text-secondary-text">{copy.none}</p>
                                  )}
                                </div>
                                {dsaWarnings.length > 0 ? (
                                  <div>
                                    <p className="text-xs font-semibold text-secondary-text">{copy.enrichmentNotices}</p>
                                    <p className="mt-1 text-sm text-secondary-text">{dsaWarnings.join(language === 'en' ? ', ' : '，')}</p>
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        </section>
      ) : null}

      <section className="rounded-2xl border border-border/80 bg-card/95 p-4 shadow-soft-card">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Clock3 className="h-4 w-4 text-cyan" />
            {copy.history}
          </div>
          <button
            type="button"
            className="text-xs font-medium text-cyan transition-colors hover:text-foreground"
            onClick={() => void loadHistory()}
            disabled={historyLoading}
          >
            {historyLoading ? copy.loading : copy.refresh}
          </button>
        </div>
        {historyError ? (
          <p className="mb-3 text-xs text-danger">{historyError}</p>
        ) : null}
        {historyRuns.length === 0 ? (
          <p className="py-3 text-center text-xs text-secondary-text">
            {historyLoading ? copy.loadingHistory : copy.emptyHistory}
          </p>
        ) : (
          <div className="divide-y divide-border/70">
            {historyRuns.map((run) => (
              <button
                key={run.runId}
                type="button"
                className="flex w-full items-center justify-between gap-3 py-2.5 text-left transition-colors hover:bg-hover/50"
                onClick={() => void handleHistoryRunSelect(run.runId)}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-foreground">
                    {formatHistoryStrategyName(language, run.strategy, strategies)}
                    <span className="ml-2 text-xs font-normal text-secondary-text">
                      {formatHistoryMarketLabel(language, run.market)}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-xs text-secondary-text">
                    {screeningText(language, 'returnedCount', { count: run.candidateCount ?? 0 })}{run.snapshotCount != null ? screeningText(language, 'snapshotCount', { count: run.snapshotCount }) : ''}
                    {run.llmRanked ? copy.rerankingSuffix : ''}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-secondary-text">
                  {formatRunCreatedAt(language, run.createdAt)}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </AppPage>
  );
};

export default StockScreeningPage;
