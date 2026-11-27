import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { SYNC_SPECS, prepareDocs } from '../scripts/prepare-docs.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE_ROOT = path.resolve(__dirname, '..');

function writeMinimalFixtureDsaRepo(dsaRoot, { omitPath = null } = {}) {
  const requiredFiles = new Set(['docs/architecture/api_spec.json']);
  for (const spec of SYNC_SPECS) {
    for (const src of spec.sources) requiredFiles.add(src);
    for (const src of spec.enSources || []) requiredFiles.add(src);
  }

  for (const rel of requiredFiles) {
    if (rel === omitPath) continue;
    const dest = path.join(dsaRoot, ...rel.split('/'));
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    if (rel === 'docs/architecture/api_spec.json') {
      fs.writeFileSync(
        dest,
        JSON.stringify({
          openapi: '3.1.0',
          info: { title: 'Test DSA API', version: '1.0.0' },
          paths: {
            '/api/v1/health': {
              get: {
                tags: ['Health'],
                summary: 'Health check',
                responses: { '200': { description: 'OK' } },
              },
            },
          },
          components: { schemas: { HealthResponse: { type: 'object' } } },
        }),
        'utf8',
      );
    } else {
      fs.writeFileSync(dest, `# ${rel}\n\nSample fixture content.\n`, 'utf8');
    }
  }
}

test('prepareDocs removes stale OpenAPI artifacts and throws when api_spec.json is missing', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-site-openapi-'));
  try {
    const fakeDsa = path.join(tmpRoot, 'dsa');
    const fakeSite = path.join(tmpRoot, 'site');
    writeMinimalFixtureDsaRepo(fakeDsa);

    const meta = prepareDocs({ siteRoot: fakeSite, dsaRoot: fakeDsa, quiet: true });
    assert.equal(meta.apiEndpointCount, 1);

    const publicOpenApi = path.join(fakeSite, 'public', 'openapi.json');
    const summaryJson = path.join(fakeSite, 'src', 'data', 'openapi-endpoints.json');
    const siteMetaJson = path.join(fakeSite, 'src', 'data', 'site-meta.json');
    assert.equal(fs.existsSync(publicOpenApi), true);
    assert.equal(fs.existsSync(summaryJson), true);
    assert.equal(fs.existsSync(siteMetaJson), true);

    fs.rmSync(path.join(fakeDsa, 'docs', 'architecture', 'api_spec.json'));
    assert.throws(
      () => prepareDocs({ siteRoot: fakeSite, dsaRoot: fakeDsa, quiet: true }),
      /docs\/architecture\/api_spec\.json/,
    );
    assert.equal(fs.existsSync(publicOpenApi), false);
    assert.equal(fs.existsSync(summaryJson), false);
    assert.equal(fs.existsSync(siteMetaJson), false);
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
});

test('prepareDocs fails loudly when a sidebar-mapped upstream doc is missing', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-site-missing-doc-'));
  try {
    const fakeDsa = path.join(tmpRoot, 'dsa');
    const fakeSite = path.join(tmpRoot, 'site');
    writeMinimalFixtureDsaRepo(fakeDsa, { omitPath: 'docs/data-center-diagnostics.md' });

    assert.throws(
      () => prepareDocs({ siteRoot: fakeSite, dsaRoot: fakeDsa, quiet: true }),
      /docs\/data-center-diagnostics\.md/,
    );
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
});

