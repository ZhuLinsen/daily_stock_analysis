import type { ReportLanguage } from '../types/analysis';

export interface QuantChartText {
  windowGroupLabel: string;
  window20D: string;
  window40D: string;
  window60D: string;
  windowAll: string;
  overlayGroupLabel: string;
  ma60: string;
  boll: string;
  bollUpper: string;
  bollLower: string;
  subPanelGroupLabel: string;
  subOff: string;
  subRsi: string;
  subMacd: string;
  subKdj: string;
  subPanelInsufficientData: string;
  subPanelMissingHighLow: string;
  unadjustedNotice: string;
  riskReward: string;
  ma20Bias: string;
  annualizedVol: string;
  maxDrawdown: string;
  bollBandwidth: string;
  squeeze: string;
  oversold: string;
  overbought: string;
  neutral: string;
  goldenCross: string;
  deathCross: string;
  bullish: string;
  bearish: string;
  atrPct: string;
  open: string;
}

const QUANT_CHART_TEXT: Record<ReportLanguage, QuantChartText> = {
  zh: {
    windowGroupLabel: 'K线窗口周期',
    window20D: '20D',
    window40D: '40D',
    window60D: '60D',
    windowAll: '全部',
    overlayGroupLabel: '主图量化叠加层',
    ma60: 'MA60',
    boll: 'BOLL',
    bollUpper: 'BOLL上轨',
    bollLower: 'BOLL下轨',
    subPanelGroupLabel: '附图量化指标面板',
    subOff: '关闭',
    subRsi: 'RSI(14)',
    subMacd: 'MACD',
    subKdj: 'KDJ',
    subPanelInsufficientData: '至少需要 {minBars} 个交易日以计算 {indicator}',
    subPanelMissingHighLow: '缺少有效最高/最低价数据，暂无法计算 {indicator}',
    unadjustedNotice: '当前数据源返回未复权历史行情，存在拆合股或除权除息时可能使涨跌、波动率与技术指标失真，已暂停相关跨日统计与指标曲线。',
    riskReward: '盈亏比',
    ma20Bias: 'MA20乖离',
    annualizedVol: '年化波动',
    maxDrawdown: '回撤',
    bollBandwidth: 'BOLL带宽',
    squeeze: '收口蓄势',
    oversold: '超卖',
    overbought: '超买',
    neutral: '中性',
    goldenCross: '金叉',
    deathCross: '死叉',
    bullish: '多头',
    bearish: '空头',
    atrPct: 'ATR%',
    open: '开盘',
  },
  en: {
    windowGroupLabel: 'Chart lookback window',
    window20D: '20D',
    window40D: '40D',
    window60D: '60D',
    windowAll: 'All',
    overlayGroupLabel: 'Technical chart overlays',
    ma60: 'MA60',
    boll: 'BOLL',
    bollUpper: 'BOLL Upper',
    bollLower: 'BOLL Lower',
    subPanelGroupLabel: 'Quantitative sub-panel indicator',
    subOff: 'Off',
    subRsi: 'RSI(14)',
    subMacd: 'MACD',
    subKdj: 'KDJ',
    subPanelInsufficientData: 'Needs at least {minBars} sessions to compute {indicator}',
    subPanelMissingHighLow: 'Valid high/low range data is unavailable to compute {indicator}',
    unadjustedNotice: 'This history source returned unadjusted prices. Corporate actions such as splits may distort multi-session return, volatility, and technical indicators, so cross-session analytics are paused.',
    riskReward: 'R:R',
    ma20Bias: 'MA20 Bias',
    annualizedVol: 'Ann.Vol',
    maxDrawdown: 'MaxDD',
    bollBandwidth: 'BOLL BW',
    squeeze: 'Squeeze',
    oversold: 'Oversold',
    overbought: 'Overbought',
    neutral: 'Neutral',
    goldenCross: 'Golden Cross',
    deathCross: 'Death Cross',
    bullish: 'Bullish',
    bearish: 'Bearish',
    atrPct: 'ATR%',
    open: 'Open',
  },
  ko: {
    windowGroupLabel: '차트 조회 기간',
    window20D: '20D',
    window40D: '40D',
    window60D: '60D',
    windowAll: '전체',
    overlayGroupLabel: '보조 지표 오버레이',
    ma60: 'MA60',
    boll: 'BOLL',
    bollUpper: 'BOLL 상단',
    bollLower: 'BOLL 하단',
    subPanelGroupLabel: '정량 보조 지표 패널',
    subOff: '끄기',
    subRsi: 'RSI(14)',
    subMacd: 'MACD',
    subKdj: 'KDJ',
    subPanelInsufficientData: '{indicator} 계산에 최소 {minBars}거래일 필요',
    subPanelMissingHighLow: '유효한 고가/저가 데이터가 없어 {indicator}를 계산할 수 없습니다',
    unadjustedNotice: '현재 데이터 소스가 수정주가가 아닌 미조정 일봉을 반환했습니다. 액면분할 등 권리락 구간 왜곡을 막기 위해 기간 수익률·변동성 및 보조지표 계산을 일시 중지합니다.',
    riskReward: '손익비',
    ma20Bias: 'MA20 이격',
    annualizedVol: '연율 변동성',
    maxDrawdown: '최대낙폭',
    bollBandwidth: 'BOLL 밴드폭',
    squeeze: '수축',
    oversold: '과매도',
    overbought: '과매수',
    neutral: '중립',
    goldenCross: '골든크로스',
    deathCross: '데드크로스',
    bullish: '강세',
    bearish: '약세',
    atrPct: 'ATR%',
    open: '시가',
  },
};

export function getQuantChartText(language: ReportLanguage = 'zh'): QuantChartText {
  return QUANT_CHART_TEXT[language] ?? QUANT_CHART_TEXT.zh;
}
