import type { UiLanguage } from '../i18n/uiText';

type LocalizedText = Record<UiLanguage, string>;

const STATIC_PROGRESS_TEXT: Record<string, LocalizedText> = {
  '任务已加入队列': {
    zh: '任务已加入队列',
    en: 'Analysis task added to the queue.',
    ko: '분석 작업이 대기열에 추가되었습니다.',
  },
  '正在分析中...': {
    zh: '正在分析中...',
    en: 'Analyzing...',
    ko: '분석 중...',
  },
  '正在分析中…': {
    zh: '正在分析中…',
    en: 'Analyzing…',
    ko: '분석 중…',
  },
  '分析完成': {
    zh: '分析完成',
    en: 'Analysis completed.',
    ko: '분석이 완료되었습니다.',
  },
  '任务执行中': {
    zh: '任务执行中',
    en: 'Task is running...',
    ko: '작업 실행 중...',
  },
  '任务执行完成': {
    zh: '任务执行完成',
    en: 'Task completed.',
    ko: '작업 실행이 완료되었습니다.',
  },
  '正在抓取最新行情': {
    zh: '正在抓取最新行情',
    en: 'Fetching the latest market quote...',
    ko: '최신 시세를 불러오는 중...',
  },
  '等待分析队列': {
    zh: '等待分析队列',
    en: 'Waiting in the analysis queue.',
    ko: '분석 대기열에서 기다리는 중입니다.',
  },
};

const NAMED_PROGRESS_TEXT: Record<string, LocalizedText> = {
  '正在获取行情与筹码数据': {
    zh: '正在获取行情与筹码数据',
    en: 'Fetching market and volume-profile data',
    ko: '시세 및 매물대 데이터를 불러오는 중',
  },
  '正在聚合基本面与趋势数据': {
    zh: '正在聚合基本面与趋势数据',
    en: 'Combining fundamental and trend data',
    ko: '기본 정보와 추세 데이터를 종합하는 중',
  },
  '正在切换 Agent 分析链路': {
    zh: '正在切换 Agent 分析链路',
    en: 'Switching to the Agent analysis path',
    ko: 'Agent 분석 경로로 전환하는 중',
  },
  '正在检索新闻与舆情': {
    zh: '正在检索新闻与舆情',
    en: 'Searching news and market sentiment',
    ko: '뉴스와 투자심리를 검색하는 중',
  },
  '正在整理分析上下文': {
    zh: '正在整理分析上下文',
    en: 'Organizing analysis context',
    ko: '분석 컨텍스트를 정리하는 중',
  },
  '正在请求 LLM 生成报告': {
    zh: '正在请求 LLM 生成报告',
    en: 'Requesting the LLM to generate the report',
    ko: 'LLM에 보고서 생성을 요청하는 중',
  },
  '正在校验并整理分析结果': {
    zh: '正在校验并整理分析结果',
    en: 'Validating and organizing analysis results',
    ko: '분석 결과를 검증하고 정리하는 중',
  },
  '正在保存分析报告': {
    zh: '正在保存分析报告',
    en: 'Saving the analysis report',
    ko: '분석 보고서를 저장하는 중',
  },
  '正在准备分析任务': {
    zh: '正在准备分析任务',
    en: 'Preparing the analysis task',
    ko: '분석 작업을 준비하는 중',
  },
  '行情数据准备完成': {
    zh: '行情数据准备完成',
    en: 'Market data is ready',
    ko: '시세 데이터 준비 완료',
  },
  'LLM 已接收请求，等待响应': {
    zh: 'LLM 已接收请求，等待响应',
    en: 'The LLM received the request and is awaiting a response',
    ko: 'LLM 요청을 접수하고 응답을 기다리는 중',
  },
  'LLM 返回完成，正在解析 JSON': {
    zh: 'LLM 返回完成，正在解析 JSON',
    en: 'The LLM response is ready; parsing JSON',
    ko: 'LLM 응답을 받아 JSON을 파싱하는 중',
  },
};

