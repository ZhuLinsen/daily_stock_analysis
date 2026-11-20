<div align="center">

# 📈 股票智能分析系統 (DSA)

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

> 🤖 覆蓋 **A股 / 港股 / 美股 / 日股 / 韓股 / 台股** 的全鏈路 AI 投研工作台：集多源行情聚合、技術/情報分析、Agent 策略問股、決策信號回測驗證、持倉風控與多渠道推送於一體

[**產品預覽**](#-產品預覽) · [**功能特性**](#-功能特性) · [**快速開始**](#-快速開始) · [**推送效果**](#-推送效果) · [**文檔中心**](./INDEX.md) · [**完整指南**](./full-guide.md)

**[下載桌面客戶端](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [5 分鐘 GitHub Actions](#方式一github-actions推薦) · [Docker / 本地 WebUI](#方式二客戶端配置教程--本地運行--docker-部署)**

繁體中文 | [English](README_EN.md) | [简体中文](../README.md)

</div>

<details open>
<summary><strong>💖 贊助商 (Sponsors)</strong></summary>
<table>
  <tr><td align="center"><a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis"><img src="assets/modelflare_banner_cht.png" alt="Modelflare" width="720"></a><br>感謝 <strong>Modelflare</strong> 贊助本項目！由美國 Havenbyte LLC 營運，滿血穩定不摻水，低成本接入 GPT、Claude、Gemini、Grok 及 40+ 圖片/影片模型。指定 OpenAI 分組提供 <strong>65% / 75% / 85% 每日快取命中率保障</strong>；單筆儲值 <strong>US$20 解鎖 GPT 0.015x</strong>，<strong>US$50 解鎖 Claude 0.03x</strong>。<a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis">專屬連結註冊</a></td></tr>
  <tr><td align="center"><a href="https://console.x6pro.io/register?code=zJ2qSdns"><img src="./assets/x6ai_banner.png" alt="x6.ai" width="720" height="187"></a><br>100+ 模型 $5 包月，Claude 1.9 折、GPT 0.9 折、DeepSeek 5.8 折，首充立減 20%。<a href="https://console.x6pro.io/register?code=zJ2qSdns">專屬連結註冊</a></td></tr>
  <tr><td align="center"><a href="https://serpapi.com/github-daily-stock-analysis" target="_blank"><img src="assets/serpapi_banner_zh.png" alt="輕鬆抓取搜尋引擎上的即時金融新聞數據 - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a></td></tr>
</table>
</details>

## 💻 產品預覽

<p align="center">
  <a href="assets/readme_workspace_tour_20260510.gif"><img src="assets/readme_workspace_preview.gif" alt="DSA Web 工作台演示" width="640"></a><br>
  <sub>點擊動圖查看完整工作台演示（涵蓋個股分析、智能選股、決策信號、持倉風控、回測與 Agent 問股）</sub>
</p>

> [!TIP]
> 🚀 **作者配套開源專案**：[AlphaSift · 智能選股](https://github.com/ZhuLinsen/alphasift) ｜ [AlphaEvo · 策略回測與進化](https://github.com/ZhuLinsen/alphaevo)

## ✨ 功能特性

| 階段 | 核心能力與 Web 工作台模組 | 專題文檔 |
|------|------|------|
| **發現** | 多因子與自然語言智能選股（`/screening`）、市場熱點雷達、規則化 ETF 雙動量輪動（`--etf-rotation`） | [選股引擎](./screening-engine.md) · [ETF 輪動](./etf-rotation.md) |
| **分析** | 6 市場「決策儀表盤」報告（`/`）、大盤覆盤、15 種內建策略的多輪 Agent 策略問股（`/chat`） | [完整指南](./full-guide.md) · [市場邊界](./market-support.md) |
| **驗證** | 決策信號池（`/decision-signals`）、歷史勝率與方向回測（`/backtest`） | [決策信號](./decision-signals.md) · [數據中心](./data-center-diagnostics.md) |
| **跟蹤** | 持倉帳本與風險暴露看板（`/portfolio`、富途同步）、即時異動告警（`/alerts`）、Token 統計（`/usage`） | [組合風控](./portfolio-risk-exposure-dashboard.md) · [告警中心](./alerts.md) |
| **觸達** | GitHub Actions 零伺服器定時任務、Electron 桌面端、企業微信 / 飛書 / Telegram / Discord / Slack / 郵件推送 | [通知配置](./notifications.md) · [Bot 接入](./bot-command.md) |

### 技術棧與數據來源

| 類型 | 支援 |
|------|------|
| **AI 模型** | [Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis)、[x6.ai](https://console.x6pro.io/register?code=zJ2qSdns)、AIHubMix、Gemini、OpenAI 兼容、DeepSeek、通義千問、Claude、Ollama 本地模型等 |
| **行情數據** | [TickPlus（推薦）](http://www.tickplus.org/register?reg=5433cf922395)、AkShare、Tushare、Pytdx、Baostock、YFinance、Longbridge（內建免費源零配置可跑，批量/穩定建議配合 Token 源） |
| **新聞與輿情** | [SerpAPI](https://serpapi.com/github-daily-stock-analysis)、Anspire、Tavily、Bocha、Brave、MiniMax、SearXNG；美股可選 Stock Sentiment API（Reddit / X / Polymarket） |

## 🚀 快速開始

| 上手方式 | 適合人群 | 所需前置 | 入口 |
|------|------|------|------|
| **桌面客戶端** | 不想折騰命令行的個人投資者 | 1 個 AI API Key | [Releases 下載](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [小白教程](./beginner-client-setup.md) |
| **GitHub Actions** | 零伺服器每日自動分析（推薦） | **僅 1 個 AI 模型 Secret** | [下方 4 步配置](#方式一github-actions推薦) |
| **Docker / 本地 WebUI** | 私有部署、持倉管理與 Agent 問股 | Docker 或 Python 3.10+ | [下方部署命令](#方式二客戶端配置教程--本地運行--docker-部署) · [部署指南](./DEPLOY.md) |

### 方式一：[GitHub Actions（推薦）](https://www.bilibili.com/video/BV11FEb66EXG/)

> 5 分鐘部署，無需自備伺服器（AI 模型調用費用由你選擇的 API 渠道計費）；首次跑通**只需配置 1 個 AI 模型 Secret**，`STOCK_LIST` 預設兜底 `600519`，通知渠道可選。

1. **Fork 本倉庫**：點擊右上角 `Fork`（順便點個 Star ⭐ 支援一下）。
2. **配置至少 1 個 AI 模型 Secret**（`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`）：
   - **單 Secret 推薦**：`MODELFLARE_KEY`（[Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis)，自動補齊預設位址與模型）、`AIHUBMIX_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY` 或官方 `OPENAI_API_KEY`
   - **多變數渠道 / 相容接入**：使用 [x6.ai](https://console.x6pro.io/register?code=zJ2qSdns) 需配置 `LLM_CHANNELS=x6ai`、`LLM_X6AI_BASE_URL`、`LLM_X6AI_API_KEY` 與 `LLM_X6AI_MODELS`（見 [x6.ai 渠道範例](./llm-providers.md#x6ai-聚合平台)）；使用 OpenAI 相容 DeepSeek/通義千問需同時配置 `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `OPENAI_MODEL`
   - **可選增強**：`STOCK_LIST`（如 `600519,hk00700,AAPL,7203.T,005930.KS,2330.TW`，規則見 [指數自選股配置](./full-guide.md#指数自选股配置)）、`SERPAPI_API_KEYS`（新聞補強）、`TICKPLUS_API_KEY` / `TUSHARE_TOKEN` / `LONGBRIDGE_OAUTH_CLIENT_ID`（穩定行情）、通知渠道（`WECHAT_WEBHOOK_URL` / `FEISHU_WEBHOOK_URL` / `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID` / `DISCORD_WEBHOOK_URL` / `SLACK_BOT_TOKEN`+`SLACK_CHANNEL_ID` / `EMAIL_SENDER`+`EMAIL_PASSWORD`，詳見 [完整指南](./full-guide.md)）。
3. **啟用 Actions**：進入 Fork 倉庫的 `Actions` 標籤 -> 點擊 `I understand my workflows, go ahead and enable them`。
4. **手動測試與查看結果**：`Actions` -> `每日股票分析` -> `Run workflow`，執行完成後可在推送通知查看結果或下載 `analysis-reports-*` Artifact；之後每個工作日 **18:00（北京時間）** 自動執行（非交易日跳過及斷點續傳規則見 [定時任務配置](./full-guide.md#定时任务配置)）。

### 方式二：[客戶端配置教程](https://www.bilibili.com/video/BV11FEb66Eyr/) / 本地運行 / Docker 部署

```bash
# 1. 淺克隆項目（跳過歷史提交，下載更快）
git clone --depth 1 https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis

# 2. 安裝依賴並啟動 Web 工作台（推薦直接在網頁設定頁配置模型、自選股與通知）
pip install -r requirements.txt
python main.py --webui-only
```

啟動後訪問 `http://127.0.0.1:8000`（支援圖片/CSV/剪貼簿智能匯入與 `/chat` Agent 問股）。如使用 `.env` 命令行模式：

```bash
cp .env.example .env && vim .env
python main.py                              # 全量分析（個股 + 大盤覆盤）
python main.py --stocks 600519,hk00700,AAPL # 一次性分析指定標的
python main.py --market-review              # 僅運行大盤覆盤
python main.py --schedule                   # 本地定時排程
python main.py --serve-only                 # 僅啟動 FastAPI + WebUI 服務
```

> **作為只讀金融 MCP Server 接入 Claude Code / Cursor**：`claude mcp add dsa -- python -m src.mcp_server`（6 市場行情 / K 線 / 基本面 / 新聞 / 歷史報告只讀工具，加 `--include-macro` 可額外暴露宏觀只讀工具）。Docker 部署、雲端伺服器訪問與 `--etf-rotation` 輪動請看 [完整配置與部署指南](./full-guide.md)；桌面客戶端打包請看 [桌面端打包說明](./desktop-package.md)；多模型路由與 Agent 參數請看 [LLM 配置指南](./LLM_CONFIG_GUIDE.md)。

## 📱 推送效果

<details>
<summary>點擊展開推送示例（決策儀表盤 &amp; 大盤覆盤）</summary>

```markdown
🎯 2026-02-08 決策儀表盤
共分析3隻股票 | 🟢買入:0 🟡觀望:2 🔴賣出:1

📊 分析結果摘要
🟡 中鎢高新(000657): 觀望 | 評分 65 | 看多
🟡 永鼎股份(600105): 觀望 | 評分 48 | 震盪
🔴 新萊應材(300260): 賣出 | 評分 35 | 看空

🚨 風險警報:
- 主力資金大幅淨賣出，需警惕短期拋壓；籌碼偏分散，拉升阻力較大。
✨ 利好催化:
- 受益於 AI 伺服器產業鏈，業績同比高增長提供基本面支撐。

🎯 2026-01-10 大盤覆盤
📊 主要指數: 上證指數 3250.12 (🟢+0.85%) | 深證成指 10521.36 (🟢+1.02%) | 創業板指 2156.78 (🟢+1.35%)
📈 市場概況: 上漲 3920 | 下跌 1349 | 漲停 155 | 跌停 3
```

</details>

## 🛠️ 排障與保持更新

- **Fork 保持更新**：定期在 GitHub 點擊 `Sync fork` 同步數據源與模型修復；通過 Secrets/Variables 配參數，避免改動 workflow 引發衝突。
- **60 天定時停用**：GitHub 會在倉庫 **60 天無倉庫活動** 後自動暫停 `schedule` 定時任務，可在 `Actions` 頁重新啟用或定期 `Sync fork`，詳見 [FAQ](./FAQ.md)。

## 📬 聯繫與合作

<table>
  <tr>
    <td width="92" valign="top"><strong>合作郵箱</strong></td>
    <td valign="top"><a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a>（項目諮詢、部署支援與功能擴展）</td>
    <td align="center" rowspan="3" valign="middle" width="148">
      <a href="http://xhslink.com/m/tU520DWCKT" target="_blank"><img src="assets/xiaohongshu_tick.jpg" width="112" alt="小紅書二維碼"></a><br>
      <sub>掃碼關注小紅書</sub>
    </td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>小紅書</strong></td>
    <td valign="top"><a href="http://xhslink.com/m/tU520DWCKT">歡迎關注小紅書</a></td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>問題反饋</strong></td>
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">提交 Issue</a> · <a href="./INDEX.md">文檔中心</a></td>
  </tr>
</table>

## 📄 License & ⚠️ 免責聲明

[MIT License](../LICENSE) © 2026 ZhuLinsen — 歡迎在二次開發或引用時註明本倉庫來源。本項目僅供學習和研究使用，不構成任何投資建議；股市有風險，投資需謹慎。
