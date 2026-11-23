import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { EmailGroupEditor } from '../EmailGroupEditor';
import type { SystemConfigUpdateItem } from '../../../types/systemConfig';

function EditorHarness() {
  const [items, setItems] = useState<SystemConfigUpdateItem[]>([
    { key: 'STOCK_GROUP_7', value: '600519' },
    { key: 'EMAIL_GROUP_7', value: 'one@example.com' },
  ]);
  return <EmailGroupEditor items={items} issueByKey={{}} disabled={false} onChange={(changes) => setItems((previous) => [...previous, ...changes])} />;
}

describe('EmailGroupEditor', () => {
  it('loads legacy group IDs and edits, adds and deletes paired routing fields', () => {
    render(<EditorHarness />);
    expect(screen.getByDisplayValue('600519')).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('one@example.com'), { target: { value: 'two@example.com，three@example.com' } });
    expect(screen.getByDisplayValue('two@example.com,three@example.com')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '添加分组' }));
    const stockInputs = screen.getAllByLabelText('股票代码');
    const emailInputs = screen.getAllByLabelText('收件邮箱');
    fireEvent.change(stockInputs[1], { target: { value: 'AAPL' } });
    fireEvent.change(emailInputs[1], { target: { value: 'four@example.com' } });
    expect(screen.getByText('分组 8')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '删除分组 7' }));
    expect(screen.queryByDisplayValue('600519')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('four@example.com')).toBeInTheDocument();
  });
});
