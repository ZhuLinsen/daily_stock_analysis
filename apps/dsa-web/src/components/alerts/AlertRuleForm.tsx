import type React from 'react';
import { useState } from 'react';
import { Button, Card, Checkbox, Input, Select } from '../common';
import type { AlertRuleCreateRequest, AlertSeverity, AlertType } from '../../types/alerts';
import { validateStockCode } from '../../utils/validation';

const ALERT_TYPE_OPTIONS = [
  { value: 'price_cross', label: '价格突破' },
  { value: 'price_change_percent', label: '涨跌幅' },
  { value: 'volume_spike', label: '成交量放大' },
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

interface AlertRuleFormProps {
  onSubmit: (payload: AlertRuleCreateRequest) => Promise<boolean | void> | boolean | void;
  isSubmitting?: boolean;
}

export const AlertRuleForm: React.FC<AlertRuleFormProps> = ({ onSubmit, isSubmitting = false }) => {
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [alertType, setAlertType] = useState<AlertType>('price_cross');
  const [severity, setSeverity] = useState<AlertSeverity>('warning');
  const [enabled, setEnabled] = useState(true);
  const [priceDirection, setPriceDirection] = useState<'above' | 'below'>('above');
  const [changeDirection, setChangeDirection] = useState<'up' | 'down'>('up');
  const [price, setPrice] = useState('');
  const [changePct, setChangePct] = useState('');
  const [multiplier, setMultiplier] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const resetParameters = (nextType: AlertType) => {
    if (nextType === 'price_cross') {
      setPriceDirection('above');
      setPrice('');
    } else if (nextType === 'price_change_percent') {
      setChangeDirection('up');
      setChangePct('');
    } else {
      setMultiplier('');
    }
  };

  const parsePositiveNumber = (value: string, label: string): number | null => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setFormError(`${label}必须是大于 0 的数字`);
      return null;
    }
    return parsed;
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const targetValidation = validateStockCode(target);
    if (!targetValidation.valid) {
      setFormError(targetValidation.message ?? '股票代码格式不正确');
      return;
    }

    let parameters: AlertRuleCreateRequest['parameters'];
    if (alertType === 'price_cross') {
      const parsedPrice = parsePositiveNumber(price, '价格阈值');
      if (parsedPrice == null) return;
      parameters = { direction: priceDirection, price: parsedPrice };
    } else if (alertType === 'price_change_percent') {
      const parsedChangePct = parsePositiveNumber(changePct, '涨跌幅阈值');
      if (parsedChangePct == null) return;
      parameters = { direction: changeDirection, changePct: parsedChangePct };
    } else {
      const parsedMultiplier = parsePositiveNumber(multiplier, '成交量倍数');
      if (parsedMultiplier == null) return;
      parameters = { multiplier: parsedMultiplier };
    }

    setFormError(null);
    const submitted = await onSubmit({
      name: name.trim() || undefined,
      targetScope: 'single_symbol',
      target: targetValidation.normalized,
      alertType,
      parameters,
      severity,
      enabled,
    });
    if (submitted === false) return;
    setName('');
    setTarget('');
    setPrice('');
    setChangePct('');
    setMultiplier('');
    setEnabled(true);
  };

  return (
    <Card title="创建告警规则" subtitle="Web 告警中心" variant="bordered" padding="md">
      <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
        <div className="grid gap-4 md:grid-cols-2">
          <Input
            label="规则名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="可选，例如 茅台价格突破"
            disabled={isSubmitting}
          />
          <Input
            label="标的代码"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            placeholder="600519 / AAPL / hk00700"
            disabled={isSubmitting}
          />
          <Select
            label="规则类型"
            value={alertType}
            options={ALERT_TYPE_OPTIONS}
            disabled={isSubmitting}
            onChange={(value) => {
              const nextType = value as AlertType;
              setAlertType(nextType);
              resetParameters(nextType);
            }}
          />
          <Select
            label="严重级别"
            value={severity}
            options={SEVERITY_OPTIONS}
            disabled={isSubmitting}
            onChange={(value) => setSeverity(value as AlertSeverity)}
          />
        </div>

        {alertType === 'price_cross' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label="方向"
              value={priceDirection}
              options={PRICE_DIRECTION_OPTIONS}
              disabled={isSubmitting}
              onChange={(value) => setPriceDirection(value as 'above' | 'below')}
            />
            <Input
              label="价格阈值"
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
              label="方向"
              value={changeDirection}
              options={CHANGE_DIRECTION_OPTIONS}
              disabled={isSubmitting}
              onChange={(value) => setChangeDirection(value as 'up' | 'down')}
            />
            <Input
              label="涨跌幅阈值（%）"
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
            label="成交量放大倍数"
            type="number"
            min="0"
            step="0.01"
            value={multiplier}
            onChange={(event) => setMultiplier(event.target.value)}
            disabled={isSubmitting}
          />
        ) : null}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Checkbox
            label="创建后立即启用"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            disabled={isSubmitting}
          />
          <Button type="submit" isLoading={isSubmitting} loadingText="创建中...">
            创建规则
          </Button>
        </div>
        {formError ? <p role="alert" className="text-sm text-danger">{formError}</p> : null}
      </form>
    </Card>
  );
};
