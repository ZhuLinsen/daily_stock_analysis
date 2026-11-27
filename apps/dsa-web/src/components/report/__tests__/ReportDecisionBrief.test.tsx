import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { buildDecisionBriefCopyText, parseStrategySynthesis } from '../../../utils/reportDashboard';
import { ReportDecisionBrief } from '../ReportDecisionBrief';

describe('ReportDecisionBrief', () => {
  it('renders Alert-First risk alerts, position playbook, catalysts, attribution and checklist from camelCase rawResult', () => {
    render(
      <ReportDecisionBrief
        language="zh"
        details={{
          rawResult: {
            dashboard: {
              coreConclusion: {
                oneSentence: '依托 MA20 支撑持有',
                timeSensitivity: '本周内',
                positionAdvice: {
                  noPosition: '回踩 1500 附近分批低吸',
                  hasPosition: '跌破 1420 减仓',
                },
              },
              intelligence: {
                riskAlerts: ['量能不足谨防冲高回落'],
                positiveCatalysts: ['回购计划获批'],
                earningsOutlook: '季度盈利预增',
              },
              battlePlan: {
                positionStrategy: {
                  suggestedPosition: '30% 仓位',
                },
                actionChecklist: [
                  '✅ 无需注意追高风险，多头均线排列',
                  '⚠️ 关注成交量变化',
                  '❌ 未达到放量突破标准',
                ],
              },
              signalAttribution: {
                technicalIndicators: 45,
                newsSentiment: 20,
                fundamentals: 25,
                marketConditions: 10,
                strongestBullishSignal: '放量突破平台',
                strongestBearishSignal: '短期乖离率偏高',
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('决策研报要点')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '风险预警' })).toBeInTheDocument();
    expect(screen.getByText('量能不足谨防冲高回落')).toBeInTheDocument();
    expect(screen.getByText('建议仓位: 30% 仓位')).toBeInTheDocument();
    expect(screen.getByText('回踩 1500 附近分批低吸')).toBeInTheDocument();
    expect(screen.getByText('跌破 1420 减仓')).toBeInTheDocument();
    expect(screen.getByText('回购计划获批')).toBeInTheDocument();
    expect(screen.getByText('45%')).toBeInTheDocument();
    expect(screen.getByText('放量突破平台')).toBeInTheDocument();
    expect(screen.getByText(/通过 1 · 关注 1 · 警示 1/)).toBeInTheDocument();
  });

  it('supports snake_case payloads and localized English labels', () => {
    render(
      <ReportDecisionBrief
        language="en"
        details={{
          rawResult: {
            dashboard: {
              core_conclusion: {
                position_advice: {
                  no_position: 'Accumulate on pullback',
                  has_position: 'Hold above stop',
                },
              },
              intelligence: {
                risk_alerts: ['Earnings volatility ahead'],
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('Decision Brief')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Risk Alerts' })).toBeInTheDocument();
    expect(screen.getByText('Earnings volatility ahead')).toBeInTheDocument();
    expect(screen.getByText('Accumulate on pullback')).toBeInTheDocument();
  });

  it('returns null when structured dashboard fields are absent', () => {
    const { container } = render(<ReportDecisionBrief details={{ rawResult: {} }} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders camelCase multi-strategy synthesis in Chinese with minority dissent and copy brief summary', () => {
    const details = {
      rawResult: {
        dashboard: {
          strategySynthesis: {
            finalSignal: 'buy',
            consensusLevel: 'medium',
            conflictSeverity: 'medium',
            conflictCount: 1,
            confidence: 0.78,
            supportingSkills: [
              { skillId: 'bull_trend', signal: 'buy', confidence: 0.85 },
              { skillId: 'volume_breakout', signal: 'strong_buy', confidence: 0.8 },
            ],
            opposingSkills: [
              { skillId: 'shrink_pullback', signal: 'sell', confidence: 0.76 },
            ],
            summaryParams: {
              opinionCount: 3,
              invalidOpinionCount: 1,
            },
            deliberation: {
              summary: {
                minorityViewPreserved: true,
              },
            },
          },
        },
      },
    };

    render(<ReportDecisionBrief language="zh" details={details} />);

    expect(screen.getByRole('region', { name: '多策略综合' })).toBeInTheDocument();
    expect(screen.getByText('综合信号: 买入')).toBeInTheDocument();
    expect(screen.getByText('共识度: 中')).toBeInTheDocument();
    expect(screen.getByText('冲突: 中 (1)')).toBeInTheDocument();
    expect(screen.getByText('置信度: 78%')).toBeInTheDocument();
    expect(screen.getByText(/来自 3 个策略的综合判断：综合信号为买入/)).toBeInTheDocument();
    expect(screen.getByText('支持策略 (2)')).toBeInTheDocument();
    expect(screen.getByText('反方策略 (1)')).toBeInTheDocument();
    expect(screen.getByText('默认多头趋势')).toBeInTheDocument();
    expect(screen.getByText('放量突破')).toBeInTheDocument();
    expect(screen.getByText('缩量回踩')).toBeInTheDocument();
    expect(screen.getByText(/已保留高置信度少数派异议/)).toBeInTheDocument();
    expect(screen.getByText('另有 1 个策略未能产出有效信号')).toBeInTheDocument();

    const briefText = buildDecisionBriefCopyText({
      meta: {
        queryId: 'q-syn-1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        createdAt: '2026-11-23T10:00:00Z',
      },
      summary: {
        analysisSummary: '趋势突破确认',
        operationAdvice: '买入',
        trendPrediction: '看多',
        sentimentScore: 82,
      },
      details,
      language: 'zh',
    });
    expect(briefText).toContain('多策略综合: 买入 | 共识度: 中 | 冲突: 中 (1) | 置信度: 78%');
  });

  it('supports snake_case strategy_synthesis in English and Korean and ignores malformed payloads', () => {
    const snakeDetails = {
      rawResult: {
        dashboard: {
          strategy_synthesis: {
            final_signal: 'hold',
            consensus_level: 'high',
            conflict_severity: 'none',
            conflict_count: 0,
            confidence: 0.9,
            supporting_skills: [{ skill_id: 'chan_theory', signal: 'hold', confidence: 0.9 }],
            opposing_skills: [],
          },
        },
      },
    };

    const { rerender } = render(<ReportDecisionBrief language="en" details={snakeDetails} />);
    expect(screen.getByRole('region', { name: 'Strategy Synthesis' })).toBeInTheDocument();
    expect(screen.getByText('Final Signal: Hold')).toBeInTheDocument();
    expect(screen.getByText('Consensus: High')).toBeInTheDocument();
    expect(screen.getByText('Conflict: None (0)')).toBeInTheDocument();
    expect(screen.getByText('Chan Theory')).toBeInTheDocument();

    rerender(<ReportDecisionBrief language="ko" details={snakeDetails} />);
    expect(screen.getByRole('region', { name: '전략 종합' })).toBeInTheDocument();
    expect(screen.getByText('종합 신호: 보유')).toBeInTheDocument();
    expect(screen.getByText('찬 이론 구조')).toBeInTheDocument();

    expect(parseStrategySynthesis({ rawResult: { dashboard: { strategySynthesis: 'invalid' } } })).toBeNull();
    expect(parseStrategySynthesis({ rawResult: { dashboard: { strategy_synthesis: { supporting_skills: ['bad'] } } } })).toBeNull();
  });
});
