<div align="center">

# AI Stock Analysis System

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/)

**AI-powered stock analysis system for A-shares / Hong Kong / US stocks**

Analyze your watchlist daily → generate a decision dashboard → push to multiple channels (Telegram/Discord/Email/WeChat Work/Feishu)

**Zero-cost deployment** · Runs on GitHub Actions · No server required

[**Quick Start**](#-quick-start) · [**Key Features**](#-key-features) · [**Sample Output**](#-sample-output) · [**Full Guide**](full-guide_EN.md) · [**FAQ**](FAQ_EN.md) · [**Changelog**](CHANGELOG.md)

English | [简体中文](../README.md) | [繁體中文](README_CHT.md)

</div>

## 💖 Sponsors

<div align="center">
  <a href="https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis" target="_blank">
    <img src="../sources/serpapi_banner_en.png" alt="Easily scrape real-time financial news data from search engines - SerpApi" height="160">
  </a>
</div>
<br>

## ✨ Key Features

| Module | Feature | Description |
|--------|---------|-------------|
| AI | Decision Dashboard | One-sentence conclusion + precise entry/exit levels + action checklist |
| Analysis | Multi-dimensional Analysis | Technicals + chip distribution + sentiment + real-time quotes |
| Market | Global Markets | A-shares, Hong Kong stocks, US stocks |
| Review | Market Review | Daily overview, sectors, northbound capital flow |
| Backtest | AI Backtest Validation | Auto-evaluate historical analysis accuracy, direction win rate, SL/TP hit rates |
| Agent Q&A | Strategy Chat | Multi-turn strategy chat with 11 built-in skills (Web/Bot/API) |
| Notifications | Multi-channel Push | Telegram, Discord, Email, WeChat Work, Feishu, etc. |
| Automation | Scheduled Runs | GitHub Actions scheduled execution, no server required |

### Tech Stack & Data Sources

| Type | Supported |
|------|----------|
| LLMs | Gemini (free), OpenAI-compatible, DeepSeek, Qwen, Claude, Ollama |
| Market Data | AkShare, Tushare, Pytdx, Baostock, YFinance |
| News Search | Tavily, SerpAPI, Bocha, Brave |

### Built-in Trading Rules

| Rule | Description |
|------|-------------|
| No chasing highs | Auto warn when deviation > 5% |
| Trend trading | Bull alignment: MA5 > MA10 > MA20 |
| Precise levels | Entry, stop loss, target |
| Checklist | Each condition marked as Pass / Watch / Fail |

## 🚀 Quick Start

### Option 1: GitHub Actions (Recommended, Zero Cost)

**No server needed, runs automatically every day!**

#### 1. Fork this repository

Click the `Fork` button in the upper right corner

#### 2. Configure Secrets

Go to your forked repo → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

**AI Model Configuration (Choose one)**

| Secret Name | Description | Required |
|------------|------|:----:|
| `GEMINI_API_KEY` | Get free API key from [Google AI Studio](https://aistudio.google.com/) | ✅* |
| `OPENAI_API_KEY` | OpenAI-compatible API Key (supports DeepSeek, Qwen, etc.) | Optional |
| `OPENAI_BASE_URL` | OpenAI-compatible API endpoint (e.g., `https://api.deepseek.com/v1`) | Optional |
| `OPENAI_MODEL` | Model name (e.g., `deepseek-chat`) | Optional |

> *Note: Configure at least one of `GEMINI_API_KEY` or `OPENAI_API_KEY`

<details>
<summary><b>Notification channels</b> (expand, choose at least one)</summary>

| Secret Name | Description | Required |
|------------|------|:----:|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token (Get from @BotFather) | Optional |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | Optional |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID (For sending to topics) | Optional |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL | Optional |
| `DISCORD_BOT_TOKEN` | Discord Bot Token (choose one with Webhook) | Optional |
| `DISCORD_CHANNEL_ID` | Discord Channel ID (required when using Bot) | Optional |
| `EMAIL_SENDER` | Sender email (e.g., `xxx@qq.com`) | Optional |
| `EMAIL_PASSWORD` | Email authorization code (not login password) | Optional |
| `EMAIL_RECEIVERS` | Receiver emails (comma-separated, leave empty to send to yourself) | Optional |
| `WECHAT_WEBHOOK_URL` | WeChat Work Webhook URL | Optional |
| `FEISHU_WEBHOOK_URL` | Feishu Webhook URL | Optional |
| `PUSHPLUS_TOKEN` | PushPlus Token ([Get it here](https://www.pushplus.plus), Chinese push service) | Optional |
| `SERVERCHAN3_SENDKEY` | ServerChan v3 SendKey (([Get it here](https://sc3.ft07.com/), Mobile app push notification service) ) | Optional |
| `CUSTOM_WEBHOOK_URLS` | Custom Webhook URLs (supports DingTalk, etc., comma-separated) | Optional |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | Bearer token for custom webhooks (if required) | Optional |
| `SINGLE_STOCK_NOTIFY` | Send notification immediately after each stock | Optional |
| `REPORT_TYPE` | `simple` or `full` (Docker recommended: `full`) | Optional |
| `ANALYSIS_DELAY` | Delay between stocks and market review (seconds) | Optional |

> Note: Configure at least one channel; multiple channels will all receive notifications.

</details>

**Stock List Configuration**

| Secret Name | Description | Required |
|------------|------|:----:|
| `STOCK_LIST` | Watchlist codes, e.g., `600519,AAPL,hk00700` | ✅ |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) Search API (for news) | Recommended |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API (privacy-focused, US stocks optimized) | Optional |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) Backup search | Optional |
| `BOCHA_API_KEYS` | [Bocha Search](https://open.bocha.cn/) Web Search API (Chinese search optimized, supports AI summaries, multiple keys comma-separated) | Optional |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) Token | Optional |
| `WECHAT_MSG_TYPE` | WeChat Work message type, default `markdown`, set to `text` for plain markdown text | Optional |
| `AGENT_MODE` | Enable Agent strategy chat mode (`true`/`false`, default `false`) | Optional |
| `AGENT_MAX_STEPS` | Max reasoning steps for Agent mode (default `10`) | Optional |
| `AGENT_STRATEGY_DIR` | Custom strategy directory (default built-in `strategies/`) | Optional |

**Stock Code Format**

| Market | Format | Examples |
|--------|--------|----------|
| A-shares | 6-digit number | `600519`, `000001`, `300750` |
| HK Stocks | hk + 5-digit number | `hk00700`, `hk09988` |
| US Stocks | 1-5 uppercase letters | `AAPL`, `TSLA`, `GOOGL` |

#### 3. Enable Actions

Go to `Actions` tab → Click `I understand my workflows, go ahead and enable them`

#### 4. Manual Test

`Actions` → `Daily Stock Analysis` → `Run workflow` → Select mode → `Run workflow`

#### 5. Done!

The system will:
- Run automatically at scheduled time (default: 18:00 Beijing Time)
- Send analysis reports to all configured channels
- Save reports locally

---

### Option 2: Local Deployment

#### 1. Clone Repository

```bash
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis
```

#### 2. Install Dependencies

```bash
# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

#### 3. Configure Environment Variables

```bash
# Copy configuration template
cp .env.example .env

# Edit .env file
nano .env  # or use any editor
```

Configure the following:

```bash
# AI Model (Choose one)
GEMINI_API_KEY=your_gemini_api_key_here

# Stock Watchlist (Mixed markets supported)
STOCK_LIST=600519,AAPL,hk00700

# Notification Channel (Choose at least one)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# News Search (Optional)
TAVILY_API_KEYS=your_tavily_key
```

#### 4. Run

```bash
# One-time analysis
python main.py

# Scheduled mode (runs daily at 18:00)
python main.py --schedule

# Analyze specific stocks
python main.py --stocks AAPL,TSLA,GOOGL

# Market review only
python main.py --market-review
```

### API Endpoints

| Endpoint | Method | Description |
|------|------|------|
| `/` | GET | Configuration page |
| `/health` | GET | Health check |
| `/analysis?code=xxx` | GET | Trigger async analysis for a single stock |
| `/analysis/history` | GET | Query analysis history records |
| `/tasks` | GET | Query all task statuses |
| `/task?id=xxx` | GET | Query a single task status |

---

## 📱 Supported Notification Channels

### 1. Telegram (Recommended)

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → get Bot Token
2. Get Chat ID: send a message to [@userinfobot](https://t.me/userinfobot)
3. Configure:
  ```bash
  TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
  TELEGRAM_CHAT_ID=123456789
  ```

### 2. Discord

Webhook:
```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

Bot:
```bash
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_CHANNEL_ID=your_channel_id
```

### 3. Email

```bash
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECEIVERS=receiver@example.com  # Optional
```

### 4. WeChat Work / Feishu

WeChat Work:
```bash
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

Feishu:
```bash
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

### 5. PushPlus

```bash
PUSHPLUS_TOKEN=your_token_here
```

---

## 🎨 Sample Output

### Decision Dashboard Format

```markdown
# 🎯 2026-01-24 Decision Dashboard

> Total **3** stocks analyzed | 🟢Buy:1 🟡Hold:1 🔴Sell:1

## 📊 Analysis Summary

🟢 **AAPL(Apple Inc.)**: Buy | Score 85 | Strong Bullish
🟡 **600519(Kweichow Moutai)**: Hold | Score 65 | Bullish
🔴 **TSLA(Tesla)**: Sell | Score 35 | Bearish

---

## 🟢 AAPL (Apple Inc.)

### 📰 Key Information
**💭 Sentiment**: Positive news on iPhone 16 sales
**📊 Earnings**: Q1 2024 earnings beat expectations

### 📌 Core Conclusion

**🟢 Buy** | Strong Bullish

> **One-sentence Decision**: Strong technical setup with positive catalyst, ideal entry point

⏰ **Time Sensitivity**: Within this week

| Position | Action |
|----------|--------|
| 🆕 **No Position** | Buy at pullback |
| 💼 **With Position** | Continue holding |

### 📊 Data Perspective

**MA Alignment**: MA5>MA10>MA20 | Bull Trend: ✅ Yes | Trend Strength: 85/100

| Price Metrics | Value |
|--------------|-------|
| Current | $185.50 |
| MA5 | $183.20 |
| MA10 | $180.50 |
| MA20 | $177.80 |
| Bias (MA5) | +1.26% ✅ Safe |
| Support | $183.20 |
| Resistance | $190.00 |

**Volume**: Ratio 1.8 (Moderate increase) | Turnover 2.3%
💡 *Volume confirms bullish momentum*

### 🎯 Action Plan

**📍 Sniper Points**

| Level Type | Price |
|-----------|-------|
| 🎯 Ideal Entry | $183-184 |
| 🔵 Secondary Entry | $180-181 |
| 🛑 Stop Loss | $177 |
| 🎊 Target | $195 |

**💰 Position Sizing**: 20-30% of portfolio
- Entry Plan: Enter in 2-3 batches
- Risk Control: Strict stop loss at $177

**✅ Checklist**

- ✅ Bull trend confirmed
- ✅ Price near MA5 support
- ✅ Volume confirms trend
- ⚠️ Monitor market volatility

---
```

---

## 🔧 Advanced Configuration

### Environment Variables

```bash
# === Analysis Behavior ===
ANALYSIS_DELAY=10              # Delay between analysis (seconds) to avoid API rate limit
REPORT_TYPE=full               # Report type: simple/full
SINGLE_STOCK_NOTIFY=true       # Push immediately after each stock analysis

# === Schedule ===
SCHEDULE_ENABLED=true          # Enable scheduled task
SCHEDULE_TIME=18:00            # Daily run time (HH:MM, 24-hour format)
MARKET_REVIEW_ENABLED=true     # Enable market review

# === Data Source ===
TUSHARE_TOKEN=your_token       # Tushare Pro (priority data source if configured)

# === System ===
MAX_WORKERS=3                  # Concurrent threads (3 recommended to avoid blocking)
DEBUG=false                    # Enable debug logging
```

---

## 🧩 FastAPI Web Service (Optional)

Enable the FastAPI service for configuration management and triggering analysis when running locally.

### Startup Methods

| Command | Description |
|---------|-------------|
| `python main.py --serve` | Start API service + run full analysis once |
| `python main.py --serve-only` | Start API service only, manually trigger analysis |

- URL: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`

### Features

- 📝 **Configuration Management** - View/modify watchlist
- 🚀 **Quick Analysis** - Trigger analysis via API
- 📊 **Real-time Progress** - Analysis task status updates in real-time, supports parallel tasks
- 🤖 **Agent Strategy Chat** - Multi-turn strategy Q&A via `/chat` (enable with `AGENT_MODE=true`)
- 📈 **Backtest Validation** - Evaluate historical analysis accuracy, query direction win rate and simulated returns

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/analysis/analyze` | POST | Trigger stock analysis |
| `/api/v1/analysis/tasks` | GET | Query task list |
| `/api/v1/analysis/status/{task_id}` | GET | Query task status |
| `/api/v1/history` | GET | Query analysis history |
| `/api/v1/backtest/run` | POST | Trigger backtest |
| `/api/v1/backtest/results` | GET | Query backtest results (paginated) |
| `/api/v1/backtest/performance` | GET | Get overall backtest performance |
| `/api/v1/backtest/performance/{code}` | GET | Get per-stock backtest performance |
| `/api/v1/agent/strategies` | GET | Get available built-in/custom strategies |
| `/api/v1/agent/chat/stream` | POST (SSE) | Stream multi-turn Agent strategy chat |
| `/api/health` | GET | Health check |

> For detailed instructions, see [Full Guide - API Service](full-guide_EN.md#fastapi-api-service)

---

## 📖 Documentation

- [Complete Configuration Guide](full-guide_EN.md)
- [FAQ](FAQ_EN.md)
- [Deployment Guide](DEPLOY_EN.md)
- [Bot Command Reference](bot-command.md)
- [Feishu Bot Setup](bot/feishu-bot-config.md)
- [DingTalk Bot Setup](bot/dingding-bot-config.md)

---

## ☕ Support the Project

<div align="center">
  <a href="https://ko-fi.com/mumu157" target="_blank">
    <img src="https://storage.ko-fi.com/cdn/kofi3.png?v=3" alt="Buy Me a Coffee at ko-fi.com" style="height: 40px !important;">
  </a>
</div>

| Alipay | WeChat Pay | Ko-fi |
| :---: | :---: | :---: |
| <img src="../sources/alipay.jpg" width="200" alt="Alipay"> | <img src="../sources/wechatpay.jpg" width="200" alt="WeChat Pay"> | <a href="https://ko-fi.com/mumu157" target="_blank"><img src="../sources/ko-fi.png" width="200" alt="Ko-fi"></a> |

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## ⭐ Star History
**Made with ❤️ by AI enthusiasts | Star ⭐ this repo if you find it useful!**


<a href="https://star-history.com/#ZhuLinsen/daily_stock_analysis&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=ZhuLinsen/daily_stock_analysis&type=Date" />
 </picture>
</a>

## ⚠️ Disclaimer

This tool is for **informational and educational purposes only**. The analysis results are generated by AI and should not be considered as investment advice. Stock market investments carry risk, and you should:

- Do your own research before making investment decisions
- Understand that past performance does not guarantee future results
- Only invest money you can afford to lose
- Consult with a licensed financial advisor for personalized advice

The developers of this tool are not liable for any financial losses resulting from the use of this software.

---

## 🙏 Acknowledgments

- [AkShare](https://github.com/akfamily/akshare) - Stock data source
- [Google Gemini](https://ai.google.dev/) - AI analysis engine
- [Tavily](https://tavily.com/) - News search API
- All contributors who helped improve this project

---

## 📞 Contact

- GitHub Issues: [Report bugs or request features](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
- Discussions: [Join discussions](https://github.com/ZhuLinsen/daily_stock_analysis/discussions)

----
