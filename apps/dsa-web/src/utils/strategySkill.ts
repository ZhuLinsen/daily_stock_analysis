import type { UiLanguage } from '../i18n/uiText';

type StrategySkillId =
  | 'bull_trend'
  | 'ma_golden_cross'
  | 'volume_breakout'
  | 'hot_theme'
  | 'shrink_pullback'
  | 'event_driven'
  | 'box_oscillation'
  | 'growth_quality'
  | 'bottom_volume'
  | 'expectation_repricing'
  | 'chan_theory'
  | 'wave_theory'
  | 'dragon_head'
  | 'emotion_cycle'
  | 'one_yang_three_yin';

type LocalizedText = Record<UiLanguage, string>;

const SKILL_LABELS: Record<StrategySkillId, LocalizedText> = {
  bull_trend: { zh: '默认多头趋势', en: 'Bull Trend', ko: '기본 상승 추세' },
  ma_golden_cross: { zh: '均线金叉', en: 'MA Golden Cross', ko: '이평선 골든크로스' },
  volume_breakout: { zh: '放量突破', en: 'Volume Breakout', ko: '거래량 급증 돌파' },
  hot_theme: { zh: '热点题材', en: 'Hot Theme', ko: '주도 테마' },
  shrink_pullback: { zh: '缩量回踩', en: 'Shrink Pullback', ko: '거래량 감소 눌림목' },
  event_driven: { zh: '事件驱动', en: 'Event Driven', ko: '이벤트 드리븐' },
  box_oscillation: { zh: '箱体震荡', en: 'Box Oscillation', ko: '박스권 매매' },
  growth_quality: { zh: '成长质量', en: 'Growth Quality', ko: '성장성·품질' },
  bottom_volume: { zh: '底部放量', en: 'Bottom Volume', ko: '저점 거래량 급증' },
  expectation_repricing: { zh: '预期重估', en: 'Expectation Repricing', ko: '기대 재평가' },
  chan_theory: { zh: '缠论', en: 'Chan Theory', ko: '찬론' },
  wave_theory: { zh: '波浪理论', en: 'Wave Theory', ko: '파동 이론' },
  dragon_head: { zh: '龙头策略', en: 'Dragon Head', ko: '대장주 전략' },
  emotion_cycle: { zh: '情绪周期', en: 'Emotion Cycle', ko: '투자심리 사이클' },
  one_yang_three_yin: { zh: '一阳夹三阴', en: 'One Yang Three Yin', ko: '일양협삼음' },
};

const SKILL_DESCRIPTIONS: Record<StrategySkillId, LocalizedText> = {
  bull_trend: {
    zh: '默认个股分析优先策略，识别多头排列、趋势延续与回踩低吸机会。',
    en: 'Default stock-analysis strategy for bullish alignment, trend continuation, and pullback entries.',
    ko: '기본 종목 분석 전략으로 정배열, 추세 지속, 눌림목 진입 기회를 식별합니다.',
  },
  ma_golden_cross: {
    zh: '检测均线金叉配合量能确认信号，经典的趋势反转/延续信号。',
    en: 'Evaluates moving-average golden crosses with volume confirmation for trend reversal or continuation.',
    ko: '이동평균선 골든크로스와 거래량 확인 신호를 분석하는 대표적인 추세 반전·지속 전략입니다.',
  },
  volume_breakout: {
    zh: '检测放量突破阻力位信号。适用于股价接近已知阻力位时。',
    en: 'Detects volume-backed resistance breakouts when a price approaches a known resistance level.',
    ko: '저항선 돌파 시 거래량 증가 신호를 분석합니다. 주가가 알려진 저항선 부근에 있을 때 적합합니다.',
  },
  hot_theme: {
    zh: '跟踪政策、产业和市场热点，判断题材强度、板块扩散和个股相对强弱。',
    en: 'Tracks policy, industry, and market themes to assess theme strength, sector breadth, and relative stock strength.',
    ko: '정책·산업·시장 테마를 추적하여 테마 강도, 섹터 확산, 종목 상대 강도를 판단합니다.',
  },
  shrink_pullback: {
    zh: '检测缩量回踩均线支撑信号，趋势延续的理想入场点。',
    en: 'Detects low-volume pullbacks to moving-average support as potential trend-continuation entries.',
    ko: '거래량이 감소한 이동평균선 눌림 신호를 분석하는 추세 지속형 진입 전략입니다.',
  },
  event_driven: {
    zh: '围绕业绩、政策、并购、订单、产品发布等事件，评估催化强度、兑现概率和风险边界。',
    en: 'Evaluates catalysts from earnings, policy, M&A, orders, and product events.',
    ko: '실적·정책·인수합병·수주·제품 출시 등의 이벤트를 바탕으로 촉매 강도, 실현 가능성, 위험 한계를 평가합니다.',
  },
  box_oscillation: {
    zh: '识别价格箱体区间，在箱底买入、箱顶减仓，适用于横盘震荡行情。',
    en: 'Identifies price ranges for lower-range entries and upper-range trims in sideways markets.',
    ko: '가격 박스권을 식별하여 하단 매수·상단 비중 축소 기회를 분석합니다. 횡보장에 적합합니다.',
  },
  growth_quality: {
    zh: '结合收入利润增长、ROE、现金流和行业空间，识别高质量成长股与成长失速风险。',
    en: 'Combines growth, ROE, cash flow, and industry runway to identify quality growth and slowdown risk.',
    ko: '매출·이익 성장, ROE, 현금흐름, 산업 성장 여력을 종합해 고품질 성장주와 성장 둔화 위험을 식별합니다.',
  },
  bottom_volume: {
    zh: '检测长期下跌后底部放量信号，潜在趋势反转信号。',
    en: 'Detects volume expansion at a base after a prolonged decline as a potential reversal signal.',
    ko: '장기 하락 후 저점 거래량 급증 신호를 분석해 잠재적 추세 반전을 찾습니다.',
  },
  expectation_repricing: {
    zh: '分析业绩预期、政策预期和估值预期的变化，寻找预期差修复或预期过热后的回落风险。',
    en: 'Analyzes changing earnings, policy, and valuation expectations.',
    ko: '실적·정책·밸류에이션 기대 변화로 기대 차이 회복 또는 과열 후 조정 위험을 분석합니다.',
  },
  chan_theory: {
    zh: '基于缠论笔、线段、中枢结构，判断趋势级别、买卖点与背驰信号。',
    en: 'Uses Chan-theory structures to assess trend scale, trade points, and divergence.',
    ko: '찬론의 필선·구간·중심 구조를 바탕으로 추세 단계, 매매 시점, 다이버전스 신호를 판단합니다.',
  },
  wave_theory: {
    zh: '基于艾略特波浪理论的推动浪与调整浪结构，判断当前所处浪型与潜在目标价。',
    en: 'Uses Elliott impulse and corrective-wave structures to assess the current wave and potential targets.',
    ko: '엘리엇 파동 이론의 추진파와 조정파 구조를 바탕으로 현재 파동과 잠재 목표가를 판단합니다.',
  },
  dragon_head: {
    zh: '板块轮动中识别龙头股。适用于板块启动或行业催化剂出现时。',
    en: 'Identifies leading stocks during sector rotation and industry catalysts.',
    ko: '섹터 순환에서 대장주를 식별합니다. 섹터가 시작되거나 업종 촉매가 나타날 때 적합합니다.',
  },
  emotion_cycle: {
    zh: '基于市场情绪、换手率与量价结构，识别情绪低点与情绪高点，逆情绪布局。',
    en: 'Uses sentiment, turnover, and price-volume structure to identify fear lows and exuberance highs.',
    ko: '시장 심리, 회전율, 거래량·가격 구조를 바탕으로 공포 저점과 과열 고점을 식별해 역심리 관점의 진입 기회를 찾습니다.',
  },
  one_yang_three_yin: {
    zh: '检测一阳夹三阴K线整理形态，趋势延续入场信号。',
    en: 'Detects the one-yang-between-three-yin consolidation pattern as a trend-continuation entry signal.',
    ko: '일양협삼음 캔들 정리 패턴을 분석하는 추세 지속형 진입 신호입니다.',
  },
};

