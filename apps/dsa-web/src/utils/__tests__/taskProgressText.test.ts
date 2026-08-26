import { describe, expect, test } from 'vitest';
import { localizeTaskProgressMessage } from '../taskProgressText';

describe('task progress text localization', () => {
  test.each([
    ['正在分析中...', '분석 중...'],
    ['任务已加入队列', '분석 작업이 대기열에 추가되었습니다.'],
    ['005930.KS：正在请求 LLM 生成报告', '005930.KS: LLM에 보고서 생성을 요청하는 중'],
    ['삼성전자：LLM 正在生成分析结果（已接收 320 字符）', '삼성전자: LLM이 분석 결과를 생성하는 중(수신 320자)'],
    ['삼성전자：报告字段不完整，正在补全重试（1/2）', '삼성전자: 보고서 필드를 보완하기 위해 재시도 중(1/2)'],
  ])('localizes %s for the Korean task panel', (source, expected) => {
    expect(localizeTaskProgressMessage(source, 'ko')).toBe(expected);
  });

  test('keeps Chinese text unchanged for the Chinese interface', () => {
    expect(localizeTaskProgressMessage('正在分析中...', 'zh')).toBe('正在分析中...');
  });

  test('uses a localized fallback for an unknown Chinese backend status', () => {
    expect(localizeTaskProgressMessage('正在同步未知数据源', 'ko')).toBe('분석 진행 상태를 업데이트하는 중…');
    expect(localizeTaskProgressMessage('正在同步未知数据源', 'en')).toBe('Updating analysis status…');
  });
});
