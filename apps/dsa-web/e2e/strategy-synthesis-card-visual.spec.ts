import { chromium, expect, test, type TestInfo } from '@playwright/test';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import fs from 'node:fs';
import { createServer } from 'node:http';
import path from 'node:path';
import type { AddressInfo } from 'node:net';
import { fileURLToPath } from 'node:url';
import { build as viteBuild } from 'vite';
import type { StrategySynthesis } from '../src/types/analysis';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(currentDir, '..');
const sourceRoot = path.join(webRoot, 'src');

const longReasoning = 'The strategy remains cautious until volume, moving-average structure, and market risk appetite improve together. '.repeat(4);

const synthesis: StrategySynthesis = {
  schemaVersion: 'strategy-synthesis-v1',
  finalSignal: 'hold',
  weightedScore: 3,
  confidence: 0.62,
  originalConfidence: 0.8,
  conflictCount: 1,
  conflictSeverity: 'high',
  conflicts: [{
    conflictType: 'directional_opposition',
    severity: 'high',
    descriptionKey: 'strategy_conflict.directional_opposition',
    participants: ['bull-trend', 'bear-risk'],
  }],
  supportingSkills: [{
    skillId: 'bull-trend',
    agentName: 'skill_bull_trend',
    signal: 'buy',
    confidence: 0.72,
    appliedWeight: 0.4,
    reasoning: '等待成交量确认后再决定。',
  }],
  opposingSkills: [{
    skillId: 'bear-risk',
    agentName: 'skill_bear_risk',
    signal: 'sell',
    confidence: 0.8,
    appliedWeight: 0.4,
    reasoning: longReasoning,
  }],
  signalDistribution: {
    bullish: { count: 1, weightShare: 0.4 },
    neutral: { count: 1, weightShare: 0.2 },
    bearish: { count: 1, weightShare: 0.4 },
  },
  primaryDissent: {
    skillId: 'bear-risk',
    agentName: 'skill_bear_risk',
    signal: 'sell',
    confidence: 0.8,
    appliedWeight: 0.4,
    reasoning: longReasoning,
  },
  consensusLevel: 'low',
  summaryKey: 'strategy_synthesis.with_conflicts',
  summaryParams: {
    opinionCount: 3,
    totalOpinionCount: 4,
    invalidOpinionCount: 1,
    finalSignal: 'hold',
    consensusLevel: 'low',
    conflictSeverity: 'high',
    conflictCount: 1,
  },
  deliberation: {
    status: 'completed',
    mode: 'mediator_v0',
    rounds: 1,
    agenda: [],
    responses: [],
    summary: {
      resolutionStatus: 'partially_resolved',
      resolvedConflictCount: 0,
      unresolvedConflictCount: 1,
      minorityViewPreserved: true,
      confidenceAdjustment: -0.06,
    },
  },
  revisionProjection: {
    status: 'computed',
    mode: 'preview_only',
    sourceMode: 'mediator_v0',
    projectedSignal: 'hold',
    projectedWeightedScore: 3.1,
    projectedConfidence: 0.58,
    projectedOriginalConfidence: 0.7,
    projectedConflictCount: 1,
    projectedConflictSeverity: 'medium',
    projectedConsensusLevel: 'low',
    changedSkillCount: 1,
    changedSkills: ['bear-risk'],
    finalSignalOverridden: false,
  },
};

const scenarios = [
  { id: 'zh-dark-wide', language: 'zh', theme: 'dark', width: 1280, height: 1000, title: '观点共识与分歧', conflict: '冲突详情 (1)', summary: '部分解决' },
  { id: 'zh-light-narrow', language: 'zh', theme: 'light', width: 390, height: 900, title: '观点共识与分歧', conflict: '冲突详情 (1)', summary: '部分解决' },
  { id: 'en-light-wide', language: 'en', theme: 'light', width: 1280, height: 1000, title: 'Consensus and Dissent', conflict: 'Conflict Details (1)', summary: 'Partially resolved' },
  { id: 'en-dark-narrow', language: 'en', theme: 'dark', width: 390, height: 900, title: 'Consensus and Dissent', conflict: 'Conflict Details (1)', summary: 'Partially resolved' },
  { id: 'ko-dark-wide', language: 'ko', theme: 'dark', width: 1280, height: 1000, title: '합의와 이견', conflict: '충돌 상세 (1)', summary: '부분 해결' },
  { id: 'ko-light-narrow', language: 'ko', theme: 'light', width: 390, height: 900, title: '합의와 이견', conflict: '충돌 상세 (1)', summary: '부분 해결' },
] as const;

function toImportPath(fromDir: string, targetPath: string): string {
  const relativePath = path.relative(fromDir, targetPath).split(path.sep).join('/');
  return relativePath.startsWith('.') ? relativePath : `./${relativePath}`;
}

function writeFile(filePath: string, content: string): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
}

