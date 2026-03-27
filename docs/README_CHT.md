<div align="center">

# 股票智能分析系統

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/)

<p>
  <a href="https://trendshift.io/repositories/18527" target="_blank"><img src="https://trendshift.io/api/badge/repositories/18527" alt="ZhuLinsen%2Fdaily_stock_analysis | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
  <a href="https://hellogithub.com/repository/ZhuLinsen/daily_stock_analysis" target="_blank"><img src="https://api.hellogithub.com/v1/widgets/recommend.svg?rid=6daa16e405ce46ed97b4a57706aeb29f&claim_uid=pfiJMqhR9uvDGlT&theme=neutral" alt="Featured｜HelloGitHub" style="width: 250px; height: 54px;" width="250" height="54" /></a>
</p>

**基於 AI 大模型的 A股/港股/美股 智能分析系統**

自動分析自選股 → 生成決策儀表盤 → 多渠道推送（Telegram/Discord/Slack/郵件/企業微信/飛書）

**零成本部署** · GitHub Actions 免費運行 · 無需伺服器

[**功能特性**](#-功能特性) · [**快速開始**](#-快速開始) · [**推送效果**](#-推送效果) · [**完整指南**](full-guide.md) · [**常見問題**](FAQ.md) · [**更新日誌**](CHANGELOG.md)

 繁體中文 | [English](../README_EN.md) | [简体中文](../README.md)

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
| AI | 決策儀表盤 | 一句話核心結論 + 精確買賣點位 + 操作檢查清單 |
| 分析 | 多維度分析 | 技術面 + 籌碼分布 + 輿情情報 + 實時行情 |
| 市場 | 全球市場 | 支援 A股、港股、美股 |
| 補全 | 智慧補全 (MVP) | **[測試階段]** 首頁搜尋框支援代碼 / 名稱 / 拼音 / 別名聯想；本地索引已覆蓋 A股、港股、美股，並可透過 Tushare 或 AkShare 重新生成 |
| 復盤 | 大盤復盤 | 每日市場概覽、板塊漲跌、北向資金 |
| 回測 | AI 回測驗證 | 自動評估歷史分析準確率，方向勝率、止盈止損命中率 |
| **Agent 問股** | **策略對話** | **多輪策略問答，支援 11 種內建策略（Web/Bot/API）** |
| 推送 | 多渠道通知 | Telegram、Discord、Slack、郵件、企業微信、飛書等 |
| 自動化 | 定時運行 | GitHub Actions 定時執行，無需伺服器 |

### 技術棧與數據來源

| 類型 | 支援 |
|------|------|
| AI 模型 | Gemini（免費）、OpenAI 兼容、DeepSeek、通義千問、Claude、Ollama |
| 行情數據 | AkShare、Tushare、Pytdx、Baostock、YFinance |
| 新聞搜索 | Tavily、SerpAPI、Bocha、Brave、MiniMax |

### 內建交易紀律

| 規則 | 說明 |
|------|------|
| 嚴禁追高 | 乖離率 > 5% 自動提示風險 |
| 趨勢交易 | MA5 > MA10 > MA20 多頭排列 |
| 精確點位 | 買入價、止損價、目標價 |
| 檢查清單 | 每項條件以「符合 / 注意 / 不符合」標記 |

## 🚀 快速開始

### 方式一：GitHub Actions（推薦）

**無需服務器，每天自動運行！**

#### 1. Fork 本倉庫

點擊右上角 `Fork` 按鈕（順便點個 Star 支持一下）

#### 2. 配置 Secrets

進入你 Fork 的倉庫 → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

**AI 模型配置（二選一）**

| Secret 名稱 | 說明 | 必填 |
|------------|------|:----:|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) 獲取免費 Key | ✅* |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（支持 DeepSeek、通義千問等） | 可選 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址（如 `https://api.deepseek.com/v1`） | 可選 |
| `OPENAI_MODEL` | 模型名稱（如 `deepseek-chat`） | 可選 |

> *注：`GEMINI_API_KEY` 和 `OPENAI_API_KEY` 至少配置一個

<details>
<summary><b>通知渠道配置</b>（點擊展開，至少配置一個）</summary>

