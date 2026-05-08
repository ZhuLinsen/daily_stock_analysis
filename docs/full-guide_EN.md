# Complete Configuration & Deployment Guide

This document contains the complete configuration guide for the AI Stock Analysis System, intended for users who need advanced features or special deployment methods.

> Quick start guide available in [README_EN.md](README_EN.md). This document covers advanced configuration.

## Project Structure

```
daily_stock_analysis/
├── main.py              # Main entry point
├── src/                 # Core business logic
│   ├── analyzer.py      # AI analyzer
│   ├── config.py        # Configuration management
│   ├── notification.py  # Message push notifications
│   └── ...
├── data_provider/       # Multi-source data adapters
├── bot/                 # Bot interaction module
├── api/                 # FastAPI backend service
├── apps/dsa-web/        # React frontend
├── docker/              # Docker configuration
├── docs/                # Project documentation
└── .github/workflows/   # GitHub Actions
```

## Table of Contents

- [Project Structure](#project-structure)
- [GitHub Actions Configuration](#github-actions-configuration)
- [Complete Environment Variables List](#complete-environment-variables-list)
- [Docker Deployment](#docker-deployment)
- [Local Deployment](#local-deployment)
- [Scheduled Task Configuration](#scheduled-task-configuration)
- [Notification Channel Configuration](#notification-channel-configuration)
- [Data Source Configuration](#data-source-configuration)
- [Advanced Features](#advanced-features)
- [Backtesting](#backtesting)
- [Local WebUI Management Interface](#local-webui-management-interface)

---

## GitHub Actions Configuration

### 1. Fork this Repository

Click the `Fork` button in the upper right corner.

### 2. Configure Secrets

Go to your forked repo → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

<div align="center">
  <img src="../sources/secret_config.png" alt="GitHub Secrets Configuration" width="600">
</div>

#### AI Model Configuration (Configure at Least One)

> Note: The configuration below documents existing runtime provider support and compatibility boundaries; this update is documentation-alignment only and does not introduce new runtime implementation.

| Secret Name | Description | Required |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC) API key, one key for popular LLMs and Chinese-optimized web search with free quota for this project | Recommended |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API key, one key for multiple model families and a 10% top-up discount for this project | Recommended |
| `GEMINI_API_KEY` | Get free key from [Google AI Studio](https://aistudio.google.com/) | Optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | Optional |
| `OPENAI_API_KEY` | OpenAI-compatible API Key (supports DeepSeek, Qwen, etc.) | Optional |
| `OPENAI_BASE_URL` | OpenAI-compatible API endpoint (e.g., `https://api.deepseek.com`) | Optional |
| `OPENAI_MODEL` | Model name (e.g., `deepseek-v4-flash`) | Optional |

> *Note: Configure at least one model key or channel. Anspire or AIHubMix is the simplest starting point for one-key multi-model access.

#### Notification Channels (Multiple can be configured, all will receive notifications)

> The notification baseline, minimal/advanced key split, Actions mapping, `--check-notify` CLI behavior, and Web one-click notification test are tracked in [Notification Baseline](notifications.md). A complete English notification topic remains a later follow-up.

| Secret Name | Description | Required |
|------------|------|:----:|
| `WECHAT_WEBHOOK_URL` | WeChat Work Webhook URL | Optional |
| `FEISHU_WEBHOOK_URL` | Feishu Webhook URL | Optional |
| `FEISHU_WEBHOOK_SECRET` | Feishu Webhook signing secret (required when “Signature” security is enabled) | Optional |
| `FEISHU_WEBHOOK_KEYWORD` | Feishu Webhook keyword (required when “Keyword” security is enabled) | Optional |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token (get from @BotFather) | Optional |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | Optional |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID (for sending to topics) | Optional |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL ([How to create](https://support.discord.com/hc/en-us/articles/228383668)) | Optional |
| `DISCORD_BOT_TOKEN` | Discord Bot Token (choose one with Webhook) | Optional |
| `DISCORD_MAIN_CHANNEL_ID` | Discord Channel ID (required when using Bot) | Optional |
| `DISCORD_INTERACTIONS_PUBLIC_KEY` | Discord Public Key (required only for inbound Interaction/Webhook signature verification) | Optional |
| `SLACK_BOT_TOKEN` | Slack Bot Token (recommended, supports image upload; takes priority over Webhook when both set) | Optional |
| `SLACK_CHANNEL_ID` | Slack Channel ID (required when using Bot) | Optional |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL (text only, no image support) | Optional |
| `EMAIL_SENDER` | Sender email (e.g., `xxx@qq.com`) | Optional |
| `EMAIL_PASSWORD` | Email authorization code (not login password) | Optional |
| `EMAIL_RECEIVERS` | Receiver emails (comma-separated, leave empty to send to self) | Optional |
| `EMAIL_SENDER_NAME` | Sender display name | Optional |
| `STOCK_GROUP_N` / `EMAIL_GROUP_N` | Email routing groups (Issue #268): `STOCK_GROUP_N` should be a subset of `STOCK_LIST`; affects email recipients only, not analysis scope or other channels | Optional |
| `PUSHPLUS_TOKEN` | PushPlus Token ([Get here](https://www.pushplus.plus), Chinese push service) | Optional |
| `SERVERCHAN3_SENDKEY` | ServerChan v3 Sendkey ([Get here](https://sc3.ft07.com/), mobile app push service) | Optional |
| `ASTRBOT_URL` | AstrBot Webhook URL | Optional |
| `ASTRBOT_TOKEN` | Optional AstrBot Bearer Token | Optional |
| `CUSTOM_WEBHOOK_URLS` | Custom Webhook (supports DingTalk, etc., comma-separated) | Optional |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | Bearer Token for custom webhooks (for authenticated webhooks) | Optional |
| `CUSTOM_WEBHOOK_BODY_TEMPLATE` | Custom Webhook JSON body template for AstrBot, NapCat, or self-hosted services with special payloads | Optional |
| `WEBHOOK_VERIFY_SSL` | Verify Webhook HTTPS certificates (default true). Set to false for self-signed certs. WARNING: Disabling has serious security risk (MITM), use only on trusted internal networks | Optional |

> *Note: Configure at least one channel; multiple channels will all receive notifications
>
> The default `daily_analysis.yml` in this repository only exports fixed Secret / Variable names. Arbitrary numbered env vars such as `STOCK_GROUP_1` and `EMAIL_GROUP_1` are not auto-injected into the job, so grouped email routing is not available in the stock workflow unless you explicitly extend the workflow's `env:` mapping in your own fork. P0 maps `CUSTOM_WEBHOOK_BODY_TEMPLATE`, `WEBHOOK_VERIFY_SSL`, `FEISHU_WEBHOOK_SECRET`, `FEISHU_WEBHOOK_KEYWORD`, and `PUSHPLUS_TOPIC`; `MARKDOWN_TO_IMAGE_CHANNELS` and `MERGE_EMAIL_NOTIFICATION` remain behavior toggles for a later phase.

#### Push Behavior Configuration

| Secret Name | Description | Required |
|------------|------|:----:|
| `SINGLE_STOCK_NOTIFY` | Single stock push mode: set to `true` to push immediately after each stock analysis | Optional |
| `REPORT_TYPE` | Report type: `simple` (concise), `full` (complete), `brief` (3-5 sentences), Docker recommended: `full` | Optional |
| `REPORT_LANGUAGE` | Report output language: `zh` (default Chinese) / `en` (English); also updates prompt instructions, templates, notification fallbacks, and fixed copy in the Web report view. The bundled `daily_analysis.yml` already maps this variable, so setting it in Actions Secrets/Variables works out of the box | Optional |
| `REPORT_TEMPLATES_DIR` | Jinja2 template directory (relative to project root, default `templates`) | Optional |
| `REPORT_RENDERER_ENABLED` | Enable Jinja2 template rendering (default `false`, zero regression) | Optional |
| `REPORT_INTEGRITY_ENABLED` | Enable report integrity checks, retry or placeholder on missing fields (default `true`) | Optional |
| `REPORT_INTEGRITY_RETRY` | Integrity retry count (default `1`, `0` = placeholder only) | Optional |
| `REPORT_HISTORY_COMPARE_N` | History signal comparison count, `0` off (default), `>0` enable | Optional |
| `ANALYSIS_DELAY` | Delay between stock analysis and market review (seconds) to avoid API rate limits, e.g., `10` | Optional |

#### Other Configuration

| Secret Name | Description | Required |
|------------|------|:----:|
| `STOCK_LIST` | Watchlist codes, e.g., `600519,300750,002594` | ✅ |
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/) optimized for Chinese content; the same key can also be used for Anspire LLM fallback scenarios (example model: `Doubao-Seed-2.0-lite`) | Recommended |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) search-engine results for realtime financial news | Recommended |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) Search API (for news search) | Optional |
| `BOCHA_API_KEYS` | [Bocha Search](https://open.bocha.cn/) Web Search API (Chinese search optimized, supports AI summaries, multiple keys comma-separated) | Optional |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API (privacy-first, US-stock news enrichment, comma-separated for multiple keys) | Optional |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimax.io/) Coding Plan Web Search (structured search results) | Optional |
| `SEARXNG_BASE_URLS` | SearXNG self-hosted instances (quota-free fallback, enable format: json in settings.yml); when empty the app auto-discovers public instances | Optional |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Auto-discover public SearXNG instances from `searx.space` when `SEARXNG_BASE_URLS` is empty (default `true`) | Optional |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638) Token | Optional |
| `TICKFLOW_API_KEY` | [TickFlow](https://tickflow.org) API key for CN market review index enhancement; market breadth also uses TickFlow when the plan supports universe queries | Optional |

#### ✅ Minimum Configuration Example

To get started quickly, you need at minimum:

1. **AI Model**: `ANSPIRE_API_KEYS` (one key for LLMs and search), `AIHUBMIX_KEY` (one key for multiple model families), `GEMINI_API_KEY`, or `OPENAI_API_KEY`
2. **Notification Channel**: At least one, e.g., `WECHAT_WEBHOOK_URL` or `EMAIL_SENDER` + `EMAIL_PASSWORD`
3. **Stock List**: `STOCK_LIST` (required)
4. **Search API**: `ANSPIRE_API_KEYS` or `SERPAPI_API_KEYS` (recommended for news and sentiment search)

> Configure these 4 items and you're ready to go!

### 3. Enable Actions

1. Go to your forked repository
2. Click the `Actions` tab at the top
3. If prompted, click `I understand my workflows, go ahead and enable them`

### 4. Manual Test

1. Go to `Actions` tab
2. Select `Daily Stock Analysis` workflow on the left
3. Click `Run workflow` button on the right
4. Select run mode
5. Click green `Run workflow` to confirm

### 5. Done!

Default schedule: Every weekday at **18:00 (Beijing Time)** automatic execution.

---

## Complete Environment Variables List

### AI Model Configuration

> Full details: [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md) (three-tier config, channels, Vision, Agent, troubleshooting).

| Variable | Description | Default | Required |
|--------|------|--------|:----:|
| `LITELLM_MODEL` | Primary model, format `provider/model` (e.g. `gemini/gemini-3.1-pro-preview`), recommended | - | No |
| `AGENT_LITELLM_MODEL` | Optional Agent-only primary model; when empty it inherits the primary model, and bare names are normalized to `openai/<model>` | - | No |
| `LITELLM_FALLBACK_MODELS` | Fallback models, comma-separated | - | No |
| `LLM_CHANNELS` | Channel names (comma-separated), use with `LLM_{NAME}_*`, see [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md) | - | No |
| `LITELLM_CONFIG` | Advanced model routing YAML path (expert use) | - | No |
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC) API key, one key for the LLM gateway and search | - | Optional |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API key, one key for multiple model families | - | Optional |
| `GEMINI_API_KEY` | Google Gemini API Key | - | Optional |
| `GEMINI_MODEL` | Primary model name (legacy, `LITELLM_MODEL` preferred) | `gemini-3.1-pro-preview` | No |
| `GEMINI_MODEL_FALLBACK` | Fallback model (legacy) | `gemini-3-flash-preview` | No |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | - | Optional |
| `OPENAI_API_KEY` | OpenAI-compatible API Key | - | Optional |
| `OPENAI_BASE_URL` | OpenAI-compatible API endpoint | - | Optional |
| `OLLAMA_API_BASE` | Ollama local service address (e.g. `http://localhost:11434`), see [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md) | - | Optional |
| `OPENAI_MODEL` | OpenAI model name (legacy) | `gpt-5.5` | Optional |

> *Note: Configure at least one of `ANSPIRE_API_KEYS`, `AIHUBMIX_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_API_BASE`, or `LLM_CHANNELS` / `LITELLM_CONFIG`. `ANSPIRE_API_KEYS` and `AIHUBMIX_KEY` are auto-adapted without an `OPENAI_BASE_URL`.

### Notification Channel Configuration

For the P0 notification baseline and diagnostics, see [Notification Baseline](notifications.md).

| Variable | Description | Required |
|--------|------|:----:|
| `WECHAT_WEBHOOK_URL` | WeChat Work Bot Webhook URL | Optional |
| `FEISHU_WEBHOOK_URL` | Feishu Bot Webhook URL | Optional |
| `FEISHU_WEBHOOK_SECRET` | Feishu bot signing secret (only for webhook bots with Signature security enabled) | Optional |
| `FEISHU_WEBHOOK_KEYWORD` | Feishu bot keyword (only for webhook bots with Keyword security enabled) | Optional |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | Optional |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | Optional |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID | Optional |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL | Optional |
| `DISCORD_BOT_TOKEN` | Discord Bot Token (choose one with Webhook) | Optional |
| `DISCORD_MAIN_CHANNEL_ID` | Discord Channel ID (required when using Bot) | Optional |
| `DISCORD_INTERACTIONS_PUBLIC_KEY` | Discord Public Key (required only for inbound Interaction/Webhook signature verification) | Optional |
| `DISCORD_MAX_WORDS` | Discord Word Limit (default 2000 for un-upgraded servers) | Optional |
| `SLACK_BOT_TOKEN` | Slack Bot Token (recommended, supports image upload; takes priority over Webhook when both set) | Optional |
| `SLACK_CHANNEL_ID` | Slack Channel ID (required when using Bot) | Optional |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL (text only, no image support) | Optional |
| `EMAIL_SENDER` | Sender email | Optional |
| `EMAIL_PASSWORD` | Email authorization code (not login password) | Optional |
| `EMAIL_RECEIVERS` | Receiver emails (comma-separated, leave empty to send to self) | Optional |
| `EMAIL_SENDER_NAME` | Sender display name | Optional |
| `STOCK_GROUP_N` / `EMAIL_GROUP_N` | Email routing groups (Issue #268): `STOCK_GROUP_N` should stay within `STOCK_LIST` and only changes email recipients | Optional |
| `CUSTOM_WEBHOOK_URLS` | Custom Webhook (comma-separated) | Optional |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | Custom Webhook Bearer Token | Optional |
| `WEBHOOK_VERIFY_SSL` | Webhook HTTPS certificate verification (default true). Set to false for self-signed certs. WARNING: Disabling has serious security risk | Optional |
| `PUSHOVER_USER_KEY` | Pushover User Key | Optional |
| `PUSHOVER_API_TOKEN` | Pushover API Token | Optional |
| `PUSHPLUS_TOKEN` | PushPlus Token (Chinese push service) | Optional |
| `SERVERCHAN3_SENDKEY` | ServerChan v3 Sendkey | Optional |
| `ASTRBOT_URL` | AstrBot Webhook URL | Optional |
| `ASTRBOT_TOKEN` | Optional AstrBot Bearer Token | Optional |

> Note: the default `daily_analysis` GitHub Actions workflow only maps fixed variable names. It does not automatically import arbitrary numbered variables such as `STOCK_GROUP_N` / `EMAIL_GROUP_N`. This feature therefore works in local `.env`, Docker, or any runtime where you explicitly inject those variables.

#### Feishu Cloud Document Configuration (Optional, solves message truncation issues)

| Variable | Description | Required |
|--------|------|:----:|
| `FEISHU_APP_ID` | Feishu App ID | Optional |
| `FEISHU_APP_SECRET` | Feishu App Secret | Optional |
| `FEISHU_FOLDER_TOKEN` | Feishu Cloud Drive Folder Token | Optional |

> Feishu Cloud Document setup steps:
> 1. Create an app in [Feishu Developer Console](https://open.feishu.cn/app)
> 2. Configure GitHub Secrets
> 3. Create a group and add the app bot
> 4. Add the group as a collaborator to the cloud drive folder (with manage permissions)
>
> Note: `FEISHU_APP_ID` / `FEISHU_APP_SECRET` are for Feishu app mode, cloud documents, or Stream Bot mode. They do not enable group webhook notifications by themselves. For simple push notifications, use `FEISHU_WEBHOOK_URL` first.

### Search Service Configuration

| Variable | Description | Required |
|--------|------|:----:|
| `ANSPIRE_API_KEYS` | Anspire Open API Key (shared with search and LLM fallback examples; availability depends on account/model entitlement, and can effectively enhance A-share analysis) | Recommended |
| `SERPAPI_API_KEYS` | SerpAPI search-engine results for realtime financial news | Recommended |
| `TAVILY_API_KEYS` | Tavily Search API Key | Optional |
| `BOCHA_API_KEYS` | Bocha Search API Key (Chinese optimized) | Optional |
| `BRAVE_API_KEYS` | Brave Search API Key (US stocks optimized) | Optional |
| `MINIMAX_API_KEYS` | MiniMax Coding Plan Web Search (structured results) | Optional |
| `SOCIAL_SENTIMENT_API_KEY` | Stock Sentiment API Key (Reddit / X / Polymarket, US stocks optional) | Optional |
| `SOCIAL_SENTIMENT_API_URL` | Stock Sentiment API endpoint (default `https://api.adanos.org`) | Optional |
| `SEARXNG_BASE_URLS` | SearXNG self-hosted instances (quota-free fallback, enable format: json in settings.yml); when empty the app auto-discovers public instances | Optional |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Auto-discover public SearXNG instances from `searx.space` when `SEARXNG_BASE_URLS` is empty (default `true`) | Optional |

> Behavior note: Search and social sentiment are optional enhancement services. If either service fails to initialize, the system logs a warning and degrades gracefully by skipping that stage without blocking the core analysis flow.

### Data Source Configuration

| Variable | Description | Default | Required |
|--------|------|--------|:----:|
| `TUSHARE_TOKEN` | Tushare Pro Token | - | Optional |
| `TICKFLOW_API_KEY` | TickFlow API key; CN market review indices prefer TickFlow when configured, and market breadth does so only when the plan supports universe queries | - | Optional |
| `ENABLE_REALTIME_QUOTE` | Enable real-time quotes (if disabled, uses historical closing prices for analysis) | `true` | Optional |
| `ENABLE_REALTIME_TECHNICAL_INDICATORS` | Intraday real-time technicals: Calculate MA5/MA10/MA20 and bull trends using real-time prices when enabled (Issue #234); uses yesterday's close if disabled. | `true` | Optional |
| `ENABLE_CHIP_DISTRIBUTION` | Enable chip distribution analysis (this API is unstable, recommended to disable for cloud deployment). GitHub Actions users must set `ENABLE_CHIP_DISTRIBUTION=true` in Repository Variables to enable; disabled by default in workflows. | `true` | Optional |
| `ENABLE_EASTMONEY_PATCH` | Eastmoney API patch: Recommended to set to `true` when Eastmoney APIs fail frequently (e.g., RemoteDisconnected, connection closed). Injects NID tokens and random User-Agents to reduce rate limiting probability. | `false` | Optional |
| `REALTIME_SOURCE_PRIORITY` | Real-time quote source priority (comma-separated), e.g., `tencent,akshare_sina,efinance,akshare_em` | See .env.example | Optional |
| `ENABLE_FUNDAMENTAL_PIPELINE` | Master switch for fundamental aggregation; when disabled, returns `not_supported` block only, without altering the original analysis pipeline. | `true` | Optional |
| `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS` | Total latency budget for the fundamental stage (seconds) | `1.5` | Optional |
| `FUNDAMENTAL_FETCH_TIMEOUT_SECONDS` | Timeout for a single capability source call (seconds) | `0.8` | Optional |
| `FUNDAMENTAL_RETRY_MAX` | Retry count for fundamental capabilities (including the first attempt) | `1` | Optional |
| `FUNDAMENTAL_CACHE_TTL_SECONDS` | Fundamental aggregation cache TTL (seconds), short cache to reduce repeated API pulling. | `120` | Optional |
| `FUNDAMENTAL_CACHE_MAX_ENTRIES` | Maximum entries for fundamental cache (evicted by time within TTL) | `256` | Optional |

> **Behavior Notes:**
> - **A-shares**: Returns aggregated capabilities by `valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards`.
> - **ETFs**: Returns available items, marks missing capabilities as `not_supported`, and does not affect the original flow overall.
> - **US/HK stocks**: Returns `not_supported` fallback block.
> - Any exception uses fail-open logic, only logs errors without affecting the main technical/news/chip pipeline.
> - **Field contracts**:
>   - `fundamental_context.belong_boards` = related board list for the stock (currently populated for A-shares only; `[]` when unavailable);
>   - `fundamental_context.boards.data` = `sector_rankings` (sector rise/fall leaderboard, structure `{top, bottom}`);
>   - `get_stock_info.belong_boards` = list of sectors the individual stock belongs to;
>   - `get_stock_info.boards` is a compatibility alias, value is identical to `belong_boards` (removal considered only in major version updates);
>   - `get_stock_info.sector_rankings` stays consistent with `fundamental_context.boards.data`.
>   - `AnalysisReport.details.belong_boards` = related board list in structured report details;
>   - `AnalysisReport.details.sector_rankings` = sector leaderboard in structured report details for board-linkage display.
> - **Sector leaderboard** uses a fixed fallback order: consistent with global priority.
> - **Timeout control** is a `best-effort` soft timeout: the stage will quickly degrade and continue execution based on the budget, but does not guarantee a hard interrupt of underlying third-party network calls.
> - `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS=1.5` indicates the target budget for the newly added fundamental stage, not a strict hard SLA.
> - For a hard SLA, please upgrade to isolated child process execution in future versions to forcefully terminate timeout tasks.

### Other Configuration

| Variable | Description | Default |
|--------|------|--------|
| `STOCK_LIST` | Watchlist codes (comma-separated) | - |
| `MAX_WORKERS` | Concurrent threads | `3` |
| `MARKET_REVIEW_ENABLED` | Enable market review | `true` |
| `MARKET_REVIEW_REGION` | Market review region: cn (A-shares), hk (HK stocks), us (US stocks), both (all three markets) | `cn` |
| `SCHEDULE_ENABLED` | Enable scheduled tasks | `false` |
| `SCHEDULE_TIME` | Scheduled execution time | `18:00` |
| `LOG_DIR` | Log directory | `./logs` |

> Behavior notes:
> - When `TICKFLOW_API_KEY` is configured, CN market review first tries TickFlow for main indices. Market breadth also tries TickFlow only when the current TickFlow plan supports universe queries.
> - TickFlow behavior is capability-based rather than just key-based: limited plans can still enhance main CN indices, while plans with `CN_Equity_A` universe query support also enhance market breadth.
> - The official quickstart documents `quotes.get(universes=["CN_Equity_A"])`, but online smoke tests confirmed two additional real-world constraints: universe access depends on plan permissions, and `quotes.get(symbols=[...])` has a per-request symbol limit.
> - TickFlow currently returns `change_pct` / `amplitude` as ratio values; this integration normalizes them to the project's percent convention so they match AkShare / Tushare / efinance semantics.
> - CN market review reports now use a post-market workstation layout with fixed market light, market temperature, index detail, sector Top tables, news catalysts, next-session plan, and risk sections. Missing data sources degrade by omitting or simplifying only the affected block.
> - Per-stock analysis, realtime quote priority, and sector rankings fallback remain unchanged.

---

## Docker Deployment

The image uses prebuilt frontend assets under `/app/static` at runtime, so the running `server` container does not require the `apps/dsa-web` source tree or runtime `npm`. If WebUI cannot be opened after Docker deployment, first verify that `/app/static/index.html` exists inside the container.

Official image registries:

- GHCR: `ghcr.io/zhulinsen/daily_stock_analysis:<tag>`
- Docker Hub: `<DOCKERHUB_USERNAME>/daily_stock_analysis:<tag>` (driven by the publisher's `DOCKERHUB_USERNAME` secret; the official release uses `zhulinsen/daily_stock_analysis`)

### Quick Start

```bash
# 1. Clone repository
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis

# 2. Configure environment variables
cp .env.example .env
vim .env  # Fill in API Keys and configuration

# 3. Start container
docker-compose -f ./docker/docker-compose.yml up -d server     # Web service mode (recommended, provides API & WebUI)
docker-compose -f ./docker/docker-compose.yml up -d analyzer   # Scheduled task mode
docker-compose -f ./docker/docker-compose.yml up -d            # Start both modes

# 4. Access WebUI
# http://localhost:8000

# 5. View logs
docker-compose -f ./docker/docker-compose.yml logs -f server
```

### Run Official Images Directly

If you do not want to keep the source tree on the target machine, you can run the published image directly:

```bash
# Web/API mode
docker pull zhulinsen/daily_stock_analysis:latest
docker run -d \
  --name dsa-server \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  -v "$(pwd)/.env:/app/.env" \
  zhulinsen/daily_stock_analysis:latest \
  python main.py --serve-only --host 0.0.0.0 --port 8000

# Scheduled-task mode
docker run -d \
  --name dsa-analyzer \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  -v "$(pwd)/.env:/app/.env" \
  zhulinsen/daily_stock_analysis:latest
```

For pinned deployments or easier rollback, replace `latest` with a concrete version tag such as `v3.13.0`.

### Run Mode Description

| Command | Description | Port |
|------|------|------|
| `docker-compose -f ./docker/docker-compose.yml up -d server` | Web service mode, provides API & WebUI | 8000 |
| `docker-compose -f ./docker/docker-compose.yml up -d analyzer` | Scheduled task mode, daily auto execution | - |
| `docker-compose -f ./docker/docker-compose.yml up -d` | Start both modes simultaneously | 8000 |

### Docker Compose Configuration

`docker-compose.yml` uses YAML anchors to reuse configuration:

```yaml
version: '3.8'

x-common: &common
  build:
    context: ..
    dockerfile: docker/Dockerfile
  restart: unless-stopped
  env_file:
    - ../.env
  environment:
    - TZ=Asia/Shanghai
  volumes:
    - ../data:/app/data
    - ../logs:/app/logs
    - ../reports:/app/reports
    - ../.env:/app/.env
    - ../strategies:/app/strategies:ro

services:
  # Scheduled task mode
  analyzer:
    <<: *common
    container_name: stock-analyzer

  # FastAPI mode
  server:
    <<: *common
    container_name: stock-server
    command: ["python", "main.py", "--serve-only", "--host", "0.0.0.0", "--port", "${API_PORT:-8000}"]
    ports:
      - "${API_PORT:-8000}:${API_PORT:-8000}"
```

### `.env` and Volume Mapping

For both `docker run` and Compose, keep these two layers in mind:

- Environment injection: `--env-file .env` or Compose `env_file`
  This passes key/value pairs from `.env` into the container process environment.
- File mapping: `-v "$(pwd)/.env:/app/.env"` or Compose `../.env:/app/.env`
  This mounts the same `.env` file into the container so the Web settings page and backend read/write the same persisted config file.

Recommended host mappings:

- `./data:/app/data` for runtime data and database files
- `./logs:/app/logs` for logs
- `./reports:/app/reports` for generated reports
- `./strategies:/app/strategies:ro` for custom strategy YAML files

Optional static asset override:

- `./static:/app/static:ro`

### Common Commands

```bash
# View running status
docker-compose -f ./docker/docker-compose.yml ps

# View logs
docker-compose -f ./docker/docker-compose.yml logs -f server

# Stop services
docker-compose -f ./docker/docker-compose.yml down

# Rebuild image (after code update)
docker-compose -f ./docker/docker-compose.yml build --no-cache
docker-compose -f ./docker/docker-compose.yml up -d server
```

### Manual Image Build

```bash
docker build -f docker/Dockerfile -t stock-analysis .
docker run -d \
  --name dsa-server-local \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  -v "$(pwd)/.env:/app/.env" \
  stock-analysis \
  python main.py --serve-only --host 0.0.0.0 --port 8000
```

---

## Local Deployment

### Install Dependencies

```bash
# Python 3.10+ recommended
pip install -r requirements.txt

# Or use conda
conda create -n stock python=3.10
conda activate stock
pip install -r requirements.txt
```

### Command Line Arguments

```bash
python main.py                        # Full analysis (stocks + market review)
python main.py --market-review        # Market review only
python main.py --no-market-review     # Stock analysis only
python main.py --stocks 600519,300750 # Specify stocks
python main.py --dry-run              # Fetch data only, no AI analysis
python main.py --no-notify            # Don't send notifications
python main.py --schedule             # Scheduled task mode
python main.py --debug                # Debug mode (verbose logging)
python main.py --workers 5            # Specify concurrency
```

---

## Scheduled Task Configuration

### GitHub Actions Schedule

Edit `.github/workflows/daily_analysis.yml`:

```yaml
schedule:
  # UTC time, Beijing time = UTC + 8
  - cron: '0 10 * * 1-5'   # Monday to Friday 18:00 (Beijing Time)
```

Common time reference:

| Beijing Time | UTC cron expression |
|---------|----------------|
| 09:30 | `'30 1 * * 1-5'` |
| 12:00 | `'0 4 * * 1-5'` |
| 15:00 | `'0 7 * * 1-5'` |
| 18:00 | `'0 10 * * 1-5'` |
| 21:00 | `'0 13 * * 1-5'` |

### Local Scheduled Tasks

```bash
# Start scheduled mode (default 18:00 execution)
python main.py --schedule

# Or use crontab
crontab -e
# Add: 0 18 * * 1-5 cd /path/to/project && python main.py
```

> Note: Scheduled mode reloads the saved `STOCK_LIST` before each run. If you also pass `--stocks`, it will not pin future scheduled executions to the startup snapshot; use a normal one-off run when you want to analyze a temporary stock list.
>
> When the built-in scheduler is started via `python main.py --schedule`, `python main.py --serve --schedule`, or an equivalent local mode, saving a new `SCHEDULE_TIME` from the WebUI will rebind the daily job on the next scheduler poll without restarting the process. The previous trigger time is removed instead of being kept alongside the new one.

---

## Notification Channel Configuration

The P0 notification channel matrix and `--check-notify` CLI details are documented in [Notification Baseline](notifications.md).

### WeChat Work

1. Add "Group Bot" in WeChat Work group chat
2. Copy Webhook URL
3. Set `WECHAT_WEBHOOK_URL`

### Feishu

> ⚠️ **Key distinction**: `FEISHU_WEBHOOK_SECRET` (webhook signing secret) and `FEISHU_APP_SECRET` (Feishu App Secret) are two completely different configuration variables and cannot be used interchangeably.

**Minimum viable config (no security restrictions):**

```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your_hook_token
```

**Step-by-step setup:**

1. **Create a Custom Bot in the target Feishu group**:
   - Open the group → tap the settings icon (top right) → **Group Bots** → **Add Bot** → **Custom Bot**
   - Enter a name for the bot, then copy the generated **Webhook URL** (format: `https://open.feishu.cn/open-apis/bot/v2/hook/...`)
2. Set `FEISHU_WEBHOOK_URL` to the URL you just copied.
3. Check the bot's **Security Settings** and add the corresponding config if any extra option is enabled:
   - **No extra security**: only `FEISHU_WEBHOOK_URL` is needed.
   - **Signature verification enabled**: copy the secret shown in Feishu into `FEISHU_WEBHOOK_SECRET`. **Both sides must be enabled or disabled together** — if Feishu has signing on but `FEISHU_WEBHOOK_SECRET` is missing (or vice versa), every request will be rejected.
   - **Keyword enabled**: copy the exact same keyword into `FEISHU_WEBHOOK_KEYWORD`. The app will prepend it to every message automatically; no need to change report templates.
   - **IP allowlist enabled**: make sure the outbound IP of your runtime (local / Docker / GitHub Actions each have different IPs) is on the allowlist.
4. `FEISHU_APP_ID` / `FEISHU_APP_SECRET` are for Feishu app / Stream Bot / cloud document flows only — they do **not** trigger group webhook notifications and must not be used instead of `FEISHU_WEBHOOK_URL`.

**Common failure causes:**
- Only `FEISHU_APP_ID` / `FEISHU_APP_SECRET` were set, but `FEISHU_WEBHOOK_URL` was not configured
- The bot has Signature security enabled, but `FEISHU_WEBHOOK_SECRET` was not set locally (or was mistakenly set to `FEISHU_APP_SECRET`)
- The bot has Keyword security enabled, but `FEISHU_WEBHOOK_KEYWORD` was not set locally
- The bot was not added to the target group, or group permissions block it from posting
- A Feishu IP allowlist is enabled and your runtime IP is not on the allowlist
- Message content too long: Feishu has a per-message length limit; the system auto-segments messages. For full content in a single document, configure Feishu Cloud Document (`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_FOLDER_TOKEN`)

For a full illustrated troubleshooting guide, see [docs/bot/feishu-bot-config.md](bot/feishu-bot-config.md).

### Telegram

1. Talk to @BotFather to create a Bot
2. Get Bot Token
3. Get Chat ID (via @userinfobot)
4. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
5. (Optional) To send to Topic, set `TELEGRAM_MESSAGE_THREAD_ID` (get from Topic link)

### Email

1. Enable SMTP service for your email
2. Get authorization code (not login password)
3. Set `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS`

Supported email providers:
- QQ Mail: smtp.qq.com:465
- 163 Mail: smtp.163.com:465
- Gmail: smtp.gmail.com:587

**Send different stock groups to different email recipients** (Issue #268, optional):
Configure `STOCK_GROUP_N` and `EMAIL_GROUP_N` to route different stock groups to different inboxes. `STOCK_LIST` still defines the actual analysis scope, so each `STOCK_GROUP_N` should be a subset of `STOCK_LIST`. This only changes email recipients; Telegram, WeChat, Webhook, and other channels still receive the full report for the entire `STOCK_LIST`. Market review emails are sent to all configured group recipients.

> GitHub Actions limitation: as of 2026-03-29, the repository's default `daily_analysis.yml` does not auto-import arbitrary numbered `STOCK_GROUP_N` / `EMAIL_GROUP_N` variables. If you only add them in repository Secrets / Variables without extending the workflow `env:` block, they will not reach the runtime process.

```bash
STOCK_LIST=600519,300750,002594,AAPL
STOCK_GROUP_1=600519,300750
EMAIL_GROUP_1=user1@example.com
STOCK_GROUP_2=002594,AAPL
EMAIL_GROUP_2=user2@example.com
```

### Custom Webhook

Supports any POST JSON Webhook, including:
- DingTalk Bot
- Discord Webhook
- Slack Webhook
- Bark (iOS push)
- Self-hosted services

Set `CUSTOM_WEBHOOK_URLS`, separate multiple with commas.

If AstrBot, NapCat, or a self-hosted service requires a custom request body, set
`CUSTOM_WEBHOOK_BODY_TEMPLATE`. The rendered value must be a JSON object. Prefer
`$content_json` so newlines and quotes stay valid JSON:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"msg_type":"text","content":$content_json}
```

Available placeholders: `$content_json`, `$content`, `$title_json`, `$title`.

### Discord

Discord supports two push methods:

**Method 1: Webhook (Recommended, Simple)**

1. Create Webhook in Discord channel settings
2. Copy Webhook URL
3. Configure environment variable:

```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

**Method 2: Bot API (Requires more permissions)**

1. Create application in [Discord Developer Portal](https://discord.com/developers/applications)
2. Create Bot and get Token
3. Invite Bot to server
4. Get Channel ID (right-click channel in developer mode)
5. Configure environment variables:

```bash
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_MAIN_CHANNEL_ID=your_channel_id
```

If you need to receive Discord Slash Command / Interaction callbacks instead of only sending notifications to Discord, also copy the public key from `Discord Developer Portal -> General Information -> Public Key` and configure:

```bash
DISCORD_INTERACTIONS_PUBLIC_KEY=your_public_key
```

Without this public key, inbound Discord webhook requests are rejected.

### Slack

Slack supports two push methods. When both are configured, Bot API takes priority to ensure text and images land in the same channel:

**Method 1: Bot API (Recommended, supports image upload)**

1. Create a Slack App: https://api.slack.com/apps → Create New App
2. Add Bot Token Scopes: `chat:write`, `files:write`
3. Install to workspace and get Bot Token (xoxb-...)
4. Get Channel ID: channel details → copy channel ID at the bottom
5. Configure environment variables:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C01234567
```

**Method 2: Incoming Webhook (Simple setup, text only)**

1. Create an Incoming Webhook in Slack App management page
2. Copy the Webhook URL
3. Configure environment variable:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```

### Pushover (iOS/Android Push)

[Pushover](https://pushover.net/) is a cross-platform push service supporting iOS and Android.

1. Register Pushover account and download App
2. Get User Key from [Pushover Dashboard](https://pushover.net/)
3. Create Application to get API Token
4. Configure environment variables:

```bash
PUSHOVER_USER_KEY=your_user_key
PUSHOVER_API_TOKEN=your_api_token
```

Features:
- Supports iOS/Android
- Supports notification priority and sound settings
- Free quota sufficient for personal use (10,000 messages/month)
- Messages retained for 7 days

---

## Data Source Configuration

System defaults to AkShare (free), also supports other data sources:

### AkShare (Default)
- Free, no configuration needed
- Data source: Eastmoney scraper

### Tushare Pro
- Requires registration to get Token
- More stable, more comprehensive data
- Set `TUSHARE_TOKEN`

### Baostock
- Free, no configuration needed
- Used as backup data source

### YFinance
- Free, no configuration needed
- Supports US/HK stock data
- US stock historical and real-time data both use YFinance exclusively to avoid technical indicator errors from akshare's US stock adjustment issues

---

## Advanced Features

### Hong Kong Stock Support

Use `hk` prefix for HK stock codes:

```bash
STOCK_LIST=600519,hk00700,hk01810
```

### Multi-Model Switching

Configure multiple models, system auto-switches:

```bash
# Gemini (primary)
GEMINI_API_KEY=xxx
GEMINI_MODEL=gemini-3.1-pro-preview

# OpenAI compatible (backup)
OPENAI_API_KEY=xxx
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
# deepseek-chat / deepseek-reasoner remain compatible, but DeepSeek marks them deprecated after 2026/07/24
```

### Advanced Model Routing (Powered by LiteLLM)

See [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md). Most users only need to think in terms of primary models, fallback models, and channels; this section is for expert users who want direct access to the underlying [LiteLLM](https://github.com/BerriAI/litellm) routing capabilities. No separate Proxy service is required.

**Two-layer mechanism**: Same-model multi-key rotation (Router) and cross-model fallback are independent.

**Multi-key + cross-model fallback example**:

```env
# Primary: 3 Gemini keys rotate; Router switches on 429
GEMINI_API_KEYS=key1,key2,key3
LITELLM_MODEL=gemini/gemini-3.1-pro-preview

# Cross-model fallback: when all primary keys fail, try Claude → GPT
# Requires ANTHROPIC_API_KEY, OPENAI_API_KEY
LITELLM_FALLBACK_MODELS=anthropic/claude-sonnet-4-6,openai/gpt-5.4-mini
```

> ⚠️ `LITELLM_MODEL` must include provider prefix (e.g. `gemini/`, `anthropic/`, `openai/`). Legacy `GEMINI_MODEL` (no prefix) is only used when `LITELLM_MODEL` is not set.

**Vision model (image stock code extraction)**: See [LLM Config Guide - Vision](LLM_CONFIG_GUIDE_EN.md#41-vision-model-image-stock-code-extraction).

### Debug Mode

```bash
python main.py --debug
```

Log file locations:
- Regular logs: `logs/stock_analysis_YYYYMMDD.log`
- Debug logs: `logs/stock_analysis_debug_YYYYMMDD.log`

Debug logs keep the app's own DEBUG messages, but LiteLLM internals default to `WARNING` to avoid token-level third-party noise during streaming generation. To inspect LiteLLM internals temporarily, set `LITELLM_LOG_LEVEL=DEBUG` in `.env`.

### SQLite Write Stability

For file-based SQLite databases, the app now enables `WAL` and sets `busy_timeout` on connection startup. `save_daily_data()` also uses a batch atomic upsert on `(code, date)` to reduce lock contention during bulk writes and concurrent callbacks.

You can tune the behavior in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SQLITE_WAL_ENABLED` | `true` | Enable `journal_mode=WAL` for file-based SQLite |
| `SQLITE_BUSY_TIMEOUT_MS` | `5000` | SQLite lock wait timeout in milliseconds |
| `SQLITE_WRITE_RETRY_MAX` | `3` | Max retries for `database is locked` / `database table is locked` errors |
| `SQLITE_WRITE_RETRY_BASE_DELAY` | `0.1` | Base backoff delay in seconds for exponential write retries |

---

## Backtesting

The backtesting module automatically validates historical AI analysis records against actual price movements, evaluating the accuracy of analysis recommendations.

### How It Works

1. Selects `AnalysisHistory` records past the cooldown period (default 14 days)
2. Fetches daily bar data after the analysis date (forward bars)
3. Infers expected direction from the operation advice and compares against actual movement
4. Evaluates stop-loss/take-profit hit conditions and simulates execution returns
5. Aggregates into overall and per-stock performance metrics

### Operation Advice Mapping

| Operation Advice | Position | Expected Direction | Win Condition |
|-----------------|----------|-------------------|---------------|
| Buy / Add / Strong Buy | long | up | Return >= neutral band |
| Sell / Reduce / Strong Sell | cash | down | Decline >= neutral band |
| Hold | long | not_down | No significant decline |
| Wait / Observe | cash | flat | Price within neutral band |

### Configuration

Set the following variables in `.env` (all optional, have defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKTEST_ENABLED` | `true` | Whether to auto-run backtest after daily analysis |
| `BACKTEST_EVAL_WINDOW_DAYS` | `10` | Evaluation window (trading days) |
| `BACKTEST_MIN_AGE_DAYS` | `14` | Only backtest records older than N days to avoid incomplete data |
| `BACKTEST_ENGINE_VERSION` | `v1` | Engine version, used to distinguish results when logic is updated |
| `BACKTEST_NEUTRAL_BAND_PCT` | `2.0` | Neutral band threshold (%), ±2% treated as range-bound |

### Auto-run

Backtesting triggers automatically after the daily analysis flow completes (non-blocking; failures do not affect notifications). It can also be triggered manually via API.

### Evaluation Metrics

| Metric | Description |
|--------|-------------|
| `direction_accuracy_pct` | Direction prediction accuracy (expected direction matches actual) |
| `win_rate_pct` | Win rate (wins / (wins + losses), excludes neutral) |
| `avg_stock_return_pct` | Average stock return percentage |
| `avg_simulated_return_pct` | Average simulated execution return (including SL/TP exits) |
| `stop_loss_trigger_rate` | Stop-loss trigger rate (only counts records with SL configured) |
| `take_profit_trigger_rate` | Take-profit trigger rate (only counts records with TP configured) |

---

## Local WebUI Management Interface

The WebUI and FastAPI API share the same service process. After startup, use the browser workspace for configuration management, manual analysis, task progress, historical reports, backtesting, portfolio management, and smart import. Authentication, cloud-server access, and API usage details are covered below.

### FastAPI API Service

FastAPI provides RESTful API service for configuration management and triggering analysis.

### Startup Methods

| Command | Description |
|------|------|
| `python main.py --serve` | Start API service + run full analysis once |
| `python main.py --serve-only` | Start API service only, manually trigger analysis |

### Features

- **Configuration Management** - View/modify watchlist
- **Quick Analysis** - Trigger analysis via API
- **Real-time Progress** - Analysis task status updates in real-time, supports parallel tasks; the regular stock-analysis path now prefers LiteLLM streaming during the LLM stage and pushes finer-grained `message/progress` updates through task SSE
- **Backtest Validation** - Evaluate historical analysis accuracy, query direction win rate and simulated returns
- **API Documentation** - Visit `/docs` for Swagger UI

### API Endpoints

| Endpoint | Method | Description |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | Trigger stock analysis |
| `/api/v1/analysis/tasks` | GET | Query task list |
| `/api/v1/analysis/tasks/stream` | GET (SSE) | Subscribe to realtime task updates |
| `/api/v1/analysis/status/{task_id}` | GET | Query task status |
| `/api/v1/history` | GET | Query analysis history |
| `/api/v1/usage/summary?period=today|month|all` | GET | Query LLM call counts and token usage grouped by call type and model |
| `/api/v1/backtest/run` | POST | Trigger backtest |
| `/api/v1/backtest/results` | GET | Query backtest results (paginated) |
| `/api/v1/backtest/performance` | GET | Get overall backtest performance |
| `/api/v1/backtest/performance/{code}` | GET | Get per-stock backtest performance |
| `/api/health` | GET | Health check |
| `/docs` | GET | API Swagger documentation |

> Note: `POST /api/v1/analysis/analyze` supports only one stock when `async_mode=false`; batch `stock_codes` requires `async_mode=true`. The async `202` response returns a single `task_id` for one stock, or an `accepted` / `duplicates` summary for batch requests.

> Progress-stream note: `GET /api/v1/analysis/tasks/stream` now emits `task_progress` in addition to `task_created / task_started / task_completed / task_failed`. The regular analysis path updates `progress` and `message` across quote preparation, news retrieval, context assembly, LLM generation, and report persistence. Streaming chunks are accumulated only on the server side; history is persisted only after the final JSON parses successfully. If streaming is unavailable before the first chunk, the system falls back to the previous non-stream request. If a stream fails after partial output has already arrived, the system first retries non-stream for the same model, then continues through existing fallback models in the original order (primary + fallback list).
> If a progress callback fails, the analysis flow continues, and the exception is now logged at warning level to help troubleshoot SSE delivery gaps.

> Note: This behavior is documented in the full guide (`full-guide*.md`) because it is detailed runtime SSE/fallback behavior and is therefore kept out of the README.

**Usage examples**:
```bash
# Health check
curl http://127.0.0.1:8000/api/health

# Trigger analysis (A-shares)
curl -X POST http://127.0.0.1:8000/api/v1/analysis/analyze \
  -H 'Content-Type: application/json' \
  -d '{"stock_code": "600519"}'

# Query task status
curl http://127.0.0.1:8000/api/v1/analysis/status/<task_id>

# Query today's LLM usage
curl "http://127.0.0.1:8000/api/v1/usage/summary?period=today"

# Trigger backtest (all stocks)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'

# Trigger backtest (specific stock)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"code": "600519", "force": false}'

# Query overall backtest performance
curl http://127.0.0.1:8000/api/v1/backtest/performance

# Query per-stock backtest performance
curl http://127.0.0.1:8000/api/v1/backtest/performance/600519

# Paginated backtest results
curl "http://127.0.0.1:8000/api/v1/backtest/results?page=1&limit=20"
```

### Custom Configuration

Modify default port or allow LAN access:

```bash
python main.py --serve-only --host 0.0.0.0 --port 8888
```

### Supported Stock Code Formats

| Type | Format | Examples |
|------|------|------|
| A-shares | 6-digit number | `600519`, `000001`, `300750` |
| BSE (Beijing) | 8/4/92 prefix, 6-digit | `920748`, `838163`, `430047` |
| HK stocks | hk + 5-digit number | `hk00700`, `hk09988` |

### Notes

- Browser access: `http://127.0.0.1:8000` (or your configured port)
- After analysis completion, notifications are automatically pushed to configured channels
- This feature is automatically disabled in GitHub Actions environment

---

## FAQ

### Q: Push messages getting truncated?
A: WeChat Work/Feishu have message length limits, system already auto-segments messages. For complete content, configure Feishu Cloud Document feature.

### Q: Data fetch failed?
A: AkShare uses scraping mechanism, may be temporarily rate-limited. System has retry mechanism configured, usually just wait a few minutes and retry.

### Q: How to add watchlist stocks?
A: Modify `STOCK_LIST` environment variable, separate multiple codes with commas.

### Q: GitHub Actions not executing?
A: Check if Actions is enabled, and if cron expression is correct (note it's UTC time).

---

## Portfolio Web Notes

### Manual FX refresh on `/portfolio`

- The FX status card on the Web `/portfolio` page includes a manual refresh action.
- The button calls the existing `POST /api/v1/portfolio/fx/refresh` endpoint and reloads snapshot/risk data only.
- If upstream FX fetch fails, the page may still remain stale after refresh and will explain the fallback result inline.
- When `PORTFOLIO_FX_UPDATE_ENABLED=false`, the refresh API returns an explicit disabled status and the page shows that online FX refresh is disabled instead of implying that no refreshable pairs exist.
- Portfolio snapshot `positions[]` now includes price metadata such as `price_source`, `price_date`, `price_stale`, and `price_available`. Today's snapshot uses the historical close first and only falls back to realtime quotes when no close exists, while historical `as_of` snapshots stay on historical-close semantics and no longer silently treat cost basis as the current price. Missing-price positions are marked with `price_available=false` and excluded from market value / unrealized PnL totals.

## Agent Tool Data Cache And Persistence

- `get_daily_history` first tries to reuse local `stock_daily` daily-bar cache; when the cache is fresh and contains at least the dashboard default of 30 records, it avoids another external data-source request.
- If Agent asks for more days than the local cache contains, the tool returns the available records and marks the response with `partial_cache=true`, `requested_days`, and `actual_records`.
- When the cache is missing or stale, the tool keeps the original data-source fetch path; successful fetches are written back to `stock_daily` on a best-effort basis, and write failures do not block the Agent response.
- `search_stock_news` and `search_comprehensive_intel` persist successful results to `news_intel` on a best-effort basis, reusing the existing URL / fallback-key deduplication logic.
- `get_realtime_quote` does not use `stock_daily` as a realtime-quote cache and does not write intraday quotes into the daily-bar table; realtime quote caching should use a dedicated realtime store if needed.

## Agent Event Monitor

When `AGENT_EVENT_MONITOR_ENABLED=true`, schedule mode polls the rules in `AGENT_EVENT_ALERT_RULES_JSON` every `AGENT_EVENT_MONITOR_INTERVAL_MINUTES` minutes and sends triggered alerts through the existing notification channels. The runtime currently supports three rule types:

> Compatibility and rollback note: this section documents current Event Monitor rule behavior (including `price_change_percent`) and does not change external model/provider API semantics such as model names, providers, Base URL, LiteLLM, `OPENAI_*`, `DEEPSEEK_*`, or `GEMINI_*` configuration.
> Rollback is explicit: clear or disable `AGENT_EVENT_MONITOR_ENABLED`/related rule config to restore previous behavior.

| `alert_type` | Direction | Threshold | Description |
| --- | --- | --- | --- |
| `price_cross` | `above` / `below` | `price` | Current price crosses a fixed threshold |
| `price_change_percent` | `up` / `down` | `change_pct` | Intraday change percentage reaches a threshold |
| `volume_spike` | - | `multiplier` | Latest volume exceeds the recent 20-day average by this multiplier |

Example:

```env
AGENT_EVENT_MONITOR_ENABLED=true
AGENT_EVENT_MONITOR_INTERVAL_MINUTES=5
AGENT_EVENT_ALERT_RULES_JSON=[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":3.0},{"stock_code":"000858","alert_type":"volume_spike","multiplier":2.5}]
```

---

For more questions, please [submit an Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