const FAILURE_TEXT: Record<string, LocalizedText> = {
  '分析失败': {
    zh: '分析失败',
    en: 'Analysis failed',
    ko: '분석에 실패했습니다',
  },
  '任务失败': {
    zh: '任务失败',
    en: 'Task failed',
    ko: '작업 실행에 실패했습니다',
  },
};

const CJK_RE = /[\u3400-\u9fff]/u;
const NAMED_PROGRESS_RE = /^(.+?)[：:]\s*(.+)$/u;
const LLM_GENERATING_RE = /^LLM 正在生成分析结果（已接收 (\d+) 字符）$/u;
const LLM_WAITING_RE = /^LLM 请求前等待 ([\d.]+) 秒$/u;
const REPORT_RETRY_RE = /^报告字段不完整，正在补全重试（(\d+)\/(\d+)）$/u;
const FAILURE_RE = /^(分析失败|任务失败)[：:]\s*(.*)$/u;

const localizedFallback = (language: UiLanguage): string => (
  language === 'ko' ? '분석 진행 상태를 업데이트하는 중…' : 'Updating analysis status…'
);

function localizeNamedProgress(message: string, language: UiLanguage): string | null {
  const matched = message.match(NAMED_PROGRESS_RE);
  if (!matched) {
    return null;
  }

  const [, stockName, detail] = matched;
  const known = NAMED_PROGRESS_TEXT[detail];
  if (known) {
    return `${stockName}: ${known[language]}`;
  }

  const generating = detail.match(LLM_GENERATING_RE);
  if (generating) {
    const [, charsReceived] = generating;
    return language === 'ko'
      ? `${stockName}: LLM이 분석 결과를 생성하는 중(수신 ${charsReceived}자)`
      : `${stockName}: LLM is generating analysis results (${charsReceived} characters received)`;
  }

  const waiting = detail.match(LLM_WAITING_RE);
  if (waiting) {
    const [, seconds] = waiting;
    return language === 'ko'
      ? `${stockName}: LLM 요청 전 ${seconds}초 대기 중`
      : `${stockName}: Waiting ${seconds} seconds before the LLM request`;
  }

  const retry = detail.match(REPORT_RETRY_RE);
  if (retry) {
    const [, currentRetry, maxRetries] = retry;
    return language === 'ko'
      ? `${stockName}: 보고서 필드를 보완하기 위해 재시도 중(${currentRetry}/${maxRetries})`
      : `${stockName}: Retrying to complete report fields (${currentRetry}/${maxRetries})`;
  }

  return null;
}

function localizeFailure(message: string, language: UiLanguage): string | null {
  const matched = message.match(FAILURE_RE);
  if (!matched) {
    return null;
  }

  const [, type, detail] = matched;
  const label = FAILURE_TEXT[type];
  if (!label) {
    return null;
  }
  if (!detail || CJK_RE.test(detail)) {
    return language === 'ko'
      ? `${label[language]}. 실행 흐름에서 상세 정보를 확인하세요.`
      : `${label[language]}. Check the run flow for details.`;
  }
  return `${label[language]}: ${detail}`;
}

/**
 * Localize task-queue progress supplied by the backend.
 *
 * The task API intentionally exposes raw status text for SSE clients. Convert
 * known progress messages at the WebUI boundary so switching the interface
 * language also switches in-flight task updates.
 */
export function localizeTaskProgressMessage(
  value: string | null | undefined,
  language: UiLanguage,
): string {
  const message = String(value || '').trim();
  if (!message || language === 'zh') {
    return message;
  }

  const known = STATIC_PROGRESS_TEXT[message];
  if (known) {
    return known[language];
  }

  const namedProgress = localizeNamedProgress(message, language);
  if (namedProgress) {
    return namedProgress;
  }

  const failure = localizeFailure(message, language);
  if (failure) {
    return failure;
  }

  // Do not expose a newly introduced Chinese backend status untranslated.
  return CJK_RE.test(message) ? localizedFallback(language) : message;
}
