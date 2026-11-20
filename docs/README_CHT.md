<div align="center">

<a name="股票智能分析系統"></a>

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

> 🤖 基於 AI 大模型的自選股分析系統，涵蓋 A 股、港股、美股、日股、韓股和台股，支援決策報告、策略問股、回測、持倉風險追蹤和多渠道推送。

[**產品預覽**](#-產品預覽) · [**功能特性**](#-功能特性) · [**快速開始**](#-快速開始) · [**推送效果**](#-推送效果) · [**文檔中心**](./INDEX.md) · [**完整指南**](./full-guide.md)

繁體中文 | [English](README_EN.md) | [简体中文](../README.md)

</div>

## 🚀 快速開始

<a name="-配置說明"></a>

[通知配置](./notifications.md) · [完整配置與部署指南](./full-guide.md)

| 上手方式 | 適合人群 | 所需前置 | 入口 |
|------|------|------|------|
| **桌面客戶端** | 不想折騰命令行的個人投資者 | 1 個 AI API Key | [Releases 下載](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [小白教程](./beginner-client-setup.md) |
| **GitHub Actions** | 零伺服器每日自動分析（推薦） | **僅 1 個 AI 模型 Secret** | [下方 4 步配置](#方式一github-actions推薦) |
| **本地命令行** | 產出首份報告或檢查行情擷取 | Git、Python | [3 分鐘快速上手（簡中）](./QUICKSTART.md#本地-3-步快速起步) |
| **Docker / 本地 WebUI** | 私有部署、持倉管理與 Agent 問股 | Docker 或 Git / Python / Node.js | [下方部署命令](#方式二客戶端配置教程--本地運行--docker-部署) · [部署指南](./DEPLOY.md) |

### 方式一：[GitHub Actions（推薦）](https://www.bilibili.com/video/BV11FEb66EXG/)

> 無需自備伺服器，AI 模型呼叫依所選渠道計費。首次執行**只需配置 1 個 AI 模型 Secret**，`STOCK_LIST` 預設為 `600519`，通知渠道可選。

1. <a name="1-fork-本倉庫"></a>**Fork 本倉庫**：點擊右上角 `Fork`。
2. <a name="2-配置-secrets"></a>前往 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`，擇一填寫 `MODELFLARE_KEY`、`AIHUBMIX_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY` 或官方 `OPENAI_API_KEY`。x6.ai 與其他相容服務請參閱 [模型配置表](./full-guide.md#ai-模型配置至少配置一个)。
3. <a name="3-啟用-actions"></a>**啟用 Actions**：進入 Fork 倉庫的 `Actions` 標籤 -> 點擊 `I understand my workflows, go ahead and enable them`。
4. <a name="完成"></a><a name="4-手動測試"></a>**手動測試與查看結果**：`Actions` -> `每日股票分析` -> `Run workflow`，執行完成後可在推送通知查看結果或下載 `analysis-reports-*` 產物。之後每個工作日 **18:00（北京時間）** 自動執行（非交易日跳過及斷點續傳規則見 [定時任務配置](./full-guide.md#定时任务配置)）。非交易日試跑時可在手動觸發畫面勾選強制執行。

依需要配置自選股、資訊來源、行情源和通知渠道，請參閱 [完整指南](./full-guide.md#github-actions-详细配置)。

### 方式二：[客戶端配置教程](https://www.bilibili.com/video/BV11FEb66Eyr/) / 本地運行 / Docker 部署

<a name="-web-介面"></a>

本地 WebUI 需要 Git、Python 3.10+、Node.js `^20.19.0 || ^22.12.0 || >=24.0.0 <27` 及 npm 10+。

「OpenAI 官方」預設透過 Chat Completions 使用 `gpt-6.1-sol`。請使用 Python 3.11+，並將下方的相依套件安裝指令換成 `python -m pip install -r requirements.txt "litellm>=1.98.1"`。使用 Python 3.10 時，在「設定」中將該預設的模型清單換成帳戶有權使用的 `gpt-5`，再測試連線。

```bash
git clone --depth 1 https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis
python -m pip install -r requirements.txt
(cd apps/dsa-web && npm ci && npm run build)
python main.py --serve-only
```

在瀏覽器開啟 `http://127.0.0.1:8000`，於「設定」填寫 AI Key 和自選股後開始分析。Docker 使用者請參閱 [部署指南](./DEPLOY.md)。

## ✨ 功能特性

| 階段 | 核心能力與 Web 工作台模組 | 專題文檔 |
|------|------|------|
| **發現** | 多因子與自然語言智能選股（`/screening`）、市場熱點雷達、規則化 ETF 雙動量輪動（`--etf-rotation`） | [選股引擎](./screening-engine.md) · [ETF 輪動](./etf-rotation.md) |
| **分析** | 6 市場「決策儀表盤」報告（`/`）、大盤覆盤、15 種內建策略的多輪 Agent 策略問股（`/chat`） | [完整指南](./full-guide.md) · [市場邊界](./market-support.md) |
| **驗證** | 決策信號池（`/decision-signals`）、歷史勝率與方向回測（`/backtest`） | [決策信號](./decision-signals.md) · [數據中心](./data-center-diagnostics.md) |
| **跟蹤** | 持倉帳本與風險暴露看板（`/portfolio`，支援 CSV 匯入；CLI 支援唯讀富途持倉選股 `--portfolio futu`）、即時異動告警（`/alerts`）、Token 統計（`/usage`） | [組合風控](./portfolio-risk-exposure-dashboard.md) · [告警中心](./alerts.md) |
| **觸達** | GitHub Actions 零伺服器定時任務、Electron 桌面端、企業微信 / 飛書 / Telegram / Discord / Slack / 郵件推送 | [通知配置](./notifications.md) · [Bot 接入](./bot-command.md) |

<a name="-agent-策略問股"></a>

在 Web 或桌面工作台使用 [策略問股](./full-guide.md#本地-webui-管理界面)。

### 🖥️ 產品預覽

<p align="center">
  <a href="assets/readme_workspace_tour_20260510.gif"><img src="assets/readme_workspace_preview.gif" alt="DSA Web 工作台演示" width="640"></a><br>
  <sub>點擊動圖查看完整工作台演示（涵蓋個股分析、智能選股、決策信號、持倉風控、回測與 Agent 問股）</sub>
</p>

> [!TIP]
> 🚀 **作者配套開源專案**：[AlphaSift · 智能選股](https://github.com/ZhuLinsen/alphasift) ｜ [AlphaEvo · 策略回測與進化](https://github.com/ZhuLinsen/alphaevo)

### 📱 推送效果

<a name="決策儀表盤"></a>
<a name="大盤復盤"></a>

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
- 主力資金大幅淨賣出，需警惕短期拋壓。籌碼偏分散，拉升阻力較大。
✨ 利好催化:
- 受益於 AI 伺服器產業鏈，業績同比高增長提供基本面支撐。

🎯 2026-01-10 大盤覆盤
📊 主要指數: 上證指數 3250.12 (🟢+0.85%) | 深證成指 10521.36 (🟢+1.02%) | 創業板指 2156.78 (🟢+1.35%)
📈 市場概況: 上漲 3920 | 下跌 1349 | 漲停 155 | 跌停 3
```

</details>

### 技術棧與數據來源

| 類型 | 支援 |
|------|------|
| **應用** | Python / FastAPI, React / Vite, Electron |
| **AI 模型** | [Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis)、[x6.ai](https://console.x6pro.io/register?code=zJ2qSdns)、AIHubMix、Gemini、OpenAI 兼容、DeepSeek、通義千問、Claude、Ollama 本地模型等 |
| **行情數據** | [TickPlus（推薦）](http://www.tickplus.org/register?reg=5433cf922395)、AkShare、Tushare、Pytdx、Baostock、YFinance、Longbridge（內建免費源零配置可跑，批量/穩定建議配合 Token 源） |
| **新聞與輿情** | [SerpAPI](https://serpapi.com/github-daily-stock-analysis)、Anspire、Tavily、Bocha、Brave、MiniMax、SearXNG。美股可選 Stock Sentiment API（Reddit / X / Polymarket） |

**[3 分鐘快速上手（簡中）](./QUICKSTART.md) · [下載桌面客戶端](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [GitHub Actions](#方式一github-actions推薦) · [Docker / 本地 WebUI](#方式二客戶端配置教程--本地運行--docker-部署)**

<details open>
<summary><strong>💖 贊助商 (Sponsors)</strong></summary>
<table>
  <tr><td align="center"><a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis"><img src="assets/modelflare_banner_cht.png" alt="Modelflare" width="720"></a><br>感謝 <strong>Modelflare</strong> 贊助本項目！由美國 Havenbyte LLC 營運，滿血穩定不摻水，低成本接入 GPT、Claude、Gemini、Grok 及 40+ 圖片/影片模型。指定 OpenAI 分組提供 <strong>65% / 75% / 85% 每日快取命中率保障</strong>；單筆儲值 <strong>US$20 解鎖 GPT 0.015x</strong>，<strong>US$50 解鎖 Claude 0.03x</strong>。<a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis">專屬連結註冊</a></td></tr>
  <tr><td align="center"><a href="https://console.x6pro.io/register?code=zJ2qSdns"><img src="./assets/x6ai_banner.png" alt="x6.ai" width="720" height="187"></a><br>100+ 模型 $5 包月，Claude 1.9 折、GPT 0.9 折、DeepSeek 5.8 折，首充立減 20%。<a href="https://console.x6pro.io/register?code=zJ2qSdns">專屬連結註冊</a></td></tr>
  <tr><td align="center"><a href="https://serpapi.com/github-daily-stock-analysis" target="_blank"><img src="assets/serpapi_banner_zh.png" alt="輕鬆抓取搜尋引擎上的即時金融新聞數據 - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a></td></tr>
</table>
</details>

## 📬 聯繫與合作

<table>
  <tr>
    <td width="92" valign="top"><strong>合作郵箱</strong></td>
    <td valign="top">
      <a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a><br>
      項目諮詢、部署支援與功能擴展
    </td>
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
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">提交 Issue</a></td>
  </tr>
</table>

## 📄 License

[MIT License](../LICENSE) © 2026 ZhuLinsen

如果你在項目中使用或基於本項目進行二次開發，非常歡迎在 README 或文檔中註明來源並附上本倉庫鏈接。

## ⚠️ 免責聲明

本項目僅供學習和研究使用，不構成任何投資建議。股市有風險，投資需謹慎。作者不對使用本項目產生的任何損失負責。
