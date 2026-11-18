<div align="center">

# 📈 AI Stock Analysis System (DSA)

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![arXiv](https://img.shields.io/badge/arXiv-2608.26990-b31b1b.svg)](https://arxiv.org/abs/2608.26990)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

<p align="center">
  <a href="https://trendshift.io/repositories/18527?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-18527" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/18527" alt="ZhuLinsen%2Fdaily_stock_analysis | Trendshift" width="250" height="55"/></a>&nbsp;<a href="https://hellogithub.com/repository/ZhuLinsen/daily_stock_analysis" target="_blank"><img src="https://api.hellogithub.com/v1/widgets/recommend.svg?rid=6daa16e405ce46ed97b4a57706aeb29f&claim_uid=pfiJMqhR9uvDGlT&theme=neutral" alt="Featured｜HelloGitHub" width="230" /></a>
</p>

> 🤖 Full-stack AI investment research workbench for **A-shares / HK / US / JP / KR / TW** stocks: multi-source market data aggregation, decision dashboards, strategy chat agent, post-outcome backtest verification, portfolio risk tracking, and multi-channel delivery

[**Product Preview**](#-product-preview) · [**Key Features**](#-key-features) · [**Quick Start**](#-quick-start) · [**Sample Output**](#-sample-output) · [**Documentation Index**](./INDEX_EN.md) · [**Full Guide**](./full-guide_EN.md)

**[Download Desktop App](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [5-Min GitHub Actions](#option-1-github-actions-recommended) · [Docker / Local WebUI](#option-2-local--docker-deployment)**

English | [简体中文](../README.md) | [繁體中文](README_CHT.md)

</div>

<details>
<summary><strong>💖 Sponsors: Modelflare · x6.ai · SerpAPI (Click to expand offers &amp; referral links)</strong></summary>
<table>
  <tr><td align="center"><a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis"><img src="assets/modelflare_banner_en.png" alt="Modelflare" width="720"></a><br>Thanks to <strong>Modelflare</strong> for sponsoring this project! Operated by US-based Havenbyte LLC, it offers full-strength, stable GPT, Claude, Gemini, Grok and 40+ image/video models at lower cost. Selected OpenAI groups offer <strong>65% / 75% / 85% daily cache-hit guarantees</strong>; a single <strong>US$20 top-up unlocks GPT at 0.015x</strong>, and <strong>US$50 unlocks Claude at 0.03x</strong>. <a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis">Register via this exclusive link</a></td></tr>
  <tr><td align="center"><a href="https://console.x6pro.io/register?code=zJ2qSdns"><img src="./assets/x6ai_banner.png" alt="x6.ai" width="720" height="187"></a><br>100+ models from $5/month. Claude 81% off, GPT 91% off, DeepSeek 42% off, plus 20% off your first top-up. <a href="https://console.x6pro.io/register?code=zJ2qSdns">Register</a></td></tr>
  <tr><td align="center"><a href="https://serpapi.com/github-daily-stock-analysis" target="_blank"><img src="assets/serpapi_banner_en.png" alt="Easily scrape real-time financial news data from search engines - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a></td></tr>
</table>
</details>

## 🖥️ Product Preview

<p align="center">
  <a href="assets/readme_workspace_tour_20260510.gif"><img src="assets/readme_workspace_preview.gif" alt="DSA Web workspace demo" width="640"></a><br>
  <sub>Click the GIF to view the full demo (analysis, screening, decision signals, portfolio risk, backtest, and agent chat)</sub>
</p>

> [!TIP]
> 🚀 **Ecosystem Projects**: [AlphaSift · Smart screening](https://github.com/ZhuLinsen/alphasift) | [AlphaEvo · Strategy backtesting & evolution](https://github.com/ZhuLinsen/alphaevo)

## ✨ Key Features

| Stage | Core Capabilities & Web Workbench Routes | Documentation |
|-------|----------------------------------------|---------------|
| **Discovery** | Multi-factor & natural-language stock screening (`/screening`), market hotspot radar, rule-based ETF dual-momentum rotation (`--etf-rotation`) | [Screening Engine](./screening-engine.md) · [ETF Rotation](./etf-rotation.md) |
| **Analysis** | Multi-market decision dashboard reports (`/`), 6-market index recap, multi-turn strategy chat agent with 15 built-in strategies (`/chat`) | [Full Guide](./full-guide_EN.md) · [Market Boundaries](./market-support.md) |
| **Verification** | Decision-signal outcome tracking pool (`/decision-signals`), multi-horizon historical backtesting (`/backtest`), and LLM token usage telemetry (`/usage`) | [DecisionSignal](./decision-signals.md) · [Backtesting](./full-guide_EN.md#backtest-feature) |
| **Tracking** | Portfolio risk & exposure dashboard with Futu sync (`/portfolio`), EventMonitor realtime alerts (`/alerts`), and Data Center diagnostics (`/data`) | [Portfolio Risk](./portfolio-risk-exposure-dashboard.md) · [Alerts](./alerts.md) · [Data Center](./data-center-diagnostics.md) |
| **Delivery & Integration** | Visual settings center (`/settings`), WeChat Work / Feishu / Telegram / Discord / Slack / Email delivery, shareable report cards, interactive Bots, REST API & Agent Skills | [Notifications](./notifications.md) · [Bot Commands](./bot-command_EN.md) · [OpenClaw Skill](./openclaw-skill-integration.md) |

> Built-in free sources (AkShare, Baostock, YFinance) run out of the box with zero data-source credentials. For steadier A-share/ETF/HK/US quotes and realtime financial news, configure [TickPlus (Recommended)](http://www.tickplus.org/register?reg=5433cf922395), Tushare, Longbridge, or [SerpAPI](https://serpapi.com/github-daily-stock-analysis) — see [Data Source Stability](./data-source-stability.md).

## 🚀 Quick Start

| Mode | Best For | Minimum Requirement | Entry |
|------|----------|---------------------|-------|
| **Desktop App** | Non-CLI individual investors | 1 AI API key | [Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [Beginner Setup](./beginner-client-setup.md) |
| **GitHub Actions** | Zero-server daily automation (Recommended) | **Just 1 AI Model Secret** | [4-step setup below](#option-1-github-actions-recommended) |
| **Docker / Local WebUI** | Self-hosting, portfolio & agent chat | Docker or Python 3.10+ | [Commands below](#option-2-local--docker-deployment) · [Deploy Guide](./DEPLOY_EN.md) |

### Option 1: GitHub Actions (Recommended)

> Deploy in 5 minutes at zero cost: **only 1 AI Model Secret is required** for your first run (`STOCK_LIST` falls back to `600519`, and notification secrets are optional — run status is printed in Actions Step Summary, with optional report preview via `STEP_SUMMARY_REPORT=true`).

1. **Fork this repository**: Click `Fork` in the upper-right corner (and leave a Star ⭐ if helpful).
2. **Add at least 1 AI Model Secret** (`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`):
   - **Recommended**: `MODELFLARE_KEY` ([Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis)) or `LLM_X6AI_API_KEY` ([x6.ai](https://console.x6pro.io/register?code=zJ2qSdns))
   - **Direct providers**: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (DeepSeek/Qwen compatible), or `AIHUBMIX_KEY`
   - **Optional enhancers**: `STOCK_LIST` (e.g. `600519,hk00700,AAPL,7203.T,005930.KS,2330.TW`), `SERPAPI_API_KEYS` (news), `TICKPLUS_API_KEY` (A-share/ETF quotes), and notification channels (`TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `FEISHU_WEBHOOK_URL`, `WECHAT_WEBHOOK_URL`, etc. — see the [Full Guide](./full-guide_EN.md)).
3. **Enable Workflows**: Open your fork's `Actions` tab -> click `I understand my workflows, go ahead and enable them`.
4. **Run a Test**: `Actions` -> `Daily Stock Analysis` -> `Run workflow`. Scheduled runs execute every weekday at **18:00 Beijing Time** (non-trading days are skipped by default).

### Option 2: Local / Docker Deployment

```bash
# 1. Shallow clone (faster, skips heavy git history)
git clone --depth 1 https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis

# 2. Install dependencies & launch WebUI (recommended: configure keys visually in Settings)
pip install -r requirements.txt
python main.py --webui-only
```

Open `http://127.0.0.1:8000` (if configuring via `.env`, copy `.env.example` to `.env` and run `python main.py --doctor`). Common CLI commands:

```bash
python main.py --doctor                      # Offline redacted diagnostics (--json supported)
python main.py --stocks 600519,hk00700,AAPL  # One-shot stock analysis
python main.py --market-review               # Market review only
python main.py --schedule                    # Local daily scheduler
python main.py --serve-only                  # FastAPI + WebUI server only
```

> Docker prebuilt images, `--etf-rotation`, and cloud WebUI setup are in [Full Guide](./full-guide_EN.md); desktop packaging is in [Desktop Packaging](./desktop-package.md); multi-model setup is in [LLM Config Guide](./LLM_CONFIG_GUIDE_EN.md).

## 📱 Sample Output

<details>
<summary>Click to preview text notification output (Decision Dashboard &amp; Market Review)</summary>

```markdown
🎯 2026-02-08 Decision Dashboard
Analyzed 3 stocks | 🟢 Buy:0 🟡 Watch:2 🔴 Sell:1
🟡 000657: Watch | Score 65 | Bullish
🚨 Risk Alerts: Main-force outflow noticed; chip concentration near resistance.
✨ Positive Catalysts: Strong earnings momentum & sector demand.

🎯 2026-01-10 Market Review
📊 Major Indices: SSE 3250.12 (🟢+0.85%) | SZSE 10521.36 (🟢+1.02%) | ChiNext 2156.78 (🟢+1.35%)
```

</details>

## 🛠️ Troubleshooting & Keeping Updated

- **Local diagnostics**: Run `python main.py --doctor` to verify config, LLM readiness, notifications, and storage permissions before filing an issue.
- **Syncing your fork**: Click `Sync fork` on GitHub regularly for data-source fixes; keep settings in Secrets/Variables rather than editing workflow YAML files.
- **60-day schedule pause**: GitHub automatically disables scheduled workflows in forks with no commits for 60 days — sync your fork or re-enable under `Actions` (see [FAQ](./FAQ_EN.md)).

## 📞 Contact

<table>
  <tr>
    <td width="92" valign="top"><strong>Email</strong></td>
    <td valign="top"><a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a> (Consulting, deployment support &amp; extensions)</td>
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
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">GitHub Issues</a> · <a href="./INDEX_EN.md">Documentation Index</a></td>
  </tr>
</table>

## 📄 License & ⚠️ Disclaimer

[MIT License](../LICENSE) © 2026 ZhuLinsen — Attribution is appreciated when building upon this project. This project is for informational and educational purposes only and does not constitute investment advice.
