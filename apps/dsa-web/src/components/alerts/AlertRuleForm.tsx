import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import type {
  AlertRuleCreateRequest,
  AlertSeverity,
  AlertTargetScope,
  AlertType,
  MarketLightStatus,
  MarketRegion,
  PortfolioStopLossMode,
} from '../../types/alerts';
import type { PortfolioAccountItem } from '../../types/portfolio';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import {
  ALERT_CHANGE_DIRECTION_OPTIONS,
  ALERT_CROSS_DIRECTION_OPTIONS,
  ALERT_FORM_TEXT,
  ALERT_MARKET_LIGHT_STATUS_OPTIONS,
  ALERT_MARKET_REGION_OPTIONS,
  ALERT_MARKET_TYPE_OPTIONS,
  ALERT_PORTFOLIO_TYPE_OPTIONS,
  ALERT_PRICE_DIRECTION_OPTIONS,
  ALERT_SEVERITY_OPTIONS,
  ALERT_STOP_LOSS_MODE_OPTIONS,
  ALERT_SYMBOL_TYPE_OPTIONS,
  ALERT_TARGET_SCOPE_OPTIONS,
  ALERT_THRESHOLD_DIRECTION_OPTIONS,
} from '../../locales/featureText';
import { validateStockCode } from '../../utils/validation';
import { Button, Card, Checkbox, Input, Select } from '../common';

const SYMBOL_ALERT_TYPE_OPTIONS = [
  { value: 'price_cross', label: '价格突破' },
  { value: 'price_change_percent', label: '涨跌幅' },
  { value: 'volume_spike', label: '成交量放大' },
  { value: 'ma_price_cross', label: '价格均线穿越' },
  { value: 'rsi_threshold', label: 'RSI 阈值' },
  { value: 'macd_cross', label: 'MACD 金叉/死叉' },
  { value: 'kdj_cross', label: 'KDJ 金叉/死叉' },
  { value: 'cci_threshold', label: 'CCI 阈值' },
];

const PORTFOLIO_ALERT_TYPE_OPTIONS = [
  { value: 'portfolio_stop_loss', label: '组合止损' },
  { value: 'portfolio_concentration', label: '组合集中度' },
  { value: 'portfolio_drawdown', label: '组合回撤' },
  { value: 'portfolio_price_stale', label: '组合价格状态' },
];

const MARKET_ALERT_TYPE_OPTIONS = [
  { value: 'market_light_status', label: '大盘红绿灯状态' },
  { value: 'market_light_score_drop', label: '大盘红绿灯分数下降' },
];

const TARGET_SCOPE_OPTIONS = [
  { value: 'single_symbol', label: '单标的' },
  { value: 'watchlist', label: '自选股' },
  { value: 'portfolio_holdings', label: '持仓标的' },
  { value: 'portfolio_account', label: '持仓账户' },
  { value: 'market', label: '大盘市场' },
];

const SEVERITY_OPTIONS = [
  { value: 'info', label: '提示' },
  { value: 'warning', label: '警告' },
  { value: 'critical', label: '严重' },
];

const PRICE_DIRECTION_OPTIONS = [
  { value: 'above', label: '上破' },
  { value: 'below', label: '下破' },
];

const CHANGE_DIRECTION_OPTIONS = [
  { value: 'up', label: '上涨达到' },
  { value: 'down', label: '下跌达到' },
];

const THRESHOLD_DIRECTION_OPTIONS = [
  { value: 'above', label: '上穿' },
  { value: 'below', label: '下穿' },
];

const CROSS_DIRECTION_OPTIONS = [
  { value: 'bullish_cross', label: '金叉' },
  { value: 'bearish_cross', label: '死叉' },
];

const STOP_LOSS_MODE_OPTIONS = [
  { value: 'near', label: '接近止损' },
  { value: 'breach', label: '已触发止损' },
];

const MARKET_REGION_OPTIONS = [
  { value: 'cn', label: 'A 股（cn）' },
  { value: 'hk', label: '港股（hk）' },
  { value: 'us', label: '美股（us）' },
];