const ALIASES: Record<string, StrategySkillId> = {
  bull_trend: 'bull_trend',
  'bull trend': 'bull_trend',
  默认多头趋势: 'bull_trend',
  ma_golden_cross: 'ma_golden_cross',
  'ma golden cross': 'ma_golden_cross',
  均线金叉: 'ma_golden_cross',
  volume_breakout: 'volume_breakout',
  'volume breakout': 'volume_breakout',
  放量突破: 'volume_breakout',
  hot_theme: 'hot_theme',
  'hot theme': 'hot_theme',
  热点题材: 'hot_theme',
  shrink_pullback: 'shrink_pullback',
  'shrink pullback': 'shrink_pullback',
  缩量回踩: 'shrink_pullback',
  event_driven: 'event_driven',
  'event driven': 'event_driven',
  事件驱动: 'event_driven',
  box_oscillation: 'box_oscillation',
  'box oscillation': 'box_oscillation',
  箱体震荡: 'box_oscillation',
  growth_quality: 'growth_quality',
  'growth quality': 'growth_quality',
  成长质量: 'growth_quality',
  bottom_volume: 'bottom_volume',
  'bottom volume': 'bottom_volume',
  底部放量: 'bottom_volume',
  expectation_repricing: 'expectation_repricing',
  'expectation repricing': 'expectation_repricing',
  预期重估: 'expectation_repricing',
  chan_theory: 'chan_theory',
  'chan theory': 'chan_theory',
  缠论: 'chan_theory',
  缠论结构: 'chan_theory',
  wave_theory: 'wave_theory',
  'wave theory': 'wave_theory',
  波浪理论: 'wave_theory',
  dragon_head: 'dragon_head',
  'dragon head': 'dragon_head',
  龙头策略: 'dragon_head',
  龙头战法: 'dragon_head',
  emotion_cycle: 'emotion_cycle',
  'emotion cycle': 'emotion_cycle',
  情绪周期: 'emotion_cycle',
  one_yang_three_yin: 'one_yang_three_yin',
  'one yang three yin': 'one_yang_three_yin',
  一阳夹三阴: 'one_yang_three_yin',
  一阳三阴: 'one_yang_three_yin',
};

function resolveSkillId(value: string | null | undefined): StrategySkillId | null {
  const normalized = String(value || '').trim().toLocaleLowerCase();
  return ALIASES[normalized] || null;
}

export function localizeStrategySkill(
  value: string | null | undefined,
  language: UiLanguage,
): string {
  const skillId = resolveSkillId(value);
  return skillId ? SKILL_LABELS[skillId][language] : String(value || '').trim();
}

export function localizeStrategySkillDescription(
  skillIdOrName: string | null | undefined,
  fallback: string | null | undefined,
  language: UiLanguage,
): string {
  const skillId = resolveSkillId(skillIdOrName);
  return skillId ? SKILL_DESCRIPTIONS[skillId][language] : String(fallback || '').trim();
}