| Secret 名稱 | 說明 | 必填 |
|------------|------|:----:|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（@BotFather 獲取） | 可選 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可選 |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID (用於發送到子話題) | 可選 |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL | 可選 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token（與 Webhook 二選一） | 可選 |
| `DISCORD_MAIN_CHANNEL_ID` | Discord Channel ID（使用 Bot 時需要） | 可選 |
| `SLACK_BOT_TOKEN` | Slack Bot Token（推薦，支援圖片上傳；同時配置時優先於 Webhook） | 可選 |
| `SLACK_CHANNEL_ID` | Slack Channel ID（使用 Bot 時需要） | 可選 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL（僅文字，不支援圖片） | 可選 |
| `EMAIL_SENDER` | 發件人郵箱（如 `xxx@qq.com`） | 可選 |
| `EMAIL_PASSWORD` | 郵箱授權碼（非登錄密碼） | 可選 |
| `EMAIL_RECEIVERS` | 收件人郵箱（多個用逗號分隔，留空則發給自己） | 可選 |
| `WECHAT_WEBHOOK_URL` | 企業微信 Webhook URL | 可選 |
| `FEISHU_WEBHOOK_URL` | 飛書 Webhook URL | 可選 |
| `PUSHPLUS_TOKEN` | PushPlus Token（[獲取地址](https://www.pushplus.plus)，國內推送服務） | 可選 |
| `SERVERCHAN3_SENDKEY` | Server酱³ Sendkey（[獲取地址](https://sc3.ft07.com/)，手機軟體推播服務） | 可选 |
| `CUSTOM_WEBHOOK_URLS` | 自定義 Webhook（支持釘釘等，多個用逗號分隔） | 可選 |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | 自定義 Webhook 的 Bearer Token（用於需要認證的 Webhook） | 可選 |
| `SINGLE_STOCK_NOTIFY` | 單股推送模式：設為 `true` 則每分析完一隻股票立即推送 | 可選 |
| `REPORT_TYPE` | 報告類型：`simple`(精簡) 或 `full`(完整)，Docker環境推薦設為 `full` | 可選 |
| `REPORT_LANGUAGE` | 報告輸出語言：`zh`(預設中文) / `en`(英文)；會同步影響 Prompt、Markdown 模板、通知 fallback 與 Web 報告頁固定文案 | 可選 |
| `ANALYSIS_DELAY` | 個股分析和大盤分析之間的延遲（秒），避免API限流，如 `10` | 可選 |

> 至少配置一個渠道，配置多個則同時推送。更多配置請參考 [完整指南](full-guide.md)

</details>

**其他配置**

| Secret 名稱 | 說明 | 必填 |
|------------|------|:----:|
| `STOCK_LIST` | 自選股代碼，如 `600519,hk00700,AAPL,TSLA` | ✅ |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) 搜索 API（新聞搜索） | 推薦 |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimaxi.com/) Coding Plan Web Search（結構化搜索結果） | 可選 |
| `BOCHA_API_KEYS` | [博查搜索](https://open.bocha.cn/) Web Search API（中文搜索優化，支持AI摘要，多個key用逗號分隔） | 可選 |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API（隱私優先，美股優化，多個key用逗號分隔） | 可選 |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) 備用搜索 | 可選 |
| `SEARXNG_BASE_URLS` | SearXNG 自建實例（無配額兜底，需在 settings.yml 啟用 format: json）；留空時預設自動發現公共實例 | 可選 |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | 是否在 `SEARXNG_BASE_URLS` 為空時自動從 `searx.space` 取得公共實例（預設 `true`） | 可選 |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) Token | 可選 |
| `AGENT_MODE` | 啟用 Agent 策略問股模式（內部統一命名為 skill，`true`/`false`，預設 `false`） | 可選 |
| `AGENT_LITELLM_MODEL` | Agent 專用主模型（可選）；留空時繼承 `LITELLM_MODEL`，無 provider 前綴時按 `openai/<model>` 解析 | 可選 |
| `AGENT_MAX_STEPS` | Agent 最大推理步數（預設 `10`） | 可選 |
| `AGENT_SKILLS` | 逗號分隔的策略技能 id。留空時使用 metadata 宣告的主預設策略 skill（內建預設為 `bull_trend`）；使用 `all` 可啟用所有已載入策略技能。 | 可選 |
| `AGENT_SKILL_DIR` | 自訂策略技能目錄（預設沿用內建 `strategies/` 相容路徑） | 可選 |

