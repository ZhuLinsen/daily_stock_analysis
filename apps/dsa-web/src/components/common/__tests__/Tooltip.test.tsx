import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Tooltip } from '../Tooltip';

describe('Tooltip', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('opens on hover or focus, closes on blur or Escape, and wraps within viewport bounds', async () => {
    render(
      <Tooltip
        content="AlphaSift: multi-market daily screening & public T+N paper track record"
        focusable
      >
        <button type="button">AlphaSift Daily Picks</button>
      </Tooltip>,
    );

    const triggerButton = screen.getByRole('button', { name: 'AlphaSift Daily Picks' });
    const triggerWrapper = triggerButton.parentElement!;

    fireEvent.focus(triggerWrapper);
    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip).toHaveTextContent('AlphaSift: multi-market daily screening & public T+N paper track record');
    expect(tooltip.className).not.toContain('min-w-max');
    expect(tooltip.className).toContain('w-max');
    expect(tooltip.className).toContain('max-w-[min(18rem,calc(100vw-1rem))]');
    expect(tooltip.className).toContain('whitespace-normal');
    expect(tooltip.className).toContain('break-words');

    fireEvent.keyDown(triggerWrapper, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    fireEvent.mouseEnter(triggerWrapper);
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();

    fireEvent.blur(triggerWrapper);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('clamps horizontal position inside a 320px narrow viewport', async () => {
    const originalInnerWidth = window.innerWidth;
    const originalInnerHeight = window.innerHeight;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 640 });
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 1;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});

    const rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.getAttribute('role') === 'tooltip') {
        return {
          top: 0,
          left: 0,
          right: 288,
          bottom: 40,
          width: 288,
          height: 40,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      }
      return {
        top: 24,
        left: 220,
        right: 308,
        bottom: 60,
        width: 88,
        height: 36,
        x: 220,
        y: 24,
        toJSON: () => ({}),
      } as DOMRect;
    });

    try {
      render(
        <Tooltip content="Long wrapped tooltip content on narrow viewport" side="bottom">
          <a href="https://alphasift.zhulinsen.tech/?lang=en">AlphaSift Daily Picks</a>
        </Tooltip>,
      );

      const link = screen.getByRole('link', { name: 'AlphaSift Daily Picks' });
      fireEvent.focus(link.parentElement!);

      const tooltip = await screen.findByRole('tooltip');
      await waitFor(() => {
        const leftPx = Number.parseFloat(tooltip.style.left);
        expect(leftPx).toBeGreaterThanOrEqual(8);
        expect(leftPx).toBeLessThanOrEqual(24);
        expect(leftPx).toBe(24);
      });
    } finally {
      rectSpy.mockRestore();
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalInnerWidth });
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalInnerHeight });
    }
  });
});
