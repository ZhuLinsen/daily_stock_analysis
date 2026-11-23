import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: 'https://dsa.zhulinsen.tech',
  vite: {
    plugins: [tailwindcss()],
  },
  redirects: {
    '/docs/quick-start': '/docs/getting-started/quick-start/',
    '/docs/env-config': '/docs/getting-started/env-config/',
    '/docs/github-actions': '/docs/deployment/github-actions/',
    '/docs/local': '/docs/deployment/local/',
    '/docs/docker': '/docs/deployment/docker/',
    '/docs/llm-config': '/docs/configuration/llm-guide/',
    '/docs/notifications': '/docs/configuration/notifications/',
    '/docs/data-sources': '/docs/configuration/data-sources/',
    '/docs/webui': '/docs/features/webui-and-agent/',
    '/docs/bot': '/docs/configuration/bot-commands/',
    '/docs/faq': '/docs/deployment/faq/',
    '/docs/troubleshooting': '/docs/deployment/faq/',
    '/docs/changelog': '/docs/reference/changelog/',
    '/docs/risk-limits': '/docs/reference/risk-and-disclaimer/',
    '/docs/source-readme-md': '/',
    '/docs/source-docs-index-md': '/docs/',
    '/docs/source-docs-full-guide-md': '/docs/reference/full-guide/',
    '/docs/source-docs-deploy-md': '/docs/deployment/docker/',
    '/docs/source-docs-deploy-webui-cloud-md': '/docs/deployment/cloud-webui/',
    '/docs/source-docs-docker-zeabur-deployment-md': '/docs/deployment/zeabur/',
    '/docs/source-docs-desktop-package-md': '/docs/deployment/desktop-package/',
    '/docs/source-docs-llm-config-guide-md': '/docs/configuration/llm-guide/',
    '/docs/source-docs-llm-providers-md': '/docs/configuration/llm-providers/',
    '/docs/source-docs-notifications-md': '/docs/configuration/notifications/',
    '/docs/source-docs-bot-command-md': '/docs/configuration/bot-commands/',
    '/docs/source-docs-bot-feishu-bot-config-md': '/docs/configuration/bot-platforms/',
    '/docs/source-docs-bot-dingding-bot-config-md': '/docs/configuration/bot-platforms/',
    '/docs/source-docs-bot-discord-bot-config-md': '/docs/configuration/bot-platforms/',
    '/docs/source-docs-tushare-stock-list-guide-md': '/docs/configuration/tushare/',
    '/docs/source-docs-faq-md': '/docs/deployment/faq/',
    '/docs/source-docs-changelog-md': '/docs/reference/changelog/',
    '/docs/source-docs-contributing-md': '/docs/reference/contributing/',
    '/docs/source-docs-openclaw-skill-integration-md': '/docs/configuration/skills-integration/',
    '/docs/source-strategies-readme-md': '/docs/features/strategies/',
    '/docs/source-docs-examples-litellm-config-example-yaml': '/docs/configuration/llm-guide/',
    '/docs/source-docs-architecture-api-spec-json': '/docs/reference/api/',
  },
  integrations: [
    starlight({
      title: 'DSA',
      description: 'LLM 驱动的多市场股票智能分析系统文档中心',
      favicon: '/assets/favicon.svg',
      logo: {
        src: './src/assets/dsa-mark.svg',
        alt: 'DSA',
        replacesTitle: false,
      },
      defaultLocale: 'root',
      locales: {
        root: { label: '简体中文', lang: 'zh-CN' },
        en: { label: 'English', lang: 'en' },
      },
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/ZhuLinsen/daily_stock_analysis',
        },
      ],
      editLink: {
        baseUrl: 'https://github.com/ZhuLinsen/daily_stock_analysis/edit/main/apps/dsa-site/',
      },
      customCss: ['./src/styles/starlight-obsidian.css'],
      expressiveCode: {
        themes: ['github-dark-default', 'github-light'],
        styleOverrides: {
          borderRadius: '10px',
          borderColor: 'rgba(255, 255, 255, 0.09)',
        },
      },
      sidebar: [
        {
          label: '快速上手',
          translations: { en: 'Getting Started' },
          items: [
            { label: '文档总览', translations: { en: 'Docs Overview' }, slug: 'docs' },
            {
              label: '选择运行方式',
              translations: { en: 'Quick Start' },
              slug: 'docs/getting-started/quick-start',
              badge: { text: '推荐', variant: 'tip' },
            },
            {
              label: '小白桌面端教程',
              translations: { en: 'Beginner Desktop Setup' },
              slug: 'docs/getting-started/beginner-client',
            },
            {
              label: '最小环境变量',
              translations: { en: 'Minimal Env Config' },
              slug: 'docs/getting-started/env-config',
            },
          ],
        },
        {
          label: '核心能力',
          translations: { en: 'Core Features' },
          items: [
            {
              label: '6 大市场支持边界',
              translations: { en: 'Market Support Matrix' },
              slug: 'docs/features/market-support',
            },
            {
              label: '决策信号与建议池',
              translations: { en: 'Decision Signals' },
              slug: 'docs/features/decision-signals',
            },
            {
              label: 'Agent 15 种内置策略',
              translations: { en: 'Trading Strategies' },
              slug: 'docs/features/strategies',
            },
            {
              label: 'WebUI 与 Agent 问股',
              translations: { en: 'WebUI & Agent Q&A' },
              slug: 'docs/features/webui-and-agent',
            },
            {
              label: '实时告警中心',
              translations: { en: 'Alert Center' },
              slug: 'docs/features/alerts',
            },
            {
              label: '组合风险与暴露看板',
              translations: { en: 'Portfolio Risk Dashboard' },
              slug: 'docs/features/portfolio-risk',
            },
            {
              label: 'ETF 双动量轮动',
              translations: { en: 'ETF Rotation' },
              slug: 'docs/features/etf-rotation',
            },
            {
              label: '全市场选股引擎',
              translations: { en: 'Screening Engine' },
              slug: 'docs/features/screening',
            },
            {
              label: '自选信号与分享长图',
              translations: { en: 'Watchlist & Share Images' },
              slug: 'docs/features/watchlist-and-share',
            },
          ],
        },
        {
          label: '配置与集成',
          translations: { en: 'Configuration & Integrations' },
          items: [
            {
              label: 'LLM 大模型配置',
              translations: { en: 'LLM Configuration' },
              slug: 'docs/configuration/llm-guide',
            },
            {
              label: 'LLM 服务商预设',
              translations: { en: 'LLM Providers' },
              slug: 'docs/configuration/llm-providers',
            },
            {
              label: '数据源稳定性与降级',
              translations: { en: 'Data Sources & Stability' },
              slug: 'docs/configuration/data-sources',
            },
            {
              label: 'TickPlus 数据源接入',
              translations: { en: 'TickPlus Integration' },
              slug: 'docs/configuration/tickplus',
            },
            {
              label: 'Tushare 股票列表工具',
              translations: { en: 'Tushare Stock List' },
              slug: 'docs/configuration/tushare',
            },
            {
              label: '通知渠道配置基线',
              translations: { en: 'Notifications' },
              slug: 'docs/configuration/notifications',
            },
            {
              label: 'RSS / 情报源接入',
              translations: { en: 'Intelligence Sources' },
              slug: 'docs/configuration/intelligence-sources',
            },
            {
              label: 'Bot 命令与回调架构',
              translations: { en: 'Bot Commands' },
              slug: 'docs/configuration/bot-commands',
            },
            {
              label: '飞书 / 钉钉 / Discord 配置',
              translations: { en: 'Bot Platforms' },
              slug: 'docs/configuration/bot-platforms',
            },
            {
              label: 'OpenClaw & Grok Skill',
              translations: { en: 'Skill Integrations' },
              slug: 'docs/configuration/skills-integration',
            },
          ],
        },
        {
          label: '部署与运维',
          translations: { en: 'Deployment & Operations' },
          items: [
            {
              label: 'GitHub Actions 零成本部署',
              translations: { en: 'GitHub Actions' },
              slug: 'docs/deployment/github-actions',
            },
            {
              label: 'Docker 与服务部署',
              translations: { en: 'Docker & Server Deploy' },
              slug: 'docs/deployment/docker',
            },
            {
              label: 'Zeabur 一键云部署',
              translations: { en: 'Zeabur Deployment' },
              slug: 'docs/deployment/zeabur',
            },
            {
              label: '本地运行与诊断',
              translations: { en: 'Local Run & Doctor' },
              slug: 'docs/deployment/local',
            },
            {
              label: '云服务器 WebUI 访问',
              translations: { en: 'Cloud WebUI Access' },
              slug: 'docs/deployment/cloud-webui',
            },
            {
              label: '桌面端打包说明',
              translations: { en: 'Desktop Packaging' },
              slug: 'docs/deployment/desktop-package',
            },
            {
              label: '常见问题排查 FAQ',
              translations: { en: 'FAQ & Troubleshooting' },
              slug: 'docs/deployment/faq',
            },
          ],
        },
        {
          label: '开发者参考',
          translations: { en: 'Developers & Reference' },
          items: [
            {
              label: 'OpenAPI 接口浏览器',
              translations: { en: 'OpenAPI Explorer' },
              slug: 'docs/reference/api',
            },
            {
              label: '数据中心诊断契约',
              translations: { en: 'Data Center Diagnostics' },
              slug: 'docs/reference/data-center',
            },
            {
              label: '分析上下文包契约',
              translations: { en: 'Analysis Context Pack' },
              slug: 'docs/reference/context-pack',
            },
            {
              label: '完整配置与部署大全',
              translations: { en: 'Full Configuration Guide' },
              slug: 'docs/reference/full-guide',
            },
            {
              label: '贡献指南',
              translations: { en: 'Contributing' },
              slug: 'docs/reference/contributing',
            },
            {
              label: '版本更新日志',
              translations: { en: 'Changelog' },
              slug: 'docs/reference/changelog',
            },
            {
              label: '研究边界与免责声明',
              translations: { en: 'Risk & Disclaimer' },
              slug: 'docs/reference/risk-and-disclaimer',
            },
          ],
        },
      ],
    }),
  ],
});
