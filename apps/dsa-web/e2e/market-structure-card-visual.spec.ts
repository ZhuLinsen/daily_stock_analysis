import { chromium, expect, test, type TestInfo } from '@playwright/test';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import fs from 'node:fs';
import { createServer } from 'node:http';
import path from 'node:path';
import type { AddressInfo } from 'node:net';
import { fileURLToPath } from 'node:url';
import { build as viteBuild } from 'vite';
import type { MarketStructureContext } from '../src/types/analysis';

test.use({ locale: 'zh-CN' });

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(currentDir, '..');
const sourceRoot = path.join(webRoot, 'src');

const context: MarketStructureContext = {
  schemaVersion: 'market-structure-v1',
  status: 'partial',
  market: 'cn',
  tradeDate: '2026-07-04',
  marketThemeContext: {
    schemaVersion: 'market-theme-v1',
    status: 'partial',
    market: 'cn',
    activeThemes: [
      { name: '机器人概念', changePct: 4.2, rank: 1, source: 'concept', phase: 'accelerating' },
      { name: 'AI 算力', changePct: 3.6, rank: 2, source: 'concept', phase: 'warming' },
    ],
    leadingConcepts: [
      { name: '机器人概念', changePct: 4.2, rank: 1, source: 'concept' },
      { name: 'AI 算力', changePct: 3.6, rank: 2, source: 'concept' },
    ],
    leadingIndustries: [
      { name: '通用设备', changePct: 2.1, rank: 2, source: 'industry' },
      { name: '软件开发', changePct: 1.8, rank: 4, source: 'industry' },
    ],
    laggingThemes: [],
    themeBreadth: {
      activeCount: 2,
      leadingConceptCount: 2,
      leadingIndustryCount: 2,
      laggingCount: 0,
    },
    dataQuality: {
      status: 'partial',
      missingFields: ['industry_rankings'],
      sources: [],
      errors: [],
    },
  },
  stockMarketPosition: {
    schemaVersion: 'stock-market-position-v1',
    status: 'partial',
    stockCode: '300024',
    stockName: '机器人',
    market: 'cn',
    primaryTheme: {
      name: '机器人概念',
      source: 'concept',
      phase: 'accelerating',
      rank: 1,
      changePct: 4.2,
    },
    relatedBoards: [
      { name: '机器人概念', type: '概念', source: 'concept', rank: 1, changePct: 4.2 },
      { name: '通用设备', type: '行业', source: 'industry', rank: 2, changePct: 2.1 },
    ],
    stockRole: 'follower',
    themePhase: 'accelerating',
    riskTags: [
      { code: 'theme_data_partial', message: '题材主线数据不完整' },
      { code: 'stock_theme_evidence_partial', message: '个股板块未匹配到市场题材榜单，个股位置按降级证据处理' },
    ],
    missingFields: ['hotspot_constituents', 'leader_stocks'],
  },
};

function toImportPath(fromDir: string, targetPath: string): string {
  const relativePath = path.relative(fromDir, targetPath).split(path.sep).join('/');
  return relativePath.startsWith('.') ? relativePath : `./${relativePath}`;
}

function writeFile(filePath: string, content: string): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
}

