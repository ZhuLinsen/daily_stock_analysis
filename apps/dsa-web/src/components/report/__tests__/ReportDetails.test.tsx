import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportDetails } from '../ReportDetails';

describe('ReportDetails', () => {
  const writeTextMock = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    writeTextMock.mockClear();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: writeTextMock,
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('toggles sections and copies json payloads', async () => {
    render(
      <ReportDetails
        recordId={7}
        details={{
          rawResult: { score: 82 },
          contextSnapshot: { window: '30d' },
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '原始分析结果' }));
    expect(screen.getByText(/"score": 82/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: '复制' })[0]);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalled();
    });

    expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 2100));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();
    });
  });

  it('does not render when details and record id are both absent', () => {
    const { container } = render(<ReportDetails />);
    expect(container).toBeEmptyDOMElement();
  });
});
