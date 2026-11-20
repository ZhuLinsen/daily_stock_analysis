import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { useState } from 'react';
import { CommandPalette } from '../CommandPalette';

const LocationDisplay = () => {
  const location = useLocation();
  return <div data-testid="current-route">{`${location.pathname}${location.search}`}</div>;
};

const PaletteHarness = () => {
  const [open, setOpen] = useState(false);
  return (
    <MemoryRouter initialEntries={['/']}>
      <LocationDisplay />
      <CommandPalette
        isOpen={open}
        onClose={() => setOpen(false)}
        onToggle={() => setOpen((prev) => !prev)}
      />
    </MemoryRouter>
  );
};

describe('CommandPalette', () => {
  it('opens on Ctrl/Cmd+K, filters commands, jumps to route on Enter, and offers direct ticker shortcut', () => {
    render(<PaletteHarness />);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();

    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'backtest' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('current-route')).toHaveTextContent('/backtest');

    // Re-open with Cmd+K and jump to a ticker
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input2 = screen.getByRole('textbox');
    fireEvent.change(input2, { target: { value: '600519' } });
    expect(screen.getByText('前往首页分析 600519')).toBeInTheDocument();
    fireEvent.keyDown(input2, { key: 'Enter' });
    expect(screen.getByTestId('current-route')).toHaveTextContent('/?stock=600519');

    // Escape closes when open
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('ignores Enter and Escape during IME composition and executes after composition ends', () => {
    render(<PaletteHarness />);

    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = screen.getByRole('textbox');

    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByTestId('current-route')).toHaveTextContent('/');

    fireEvent.compositionEnd(input);
    fireEvent.change(input, { target: { value: 'backtest' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('current-route')).toHaveTextContent('/backtest');
  });
});
