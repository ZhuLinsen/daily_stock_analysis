import { describe, expect, it } from 'vitest';
import { parseApiError } from '../error';

describe('parseApiError', () => {
  it('explains an interrupted Codex CLI execution in Korean', () => {
    const parsed = parseApiError(
      'execution_interrupted at execution for backend codex_cli',
    );

    expect(parsed.category).toBe('execution_interrupted');
    expect(parsed.title).toBe('분석 실행이 중단되었습니다');
    expect(parsed.message).toContain('서버가 재시작되었거나');
  });

  it('explains a genuine approval-required error in Korean', () => {
    const parsed = parseApiError(
      'approval_required at execution for backend codex_cli',
    );

    expect(parsed.category).toBe('approval_required');
    expect(parsed.title).toBe('Codex CLI 승인이 필요합니다');
    expect(parsed.message).toContain('승인 없이 읽기 전용');
  });
});
