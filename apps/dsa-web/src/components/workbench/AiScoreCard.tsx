import type React from 'react';
import { BrainCircuit, ShieldAlert, Target, TrendingUp } from 'lucide-react';
import { Card } from '../common';
import type { AiScorePayload } from '../../types/workbench';
import { clamp } from './format';
import { RiskTags } from './RiskTags';

type AiScoreCardProps = {
  analysis: AiScorePayload;
  riskTags?: string[];
  opportunityTags?: string[];
  watchTags?: string[];
  compact?: boolean;
};

const scoreTone = (score: number): string => {
  if (score >= 75) return 'text-red-500 dark:text-red-300';
  if (score >= 55) return 'text-cyan';
  return 'text-amber-500';
};

export const AiScoreCard: React.FC<AiScoreCardProps> = ({ analysis, riskTags = [], opportunityTags = [], watchTags = [], compact = false }) => {
  const score = clamp(Number(analysis.aiScore || 0));
  const meterStyle = { width: `${score}%` };

  return (
    <Card className="rounded-lg" padding={compact ? 'sm' : 'md'}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="label-uppercase">AI 评分卡</p>
            <h3 className="mt-1 text-lg font-semibold text-foreground">{analysis.name || analysis.symbol}</h3>
          </div>
          <div className="text-right">
            <div className={`text-4xl font-semibold leading-none ${scoreTone(score)}`}>{score}</div>
            <div className="mt-1 text-xs text-secondary-text">/ 100</div>
          </div>
        </div>
        <div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-gradient-to-r from-cyan via-amber-400 to-red-500" style={meterStyle} />
          </div>
          <RiskTags
            className="mt-3"
            status={analysis.statusTag}
            risks={riskTags}
            opportunities={opportunityTags}
            watches={watchTags}
          />
        </div>
        <p className="text-sm leading-6 text-secondary-text">{analysis.summary}</p>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-border/60 bg-card/60 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground"><TrendingUp className="h-4 w-4 text-cyan" /> 趋势</div>
            <p className="mt-2 text-xs leading-5 text-secondary-text">{analysis.trend.direction} · 强度 {analysis.trend.strength}</p>
          </div>
          <div className="rounded-lg border border-border/60 bg-card/60 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground"><BrainCircuit className="h-4 w-4 text-cyan" /> 技术</div>
            <p className="mt-2 text-xs leading-5 text-secondary-text">{analysis.technical.summary}</p>
          </div>
          <div className="rounded-lg border border-border/60 bg-card/60 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground"><ShieldAlert className="h-4 w-4 text-cyan" /> 风险</div>
            <p className="mt-2 text-xs leading-5 text-secondary-text">{analysis.risks.slice(0, 2).join('；')}</p>
          </div>
        </div>
        {!compact ? (
          <div className="rounded-lg border border-cyan/20 bg-cyan/10 p-3 text-sm text-cyan">
            <div className="flex items-center gap-2 font-medium"><Target className="h-4 w-4" /> 明日观察位</div>
            <div className="mt-2 grid gap-1.5 text-xs leading-5">
              {analysis.nextDayWatch.map((item) => <span key={item}>{item}</span>)}
            </div>
          </div>
        ) : null}
        <p className="text-xs text-secondary-text">{analysis.disclaimer}</p>
      </div>
    </Card>
  );
};