test('astro.config.mjs preserves legacy dsa_page redirects and valid sidebar slugs', async () => {
  const configMod = await import('../astro.config.mjs');
  const redirects = configMod.default?.redirects || {};

  const requiredLegacyRedirects = [
    '/docs/quick-start',
    '/docs/env-config',
    '/docs/github-actions',
    '/docs/local',
    '/docs/docker',
    '/docs/llm-config',
    '/docs/notifications',
    '/docs/data-sources',
    '/docs/webui',
    '/docs/bot',
    '/docs/faq',
    '/docs/troubleshooting',
    '/docs/changelog',
    '/docs/risk-limits',
    '/docs/source-readme-md',
    '/docs/source-docs-index-md',
    '/docs/source-docs-full-guide-md',
    '/docs/source-docs-deploy-md',
    '/docs/source-docs-deploy-webui-cloud-md',
    '/docs/source-docs-docker-zeabur-deployment-md',
    '/docs/source-docs-desktop-package-md',
    '/docs/source-docs-llm-config-guide-md',
    '/docs/source-docs-llm-providers-md',
    '/docs/source-docs-notifications-md',
    '/docs/source-docs-bot-command-md',
    '/docs/source-docs-bot-feishu-bot-config-md',
    '/docs/source-docs-bot-dingding-bot-config-md',
    '/docs/source-docs-bot-discord-bot-config-md',
    '/docs/source-docs-tushare-stock-list-guide-md',
    '/docs/source-docs-faq-md',
    '/docs/source-docs-changelog-md',
    '/docs/source-docs-contributing-md',
    '/docs/source-docs-openclaw-skill-integration-md',
    '/docs/source-strategies-readme-md',
    '/docs/source-docs-examples-litellm-config-example-yaml',
    '/docs/source-docs-architecture-api-spec-json',
  ];

  const validSlugs = new Set(['docs', 'en/docs']);
  for (const spec of SYNC_SPECS) {
    validSlugs.add(spec.target.replace(/\.md$/, ''));
    if (spec.enSources) {
      validSlugs.add(`en/${spec.target.replace(/\.md$/, '')}`);
    }
  }
  const contentRoot = path.join(SITE_ROOT, 'src', 'content', 'docs');
  function collectMdxSlugs(dir, prefix = '') {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        collectMdxSlugs(path.join(dir, entry.name), rel);
      } else if (entry.isFile() && entry.name.endsWith('.mdx')) {
        if (entry.name === 'index.mdx') {
          if (prefix) validSlugs.add(prefix);
        } else {
          validSlugs.add(rel.replace(/\.mdx$/, ''));
        }
      }
    }
  }
  collectMdxSlugs(contentRoot);

  for (const legacyPath of requiredLegacyRedirects) {
    const target = redirects[legacyPath];
    assert.ok(target, `Missing redirect for legacy path ${legacyPath}`);
    if (target !== '/') {
      const slug = target.replace(/^\/|\/$/g, '');
      assert.equal(validSlugs.has(slug), true, `Redirect ${legacyPath} -> ${target} points to missing slug ${slug}`);
    }
  }

  const astroText = fs.readFileSync(path.join(SITE_ROOT, 'astro.config.mjs'), 'utf8');
  const sidebarSlugs = Array.from(astroText.matchAll(/slug:\s*'([^']+)'/g), (m) => m[1]);
  assert.ok(sidebarSlugs.length > 20, 'Expected sidebar slugs in astro.config.mjs');
  for (const slug of sidebarSlugs) {
    assert.equal(validSlugs.has(slug), true, `Sidebar slug ${slug} does not resolve to an MDX or SYNC_SPECS page`);
  }
});

