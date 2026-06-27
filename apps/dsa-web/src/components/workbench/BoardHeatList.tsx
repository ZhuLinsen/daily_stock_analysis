import type React from 'react';
import { Flame } from 'lucide-react';
import { Card, EmptyState } from '../common';
import type { BoardHeatItem } from '../../types/workbench';
import { formatPercent, signedClass } from './format';

type BoardHeatListProps = {
  title: string;
  items: BoardHeatItem[];
};

export const BoardHeatList: React.FC<BoardHeatListProps> = ({ title, items }) => {
  return (
    <Card className="rounded-lg" padding="sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Flame className="h-4 w-4 text-amber-500" />
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
        </div>
        <span className="text-xs text-secondary-text">板块热力榜</span>
      </div>
      {items.length === 0 ? (
        <EmptyState title="暂无板块数据" className="rounded-lg py-8" />
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => {
            const width = Math.max(8, Math.min(100, Math.abs(item.changePct ?? 0) * 12));
            return (
              <div key={`${item.name}-${index}`} className="rounded-lg border border-border/55 bg-card/65 p-2.5">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate font-medium text-foreground">{index + 1}. {item.name}</span>
                  <span className={signedClass(item.changePct)}>{formatPercent(item.changePct)}</span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-cyan" style={{ width: `${width}%` }} />
                </div>
                {item.leadingStock ? <p className="mt-1 text-xs text-secondary-text">领涨：{item.leadingStock}</p> : null}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
};