const MARKET_LIGHT_STATUS_OPTIONS: Array<{ value: MarketLightStatus; label: string }> = [
  { value: 'red', label: '红灯' },
  { value: 'yellow', label: '黄灯' },
];

const MAX_REQUESTED_DAYS = 365;

interface AlertRuleFormProps {
  onSubmit: (payload: AlertRuleCreateRequest) => Promise<boolean | void> | boolean | void;
  isSubmitting?: boolean;
}

function isPortfolioScope(scope: AlertTargetScope): boolean {
  return scope === 'portfolio_holdings' || scope === 'portfolio_account';
}

function defaultAlertTypeForScope(scope: AlertTargetScope): AlertType {
  if (scope === 'market') return 'market_light_status';
  return scope === 'portfolio_account' ? 'portfolio_stop_loss' : 'price_cross';
}

function optionsForScope(scope: AlertTargetScope, language: UiLanguage) {
  if (language === 'zh') {
    if (scope === 'market') return MARKET_ALERT_TYPE_OPTIONS;
    return scope === 'portfolio_account' ? PORTFOLIO_ALERT_TYPE_OPTIONS : SYMBOL_ALERT_TYPE_OPTIONS;
  }
  if (scope === 'market') return ALERT_MARKET_TYPE_OPTIONS[language];
  return scope === 'portfolio_account' ? ALERT_PORTFOLIO_TYPE_OPTIONS[language] : ALERT_SYMBOL_TYPE_OPTIONS[language];
}

