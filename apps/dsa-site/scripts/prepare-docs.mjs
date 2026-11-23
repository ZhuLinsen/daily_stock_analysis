#!/usr/bin/env node
/**
 * Prepare upstream DSA docs, images, OpenAPI summary, and repo metadata
 * for Astro + Starlight without duplicating docs in Git.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_SITE_ROOT = path.resolve(__dirname, '..');

const DSA_REPO = 'https://github.com/ZhuLinsen/daily_stock_analysis';

export const SOURCE_ROUTE_MAP = {
  'README.md': '/',
  'docs/README_EN.md': '/en/',
  'docs/README_CHT.md': '/',
  'docs/INDEX.md': '/docs/',
  'docs/INDEX_EN.md': '/en/docs/',
  'docs/beginner-client-setup.md': '/docs/getting-started/beginner-client/',
  'docs/market-support.md': '/docs/features/market-support/',
  'docs/decision-signals.md': '/docs/features/decision-signals/',
  'strategies/README.md': '/docs/features/strategies/',
  'docs/alerts.md': '/docs/features/alerts/',
  'docs/portfolio-risk-exposure-dashboard.md': '/docs/features/portfolio-risk/',
  'docs/etf-rotation.md': '/docs/features/etf-rotation/',
  'docs/screening-engine.md': '/docs/features/screening/',
  'docs/watchlist-next-action.md': '/docs/features/watchlist-and-share/',
  'docs/share-images.md': '/docs/features/watchlist-and-share/',
  'docs/LLM_CONFIG_GUIDE.md': '/docs/configuration/llm-guide/',
  'docs/LLM_CONFIG_GUIDE_EN.md': '/en/docs/configuration/llm-guide/',
  'docs/llm-providers.md': '/docs/configuration/llm-providers/',
  'docs/data-source-stability.md': '/docs/configuration/data-sources/',
  'docs/tickplus.md': '/docs/configuration/tickplus/',
  'docs/TUSHARE_STOCK_LIST_GUIDE.md': '/docs/configuration/tushare/',
  'docs/notifications.md': '/docs/configuration/notifications/',
  'docs/intelligence-sources.md': '/docs/configuration/intelligence-sources/',
  'docs/bot-command.md': '/docs/configuration/bot-commands/',
  'docs/bot-command_EN.md': '/en/docs/configuration/bot-commands/',
  'docs/bot/feishu-bot-config.md': '/docs/configuration/bot-platforms/',
  'docs/bot/dingding-bot-config.md': '/docs/configuration/bot-platforms/',
  'docs/bot/discord-bot-config.md': '/docs/configuration/bot-platforms/',
  'docs/openclaw-skill-integration.md': '/docs/configuration/skills-integration/',
  'docs/grok-bot-integration.md': '/docs/configuration/skills-integration/',
  'docs/DEPLOY.md': '/docs/deployment/docker/',
  'docs/DEPLOY_EN.md': '/en/docs/deployment/docker/',
  'docs/docker/zeabur-deployment.md': '/docs/deployment/zeabur/',
  'docs/deploy-webui-cloud.md': '/docs/deployment/cloud-webui/',
  'docs/desktop-package.md': '/docs/deployment/desktop-package/',
  'docs/FAQ.md': '/docs/deployment/faq/',
  'docs/FAQ_EN.md': '/en/docs/deployment/faq/',
  'docs/data-center-diagnostics.md': '/docs/reference/data-center/',
  'docs/analysis-context-pack.md': '/docs/reference/context-pack/',
  'docs/full-guide.md': '/docs/reference/full-guide/',
  'docs/full-guide_EN.md': '/en/docs/reference/full-guide/',
  'docs/CONTRIBUTING.md': '/docs/reference/contributing/',
  'docs/CONTRIBUTING_EN.md': '/en/docs/reference/contributing/',
  'docs/CHANGELOG.md': '/docs/reference/changelog/',
  'docs/architecture/api_spec.json': '/docs/reference/api/',
};

export const SYNC_SPECS = [
  {
    target: 'docs/getting-started/beginner-client.md',
    sources: ['docs/beginner-client-setup.md'],
    title: '小白桌面客户端安装与配置',
    description: '面向非技术用户的桌面客户端下载、AI Key 与自选股配置指南。',
  },
  {
    target: 'docs/features/market-support.md',
    sources: ['docs/market-support.md'],
    title: '6 大市场支持边界',
    description: 'A股、港股、美股、日股、韩股、台股及 ETF 的支持能力、代码规范与降级边界。',
  },
  {
    target: 'docs/features/decision-signals.md',
    sources: ['docs/decision-signals.md'],
    title: '决策信号与建议池',
    description: 'DecisionSignal 结构化建议池字段契约、Web 展示、通知联动与后验评估。',
  },
  {
    target: 'docs/features/strategies.md',
    sources: ['strategies/README.md'],
    title: 'Agent 15 种内置策略与自定义 Skill',
    description: '自然语言 YAML 交易策略编写指南、核心理念与默认策略目录。',
  },
  {
    target: 'docs/features/alerts.md',
    sources: ['docs/alerts.md'],
    title: '实时告警中心',
    description: '价格突破、均线穿插、MACD/RSI 告警规则管理、冷却控制与多渠道触发。',
  },
  {
    target: 'docs/features/portfolio-risk.md',
    sources: ['docs/portfolio-risk-exposure-dashboard.md'],
    title: '组合风险与暴露看板',
    description: '持仓页风险旗标、市场暴露、币种暴露及行情质量聚合展示。',
  },
  {
    target: 'docs/features/etf-rotation.md',
    sources: ['docs/etf-rotation.md'],
    title: 'ETF 双动量轮动',
    description: '规则化双动量 ETF 轮动策略、配置项、报告章节与参数平原解读。',
  },
  {
    target: 'docs/features/screening.md',
    sources: ['docs/screening-engine.md', 'docs/screening-explanations.md'],
    title: '全市场选股引擎',
    description: '全市场扫描选股引擎架构、因子评分规则与确定性选股解释契约。',
  },
  {
    target: 'docs/features/watchlist-and-share.md',
    sources: ['docs/watchlist-next-action.md', 'docs/share-images.md'],
    title: '自选信号状态与分享长图',
    description: '自选股变化三段信号规则以及移动端分享图片模板的数据填充契约。',
  },
  {
    target: 'docs/configuration/llm-guide.md',
    enSources: ['docs/LLM_CONFIG_GUIDE_EN.md'],
    sources: ['docs/LLM_CONFIG_GUIDE.md'],
    title: 'LLM 大模型配置指南',
    enTitle: 'LLM Configuration Guide',
    description: '大模型渠道接入、多模型路由、LiteLLM 高级配置与视觉模型说明。',
    enDescription: 'Configure LLM providers, multi-model routing, LiteLLM, and vision models.',
  },
  {
    target: 'docs/configuration/llm-providers.md',
    sources: ['docs/llm-providers.md'],
    title: 'LLM 服务商配置参考',
    description: '主流 LLM 服务商预设、Actions Secret 映射、错误分类与诊断建议。',
  },
  {
    target: 'docs/configuration/data-sources.md',
    sources: ['docs/data-source-stability.md'],
    title: '数据源稳定性与降级策略',
    description: '多市场行情源优先级、熔断恢复机制、缓存策略与统一只读数据能力契约。',
  },
  {
    target: 'docs/configuration/tickplus.md',
    sources: ['docs/tickplus.md'],
    title: 'TickPlus 接入指南',
    description: 'A 股与 ETF 首选推荐行情源 TickPlus 的申请与配置说明。',
  },
  {
    target: 'docs/configuration/tushare.md',
    sources: ['docs/TUSHARE_STOCK_LIST_GUIDE.md'],
    title: 'Tushare 股票列表与稳定行情',
    description: 'Tushare Token 配置、股票列表获取工具与积分权限降级处理。',
  },
  {
    target: 'docs/configuration/notifications.md',
    sources: ['docs/notifications.md'],
    title: '通知渠道配置基线',
    description: '企业微信、飞书、Telegram、Discord、Slack、邮件、Bark 与 ntfy 配置参考。',
  },
  {
    target: 'docs/configuration/intelligence-sources.md',
    sources: ['docs/intelligence-sources.md'],
    title: '资讯与 RSS 情报源',
    description: '合规 RSS/Atom 金融资讯源配置、定时抓取、去重与安全边界。',
  },
  {
    target: 'docs/configuration/bot-commands.md',
    enSources: ['docs/bot-command_EN.md'],
    sources: ['docs/bot-command.md'],
    title: 'Bot 命令与 Webhook 集成',
    enTitle: 'Bot Integration Guide',
    description: '聊天机器人指令体系、平台适配器设计与回调安全校验。',
    enDescription: 'Chat bot command architecture, webhook handlers, and platform adapters.',
  },
  {
    target: 'docs/configuration/bot-platforms.md',
    sources: [
      'docs/bot/feishu-bot-config.md',
      'docs/bot/dingding-bot-config.md',
      'docs/bot/discord-bot-config.md',
    ],
    title: '飞书 / 钉钉 / Discord 机器人配置',
    description: '主流办公与社区平台机器人创建、Stream 模式与权限设置图文指南。',
  },
  {
    target: 'docs/configuration/skills-integration.md',
    sources: [
      'docs/openclaw-skill-integration.md',
      'docs/grok-bot-integration.md',
    ],
    title: 'OpenClaw 与 Grok Skill 集成',
    description: '通过 REST API 与 Skill 规范将 DSA 接入外部 AI 助手或团队工作流。',
  },
  {
    target: 'docs/deployment/docker.md',
    enSources: ['docs/DEPLOY_EN.md'],
    sources: ['docs/DEPLOY.md'],
    title: 'Docker 与服务器部署指南',
    enTitle: 'Deployment Guide',
    description: 'Docker Compose、官方镜像、systemd、Supervisor 与生产环境变量部署指南。',
    enDescription: 'Deploy DSA using Docker Compose, official images, or Linux servers.',
  },
  {
    target: 'docs/deployment/zeabur.md',
    sources: ['docs/docker/zeabur-deployment.md'],
    title: 'Zeabur 一键云部署',
    description: '使用 Zeabur 容器平台零运维托管 DSA 分析服务与 WebUI。',
  },
  {
    target: 'docs/deployment/cloud-webui.md',
    sources: ['docs/deploy-webui-cloud.md'],
    title: '云服务器 WebUI 安全访问',
    description: '公网服务器暴露 WebUI 时的反向代理、HTTPS 与管理员鉴权配置。',
  },
  {
    target: 'docs/deployment/desktop-package.md',
    sources: ['docs/desktop-package.md'],
    title: '桌面客户端打包说明',
    description: 'Electron + React UI 跨平台桌面客户端构建、签名与发版流程。',
  },
  {
    target: 'docs/deployment/faq.md',
    enSources: ['docs/FAQ_EN.md'],
    sources: ['docs/FAQ.md'],
    title: '常见问题解答 (FAQ)',
    enTitle: 'Frequently Asked Questions',
    description: '安装、数据源报错、LLM 限流、Docker 架构与通知推送高频问题排查。',
    enDescription: 'Troubleshooting guide for installation, market data, LLMs, and notifications.',
  },
  {
    target: 'docs/reference/data-center.md',
    sources: ['docs/data-center-diagnostics.md'],
    title: '数据中心与诊断契约',
    description: '只读 Provider 能力概览、数据集质量状态与运行时优先级契约。',
  },
  {
    target: 'docs/reference/context-pack.md',
    sources: ['docs/analysis-context-pack.md'],
    title: '分析上下文包架构契约',
    description: 'AnalysisContextPack 结构、数据质量评分与各分析阶段消费边界。',
  },
  {
    target: 'docs/reference/full-guide.md',
    enSources: ['docs/full-guide_EN.md'],
    sources: ['docs/full-guide.md'],
    title: '完整配置与部署大全',
    enTitle: 'Complete Configuration Guide',
    description: '全量环境变量、调度规则、交易纪律、回测与系统行为的完整参考手册。',
    enDescription: 'Complete reference covering all environment variables, scheduling, and features.',
  },
  {
    target: 'docs/reference/contributing.md',
    enSources: ['docs/CONTRIBUTING_EN.md'],
    sources: ['docs/CONTRIBUTING.md'],
    title: '贡献指南',
    enTitle: 'Contributing Guide',
    description: '开发环境搭建、测试门禁、PR 规范与文档同步要求。',
    enDescription: 'Development setup, test gates, PR conventions, and documentation rules.',
  },
  {
    target: 'docs/reference/changelog.md',
    sources: ['docs/CHANGELOG.md'],
    title: '版本更新日志',
    description: 'DSA 近期发布版本的功能演进、稳定性修复与升级注意事项。',
    mode: 'changelog',
  },
];

const ALERT_MAP = {
  NOTE: 'note',
  TIP: 'tip',
  IMPORTANT: 'caution',
  WARNING: 'caution',
  CAUTION: 'danger',
};

const ALERT_TITLES = {
  zh: { NOTE: '说明', TIP: '提示', IMPORTANT: '重要', WARNING: '注意', CAUTION: '警告' },
  en: { NOTE: 'Note', TIP: 'Tip', IMPORTANT: 'Important', WARNING: 'Warning', CAUTION: 'Caution' },
};

const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']);

function runGit(dsaRoot, args) {
  return execFileSync('git', ['-C', dsaRoot, ...args], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
}

function readGitMetadata(dsaRoot) {
  let dsaCommit = 'unknown';
  let versionLabel = 'latest';
  try {
    dsaCommit = runGit(dsaRoot, ['rev-parse', '--short', 'HEAD']);
  } catch {}
  try {
    versionLabel = runGit(dsaRoot, ['describe', '--tags', '--always']);
  } catch {}

  const changelogPath = path.join(dsaRoot, 'docs', 'CHANGELOG.md');
  if ((versionLabel === 'latest' || !versionLabel.startsWith('v')) && fs.existsSync(changelogPath)) {
    const text = fs.readFileSync(changelogPath, 'utf8');
    const match = text.match(/^##\s+\[(\d+\.\d+\.\d+)\]/m);
    if (match) versionLabel = `v${match[1]}`;
  }

  return {
    dsaCommit,
    versionLabel,
    syncedAt: new Date().toISOString().slice(0, 10),
    repoUrl: DSA_REPO,
  };
}

function cleanGeneratedMarkdown(dir) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      cleanGeneratedMarkdown(fullPath);
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      fs.unlinkSync(fullPath);
    }
  }
}

function trimChangelog(markdown, maxReleases = 12) {
  const parts = markdown.split(/(?=^## \[)/m);
  if (parts.length <= maxReleases + 1) return markdown;
  const kept = parts.slice(0, maxReleases + 1).join('').trimEnd();
  return `${kept}\n\n---\n\n> 更早版本的完整历史变更记录请前往 [GitHub CHANGELOG.md](${DSA_REPO}/blob/main/docs/CHANGELOG.md) 或 [Releases](${DSA_REPO}/releases) 查看。\n`;
}

function stripFirstH1(text) {
  const lines = text.split('\n');
  const out = [];
  let removed = false;
  let inFence = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('```')) {
      inFence = !inFence;
    }
    if (!inFence && !removed && /^#\s+\S/.test(line)) {
      removed = true;
      continue;
    }
    if (removed && out.length === 0 && trimmed === '') {
      continue;
    }
    out.push(line);
  }
  return out.join('\n');
}

function normalizeCodeFences(text) {
  const lines = text.split('\n');
  const out = [];
  let inFence = false;
  for (const line of lines) {
    const m = line.match(/^(\s*)```(.*)$/);
    if (m) {
      if (!inFence) {
        inFence = true;
        const lang = m[2].trim();
        if (lang.toLowerCase() === 'env') {
          out.push(`${m[1]}\`\`\`ini`);
          continue;
        }
      } else if (m[2].trim() === '') {
        inFence = false;
      }
    }
    out.push(line);
  }
  return out.join('\n');
}

function convertGithubAlerts(text, lang) {
  const lines = text.split('\n');
  const out = [];
  let i = 0;
  let inFence = false;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith('```')) {
      inFence = !inFence;
      out.push(line);
      i += 1;
      continue;
    }
    if (!inFence) {
      const m = line.trim().match(/^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$/);
      if (m) {
        const kind = m[1];
        const asideType = ALERT_MAP[kind];
        const asideTitle = ALERT_TITLES[lang][kind];
        const bodyLines = [];
        if (m[2].trim()) bodyLines.push(m[2].trim());
        i += 1;
        while (i < lines.length && lines[i].trimStart().startsWith('>')) {
          bodyLines.push(lines[i].trimStart().replace(/^>\s?/, ''));
          i += 1;
        }
        out.push(`:::${asideType}[${asideTitle}]`);
        out.push(...bodyLines);
        out.push(':::');
        continue;
      }
    }
    out.push(line);
    i += 1;
  }
  return out.join('\n');
}

function resolveRepoPath(currentSource, target) {
  const clean = target.trim().replace(/^<|>$/g, '').trim();
  if (!clean || /^(https?:|mailto:|tel:|#|data:)/i.test(clean)) {
    return null;
  }
  const baseDir = path.posix.dirname(currentSource);
  const rawJoined = clean.startsWith('/') ? clean.slice(1) : path.posix.join(baseDir, clean);
  const normalized = path.posix.normalize(rawJoined).replace(/^(\.\.\/)+/, '').replace(/^\.\//, '');
  return normalized === '.' ? '' : normalized;
}

function copyAsset({ repoRel, dsaRoot, publicAssetsDir, copiedAssets }) {
  if (!repoRel) return null;
  const srcPath = path.join(dsaRoot, ...repoRel.split('/'));
  if (!fs.existsSync(srcPath) || !fs.statSync(srcPath).isFile()) {
    return null;
  }
  const destPath = path.join(publicAssetsDir, ...repoRel.split('/'));
  fs.mkdirSync(path.dirname(destPath), { recursive: true });
  fs.copyFileSync(srcPath, destPath);
  copiedAssets.add(repoRel);
  return `/docs-assets/${repoRel}`;
}

function rewriteLinksAndAssets(text, sourcePath, lang, assetContext) {
  function mapHref(rawUrl, isImage) {
    let urlNoTitle = rawUrl.trim();
    let titleSuffix = '';
    const titleMatch = urlNoTitle.match(/^(\S+)(\s+["'].*["'])$/);
    if (titleMatch) {
      urlNoTitle = titleMatch[1];
      titleSuffix = titleMatch[2];
    }

    const hashIdx = urlNoTitle.indexOf('#');
    const pathPart = hashIdx >= 0 ? urlNoTitle.slice(0, hashIdx) : urlNoTitle;
    const frag = hashIdx >= 0 ? urlNoTitle.slice(hashIdx) : '';

    const repoRel = resolveRepoPath(sourcePath, pathPart);
    if (repoRel === null) return rawUrl;

    const ext = path.posix.extname(repoRel).toLowerCase();
    if (isImage || IMAGE_EXTS.has(ext)) {
      const assetUrl = copyAsset({ repoRel, ...assetContext });
      if (assetUrl) return `${assetUrl}${titleSuffix}`;
      return `${DSA_REPO}/raw/main/${repoRel}${titleSuffix}`;
    }

    if (repoRel in SOURCE_ROUTE_MAP) {
      let route = SOURCE_ROUTE_MAP[repoRel];
      if (lang === 'en' && route.startsWith('/docs/') && !route.startsWith('/en/')) {
        route = `/en${route}`;
      }
      return `${route}${frag}${titleSuffix}`;
    }

    return `${DSA_REPO}/blob/main/${repoRel}${frag}${titleSuffix}`;
  }

  const lines = text.split('\n');
  const out = [];
  let inFence = false;
  for (let line of lines) {
    if (line.trim().startsWith('```')) {
      inFence = !inFence;
      out.push(line);
      continue;
    }
    if (inFence) {
      out.push(line);
      continue;
    }

    line = line.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_m, alt, href) => `![${alt}](${mapHref(href, true)})`);
    line = line.replace(/(?<!!)\[([^\]]+)\]\(([^)]+)\)/g, (_m, label, href) => `[${label}](${mapHref(href, false)})`);
    line = line.replace(/(<img\b[^>]*?\bsrc=["'])([^"']+)(["'])/gi, (_m, pre, src, post) => `${pre}${mapHref(src, true)}${post}`);
    out.push(line);
  }
  return out.join('\n');
}

function sanitizeMarkdown(raw, sourcePath, lang, assetContext, mode) {
  let text = raw.replace(/\r\n/g, '\n').replace(/^\uFEFF/, '');
  if (mode === 'changelog') {
    text = trimChangelog(text);
  }
  text = stripFirstH1(text);
  text = normalizeCodeFences(text);
  text = convertGithubAlerts(text, lang);
  text = rewriteLinksAndAssets(text, sourcePath, lang, assetContext);
  return text.replace(/\n{4,}/g, '\n\n\n').trim() + '\n';
}

function buildFrontmatter(title, description, editUrl) {
  return [
    '---',
    `title: ${JSON.stringify(title)}`,
    `description: ${JSON.stringify(description)}`,
    `editUrl: ${JSON.stringify(editUrl)}`,
    '---',
    '',
  ].join('\n');
}

function resolveSchemaName(schemaObj) {
  if (!schemaObj || typeof schemaObj !== 'object') return '';
  if (schemaObj.$ref) return String(schemaObj.$ref).split('/').pop() || '';
  if (schemaObj.type === 'array' && schemaObj.items && typeof schemaObj.items === 'object') {
    const inner = resolveSchemaName(schemaObj.items);
    return `Array<${inner || schemaObj.items.type || 'any'}>`;
  }
  return String(schemaObj.type || '');
}

function buildOpenApiSummary({ dsaRoot, publicOpenApiPath, openApiEndpointsPath }) {
  const specPath = path.join(dsaRoot, 'docs', 'architecture', 'api_spec.json');
  if (!fs.existsSync(specPath) || !fs.statSync(specPath).isFile()) {
    throw new Error('Missing required OpenAPI spec: docs/architecture/api_spec.json');
  }

  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  fs.mkdirSync(path.dirname(publicOpenApiPath), { recursive: true });
  fs.copyFileSync(specPath, publicOpenApiPath);

  const schemas = spec.components?.schemas || {};
  const endpoints = [];
  const allowedMethods = new Set(['get', 'post', 'put', 'patch', 'delete']);

  for (const [apiPath, pathItem] of Object.entries(spec.paths || {})) {
    if (!pathItem || typeof pathItem !== 'object') continue;
    for (const [method, op] of Object.entries(pathItem)) {
      if (!allowedMethods.has(method.toLowerCase()) || !op || typeof op !== 'object') continue;
      const tags = Array.isArray(op.tags) && op.tags.length ? op.tags : ['General'];
      const parameters = (Array.isArray(op.parameters) ? op.parameters : [])
        .filter((p) => p && typeof p === 'object')
        .map((p) => ({
          name: p.name || '',
          in: p.in || 'query',
          required: Boolean(p.required),
          type: resolveSchemaName(p.schema),
          description: p.description || '',
        }));

      const reqSchema = resolveSchemaName(op.requestBody?.content?.['application/json']?.schema);
      const responses = Object.entries(op.responses || {})
        .filter(([, resp]) => resp && typeof resp === 'object')
        .map(([code, resp]) => ({
          code: String(code),
          description: resp.description || '',
          schema: resolveSchemaName(resp.content?.['application/json']?.schema),
        }));

      endpoints.push({
        tag: tags[0],
        method: method.toUpperCase(),
        path: apiPath,
        summary: op.summary || apiPath,
        description: String(op.description || '').trim(),
        parameters,
        requestSchema: reqSchema,
        responses,
      });
    }
  }

  const payload = {
    info: {
      title: spec.info?.title || 'Daily Stock Analysis API',
      version: spec.info?.version || '1.0.0',
      description: spec.info?.description || '',
    },
    tags: Array.from(new Set(endpoints.map((e) => e.tag))).sort(),
    schemaCount: Object.keys(schemas).length,
    endpointCount: endpoints.length,
    endpoints,
  };

  fs.mkdirSync(path.dirname(openApiEndpointsPath), { recursive: true });
  fs.writeFileSync(openApiEndpointsPath, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  return endpoints.length;
}

function collectMissingSources(dsaRoot) {
  const missing = [];
  for (const spec of SYNC_SPECS) {
    for (const srcRel of spec.sources) {
      const srcFile = path.join(dsaRoot, ...srcRel.split('/'));
      if (!fs.existsSync(srcFile) || !fs.statSync(srcFile).isFile()) {
        missing.push(srcRel);
      }
    }
    if (spec.enSources) {
      for (const srcRel of spec.enSources) {
        const srcFile = path.join(dsaRoot, ...srcRel.split('/'));
        if (!fs.existsSync(srcFile) || !fs.statSync(srcFile).isFile()) {
          missing.push(srcRel);
        }
      }
    }
  }
  return missing;
}

function syncDocEntry({
  dsaRoot,
  contentRoot,
  target,
  sources,
  title,
  description,
  lang,
  assetContext,
  mode,
}) {
  const parts = [];

  for (const srcRel of sources) {
    const srcFile = path.join(dsaRoot, ...srcRel.split('/'));
    if (!fs.existsSync(srcFile) || !fs.statSync(srcFile).isFile()) {
      throw new Error(`Missing required upstream doc: ${srcRel}`);
    }
    const raw = fs.readFileSync(srcFile, 'utf8');
    const cleaned = sanitizeMarkdown(raw, srcRel, lang, assetContext, mode);
    if (sources.length > 1) {
      const h1 = raw.match(/^#\s+(.+)$/m);
      const rawHeading = h1 ? h1[1].trim() : path.posix.basename(srcRel, '.md');
      const sectionTitle = rawHeading.replace(/^[^\w\u4e00-\u9fff]+/, '').trim();
      parts.push(`## ${sectionTitle}\n\n${cleaned}`);
    } else {
      parts.push(cleaned);
    }
  }

  const editUrl = `${DSA_REPO}/edit/main/${sources[0]}`;
  let output = buildFrontmatter(title, description, editUrl) + parts.join('\n\n---\n\n');
  if (!output.endsWith('\n')) output += '\n';

  const dest = path.join(contentRoot, ...target.split('/'));
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, output, 'utf8');
  return true;
}

export function prepareDocs({
  siteRoot = DEFAULT_SITE_ROOT,
  dsaRoot = path.resolve(siteRoot, '../..'),
  quiet = false,
} = {}) {
  const contentRoot = path.join(siteRoot, 'src', 'content', 'docs');
  const publicAssetsDir = path.join(siteRoot, 'public', 'docs-assets');
  const publicOpenApiPath = path.join(siteRoot, 'public', 'openapi.json');
  const siteMetaPath = path.join(siteRoot, 'src', 'data', 'site-meta.json');
  const openApiEndpointsPath = path.join(siteRoot, 'src', 'data', 'openapi-endpoints.json');

  // Remove all generated outputs up front so failed/repeat builds never retain stale files.
  cleanGeneratedMarkdown(contentRoot);
  fs.rmSync(publicAssetsDir, { recursive: true, force: true });
  fs.rmSync(publicOpenApiPath, { force: true });
  fs.rmSync(openApiEndpointsPath, { force: true });
  fs.rmSync(siteMetaPath, { force: true });
  fs.mkdirSync(publicAssetsDir, { recursive: true });

  const missingSources = collectMissingSources(dsaRoot);
  if (missingSources.length > 0) {
    throw new Error(`Missing required upstream docs:\n- ${missingSources.join('\n- ')}`);
  }

  const endpointCount = buildOpenApiSummary({
    dsaRoot,
    publicOpenApiPath,
    openApiEndpointsPath,
  });

  const meta = readGitMetadata(dsaRoot);
  meta.apiEndpointCount = endpointCount;

  const copiedAssets = new Set();
  const assetContext = { dsaRoot, publicAssetsDir, copiedAssets };
  let syncedZh = 0;
  let syncedEn = 0;

  for (const spec of SYNC_SPECS) {
    syncDocEntry({
      dsaRoot,
      contentRoot,
      target: spec.target,
      sources: spec.sources,
      title: spec.title,
      description: spec.description,
      lang: 'zh',
      assetContext,
      mode: spec.mode,
    });
    syncedZh += 1;

    if (spec.enSources) {
      syncDocEntry({
        dsaRoot,
        contentRoot,
        target: `en/${spec.target}`,
        sources: spec.enSources,
        title: spec.enTitle || spec.title,
        description: spec.enDescription || spec.description,
        lang: 'en',
        assetContext,
        mode: spec.mode,
      });
      syncedEn += 1;
    }
  }

  meta.syncedZhDocs = syncedZh;
  meta.syncedEnDocs = syncedEn;
  meta.copiedAssets = copiedAssets.size;

  fs.mkdirSync(path.dirname(siteMetaPath), { recursive: true });
  fs.writeFileSync(siteMetaPath, JSON.stringify(meta, null, 2) + '\n', 'utf8');

  if (!quiet) {
    console.log(
      `[prepare-docs] ${syncedZh} zh docs, ${syncedEn} en docs, ${copiedAssets.size} assets, ${endpointCount} OpenAPI endpoints (DSA ${meta.versionLabel} @ ${meta.dsaCommit})`,
    );
  }

  return meta;
}

const isMainModule =
  Boolean(process.argv[1]) &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMainModule) {
  prepareDocs();
}
