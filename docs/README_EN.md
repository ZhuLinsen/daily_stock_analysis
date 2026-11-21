<div align="center">

<a name="ai-stock-analysis-system"></a>

# 📈 AI Stock Analysis System (DSA)

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![arXiv](https://img.shields.io/badge/arXiv-2608.26990-b31b1b.svg)](https://arxiv.org/abs/2608.26990)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

<p align="center">
  <a href="https://trendshift.io/repositories/18527?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-18527" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/18527" alt="ZhuLinsen%2Fdaily_stock_analysis | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://www.star-history.com/zhulinsen/daily_stock_analysis">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=ZhuLinsen/daily_stock_analysis&amp;type=rank&amp;theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=ZhuLinsen/daily_stock_analysis&amp;type=rank" />
      <img alt="Star History Rank" src="https://api.star-history.com/badge?repo=ZhuLinsen/daily_stock_analysis&amp;type=rank" height="55" />
    </picture>
  </a>
</p>

> 🤖 AI stock analysis for US, Hong Kong, Japanese, Korean, Taiwanese, and mainland Chinese markets, with daily Decision Dashboards, Agent strategy chat, backtesting, portfolio risk tracking, and multi-channel notifications.

[**Product Preview**](#-product-preview) · [**Key Features**](#-key-features) · [**Quick Start**](#-quick-start) · [**Sample Output**](#-sample-output) · [**Docs Index**](./INDEX_EN.md) · [**Full Guide**](./full-guide_EN.md)

English | [简体中文](../README.md) | [繁體中文](README_CHT.md)

</div>

<details open>
<summary><strong>💖 Sponsors</strong></summary>
<table>
  <tr><td align="center"><a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis"><img src="assets/modelflare_banner_en.png" alt="Modelflare" width="720"></a><br>Thanks to <strong>Modelflare</strong> for sponsoring this project! Operated by US-based Havenbyte LLC, it offers full-strength, stable GPT, Claude, Gemini, Grok and 40+ image/video models at lower cost. Selected OpenAI groups offer <strong>65% / 75% / 85% daily cache-hit guarantees</strong>; a single <strong>US$20 top-up unlocks GPT at 0.015x</strong>, and <strong>US$50 unlocks Claude at 0.03x</strong>. <a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis">Register via this exclusive link</a></td></tr>
  <tr><td align="center"><a href="https://console.x6pro.io/register?code=zJ2qSdns"><img src="./assets/x6ai_banner.png" alt="x6.ai" width="720" height="187"></a><br>100+ models from $5/month. Claude 81% off, GPT 91% off, DeepSeek 42% off, plus 20% off your first top-up. <a href="https://console.x6pro.io/register?code=zJ2qSdns">Register</a></td></tr>
  <tr><td align="center"><a href="https://serpapi.com/github-daily-stock-analysis" target="_blank"><img src="assets/serpapi_banner_en.png" alt="Easily scrape real-time financial news data from search engines - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a></td></tr>
</table>
</details>

## 🖥️ Product Preview

<p align="center">
  <a href="assets/readme_workspace_tour_20260510.gif"><img src="assets/readme_workspace_preview.gif" alt="DSA Web workspace demo" width="640"></a><br>
  <sub>Click the GIF to view the full demo</sub>
</p>

> [!TIP]
> 🚀 **Ecosystem Projects**: [AlphaSift · Smart screening](https://github.com/ZhuLinsen/alphasift) | [AlphaEvo · Strategy backtesting & evolution](https://github.com/ZhuLinsen/alphaevo)

## ✨ Key Features

| Stage | Core Capabilities & Entry Points | Docs |
|-------|----------------------------------|------|
| **Discover** | Multi-factor & natural-language screening (`/screening`), market hotspots, dual-momentum ETF rotation (`--etf-rotation`) | [Screening Engine](./screening-engine.md) · [ETF Rotation](./etf-rotation.md) |
| **Analyze** | 6-market Decision Dashboard (`/`), market review, multi-turn Agent strategy chat with 15 built-in strategies (`/chat`)<a name="-agent-strategy-chat"></a> | [Full Guide](./full-guide_EN.md) · [Market Boundaries](./market-support.md) |
| **Verify** | Decision signal pool (`/decision-signals`), win-rate backtest (`/backtest`), diagnostics & data-source health | [Decision Signals](./decision-signals.md) · [Data Center](./data-center-diagnostics.md) |
| **Track** | Portfolio ledger & risk exposure (`/portfolio`, CSV import; CLI `--portfolio futu`), real-time alerts (`/alerts`), token usage (`/usage`) | [Portfolio Risk](./portfolio-risk-exposure-dashboard.md) · [Alerts](./alerts.md) |
| **Deliver** | Zero-server GitHub Actions schedule, Electron desktop app, Telegram / Discord / Slack / Email / ntfy / Gotify / WeChat / Feishu notifications | [Notifications](./notifications.md) · [Bot Commands](./bot-command_EN.md) |

## 🚀 Quick Start

<a name="-configuration"></a>

| Method | Best For | Link |
|--------|----------|------|
| **Desktop App** | Native GUI without CLI setup | [Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [Setup Guide](./beginner-client-setup.md) |
| **GitHub Actions** | Zero-server daily scheduled reports (Recommended) | [4-Step Setup Below](#option-1-github-actions-recommended) |
| **Local CLI / WebUI** | Local CLI runs or self-hosted Web workspace | [Commands Below](#option-2-local--docker-deployment) |
| **Docker** | Always-on server deployment | [Deploy Guide](./DEPLOY_EN.md) |

### Option 1: GitHub Actions (Recommended)

> No server required. Configure **at least 1 AI model Secret** to run (`STOCK_LIST` defaults to `600519`; notifications and search sources are optional).

1. <a name="1-fork-this-repository"></a>**Fork this repository**: Click `Fork` in the upper-right corner.
2. <a name="2-configure-secrets"></a>**Add an AI model Secret**: Go to `Settings` → `Secrets and variables` → `Actions` → `New repository secret` and add any supported provider key (e.g. `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or an aggregator key; full list in [GitHub Actions Configuration](./full-guide_EN.md#github-actions-configuration)).
3. <a name="3-enable-actions"></a>**Enable Actions**: Open the `Actions` tab → click `I understand my workflows, go ahead and enable them`.
4. <a name="done"></a><a name="4-manual-test"></a>**Manual test**: Go to `Actions` → `每日股票分析` → `Run workflow`, then check pushed notifications or download the report artifact. Runs automatically every weekday at **18:00 Beijing Time** (enable force-run when testing on non-trading days).

### Option 2: Local / Docker Deployment

<a name="-web-ui"></a>

```bash
git clone --depth 1 https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis
python -m pip install -r requirements.txt
cp .env.example .env   # Fill in 1 AI model key and STOCK_LIST

python main.py               # Run one analysis
python main.py --serve-only  # Launch local WebUI (build apps/dsa-web first)
```

> For exact version requirements, WebUI build steps, Docker Compose, and full CLI flags, see [Local Deployment](./full-guide_EN.md#local-deployment) and the [Deployment Guide](./DEPLOY_EN.md).

### 📱 Sample Output

<a name="decision-dashboard"></a>
<a name="market-review"></a>

<details>
<summary>Click to expand sample outputs (Decision Dashboard &amp; Market Review)</summary>

```markdown
🎯 2026-02-08 Decision Dashboard
Analyzed 3 stocks | 🟢 Buy:0 🟡 Watch:2 🔴 Sell:1
🟡 000657: Watch | Score 65 | Bullish
🟡 600105: Watch | Score 48 | Range-bound
🔴 300260: Sell | Score 35 | Bearish
🚨 Risk Alerts: Main-force funds showed notable outflow. Chip concentration suggests short-term resistance.
✨ Positive Catalysts: AI-server supply-chain exposure and recent earnings growth support fundamentals.

🎯 2026-01-10 Market Review
📊 Major Indices: SSE Composite 3250.12 (🟢+0.85%) | SZSE Component 10521.36 (🟢+1.02%) | ChiNext 2156.78 (🟢+1.35%)
📈 Market Breadth: Up 3920 | Down 1349 | Limit up 155 | Limit down 3
```

</details>

### Tech Stack & Data Sources

| Type | Supported |
|------|-----------|
| **Application** | Python / FastAPI, React / Vite, Electron |
| **AI Models** | [Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis), [x6.ai](https://console.x6pro.io/register?code=zJ2qSdns), AIHubMix, Gemini, OpenAI-compatible providers, DeepSeek, Qwen, Claude, Ollama |
| **Market Data** | YFinance, Longbridge, AkShare, Tushare, [TickPlus](http://www.tickplus.org/register?reg=5433cf922395), Pytdx, Baostock (works out-of-the-box with free sources across US/HK/JP/KR/TW/CN, with optional token-based sources) |
| **News & Sentiment** | [SerpAPI](https://serpapi.com/github-daily-stock-analysis), Tavily, Brave, Anspire, Bocha, MiniMax, SearXNG; optional Stock Sentiment API (US) |

## 📞 Contact

<table>
  <tr>
    <td width="92" valign="top"><strong>Email</strong></td>
    <td valign="top">
      <a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a><br>
      Project consulting, deployment support, and feature extensions
    </td>
    <td align="center" rowspan="3" valign="middle" width="148">
      <a href="http://xhslink.com/m/tU520DWCKT" target="_blank"><img src="assets/xiaohongshu_tick.jpg" width="112" alt="Xiaohongshu QR code"></a><br>
      <sub>Follow on Xiaohongshu</sub>
    </td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>Xiaohongshu</strong></td>
    <td valign="top"><a href="http://xhslink.com/m/tU520DWCKT">Follow on Xiaohongshu</a></td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>Feedback</strong></td>
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">GitHub Issues</a> · <a href="https://github.com/ZhuLinsen/daily_stock_analysis/discussions">Discussions</a></td>
  </tr>
</table>

## 📄 License

[MIT License](../LICENSE) © 2026 ZhuLinsen

If you use or build on this project, attribution with a link back to this repository is appreciated.

## ⚠️ Disclaimer

This project is for informational and educational purposes only. AI-generated analysis is not investment advice. Stock market investing involves risk; do your own research and consult a licensed financial advisor when needed.
