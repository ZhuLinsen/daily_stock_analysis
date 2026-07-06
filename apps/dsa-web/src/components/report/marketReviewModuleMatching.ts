import type {
  MarketReviewNextSessionPlan,
  MarketReviewPayloadSection,
} from '../../types/analysis';

/**
 * 复盘工作台模块 ↔ 报告叙事 section 的匹配（Issue #1584）。
 *
 * 标题正则与后端 prompt 模板段落保持镜像（src/market_analyzer.py:41-53 与
 * _build_output_template_sections）；编号无关（限数据市场的段落编号会动态
 * 漂移，如 "三、消息催化"）。未匹配的 section（风险提示 / Outlook / 后市展望 /
 * 韩文标题等）作为叙事卡渲染在模块之后。
 */
export type MarketReviewModuleKey =
  | 'conclusion'
  | 'indices'
  | 'breadth'
  | 'sectors'
  | 'catalysts'
  | 'plan';

export interface ModuleSectionMatch {
  /** 每模块吸收的叙事 markdown（多个 section 命中时按原顺序以空行拼接） */
  modules: Partial<Record<MarketReviewModuleKey, string>>;
  /** 未匹配的 section，保持原顺序 */
  narrative: MarketReviewPayloadSection[];
}

const MODULE_TITLE_PATTERNS: Array<{ key: MarketReviewModuleKey; pattern: RegExp }> = [
  { key: 'conclusion', pattern: /盘面总览|市场总结|market\s*summary/i },
  { key: 'indices', pattern: /指数结构|指数点评|主要指数|index\s*commentary|major\s*indices/i },
  { key: 'breadth', pattern: /资金与情绪|资金动向|fund\s*flows?/i },
  { key: 'sectors', pattern: /板块主线|热点解读|板块表现|sector(?:\s*\/?\s*theme)?\s*highlights?/i },
  { key: 'catalysts', pattern: /消息催化|news\s*catalysts?/i },
  { key: 'plan', pattern: /明日交易计划|交易计划|strategy\s*plan/i },
];

export const matchSectionsToModules = (
  sections: MarketReviewPayloadSection[],
): ModuleSectionMatch => {
  const modules: Partial<Record<MarketReviewModuleKey, string>> = {};
  const narrative: MarketReviewPayloadSection[] = [];

  const absorb = (key: MarketReviewModuleKey, markdown: string) => {
    modules[key] = modules[key] ? `${modules[key]}\n\n${markdown}` : markdown;
  };

  for (const section of sections || []) {
    const markdown = (section?.markdown || '').trim();
    if (!markdown) {
      continue;
    }
    // 报告标题下的引言（key: overview）归入一句话结论模块
    if (section.key === 'overview') {
      absorb('conclusion', markdown);
      continue;
    }
    const title = section.title || '';
    const matched = MODULE_TITLE_PATTERNS.find(({ pattern }) => pattern.test(title));
    if (matched) {
      absorb(matched.key, markdown);
    } else {
      narrative.push(section);
    }
  }

  return { modules, narrative };
};

/**
 * 防御性剥表：开发窗口期的过渡记录 sections 仍含注入的数据表；被模块卡
 * 吸收的叙事若带表格会与模块数据重复，剥掉 `|` 表格行与随之变空的
 * `####` 数据块标题。正式后端产出的纯叙事不含表格，不受影响。
 */
export const stripInjectedTables = (markdown: string): string => {
  const lines = (markdown || '').split('\n');
  const kept: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (/^\s*\|.*\|\s*$/.test(line)) {
      continue;
    }
    if (/^####\s/.test(line)) {
      // 后续第一段非空内容若全是表格行，则该 #### 标题属于被剥除的数据块
      let lookahead = index + 1;
      while (lookahead < lines.length && !lines[lookahead].trim()) {
        lookahead += 1;
      }
      if (lookahead >= lines.length || /^\s*\|.*\|\s*$/.test(lines[lookahead])) {
        continue;
      }
    }
    kept.push(line);
  }
  return kept
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
};

export const hasNextSessionPlanContent = (plan?: MarketReviewNextSessionPlan): boolean =>
  Boolean(
    plan
    && (plan.positionAdvice || plan.focusSectors?.length || plan.avoidSectors?.length
      || plan.keyLevels?.length || plan.riskTriggers?.length),
  );


