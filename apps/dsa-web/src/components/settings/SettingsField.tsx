import { useState } from 'react';
import type React from 'react';
import { Badge, Select, Input } from '../common';
import type { ConfigValidationIssue, SystemConfigFieldSchema, SystemConfigItem } from '../../types/systemConfig';
import { getFieldDescriptionZh, getFieldTitleZh } from '../../utils/systemConfigI18n';
import { cn } from '../../utils/cn';

function normalizeSelectOptions(options: SystemConfigFieldSchema['options'] = []) {
  return options.map((option) => {
    if (typeof option === 'string') {
      return { value: option, label: option };
    }

    return option;
  });
}

function isMultiValueField(item: SystemConfigItem): boolean {
  const validation = (item.schema?.validation ?? {}) as Record<string, unknown>;
  return Boolean(validation.multiValue ?? validation.multi_value);
}

function parseMultiValues(value: string): string[] {
  if (!value) {
    return [''];
  }

  const values = value.split(',').map((entry) => entry.trim());
  return values.length ? values : [''];
}

function serializeMultiValues(values: string[]): string {
  return values.map((entry) => entry.trim()).join(',');
}

function inferPasswordIconType(key: string): 'password' | 'key' {
  return key.toUpperCase().includes('PASSWORD') ? 'password' : 'key';
}

interface SettingsFieldProps {
  item: SystemConfigItem;
  value: string;
  disabled?: boolean;
  onChange: (key: string, value: string) => void;
  issues?: ConfigValidationIssue[];
}

function renderFieldControl(
  item: SystemConfigItem,
  value: string,
  disabled: boolean,
  onChange: (nextValue: string) => void,
  isPasswordEditable: boolean,
  onPasswordFocus: () => void,
  controlId: string,
) {
  const schema = item.schema;
  const commonClass = 'input-terminal border-border/55 bg-card/94 hover:border-border/75';
  const controlType = schema?.uiControl ?? 'text';
  const isMultiValue = isMultiValueField(item);

  if (controlType === 'textarea') {
    return (
      <textarea
        id={controlId}
        className={`${commonClass} min-h-[92px] resize-y`}
        value={value}
        disabled={disabled || !schema?.isEditable}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  if (controlType === 'select' && schema?.options?.length) {
    return (
        <Select
          id={controlId}
          value={value}
          onChange={onChange}
          options={normalizeSelectOptions(schema.options)}
          disabled={disabled || !schema.isEditable}
          placeholder="请选择"
        />
      );
  }

  if (controlType === 'switch') {
    const checked = value.trim().toLowerCase() === 'true';
    return (
      <label className="inline-flex cursor-pointer items-center gap-3">
        <input
          id={controlId}
          type="checkbox"
          checked={checked}
          disabled={disabled || !schema?.isEditable}
          onChange={(event) => onChange(event.target.checked ? 'true' : 'false')}
        />
        <span className="text-sm text-secondary-text">{checked ? '已启用' : '未启用'}</span>
      </label>
    );
  }

  if (controlType === 'password') {
    const iconType = inferPasswordIconType(item.key);

    if (isMultiValue) {
      const values = parseMultiValues(value);

      return (
        <div className="space-y-2">
          {values.map((entry, index) => (
            <div className="flex items-center gap-2" key={`${item.key}-${index}`}>
              <div className="flex-1">
                <Input
                  type="password"
                  allowTogglePassword
                  iconType={iconType}
                  id={index === 0 ? controlId : `${controlId}-${index}`}
                  readOnly={!isPasswordEditable}
                  onFocus={onPasswordFocus}
                  value={entry}
                  disabled={disabled || !schema?.isEditable}
                  onChange={(event) => {
                    const nextValues = [...values];
                    nextValues[index] = event.target.value;
                    onChange(serializeMultiValues(nextValues));
                  }}
                />
              </div>
              <button
                type="button"
                className="inline-flex h-11 items-center justify-center rounded-xl border settings-border settings-surface-hover px-3 text-xs text-muted-text transition-colors hover:settings-surface-hover hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                disabled={disabled || !schema?.isEditable || values.length <= 1}
                onClick={() => {
                  const nextValues = values.filter((_, rowIndex) => rowIndex !== index);
                  onChange(serializeMultiValues(nextValues.length ? nextValues : ['']));
                }}
              >
                删除
              </button>
            </div>
          ))}

          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center justify-center rounded-lg border settings-border settings-surface-hover px-3 py-1 text-xs text-secondary-text transition-colors hover:settings-surface-hover hover:text-foreground"
              disabled={disabled || !schema?.isEditable}
              onClick={() => onChange(serializeMultiValues([...values, '']))}
            >
              添加 Key
            </button>
          </div>
        </div>
      );
    }

    return (
      <Input
        type="password"
        allowTogglePassword
        iconType={iconType}
        id={controlId}
        readOnly={!isPasswordEditable}
        onFocus={onPasswordFocus}
        value={value}
        disabled={disabled || !schema?.isEditable}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  const inputType = controlType === 'number' ? 'number' : controlType === 'time' ? 'time' : 'text';

  return (
    <input
      id={controlId}
      type={inputType}
      className={commonClass}
      value={value}
      disabled={disabled || !schema?.isEditable}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

export const SettingsField: React.FC<SettingsFieldProps> = ({
  item,
  value,
  disabled = false,
  onChange,
  issues = [],
}) => {
  const schema = item.schema;
  const isMultiValue = isMultiValueField(item);
  const title = getFieldTitleZh(item.key, item.key);
  const description = getFieldDescriptionZh(item.key, schema?.description);
  const hasError = issues.some((issue) => issue.severity === 'error');
  const [isPasswordEditable, setIsPasswordEditable] = useState(false);
  const controlId = `setting-${item.key}`;

  return (
    <div
      className={cn(
        'rounded-[1.15rem] border settings-surface p-4 shadow-soft-card transition-all duration-200 hover:settings-surface-hover',
        hasError ? 'border-danger/40' : 'settings-border',
      )}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <label className="text-sm font-semibold text-foreground" htmlFor={controlId}>
          {title}
        </label>
        {schema?.isSensitive ? (
          <Badge variant="history" size="sm">
            敏感
          </Badge>
        ) : null}
        {!schema?.isEditable ? (
          <Badge variant="default" size="sm">
            只读
          </Badge>
        ) : null}
      </div>

      {description ? (
        <p className="mb-3 text-xs leading-5 text-muted-text" title={description}>
          {description}
        </p>
      ) : null}

      <div>
        {renderFieldControl(
          item,
          value,
          disabled,
          (nextValue) => onChange(item.key, nextValue),
          isPasswordEditable,
          () => setIsPasswordEditable(true),
          controlId,
        )}
      </div>

      {schema?.isSensitive ? (
        <p className="mt-3 text-[11px] leading-5 text-secondary-text">
          敏感内容默认隐藏，可点击眼睛图标查看明文。
          {isMultiValue ? ' 支持添加多个输入框进行增删。' : ''}
        </p>
      ) : null}

      {issues.length ? (
        <div className="mt-2 space-y-1">
          {issues.map((issue, index) => (
            <p
              key={`${issue.code}-${issue.key}-${index}`}
              className={issue.severity === 'error' ? 'text-xs text-danger' : 'text-xs text-warning'}
            >
              {issue.message}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
};
