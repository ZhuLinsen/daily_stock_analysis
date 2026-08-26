import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StockScreeningPage from '../StockScreeningPage';

const { getScreeningStatus, navigate } = vi.hoisted(() => ({
  getScreeningStatus: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock('../../api/screening', () => ({
  screeningApi: {
    getStatus: getScreeningStatus,
  },
}));

describe('StockScreeningPage', () => {
  beforeEach(() => {
    navigate.mockReset();
    getScreeningStatus.mockReset();
    getScreeningStatus.mockResolvedValue({ enabled: false, available: false });
  });

  it('shows the Korean KRX notice instead of the legacy China-market screener', () => {
    render(
      <MemoryRouter>
        <StockScreeningPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: '한국 주식 스크리닝' })).toBeInTheDocument();
    expect(screen.getByText('KOSPI · KOSDAQ')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('KRX 스크리닝 준비 중');
    expect(screen.getByRole('alert')).toHaveTextContent('.KS 또는 .KQ');
    expect(screen.queryByText('A 股')).not.toBeInTheDocument();
  });

  it('links the user to the Korean watchlist workflow', () => {
    render(
      <MemoryRouter>
        <StockScreeningPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: '관심종목으로 이동' }));

    expect(navigate).toHaveBeenCalledWith('/');
  });
});