test('landing page and docs honor review regression guards', () => {
  const landing = fs.readFileSync(path.join(SITE_ROOT, 'src', 'components', 'LandingPage.astro'), 'utf8');
  assert.equal(landing.includes('stratsPresets'), false);
  assert.equal(landing.includes('TELEGRAM_CHAT_ID'), true);
  assert.equal(landing.includes('EMAIL_PASSWORD'), true);
  assert.match(landing, /Edit \.env:/);
  assert.match(landing, /编辑 \.env/);

  const validLocalDocRoutes = new Set(['/docs/', '/en/docs/']);
  for (const spec of SYNC_SPECS) {
    validLocalDocRoutes.add(`/${spec.target.replace(/\.md$/, '')}/`);
    if (spec.enSources) {
      validLocalDocRoutes.add(`/en/${spec.target.replace(/\.md$/, '')}/`);
    }
  }
  const mdxRoutes = [
    '/docs/getting-started/quick-start/',
    '/docs/getting-started/env-config/',
    '/docs/features/webui-and-agent/',
    '/docs/deployment/github-actions/',
    '/docs/deployment/local/',
    '/docs/reference/api/',
    '/docs/reference/risk-and-disclaimer/',
    '/en/docs/getting-started/quick-start/',
    '/en/docs/getting-started/env-config/',
    '/en/docs/features/webui-and-agent/',
    '/en/docs/deployment/github-actions/',
    '/en/docs/deployment/local/',
    '/en/docs/reference/api/',
    '/en/docs/reference/risk-and-disclaimer/',
  ];
  for (const r of mdxRoutes) validLocalDocRoutes.add(r);

  for (const m of landing.matchAll(/localizeDoc\('([^']+)'\)/g)) {
    assert.equal(validLocalDocRoutes.has(m[1]), true, `localizeDoc target missing: ${m[1]}`);
  }

  const envConfig = fs.readFileSync(path.join(SITE_ROOT, 'src', 'content', 'docs', 'docs', 'getting-started', 'env-config.mdx'), 'utf8');
  assert.equal(envConfig.includes('deepseek-chat'), false);

  const enEnvConfig = fs.readFileSync(path.join(SITE_ROOT, 'src', 'content', 'docs', 'en', 'docs', 'getting-started', 'env-config.mdx'), 'utf8');
  assert.equal(enEnvConfig.includes('deepseek-chat'), false);
  assert.equal(enEnvConfig.includes('openai/Qwen/Qwen3-32B'), true);
  assert.equal(enEnvConfig.includes('LITELLM_MODEL=deepseek/deepseek-flash'), true);
  assert.equal(enEnvConfig.includes('LITELLM_MODEL=deepseek/deepseek-v4-pro'), true);

  const webuiDoc = fs.readFileSync(path.join(SITE_ROOT, 'src', 'content', 'docs', 'docs', 'features', 'webui-and-agent.mdx'), 'utf8');
  assert.equal(webuiDoc.includes('/decision-signals'), true);
  assert.equal(webuiDoc.includes('| `/signals` |'), false);
  assert.match(webuiDoc, /hermes/i);

  const enWebuiDoc = fs.readFileSync(path.join(SITE_ROOT, 'src', 'content', 'docs', 'en', 'docs', 'features', 'webui-and-agent.mdx'), 'utf8');
  assert.equal(enWebuiDoc.includes('/decision-signals'), true);
  assert.equal(enWebuiDoc.includes('| `/signals` |'), false);
  assert.match(enWebuiDoc, /hermes/i);

  const actionsDoc = fs.readFileSync(path.join(SITE_ROOT, 'src', 'content', 'docs', 'docs', 'deployment', 'github-actions.mdx'), 'utf8');
  assert.equal(actionsDoc.includes('LLM_CHANNELS=x6ai'), true);
  assert.equal(actionsDoc.includes('LLM_X6AI_BASE_URL=https://api.x6.ai/v1'), true);
  assert.equal(actionsDoc.includes('LLM_X6AI_MODELS='), true);
  assert.doesNotMatch(actionsDoc, /\|\s*`LLM_X6AI_API_KEY`\s*\|/);

  const enActionsDoc = fs.readFileSync(path.join(SITE_ROOT, 'src', 'content', 'docs', 'en', 'docs', 'deployment', 'github-actions.mdx'), 'utf8');
  assert.equal(enActionsDoc.includes('LLM_CHANNELS=x6ai'), true);
  assert.equal(enActionsDoc.includes('LLM_X6AI_BASE_URL=https://api.x6.ai/v1'), true);
  assert.equal(enActionsDoc.includes('LLM_X6AI_MODELS='), true);
  assert.equal(enActionsDoc.includes('openai/Qwen/Qwen3-32B'), true);
  assert.equal(enActionsDoc.includes('LITELLM_MODEL=deepseek/deepseek-flash'), true);
  assert.equal(enActionsDoc.includes('LITELLM_MODEL=deepseek/deepseek-v4-pro'), true);
  assert.doesNotMatch(enActionsDoc, /\|\s*`LLM_X6AI_API_KEY`\s*\|/);

  assert.equal(fs.existsSync(path.join(SITE_ROOT, 'public', 'assets', 'dsa-vi-dark.png')), false);
  assert.equal(fs.existsSync(path.join(SITE_ROOT, 'public', 'assets', 'dsa-vi-light.png')), false);
});

