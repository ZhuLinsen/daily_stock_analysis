import type { UiLanguage } from '../i18n/uiText';

type StrategyText = { name: string; description: string };

type LocalizableSkill = { id: string; name: string; description: string };

/**
 * Display text for the bundled strategies in `strategies/*.yaml`.
 *
 * The skills API returns the YAML `display_name` / `description`, which are
 * Chinese only. `zh` mirrors the bundled YAML so a skill is only translated
 * while the API still returns the bundled text; a user override or custom
 * skill with the same id keeps whatever text the API returns.
 */
export const BUILTIN_STRATEGY_TEXT: Record<string, Record<UiLanguage, StrategyText>> = {
  bottom_volume: {
    zh: { name: '底部放量', description: '检测长期下跌后底部放量信号，潜在趋势反转信号。' },
    en: { name: 'Bottom Volume Surge', description: 'Detects a volume surge at the bottom after a prolonged decline, a potential trend-reversal signal.' },
  },
  box_oscillation: {
    zh: { name: '箱体震荡', description: '识别价格箱体区间，在箱底买入、箱顶减仓，适用于横盘震荡行情。' },
    en: { name: 'Box Range Trading', description: 'Identifies the price box range: buy near the bottom and trim near the top. Suited to sideways markets.' },
  },
  bull_trend: {
    zh: { name: '默认多头趋势', description: '默认个股分析优先策略，识别多头排列、趋势延续与回踩低吸机会。' },
    en: { name: 'Default Bull Trend', description: 'Default stock analysis strategy: identifies bullish moving-average alignment, trend continuation and pullback entry opportunities.' },
  },
  chan_theory: {
    zh: { name: '缠论', description: '基于缠论笔、线段、中枢结构，判断趋势级别、买卖点与背驰信号。' },
    en: { name: 'Chan Theory', description: 'Uses Chan Theory strokes, segments and pivots to judge trend level, buy/sell points and divergence signals.' },
  },
  dragon_head: {
    zh: { name: '龙头策略', description: '板块轮动中识别龙头股。适用于板块启动或行业催化剂出现时。' },
    en: { name: 'Dragon Head', description: 'Identifies sector-leading stocks during sector rotation. Suited to sector breakouts or new industry catalysts.' },
  },
  emotion_cycle: {
    zh: { name: '情绪周期', description: '基于市场情绪、换手率与量价结构，识别情绪低点（恐慌底）与情绪高点（狂热顶），逆情绪布局。' },
    en: { name: 'Sentiment Cycle', description: 'Uses market sentiment, turnover and price-volume structure to spot sentiment lows (panic bottoms) and highs (euphoric tops) for contrarian positioning.' },
  },
  event_driven: {
    zh: { name: '事件驱动', description: '围绕业绩、政策、并购、订单、产品发布等事件，评估催化强度、兑现概率和风险边界。' },
    en: { name: 'Event Driven', description: 'Assesses catalyst strength, likelihood of realization and risk boundaries around earnings, policy, M&A, orders and product launches.' },
  },
  expectation_repricing: {
    zh: { name: '预期重估', description: '分析业绩预期、政策预期和估值预期的变化，寻找预期差修复或预期过热后的回落风险。' },
    en: { name: 'Expectation Repricing', description: 'Analyzes shifts in earnings, policy and valuation expectations to find expectation-gap recovery or pullback risk after overheated expectations.' },
  },
  growth_quality: {
    zh: { name: '成长质量', description: '结合收入利润增长、ROE、现金流和行业空间，识别高质量成长股与成长失速风险。' },
    en: { name: 'Growth Quality', description: 'Combines revenue and profit growth, ROE, cash flow and industry headroom to identify high-quality growth stocks and growth-stall risk.' },
  },
  hot_theme: {
    zh: { name: '热点题材', description: '跟踪政策、产业和市场热点，判断题材强度、板块扩散和个股相对强弱。' },
    en: { name: 'Hot Theme', description: 'Tracks policy, industry and market hot spots to judge theme strength, sector spillover and the relative strength of individual stocks.' },
  },
  ma_golden_cross: {
    zh: { name: '均线金叉', description: '检测均线金叉配合量能确认信号，经典的趋势反转/延续信号。' },
    en: { name: 'MA Golden Cross', description: 'Detects moving-average golden crosses confirmed by volume, a classic trend reversal/continuation signal.' },
  },
  one_yang_three_yin: {
    zh: { name: '一阳夹三阴', description: '检测一阳夹三阴K线整理形态，趋势延续入场信号。' },
    en: { name: 'One Yang Three Yin', description: 'Detects the one-yang-three-yin candlestick consolidation pattern, a trend-continuation entry signal.' },
  },
  shrink_pullback: {
    zh: { name: '缩量回踩', description: '检测缩量回踩均线支撑信号，趋势延续的理想入场点。' },
    en: { name: 'Shrink Volume Pullback', description: 'Detects low-volume pullbacks to moving-average support, an ideal trend-continuation entry point.' },
  },
  volume_breakout: {
    zh: { name: '放量突破', description: '检测放量突破阻力位信号。适用于股价接近已知阻力位时。' },
    en: { name: 'Volume Breakout', description: 'Detects breakouts above resistance on rising volume. Suited to prices approaching a known resistance level.' },
  },
  wave_theory: {
    zh: { name: '波浪理论', description: '基于艾略特波浪理论的推动浪与调整浪结构，判断当前所处浪型与潜在目标价。' },
    en: { name: 'Elliott Wave Theory', description: 'Uses Elliott Wave impulse and corrective structures to judge the current wave and potential price targets.' },
  },
};

/** Returns the skill with built-in display text translated for the active UI language. */
export function localizeSkill<T extends LocalizableSkill>(skill: T, language: UiLanguage): T {
  // Skill ids come from the API (custom YAML names included), so only look up
  // own keys: ids such as `constructor` must not resolve to Object.prototype.
  if (language === 'zh' || !Object.hasOwn(BUILTIN_STRATEGY_TEXT, skill.id)) {
    return skill;
  }
  const text = BUILTIN_STRATEGY_TEXT[skill.id];
  const localized = text[language];
  return {
    ...skill,
    name: skill.name === text.zh.name ? localized.name : skill.name,
    description: skill.description === text.zh.description ? localized.description : skill.description,
  };
}
