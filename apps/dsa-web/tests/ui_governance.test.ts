import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const srcRoot = join(process.cwd(), 'src');
const nativeTitlePattern = /<(button|a|input|textarea|select|div|span)\b[^>]*\btitle=/;
const inputTerminalPattern = /\binput-terminal\b/;

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);

    if (stats.isDirectory()) {
      return collectSourceFiles(fullPath);
    }

    if (!/\.(ts|tsx)$/.test(fullPath)) {
      return [];
    }

    if (/\.test\.(ts|tsx)$/.test(fullPath)) {
      return [];
    }

    return [fullPath];
  });
}

const sourceFiles = collectSourceFiles(srcRoot);

describe('web UI governance guards', () => {
  it('does not reintroduce native title attributes on common interactive elements', () => {
    const violations = sourceFiles.filter((filePath) => nativeTitlePattern.test(readFileSync(filePath, 'utf8')));
    expect(violations).toEqual([]);
  });

  it('keeps input-terminal out of application source', () => {
    const violations = sourceFiles.filter((filePath) => inputTerminalPattern.test(readFileSync(filePath, 'utf8')));
    expect(violations).toEqual([]);
  });
});
