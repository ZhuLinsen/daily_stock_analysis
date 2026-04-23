// @vitest-environment node

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('index.html theme bootstrap', () => {
  it('preloads dark mode before React mounts and respects stored theme values', () => {
    const indexHtml = readFileSync(resolve(__dirname, '..', 'index.html'), 'utf8');

    expect(indexHtml).toContain("const storageKey = 'theme'");
    expect(indexHtml).toContain("const theme = storedTheme === 'light' || storedTheme === 'dark' ? storedTheme : 'dark';");
    expect(indexHtml).toContain("root.classList.remove('light', 'dark');");
    expect(indexHtml).toContain('root.classList.add(theme);');
    expect(indexHtml).toContain('root.style.colorScheme = theme;');
  });
});
