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
  <img src="assets/secret_config.png" alt="GitHub Secrets Configuration" width="600">
</div>

#### AI Model Configuration (Configure at Least One)

| Secret Name | Description | Required |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC) API key, one key for popular LLMs and Chinese-optimized web search with free quota for this project | Recommended |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API key, one key for multiple model families and a 10% top-up discount for this project | Recommended |
| `GEMINI_API_KEY` | Get free key from [Google AI Studio](https://aistudio.google.com/) | Optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | Optional |
| `OPENAI_API_KEY` | OpenAI-compatible API Key (supports DeepSeek, Qwen, etc.) | Optional |
| `OPENAI_BASE_URL` | OpenAI-compatible API endpoint (e.g., `https://api.deepseek.com`) | Optional |
| `OPENAI_MODEL` | Model name (e.g., `deepseek-v4-flash`) | Optional |

> *Note: Configure at least one model key or channel. Anspire or AIHubMix is the simplest starting point for one-key multi-model access. Startup validation reports a clear error when no usable AI model key or model channel is configured.

#### Notification Channels (Multiple can be configured, all will receive notifications)

> The notification channel matrix, minimal/advanced key split, generated Actions mapping, `--check-notify` CLI behavior, Web one-click notification test, and local / Docker / GitHub Actions / Desktop setup notes are tracked in [Notification Guide](notifications.md).

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
| `NTFY_URL` | Full ntfy topic endpoint, must include topic path, e.g. `https://ntfy.sh/my-topic` | Optional |
| `NTFY_TOKEN` | Optional ntfy Bearer Token | Optional |
| `GOTIFY_URL` | Gotify server base URL, without `/message`; the sender appends `/message` | Optional |
| `GOTIFY_TOKEN` | Gotify application token sent with the `X-Gotify-Key` header | Optional |
| `CUSTOM_WEBHOOK_URLS` | Custom Webhook (supports DingTalk, etc., comma-separated) | Optional |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | Bearer Token for custom webhooks (for authenticated webhooks) | Optional |
| `CUSTOM_WEBHOOK_BODY_TEMPLATE` | Custom Webhook JSON body template for AstrBot, NapCat, or self-hosted services with special payloads | Optional |
| `WEBHOOK_VERIFY_SSL` | HTTPS certificate verification for webhook-style notification requests that read this setting (default true). Set to false for self-signed certs. WARNING: Disabling has serious security risk (MITM), use only on trusted internal networks | Optional |

> *Note: Configure at least one channel; multiple channels will all receive notifications. Startup validation reports missing paired Telegram / email fields and common Webhook URLs that do not start with `http://` or `https://`.
>
> The default `00-daily-analysis.yml` in this repository only exports fixed Secret / Variable names. Arbitrary numbered env vars such as `STOCK_GROUP_1` and `EMAIL_GROUP_1` are not auto-injected into the job, so grouped email routing is not available in the stock workflow unless you explicitly extend the workflow's `env:` mapping in your own fork. Actions now maps `CUSTOM_WEBHOOK_BODY_TEMPLATE`, `WEBHOOK_VERIFY_SSL`, `FEISHU_WEBHOOK_SECRET`, `FEISHU_WEBHOOK_KEYWORD`, `PUSHPLUS_TOPIC`, `NTFY_URL`, `NTFY_TOKEN`, `GOTIFY_URL`, `GOTIFY_TOKEN`, the P3 notification route keys, and the P4 notification noise-control keys; `MARKDOWN_TO_IMAGE_CHANNELS` and `MERGE_EMAIL_NOTIFICATION` remain behavior toggles outside the default workflow mapping.

#### Push Behavior Configuration

| Secret Name | Description | Required |
|------------|------|:----:|
| `SINGLE_STOCK_NOTIFY` | Single stock push mode: set to `true` to push immediately after each stock analysis | Optional |
| `REPORT_TYPE` | Report type: `simple` (concise), `full` (complete), `brief` (3-5 sentences), Docker recommended: `full` | Optional |
| `REPORT_LANGUAGE` | Report output language: `zh` (default Chinese) / `en` (English) / `ko` (Korean); also updates prompt instructions, templates, notification fallbacks, and fixed copy in the Web report view. `ko` reuses the English structural scaffolding and constrains the model to Korean output via an output-language directive; notifications render localized labels by report language. The bundled `00-daily-analysis.yml` already maps this variable, so setting it in Actions Secrets/Variables works out of the box | Optional |
| `REPORT_SHOW_LLM_MODEL` | Whether notification report footers show the LLM model used for analysis. Defaults to `true`; set to `false` to hide runtime model metadata. This switch only affects presentation and does not change provider/model/Base URL, LiteLLM routing, or runtime model save/migration/cleanup behavior. | Optional |
| `REPORT_TEMPLATES_DIR` | Jinja2 template directory (relative to project root, default `templates`) | Optional |
| `REPORT_RENDERER_ENABLED` | Enable Jinja2 template rendering (default `false`, zero regression) | Optional |
| `REPORT_INTEGRITY_ENABLED` | Enable report integrity checks, retry or placeholder on missing fields (default `true`) | Optional |
| `REPORT_INTEGRITY_RETRY` | Integrity retry count (default `1`, `0` = placeholder only) | Optional |
| `REPORT_HISTORY_COMPARE_N` | History signal comparison count, `0` off (default), `>0` enable | Optional |
| `ANALYSIS_DELAY` | Delay between stock analysis and market review (seconds) to avoid API rate limits, e.g., `10` | Optional |
| `SAVE_CONTEXT_SNAPSHOT` | Whether to persist analysis-history `context_snapshot`; defaults to `true`. Set to `false` or use `--no-context-snapshot` to stop persisting the full snapshot | Optional |
| `NOTIFICATION_REPORT_CHANNELS` | Report route channels for single-stock, aggregate daily, market review, merged push, and Feishu document success notifications. Empty means all configured channels | Optional |
| `NOTIFICATION_ALERT_CHANNELS` | Alert route channels for EventMonitor notifications. Empty means all configured channels | Optional |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | Reserved system_error route channels. No automatic system error producer is added in P3; empty means all configured channels | Optional |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | Dedup TTL in seconds. `0` disables dedup; the same stable dedup key sends only once within the TTL | Optional |
| `NOTIFICATION_COOLDOWN_SECONDS` | Cooldown window in seconds. `0` disables cooldown; the same cooldown key is rate-limited within the window | Optional |
| `NOTIFICATION_QUIET_HOURS` | Quiet-hours window in `HH:MM-HH:MM` format, supports overnight ranges. Empty disables quiet hours | Optional |
| `NOTIFICATION_TIMEZONE` | IANA timezone for quiet hours, e.g. `Asia/Shanghai`. Empty follows `TZ` or the local system timezone | Optional |
| `NOTIFICATION_MIN_SEVERITY` | Minimum severity: `info`, `warning`, `error`, `critical`. Empty keeps current behavior | Optional |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | Reserved daily digest flag. The current implementation does not send or persist digests | Optional |

> Compatibility note: `REPORT_SHOW_LLM_MODEL` keeps the previous default-visible behavior (`true`) and only changes report footer rendering. It does not alter provider/model/Base URL, LiteLLM routing, or runtime model persistence/migration/cleanup semantics. Rollback is to remove the variable or set it back to `true`.

> `REPORT_LANGUAGE` only affects report text and report page fixed copy. Web UI chrome language (navigation, login, settings, shell labels, shared controls) is intentionally independent and stored in browser `localStorage` as `dsa.uiLanguage`.
> UI language resolution is: explicit localStorage value (`zh` or `en`) -> browser language (`navigator.languages` / `navigator.language`) -> default `zh`.

#### Other Configuration

| Secret Name | Description | Required |
|------------|------|:----:|
| `STOCK_LIST` | Watchlist codes, e.g., `600519,300750,002594,7203.T,005930.KS` | ✅ |
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/) optimized for Chinese content; the same key can also be used for Anspire LLM fallback scenarios (example model: `Doubao-Seed-2.0-lite`) | Recommended |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) search-engine results for realtime financial news | Recommended |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) Search API (for news search) | Optional |
| `BOCHA_API_KEYS` | [Bocha Search](https://open.bocha.cn/) Web Search API (Chinese search optimized, supports AI summaries, multiple keys comma-separated) | Optional |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API (privacy-first, US-stock news enrichment, comma-separated for multiple keys) | Optional |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimax.io/) Coding Plan Web Search (structured search results) | Optional |
| `SEARXNG_BASE_URLS` | SearXNG self-hosted instances (quota-free fallback, enable format: json in settings.yml); when empty the app auto-discovers public instances | Optional |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Auto-discover public SearXNG instances from `searx.space` when `SEARXNG_BASE_URLS` is empty (default `true`) | Optional |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638) Token | Optional |
| `TICKFLOW_API_KEY` | [TickFlow](https://tickflow.org) API key for optional A-share daily K-lines, realtime quotes, stock list/name lookup, and CN market review enhancement; permission or entitlement failures fall back to existing providers | Optional |

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
> Compatibility note for Issue #1306: this change only persists and exposes existing market-review output via history paths, and does not alter model name, provider, base URL, LiteLLM cleanup rules, or `.env` runtime migration semantics. Rollback is to revert this change set. Runtime compatibility references are `requirements.txt` (`litellm` constraints), `docs/LLM_CONFIG_GUIDE_EN.md`, and regression tests in `tests/test_analysis_api_contract.py`, `tests/test_analysis_history.py`, `tests/test_market_review.py`; official references: [LiteLLM OpenAI-compatible](https://docs.litellm.ai/docs/providers/openai_compatible), [OpenAI Chat Completion API](https://platform.openai.com/docs/api-reference/chat).
> Phase 3 compatibility note for #1815: this change only narrows JP/KR vs Market Light runtime boundaries. It does not add new provider/model/base URL migration logic, and it does not change `.env` model persistence semantics. `MarketSymbol`, alert market enums, and snapshot `data_quality/limitations` are boundary-contract updates only.

| Variable | Description | Default | Required |
|--------|------|--------|:----:|
| `GENERATION_BACKEND` | Generation backend for regular analysis. Supports `litellm` or explicit opt-in `codex_cli` (experimental/limited) | `litellm` | No |
| `GENERATION_FALLBACK_BACKEND` | Backend-level fallback. Unset defaults to `litellm`; an empty value disables fallback; self fallback resolves to no-op | `litellm` | No |
| `GENERATION_BACKEND_TIMEOUT_SECONDS` | Per-call generation backend timeout in seconds, mainly for local CLI backends; range `1-3600` | `300` | No |
| `GENERATION_BACKEND_MAX_OUTPUT_BYTES` | Total captured diagnostic stdout/stderr plus final-response size limit for one local CLI backend call; final responses duplicated to stdout by `--output-last-message` are not counted twice; range `1-33554432` | `1048576` | No |
| `GENERATION_BACKEND_MAX_CONCURRENCY` | Global generation backend concurrency cap; range `1-16`, does not change LiteLLM Router or `MAX_WORKERS` behavior | `1` | No |
| `LOCAL_CLI_BACKEND_MAX_CONCURRENCY` | Local CLI backend concurrency cap; range `1-4`, effective concurrency is the lower of this value and `GENERATION_BACKEND_MAX_CONCURRENCY` | `1` | No |
| `AGENT_GENERATION_BACKEND` | Agent Chat generation backend. Web settings only expose `auto|litellm`; hand-written `codex_cli` returns an unsupported tool-calling diagnostic | `auto` | No |
| `LITELLM_MODEL` | Primary model, format `provider/model` (e.g. `gemini/gemini-3.1-pro-preview`), recommended | - | No |
| `AGENT_LITELLM_MODEL` | Optional Agent-only primary model; when empty it inherits the primary model, and bare names are normalized to `openai/<model>` | - | No |
| `LITELLM_FALLBACK_MODELS` | Fallback models, comma-separated | - | No |
| `LLM_CHANNELS` | Channel names (comma-separated), use with `LLM_{NAME}_*`, see [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md) | - | No |
| `LLM_HERMES_API_KEY` | Single API key for the reserved Hermes local HTTP generation channel; provide it through `.env`, runtime config, or Secrets only | - | Required for Hermes |
| `LLM_HERMES_BASE_URL` | Hermes local loopback `/v1` endpoint; defaults to `http://127.0.0.1:8642/v1`; remote endpoints are not supported | `http://127.0.0.1:8642/v1` | No |
| `LLM_HERMES_MODELS` | Raw Hermes model list; Phase 3 defaults to `hermes-agent`, maps to runtime route `openai/hermes-agent`, and does not support Vision, stream, tools, or Agent tools | `hermes-agent` | No |
| `LITELLM_CONFIG` | Advanced model routing YAML path (expert use) | - | No |
| `LLM_USAGE_HMAC_SECRET` | Secret for LLM usage telemetry message HMACs; leave empty to use a generated local data-dir secret file | - | No |
| `LLM_USAGE_HMAC_KEY_VERSION` | Version label for the LLM usage HMAC key; update it when rotating the secret | `local-v1` | No |
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

> GitHub Actions note: the bundled `00-daily-analysis.yml` explicitly uses `litellm` when `GENERATION_FALLBACK_BACKEND` is not configured, so an unset Secret/Variable is not exported as an empty value that disables backend fallback. To disable backend fallback in Actions, set the fallback to the primary backend and let the resolver treat it as self no-op.

> *Note: Configure at least one of `ANSPIRE_API_KEYS`, `AIHUBMIX_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_API_BASE`, or `LLM_CHANNELS` / `LITELLM_CONFIG`. `ANSPIRE_API_KEYS` and `AIHUBMIX_KEY` are auto-adapted without an `OPENAI_BASE_URL`.

### Notification Channel Configuration

For the notification baseline, diagnostics, and deployment notes, see [Notification Guide](notifications.md).

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
| `WEBHOOK_VERIFY_SSL` | HTTPS certificate verification for webhook-style notification requests that read this setting (default true). Set to false for self-signed certs. WARNING: Disabling has serious security risk | Optional |
| `PUSHOVER_USER_KEY` | Pushover User Key | Optional |
| `PUSHOVER_API_TOKEN` | Pushover API Token | Optional |
| `NTFY_URL` | Full ntfy topic endpoint, must include topic path, e.g. `https://ntfy.sh/my-topic` | Optional |
| `NTFY_TOKEN` | Optional ntfy Bearer Token | Optional |
| `GOTIFY_URL` | Gotify server base URL, without `/message` | Optional |
| `GOTIFY_TOKEN` | Gotify application token sent with `X-Gotify-Key` | Optional |
| `PUSHPLUS_TOKEN` | PushPlus Token (Chinese push service) | Optional |
| `SERVERCHAN3_SENDKEY` | ServerChan v3 Sendkey | Optional |
| `ASTRBOT_URL` | AstrBot Webhook URL | Optional |
| `ASTRBOT_TOKEN` | Optional AstrBot Bearer Token | Optional |
| `NOTIFICATION_REPORT_CHANNELS` | Report route channels, comma-separated. Allowed values: wechat,feishu,telegram,email,pushover,ntfy,gotify,pushplus,serverchan3,custom,discord,slack,astrbot | Optional |
| `NOTIFICATION_ALERT_CHANNELS` | Alert route channels, comma-separated. Empty keeps all configured channels | Optional |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | Reserved system_error route channels, comma-separated. Empty keeps all configured channels | Optional |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | Dedup TTL in seconds. `0` disables dedup | Optional |
| `NOTIFICATION_COOLDOWN_SECONDS` | Cooldown window in seconds. `0` disables cooldown | Optional |
| `NOTIFICATION_QUIET_HOURS` | Quiet-hours window in `HH:MM-HH:MM` format, supports overnight ranges | Optional |
| `NOTIFICATION_TIMEZONE` | Quiet-hours timezone, e.g. `Asia/Shanghai`; empty follows `TZ` or local system timezone | Optional |
| `NOTIFICATION_MIN_SEVERITY` | Minimum severity: info, warning, error, critical. Empty keeps current behavior | Optional |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | Reserved daily digest flag. It does not send digests yet | Optional |

> Note: the default `00-daily-analysis.yml` GitHub Actions workflow only maps fixed variable names. It does not automatically import arbitrary numbered variables such as `STOCK_GROUP_N` / `EMAIL_GROUP_N`. This feature therefore works in local `.env`, Docker, or any runtime where you explicitly inject those variables.

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
> Note: `FEISHU_APP_ID` / `FEISHU_APP_SECRET` are for Feishu app mode, cloud documents, or Stream Bot mode. They do not enable group webhook notifications by themselves. For simple group push notifications, use `FEISHU_WEBHOOK_URL` first.
>
> Supplement: When `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_CHAT_ID` are all configured, they enable the Feishu App Bot active notification channel without relying on group webhooks. `FEISHU_RECEIVE_ID_TYPE` defaults to `chat_id`; set it to `open_id` for P2P delivery. This uses the Feishu OpenAPI Bot session route, which is independent of the group webhook path.

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
| `TICKFLOW_API_KEY` | TickFlow API key; enables optional A-share daily K-lines, realtime quotes, stock list/name lookup, and CN market review enhancement. Permission failures fall back to existing providers. | - | Optional |
| `TICKFLOW_PRIORITY` | TickFlow daily K-line provider priority; lower values are tried earlier. No effect unless `TICKFLOW_API_KEY` is configured. Does not affect realtime quotes, which are ordered by `REALTIME_SOURCE_PRIORITY`. | `2` | Optional |
| `TICKFLOW_KLINE_ADJUST` | TickFlow daily K-line adjustment mode: `none`, `forward`, `backward`, `forward_additive`, or `backward_additive`. | `none` | Optional |
| `TICKFLOW_BATCH_DAILY_ENABLED` | Enable TickFlow batch daily K-line prefetch when the current plan supports it; permission failures are negative-cached and fall back to per-stock providers. | `true` | Optional |
| `TICKFLOW_BATCH_SIZE` | Maximum symbols per TickFlow batch request for daily K-lines and realtime quotes. | `100` | Optional |
| `ENABLE_REALTIME_QUOTE` | Enable real-time quotes (if disabled, uses historical closing prices for analysis) | `true` | Optional |
| `ENABLE_REALTIME_TECHNICAL_INDICATORS` | Intraday real-time technicals: Calculate MA5/MA10/MA20 and bull trends using real-time prices when enabled (Issue #234); uses yesterday's close if disabled. | `true` | Optional |
| `ENABLE_CHIP_DISTRIBUTION` | Enable chip distribution analysis (this API is unstable, recommended to disable for cloud deployment). GitHub Actions users must set `ENABLE_CHIP_DISTRIBUTION=true` in Repository Variables to enable; disabled by default in workflows. | `true` | Optional |
| `ENABLE_EASTMONEY_PATCH` | Eastmoney API patch: Recommended to set to `true` when Eastmoney APIs fail frequently (e.g., RemoteDisconnected, connection closed). Injects NID tokens and random User-Agents to reduce rate limiting probability. | `false` | Optional |
| `REALTIME_SOURCE_PRIORITY` | Real-time quote source priority (comma-separated), e.g., `tencent,akshare_sina,efinance,akshare_em`; add `tickflow` explicitly to use TickFlow realtime quotes | See .env.example | Optional |
| `ENABLE_FUNDAMENTAL_PIPELINE` | Master switch for fundamental aggregation; when disabled, returns `not_supported` block only, without altering the original analysis pipeline. | `true` | Optional |
| `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS` | Total latency budget for the fundamental stage (seconds) | `8.0` | Optional |
| `FUNDAMENTAL_FETCH_TIMEOUT_SECONDS` | Timeout for a single capability source call (seconds) | `3.0` | Optional |
| `FUNDAMENTAL_RETRY_MAX` | Retry count for fundamental capabilities (including the first attempt) | `1` | Optional |
| `FUNDAMENTAL_CACHE_TTL_SECONDS` | Fundamental aggregation cache TTL (seconds), short cache to reduce repeated API pulling. | `120` | Optional |
| `FUNDAMENTAL_CACHE_MAX_ENTRIES` | Maximum entries for fundamental cache (evicted by time within TTL) | `256` | Optional |

> **Behavior Notes:**
> - **A-shares**: Returns aggregated capabilities by `valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards`.
> - **ETFs**: Returns available items, marks missing capabilities as `not_supported`, and does not affect the original flow overall.
> - **US/HK stocks**: Returns `valuation/growth/earnings/belong_boards` (sourced from `info.sector`/`info.industry`) via the yfinance adapter; `institution/capital_flow/dragon_tiger/boards` stay `not_supported` because no offshore data feed exists today. Falls back to a full `not_supported` block if yfinance is unavailable or returns empty payloads. Still fail-open.
> - **Japanese/Korean stocks**: Current MVP uses Yfinance daily/basic quote coverage only; `institution`, `capital_flow`, `dragon_tiger`, and `boards` are not fully supported and degrade to `not_supported` (see [market boundaries](market-support.md)).
> - Any exception uses fail-open logic, only logs errors without affecting the main technical/news/chip pipeline.
> - **Field contracts**:
>   - `fundamental_context.belong_boards` = related board list for the stock; A-shares are sourced from AkShare board membership, US/HK from yfinance `info.sector`/`info.industry`, `[]` when unavailable;
>   - `fundamental_context.boards.data` = `sector_rankings` (sector rise/fall leaderboard, structure `{top, bottom}`; not provided for US/HK today);
>   - `fundamental_context.concept_boards.data` = `concept_rankings` (concept/theme rise/fall leaderboard, structure `{top, bottom}`; currently A-share only and omitted or empty on fail-open);
>   - `fundamental_context.earnings.data.financial_report.currency` = financial statement currency (`info.financialCurrency`; HK ADRs commonly report CNY here);
>   - `fundamental_context.earnings.data.dividend.currency` = trading / dividend currency (`info.currency`; HK ADRs use HKD here even when the statement currency is CNY). The renderer reads each block's own currency rather than assuming a single global currency;
>   - `fundamental_context.earnings.data.dividend.ttm_dividend_yield_pct` = `ttm_cash_dividend_per_share / latest_price * 100`, both sides in the trading currency. Falls back to `info.trailingAnnualDividendYield` (decimal) or `info.dividendYield` (already-percent passthrough) only when TTM cash or latest price is unavailable;
>   - `get_stock_info.belong_boards` = list of sectors the individual stock belongs to;
>   - `get_stock_info.boards` is a compatibility alias, value is identical to `belong_boards` (removal considered only in major version updates);
>   - `get_stock_info.sector_rankings` stays consistent with `fundamental_context.boards.data`.
>   - `AnalysisReport.details.belong_boards` = related board list in structured report details;
>   - `AnalysisReport.details.sector_rankings` = sector leaderboard in structured report details for board-linkage display.
>   - `AnalysisReport.details.concept_rankings` = concept/theme leaderboard in structured report details for Web related-board signal matching and notification table type labels.
> - **Sector leaderboard** uses a fixed fallback order: consistent with global priority.
> - **Timeout control** is a `best-effort` soft timeout: the stage will quickly degrade and continue execution based on the budget, but does not guarantee a hard interrupt of underlying third-party network calls.
> - `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS=8.0` indicates the target budget for the newly added fundamental stage, not a strict hard SLA; Windows, Docker, or rate-limited free data sources can raise it to `12-15s`.
> - For a hard SLA, please upgrade to isolated child process execution in future versions to forcefully terminate timeout tasks.

### Other Configuration

| Variable | Description | Default |
|--------|------|--------|
| `STOCK_LIST` | Watchlist codes (comma-separated) | - |
| `MAX_WORKERS` | Concurrent threads | `3` |
| `MARKET_REVIEW_ENABLED` | Enable market review | `true` |
| `DAILY_MARKET_CONTEXT_ENABLED` | Inject the daily market context into stock-analysis prompts and soften aggressive buy advice in high-risk/risk-off markets; enabled by default, and market review can still run when this is set to `false` | `true` |
| `MARKET_REVIEW_REGION` | Market review region: cn (A-shares), hk (HK stocks), us (US stocks), jp (JP stocks), kr (KR stocks), both (all five markets) | `cn` |
| `MARKET_REVIEW_COLOR_SCHEME` | Index change color style in market reviews: `green_up` = green gains/red losses (default), `red_up` = red gains/green losses | `green_up` |
| `SCHEDULE_ENABLED` | Enable scheduled tasks | `false` |
| `SCHEDULE_TIME` | Scheduled execution time | `18:00` |
| `SCHEDULE_TIMES` | Multiple scheduled execution times, comma-separated; falls back to `SCHEDULE_TIME` when empty | empty |
| `SCHEDULE_RUN_IMMEDIATELY` | Run once immediately when scheduler mode starts; when unset it keeps following the legacy `RUN_IMMEDIATELY` runtime override | `true` |
| `RUN_IMMEDIATELY` | Run once immediately for non-scheduler startup; also acts as the legacy fallback when `SCHEDULE_RUN_IMMEDIATELY` is unset | `true` |
| `LOG_DIR` | Log directory | `./logs` |
| `SAVE_CONTEXT_SNAPSHOT` | Persist analysis-history `context_snapshot`. When false, new history records do not save enhanced_context, market_phase_summary, AnalysisContextPack overview, or diagnostic snapshots, but current-run prompt summaries remain enabled | `true` |

> Behavior notes:
> - When `TICKFLOW_API_KEY` is configured, TickFlow is instantiated as an optional A-share daily K-line data source and CN market-review enhancer. `TICKFLOW_PRIORITY` only affects the daily K-line/general provider fallback chain. Realtime quote priority is controlled separately by `REALTIME_SOURCE_PRIORITY`; TickFlow realtime quotes are used only when that list explicitly includes `tickflow`, and any source listed before `tickflow` is tried first.
> - TickFlow daily K-lines default to `TICKFLOW_KLINE_ADJUST=none`; daily `volume` is converted from lots to shares, while `amount` remains in yuan.
> - TickFlow daily K-line range requests pass explicit `start_time` / `end_time` / `count`. Because the official quickstart documents that time-range queries are still limited by `count`, non-empty count-capped responses whose first returned trading date is later than the requested start trading date are rejected before normalization or cache writes, allowing manager fallback to continue.
> - Batch analysis can warm the per-process TickFlow daily K-line cache through `prefetch_daily_klines()` before per-stock `get_daily_data()` calls. Only validated frames are cached; batch permission failures are negative-cached and degrade to single-stock requests or existing providers.
> - TickFlow behavior is capability-based rather than just key-based: limited plans can still enhance main CN indices, while plans with `CN_Equity_A` universe query support also enhance market breadth and stock-list/name lookups.
> - The official quickstart documents `quotes.get(universes=["CN_Equity_A"])`, but online smoke tests confirmed two additional real-world constraints: universe access depends on plan permissions, and `quotes.get(symbols=[...])` has a per-request symbol limit.
> - TickFlow currently returns `change_pct` / `amplitude` / `turnover_rate` as ratio values; this integration normalizes them to the project's percent convention so they match AkShare / Tushare / efinance semantics.
> - In scheduler mode, if runtime env explicitly sets `RUN_IMMEDIATELY` but does not set `SCHEDULE_RUN_IMMEDIATELY`, the scheduler keeps inheriting the legacy runtime override instead of being pulled back to a persisted `.env` alias value.

> Compatibility note (Issue #1815): `MARKET_REVIEW_REGION=cn|hk|us|jp|kr|both` only expands the market set used by market review; `jp`/`kr` are for recap scope and do not open JP/KR for Market Light alerts.
> - Changes in `src/config.py`, `src/core/config_registry.py`, and `src/services/system_config_service.py` are configuration-contract updates only, and do not alter runtime provider/model/base URL routing semantics or trigger provider migration/cleanup logic.
> - Affected config keys are `MARKET_REVIEW_REGION` and `MARKET_REVIEW_COLOR_SCHEME`; existing model/runtime keys (`LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `VISION_MODEL`, `OPENAI_BASE_URL`, etc.) remain unchanged under the existing atomic upsert semantics and are not silently cleared when this scope is changed.
> - Verifiable evidence summary: official provider / Base URL / model-name sources remain the [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md#official-references-for-provider-presets--base-urls--model-naming), and the locked runtime dependency window remains `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` in `requirements.txt`; this scope adds no migration script or cleanup branch, and save/import still writes only submitted keys. `tests/test_system_config_service.py::SystemConfigServiceTestCase::test_update_market_review_region_does_not_trigger_runtime_model_cleanup` covers saving `MARKET_REVIEW_REGION` without clearing or rewriting existing `LITELLM_CONFIG`, `LLM_CHANNELS`, `LLM_OPENAI_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `VISION_MODEL`, `OPENAI_*`, and related runtime settings.
> - Rollback is a restore-and-recover path: apply pre-PR `.env` / config backup for the above keys, restore `MARKET_REVIEW_REGION`, and restart the runtime; or revert this PR directly.
> - CN market review reports now use a post-market workstation layout with market signal, index detail, sector Top tables, news catalysts, next-session plan, and risk sections. The market signal uses a plain-text score such as `66/100 (constructive, risk-on)` instead of block bars so it renders consistently across terminals and notification clients. News catalysts list only headline, source, and link instead of search snippets to reduce mixed-language noise. Missing data sources degrade by omitting or simplifying only the affected block.
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

The default Compose file sets `limits.memory: 1G` and `reservations.memory: 512M` for each service. Use `512M` only for lightweight Web/API usage, single-stock runs, and low concurrency with `MAX_WORKERS=1`; use `1G` for normal full analysis, and `2G+` when running `server + analyzer` together, multi-stock analysis, market review, news expansion, image reports, or AlphaSift. If constrained to `512M`, avoid starting both services and reduce heavy features.

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
  zhulinsen/daily_stock_analysis:latest \
  python main.py --serve-only --host 0.0.0.0 --port 8000

# Scheduled-task mode
docker run -d \
  --name dsa-analyzer \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
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
    - ../strategies:/app/strategies:ro
  deploy:
    resources:
      limits:
        memory: 1G
      reservations:
        memory: 512M

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

For both `docker run` and Compose, keep startup environment injection separate from runtime file writes:

- Environment injection: `--env-file .env` or Compose `env_file`
  This passes key/value pairs from `.env` into the container process environment.
- Runtime config writes: do not bind-mount the host `.env` as a single file over the container's `.env` path. Docker treats the target as a mount point, so the `os.replace()` atomic update used during config saves can fail with `Device or resource busy`; fallback in-place writes can also fail on permissions.

The default Compose and `docker run` examples only use `env_file` / `--env-file` for startup config injection and no longer mount the host `.env` file into the container. When the active `.env` file does not contain a key, the WebUI Settings page falls back to showing the same key from startup-injected process environment variables, so Docker users can see injected config without importing it first. The raw `.env` export still contains only the active config file content.

Runtime config saved from the WebUI is written to the container-local config file by default and is not the same as writing back to the host `.env`; after deleting or recreating the container, startup still uses the injected `.env` file. If you need persistent runtime config, point `ENV_FILE` at a writable data volume file such as `/app/data/runtime.env` instead of using a single-file `.env` bind mount. Note that same-name values still present in startup `env_file`, `--env-file`, `docker run -e`, or Compose `environment:` can override the runtime file on restart; update or remove those startup overrides if you want WebUI-saved values to take over.

Recommended host mappings:

- `./data:/app/data` for runtime data and database files
- `./logs:/app/logs` for logs
- `./reports:/app/reports` for generated reports
- `./strategies:/app/strategies:ro` for custom strategy YAML files

Official Docker images automatically create and fix ownership for the `/app/data`, `/app/logs`, and `/app/reports` mounts during startup, then drop privileges to the non-root `dsa` user inside the container (UID/GID `1000:1000`). Normal Docker / Compose deployments do not require manual host-side `chown` or `chmod`.

If you override the runtime user with `--user` or Compose `user:`, or use read-only mounts, rootless Docker, NFS, or another storage environment that blocks `chown`, the automatic repair may not apply. In that case, make sure the actual runtime user can write to `data`, `logs`, and `reports`, or use writable volumes.

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

On Windows PowerShell, if Python or pip still uses the system default code page, enable UTF-8 before the first dependency install or environment check. This keeps terminal output and third-party tooling from failing on non-ASCII text:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -m pip install -r requirements.txt
python scripts/check_env.py --config
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

Edit `.github/workflows/00-daily-analysis.yml`:

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
> When the built-in scheduler is started via `python main.py --schedule` or an equivalent CLI-only mode, saving a new `SCHEDULE_TIME` / `SCHEDULE_TIMES` from the WebUI will rebind the daily jobs on the next scheduler poll without restarting the process. The previous trigger times are removed instead of being kept alongside the new ones. `python main.py --serve --schedule` is owned by the Web/API runtime scheduler, so long-running WebUI/API/Desktop processes start, stop, or rebuild the runtime scheduler after saving `SCHEDULE_ENABLED`, `SCHEDULE_TIME`, or `SCHEDULE_TIMES`.
>
> The Web/API runtime scheduler run-now endpoint only accepts a request when no analysis is already running; if an analysis is in progress, it returns a busy response instead of reporting a queued run.

### Market Phase Baseline (Issue #1386 P0)

P0 only adds an internal market-phase inference baseline. It does not change the existing daily post-market report, trading-day skip behavior, effective trading date resolution, API, Web, Bot, Agent, or GitHub Actions defaults. The phase inference is preparation for the P1+ context contract. If `exchange-calendars` is unavailable or the calendar lookup fails, the phase returns `unknown`; the existing trading-day filter and effective-date helpers keep their current fail-open behavior.

The phase labels describe regular-session state:

| Phase | Meaning |
| --- | --- |
| `premarket` | Before the regular session opens; does not mean extended-hours quotes were fetched |
| `intraday` | Inside the regular session and outside lunch break or the near-close window |
| `lunch_break` | Lunch break window supplied by the market calendar; markets without lunch breaks skip this phase |
| `closing_auction` | Near-close heuristic window: 3 minutes for CN, 10 minutes for HK, and 5 minutes for US; this is not a full exchange auction model |
| `postmarket` | After the regular session closes; does not mean post-market quotes were fetched |
| `non_trading` | The current market-local date is not a trading session |
| `unknown` | Unknown market, calendar unavailable, or calendar error, so the phase cannot be inferred reliably |

Current entrypoint baseline:

- Regular stock analysis, Agent analysis, Web manual analysis, Bot `/analyze` / `/ask`, schedule mode, and GitHub Actions still use the existing analysis path and post-market recap wording. P0 does not switch prompts or output schema automatically.
- Market review still follows `MARKET_REVIEW_REGION` and trading-day filtering; it does not consume market phase labels.
- Mixed-market watchlists should infer phase per symbol market. Displaying inconsistent phases in aggregate reports is left to P1+.

Known problem baseline:

- Intraday runs can still describe unfinished intraday data like a complete daily recap.
- Output may still focus on "today's recap / watch tomorrow" instead of current intraday observation.
- Quote timestamp, source, cache, and stale state are not yet unified into a phase context.
- Lunch break, near-close, and forced non-trading-day runs are not yet explicit in prompts or report structure.

P0 does not connect this baseline to pipeline / Agent / API / Web / Bot, does not change report schemas, does not change alert technical-indicator partial-bar handling, and does not add configuration keys.

### Runtime Market Phase Context (Issue #1386 P1a)

P1a constructs and passes an internal `market_phase_context` through the regular stock-analysis pipeline, the legacy Agent context, and multi-agent `ctx.meta`. The context includes market, phase, market-local date, effective daily-bar date, trading-day / market-open / partial-bar tristate flags, best-effort open/close minute estimates, and degradation warning codes such as `unknown_market`, `calendar_unavailable`, and `calendar_error`.

P1a itself does not change prompt wording, API/Web/Bot parameters, report schemas, stable history/task-status metadata, or quote freshness/data quality semantics. Regular history snapshots and Agent history snapshots strip this runtime-only field. P1b is left to define persistent metadata and task-status display contracts.

### Market Phase Low-Sensitivity Metadata (Issue #1386 P1b)

P1b projects the P1a runtime `market_phase_context` into a stable, low-sensitivity, public `market_phase_summary` and stores it at the top level of `analysis_history.context_snapshot`. History detail, sync analysis responses, and completed `/api/v1/analysis/status/{task_id}` responses return the same market-phase metadata at `report.meta.market_phase_summary`; completed task status does not add a top-level `TaskStatus` field and only exposes it through `status.result.report.meta.market_phase_summary`.

`market_phase_summary` only contains market, phase, market-local time, session date, effective daily-bar date, trading-day / market-open / partial-bar flags, open/close minute estimates, trigger source, analysis intent, and warning codes. It does not expose the full `market_phase_context`, and it does not add quote freshness, fallback, stale, or data-quality scoring fields. `report.details.analysis_context_pack_overview` remains the #1389 input data-block quality overview. API `details.context_snapshot` strips the top-level `market_phase_summary` and `analysis_context_pack_overview` so raw snapshots do not duplicate these stable public fields. When `SAVE_CONTEXT_SNAPSHOT=false`, the full `analysis_history.context_snapshot` is not persisted; when older history records lack the summary, the field is empty and the report still loads.

P1b does not change prompts, does not add an `analysis_phase` request parameter, does not add Web phase labels or rendering, and does not cover pending/processing TaskPanel state, in-progress SSE events, Bot, notifications, `market_review`, or P3 intraday data-quality fields.

### Market Phase Prompt Injection (Issue #1386 P2-min)

P2-min starts rendering the runtime market phase into an LLM-readable prompt section for analysis paths that already receive `market_phase_context`. Regular analysis, single Agent, and multi-agent prompts can now see the current phase, market-local time, latest reusable complete daily-bar date, and the minimal phase constraints: pre-market runs must not describe today's price action as already happened, intraday / lunch-break / near-close runs must treat the latest daily bar as potentially unfinished, post-market runs can keep the complete-session recap style, and non-trading or unknown phases should stay conservative.

P2-min still does not add API/Web/Bot parameters, persist phase into history/task status/report metadata, change report JSON schemas, or introduce the full quote freshness, fallback, stale, or data-quality contract. Bot/API direct Agent entrypoints that do not go through the P1a pipeline to build `market_phase_context` keep their previous behavior; entrypoint propagation and visible labels are left to later P4+ work.

### Intraday Data Packet and Realtime Quality Control (Issue #1386 P3)

P3 adds realtime quote quality metadata for the regular analysis path, but still does not add an `analysis_phase` parameter, change API/Web/Bot phase entrypoints, change report JSON schemas, or implement #1389 P5 data-quality scoring or model confidence limits. Realtime quotes may carry `fetched_at`, `provider_timestamp`, `is_stale`, `stale_seconds`, and `fallback_from`; `fetched_at` is the system fetch time, while `provider_timestamp` is only populated when the provider actually returns a quote timestamp. If provider time is unavailable, the system does not fabricate freshness, and `stale_seconds` / `is_stale` stay empty.

Whole-source fallback semantics are fixed: `source` keeps the actual successful provider token, while `fallback_from` records the highest-priority whole source that failed in the current attempt; if the primary source succeeds and later providers only supplement missing fields, `fallback_from` is not set. `AnalysisContextBuilder` only maps these upstream artifacts, performs no extra fetches, and does no quality scoring; quote block status collapses as `STALE > FALLBACK > AVAILABLE`. When realtime price overlays `today`, the pipeline marks `is_partial_bar`, `is_estimated`, `estimated_fields`, `realtime_source`, and quote metadata. The `daily_bars` block still represents the complete daily-bar window in storage; partial/estimated markers only enter the technical block. Freshness scoring, intraday cache TTL tiers, Agent tool-level reuse, and API/Web display remain follow-ups.

### Analysis Phase Entrypoint and Task Queue Pass-Through (Issue #1386 P4a)

P4a adds an `analysis_phase=auto|premarket|intraday|postmarket` request parameter, defaulting to `auto`, so API callers can explicitly override the phase for the current analysis. The parameter is wired through `POST /api/v1/analysis/analyze`, the async task queue, `AnalysisService`, the regular analysis pipeline, and market-phase context construction. Web frontend types and API mapping accept the field, but this phase does not add a page selector; Bot, schedule, GitHub Actions, and DB migrations remain out of scope.

`analysis_phase` is the requested override value; the final report phase remains `report.meta.market_phase_summary.phase`. Async accepted responses, in-memory task status, task list responses, and SSE payloads echo the requested phase. DB history fallback does not add a persisted phase field, so older records may still return it empty. Duplicate detection remains stock-only, so the same stock submitted with different phases is still treated as a duplicate in-flight task.

Market-phase context construction still supports the legacy internal `analysis_intent` argument: only when `analysis_phase` remains `auto`, a non-`auto` `analysis_intent` is normalized as the requested phase for this run. External callers should prefer `analysis_phase`.

`auto` preserves existing calendar inference. Non-`auto` values only override the phase and recompute `is_trading_day`, `is_market_open_now`, `is_partial_bar`, `minutes_to_open`, and `minutes_to_close`. The override does not rewrite the real `market_local_time` or `effective_daily_bar_date`; if the current date is not a trading session or the calendar cannot support the session, minute fields may be empty.

### Web Phase Labels (Issue #1386 P4b)

P4b completes the Web visibility slice without adding a phase override selector. The in-progress TaskPanel only shows the requested `analysis_phase` echoed by P4a; in the current task-panel UI, `auto` is explicitly labeled as the requested automatic phase (`请求阶段: 自动阶段`) and is not presented as the final inferred phase. The final report page renders the actual market phase from `report.meta.market_phase_summary.phase`, and shows a `Partial bar` marker when `is_partial_bar=true`.

Data-quality visibility continues to reuse `report.details.analysis_context_pack_overview.data_quality` and the existing `AnalysisContextSummary` component. The Web UI only displays the phase label alongside the low-sensitivity data-quality summary; it does not expose the full `AnalysisContextPack`, prompt summary, raw payloads, or stripped snapshot internals. History-list fields, Bot, schedule, GitHub Actions, Desktop, notification summaries, and advanced phase override UI remain follow-up work.

### AnalysisContextPack Prompt Summary (Issue #1389 P3)

P3 injects a low-sensitivity `AnalysisContextPack` summary into regular analysis and Agent initial prompts. The pipeline builds the pack from already-fetched quote, daily-bar, trend, chip, fundamentals, news, and market-phase artifacts, then passes `analysis_context_pack_summary` downstream; in this new pack-summary section, the LLM only sees subject, version, data-block status/source/warnings/missing reason, and news result count, not full `news.content`, `trend_result`, chip, or fundamentals raw payloads through that section. On the Agent path, the pipeline reads `storage.get_analysis_context()` once after history prefetch to drive the daily-bars status, and marks `daily_bars_missing` only when that read has no usable context. Existing `news_context`, Agent pre-fetched JSON, and `enhanced_context` raw-payload channels keep their pre-P3 behavior and are not replaced or sanitized by this summary.

P3 itself did not add API/Web/Bot parameters, persist fields into history/task status/report metadata, change report JSON schemas, or expose the full pack through history, notifications, or Web surfaces. Agent tool-level reuse of pack data and P5 data-quality scoring are left to later phases.

### AnalysisContextPack Low-Sensitivity Visibility (Issue #1389 P4)

P4 adds `report.details.analysis_context_pack_overview`. History detail and completed `/api/v1/analysis/status/{task_id}` responses read the same low-sensitivity overview from the persisted `context_snapshot`; sync analysis responses also extract the overview from the just-persisted `analysis_history.context_snapshot`, so new records do not guarantee this field when `SAVE_CONTEXT_SNAPSHOT=false`. The Web report page renders a collapsed data-block summary after Strategy and News, with available/missing counts, non-zero other status counts, and trigger source in the header and data-block status, source, warnings, missing reasons, status counts, and news result count after expansion. API `details.context_snapshot` strips the top-level `analysis_context_pack_overview` so the raw snapshot panel does not duplicate the public overview.

The overview does not include the full pack, the `analysis_context_pack_summary` prompt string, `items.value`, news body text, `trend_result`, chip, or fundamentals raw payloads. When `SAVE_CONTEXT_SNAPSHOT=false`, the full `analysis_history.context_snapshot` is not persisted, so new history records cannot provide the overview; older records without the overview keep returning an empty field and the report still loads. This phase does not cover pending/processing TaskPanel, in-progress SSE events, notification summaries, Bot/Desktop-specific rendering, `market_review` overview, or data-quality scoring.

### AnalysisContextPack Data Quality Scoring and Prompt Limitations (Issue #1389 P5)

P5 adds lightweight data-quality scoring and model-readable data limitations to `AnalysisContextPack` without changing `PACK_VERSION = "1.0"`, adding data sources, or changing the report JSON schema. `ContextFieldStatus` now includes `fetch_failed`, which only means a field or data block explicitly failed to fetch in this run; the first mapping only turns `fundamental_context.status == "failed"` into `fetch_failed`, while empty news, unconfigured search, missing realtime quote, or missing chip data keep the existing `missing` / `not_supported` semantics.

`DataQuality` now contains `overall_score`, `level`, `block_scores`, and `limitations`, while preserving the old `warnings` / `metadata` fields. Scoring is fixed to six blocks: `quote`, `daily_bars`, `technical`, `news`, `fundamentals`, and `chip`; auxiliary missing blocks are not re-normalized away. When core blocks are degraded, the prompt's `Data Limitations` section tells the model not to return high confidence; missing auxiliary blocks only constrain their matching analysis sections and must not be interpreted as bullish or bearish. The section is generated by `format_analysis_context_pack_prompt_section()`, so regular analysis, single Agent, and multi-agent paths reuse the same low-sensitivity summary without exposing raw payloads, news body text, raw trend values, secrets, tokens, or webhooks.

History detail, sync analysis responses, and completed task status responses still expose only `report.details.analysis_context_pack_overview`; P5 only adds a nested `data_quality` object with score, level, block_scores, and limitations, and does not duplicate `warnings`. The Web report page remains collapsed by default, adds quality score/level to the header, and shows limitations plus `fetch_failed` status after expansion; API `details.context_snapshot` continues to strip the top-level `analysis_context_pack_overview`.

### AnalysisContextPack Documentation, Migration, and Rollback (Issue #1389 P6)

P6 is a documentation and configuration-visibility closure only. It does not add pack runtime behavior, does not add a pack enable/disable feature flag, does not change `PACK_VERSION = "1.0"`, does not add API parameters, does not change the report JSON schema, and does not run a database migration. See the [AnalysisContextPack topic document](analysis-context-pack.md) for the full contract, field states, low-sensitivity visibility, redaction boundary, migration notes, and rollback path.

`SAVE_CONTEXT_SNAPSHOT` is an existing environment variable; P6 only exposes it through `.env.example`, the config registry, and Web settings help. It defaults to `true`. When set to `false`, or when the CLI uses `--no-context-snapshot`, new history records no longer persist the full `analysis_history.context_snapshot`, including `enhanced_context`, `market_phase_summary`, `analysis_context_pack_overview`, diagnostic snapshots, and raw snapshot fields. This setting does not disable current-run `AnalysisContextPack` construction, does not remove the low-sensitivity `analysis_context_pack_summary` from prompts, and does not change report JSON schemas or API request parameters.

There is no runtime pack master switch. Disabling the P3-P5 pack prompt summary, overview, or data-quality integration requires a release rollback or code rollback. Older history records without `analysis_context_pack_overview` / `data_quality` continue to return empty fields and remain readable.

### Intraday Decision Guardrails and Quality Checks (Issue #1386 P5)

P5 adds a phase-aware decision block under `dashboard.phase_decision` for individual stock analysis reports: `phase_context`, `action_window`, `immediate_action`, `watch_conditions`, `next_check_time`, `confidence_reason`, and `data_limitations`. This is a backward-compatible report JSON addition stored in historical `raw_result`; it does not add an `analysis_phase` API parameter, change Web phase entrypoints, add configuration, or change the default post-market daily review behavior.

Regular analysis and Agent analysis now apply lightweight guardrails before history is saved, using the current `market_phase_summary` and `analysis_context_pack_overview.data_quality`. If core quote / daily_bars / technical data is stale, fallback, missing, fetch_failed, partial, or estimated, high-confidence conclusions are capped. Pre-market, non-trading, or unknown phases must not emit high-confidence intraday buy/sell actions. Intraday, lunch-break, and near-close outputs are scanned for post-market recap wording such as "after today's close" or "focus tomorrow" in the main conclusion and action fields, and obvious violations are replaced with phase-safe wait/watch wording. The guardrail only fills low-sensitivity `phase_context` and data limitations; it does not invent watch conditions or next-check times. Notification summaries, alerts, holdings, and backtest linkage remain later P6 work.

### Signal Attribution Analysis (Issue #1742)

Issue #1742 adds a signal attribution analysis block under `dashboard.signal_attribution` for individual stock analysis reports: `technical_indicators`, `news_sentiment`, `fundamentals`, `market_conditions` (four contribution values; valid non-zero values are normalized to 100; all-zero means no effective signal), `strongest_bullish_signal`, and `strongest_bearish_signal`. This field explains the composition of recommendation reasons, helping users understand the attribution weights of AI decisions.

Signal attribution analysis is rendered in all report paths:
- `generate_dashboard_report()` (default notification report)
- `generate_single_stock_report()` (single-stock push report)
- `templates/report_markdown.j2` (Jinja2 template)
- `HistoryService._generate_single_stock_markdown()` (Web history drawer)

Normalization functions are explicitly called in `_parse_response()` and `parse_dashboard_json()` to ensure:
- String percentages are converted to int (e.g., `"35%"` → `35`)
- Negative numbers are clamped to 0
- Non-zero valid values with sum ≠ 100 are normalized to sum = 100
- All-zero values are preserved as 0 to mean no effective signal
- Values are clamped to [0, 100]

`signal_attribution` is an optional display field, not a required integrity field. Missing it does not fail integrity checks, is not recorded in the `missing` list, and does not trigger a completion prompt; when present, it is normalized and rendered by supported report paths.

### Alerts, Portfolio, and History Linkage (Issue #1386 P6)

P6 reuses the existing `market_phase_summary` and `analysis_context_pack_overview` across alerts, portfolio, history, backtesting, and notifications. It does not introduce a new phase/pack protocol and does not require a database migration. Alert trigger rows keep using the existing text `diagnostics` field; when diagnostics can be represented as JSON, the worker merges `analysis_visibility.market_phase_summary`, `analysis_visibility.analysis_context_pack_overview`, and `analysis_visibility.source` into triggered rows. Legacy plain-text diagnostics remain readable; Alert API derived fields stay empty and `analysis_visibility_source=legacy_text`.

Alert phase summaries are generated from trigger-time context: symbol targets infer the stock market, `target_scope=market` uses the `cn|hk|us|jp|kr` region directly, and account-level targets that cannot map to a single market may fall back to `unknown`. The pack overview only comes from an evaluator-provided overview or a recent low-sensitivity history snapshot from the last 30 days. Missing data returns `null`; the alert worker does not fabricate packs and does not automatically run a lightweight LLM analysis. Public source values are `alert_trigger_market_context`, `analysis_history_snapshot`, `evaluator_snapshot`, `legacy_text`, or `null`.

The portfolio page adds a manual per-position analysis action backed by `POST /api/v1/portfolio/positions/{symbol}/analysis`. The request accepts `account_id`, `analysis_phase=auto|premarket|intraday|postmarket`, and `force`. Only non-zero current holdings can be submitted; missing holdings return 404, and the same symbol held in multiple accounts without `account_id` returns `400 ambiguous_position_account`. The endpoint keeps the existing async accepted / duplicate semantics, and `force` only controls refresh behavior; it does not bypass in-flight duplicate detection. The backend passes only a low-sensitivity `portfolio_context` internally into the pipeline and into an optional context-pack `portfolio` block. That block does not affect the six existing data-quality weights and is not exposed through task lists or SSE payloads.

History lists, same-stock history, StockBar items, and details extract `market_phase_summary` from `context_snapshot`; old rows, missing snapshots, or parse failures return `null`. Backtest result items now include `market_phase` and `market_phase_summary`, and result/performance/summary queries support `analysis_phase=premarket|intraday|postmarket|unknown`. Statistics fold `intraday`, `lunch_break`, and `closing_auction` into intraday, and fold `non_trading`, missing, and invalid values into unknown. Phase-filtered backtest queries batch-read results and snapshots through the repository, bucket before pagination, and expose `phase_breakdown` plus `raw_phase_counts` in summary diagnostics.

Notification summaries use one public formatting helper and only include the phase label, trigger source, partial-bar warning, data-quality level, and the first two limitations. They do not output raw context packs, prompts, news body text, or sensitive portfolio details. The Web Alerts, Portfolio, History, StockBar, and Backtest pages display the new phase badges, quality summary, phase filter, and breakdown.

### Documentation, Configuration, And Migration Notes (Issue #1386 P7)

P7 is a user-facing documentation closeout for pre-market / intraday / post-market analysis only. It does not add runtime behavior, configuration keys, API parameters, database migrations, a Web phase override selector, Bot phase parameters, or a GitHub Actions intraday workflow. The default daily post-market analysis, default GitHub Actions run, and existing schedule behavior stay unchanged.

Recommended usage:

| Scenario | Recommended Use | Notes |
| --- | --- | --- |
| Pre-market | Build an opening plan and watch conditions | Do not describe today's not-yet-traded price action as fact; focus on the last complete trading day, overnight information, and opening triggers. |
| Intraday / lunch break / near close | Check live state, risk, and opportunity alerts | Focus on current price, realtime quote freshness, partial bars, data limitations, and next watch conditions. This does not replace the full post-market review. |
| Post-market | Keep the full review and next-day plan | Uses complete trading-day semantics and is closest to the default daily-analysis scenario. |

Entrypoints and visibility:

| Entrypoint | Phase Behavior |
| --- | --- |
| `POST /api/v1/analysis/analyze` | Supports `analysis_phase=auto|premarket|intraday|postmarket`; omitted values default to `auto`. |
| Web main analysis / re-analysis / portfolio manual analysis | There is currently no phase override selector. The frontend defaults to `auto`, the in-progress task panel shows the requested phase, and the final report page shows the final phase label. |
| Bot / CLI / schedule / default GitHub Actions | Do not pass `analysis_phase`; they continue to use `auto` inference, and the default post-market behavior is unchanged. |
| History / backtest / notifications / alerts | Only consume public `market_phase_summary` and low-sensitivity `analysis_context_pack_overview`; they do not expose the full pack, prompt summary, news body text, or sensitive portfolio details. |

`analysis_phase` is the requested override value, while the final report phase remains `report.meta.market_phase_summary.phase`. Older callers that omit `analysis_phase` remain compatible. Older history rows without `market_phase_summary` or `analysis_context_pack_overview` return empty fields and still load normally. Backtest queries support `analysis_phase=premarket|intraday|postmarket|unknown` filtering, and P6 folds lunch-break and near-close phases into intraday.

`SAVE_CONTEXT_SNAPSHOT=false` or CLI `--no-context-snapshot` only stops persisting the full `context_snapshot` for new history rows, so new history no longer exposes persisted phase summary / pack overview / diagnostics snapshot data. It does not disable current-run `AnalysisContextPack` construction, does not remove the low-sensitivity `analysis_context_pack_summary` from prompts, and does not change the report JSON schema. Callers that need output closer to the old post-market wording can temporarily pin `analysis_phase=postmarket`; fully removing the P0-P6 phase/pack runtime integration requires a release rollback or code rollback.

---

## Notification Channel Configuration

The notification channel matrix and `--check-notify` CLI details are documented in [Notification Guide](notifications.md).

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
4. `FEISHU_APP_ID` / `FEISHU_APP_SECRET` are for Feishu app / Stream Bot / cloud document flows only. They do **not** trigger group webhook notifications and must not be used alone instead of `FEISHU_WEBHOOK_URL`.
5. If `FEISHU_APP_ID` / `FEISHU_APP_SECRET` are configured together with `FEISHU_CHAT_ID`, the Feishu App Bot can push notifications directly to a specified chat or user, no group webhook required. `FEISHU_RECEIVE_ID_TYPE` defaults to `chat_id`; set it to `open_id` for P2P delivery. This uses the Feishu OpenAPI Bot session route, independent of the group webhook path.
6. The App Bot send path reuses the existing `lark-oapi>=1.0.0` dependency already listed in `requirements.txt`; standard source installs, Docker, the GitHub Actions daily workflow, and desktop builds all install it through `pip install -r requirements.txt`. References: [Feishu message create OpenAPI](https://open.feishu.cn/document/server-docs/im-v1/message/create), [lark-oapi PyPI](https://pypi.org/project/lark-oapi/), [SDK repo](https://github.com/larksuite/oapi-sdk-python).

**Common failure causes:**
- Only `FEISHU_APP_ID` / `FEISHU_APP_SECRET` were set, with neither `FEISHU_WEBHOOK_URL` nor the App Bot active-delivery target `FEISHU_CHAT_ID` configured
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

> GitHub Actions limitation: as of 2026-03-29, the repository's default `00-daily-analysis.yml` does not auto-import arbitrary numbered `STOCK_GROUP_N` / `EMAIL_GROUP_N` variables. If you only add them in repository Secrets / Variables without extending the workflow `env:` block, they will not reach the runtime process.

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
`CUSTOM_WEBHOOK_BODY_TEMPLATE`. This is a global template and is rendered before
URL auto-detected payloads such as Bark, Slack, or Discord. If the rendered value
is not a JSON object, DSA falls back to the default payload. Prefer
`$content_json` / `$title_json` so newlines and quotes stay valid JSON:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"msg_type":"text","content":$content_json}
```

Available placeholders: `$content_json`, `$content`, `$title_json`, `$title`.
Raw `$content` / `$title` are not JSON-escaped, so quotes or newlines can make
the template invalid and trigger fallback.

In Docker Compose deployments, saving this value from Web Settings writes these
app placeholders as `$$content_json` / `$$title_json` and restores the single
`$` form at runtime, preventing Compose from expanding them to empty values. If
you edit the Docker `.env` manually, use the same `$$content_json` style.

Bark stays on the custom webhook baseline; no `BARK_*` settings are required.
Set the Bark endpoint in `CUSTOM_WEBHOOK_URLS`. When using Bark with a global
template, include the Bark body explicitly:

```env
CUSTOM_WEBHOOK_URLS=https://api.day.app/YOUR_BARK_KEY
```

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"body":$content_json,"group":"stock"}
```

NapCat / OneBot examples must be adjusted for your actual endpoint, `user_id`,
or `group_id`:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"user_id":123456,"message":$content_json}
```

### ntfy / Gotify

ntfy and Gotify are first-class notification channels. They send text / JSON
only and do not use Markdown-to-image.

ntfy uses the full topic endpoint; the last path segment is treated as the
topic:

```env
NTFY_URL=https://ntfy.sh/my-topic
NTFY_TOKEN=
```

Gotify uses the server base URL. The sender appends the fixed `/message` API and
sends the application token in the `X-Gotify-Key` header. `GOTIFY_URL` may
include a reverse-proxy path prefix, but must not include `/message`:

```env
GOTIFY_URL=https://gotify.example
GOTIFY_TOKEN=app-token
```

```env
# Actual request URL: https://example.com/gotify/message
GOTIFY_URL=https://example.com/gotify
GOTIFY_TOKEN=app-token
```

`NTFY_URL` and `GOTIFY_URL` intentionally use different URL semantics because
the two services expose different APIs: ntfy topics are part of the endpoint,
while Gotify uses `/message` as a fixed server API.

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

### Longbridge
- Optional fallback for US/HK stocks, mainly used to supplement fields that YFinance may miss
- New integrations should use Longbridge OAuth 2.0: the client id is read from `LONGBRIDGE_OAUTH_CLIENT_ID`, or from `LONGBRIDGE_APP_KEY` when no Legacy Access Token is configured; run `python scripts/generate_longbridge_oauth_token.py --client-id <client_id>` once on an interactive machine to generate the SDK token cache
- For GitHub Actions / Docker headless runs, base64 the local `~/.longbridge/openapi/tokens/<client_id>` file and store it as `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64`
- OAuth runtime support requires SDK APIs `OAuthBuilder` and `Config.from_oauth`; if a Linux/Docker environment can only install the older SDK, the app logs a clear warning and skips Longbridge while keeping YFinance / AkShare fallback available
- Legacy API Key remains supported with `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, and `LONGBRIDGE_ACCESS_TOKEN`; this Access Token is the legacy API-key credential, not an OAuth access token
- Optional knobs: `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` (default `86400`) and `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` (default `15`)
- If credentials are absent, the optional Longbridge fetcher is not instantiated
- When runtime errors such as `client is closed`, `context closed`, or `connection closed` occur, Longbridge enters a short cooldown window and US/HK daily or realtime requests automatically fall back to YFinance / AkShare instead of reconnecting on every request

---

## Advanced Features

### Hong Kong Stock Support

Use `hk` prefix for HK stock codes:

```bash
STOCK_LIST=600519,hk00700,hk01810
```

HK daily history skips efinance, pytdx, baostock, and other built-in providers that do not support HK daily data, avoiding mismatches between HK symbols and non-HK market data. AkShare/Tushare/YFinance/Longbridge continue to provide HK fallback paths. If Longbridge is inside its connection cooldown window, the route temporarily skips it and continues with the remaining HK-capable fallbacks.

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

## Decision Actionability

Single-stock reports calibrate operation advice with support/resistance, volume/chip context, main-force capital flow, and risk events. This reduces direct buy/sell flips caused only by one-day price movement or score thresholds. When price is between support and resistance and capital flow is unclear, the report prefers neutral actionable wording such as hold, range-bound watch, or shakeout watch. Buy calls require support confirmation or a valid resistance breakout with volume/capital-flow confirmation; sell/reduce calls require support failure, sustained outflow, or clearly elevated risk.
This post-processing update only adjusts advisory wording and stability logic and does not change the configured LLM model/provider routing semantics (including LiteLLM, providers, or API model settings).
Compatibility check result: decision operability and runtime post-processing paths are changed, while model/provider/API configuration and persistence semantics remain unchanged; the compatibility boundary is now in analysis/pipeline/agent intent inference and stabilization mapping.
Verification trail: the runtime behavior is implemented in `src/analyzer.py`, `src/core/pipeline.py`, `src/core/backtest_engine.py`, `src/report_language.py`, and `src/agent` decision-path modules (with corresponding tests in `tests/test_backtest_engine.py`, `tests/test_analyzer_news_prompt.py`, `tests/test_decision_stability.py`, and `tests/test_agent_pipeline.py`); it does not add/remove runtime config fields or config-cleanup logic in `src/config.py` or persistence code paths.

### Decision Action Taxonomy (#1390 P0)

Single-stock reports now keep the existing free-text `operation_advice` and add optional `action` / `action_label` fields for structured display in Web history, StockBar, same-stock history, and backtest result rows. `decision_type` remains the legacy `buy|hold|sell` statistics contract; an empty `action` does not rewrite the existing `decision_type` inference chain.

| `action` | Common source text | `decision_type` bridge |
| --- | --- | --- |
| `buy` | `strong_buy`, `强烈买入`, `buy`, `买入`, `布局`, `建仓` | `buy` |
| `add` | `add`, `加仓`, `增持`, `accumulate` | `buy` |
| `hold` | `hold`, `持有`, `持有观察`, `洗盘观察` | `hold` |
| `watch` | `watch`, `观望`, `等待`, `wait` | `hold` |
| `reduce` | `reduce`, `减仓`, `trim` | `sell` |
| `sell` | `sell`, `卖出`, `清仓`, `strong_sell`, `强烈卖出` | `sell` |
| `avoid` | `avoid`, `回避`, `规避`, `不建议买入`, `避免买入`, `do not buy` | `hold` |
| `alert` | `alert`, `风险预警`, `警惕`, `触发告警`, `risk alert` | `hold` |

The `decision_type` bridge in the table only documents compatibility between the eight-state action taxonomy and the legacy three-state statistics contract. #1390 P0 does not automatically write `action` back into the existing `decision_type`. If upstream sends both an explicit `action` and a semantically different `decision_type`, legacy statistics, backtesting, and old report semantics still follow `decision_type` / the existing inference chain; `action/action_label` remains structured display metadata.

Unknown or ambiguous advice is not coerced into `watch` or `hold`; it returns empty `action/action_label`. Web history cards, StockBar, same-stock history drawers, and backtest result rows use `operation_advice` as a display-only fallback when old records do not have `action/action_label`; that fallback affects only the UI label and is not a stable API action or future signal asset. When Web receives both `action` and `action_label`, it first renders the label from `action` in the current UI language; API `action_label` remains report-language display metadata for non-Web clients or compatibility display when `action` is absent. Market review and other non-stock reports do not emit trading `action` values and keep only the `operation_advice` text. `dashboard.phase_decision.immediate_action` belongs to the market-phase guardrail report block and is not used by the #1390 P0 eight-state action derivation. The final market phase still comes from `report.meta.market_phase_summary.phase`.

#1390 P0 does not flatten future signal-asset fields into current report summaries, history lists, StockBar rows, or backtest responses. #1390 P1 now carries more granular plan fields such as `horizon`, `plan_quality`, and `status` through an independent `DecisionSignal` resource; it still does not change the existing report contract, backfill history, or add configuration.

### Decision Signal Asset (#1390 P1/P2/P3/P4/P5)

`DecisionSignal` is an independent backend resource for persisting AI recommendations as queryable, deduplicated, status-updatable signal assets. It does not replace `operation_advice` or expand the legacy `decision_type=buy|hold|sell` contract. Starting with #1390 P2, regular stock analysis and Agent stock analysis best-effort extract one `source_type=analysis` signal from the final `AnalysisResult` after analysis history is saved successfully; explicit API and service calls remain supported. #1390 P3 adds default lifecycle handling, narrow same-source relaxed deduplication, opposite-signal invalidation, and stricter terminal-state transitions without changing the public response schema.

Automatic extraction consumes structured fields from the completed report only. It does not parse Markdown, backfill old history, add configuration, or change the main report contract. Extraction failures, unknown or ambiguous advice, non-stock reports, and unrecognized markets skip signal writes without affecting report persistence. `source_report_id` is the just-saved `AnalysisHistory.id`; `trace_id` prefers the runtime diagnostics trace and falls back to the pipeline trace or `query_id`; `stock_name` comes from `AnalysisResult.name`; `trigger_source` comes from the runtime entrypoint and falls back to `system`.

For P2 automatic extraction, `market_phase` first reads `market_phase_summary.phase` from the saved context snapshot and then falls back to `AnalysisResult.market_phase_summary.phase`; data quality first reads `analysis_context_pack_overview.data_quality` from the saved context snapshot and then falls back to `AnalysisResult.analysis_context_pack_overview.data_quality`. Price-plan extraction reuses the same sniper-point parser used by history persistence, mapping `dashboard.battle_plan.sniper_points.ideal_buy/secondary_buy/stop_loss/take_profit` to `entry_low/entry_high/stop_loss/target_price`; `ideal_buy` alone writes `entry_low`, `secondary_buy` alone writes `entry_high`, and when both are present they are sorted into `entry_low <= entry_high`. Missing stop-loss or target prices only lower the service-computed `plan_quality` instead of inventing fields. `watch_conditions` first reads `dashboard.phase_decision.watch_conditions` and then falls back to `dashboard.battle_plan.action_checklist`. `catalyst_summary` is written only when `dashboard.intelligence.positive_catalysts` exists and is a list. `confidence` uses a conservative report-level mapping: `高/high=0.8`, `中/medium/mid=0.6`, `低/low=0.4`; the original report confidence level remains in `metadata`.

Starting with P3, `DecisionSignalService` owns lifecycle defaults. Explicit `horizon` / `expires_at` values always win. When `horizon` is omitted, `alert` or `premarket/intraday/lunch_break/closing_auction` defaults to `intraday`, while `postmarket/non_trading/unknown` or missing phase context defaults to `3d`. When `expires_at` is omitted, `intraday` first uses `metadata.market_phase_summary.minutes_to_close/minutes_to_open`; without context it uses deterministic TTL fallback values (CN 4h, HK 5.5h, US 6.5h, unknown 4h). `1d/3d/5d/10d` use natural days, and `swing/long` do not auto-expire. The fallback TTL is only a no-context degradation path, not an exchange-calendar close time. Automatic extraction writes only low-sensitive `market_phase_summary.phase/session_date/minutes_to_open/minutes_to_close` hints into `metadata.market_phase_summary`; final `horizon/expires_at` values are still computed by the service.

Core fields include `stock_code`, `stock_name`, `market`, `source_type`, `source_agent`, `source_report_id`, `trace_id`, `market_phase`, `trigger_source`, `action`, `action_label`, `confidence`, `score`, `horizon`, `entry_low`, `entry_high`, `stop_loss`, `target_price`, `invalidation`, `watch_conditions`, `reason`, `risk_summary`, `catalyst_summary`, `evidence`, `data_quality_summary`, `plan_quality`, `status`, `expires_at`, `created_at`, `updated_at`, and `metadata`. `action` reuses the eight-state action taxonomy; `market_phase` reuses the market phase enum; `source_type` supports `analysis|agent|alert|market_review|manual`; `status` supports `active|expired|invalidated|closed|archived`; `horizon` supports `intraday|1d|3d|5d|10d|swing|long`.

`confidence` is `0.0-1.0`, and `score` is `0-100`, separate from historical `sentiment_score`. Price-plan fields `entry_low`, `entry_high`, `stop_loss`, and `target_price` must be finite positive numbers; when both `entry_low` and `entry_high` are present, `entry_low <= entry_high` is required. `plan_quality` supports `complete|partial|minimal|unknown`: a valid explicit value is saved as-is; otherwise the service computes it. The entry range (`entry_low` or `entry_high`) counts as one slot, and `stop_loss`, `target_price`, `invalidation`, and `watch_conditions` each count as one slot. Two slots produce `partial`, four or more produce `complete`, and action/reason without enough slots produces `minimal`.

New API endpoints:

- `POST /api/v1/decision-signals`: create or deduplicate a signal and return `{ item, created }` with HTTP 200. Exact deduplication uses `(source_report_id, source_type, market, stock_code, action, horizon, market_phase)` when `source_report_id` is present, or `(trace_id, source_type, market, stock_code, action, horizon, market_phase)` when only `trace_id` is present. Signals without either source identifier are not deduplicated. After an exact miss, a narrow relaxed fallback searches the same source plus `source_type/market/stock_code/action` and only fills old blank `horizon/market_phase` values. `horizon` can be filled only when the new value was generated by the service default; explicit different horizons or already different phases remain separate rows. When the same source key matches an expired signal and the new request is active with a future `expires_at`, the existing row is refreshed in place, still returns `created=false`, and that renewal is treated as a new active activation event. Active creation or expired renewal of a bullish signal (`buy/add`) invalidates earlier active defensive signals (`reduce/sell/avoid`) for the same stock, and the reverse also applies; active duplicate retries also rerun this repair to recover from a previous partial create where the signal was saved but invalidation failed; ordinary old duplicate/replay attempts are not treated as new activation events. `hold/watch/alert` do not trigger automatic invalidation. The API response schema is unchanged, and both refreshed and duplicate outcomes return `created=false`. P3 does not guarantee concurrent idempotency.
- `GET /api/v1/decision-signals`: paginated query with `market`, `stock_code`, `action`, `market_phase`, `source_type`, `source_report_id`, `trace_id`, `trigger_source`, `status`, time ranges, `holding_only`, and `account_id`.
- `POST /api/v1/decision-signals/outcomes/run`: explicitly trigger signal-level outcome evaluation; by default it skips completed and terminal unable rows, recomputes recoverable unable rows, and `force=true` recomputes and overwrites the current key.
- `GET /api/v1/decision-signals/outcomes`: paginated query for signal outcome rows.
- `GET /api/v1/decision-signals/outcomes/stats`: aggregate current outcome-engine stats; by default it excludes archived signals.
- `GET /api/v1/decision-signals/{signal_id}/outcomes`: list the selected signal's outcome rows for the current outcome engine.
- `GET /api/v1/decision-signals/{signal_id}/feedback`: fetch the selected signal's user feedback; missing feedback returns `feedback_value=null`.
- `PUT /api/v1/decision-signals/{signal_id}/feedback`: upsert the selected signal's latest `useful|not_useful` feedback.
- `GET /api/v1/decision-signals/{signal_id}`: fetch one signal; missing IDs return 404.
- `PATCH /api/v1/decision-signals/{signal_id}/status`: update a valid status and optional `metadata`; when `metadata` is provided it replaces the whole stored metadata object. `expired/invalidated/closed/archived` terminal states cannot be patched directly back to `active`; expired renewal still requires re-posting active data with a future `expires_at`.
- `GET /api/v1/decision-signals/latest/{stock_code}`: return latest active signals for a stock, default `limit=1`.

Read paths lazily expire active signals whose `expires_at` has passed before list, detail, and latest queries; creating an already expired active signal stores it as `expired`; the same-source expired signal can only be extended by re-posting active data with a future `expires_at`, and `PATCH /status` does not accept `expires_at`. `expired|invalidated|closed|archived` cannot be patched directly back to active, and `closed|invalidated|archived` are not reactivated by the create path. Automatic opposite-signal invalidation merges these fields into the old signal metadata: `invalidated_by_signal_id`, `invalidated_reason`, `invalidated_at`, and `previous_status`. If old metadata JSON is corrupt, it is replaced with invalidation metadata plus `metadata_replaced_due_to_invalid_json=true`, and the new signal creation is not blocked. Time fields are normalized to UTC naive datetimes for storage and comparison; timezone-aware inputs are converted to UTC and stripped of `tzinfo`, naive inputs are treated as UTC, and API responses continue to return ISO strings without timezone suffixes. Stock codes are normalized deterministically by `market`: CN variants such as `600519`, `SH600519`, and `600519.SH` match the same stored code; HK variants such as `00700`, `HK00700`, and `00700.HK` match `HK00700`; US tickers are uppercased. `holding_only=true` reads only cached `portfolio_positions` rows with `quantity > 0` under active accounts and matches signals by the held `(market, stock_code)`, optionally scoped by an active `account_id`; it does not call portfolio snapshot replay. When no cache exists, it returns an empty result and callers should refresh the cache through the portfolio snapshot API first.

`source_report_id` is nullable and is not required to reference an existing history row; deleting history records explicitly removes only history-bound signals with `source_type=analysis` whose `source_report_id` matches actually deleted IDs, so `manual/agent/alert/market_review` weak-reference signals are not deleted solely because of an ID collision. The list endpoint supports typed filters for `source_report_id` and `trace_id`. Follow-up association fields such as `task_id` and `alert_trigger_id` should be stored in `metadata` for P1; P1 does not add dedicated columns or typed filters for them, which are deferred to the later integration phase. JSON fields, long text fields, and public short text fields (`stock_name/source_agent/trigger_source/action_label`) are sanitized before persistence with a signal-specific sanitizer that redacts sensitive keys, Bearer values, Authorization/Cookie headers or assignments, token-like strings, other sensitive assignments, webhook URLs, URL userinfo, and URLs with sensitive query or fragment parameters. Ordinary evidence URLs are preserved for source traceability, and long text does not use the diagnostics 300-character truncation. `trace_id` is a same-source identity field; if it contains sensitive credentials that would be redacted, the API rejects the request instead of storing a lossy redacted value.

These endpoints inherit the existing `/api/v1/*` admin authentication middleware: when `ADMIN_AUTH_ENABLED=true`, callers must send a valid admin session cookie. DecisionSignal does not add a separate auth scheme.

#1390 P4 wires the existing `DecisionSignal` API into the Web UI without adding backend contracts, database tables, or configuration. The sidebar "AI signals" entry at `/decision-signals` is the centralized query surface for structured decision signals; the page defaults to `status=active`, supports filtering by market, stock code, action, market phase, source, source report ID, and status, and includes a latest-active lookup by stock code. Signal details show action, confidence/score, horizon, plan_quality, market_phase, price plan, risk, watch conditions, source report, and data quality. The Web UI only allows marking a signal as `closed`, `invalidated`, or `archived`; it does not restore terminal states to active.

#1390 P5 adds signal-level feedback, forward outcome evaluation, and stats sidecars. It does not extend the `decision_signals` main table and does not reuse `BacktestResult`, which is tied to `analysis_history_id`. `decision_signal_feedback` stores the latest `useful|not_useful` feedback per `signal_id` with optional reason/note/source. `decision_signal_outcomes` stores idempotent rows by `(signal_id, horizon, engine_version)`, currently `engine_version=decision-signal-v1`. Each outcome freezes `action/market/market_phase/source_type/source_agent/plan_quality/data_quality_level/holding_state` at evaluation time so historical stats are not rewritten by later live-join changes. Deleting history first finds `source_type=analysis` signals bound to the deleted history IDs, then removes their feedback/outcome sidecars.

P5 outcome evaluation supports only daily-bar-verifiable `1d/3d/5d/10d`. The window means the next 1/3/5/10 `StockDaily` bars after the anchor, not the natural-day expiration semantics from `DecisionSignalService._horizon_days()`. `anchor_date` first reads `metadata.market_phase_summary.session_date`, then falls back to `created_at.date()`; the exact anchor date must have `StockDaily.close`, with no previous-trading-day fallback. Action mapping is `buy/add -> up`, `hold -> not_down`, and `reduce/sell/avoid -> not_up`. `watch/alert`, `intraday/swing/long`, missing anchor price, and insufficient forward bars persist `eval_status=unable` with an explicit `unable_reason`. Missing/invalid anchor price, insufficient forward bars, and missing/invalid window close are recoverable unable states that default reruns will evaluate again after data arrives; non-directional actions, unsupported horizons, and missing anchor dates are terminal unable states and stay idempotently skipped by default. Automatic extraction may receive runtime `portfolio_context.quantity`; it writes only low-sensitive `holding_state=holding|empty|unknown` into metadata for outcome snapshots, never quantity, account, or cost.

P5 extends the existing Web `/decision-signals` page instead of adding a new navigation page or BacktestPage entry. The filter area now shows current outcome-engine stat cards; the details drawer lazily loads outcomes and lets the user submit useful/not useful feedback. P5 does not add a background scheduler: outcome calculation is triggered explicitly through `POST /api/v1/decision-signals/outcomes/run`. Batch runs prioritize missing outcomes first and then retry recoverable unable rows, so completed or terminal-unable newest signals do not keep consuming the `limit`.

The portfolio page loads AI signals as a non-blocking enhancement: portfolio snapshots and risk cards render first, then the page calls `GET /api/v1/decision-signals/latest/{stock_code}?market=<market>&limit=1` for each unique holding in the current snapshot to read the latest active signal. It no longer scans the generic `holding_only=true` list endpoint and has no fixed page-count cutoff. If a single latest lookup fails, the page keeps other loaded signals and shows a visible degradation warning; rows without a matching signal show an empty placeholder. Matching reuses the Web stock-code equivalence rules for CN variants such as `600519/SH600519/600519.SH`, HK variants such as `00700/HK00700/00700.HK`, and case-insensitive US tickers.

#1390 P6 reuses `DecisionSignal` across alerts, notifications, and portfolio risk without adding tables, migrations, or configuration. Real stock-level alert triggers first link the latest active signal for the same symbol and write a low-sensitive `decision_signal_summary` into `alert_triggers.diagnostics`; when no active signal exists, the worker creates only a minimal `source_type=alert`, `action=alert` signal. Its `trace_id=alert-rule-<hash>` is for best-effort retry de-duplication, not active-signal overwrites, and the payload intentionally omits `market_phase` to avoid cross-phase duplicates. Alert and analysis notifications reference only public summary fields such as `action/horizon/reason/watch_conditions/risk_summary/source_report_id`, and notification failure does not block trigger or signal writes. `GET /api/v1/portfolio/risk` now includes a `decision_signal_risk` block that counts active `sell/reduce/alert` signals for current holdings, explicitly excluding `avoid/buy/add/hold/watch`; if signal lookup fails, the risk endpoint fails open and the Web risk card shows a degraded state.

#1390 P7 is documented in [DecisionSignal Topic](decision-signals.md) (Chinese-only). P7 adds no `DECISION_SIGNAL_*` configuration, database migration, API field, or runtime switch. Rollback is to revert the related code. After rollback, signal extraction and writes stop, while report saving, alert triggering, notification sending, and the portfolio risk main flow continue through their existing paths. Historical signal, feedback, and outcome rows are not deleted automatically.

Regular stock history report details no longer embed the extracted `source_type=analysis` signals and no longer issue a `source_report_id=<recordId>` query when the report details open. To inspect structured AI recommendations, use `/decision-signals` and filter by source report ID, open the `/decision-signals?sourceReportId=<recordId>` deep link, or search by stock. When source report ID is filled or provided through that URL parameter, the Web UI sends an exact `source_type=analysis + source_report_id=<recordId>` query without adding default `status=active` or other list filters, preserving the best-effort lazy backfill semantics for older reports.

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
| Hold / Hold and Watch / Range-bound Watch / Shakeout Watch / Hold and watch | long | not_down | No significant decline |
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
- **UI Language Switch** - Toggle UI language (`zh`/`en`) on login page, shell/navigation, settings page, and shared controls; this switch is independent of `REPORT_LANGUAGE`.
- **Quick Analysis** - Trigger stock analysis via API; the Home page also provides a Market Review button that starts a background market recap in Docker/server mode
- **Strategy selection** - The Home page supports explicitly selecting analysis strategy skills; when `skills` is omitted, analysis uses the server default strategy so legacy clients keep existing behavior
- **First-run Setup Hint** - The Home page reads the read-only setup status and points users to Settings when required items such as the primary LLM channel or watchlist are missing
- **Real-time Progress** - Analysis task status updates in real-time, supports parallel tasks; the regular stock-analysis path now prefers LiteLLM streaming during the LLM stage and pushes finer-grained `message/progress` updates through task SSE
- **Recoverable AlphaSift screening** - The Screening page submits AlphaSift work as a background task and polls status, so returning to the page restores the active task progress or final result instead of losing feedback when snapshots, quotes, or LLM calls are slow
- **Market Review visibility** - After clicking Market Review, the API returns a `task_id` and the UI polls `GET /api/v1/analysis/status/{task_id}` to show progress; completed/failure states are rendered explicitly and failure messages are shown directly in the UI error area.
- **Market review history dedicated entry** - Market review history is shown in a dedicated history entry and isolated from regular stock history; use `stock_code=MARKET` and `report_type=market_review` to view and replay only market-review records.
- **Market review history replay** - Market review results are persisted with `report_type=market_review` and can be reopened from history list/detail or Markdown endpoints directly, without re-triggering a fresh analysis run.
- **Input data-block visibility** - Regular analysis reports expose a low-sensitivity `AnalysisContextPack` overview through history details, sync responses, and completed task status; the Web report page shows the data-block summary collapsed after Strategy and News, with block status, source, missing reasons, and fallback summaries available on expansion.
- **Ask-stock follow-up context** - When Ask Stock is opened from a historical report, follow-up messages keep sending the active `stock_code/stock_name`; reopening an existing chat can recover the base stock from loaded user messages, and comparison-style prompts do not overwrite the current stock context.
- **Backtest Validation** - Evaluate historical analysis accuracy, query direction win rate and simulated returns
- **API Documentation** - Visit `/docs` for Swagger UI

### Product behavior notes

For this feature, the product behavior is:

- UI language is independent from report language: `dsa.uiLanguage` (browser persistence) controls shell/login/settings text, while `REPORT_LANGUAGE` controls report text and report-page fixed copy (`zh`/`en`/`ko`).
- `dsa.uiLanguage` follows local persistence -> browser language -> default `zh`.
- This change only adds request-scope report language override parameters; it does not modify `provider`, `model`, `base_url`, or migration/cleanup behavior.
- PR-level verification output, screenshots, and command logs are maintained in PR description, not in this usage guide.

### API Endpoints

| Endpoint | Method | Description |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | Trigger stock analysis |
| `/api/v1/analysis/market-review` | POST | Trigger a background market review; request body may pass `{"send_notification": true}`; shares the same `GeminiAnalyzer/SearchService/NotificationService` construction semantics as `main.py --market-review` and Bot commands |
| `/api/v1/analysis/tasks` | GET | Query task list |
| `/api/v1/analysis/tasks/stream` | GET (SSE) | Subscribe to realtime task updates |
| `/api/v1/analysis/status/{task_id}` | GET | Query task status |
| `/api/v1/alphasift/screen/tasks` | POST | Submit an AlphaSift screening background task (`ALPHASIFT_ENABLED` must be enabled first) |
| `/api/v1/alphasift/screen/tasks/{task_id}` | GET | Query AlphaSift screening task status and completed result |
| `/api/v1/history` | GET | Query analysis history |
| `/api/v1/history/{record_id}/diagnostics` | GET | Query a historical report run diagnostic summary and sanitized copy text |
| `/api/v1/decision-signals` | POST | Explicitly create or deduplicate a decision signal and return `{ item, created }` |
| `/api/v1/decision-signals` | GET | Paginated decision-signal query with stock, market, action, phase, source, status, time-range, and cache-only holdings filters |
| `/api/v1/decision-signals/outcomes/run` | POST | Explicitly trigger signal outcome evaluation; by default skips completed/terminal unable rows, recomputes recoverable unable rows, and `force=true` recomputes |
| `/api/v1/decision-signals/outcomes` | GET | Paginated signal outcome query |
| `/api/v1/decision-signals/outcomes/stats` | GET | Query current outcome-engine stats; archived signals are excluded by default |
| `/api/v1/decision-signals/{signal_id}/outcomes` | GET | Query one signal's outcomes under the current outcome engine |
| `/api/v1/decision-signals/{signal_id}/feedback` | GET | Query one signal's user feedback; missing feedback returns `feedback_value=null` |
| `/api/v1/decision-signals/{signal_id}/feedback` | PUT | Upsert one signal's `useful|not_useful` feedback |
| `/api/v1/decision-signals/{signal_id}` | GET | Fetch one decision signal and apply lazy expiration before reading |
| `/api/v1/decision-signals/{signal_id}/status` | PATCH | Update a decision signal status and optional metadata |
| `/api/v1/decision-signals/latest/{stock_code}` | GET | Query the latest active decision signals for a stock |
| `/api/v1/usage/summary?period=today|month|all` | GET | Query LLM call counts and token usage grouped by call type and model |
| `/api/v1/usage/dashboard?period=today|month|all&limit=50` | GET | Return token-usage dashboard data: totals, prompt/completion split, model usage, call-type breakdown, and recent call records; the Web entry is the sidebar Usage page |
| `/api/v1/backtest/run` | POST | Trigger backtest |
| `/api/v1/backtest/results` | GET | Query backtest results (paginated) |
| `/api/v1/backtest/performance` | GET | Get overall backtest performance |
| `/api/v1/backtest/performance/{code}` | GET | Get per-stock backtest performance |
| `/api/health` | GET | Health check |
| `/docs` | GET | API Swagger documentation |

> Note: `POST /api/v1/analysis/analyze` supports only one stock when `async_mode=false`; batch `stock_codes` requires `async_mode=true`. The async `202` response returns a single `task_id` for one stock, or an `accepted` / `duplicates` summary for batch requests.
> Note: `POST /api/v1/analysis/analyze` accepts `skills` as an array of strategy IDs; if omitted, server defaults are used. The legacy field `strategies` is still accepted for backward compatibility.
> Note: `POST /api/v1/analysis/analyze` accepts `analysis_phase=auto|premarket|intraday|postmarket`, defaulting to `auto`. Non-`auto` only overrides the phase and derived phase flags for this run; it does not rewrite real trading-calendar timestamps. Accepted responses, in-memory task status, task lists, and SSE echo the requested phase, while the final report phase remains `report.meta.market_phase_summary.phase`.
> Note: `POST /api/v1/analysis/analyze` accepts `report_language=zh|en|ko` (legacy-compatible alias `reportLanguage`). When omitted, it falls back to global `REPORT_LANGUAGE`. This parameter is request-scoped only and influences report output language for this run, including `report.meta.report_language` in responses.
> Note: The Web Home page exposes an explicit strategy selector. When users do not pick one, `skills` is not sent and legacy behavior is preserved; when selected, it is passed through to this endpoint and persisted in task status/history snapshots.
> Note: `POST /api/v1/analysis/market-review` follows the same runtime configuration path as CLI/Bot market review (`GeminiAnalyzer(config=...)`, search setup, and prompt/rendering pipeline). The provider compatibility path prioritizes `litellm_model` and `llm_model_list`, then falls back to existing legacy keys (`GEMINI_*`, `OPENAI_*`, `ANTHROPIC_*`, `DEEPSEEK_*`) when those are not set; provider names, Base URL, and LiteLLM routing semantics are otherwise unchanged.
> Note: `POST /api/v1/analysis/market-review` also accepts `report_language=zh|en|ko` / `reportLanguage` to set report language for that request. If omitted, it falls back to global `REPORT_LANGUAGE`; Bot/CLI/manual `/market-review` calls keep using global config and do not carry request-level override.
> Note: `POST /api/v1/analysis/market-review` is the explicit Web/desktop trigger and submits a market-review task directly. It does not short-circuit because `TRADING_DAY_CHECK_ENABLED=true` or the configured markets are closed that day; scheduled jobs, GitHub Actions manual runs, and CLI defaults still follow the trading-day gate unless `--force-run` or workflow `force_run` is used.
> Audit note: priority and fallback are defined by `Config._load_from_env()` in `src/config.py` (`LITELLM_CONFIG` > `LLM_CHANNELS` > legacy). Regression coverage is in `tests/test_llm_channel_config.py` (configuration source parsing) and `tests/test_market_review_runtime.py` (shared runtime assembly). The endpoint lock is process/host-level only; multi-instance deployments still need external distributed idempotency controls.
> Note: Once `/api/v1/analysis/market-review` completes, the report is persisted with `report_type=market_review`; open `/api/v1/history` and `/api/v1/history/{record_id}` (or Markdown history endpoints) to view it directly without re-running analysis.
> Note: `/api/v1/analysis/market-review` responses and persisted history include a structured `market_review_payload` with fields like `market_scope`, `sections`, `sectors`, `concepts`, `news`, `market_light`, `indices`, etc. Web rendering and history detail use the same structure and fall back to raw `markdown_report` only if the structure is unavailable.
> Note: `market_review_payload.breadth` is emitted only when breadth data is truly available. For markets/feeds without usable breadth, the field is omitted and UI should display `No data` (not a misleading zero value).
> Note: when `/api/v1/analysis/market-review` returns a `task_id`, the WebUI polls `GET /api/v1/analysis/status/{task_id}`. The UI renders clear `pending/processing` progress, shows completion feedback when status becomes `completed`, and surfaces `error` content on `failed`.
> Note: filter market-review-only history via `GET /api/v1/history` with `stock_code=MARKET&report_type=market_review` to avoid mixing with regular stock history.
> Note: `GET /api/v1/history/{record_id}/diagnostics` accepts either the history primary key ID or `query_id`, and returns a `normal/degraded/failed/unknown` summary, key pipeline components, and sanitized `copy_text`. Older reports without `context_snapshot.diagnostics` return `unknown` without affecting normal report reads.
> Note: `GET /api/v1/history` list summaries can be paginated by `stock_code` for same-stock history and now include optional trend, summary, model, and analysis-time price/change fields. Older rows without persisted snapshots return empty values. The Web report page's "History Trend" drawer reuses this endpoint.
> Note: `GET /api/v1/usage/dashboard` reuses the existing `llm_usage` audit table and adds no configuration key or database migration. It returns only persisted call counts, prompt/completion/total token aggregates, model-level usage, and recent call records; it does not infer model context windows or provider metadata.
> Issue #1520 compatibility note: The `model`/`model_used` returned here is read-only historical snapshot metadata from each record, used only for trend drawer/history display. It does not alter runtime model/model-provider/base URL resolution, config migration, or cleanup semantics in the analysis path. Rollback is by reverting this commit; history query, API response shapes, and UI drawer consumption remain compatible.
> Note: history detail, sync analysis responses, and completed task status responses expose a low-sensitivity input data-block overview at `report.details.analysis_context_pack_overview`; sync analysis responses depend on the just-persisted `analysis_history.context_snapshot`, so new records do not guarantee the overview when `SAVE_CONTEXT_SNAPSHOT=false`. `details.context_snapshot` strips that top-level field and does not return the full `AnalysisContextPack` or prompt summary.
> Note: `POST /api/v1/agent/chat` and `POST /api/v1/agent/chat/stream` use the frontend-provided `context.stock_code` as the active Ask Stock baseline only after server-side stock-scope resolution. Each turn is classified as `maintain`, `switch`, or `compare`: unchanged follow-ups can call stock-scoped tools only for the current stock; explicit switches clear stale stock summaries and prefetched context; comparison prompts such as compare/vs/difference allow the explicitly mentioned codes for that turn without rewriting the current stock. If a model attempts to call a stock tool with financial abbreviations such as TTM, PE, MACD, KDJ, contextual indicator tokens such as `MA` in moving-average prompts, or exchange fragments such as SH/SZ/BJ/HK/SS, the backend returns a non-retriable `stock_scope_violation` tool result instead of executing that stock tool. Tool names are resolved only by exact registry name; provider namespaces or suffixes are not routed to existing tools.
> Note: `POST /api/v1/backtest/run` adds `analysis_date_from` / `analysis_date_to` (`YYYY-MM-DD`) to filter candidates by analysis date range. When `analysis_date_from > analysis_date_to`, it returns 400 `invalid_params`.
> Note: When backtest runs successfully but yields no new persisted rows, `BacktestRunResponse.message` carries a readable diagnostic and `diagnostics` returns troubleshooting context (for example `empty_reason`, `analysis_date_from`, `analysis_date_to`, `eval_window_days`, `min_age_days`, `limit`).
> Note: `GET /api/v1/backtest/results`, `GET /api/v1/backtest/performance`, and `GET /api/v1/backtest/performance/{code}` all support `analysis_date_from` and `analysis_date_to` consistently. Omitting them keeps historical default behavior.

> Compatibility audit evidence:
> - Official references: LiteLLM OpenAI-compatible provider documentation <https://docs.litellm.ai/docs/providers/openai_compatible>, OpenAI Chat API <https://platform.openai.com/docs/api-reference/chat/create>, and DeepSeek API docs <https://api-docs.deepseek.com/>.
> - Dependency boundary: this repo currently pins `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (see `requirements.txt`); the compatibility regressions for this path were verified under that dependency window.
> - Verifiable tests:
>   - `tests/test_llm_channel_config.py` (configuration priority and provider/base URL mapping)
>   - `tests/test_market_review_runtime.py` (`build_market_review_runtime` shared assembly path)
>   - `tests/test_analysis_api_contract.py` (`/api/v1/analysis/market-review` contract and task status flow)
> - Rollback path: if regression appears, restore historical `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, and legacy `GEMINI_*` / `OPENAI_*` / `ANTHROPIC_*` / `DEEPSEEK_*`, or import a desktop backup through `POST /api/v1/system/config/import` and restart; at runtime you can also clear `LITELLM_CONFIG` / `LLM_CHANNELS` to force legacy fallback.

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

# pass strategy list (optional)
curl -X POST http://127.0.0.1:8000/api/v1/analysis/analyze \
  -H 'Content-Type: application/json' \
  -d '{"stock_code": "600519", "skills": ["bull_trend", "growth_quality"]}'

# Query task status
curl http://127.0.0.1:8000/api/v1/analysis/status/<task_id>

# Query today's LLM usage
curl "http://127.0.0.1:8000/api/v1/usage/summary?period=today"

# Query today's LLM usage dashboard
curl "http://127.0.0.1:8000/api/v1/usage/dashboard?period=today&limit=50"

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
| BSE (Beijing) | 8/4/92 prefix, 6-digit; supports `BJ` prefix or `.BJ` suffix | `920748`, `BJ920493`, `920493.BJ` |
| HK stocks | hk + 5-digit number | `hk00700`, `hk09988` |
| US stocks | 1-5 letters, optional `.X` suffix | `AAPL`, `TSLA`, `BRK.B` |
| Japanese stocks | Yahoo `.T` suffix | `7203.T`, `6758.T` |
| Korean stocks | Yahoo `.KS` / `.KQ` suffix | `005930.KS`, `035720.KQ` |

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

### Portfolio account archive on `/portfolio`

- The `/portfolio` account toolbar can delete a selected single account through the existing `DELETE /api/v1/portfolio/accounts/{account_id}` endpoint.
- Account deletion uses soft-delete/archive semantics. Archived accounts are hidden from default account lists, portfolio snapshots, risk summaries, entry forms, and event lists.
- Historical trade, cash-ledger, corporate-action, and daily snapshot rows are not physically removed. To correct a specific ledger row from the Web UI, delete that row before archiving its account.

### Manual FX refresh on `/portfolio`

- The FX status card on the Web `/portfolio` page includes a manual refresh action.
- The button calls the existing `POST /api/v1/portfolio/fx/refresh` endpoint and reloads snapshot/risk data only.
- If upstream FX fetch fails, the page may still remain stale after refresh and will explain the fallback result inline.
- When `PORTFOLIO_FX_UPDATE_ENABLED=false`, the refresh API returns an explicit disabled status and the page shows that online FX refresh is disabled instead of implying that no refreshable pairs exist.
- Portfolio snapshot `positions[]` includes price metadata such as `price_source`, `price_date`, `price_stale`, and `price_available`. Today's snapshot tries realtime quotes first, then falls back to the latest historical close on or before `as_of` when the realtime quote is unavailable or non-positive. Historical `as_of` snapshots stay on historical-close semantics and no longer silently treat cost basis as the current price. Missing-price positions are marked with `price_available=false` and excluded from market value / unrealized PnL totals.

## Agent Tool Data Cache And Persistence

- `get_daily_history` first tries to reuse local `stock_daily` daily-bar cache; when the cache is fresh and contains at least the dashboard default of 30 records, it avoids another external data-source request.
- If Agent asks for more days than the local cache contains, the tool returns the available records and marks the response with `partial_cache=true`, `requested_days`, and `actual_records`.
- When the cache is missing or stale, the tool keeps the original data-source fetch path; successful fetches are written back to `stock_daily` on a best-effort basis, and write failures do not block the Agent response.
- `search_stock_news` and `search_comprehensive_intel` persist successful results to `news_intel` on a best-effort basis, reusing the existing URL / fallback-key deduplication logic.
- Stock news search now applies a domain-agnostic admission filter after relevance ranking: obvious download/install/app-rating pages and adult/escort spam pages are removed, and zero-score filler results are dropped when the same batch already has direct-stock or scored sector/market candidates. This is not a hard-coded website blocklist.
- This admission-filter change is isolated to retrieval post-filtering and does not alter model names, provider settings, Base URL, LiteLLM route semantics, or runtime config migration/cleanup behavior.
- `get_realtime_quote` does not use `stock_daily` as a realtime-quote cache and does not write intraday quotes into the daily-bar table; realtime quote caching should use a dedicated realtime store if needed.

## Agent Event Monitor

When `AGENT_EVENT_MONITOR_ENABLED=true`, schedule mode runs the alert worker every `AGENT_EVENT_MONITOR_INTERVAL_MINUTES` minutes. The worker reads enabled rules created through the Alert API and continues to support legacy rules in `AGENT_EVENT_ALERT_RULES_JSON`; triggered alerts still go through the existing notification channels. Alert API / Web persisted rules support price, change-percent, volume, daily technical indicators, `watchlist`, `portfolio_holdings`, `portfolio_account`, and `market` Market Light targets; legacy JSON still supports only the three basic rule types.

> Compatibility and rollback note: this section documents current Event Monitor rule behavior (including `price_change_percent`) and does not change external model/provider API semantics such as model names, providers, Base URL, LiteLLM, `OPENAI_*`, `DEEPSEEK_*`, or `GEMINI_*` configuration.
> Legacy JSON is not automatically migrated, deleted, or rewritten. To roll back the background alert worker, clear or disable `AGENT_EVENT_MONITOR_ENABLED`/related rule config.

| `alert_type` | Direction | Threshold | Description |
| --- | --- | --- | --- |
| `price_cross` | `above` / `below` | `price` | Current price crosses a fixed threshold |
| `price_change_percent` | `up` / `down` | `change_pct` | Intraday change percentage reaches a threshold |
| `volume_spike` | - | `multiplier` | Latest volume exceeds the recent 20-day average by this multiplier |
| `ma_price_cross` | `above` / `below` | `window` | Daily close edge-crosses MA(window) |
| `rsi_threshold` | `above` / `below` | `period`, `threshold` | RSI edge-crosses a threshold |
| `macd_cross` | `bullish_cross` / `bearish_cross` | `fast_period`, `slow_period`, `signal_period` | DIF/DEA edge golden/death cross |
| `kdj_cross` | `bullish_cross` / `bearish_cross` | `period`, `k_period`, `d_period` | K/D edge golden/death cross |
| `cci_threshold` | `above` / `below` | `period`, `threshold` | CCI edge-crosses a threshold |
| `portfolio_stop_loss` | `mode=near|breach` | - | Account-level stop-loss proximity or breach |
| `portfolio_concentration` | - | - | Account-level symbol concentration |
| `portfolio_drawdown` | - | - | Account-level maximum drawdown alert |
| `portfolio_price_stale` | - | - | Stale or missing portfolio prices |
| `market_light_status` | - | `statuses` | Current Market Light status matches the configured `red/yellow` list |
| `market_light_score_drop` | - | `min_drop` | Market Light score drops from the previous trading day by at least the threshold |

Example:

```env
AGENT_EVENT_MONITOR_ENABLED=true
AGENT_EVENT_MONITOR_INTERVAL_MINUTES=5
AGENT_EVENT_ALERT_RULES_JSON=[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":3.0},{"stock_code":"000858","alert_type":"volume_spike","multiplier":2.5}]
```

The worker writes `triggered`, `skipped`, `degraded`, and `failed` rows to `alert_triggers` as evaluation history; normal non-triggered checks do not write history. For DB-persisted rules, `triggered` history is best-effort deduplicated by `rule_id + target + data_source + data_timestamp`: repeated hits for the same data point reuse the earliest trigger row, while records without `data_timestamp` are not deduplicated. Real triggers write per-channel attempts to `alert_notifications`, and Alert API persisted rules write business cooldown state to `alert_cooldowns`; if the persisted cooldown read fails, the worker temporarily falls back to the in-process fingerprint guard to avoid repeated notifications during the DB failure. Legacy `AGENT_EVENT_ALERT_RULES_JSON` rules continue to use the in-process fingerprint suppressor and do not write persisted cooldown state; the notification infrastructure `notification_noise.py` guard remains independent. The Web rule list uses the backend-provided `cooldown_active` flag instead of browser-local timezone parsing to decide whether a rule is cooling down.

Technical indicator rules use daily-close edge triggers only. Partial-bar handling is a server-local-time + 16:00 heuristic and does not implement market-calendar precision. `watchlist` rules refresh and expand `STOCK_LIST` each worker run, `portfolio_holdings` expands non-zero snapshot positions with symbol de-duplication, and `portfolio_account` reuses the portfolio risk service for account-level aggregate evaluation. `market` rules accept only `cn|hk|us|jp|kr` targets and use structured `MarketLightSnapshot` data; `trade_date` comes from the current market overview, `data_quality=unavailable` skips triggering, non-trading days are skipped by the trading-day gate, and `market_light_score_drop` compares score across trading days only. The WebUI "Alerts" page can manage persisted rules, run one-shot dry-run tests, and view trigger history, notification attempts, and read-only cooldown state; cooldown on batch rules is a parent-rule summary, while child-target cooldown details are visible through trigger history. See [Real-Time Alert Center](alerts.md) for detailed boundaries.

---

For more questions, please [submit an Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
