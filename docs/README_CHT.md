<div align="center">

# 股票智能分析系統

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

<p>
  <a href="https://trendshift.io/repositories/18527" target="_blank"><img src="https://trendshift.io/api/badge/repositories/18527" alt="ZhuLinsen%2Fdaily_stock_analysis | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
  <a href="https://hellogithub.com/repository/ZhuLinsen/daily_stock_analysis" target="_blank"><img src="https://api.hellogithub.com/v1/widgets/recommend.svg?rid=6daa16e405ce46ed97b4a57706aeb29f&claim_uid=pfiJMqhR9uvDGlT&theme=neutral" alt="Featured｜HelloGitHub" style="width: 250px; height: 54px;" width="250" height="54" /></a>
</p>

**基於 AI 大模型的 A股/港股/美股自選股智能分析系統**

每日自動分析自選股 -> 生成決策儀表盤 -> 推送到 Telegram / Discord / Slack / 郵件 / 企業微信 / 飛書。

[**功能特性**](#-功能特性) · [**快速開始**](#-快速開始) · [**推送效果**](#-推送效果) · [**完整指南**](./full-guide.md) · [**常見問題**](./FAQ.md) · [**更新日誌**](./CHANGELOG.md)

繁體中文 | [English](README_EN.md) | [简体中文](../README.md)

</div>

## 💖 贊助商 (Sponsors)

<div align="center">
  <a href="https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis" target="_blank">
    <img src="../sources/serpapi_banner_zh.png" alt="輕鬆抓取搜尋引擎上的即時金融新聞數據 - SerpApi" height="160">
  </a>
</div>
<br>

## ✨ 功能特性

| 模組 | 功能 | 說明 |
|------|------|------|
| AI | 決策儀表盤 | 一句話核心結論 + 評分 + 買賣點位 + 風險警報 + 操作檢查清單 |
| 分析 | 多維度分析 | 技術面、即時行情、籌碼分布、新聞輿情、公告、資金流與基本面聚合 |
| 市場 | 全球市場 | 支援 A股、港股、美股、美股指數及常見 ETF |
| 策略 | 市場策略系統 | 內建 A股復盤、美股 Regime、均線、纏論、波浪、情緒週期等策略能力 |
| 復盤 | 大盤復盤 | 每日市場概覽、指數表現、漲跌統計與板塊強弱 |
| Web | 雙主題工作台 | 支援手動分析、配置管理、任務進度、歷史報告、回測、持倉管理 |
| 匯入 | 智能匯入與補全 | 支援圖片、CSV/Excel、剪貼簿匯入，自選股輸入支援代碼/名稱/拼音/別名補全 |
| 歷史 | 報告管理 | 支援歷史報告查看、完整 Markdown 報告、重新分析與批量管理 |
| 回測 | AI 回測驗證 | 對歷史分析進行事後驗證，查看方向準確率和模擬收益 |
| Agent 問股 | 策略對話 | 多輪策略問答，支援均線金叉/纏論/波浪等 11 種內建策略，Web/Bot/API 全鏈路 |
| 推送 | 多渠道通知 | 支援企業微信、飛書、Telegram、Discord、Slack、郵件等主流渠道 |
| 自動化 | 定時運行 | 支援 GitHub Actions、Docker、本地定時任務和 FastAPI 服務模式 |

> 功能細節、欄位契約、基本面 P0 超時語義、交易紀律、數據源優先級、Web/API 行為請看 [完整配置與部署指南](./full-guide.md)。

### 技術棧與數據來源

| 類型 | 支援 |
|------|------|
| AI 模型 | [AIHubMix](https://aihubmix.com/?aff=CfMq)、Gemini、OpenAI 兼容、DeepSeek、通義千問、Claude、Ollama 本地模型等 |
| 行情數據 | [TickFlow](https://tickflow.org/auth/register?ref=WDSGSPS5XC)、AkShare、Tushare、Pytdx、Baostock、YFinance、Longbridge |
| 新聞搜尋 | [Anspire](https://aisearch.anspire.cn/)、[SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis)、[Tavily](https://tavily.com/)、[Bocha](https://open.bocha.cn/)、[Brave](https://brave.com/search/api/)、[MiniMax](https://platform.minimaxi.com/)、SearXNG |
| 社交輿情 | [Stock Sentiment API](https://api.adanos.org/docs)（Reddit / X / Polymarket，僅美股，可選） |

> 完整規則見 [數據源配置](./full-guide.md#数据源配置)。

## 🚀 快速開始

### 方式一：GitHub Actions（推薦）

> 5 分鐘完成部署，零成本，無需伺服器。

#### 1. Fork 本倉庫

點擊右上角 `Fork` 按鈕（順便點個 Star 支援一下）。

#### 2. 配置 Secrets

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

**AI 模型配置（至少配置一個）**

預設先選一個模型服務商並填寫 API Key；需要多模型、圖片識別、本地模型或高級路由時，再參考 [LLM 配置指南](./LLM_CONFIG_GUIDE.md)。

> 推薦 [AIHubMix](https://aihubmix.com/?aff=CfMq)：一個 Key 即可使用 Gemini、GPT、Claude、DeepSeek 等全球主流模型，無需科學上網，含免費模型，付費模型高穩定性無限併發。本項目可享 10% 充值優惠。

| Secret 名稱 | 說明 | 必填 |
|-------------|------|:----:|
| `AIHUBMIX_KEY` | AIHubMix API Key，一 Key 切換使用全系模型 | 可選 |
| `GEMINI_API_KEY` | Google Gemini API Key | 可選 |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | 可選 |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（支援 DeepSeek、通義千問等） | 可選 |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | 使用 OpenAI 兼容服務時填寫 | 可選 |

> Ollama 更適合本地 / Docker 部署，GitHub Actions 推薦使用雲端 API。

**通知渠道配置（至少配置一個）**

| Secret 名稱 | 說明 |
|-------------|------|
| `WECHAT_WEBHOOK_URL` | 企業微信機器人 |
| `FEISHU_WEBHOOK_URL` | 飛書機器人 |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram |
| `DISCORD_WEBHOOK_URL` | Discord Webhook |
| `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | Slack Bot |
| `EMAIL_SENDER` + `EMAIL_PASSWORD` | 郵件推送 |

更多渠道、簽名校驗、分組郵件、Markdown 轉圖片等配置見 [通知渠道詳細配置](./full-guide.md#通知渠道详细配置)。

**自選股配置（必填）**

| Secret 名稱 | 說明 | 必填 |
|-------------|------|:----:|
| `STOCK_LIST` | 自選股代碼，如 `600519,hk00700,AAPL,TSLA` | ✅ |

**新聞源配置（推薦）**

新聞源會顯著影響輿情、公告、事件和催化因素品質，建議至少配置一個搜尋服務。

| Secret 名稱 | 說明 | 必填 |
|-------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/)：中文內容特別優化，可增強 A 股分析效果 | 推薦 |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis)：搜尋引擎結果補強，適合即時金融新聞 | 推薦 |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/)：通用新聞搜尋 API | 可選 |
| `BOCHA_API_KEYS` | [博查搜尋](https://open.bocha.cn/)：中文搜尋優化，支援 AI 摘要 | 可選 |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/)：隱私優先，美股資訊補強 | 可選 |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimaxi.com/)：結構化搜尋結果 | 可選 |
| `SEARXNG_BASE_URLS` | SearXNG 自建實例：無配額兜底，適合私有部署 | 可選 |

更多搜尋源、社交輿情和降級規則見 [搜尋服務配置](./full-guide.md#搜索服务配置)。

#### 3. 啟用 Actions

`Actions` 標籤 -> `I understand my workflows, go ahead and enable them`

#### 4. 手動測試

`Actions` -> `每日股票分析` -> `Run workflow` -> `Run workflow`

#### 完成

預設每個工作日 18:00（北京時間）自動執行，也可手動觸發。預設非交易日（含 A/H/US 節假日）不執行；強制運行、交易日檢查、斷點續傳等規則見 [完整指南](./full-guide.md#定时任务配置)。

### 方式二：本地運行 / Docker 部署

```bash
# 克隆項目
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis

# 安裝依賴
pip install -r requirements.txt

# 配置環境變數
cp .env.example .env && vim .env

# 運行分析
python main.py
```

常用命令：

```bash
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review
python main.py --schedule
python main.py --serve-only
```

> Docker 部署、定時任務、雲端伺服器訪問請參考 [完整指南](./full-guide.md)；桌面客戶端打包請參考 [桌面端打包說明](./desktop-package.md)。

## 📱 推送效果

### 決策儀表盤

```markdown
🎯 2026-02-08 決策儀表盤
共分析3隻股票 | 🟢買入:0 🟡觀望:2 🔴賣出:1

📊 分析結果摘要
🟡 中鎢高新(000657): 觀望 | 評分 65 | 看多
🟡 永鼎股份(600105): 觀望 | 評分 48 | 震盪
🔴 新萊應材(300260): 賣出 | 評分 35 | 看空

🚨 風險警報:
風險點1：主力資金出現明顯流出，需警惕短期拋壓。
風險點2：籌碼集中度偏高，拉升阻力可能較大。

✨ 利好催化:
利好1：公司被市場定位為 AI 供應鏈核心標的。
利好2：近期業績增長為股價提供基本面支撐。
```

### 大盤復盤

```markdown
🎯 2026-01-10 大盤復盤

📊 主要指數
- 上證指數: 3250.12 (+0.85%)
- 深證成指: 10521.36 (+1.02%)
- 創業板指: 2156.78 (+1.35%)

📈 市場概況
上漲: 3920 | 下跌: 1349 | 漲停: 155 | 跌停: 3
```

## ⚙️ 配置說明

完整環境變數、模型渠道、通知渠道、數據源優先級、交易紀律、基本面 P0 語義和部署說明請參考 [完整配置指南](./full-guide.md)。

## 🖥️ Web 介面

![FastAPI Web UI](../sources/fastapi_server.png)

Web 工作台提供配置管理、任務監控、手動分析、歷史報告、回測、持倉管理、智能匯入和淺色 / 深色主題。啟動方式：

```bash
python main.py --webui
python main.py --webui-only
```

訪問 `http://127.0.0.1:8000` 即可使用。認證、智能匯入、搜尋補全、歷史報告複製、雲端伺服器訪問等細節見 [本地 WebUI 管理介面](./full-guide.md#本地-webui-管理界面)。

## 🤖 Agent 策略問股

配置任意可用 AI API Key 後，Web `/chat` 頁面即可使用策略問股；如需顯式關閉可設定 `AGENT_MODE=false`。

- 支援均線金叉、纏論、波浪理論、多頭趨勢等內建策略
- 支援即時行情、K 線、技術指標、新聞和風險資訊調用
- 支援多輪追問、會話匯出、發送到通知渠道和後台執行
- 支援自訂策略文件與多 Agent 編排（實驗性）

> Agent 具體參數、`skill` 命名兼容、多 Agent 模式和預算護欄見 [完整指南](./full-guide.md#本地-webui-管理界面) 與 [LLM 配置指南](./LLM_CONFIG_GUIDE.md)。

## 🗺️ Roadmap

查看已支援的功能和未來規劃：[更新日誌](./CHANGELOG.md)

> 有建議？歡迎 [提交 Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)

> UI 正在持續調整與升級，部分頁面在過渡階段可能仍存在樣式、交互或兼容性問題。歡迎通過 Issue 或 Pull Request 一起完善。

---

## ☕ 支持項目

| 支付寶 (Alipay) | 微信支付 (WeChat) | 小紅書 |
| :---: | :---: | :---: |
| <img src="../sources/alipay.jpg" width="200" alt="Alipay"> | <img src="../sources/wechatpay.jpg" width="200" alt="WeChat Pay"> | <img src="../sources/xiaohongshu.png" width="200" alt="小紅書"> |

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request。提交前建議按改動面執行檢查：

```bash
# Python / 後端
./scripts/ci_gate.sh

# Web
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

詳見 [貢獻指南](CONTRIBUTING.md)。

## 📄 License

[MIT License](../LICENSE) © 2026 ZhuLinsen

如果你在項目中使用或基於本項目進行二次開發，非常歡迎在 README 或文檔中註明來源並附上本倉庫鏈接。

## 📬 聯繫與合作

- GitHub Issues：[提交 Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
- 合作郵箱：zhuls345@gmail.com

## ⭐ Star History

**如果覺得有用，請給個 ⭐ Star 支持一下！**

<a href="https://star-history.com/#ZhuLinsen/daily_stock_analysis&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date" />
 </picture>
</a>

## ⚠️ 免責聲明

本項目僅供學習和研究使用，不構成任何投資建議。股市有風險，投資需謹慎。作者不對使用本項目產生的任何損失負責。
