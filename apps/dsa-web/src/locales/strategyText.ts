import type { UiLanguage } from '../i18n/uiText';

type StrategyText = { name: string; description: string };

export type LocalizableSkill = { id: string; name: string; description: string };

type MessageSkillSource = {
  skills?: string[];
  skill?: string;
  skillNames?: string[];
  skillName?: string;
};

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
  bollinger_squeeze: {
    zh: { name: '布林带收口突破', description: '识别布林带带宽极值收口后的放量方向突破，结合ATR波动扩张与ADX确认趋势启动。' },
    en: { name: 'Bollinger Squeeze', description: 'Detects directional volume breakouts after extreme Bollinger bandwidth compression using ATR expansion and ADX confirmation.' },
  },
  rsi_mean_reversion: {
    zh: { name: 'RSI/KDJ 均值回归', description: '在震荡市利用ADX过滤强趋势，结合RSI超卖、KDJ低位金叉与布林带下轨偏离捕捉均值回归机会。' },
    en: { name: 'RSI/KDJ Mean Reversion', description: 'Filters strong trends with ADX in sideways markets and captures rebound setups via RSI oversold, low KDJ crosses, and lower-band deviations.' },
  },
  turtle_donchian: {
    zh: { name: '海龟唐奇安趋势', description: '经典海龟交易法则，以20日唐奇安高点突破入场、10日低点或2倍ATR动态止损并按波动率控制仓位。' },
    en: { name: 'Turtle Donchian', description: 'Classic Turtle rule system entering on 20-day Donchian breakouts with 10-day low or 2x ATR stops and volatility-sized risk.' },
  },
  momentum_quality: {
    zh: { name: '动量低波复合因子', description: '融合20/60日价格动量、年化波动率与最大回撤约束，辅以VWAP/OBV资金流确认的中期量化多因子策略。' },
    en: { name: 'Momentum Low-Vol Quality', description: 'Blends 20/60-day momentum with annualized volatility and max-drawdown limits, confirmed by VWAP and OBV money flow.' },
  },
  vcp_breakout: {
    zh: { name: 'VCP 波动收敛突破', description: '基于Minervini波动收敛形态，筛选多头排列中振幅与成交量逐级收敛、紧贴阶段高点蓄势突破的强势股。' },
    en: { name: 'VCP Breakout', description: 'Based on Minervini Volatility Contraction Pattern, screens Stage-2 leaders with tightening range and dry volume near highs.' },
  },
};

export type StrategyCategoryId = 'all' | 'quant' | 'trend' | 'pattern_reversal' | 'framework';

export const BUILTIN_STRATEGY_CATEGORIES: readonly StrategyCategoryId[] = [
  'all',
  'quant',
  'trend',
  'pattern_reversal',
  'framework',
] as const;

export const STRATEGY_CATEGORY_LABELS: Record<StrategyCategoryId, Record<UiLanguage, string>> = {
  all: { zh: '全部', en: 'All' },
  quant: { zh: '量化因子', en: 'Quant' },
  trend: { zh: '趋势顺势', en: 'Trend' },
  pattern_reversal: { zh: '形态/反转', en: 'Pattern & Reversal' },
  framework: { zh: '综合框架', en: 'Framework' },
};

const STRATEGY_CATEGORY_MAP: Record<string, Exclude<StrategyCategoryId, 'all'>> = {
  bollinger_squeeze: 'quant',
  rsi_mean_reversion: 'quant',
  turtle_donchian: 'quant',
  momentum_quality: 'quant',
  vcp_breakout: 'quant',
  bull_trend: 'trend',
  dragon_head: 'trend',
  ma_golden_cross: 'trend',
  shrink_pullback: 'trend',
  volume_breakout: 'trend',
  bottom_volume: 'pattern_reversal',
  one_yang_three_yin: 'pattern_reversal',
  box_oscillation: 'framework',
  chan_theory: 'framework',
  emotion_cycle: 'framework',
  event_driven: 'framework',
  expectation_repricing: 'framework',
  growth_quality: 'framework',
  hot_theme: 'framework',
  wave_theory: 'framework',
};

const API_CATEGORY_TO_PICKER: Record<string, Exclude<StrategyCategoryId, 'all'>> = {
  quant: 'quant',
  trend: 'trend',
  pattern: 'pattern_reversal',
  reversal: 'pattern_reversal',
  pattern_reversal: 'pattern_reversal',
  framework: 'framework',
  general: 'framework',
};

/** Resolve UI display category bucket for a built-in or custom strategy id. */
export function getStrategyCategory(
  id: string,
  apiCategory?: string | null,
): Exclude<StrategyCategoryId, 'all'> {
  if (typeof apiCategory === 'string') {
    const normalized = apiCategory.trim().toLowerCase();
    if (Object.hasOwn(API_CATEGORY_TO_PICKER, normalized)) {
      return API_CATEGORY_TO_PICKER[normalized];
    }
  }
  if (Object.hasOwn(STRATEGY_CATEGORY_MAP, id)) {
    return STRATEGY_CATEGORY_MAP[id];
  }
  return 'framework';
}

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

/**
 * Localizes a historical/fallback skill display name without treating display
 * names as built-in strategy IDs (prevents custom skills named e.g.
 * `ma_golden_cross` from being mislabeled as the built-in strategy).
 */
export function localizeBuiltInSkillDisplayName(name: string, language: UiLanguage): string {
  if (language === 'en' && name === '通用') {
    return 'General';
  }
  if (language === 'zh' && name === 'General') {
    return '通用';
  }
  const sourceLocale: UiLanguage = language === 'en' ? 'zh' : 'en';
  for (const entry of Object.values(BUILTIN_STRATEGY_TEXT)) {
    if (entry[sourceLocale].name === name) {
      return entry[language].name;
    }
  }
  return name;
}

/** Resolves message skill badges/headers using skill IDs when present and display-name lookup otherwise. */
export function resolveMessageSkillLabels(
  msg: MessageSkillSource,
  language: UiLanguage,
  availableSkills?: ReadonlyArray<LocalizableSkill>,
): string[] {
  const skillIds = msg.skills?.length
    ? msg.skills
    : msg.skill
      ? [msg.skill]
      : [];
  const rawNames = msg.skillNames?.length
    ? msg.skillNames
    : msg.skillName
      ? [msg.skillName]
      : [];

  if (skillIds.length > 0) {
    return skillIds.map((id, index) => {
      const rawName = rawNames[index];
      const matched = availableSkills?.find((skill) => skill.id === id);
      if (matched) {
        return localizeSkill(matched, language).name;
      }
      if (Object.hasOwn(BUILTIN_STRATEGY_TEXT, id)) {
        const entry = BUILTIN_STRATEGY_TEXT[id];
        if (!rawName || rawName === id || rawName === entry.zh.name || rawName === entry.en.name) {
          return entry[language].name;
        }
        return rawName;
      }
      const fallback = rawName || id;
      if (language === 'en' && fallback === '通用') {
        return 'General';
      }
      if (language === 'zh' && fallback === 'General') {
        return '通用';
      }
      return fallback;
    });
  }

  return rawNames.map((name) => localizeBuiltInSkillDisplayName(name, language));
}

/** @deprecated Prefer `resolveMessageSkillLabels` / `localizeBuiltInSkillDisplayName`. */
export function localizeSkillLabel(name: string, language: UiLanguage): string {
  return localizeBuiltInSkillDisplayName(name, language);
}