async function buildFixture(): Promise<string> {
  const fixtureDir = path.join(webRoot, 'test-results', 'strategy-synthesis-card-visual');
  const distDir = path.join(fixtureDir, 'dist');
  const componentImport = toImportPath(
    fixtureDir,
    path.join(sourceRoot, 'components/report/StrategySynthesisCard.tsx'),
  );
  const cssImport = toImportPath(fixtureDir, path.join(sourceRoot, 'index.css'));
  const typeImport = toImportPath(fixtureDir, path.join(sourceRoot, 'types/analysis.ts'));

  writeFile(
    path.join(fixtureDir, 'StrategySynthesisVisualApp.tsx'),
    `
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import '${cssImport}';
      import { StrategySynthesisCard } from '${componentImport}';
      import type { ReportLanguage, StrategySynthesis } from '${typeImport}';

      const query = new URLSearchParams(window.location.search);
      const language = (query.get('language') || 'zh') as ReportLanguage;
      const theme = query.get('theme') || 'dark';
      document.documentElement.classList.toggle('dark', theme === 'dark');
      const synthesis: StrategySynthesis = ${JSON.stringify(synthesis, null, 8)};

      createRoot(document.getElementById('root')!).render(
        <React.StrictMode>
          <main className="min-h-screen bg-background p-3 text-foreground sm:p-8">
            <div className="mx-auto max-w-6xl" data-testid="strategy-synthesis-visual-card">
              <StrategySynthesisCard synthesis={synthesis} language={language} />
            </div>
          </main>
        </React.StrictMode>,
      );
    `,
  );
  writeFile(
    path.join(fixtureDir, 'index.html'),
    `
      <!doctype html>
      <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <title>StrategySynthesisCard Visual Evidence</title>
        </head>
        <body><div id="root"></div><script type="module" src="/StrategySynthesisVisualApp.tsx"></script></body>
      </html>
    `,
  );

  await viteBuild({
    root: fixtureDir,
    base: './',
    configFile: false,
    publicDir: false,
    logLevel: 'warn',
    plugins: [tailwindcss(), react()],
    define: {
      __APP_PACKAGE_VERSION__: JSON.stringify('visual-evidence'),
      __APP_BUILD_TIME__: JSON.stringify('2026-07-23T00:00:00.000Z'),
    },
    build: { outDir: distDir, emptyOutDir: true, sourcemap: false },
  });
  return distDir;
}

async function startStaticServer(rootDir: string): Promise<{ url: string; close: () => Promise<void> }> {
  const server = createServer((request, response) => {
    const requestPath = decodeURIComponent((request.url || '/').split('?', 1)[0]);
    const relativePath = requestPath === '/' ? 'index.html' : requestPath.replace(/^\/+/, '');
    const filePath = path.resolve(rootDir, relativePath);
    const relativeToRoot = path.relative(rootDir, filePath);
    if (relativeToRoot.startsWith('..') || path.isAbsolute(relativeToRoot)) {
      response.writeHead(403).end('Forbidden');
      return;
    }
    fs.readFile(filePath, (error, content) => {
      if (error) {
        response.writeHead(error.code === 'ENOENT' ? 404 : 500).end('Not found');
        return;
      }
      const contentTypes: Record<string, string> = {
        '.css': 'text/css; charset=utf-8',
        '.html': 'text/html; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8',
      };
      response.writeHead(200, { 'Content-Type': contentTypes[path.extname(filePath)] || 'application/octet-stream' });
      response.end(content);
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}/`,
    close: () => new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

function isMissingBrowser(error: unknown): boolean {
  return error instanceof Error && error.message.includes("Executable doesn't exist");
}

function findSystemChromium(): string | null {
  const candidates = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

async function attachScreenshot(testInfo: TestInfo, screenshotPath: string, attachmentName: string): Promise<void> {
  await testInfo.attach(attachmentName, { path: screenshotPath, contentType: 'image/png' });
  const evidenceDir = process.env.DSA_WEB_VISUAL_EVIDENCE;
  if (evidenceDir && !evidenceDir.startsWith('http://') && !evidenceDir.startsWith('https://')) {
    fs.mkdirSync(path.resolve(evidenceDir), { recursive: true });
    fs.copyFileSync(screenshotPath, path.join(path.resolve(evidenceDir), path.basename(screenshotPath)));
  }
}

test('StrategySynthesisCard remains readable across locales, themes and widths', async ({ baseURL: _baseURL }, testInfo) => {
  void _baseURL;
  const distDir = await buildFixture();
  let browser;
  try {
    browser = await chromium.launch();
  } catch (error) {
    if (!isMissingBrowser(error)) throw error;
    const executablePath = findSystemChromium();
    if (!executablePath) {
      test.skip(true, 'Neither Playwright Chromium nor a supported system Chromium is installed.');
      return;
    }
    browser = await chromium.launch({ executablePath });
  }

  const server = await startStaticServer(distDir);
  try {
    for (const scenario of scenarios) {
      const page = await browser.newPage({
        locale: scenario.language === 'ko' ? 'ko-KR' : scenario.language === 'en' ? 'en-US' : 'zh-CN',
        viewport: { width: scenario.width, height: scenario.height },
      });
      await page.goto(`${server.url}?language=${scenario.language}&theme=${scenario.theme}`, { waitUntil: 'networkidle' });
      const card = page.getByTestId('strategy-synthesis-visual-card');
      await expect(card.getByRole('region', { name: scenario.title })).toBeVisible();
      await expect(card.getByText(scenario.summary)).toBeVisible();

      const expansionButtons = card.getByRole('button', { expanded: false });
      expect(await expansionButtons.count()).toBe(3);
      await expect(expansionButtons.nth(1)).toBeVisible();
      await expansionButtons.nth(1).click();
      await expect(card.getByRole('button', { expanded: true })).toBeVisible();

      await card.getByText(scenario.conflict).click();
      await expect(card.getByText('directional_opposition')).toHaveCount(0);
      const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(hasHorizontalOverflow).toBe(false);

      const screenshotPath = testInfo.outputPath(`web-strategy-synthesis-${scenario.id}.png`);
      await card.screenshot({ path: screenshotPath });
      await attachScreenshot(testInfo, screenshotPath, `web-strategy-synthesis-${scenario.id}`);
      await page.close();
    }
  } finally {
    await browser.close();
    await server.close();
  }
});
