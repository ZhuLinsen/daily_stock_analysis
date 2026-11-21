# DSA Official Website & Docs (`apps/dsa-site`)

`daily_stock_analysis` 的官方产品官网与文档中心（在线地址：`https://dsa.zhulinsen.tech`），基于 **Astro + Starlight + Tailwind CSS v4** 构建，直接从主仓 `../../docs/`、 `../../strategies/README.md` 与 `../../docs/architecture/api_spec.json` 实时编译生成，不在 Git 中保留重复的文档副本。

## 本地开发与构建

```bash
cd apps/dsa-site
npm install
npm run dev       # 自动执行 predev 准备文档并启动本地预览 (http://localhost:4321)
npm run build     # 自动执行 prebuild 准备文档并输出全静态产物至 ./dist
```

## 目录说明

- `scripts/prepare-docs.mjs`：纯 Node.js（零额外依赖）预处理脚本，在 `dev` / `build` 前自动读取主仓最新 Markdown、图片与 OpenAPI 规格并生成临时文档（由 `.gitignore` 忽略）。
- `src/components/LandingPage.astro`：Obsidian Bento 风格官网首页（支持明暗双主题与中英双语，与 Starlight 共享 `starlight-theme`）。
- `src/components/ApiExplorer.astro`：基于 `openapi.json` 的交互式 REST 接口浏览器。
- `src/content/docs/**/*.mdx`：手工精选导览页（如文档首页、快速开始、最小环境变量、OpenAPI 入口等）。
- `astro.config.mjs`：Starlight 5 大支柱侧边栏与旧版文档 URL 重定向映射。

## Cloudflare Workers Builds 部署配置

在 Cloudflare 控制台将 Worker `dsa-page` 关联到本仓库即可，无需在 GitHub 维护额外同步工作流：

- **Root directory**：留空（使构建脚本能访问仓库根目录的 `docs/` 与 `strategies/`）
- **Build command**：`cd apps/dsa-site && npm ci && npm run build`
- **Deploy command**：`cd apps/dsa-site && npx wrangler deploy`
- **Build watch paths**（可选）：`apps/dsa-site/**`、`docs/**`、`strategies/**`
- **Node.js version**：`22`
