import type React from 'react';
import { Badge } from '../common';

type RiskTagsProps = {
  risks?: string[];
  opportunities?: string[];
  watches?: string[];
  status?: string;
  className?: string;
};

function statusVariant(status: string): 'danger' | 'success' | 'info' | 'default' | 'warning' {
  if (['高位风险', '破位减仓', '资金流出'].includes(status)) return 'danger';
  if (['强势突破', '趋势持有'].includes(status)) return 'success';
  if (['缩量等待', '等待确认'].includes(status)) return 'info';
  return 'default';
}

export const RiskTags: React.FC<RiskTagsProps> = ({ risks = [], opportunities = [], watches = [], status, className = '' }) => (
  <div className={`flex flex-wrap gap-1.5 ${className}`}>
    {status ? <Badge variant={statusVariant(status)}>{status}</Badge> : null}
    {risks.map((item) => <Badge key={`risk-${item}`} variant="danger">{item}</Badge>)}
    {opportunities.map((item) => <Badge key={`opp-${item}`} variant="success">{item}</Badge>)}
    {watches.map((item) => <Badge key={`watch-${item}`} variant="info">{item}</Badge>)}
  </div>
);
