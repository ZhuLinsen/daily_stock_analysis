import type { UiLanguage } from '../i18n/uiText';

type LocalizedText = Record<UiLanguage, string>;

const TOOL_LABELS: Record<string, LocalizedText> = {
  get_realtime_quote: { zh: '获取实时行情', en: 'Fetching real-time quote', ko: '실시간 시세 조회' },
  get_daily_history: { zh: '获取历史K线', en: 'Fetching price history', ko: '일별 가격 이력 조회' },
  get_chip_distribution: { zh: '分析筹码分布', en: 'Analyzing volume profile', ko: '매물대 분포 분석' },
  get_analysis_context: { zh: '获取分析上下文', en: 'Fetching analysis context', ko: '분석 컨텍스트 조회' },
  get_stock_info: { zh: '获取股票基本面', en: 'Fetching stock fundamentals', ko: '종목 기본정보 조회' },
  search_stock_news: { zh: '搜索股票新闻', en: 'Searching stock news', ko: '종목 뉴스 검색' },
  search_comprehensive_intel: { zh: '搜索综合情报', en: 'Searching market intelligence', ko: '종합 정보 검색' },
  analyze_trend: { zh: '分析技术趋势', en: 'Analyzing technical trend', ko: '기술적 추세 분석' },
  calculate_ma: { zh: '计算均线系统', en: 'Calculating moving averages', ko: '이동평균선 계산' },
  get_volume_analysis: { zh: '分析量能变化', en: 'Analyzing volume changes', ko: '거래량 변화 분석' },
  analyze_pattern: { zh: '识别K线形态', en: 'Identifying candle patterns', ko: '캔들 패턴 식별' },
  get_market_indices: { zh: '获取市场指数', en: 'Fetching market indices', ko: '시장 지수 조회' },
  get_sector_rankings: { zh: '分析行业板块', en: 'Analyzing sector rankings', ko: '업종 순위 분석' },
  get_skill_backtest_summary: { zh: '获取技能回测概览', en: 'Fetching skill backtest summary', ko: '전략 백테스트 요약 조회' },
  get_strategy_backtest_summary: { zh: '获取策略回测概览', en: 'Fetching strategy backtest summary', ko: '전략 백테스트 요약 조회' },
  get_stock_backtest_summary: { zh: '获取个股回测数据', en: 'Fetching stock backtest data', ko: '종목 백테스트 데이터 조회' },
  get_tracker_research_bundle: { zh: '获取 Tracker 研究证据', en: 'Fetching Tracker research evidence', ko: 'Tracker 리서치 근거 조회' },
};

const PROGRESS_TEXT: Record<string, LocalizedText> = {
  codex_connecting: { zh: '正在连接 Codex…', en: 'Connecting to Codex…', ko: 'Codex에 연결하는 중…' },
  preparing: { zh: '正在准备分析…', en: 'Preparing analysis…', ko: '분석을 준비하는 중…' },
  organizing: { zh: '正在整理分析结果…', en: 'Organizing analysis results…', ko: '분석 결과를 정리하는 중…' },
  planning: { zh: '正在制定分析路径…', en: 'Planning the analysis…', ko: '분석 경로를 수립하는 중…' },
  generating: { zh: '正在生成最终分析…', en: 'Generating final analysis…', ko: '최종 분석을 생성하는 중…' },
};

const PROGRESS_ALIASES: Record<string, keyof typeof PROGRESS_TEXT> = {
  '正在连接 Codex…': 'codex_connecting',
  '正在准备分析…': 'preparing',
  '正在整理分析结果…': 'organizing',
  '正在制定分析路径...': 'planning',
  '正在制定分析路径…': 'planning',
  '正在生成最终分析...': 'generating',
  '正在生成最终分析…': 'generating',
  'Connecting to Codex…': 'codex_connecting',
  'Preparing analysis…': 'preparing',
  'Organizing analysis results…': 'organizing',
  'Planning the analysis…': 'planning',
  'Generating final analysis…': 'generating',
};

export function localizeAgentToolName(
  tool: string | null | undefined,
  fallback: string | null | undefined,
  language: UiLanguage,
): string {
  const known = TOOL_LABELS[String(tool || '').trim()];
  return known ? known[language] : String(fallback || tool || '').trim();
}

export function localizeAgentProgressMessage(
  value: string | null | undefined,
  language: UiLanguage,
): string {
  const message = String(value || '').trim();
  const key = PROGRESS_ALIASES[message];
  return key ? PROGRESS_TEXT[key][language] : message;
}
