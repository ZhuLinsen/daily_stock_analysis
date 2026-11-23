import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button, Input } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { ConfigValidationIssue, SystemConfigUpdateItem } from '../../types/systemConfig';
import { isEmailGroupKey } from '../../utils/emailGroups';
import { SettingsSectionCard } from './SettingsSectionCard';

interface EmailGroupEditorProps {
  items: SystemConfigUpdateItem[];
  issueByKey: Record<string, ConfigValidationIssue[]>;
  disabled: boolean;
  onChange: (items: SystemConfigUpdateItem[]) => void;
}

export function EmailGroupEditor({ items, issueByKey, disabled, onChange }: EmailGroupEditorProps) {
  const { t } = useUiLanguage();
  const [addedIds, setAddedIds] = useState<string[]>([]);
  const values = Object.fromEntries(items.filter((item) => isEmailGroupKey(item.key)).map((item) => [item.key, item.value]));
  const savedIds = Object.keys(values).map((key) => key.split('_')[2]);
  const groupIds = [...new Set([...savedIds, ...addedIds])]
    .filter((id) => addedIds.includes(id) || values[`STOCK_GROUP_${id}`]?.trim() || values[`EMAIL_GROUP_${id}`]?.trim())
    .sort((left, right) => Number(left) - Number(right));

  const addGroup = () => {
    const id = String(Math.max(0, ...savedIds.map(Number), ...addedIds.map(Number)) + 1);
    setAddedIds((previous) => [...previous, id]);
  };

  const removeGroup = (id: string) => {
    onChange([{ key: `STOCK_GROUP_${id}`, value: '' }, { key: `EMAIL_GROUP_${id}`, value: '' }]);
    setAddedIds((previous) => previous.filter((entry) => entry !== id));
  };

  return (
    <SettingsSectionCard
      title={t('settings.emailGroupsTitle')}
      description={t('settings.emailGroupsDescription')}
      actions={(
        <Button type="button" variant="settings-secondary" size="sm" disabled={disabled} onClick={addGroup}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          {t('settings.emailGroupsAdd')}
        </Button>
      )}
    >
      {groupIds.length === 0 ? <p className="text-sm text-muted-text">{t('settings.emailGroupsEmpty')}</p> : null}
      {groupIds.map((id) => (
        <div key={id} className="space-y-3 rounded-lg border settings-border p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-medium text-foreground">{t('settings.emailGroupsNumber', { id })}</h3>
            <Button
              type="button"
              variant="settings-secondary"
              size="sm"
              disabled={disabled}
              aria-label={t('settings.emailGroupsRemove', { id })}
              onClick={() => removeGroup(id)}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              {t('common.delete')}
            </Button>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Input
              label={t('settings.emailGroupsStocks')}
              placeholder="600519,300750,AAPL"
              value={values[`STOCK_GROUP_${id}`] ?? ''}
              disabled={disabled}
              error={issueByKey[`STOCK_GROUP_${id}`]?.map((issue) => issue.message).join(' ')}
              onChange={(event) => onChange([{ key: `STOCK_GROUP_${id}`, value: event.target.value.replace(/，/g, ',') }])}
            />
            <Input
              label={t('settings.emailGroupsRecipients')}
              placeholder="user1@example.com,user2@example.com"
              value={values[`EMAIL_GROUP_${id}`] ?? ''}
              disabled={disabled}
              error={issueByKey[`EMAIL_GROUP_${id}`]?.map((issue) => issue.message).join(' ')}
              onChange={(event) => onChange([{ key: `EMAIL_GROUP_${id}`, value: event.target.value.replace(/，/g, ',') }])}
            />
          </div>
        </div>
      ))}
    </SettingsSectionCard>
  );
}
