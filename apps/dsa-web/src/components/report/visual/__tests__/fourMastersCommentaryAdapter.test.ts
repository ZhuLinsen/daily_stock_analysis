import { describe, expect, it } from 'vitest';
import { adaptFourMastersCommentary } from '../fourMastersCommentaryAdapter';

const validPayload = () => ({
  buffett: {
    summary: '護城河仍在，股價回檔並非價值受損。',
    supportsOriginalView: 'challenge',
    keyQuestion: '目前價格是否有足夠折讓？',
    marginOfSafetyComment: '安全邊際不足。',
    whatWouldChangeThisView: '獲利結構性下修。',
  },
  munger: {
    summary: '結論與近期價格方向高度一致，需檢查敘事是否被價格驅動。',
    supportsOriginalView: 'mixed',
    inversionQuestion: '這筆投資最可能怎麼失敗？',
    biggestFailureMode: '把週期性成長誤判為結構性成長。',
  },
  duanYongping: {
    summary: '生意模式與客戶黏著未變。',
    supportsOriginalView: 'support',
    businessQualityComment: '商業模式健康。',
  },
  liLu: {
    summary: '長期確定性仍高，需明確紅線。',
    supportsOriginalView: 'support',
    certaintyComment: '產業地位帶來高確定性。',
    redLines: ['市占率跌破關鍵水準', '自由現金流轉負'],
  },
  synthesis: {
    mainDisagreement: '價值視角質疑買區估值依據。',
    mostUsefulSupplementToOriginalReport: '把技術位買區改為估值錨定觀察區。',
    confidenceAdjustment: 'lower',
    doesNotOverrideOriginalAction: true,
  },
});

describe('adaptFourMastersCommentary', () => {
  it('normalizes a valid camelCase payload into four cards + synthesis', () => {
    const vm = adaptFourMastersCommentary(validPayload());
    expect(vm).not.toBeNull();
    expect(vm!.cards.map((c) => c.key)).toEqual(['buffett', 'munger', 'duanYongping', 'liLu']);
    expect(vm!.cards[0].stance).toBe('challenge');
    expect(vm!.cards[3].redLines).toEqual(['市占率跌破關鍵水準', '自由現金流轉負']);
    expect(vm!.synthesis.confidenceAdjustment).toBe('lower');
    expect(vm!.synthesis.mainDisagreement).toContain('估值依據');
  });

  it('tolerates snake_case keys (raw payload parity)', () => {
    const vm = adaptFourMastersCommentary({
      duan_yongping: {
        summary: '生意本質未變。',
        supports_original_view: 'support',
        business_quality_comment: '穩健。',
      },
      li_lu: {
        summary: '確定性仍高。',
        red_lines: ['紅線一'],
      },
    });
    expect(vm).not.toBeNull();
    expect(vm!.cards.map((c) => c.key)).toEqual(['duanYongping', 'liLu']);
    expect(vm!.cards[0].details.some((d) => d.label === '生意品質')).toBe(true);
    expect(vm!.cards[1].redLines).toEqual(['紅線一']);
  });

  it('returns null for missing/malformed payloads', () => {
    expect(adaptFourMastersCommentary(undefined)).toBeNull();
    expect(adaptFourMastersCommentary(null)).toBeNull();
    expect(adaptFourMastersCommentary('text')).toBeNull();
    expect(adaptFourMastersCommentary([1, 2])).toBeNull();
    expect(adaptFourMastersCommentary({})).toBeNull();
    expect(adaptFourMastersCommentary({ buffett: 'not-an-object' })).toBeNull();
    expect(adaptFourMastersCommentary({ buffett: { keyQuestion: '?' } })).toBeNull();
  });

  it('coerces invalid enums to safe defaults', () => {
    const payload = validPayload();
    payload.buffett.supportsOriginalView = 'BUY NOW' as never;
    payload.synthesis.confidenceAdjustment = 'sell' as never;
    const vm = adaptFourMastersCommentary(payload);
    expect(vm!.cards[0].stance).toBe('mixed');
    expect(vm!.synthesis.confidenceAdjustment).toBe('unchanged');
  });

  it('sanitizes html-like text and truncates oversized fields', () => {
    const payload = validPayload();
    payload.buffett.summary = '<script>alert(1)</script>穩健 <b>加粗</b>' + '長'.repeat(1000);
    const vm = adaptFourMastersCommentary(payload);
    const summary = vm!.cards[0].summary;
    expect(summary).not.toContain('<');
    expect(summary).not.toContain('>');
    expect(summary).toContain('穩健');
    expect(summary.length).toBeLessThanOrEqual(600);
  });

  it('never carries smuggled action fields into the view model', () => {
    const payload = validPayload() as Record<string, Record<string, unknown>>;
    payload.buffett.operationAdvice = '買進';
    payload.buffett.finalAction = 'ACCUMULATE';
    payload.synthesis.suggestedAction = '加倉';
    const vm = adaptFourMastersCommentary(payload);
    const serialized = JSON.stringify(vm);
    expect(serialized).not.toContain('買進');
    expect(serialized).not.toContain('ACCUMULATE');
    expect(serialized).not.toContain('加倉');
  });

  it('drops non-list red lines gracefully and keeps single-string as one item', () => {
    const payload = validPayload() as Record<string, Record<string, unknown>>;
    payload.liLu.redLines = '單一字串紅線';
    expect(adaptFourMastersCommentary(payload)!.cards[3].redLines).toEqual(['單一字串紅線']);
    payload.liLu.redLines = { not: 'a list' };
    expect(adaptFourMastersCommentary(payload)!.cards[3].redLines).toEqual([]);
  });
});