test('landing page AlphaSift Daily Picks link meets WCAG AA text contrast in light and dark themes', () => {
  const landing = fs.readFileSync(path.join(SITE_ROOT, 'src', 'components', 'LandingPage.astro'), 'utf8');
  const css = fs.readFileSync(path.join(SITE_ROOT, 'src', 'styles', 'landing.css'), 'utf8');

  const linkMatch = landing.match(/<a[^>]*alphasift\.zhulinsen\.tech[^>]*style="([^"]+)"[^>]*>\s*\{isEn \? 'Daily Picks ↗' : '在线今日榜单 ↗'\}/s);
  assert.ok(linkMatch, 'Expected AlphaSift Daily Picks anchor in LandingPage.astro');
  assert.match(linkMatch[1], /--ob-accent-strong/);
  assert.doesNotMatch(linkMatch[1], /var\(--ob-accent\)/);

  function extractBlockVars(selectorPattern) {
    const match = css.match(selectorPattern);
    assert.ok(match, `Missing CSS block matching ${selectorPattern}`);
    const vars = {};
    for (const m of match[1].matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
      vars[m[1]] = m[2];
    }
    return vars;
  }

  function contrastRatio(fgHex, bgHex) {
    const relLum = (hex) => {
      const rgb = [0, 2, 4].map((i) => Number.parseInt(hex.slice(1 + i, 3 + i), 16) / 255);
      const lin = rgb.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
      return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
    };
    const [l1, l2] = [relLum(fgHex), relLum(bgHex)].sort((a, b) => b - a);
    return (l1 + 0.05) / (l2 + 0.05);
  }

  const darkVars = extractBlockVars(/:root,\s*:root\[data-theme="dark"\]\s*\{([^}]+)\}/);
  const lightVars = extractBlockVars(/:root\[data-theme="light"\]\s*\{([^}]+)\}/);

  assert.ok(contrastRatio(lightVars['--ob-accent-strong'], lightVars['--ob-surface']) >= 4.5);
  assert.ok(contrastRatio(darkVars['--ob-accent-strong'], darkVars['--ob-surface']) >= 4.5);
});

test('prepareDocs generates English counterparts for beginner setup, market support, and notifications', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-site-en-docs-'));
  try {
    const fakeDsa = path.join(tmpRoot, 'dsa');
    const fakeSite = path.join(tmpRoot, 'site');
    writeMinimalFixtureDsaRepo(fakeDsa);

    fs.writeFileSync(
      path.join(fakeDsa, 'docs', 'full-guide_EN.md'),
      [
        '# Full Guide (EN)',
        '- [Beginner](beginner-client-setup_EN.md)',
        '- [Market](market-support_EN.md)',
        '- [Notifications](notifications_EN.md)',
      ].join('\n'),
      'utf8',
    );

    const meta = prepareDocs({ siteRoot: fakeSite, dsaRoot: fakeDsa, quiet: true });
    assert.equal(meta.syncedEnDocs >= 9, true);

    for (const [relPath, expectedTitle] of [
      ['en/docs/getting-started/beginner-client.md', 'Beginner Desktop Setup Guide'],
      ['en/docs/features/market-support.md', 'Multi-Market Support & Boundaries'],
      ['en/docs/configuration/notifications.md', 'Notification Channels & Routing Baseline'],
    ]) {
      const fullPath = path.join(fakeSite, 'src', 'content', 'docs', ...relPath.split('/'));
      assert.equal(fs.existsSync(fullPath), true, `Missing synced EN doc: ${relPath}`);
      const content = fs.readFileSync(fullPath, 'utf8');
      assert.equal(content.includes(expectedTitle), true, `Expected EN title in ${relPath}`);
    }

    const fullGuideEnContent = fs.readFileSync(
      path.join(fakeSite, 'src', 'content', 'docs', 'en', 'docs', 'reference', 'full-guide.md'),
      'utf8',
    );
    assert.equal(fullGuideEnContent.includes('/en/docs/getting-started/beginner-client/'), true);
    assert.equal(fullGuideEnContent.includes('/en/docs/features/market-support/'), true);
    assert.equal(fullGuideEnContent.includes('/en/docs/configuration/notifications/'), true);
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
});