async function buildRealComponentFixture(): Promise<{
  distIndexPath: string;
  entryPath: string;
}> {
  const fixtureDir = path.join(webRoot, 'test-results', 'market-structure-card-visual');
  const distDir = path.join(fixtureDir, 'dist');
  const entryPath = path.join(fixtureDir, 'MarketStructureVisualApp.tsx');
  const htmlPath = path.join(fixtureDir, 'index.html');
  const componentImport = toImportPath(
    fixtureDir,
    path.join(sourceRoot, 'components/report/MarketStructureCard.tsx'),
  );
  const cssImport = toImportPath(fixtureDir, path.join(sourceRoot, 'index.css'));
  const typeImport = toImportPath(fixtureDir, path.join(sourceRoot, 'types/analysis.ts'));

  writeFile(
    entryPath,
    `
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import '${cssImport}';
      import { MarketStructureCard } from '${componentImport}';
      import type { MarketStructureContext } from '${typeImport}';

      const context: MarketStructureContext = ${JSON.stringify(context, null, 8)};

      createRoot(document.getElementById('root')!).render(
        <React.StrictMode>
          <main className="min-h-screen bg-background p-8 text-foreground">
            <div className="mx-auto max-w-5xl" data-testid="market-structure-visual-card">
              <MarketStructureCard context={context} language="zh" />
            </div>
          </main>
        </React.StrictMode>,
      );
    `,
  );
  writeFile(
    htmlPath,
    `
      <!doctype html>
      <html lang="zh-CN">
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <title>MarketStructureCard Real Component Visual Evidence</title>
        </head>
        <body>
          <div id="root"></div>
          <script type="module" src="/MarketStructureVisualApp.tsx"></script>
        </body>
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
      __APP_BUILD_TIME__: JSON.stringify('2026-07-05T00:00:00.000Z'),
    },
    build: {
      outDir: distDir,
      emptyOutDir: true,
      sourcemap: false,
    },
  });

  return {
    distIndexPath: path.join(distDir, 'index.html'),
    entryPath,
  };
}

function isMissingPlaywrightBrowser(error: unknown): boolean {
  return error instanceof Error && error.message.includes("Executable doesn't exist");
}

function isHttpUrl(value: string): boolean {
  const lower = value.trim().toLowerCase();
  return lower.startsWith('http://') || lower.startsWith('https://');
}

async function startStaticServer(rootDir: string): Promise<{
  url: string;
  close: () => Promise<void>;
}> {
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
      response.writeHead(200, {
        'Content-Type': contentTypes[path.extname(filePath)] || 'application/octet-stream',
      });
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
    close: () => new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    }),
  };
}

async function renderMarketStructureCard(distIndexPath: string, testInfo: TestInfo): Promise<void> {
  let browser: { close: () => Promise<void> } | null = null;
  try {
    browser = await chromium.launch();
  } catch (error) {
    if (!isMissingPlaywrightBrowser(error)) {
      throw error;
    }
    test.skip(
      true,
      'Playwright Chromium is not installed in this environment; skip visual smoke check.',
    );
    return;
  }

  const staticServer = await startStaticServer(path.dirname(distIndexPath));
  try {
    const page = await browser.newPage({
      locale: 'zh-CN',
      viewport: { width: 1280, height: 900 },
    });
    await page.goto(staticServer.url, { waitUntil: 'networkidle' });
    const card = page.getByTestId('market-structure-visual-card');
    await expect(card).toBeVisible();
    await expect(card.getByRole('region', { name: '题材主线与个股位置' })).toBeVisible();
    await expect(card.getByText('大盘题材层')).toBeVisible();
    await expect(card.getByText('个股位置层')).toBeVisible();
    await expect(card.getByText(/机器人概念 \+4\.20%/).first()).toBeVisible();

    const screenshotPath = testInfo.outputPath('market-structure-card-visual.png');
    const screenshot = await card.screenshot({ path: screenshotPath });
    expect(screenshot).toBeTruthy();
    expect(screenshot.length).toBeGreaterThan(1024);
    const githubServer = process.env.GITHUB_SERVER_URL || 'https://github.com';
    const githubRepository = process.env.GITHUB_REPOSITORY;
    const githubRunId = process.env.GITHUB_RUN_ID;
    const artifactName = 'market-structure-card-visual';
    const artifactRunHint = githubRepository && githubRunId
      ? `${githubServer}/${githubRepository}/actions/runs/${githubRunId}`
      : 'Unavailable (not running in GitHub Actions)';
    const artifactDownloadHint = githubRunId
      ? `gh run download ${githubRunId} --name ${artifactName} --dir ./.market-structure-card-visual`
      : '';
    const reproductionCommand = 'cd apps/dsa-web && npx playwright test e2e/market-structure-card-visual.spec.ts';
    const artifactHint = `${artifactRunHint}/artifacts`;
    const artifactPageHint = githubRepository && githubRunId
      ? `${githubServer}/${githubRepository}/actions/runs/${githubRunId}/jobs`
      : '';
    const externalEvidenceDir = process.env.DSA_WEB_VISUAL_EVIDENCE
      ? path.resolve(process.env.DSA_WEB_VISUAL_EVIDENCE)
      : '';
    const externalEvidenceUrl = process.env.DSA_WEB_VISUAL_EVIDENCE && isHttpUrl(process.env.DSA_WEB_VISUAL_EVIDENCE)
      ? process.env.DSA_WEB_VISUAL_EVIDENCE
      : '';
    const artifactManifestPath = testInfo.outputPath('market-structure-card-visual-artifact.txt');
    const evidenceNotes = [
      'MarketStructureCard visual evidence attached',
      `Screenshot attachment: market-structure-card-visual.png`,
      `Playwright attachment name (artifact evidence): ${artifactName}`,
      `Repro command: ${reproductionCommand}`,
    ];
    if (artifactDownloadHint) {
      evidenceNotes.push(`If running in GitHub Actions, download artifacts by command: ${artifactDownloadHint}`);
    }
    if (externalEvidenceUrl) {
      evidenceNotes.push(`External visual evidence URL: ${externalEvidenceUrl}`);
      evidenceNotes.push(`可复用外部链接查看本次截图（复制后用于 PR 说明）：${externalEvidenceUrl}`);
    }
    if (externalEvidenceDir && !externalEvidenceUrl) {
      try {
        fs.mkdirSync(externalEvidenceDir, { recursive: true });
        const externalScreenshot = path.join(externalEvidenceDir, 'market-structure-card-visual.png');
        fs.copyFileSync(screenshotPath, externalScreenshot);
        evidenceNotes.push(`Local shareable evidence copy: ${externalScreenshot}`);
      } catch (copyError) {
        testInfo.annotations.push({
          type: 'warning',
          description: `External visual evidence copy failed: ${String(copyError)}`,
        });
      }
    }
    if (githubRepository && githubRunId) {
      evidenceNotes.push(
        `GitHub Actions run: ${artifactRunHint}`,
        `GitHub Actions artifacts page: ${artifactHint}`,
        `GitHub Actions jobs page: ${artifactPageHint}`,
        `Download command: ${artifactDownloadHint}`,
        `Evidence attachment name: ${artifactName}（请在 PR 说明/评论附上 screenshots 直接附件或该 run 的附件下载链接）`,
      );
    } else {
      evidenceNotes.push(
        '未在 GitHub Actions 运行，不具备公开 artifact 链接；请补充可复现截图与复现场景。',
        '可复现证据路径（本地）：' + testInfo.outputPath('market-structure-card-visual.png'),
        `复现命令：${reproductionCommand}`,
      );
    }
    evidenceNotes.push(
      `若需外部可追溯复核，请在有 PR 权限的环境重跑该测试并在该动作页下载附件 ${artifactName} 后在 PR 中补充下载链接。`,
    );
    writeFile(
      artifactManifestPath,
      evidenceNotes.join('\n'),
    );

    testInfo.annotations.push({
      type: 'info',
      description:
        `Market structure card visual evidence attached in Playwright artifacts. `
        + `Attachment: ${artifactName}。`
        + (githubRepository && githubRunId
          ? `请在 PR 说明/评论附上 ${artifactHint} 中的该附件。`
          : '未在 GitHub Actions 运行，请将该截图附件或可访问外链输出到 PR 说明/评论。'),
    });
    await testInfo.attach('market-structure-card-visual', {
      path: screenshotPath,
      contentType: 'image/png',
    });
    await testInfo.attach('market-structure-card-visual-evidence', {
      path: artifactManifestPath,
      contentType: 'text/plain',
    });
    await testInfo.attach('market-structure-card-visual-bytes', {
      body: screenshot,
      contentType: 'image/png',
    });
  } finally {
    if (browser) {
      await browser.close();
    }
    await staticServer.close();
  }
}

test.describe('MarketStructureCard visual smoke', () => {
  test('renders MarketStructureCard with expected sections', async ({ baseURL: _baseURL }, testInfo) => {
    void _baseURL;
    const { distIndexPath } = await buildRealComponentFixture();
    expect(fs.existsSync(distIndexPath)).toBe(true);
    await renderMarketStructureCard(distIndexPath, testInfo);
  });
});
