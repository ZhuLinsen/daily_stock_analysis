import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DashboardStateBlock } from '../DashboardStateBlock';

describe('DashboardStateBlock', () => {
  it('renders the title as a paragraph by default', () => {
    const { container } = render(<DashboardStateBlock title="开始分析" description="查看提示文案" />);

    const title = screen.getByText('开始分析');
    expect(title.tagName).toBe('P');
    expect(container.querySelector('h3')).toBeNull();
  });

  it('renders the title with the requested heading level', () => {
    render(<DashboardStateBlock title="开始分析" titleAs="h3" description="查看提示文案" />);

    expect(screen.getByRole('heading', { name: '开始分析', level: 3 })).toBeInTheDocument();
  });

  it('keeps icon, description, action, and loading behaviors intact', () => {
    const { rerender } = render(
      <DashboardStateBlock
        title="开始分析"
        description="输入股票代码进行分析"
        icon={<span data-testid="icon">icon</span>}
        action={<button type="button">立即开始</button>}
      />,
    );

    expect(screen.getByTestId('icon')).toBeInTheDocument();
    expect(screen.getByText('输入股票代码进行分析')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '立即开始' })).toBeInTheDocument();

    rerender(
      <DashboardStateBlock
        title="开始分析"
        titleAs="h3"
        description="输入股票代码进行分析"
        loading
      />,
    );

    expect(screen.getByRole('heading', { name: '开始分析', level: 3 })).toBeInTheDocument();
    expect(screen.getByText('输入股票代码进行分析')).toBeInTheDocument();
    expect(document.querySelector('.home-spinner')).not.toBeNull();
    expect(screen.queryByTestId('icon')).not.toBeInTheDocument();
  });
});
