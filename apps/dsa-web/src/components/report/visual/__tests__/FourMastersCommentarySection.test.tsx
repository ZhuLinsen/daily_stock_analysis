import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FourMastersCommentarySection } from '../FourMastersCommentarySection';

const validCommentary = () => ({
  buffett: {
    summary: '護城河仍在，回檔並非價值受損。',
    supportsOriginalView: 'challenge',
    keyQuestion: '目前價格是否有足夠折讓？',
  },
  munger: {
    summary: '需檢查敘事是否被價格驅動。',
    supportsOriginalView: 'mixed',
    biggestFailureMode: '把週期性成長誤判為結構性成長。',
  },
  duanYongping: {
    summary: '生意模式與客戶黏著未變。',
    supportsOriginalView: 'support',
  },
  liLu: {
    summary: '長期確定性仍高。',
    supportsOriginalView: 'support',
    redLines: ['市占率跌破關鍵水準'],
  },
  synthesis: {
    mainDisagreement: '分歧在短線評價而非生意本質。',
    confidenceAdjustment: 'unchanged',
  },
});

describe('FourMastersCommentarySection', () => {
  it('renders four named cards, synthesis, and the disclaimer', () => {
    render(<FourMastersCommentarySection rawCommentary={validCommentary()} />);
    expect(screen.getByTestId('four-masters-commentary')).toBeInTheDocument();
    expect(screen.getByText('巴菲特視角')).toBeInTheDocument();
    expect(screen.getByText('蒙格視角')).toBeInTheDocument();
    expect(screen.getByText('段永平視角')).toBeInTheDocument();
    expect(screen.getByText('李錄視角')).toBeInTheDocument();
    expect(screen.getByTestId('four-masters-synthesis')).toBeInTheDocument();
    expect(screen.getByText(/本段為投資框架模擬點評/)).toBeInTheDocument();
    expect(screen.getByText(/不覆蓋原始操作建議$/)).toBeInTheDocument();
  });

  it('renders semantic stance badges', () => {
    render(<FourMastersCommentarySection rawCommentary={validCommentary()} />);
    const badges = screen.getAllByTestId('four-masters-stance');
    expect(badges.map((b) => b.textContent)).toEqual(['質疑', '混合', '支持', '支持']);
  });

  it('renders red lines for the Li Lu card', () => {
    render(<FourMastersCommentarySection rawCommentary={validCommentary()} />);
    expect(screen.getByText('紅線')).toBeInTheDocument();
    expect(screen.getByText('市占率跌破關鍵水準')).toBeInTheDocument();
  });

  it('renders nothing when payload is missing or malformed', () => {
    const { container: c1 } = render(<FourMastersCommentarySection rawCommentary={undefined} />);
    expect(c1.innerHTML).toBe('');
    const { container: c2 } = render(<FourMastersCommentarySection rawCommentary={{ buffett: 'bad' }} />);
    expect(c2.innerHTML).toBe('');
  });

  it('escapes html-like text instead of rendering it', () => {
    const payload = validCommentary();
    payload.munger.summary = '<img src=x onerror=alert(1)>提防敘事';
    const { container } = render(<FourMastersCommentarySection rawCommentary={payload} />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(/提防敘事/)).toBeInTheDocument();
  });

  it('does not render smuggled action text or any action CTA', () => {
    const payload = validCommentary() as Record<string, Record<string, unknown>>;
    payload.buffett.operationAdvice = '立即買進';
    payload.synthesis.suggestedAction = '加倉三成';
    const { container } = render(<FourMastersCommentarySection rawCommentary={payload} />);
    expect(container.textContent).not.toContain('立即買進');
    expect(container.textContent).not.toContain('加倉三成');
    expect(container.querySelector('button')).toBeNull();
  });

  it('shows the confidence adjustment tag', () => {
    render(<FourMastersCommentarySection rawCommentary={validCommentary()} />);
    expect(screen.getByText('信心調整：不變')).toBeInTheDocument();
  });
});
