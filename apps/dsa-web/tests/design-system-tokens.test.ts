// @vitest-environment node

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const REQUIRED_DESIGN_TOKENS = [
  '--ds-brand',
  '--ds-brand-soft',
  '--ds-brand-foreground',
  '--ds-support',
  '--ds-canvas',
  '--ds-panel',
  '--ds-panel-muted',
  '--ds-text',
  '--ds-text-secondary',
  '--ds-border',
  '--ds-focus',
  '--ds-positive',
  '--ds-caution',
  '--ds-negative',
];

describe('design system contract', () => {
  it.each([
    [':root', /:root\s*\{([\s\S]*?)\n\}/],
    ['.dark', /\.dark\s*\{([\s\S]*?)\n\}/],
  ])('defines the semantic palette in %s', (_name, pattern) => {
    const css = readFileSync(resolve(__dirname, '..', 'src', 'index.css'), 'utf8');
    const block = css.match(pattern)?.[1] ?? '';

    for (const token of REQUIRED_DESIGN_TOKENS) {
      expect(block).toContain(token);
    }
  });

  it('documents color, surface, state, spacing, and component usage', () => {
    const docPath = resolve(__dirname, '..', '..', '..', 'docs', 'design-system.md');
    expect(existsSync(docPath)).toBe(true);
    const guide = readFileSync(docPath, 'utf8');

    for (const section of ['Color', 'Surface', 'State', 'Spacing', 'Component']) {
      expect(guide).toContain(`## ${section}`);
    }

    expect(guide).toContain('Futu-inspired');
    expect(guide).toContain('橙色只承担主行动与当前状态');
  });
});