export const AlertRuleForm: React.FC<AlertRuleFormProps> = ({ onSubmit, isSubmitting = false }) => {
  const { language } = useUiLanguage();
  const text = ALERT_FORM_TEXT[language];
  const [name, setName] = useState('');
  const [targetScope, setTargetScope] = useState<AlertTargetScope>('single_symbol');
  const [target, setTarget] = useState('');
  const [portfolioTarget, setPortfolioTarget] = useState('all');
  const [marketRegion, setMarketRegion] = useState<MarketRegion>('cn');
  const [accounts, setAccounts] = useState<PortfolioAccountItem[]>([]);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [alertType, setAlertType] = useState<AlertType>('price_cross');
  const [severity, setSeverity] = useState<AlertSeverity>('warning');
  const [enabled, setEnabled] = useState(true);
  const [priceDirection, setPriceDirection] = useState<'above' | 'below'>('above');
  const [changeDirection, setChangeDirection] = useState<'up' | 'down'>('up');
  const [thresholdDirection, setThresholdDirection] = useState<'above' | 'below'>('above');
  const [crossDirection, setCrossDirection] = useState<'bullish_cross' | 'bearish_cross'>('bullish_cross');
  const [stopLossMode, setStopLossMode] = useState<PortfolioStopLossMode>('near');
  const [price, setPrice] = useState('');
  const [changePct, setChangePct] = useState('');
  const [multiplier, setMultiplier] = useState('');
  const [window, setWindow] = useState('20');
  const [period, setPeriod] = useState('12');
  const [threshold, setThreshold] = useState('');
  const [fastPeriod, setFastPeriod] = useState('12');
  const [slowPeriod, setSlowPeriod] = useState('26');
  const [signalPeriod, setSignalPeriod] = useState('9');
  const [kPeriod, setKPeriod] = useState('3');
  const [dPeriod, setDPeriod] = useState('3');
  const [marketLightStatuses, setMarketLightStatuses] = useState<MarketLightStatus[]>(['red', 'yellow']);
  const [minDrop, setMinDrop] = useState('10');
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!isPortfolioScope(targetScope)) return undefined;
    let cancelled = false;
    void portfolioApi.getAccounts(false)
      .then((response) => {
        if (cancelled) return;
        setAccounts(response.accounts ?? []);
        setAccountsError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setAccounts([]);
        setAccountsError(error instanceof Error ? error.message : text.accountLoadFailed);
      });
    return () => {
      cancelled = true;
    };
  }, [targetScope, text.accountLoadFailed]);

  const alertTypeOptions = useMemo(() => optionsForScope(targetScope, language), [language, targetScope]);
  const portfolioTargetOptions = useMemo(() => [
    { value: 'all', label: text.allAccounts },
    ...accounts.map((account) => ({
      value: String(account.id),
      label: `${account.name} #${account.id}`,
    })),
  ], [accounts, text.allAccounts]);

  const resetParameters = (nextType: AlertType) => {
    if (nextType === 'price_cross') {
      setPriceDirection('above');
      setPrice('');
    } else if (nextType === 'price_change_percent') {
      setChangeDirection('up');
      setChangePct('');
    } else if (nextType === 'volume_spike') {
      setMultiplier('');
    } else if (nextType === 'ma_price_cross') {
      setThresholdDirection('above');
      setWindow('20');
    } else if (nextType === 'rsi_threshold') {
      setThresholdDirection('above');
      setPeriod('12');
      setThreshold('');
    } else if (nextType === 'macd_cross') {
      setCrossDirection('bullish_cross');
      setFastPeriod('12');
      setSlowPeriod('26');
      setSignalPeriod('9');
    } else if (nextType === 'kdj_cross') {
      setCrossDirection('bullish_cross');
      setPeriod('9');
      setKPeriod('3');
      setDPeriod('3');
    } else if (nextType === 'cci_threshold') {
      setThresholdDirection('above');
      setPeriod('14');
      setThreshold('');
    } else if (nextType === 'portfolio_stop_loss') {
      setStopLossMode('near');
    } else if (nextType === 'market_light_status') {
      setMarketLightStatuses(['red', 'yellow']);
    } else if (nextType === 'market_light_score_drop') {
      setMinDrop('10');
    }
  };

  const toggleMarketLightStatus = (status: MarketLightStatus) => {
    setMarketLightStatuses((current) => (
      current.includes(status)
        ? current.filter((item) => item !== status)
        : [...current, status]
    ));
  };

  const parsePositiveNumber = (value: string, label: string): number | null => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setFormError(formatUiText(text.positiveNumber, { label }));
      return null;
    }
    return parsed;
  };

  const parseIntegerInRange = (value: string, label: string, min = 2, max = 250): number | null => {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
      setFormError(formatUiText(text.integerRange, { label, min, max }));
      return null;
    }
    return parsed;
  };

  const parseFiniteNumber = (value: string, label: string): number | null => {
    if (value.trim() === '') {
      setFormError(formatUiText(text.required, { label }));
      return null;
    }
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      setFormError(formatUiText(text.finiteNumber, { label }));
      return null;
    }
    return parsed;
  };

  const parseRsiThreshold = (value: string): number | null => {
    const parsed = parseFiniteNumber(value, text.rsiThreshold);
    if (parsed == null) return null;
    if (parsed < 0 || parsed > 100) {
      setFormError(text.rsiRange);
      return null;
    }
    return parsed;
  };

  const ensureRequiredBarsWithinLimit = (label: string, requiredBars: number): boolean => {
    if (requiredBars > MAX_REQUESTED_DAYS) {
      setFormError(formatUiText(text.requiredBarsLimit, { label, requiredBars, max: MAX_REQUESTED_DAYS }));
      return false;
    }
    return true;
  };

  const buildParameters = (): AlertRuleCreateRequest['parameters'] | null => {
    if (alertType === 'price_cross') {
      const parsedPrice = parsePositiveNumber(price, text.priceThreshold);
      if (parsedPrice == null) return null;
      return { direction: priceDirection, price: parsedPrice };
    }
    if (alertType === 'price_change_percent') {
      const parsedChangePct = parsePositiveNumber(changePct, text.changePctThreshold);
      if (parsedChangePct == null) return null;
      return { direction: changeDirection, changePct: parsedChangePct };
    }
    if (alertType === 'volume_spike') {
      const parsedMultiplier = parsePositiveNumber(multiplier, text.volumeMultiplier);
      if (parsedMultiplier == null) return null;
      return { multiplier: parsedMultiplier };
    }
    if (alertType === 'ma_price_cross') {
      const parsedWindow = parseIntegerInRange(window, text.maWindow);
      if (parsedWindow == null) return null;
      return { direction: thresholdDirection, window: parsedWindow };
    }
    if (alertType === 'rsi_threshold') {
      const parsedPeriod = parseIntegerInRange(period, text.rsiPeriod);
      const parsedThreshold = parseRsiThreshold(threshold);
      if (parsedPeriod == null || parsedThreshold == null) return null;
      return { direction: thresholdDirection, period: parsedPeriod, threshold: parsedThreshold };
    }
    if (alertType === 'macd_cross') {
      const parsedFast = parseIntegerInRange(fastPeriod, text.fastPeriod);
      const parsedSlow = parseIntegerInRange(slowPeriod, text.slowPeriod);
      const parsedSignal = parseIntegerInRange(signalPeriod, text.signalPeriod);
      if (parsedFast == null || parsedSlow == null || parsedSignal == null) return null;
      if (parsedFast >= parsedSlow) {
        setFormError(text.fastLessThanSlow);
        return null;
      }
      if (!ensureRequiredBarsWithinLimit('MACD', parsedSlow + parsedSignal + 1)) return null;
      return {
        direction: crossDirection,
        fastPeriod: parsedFast,
        slowPeriod: parsedSlow,
        signalPeriod: parsedSignal,
      };
    }
    if (alertType === 'kdj_cross') {
      const parsedPeriod = parseIntegerInRange(period, text.kdjPeriod);
      const parsedK = parseIntegerInRange(kPeriod, text.kPeriod);
      const parsedD = parseIntegerInRange(dPeriod, text.dPeriod);
      if (parsedPeriod == null || parsedK == null || parsedD == null) return null;
      if (!ensureRequiredBarsWithinLimit('KDJ', parsedPeriod + parsedK + parsedD + 1)) return null;
      return { direction: crossDirection, period: parsedPeriod, kPeriod: parsedK, dPeriod: parsedD };
    }
    if (alertType === 'cci_threshold') {
      const parsedPeriod = parseIntegerInRange(period, text.cciPeriod);
      const parsedThreshold = parseFiniteNumber(threshold, text.cciThreshold);
      if (parsedPeriod == null || parsedThreshold == null) return null;
      return { direction: thresholdDirection, period: parsedPeriod, threshold: parsedThreshold };
    }
    if (alertType === 'portfolio_stop_loss') {
      return { mode: stopLossMode };
    }
    if (alertType === 'market_light_status') {
      if (marketLightStatuses.length === 0) {
        setFormError(text.noMarketStatus);
        return null;
      }
      return { statuses: marketLightStatuses };
    }
    if (alertType === 'market_light_score_drop') {
      const parsedMinDrop = parsePositiveNumber(minDrop, text.scoreDropThreshold);
      if (parsedMinDrop == null) return null;
      return { minDrop: parsedMinDrop };
    }
    return {};
  };

  const handleScopeChange = (value: string) => {
    const nextScope = value as AlertTargetScope;
    const nextType = defaultAlertTypeForScope(nextScope);
    setTargetScope(nextScope);
    setAlertType(nextType);
    setPortfolioTarget('all');
    setMarketRegion('cn');
    resetParameters(nextType);
    setFormError(null);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    let resolvedTarget = target.trim();
    if (targetScope === 'single_symbol') {
      const targetValidation = validateStockCode(target);
      if (!targetValidation.valid) {
        setFormError(language === 'en' ? text.invalidStockCode : (targetValidation.message ?? text.invalidStockCode));
        return;
      }
      resolvedTarget = targetValidation.normalized;
    } else if (targetScope === 'watchlist') {
      resolvedTarget = 'default';
    } else if (targetScope === 'market') {
      resolvedTarget = marketRegion;
    } else {
      resolvedTarget = portfolioTarget;
    }

    const parameters = buildParameters();
    if (parameters == null) return;

    setFormError(null);
    const submitted = await onSubmit({
      name: name.trim() || undefined,
      targetScope,
      target: resolvedTarget,
      alertType,
      parameters,
      severity,
      enabled,
    });
    if (submitted === false) return;
    setName('');
    setTarget('');
    setPortfolioTarget('all');
    setMarketRegion('cn');
    setPrice('');
    setChangePct('');
    setMultiplier('');
    setWindow('20');
    setPeriod('12');
    setThreshold('');
    setFastPeriod('12');
    setSlowPeriod('26');
    setSignalPeriod('9');
    setKPeriod('3');
    setDPeriod('3');
    setMarketLightStatuses(['red', 'yellow']);
    setMinDrop('10');
    resetParameters(alertType);
    setEnabled(true);
  };

  const renderTargetControl = () => {
    if (targetScope === 'single_symbol') {
      return (
        <Input
          label={text.targetCode}
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          placeholder="600519 / AAPL / hk00700"
          disabled={isSubmitting}
        />
      );
    }
    if (targetScope === 'watchlist') {
      return (
        <Input
          label={text.target}
          value="default"
          onChange={() => undefined}
          disabled
        />
      );
    }
    if (targetScope === 'market') {
      return (
        <Select
          label={text.marketRegion}
          value={marketRegion}
          options={language === 'zh' ? MARKET_REGION_OPTIONS : ALERT_MARKET_REGION_OPTIONS[language]}
          disabled={isSubmitting}
          onChange={(value) => setMarketRegion(value as MarketRegion)}
        />
      );
    }
    return (
      <div className="space-y-2">
        <Select
          label={text.account}
          value={portfolioTarget}
          options={portfolioTargetOptions}
          disabled={isSubmitting}
          onChange={setPortfolioTarget}
        />
        {accountsError ? <p role="alert" className="text-xs text-warning">{accountsError}</p> : null}
      </div>
    );
  };

  return (
    <Card title={text.cardTitle} subtitle={text.cardSubtitle} variant="bordered" padding="md">
      <form className="space-y-4" noValidate onSubmit={(event) => void handleSubmit(event)}>
        <div className="grid gap-4 md:grid-cols-2">
          <Input
            label={text.ruleName}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={text.ruleNamePlaceholder}
            disabled={isSubmitting}
          />
          <Select
            label={text.targetScope}
            value={targetScope}
            options={language === 'zh' ? TARGET_SCOPE_OPTIONS : ALERT_TARGET_SCOPE_OPTIONS[language]}
            disabled={isSubmitting}
            onChange={handleScopeChange}
          />
          {renderTargetControl()}
          <Select
            label={text.ruleType}
            value={alertType}
            options={alertTypeOptions}
            disabled={isSubmitting}
            onChange={(value) => {
              const nextType = value as AlertType;
              setAlertType(nextType);
              resetParameters(nextType);
            }}
          />
          <Select
            label={text.severity}
            value={severity}
            options={language === 'zh' ? SEVERITY_OPTIONS : ALERT_SEVERITY_OPTIONS[language]}
            disabled={isSubmitting}
            onChange={(value) => setSeverity(value as AlertSeverity)}
          />
        </div>

        {alertType === 'price_cross' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label={text.direction}
              value={priceDirection}
              options={language === 'zh' ? PRICE_DIRECTION_OPTIONS : ALERT_PRICE_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setPriceDirection(value as 'above' | 'below')}
            />
            <Input
              label={text.priceThreshold}
              type="number"
              min="0"
              step="0.0001"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'price_change_percent' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label={text.direction}
              value={changeDirection}
              options={language === 'zh' ? CHANGE_DIRECTION_OPTIONS : ALERT_CHANGE_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setChangeDirection(value as 'up' | 'down')}
            />
            <Input
              label={text.changePctThreshold}
              type="number"
              min="0"
              step="0.01"
              value={changePct}
              onChange={(event) => setChangePct(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'volume_spike' ? (
          <Input
            label={text.volumeMultiplier}
            type="number"
            min="0"
            step="0.01"
            value={multiplier}
            onChange={(event) => setMultiplier(event.target.value)}
            disabled={isSubmitting}
          />
        ) : null}

        {alertType === 'ma_price_cross' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label={text.maDirection}
              value={thresholdDirection}
              options={language === 'zh' ? THRESHOLD_DIRECTION_OPTIONS : ALERT_THRESHOLD_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setThresholdDirection(value as 'above' | 'below')}
            />
            <Input
              label={text.maWindow}
              type="number"
              min="2"
              max="250"
              step="1"
              value={window}
              onChange={(event) => setWindow(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'rsi_threshold' ? (
          <div className="grid gap-4 md:grid-cols-3">
            <Select
              label={text.thresholdDirection}
              value={thresholdDirection}
              options={language === 'zh' ? THRESHOLD_DIRECTION_OPTIONS : ALERT_THRESHOLD_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setThresholdDirection(value as 'above' | 'below')}
            />
            <Input
              label={text.rsiPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.rsiThreshold}
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'macd_cross' ? (
          <div className="grid gap-4 md:grid-cols-4">
            <Select
              label={text.crossDirection}
              value={crossDirection}
              options={language === 'zh' ? CROSS_DIRECTION_OPTIONS : ALERT_CROSS_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setCrossDirection(value as 'bullish_cross' | 'bearish_cross')}
            />
            <Input
              label={text.fastPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={fastPeriod}
              onChange={(event) => setFastPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.slowPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={slowPeriod}
              onChange={(event) => setSlowPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.signalPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={signalPeriod}
              onChange={(event) => setSignalPeriod(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'kdj_cross' ? (
          <div className="grid gap-4 md:grid-cols-4">
            <Select
              label={text.crossDirection}
              value={crossDirection}
              options={language === 'zh' ? CROSS_DIRECTION_OPTIONS : ALERT_CROSS_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setCrossDirection(value as 'bullish_cross' | 'bearish_cross')}
            />
            <Input
              label={text.kdjPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.kPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={kPeriod}
              onChange={(event) => setKPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.dPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={dPeriod}
              onChange={(event) => setDPeriod(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'cci_threshold' ? (
          <div className="grid gap-4 md:grid-cols-3">
            <Select
              label={text.thresholdDirection}
              value={thresholdDirection}
              options={language === 'zh' ? THRESHOLD_DIRECTION_OPTIONS : ALERT_THRESHOLD_DIRECTION_OPTIONS[language]}
              disabled={isSubmitting}
              onChange={(value) => setThresholdDirection(value as 'above' | 'below')}
            />
            <Input
              label={text.cciPeriod}
              type="number"
              min="2"
              max="250"
              step="1"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              disabled={isSubmitting}
            />
            <Input
              label={text.cciThreshold}
              type="number"
              step="0.01"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        {alertType === 'portfolio_stop_loss' ? (
          <Select
            label={text.stopLossMode}
            value={stopLossMode}
            options={language === 'zh' ? STOP_LOSS_MODE_OPTIONS : ALERT_STOP_LOSS_MODE_OPTIONS[language]}
            disabled={isSubmitting}
            onChange={(value) => setStopLossMode(value as PortfolioStopLossMode)}
          />
        ) : null}

        {alertType === 'market_light_status' ? (
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">{text.triggerStatus}</div>
            <div className="grid gap-3 sm:grid-cols-2">
              {(language === 'zh' ? MARKET_LIGHT_STATUS_OPTIONS : ALERT_MARKET_LIGHT_STATUS_OPTIONS[language]).map((option) => (
                <Checkbox
                  key={option.value}
                  label={option.label}
                  checked={marketLightStatuses.includes(option.value)}
                  disabled={isSubmitting}
                  onChange={() => toggleMarketLightStatus(option.value)}
                />
              ))}
            </div>
          </div>
        ) : null}

        {alertType === 'market_light_score_drop' ? (
          <Input
            label={text.scoreDropThreshold}
            type="number"
            min="0"
            max="100"
            step="1"
            value={minDrop}
            onChange={(event) => setMinDrop(event.target.value)}
            disabled={isSubmitting}
          />
        ) : null}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Checkbox
            label={text.enableAfterCreate}
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            disabled={isSubmitting}
          />
          <Button type="submit" isLoading={isSubmitting} loadingText={text.creating}>
            {text.create}
          </Button>
        </div>
        {formError ? <p role="alert" className="text-sm text-danger">{formError}</p> : null}
      </form>
    </Card>
  );
};
