import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { StrategySynthesis } from '../../../types/analysis';
import { StrategySynthesisCard } from '../StrategySynthesisCard';

const longReasoning = '该策略认为短期趋势仍然偏弱，需要等待成交量、均线结构和市场风险偏好同时改善后再提高仓位。'.repeat(4);

const synthesis: StrategySynthesis = {
  schemaVersion: 'strategy-synthesis-v1',
  finalSignal: 'hold',
  weightedScore: 3,
  confidence: 0.62,
  originalConfidence: 0.8,
  conflictCount: 1,
  conflictSeverity: 'high',
  conflicts: [{
    conflictType: 'directional_opposition',
    severity: 'high',
    descriptionKey: 'strategy_conflict.directional_opposition',
    participants: ['bull', 'bear'],
  }],
  supportingSkills: [{
    skillId: 'neutral-core',
    agentName: 'skill_neutral_core',
    signal: 'hold',
    confidence: 0.6,
    appliedWeight: 0.2,
    reasoning: '等待确认',
  }],
  opposingSkills: [{
    skillId: 'bear-risk',
    agentName: 'skill_bear_risk',
    signal: 'sell',
    confidence: 0.8,
    appliedWeight: 0.4,
    reasoning: longReasoning,
  }],
  signalDistribution: {
    bullish: { count: 1, weightShare: 0.4 },
    neutral: { count: 1, weightShare: 0.2 },
    bearish: { count: 1, weightShare: 0.4 },
  },
  primaryDissent: {
    skillId: 'bear-risk',
    agentName: 'skill_bear_risk',
    signal: 'sell',
    confidence: 0.8,
    appliedWeight: 0.4,
    reasoning: longReasoning,
  },
  consensusLevel: 'low',
  summaryKey: 'strategy_synthesis.with_conflicts',
  summaryParams: {
    opinionCount: 3,
    totalOpinionCount: 4,
    invalidOpinionCount: 1,
    finalSignal: 'hold',
    consensusLevel: 'low',
    conflictSeverity: 'high',
    conflictCount: 1,
  },
  deliberation: {
    status: 'completed',
    mode: 'mediator_v0',
    rounds: 1,
    agenda: [],
    responses: [],
    summary: {
      resolutionStatus: 'partially_resolved',
      resolvedConflictCount: 0,
      unresolvedConflictCount: 1,
      minorityViewPreserved: true,
      confidenceAdjustment: -0.06,
    },
  },
  revisionProjection: {
    status: 'computed',
    mode: 'preview_only',
    sourceMode: 'mediator_v0',
    projectedSignal: 'hold',
    projectedWeightedScore: 3.1,
    projectedConfidence: 0.58,
    projectedOriginalConfidence: 0.7,
    projectedConflictCount: 1,
    projectedConflictSeverity: 'medium',
    projectedConsensusLevel: 'low',
    changedSkillCount: 1,
    changedSkills: ['bear-risk'],
    finalSignalOverridden: false,
  },
};

describe('StrategySynthesisCard', () => {
  it('renders authoritative synthesis, backend distribution, dissent and preview', () => {
    render(<StrategySynthesisCard synthesis={synthesis} language="zh" />);

    expect(screen.getByRole('region', { name: '观点共识与分歧' })).toBeVisible();
    expect(screen.getByText('权威结论')).toBeVisible();
    expect(screen.getByText('无效观点: 1')).toBeVisible();
    expect(screen.getByText('实际权重 0.2000')).toBeVisible();
    expect(screen.getByRole('img', { name: '看多: 权重占比 40%' })).toBeVisible();
    expect(screen.getByRole('region', { name: '主要异议' })).toBeVisible();
    expect(screen.getByRole('region', { name: '协同推理' })).toHaveTextContent('mediator_v0');
    expect(screen.getByRole('region', { name: '协同推理' })).toHaveTextContent('部分解决');
    expect(screen.getByRole('region', { name: '协同推理' })).toHaveTextContent('0 / 1');
    expect(screen.getByRole('region', { name: '协同推理' })).toHaveTextContent('已保留');
    expect(screen.getByRole('region', { name: '协同推理' })).toHaveTextContent('-6%');
    fireEvent.click(screen.getByText('冲突详情 (1)'));
    expect(screen.getByText(/策略方向出现对立/)).toBeVisible();
    expect(screen.queryByText(/directional opposition/i)).not.toBeInTheDocument();
    expect(screen.queryByText('directional_opposition')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: '修订投影' })).toHaveTextContent('预览（非权威，不改变最终信号）');
  });

  it('offers expansion for every non-empty reasoning regardless of character count', () => {
    render(<StrategySynthesisCard synthesis={synthesis} language="zh" />);

    const buttons = screen.getAllByRole('button', { name: '展开理由' });
    expect(buttons).toHaveLength(3);
    expect(buttons[1]).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(buttons[1]);
    expect(buttons[1]).toHaveAttribute('aria-expanded', 'true');
    expect(buttons[1]).toHaveTextContent('收起理由');
  });

  it('renders synchronized English and Korean labels', () => {
    const { rerender } = render(<StrategySynthesisCard synthesis={synthesis} language="en" />);
    expect(screen.getByRole('region', { name: 'Consensus and Dissent' })).toBeVisible();
    expect(screen.getByText('Applied weight 0.2000')).toBeVisible();
    fireEvent.click(screen.getByText('Conflict Details (1)'));
    expect(screen.getByText(/Strategy directions diverge/)).toBeVisible();
    expect(screen.getByRole('region', { name: 'Deliberation' })).toHaveTextContent('Partially resolved');
    expect(screen.getByRole('region', { name: 'Deliberation' })).toHaveTextContent('Preserved');
    expect(screen.getByRole('region', { name: 'Deliberation' })).toHaveTextContent('-6%');
    expect(screen.getByText('Preview (non-authoritative; final signal unchanged)')).toBeVisible();

    rerender(<StrategySynthesisCard synthesis={synthesis} language="ko" />);
    expect(screen.getByRole('region', { name: '합의와 이견' })).toBeVisible();
    expect(screen.getByText('적용 가중치 0.2000')).toBeVisible();
    expect(screen.getByText(/전략 방향이 엇갈립니다/)).toBeVisible();
    expect(screen.getByRole('region', { name: '협업 추론' })).toHaveTextContent('부분 해결');
    expect(screen.getByRole('region', { name: '협업 추론' })).toHaveTextContent('보존됨');
    expect(screen.getByRole('region', { name: '협업 추론' })).toHaveTextContent('-6%');
    expect(screen.getByText('미리보기(비권위, 최종 신호 변경 없음)')).toBeVisible();
  });

  it('does not render without the typed projection', () => {
    const { container } = render(<StrategySynthesisCard synthesis={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