#### 3. 啟用 Actions

進入 `Actions` 標籤 → 點擊 `I understand my workflows, go ahead and enable them`

#### 4. 手動測試

`Actions` → `每日股票分析` → `Run workflow` → 選擇模式 → `Run workflow`

#### 5. 完成！

默認每個工作日 **18:00（北京時間）** 自動執行

### 方式二：本地運行 / Docker 部署

> 📖 本地運行、Docker 部署詳細步驟請參考 [完整配置指南](full-guide.md)

## 📱 推送效果

### 決策儀表盤
```
📊 2026-01-10 決策儀表盤
3隻股票 | 🟢買入:1 🟡觀望:2 🔴賣出:0

🟢 買入 | 貴州茅台(600519)
📌 縮量回踩MA5支撐，乖離率1.2%處於最佳買點
💰 狙擊: 買入1800 | 止損1750 | 目標1900
✅多頭排列 ✅乖離安全 ✅量能配合

🟡 觀望 | 寧德時代(300750)
📌 乖離率7.8%超過5%警戒線，嚴禁追高
⚠️ 等待回調至MA5附近再考慮

---
生成時間: 18:00
```

### 大盤復盤

```
🎯 2026-01-10 大盤復盤

📊 主要指數
- 上證指數: 3250.12 (🟢+0.85%)
- 深證成指: 10521.36 (🟢+1.02%)
- 創業板指: 2156.78 (🟢+1.35%)

📈 市場概況
上漲: 3920 | 下跌: 1349 | 漲停: 155 | 跌停: 3

🔥 板塊表現
領漲: 互聯網服務、文化傳媒、小金屬
領跌: 保險、航空機場、光伏設備
```

## 配置說明

> 📖 完整環境變量、定時任務配置請參考 [完整配置指南](full-guide.md)

## 🧩 FastAPI Web 服務（可選）

本地運行時，可啟用 FastAPI 服務來管理配置和觸發分析。

### 啟動方式

| 命令 | 說明 |
|------|------|
| `python main.py --serve` | 啟動 API 服務 + 執行一次完整分析 |
| `python main.py --serve-only` | 僅啟動 API 服務，手動觸發分析 |

- 訪問地址：`http://127.0.0.1:8000`
- API 文檔：`http://127.0.0.1:8000/docs`

### 功能特性

- 📝 **配置管理** - 查看/修改自選股列表
- 🚀 **快速分析** - 通過 API 接口觸發分析
- 📊 **實時進度** - 分析任務狀態實時更新，支持多任務並行
- 🤖 **Agent 策略對話** - 啟用 `AGENT_MODE=true` 後可使用 `/ask`、`/chat`、`/history`、`/strategies`、`/research` 進行問答、查歷史、查看策略與深度研究
- 📈 **回測驗證** - 評估歷史分析準確率，查詢方向勝率與模擬收益

### API 接口

| 接口 | 方法 | 說明 |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | 觸發股票分析 |
| `/api/v1/analysis/tasks` | GET | 查詢任務列表 |
| `/api/v1/analysis/status/{task_id}` | GET | 查詢任務狀態 |
| `/api/v1/history` | GET | 查詢分析歷史記錄 |
| `/api/v1/backtest/run` | POST | 觸發回測 |
| `/api/v1/backtest/results` | GET | 查詢回測結果（分頁） |
| `/api/v1/backtest/performance` | GET | 獲取整體回測表現 |
| `/api/v1/backtest/performance/{code}` | GET | 獲取單股回測表現 |
| `/api/v1/agent/skills` | GET | 取得可用策略技能清單（內建/自訂） |
| `/api/v1/agent/chat/stream` | POST (SSE) | Agent 多輪策略對話（流式） |
| `/api/health` | GET | 健康檢查 |

> 備註：`POST /api/v1/analysis/analyze` 在 `async_mode=false` 時僅支援單一股票；批量 `stock_codes` 需使用 `async_mode=true`。異步 `202` 對單股回傳 `task_id`，對批量回傳 `accepted` / `duplicates` 匯總。

