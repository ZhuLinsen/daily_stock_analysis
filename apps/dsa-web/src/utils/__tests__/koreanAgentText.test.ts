import { describe, expect, test } from 'vitest';
import { localizeAgentProgressMessage, localizeAgentToolName } from '../agentProgressText';
import { localizeStrategySkill, localizeStrategySkillDescription } from '../strategySkill';

describe('Korean Agent display text', () => {
  test.each([
    ['默认多头趋势', '기본 상승 추세'],
    ['均线金叉', '이평선 골든크로스'],
    ['放量突破', '거래량 급증 돌파'],
    ['热点题材', '주도 테마'],
    ['缩量回踩', '거래량 감소 눌림목'],
    ['事件驱动', '이벤트 드리븐'],
    ['箱体震荡', '박스권 매매'],
    ['成长质量', '성장성·품질'],
    ['底部放量', '저점 거래량 급증'],
    ['预期重估', '기대 재평가'],
    ['缠论', '찬론'],
    ['波浪理论', '파동 이론'],
    ['龙头策略', '대장주 전략'],
    ['情绪周期', '투자심리 사이클'],
    ['一阳夹三阴', '일양협삼음'],
  ])('localizes strategy %s', (source, expected) => {
    expect(localizeStrategySkill(source, 'ko')).toBe(expected);
    expect(localizeStrategySkillDescription(source, '원본 설명', 'ko')).not.toMatch(/[\u3400-\u9fff]/u);
  });

  test('localizes live Codex progress and tool labels', () => {
    expect(localizeAgentProgressMessage('正在准备分析…', 'ko')).toBe('분석을 준비하는 중…');
    expect(localizeAgentToolName('get_analysis_context', '获取分析上下文', 'ko')).toBe('분석 컨텍스트 조회');
    expect(localizeAgentToolName('get_tracker_research_bundle', 'get_tracker_research_bundle', 'ko')).toBe('Tracker 리서치 근거 조회');
  });
});
