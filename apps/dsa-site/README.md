# DSA Official Website & Docs (`apps/dsa-site`)

`daily_stock_analysis` 的官方产品官网与文档中心（在线地址：`https://dsa.zhulinsen.tech`），基于 **Astro + Starlight + Tailwind CSS v4** 构建，直接从主仓 `../../docs/`、`../../strategies/README.md` 与 `../../docs/architecture/api_spec.json` 实时编译生成，不在 Git 中保留重复的文档副本。

## 环境要求

- **Node.js**：`>= 22.23.4`（与 `package.json` `engines.node` 及锁定版本 `astro@7.4.13` 一致；建议使用 Node `22.23.4+` 或 `24 LTS`）

## 本地开发与构建

```bash
cd apps/dsa-site
npm ci
npm run dev       # 自动执行 predev 准备文档并启动本地预览 (http://localhost:4321)
npm run build     # 自动执行 prebuild 准备文档并输出全静态产物至 ./dist
npm test          # 运行构建产物/脚本/重定向与文档契约回归测试
```

## 目录说明

- `scripts/prepare-docs.mjs`：纯 Node.js（零额外依赖）预处理脚本，在 `dev` / `build` 前清空旧生成产物并读取主仓最新 Markdown、图片与 `docs/architecture/api_spec.json` 快照（任一必需上游输入缺失时直接失败并清理残留产物）。
- `src/components/LandingPage.astro`：Obsidian Bento 风格官网首页（支持明暗双主题与中英双语，与 Starlight 共享 `starlight-theme`）。
- `src/components/ApiExplorer.astro`：基于静态快照 `docs/architecture/api_spec.json` 的交互式 REST 接口浏览器。
- `src/content/docs/**/*.mdx`：手工精选导览页（如文档首页、快速开始、最小环境变量、静态 OpenAPI 快照入口等）。
- `astro.config.mjs`：Starlight 5 大支柱侧边栏与旧版 `dsa_page` 文档 URL 重定向映射（含短别名与 `/docs/source-*` 公开路径）。
- `tests/site-contracts.test.mjs`：预处理防残留/缺文件 fail-fast、旧路径重定向与文档内容契约测试。

## Cloudflare Workers Builds 部署配置

在 Cloudflare 控制台将 Worker `dsa-page` 关联到本仓库即可，无需在 GitHub 维护额外同步工作流：

- **Root directory**：留空（使构建脚本能访问仓库根目录的 `docs/` 与 `strategies/`）
- **Build command**：`cd apps/dsa-site && npm ci && npm run build`
- **Deploy command**：`cd apps/dsa-site && npx wrangler deploy`
- **Build watch paths**（可选）：`apps/dsa-site/**`、`docs/**`、`strategies/README.md`
- **Node.js version**：`22`（需 `>= 22.23.4`）

### 回滚与原构建来源恢复

如需在切换或升级后快速回滚线上站点：

1. **版本瞬时回滚**：进入 Cloudflare Dashboard → Workers & Pages → `dsa-page` → **Deployments**，选择上一个已验证版本点击 **Rollback**（详见 Cloudflare 官方文档 [Workers Rollbacks](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/)）。
2. **恢复原独立仓库构建来源**：若需切回旧版 `ZhuLinsen/dsa_page`，在 `dsa-page` → **Settings → Build → Git Repository** 中将绑定仓库与构建命令改回 `ZhuLinsen/dsa_page`（仅执行 `npx wrangler deploy` / static assets）并重新触发一次部署即可。