## 🔎 智慧搜尋補全 (MVP)

首頁分析輸入框現已升級為類搜尋引擎的補全框，降低手動記憶股票代碼的負擔。

- **多維匹配**：支援股票代碼、公司名稱、拼音縮寫與別名（例如 `gzmt` -> 貴州茅台、`tencent` -> 騰訊控股、`aapl` -> Apple Inc.）。
- **多市場覆蓋**：本地索引已覆蓋 **A股、港股、美股** 三個市場；需要時可基於 Tushare 或 AkShare 資料重新生成。
- **自動降級**：
  - 若索引尚未更新、缺少新上市標的，或載入失敗，介面會自動退回一般手動輸入模式，不阻斷分析流程。
  - 若補全未命中，直接按 Enter 仍會送出原始輸入。

> 提示：如需更新索引，可先執行 `python3 scripts/fetch_tushare_stock_list.py` 更新股票列表 CSV，再執行 `python3 scripts/generate_index_from_csv.py` 重新生成靜態索引。

## 項目結構

```
daily_stock_analysis/
├── main.py              # 主程序入口
├── server.py            # FastAPI 服務入口
├── src/                 # 核心業務代碼
│   ├── analyzer.py      # AI 分析器（Gemini）
│   ├── config.py        # 配置管理
│   ├── notification.py  # 消息推送
│   ├── storage.py       # 數據存儲
│   └── ...
├── api/                 # FastAPI API 模塊
├── bot/                 # 機器人模塊
├── data_provider/       # 數據源適配器
├── docker/              # Docker 配置
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/                # 項目文檔
│   ├── full-guide.md    # 完整配置指南
│   └── ...
└── .github/workflows/   # GitHub Actions
```

## 🗺️ Roadmap

> 📢 以下功能將視後續情況逐步完成，如果你有好的想法或建議，歡迎 [提交 Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues) 討論！

### 🔔 通知渠道擴展
- [x] 企業微信機器人
- [x] 飛書機器人
- [x] Telegram Bot
- [x] 郵件通知（SMTP）
- [x] 自定義 Webhook（支持釘釘、Discord、Slack、Bark 等）
- [x] iOS/Android 推送（Pushover）
- [x] 釘釘機器人 （已支持命令交互 >> [相關配置](bot/dingding-bot-config.md)）
### 🤖 AI 模型支持
- [x] Google Gemini（主力，免費額度）
- [x] OpenAI 兼容 API（支持 GPT-4/DeepSeek/通義千問/Claude/文心一言 等）
- [x] 本地模型（Ollama）

### 📊 數據源擴展
- [x] AkShare（免費）
- [x] Tushare Pro
- [x] Baostock
- [x] YFinance

### 🎯 功能增強
- [x] 決策儀表盤
- [x] 大盤復盤
- [x] 定時推送
- [x] GitHub Actions
- [x] 港股支持
- [x] Web 管理界面 (簡易版)
- [x] 美股支持
- [ ] 歷史分析回測

## ☕ 支持項目

| 支付寶 (Alipay) | 微信支付 (WeChat) | 小紅書 |
| :---: | :---: | :---: |
| <img src="../sources/alipay.jpg" width="200" alt="Alipay"> | <img src="../sources/wechatpay.jpg" width="200" alt="WeChat Pay"> | <img src="../sources/xiaohongshu.png" width="200" alt="小紅書"> |

## 貢獻

歡迎提交 Issue 和 Pull Request！

詳見 [貢獻指南](CONTRIBUTING.md)

## License
[MIT License](../LICENSE) © 2026 ZhuLinsen

如果你在項目中使用或基於本项目进行二次开发，
非常歡迎在 README 或文檔中註明來源並附上本倉庫鏈接。
這將有助於項目的持續維護和社區發展。

## 聯繫與合作
- GitHub Issues：[提交 Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
- 合作郵箱：zhuls345@gmail.com

## Star History
**如果覺得有用，請給個 ⭐ Star 支持一下！**

<a href="https://star-history.com/#ZhuLinsen/daily_stock_analysis&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date" />
 </picture>
</a>

## 免責聲明

本項目僅供學習和研究使用，不構成任何投資建議。股市有風險，投資需謹慎。作者不對使用本項目產生的任何損失負責。

---
