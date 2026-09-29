// @vitest-environment node

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('home mobile stock sidebar styles', () => {
  it('overrides glass-card clipping outside the Tailwind utilities layer on mobile', () => {
    const css = readFileSync(resolve(__dirname, '..', 'src', 'index.css'), 'utf8');
    const glassCardIndex = css.indexOf('.glass-card {');
    const mobileShellIndex = css.indexOf('.glass-card.home-stock-scroll-shell');
    const mobileShellRule = css.match(
      /\.home-stock-scroll-shell,\s*\.glass-card\.home-stock-scroll-shell\s*\{([\s\S]*?)\}/,
    );

    expect(glassCardIndex).toBeGreaterThanOrEqual(0);
    expect(mobileShellIndex).toBeGreaterThan(glassCardIndex);
    expect(mobileShellRule?.[1]).toMatch(/overflow:\s*visible;/);
  });

  it('restores card clipping at the desktop breakpoint', () => {
    const css = readFileSync(resolve(__dirname, '..', 'src', 'index.css'), 'utf8');
    const desktopRule = css.match(
      /@media \(min-width: 48rem\)\s*\{\s*\.home-stock-scroll-shell,\s*\.glass-card\.home-stock-scroll-shell\s*\{([\s\S]*?)\}\s*\}/,
    );

    expect(desktopRule?.[1]).toMatch(/overflow:\s*hidden;/);
  });
});