/**
 * 结构化数值格式化（PR #1880 引入，自 MarketReviewReportView 迁至此处共享）：
 * 旧结构化大卡与工作台模块表必须对同一 payload 数值呈现一致的格式。
 */
const coerceFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }

  if (typeof value === 'string' && value.trim()) {
    const normalizedValue = value.trim().replace(/,/g, '');
    const numericText = normalizedValue.endsWith('%')
      ? normalizedValue.slice(0, -1).trim()
      : normalizedValue;
    const parsed = Number(numericText);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

export const formatMarketNumber = (value: unknown, options?: { zeroAsMissing?: boolean }): string => {
  const numericValue = coerceFiniteNumber(value);
  if (numericValue === null || (options?.zeroAsMissing && numericValue === 0)) {
    return '-';
  }
  return numericValue.toFixed(2);
};

export const formatMarketCount = (value: unknown): string => {
  const numericValue = coerceFiniteNumber(value);
  return numericValue === null ? '-' : numericValue.toFixed(0);
};

export const formatMarketAmount = (value: unknown, unit?: string): string => {
  const formattedValue = formatMarketNumber(value);
  if (formattedValue === '-') {
    return '-';
  }
  return unit ? `${formattedValue} ${unit}` : formattedValue;
};

export const formatMarketPercent = (value: unknown): string => {
  const formattedValue = formatMarketNumber(value);
  return formattedValue === '-' ? '-' : `${formattedValue}%`;
};

export const formatMarketHighLow = (high: unknown, low: unknown): string => {
  const highText = formatMarketNumber(high, { zeroAsMissing: true });
  const lowText = formatMarketNumber(low, { zeroAsMissing: true });
  return highText === '-' && lowText === '-' ? '-' : `${highText} / ${lowText}`;
};

/** 指数成交额展示：原始币值 → 亿（zh）/ B·M 紧凑格式（en）；无值返回空 */
export const formatIndexAmount = (amount: unknown, language: 'zh' | 'en'): string => {
  const numeric = typeof amount === 'number' ? amount : Number(amount ?? Number.NaN);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return '';
  }
  if (language === 'zh') {
    return `${(numeric / 1e8).toFixed(0)}亿`;
  }
  if (numeric >= 1e9) {
    return `${(numeric / 1e9).toFixed(1)}B`;
  }
  return `${(numeric / 1e6).toFixed(0)}M`;
};

const ZH_NUMERALS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'] as const;

/** 模块/叙事卡标题编号：zh 用 一、二、…；en/ko 用 1. 2. …（参考截图形态） */
export const formatSectionNumber = (index: number, title: string, language: 'zh' | 'en'): string => {
  if (language === 'zh') {
    const numeral = ZH_NUMERALS[index] ?? String(index + 1);
    return `${numeral}、${title}`;
  }
  return `${index + 1}. ${title}`;
};

/** 剥掉叙事 section 标题里 LLM 自带的编号与装饰前缀（emoji 等），
 * 交由分组统一接续编号；否则会出现"七、⚠️ 七、风险提示"式双重编号 */
export const stripSectionNumbering = (title: string): string =>
  (title || '')
    .replace(/^[^\u4e00-\u9fa5A-Za-z0-9]+/u, '')
    .replace(/^[一二三四五六七八九十]+、\s*/, '')
    .replace(/^\d+[.、]\s*/, '')
    .trim();

/** 多市场 payload 的渲染顺序（镜像后端 _MARKET_REVIEW_REGION_ORDER） */
export const MARKET_REVIEW_REGION_ORDER = ['cn', 'hk', 'us', 'jp', 'kr'] as const;

export const orderMarketEntries = <T,>(markets: Record<string, T>): Array<[string, T]> => {
  const known = MARKET_REVIEW_REGION_ORDER.filter((region) => region in markets).map(
    (region) => [region, markets[region]] as [string, T],
  );
  const unknown = Object.entries(markets).filter(
    ([region]) => !(MARKET_REVIEW_REGION_ORDER as readonly string[]).includes(region),
  );
  return [...known, ...unknown];
};
