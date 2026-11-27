# Notification Channels & Routing Baseline

This document specifies the P0–P7 notification baseline: supported channels, configuration keys, GitHub Actions mappings, Web settings metadata, CLI diagnostics, Web one-click channel testing, custom Webhook body templates, notification routing, in-process noise controls, per-channel failure isolation on batch reports, first-class `ntfy` / `Gotify` support, WebPush / Apprise evaluation, and deployment guidance across Local, Docker, GitHub Actions, and Desktop.

- **Scope summary**: P0 establishes diagnostics & contract baselines; P1 adds live single-channel Web tests; P2 standardizes body templates; P3 adds `report` / `alert` / `system_error` routing; P4 introduces in-process dedup/cooldown/quiet hours/severity filtering; P5 strengthens test redaction and per-channel batch failure isolation; P6-A adds `ntfy`; P6-C adds `Gotify`; P6-D evaluates WebPush / Apprise without adding dependencies; P7 automates the Actions env mapping check without adding runtime dependencies, per-URL templates, cross-process persistence, daily digests, or retry loops.

## Channel Baseline

| Channel | Type | Minimal Keys | Advanced Keys | Notes |
| --- | --- | --- | --- | --- |
| DingTalk Webhook | Static config | `DINGTALK_WEBHOOK_URL` | `DINGTALK_SECRET` | Supports signed webhooks; wired into Web Settings & single-channel test |
| WeChat Work | Static config | `WECHAT_WEBHOOK_URL` | `WECHAT_MSG_TYPE` | Participates in batch report delivery when configured |
| Feishu Webhook / App Bot | Static config | `FEISHU_WEBHOOK_URL` or `FEISHU_APP_ID` + `FEISHU_APP_SECRET` + `FEISHU_CHAT_ID` | `FEISHU_WEBHOOK_SECRET`, `FEISHU_WEBHOOK_KEYWORD`, `FEISHU_RECEIVE_ID_TYPE`, `FEISHU_DOMAIN` | Webhook takes precedence; App Bot pushes to target chats/users when Webhook is unset. `FEISHU_STREAM_ENABLED` only controls Stream event intake and does not count as outbound notification readiness |
| Telegram | Static config | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `TELEGRAM_MESSAGE_THREAD_ID` | Both token and chat ID are required |
| Email | Static config | `EMAIL_SENDER`, `EMAIL_PASSWORD` | `EMAIL_RECEIVERS`, `EMAIL_SENDER_NAME` | Sends to `EMAIL_SENDER` when `EMAIL_RECEIVERS` is blank |
| Pushover | Static config | `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN` | - | Both keys are required |
| ntfy | Static config | `NTFY_URL` | `NTFY_TOKEN`, `WEBHOOK_VERIFY_SSL` | `NTFY_URL` must include the topic path, e.g., `https://ntfy.sh/my-topic` |
| Gotify | Static config | `GOTIFY_URL`, `GOTIFY_TOKEN` | `WEBHOOK_VERIFY_SSL` | `GOTIFY_URL` is the server base URL without `/message`; token is sent via the `X-Gotify-Key` header |
| PushPlus | Static config | `PUSHPLUS_TOKEN` | `PUSHPLUS_TOPIC` | `PUSHPLUS_TOPIC` applies only when token is set |
| ServerChan3 | Static config | `SERVERCHAN3_SENDKEY` | - | Mobile app push |
| Custom Webhook | Static config | `CUSTOM_WEBHOOK_URLS` | `CUSTOM_WEBHOOK_BEARER_TOKEN`, `CUSTOM_WEBHOOK_BODY_TEMPLATE`, `WEBHOOK_VERIFY_SSL` | Comma-separated list of webhook URLs |
| Discord | Static config | `DISCORD_WEBHOOK_URL` or `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` | `DISCORD_INTERACTIONS_PUBLIC_KEY` | Works via either Webhook or Bot token |
| Slack | Static config | `SLACK_WEBHOOK_URL` or `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | - | Bot is preferred for combined text + image channel posts |
| AstrBot | Static config | `ASTRBOT_URL` | `ASTRBOT_TOKEN`, `WEBHOOK_VERIFY_SSL` | `ASTRBOT_TOKEN` is optional |
| `UNKNOWN` | Fallback enum | - | - | Unrecognized channel placeholder; never enabled by static env vars |
| DingTalk Session | Runtime context | - | - | Extracted from incoming message context; cannot be inferred from `.env` |
| Feishu Session | Runtime context | - | - | Extracted from incoming message context; interactive replies return to source chat |
| Telegram Session | Runtime context | - | - | Extracted from incoming message context; interactive replies return to source chat |

Discord long reports reuse chunked delivery so each `content` payload stays within Discord's 2,000-character limit. Both Webhook and Bot senders pause briefly between chunks and obey HTTP 429 `retry_after` / `Retry-After` responses to avoid partial truncation.

Telegram messages encountering HTTP 429 prefer [Bot API `parameters.retry_after`](https://core.telegram.org/bots/api#responseparameters), falling back to `Retry-After` and exponential backoff, up to 3 total attempts per message with no wait after the final attempt.

## Minimal vs. Advanced Key Tiering

- **Minimal key**: Minimum credentials/endpoints needed to enable a channel.
- **Advanced key**: Adjusts signing, security, payload format, threads, receivers, SSL verification, or noise rules; cannot enable a channel on its own.
- `NOTIFICATION_*_CHANNELS` (P3 routing keys) are Advanced keys: they narrow already-enabled channels and never activate unconfigured channels.
- `NOTIFICATION_DEDUP_TTL_SECONDS`, `NOTIFICATION_COOLDOWN_SECONDS`, `NOTIFICATION_QUIET_HOURS`, `NOTIFICATION_TIMEZONE`, `NOTIFICATION_MIN_SEVERITY`, and `NOTIFICATION_DAILY_DIGEST_ENABLED` (P4 noise keys) are Advanced keys affecting enabled static channels only.
- `REPORT_SHOW_LLM_MODEL` controls footer display of `model_used` (default `true`; set `false` to hide). It changes presentation only without altering runtime provider/model/base URL selection or saving behavior.
- `WEBHOOK_VERIFY_SSL` applies to webhook-style HTTPS requests (custom webhook, `ntfy`, `Gotify`, `AstrBot`).
- WebPush, Apprise, finer-grained routing, cross-process noise persistence, and daily digest jobs remain out of runtime scope until dedicated design, docs, and tests are added.
- Bark stays under Custom Webhook rather than introducing top-level `BARK_*` keys.
- Feishu App Bot reuses `lark-oapi>=1.0.0` already declared in `requirements.txt` ([Feishu message create OpenAPI](https://open.feishu.cn/document/server-docs/im-v1/message/create), [lark-oapi PyPI](https://pypi.org/project/lark-oapi/), [SDK repo](https://github.com/larksuite/oapi-sdk-python)); file upload uses `im.v1.file.create` ([Feishu file create OpenAPI](https://open.feishu.cn/document/server-docs/im-v1/file/create)).

## Report Rendering & Chunking

Notification entry points, content sources, and overall layout remain backward-compatible while unifying channel capabilities, `PreparedMessage`, renderer presets, and structure-aware chunking.

WeChat Work and Slack preserve their existing Markdown conversion and chunking paths. Feishu Webhook and App Bot extract card titles, sentiment colors, and dedicated risk-alert panels, paginating by serialized JSON byte size; see the [Full Guide](full-guide_EN.md) for card button details. `send_feishu_file()` uploads files via App Bot and falls back to inline text in Webhook mode.

Compatibility scope note:
- `model_used` is strictly display-only (`report_show_llm_model`) and never affects LLM routing, persistence, or config migrations. Related test fixtures live under `tests/fixtures/notification_reports/*.md` and `src/notification.py`.
- Both `REPORT_SHOW_LLM_MODEL` (defaults to `true`) and `REPORT_RENDERER_ENABLED` / `report_renderer_enabled` (defaults to `false`) govern presentation/rendering fallback only; reverting means restoring their defaults (`true` / `false`) or removing the override.
- Correlated sector/concept tables appear only when `fundamental_context.boards.data` / `sector_rankings` or `fundamental_context.concept_boards.data` / `concept_rankings` carry leader/laggard signals (with a "Type" column marking industry vs. concept boards); otherwise, reports keep the compact single-line tag list.

## GitHub Actions Mapping

The built-in `.github/workflows/00-daily-analysis.yml` imports an explicit set of variables. `scripts/generate_notification_actions_env_table.py` automatically verifies and syncs the Chinese baseline ([`docs/notifications.md`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/notifications.md)); this English table is maintained in manual sync with it:

| Key | Tier | Channel / feature | Actions source | Default |
| --- | --- | --- | --- | --- |
| `WECHAT_WEBHOOK_URL` | minimal | wechat | Secret | - |
| `WECHAT_MSG_TYPE` | advanced | wechat | Variable or Secret | `markdown` |
| `FEISHU_WEBHOOK_URL` | minimal | feishu | Secret | - |
| `FEISHU_WEBHOOK_SECRET` | advanced | feishu | Secret | - |
| `FEISHU_WEBHOOK_KEYWORD` | advanced | feishu | Variable or Secret | - |
| `DINGTALK_WEBHOOK_URL` | minimal | dingtalk | Secret | - |
| `DINGTALK_SECRET` | advanced | dingtalk | Secret | - |
| `TELEGRAM_BOT_TOKEN` | minimal | telegram | Secret | - |
| `TELEGRAM_CHAT_ID` | minimal | telegram | Secret | - |
| `TELEGRAM_MESSAGE_THREAD_ID` | advanced | telegram | Secret | - |
| `EMAIL_SENDER` | minimal | email | Variable or Secret | - |
| `EMAIL_PASSWORD` | minimal | email | Secret | - |
| `EMAIL_RECEIVERS` | advanced | email | Variable or Secret | - |
| `EMAIL_SENDER_NAME` | advanced | email | Variable or Secret | `daily_stock_analysis股票分析助手` |
| `PUSHOVER_USER_KEY` | minimal | pushover | Secret | - |
| `PUSHOVER_API_TOKEN` | minimal | pushover | Secret | - |
| `NTFY_URL` | minimal | ntfy | Secret | - |
| `NTFY_TOKEN` | advanced | ntfy | Secret | - |
| `GOTIFY_URL` | minimal | gotify | Secret | - |
| `GOTIFY_TOKEN` | minimal | gotify | Secret | - |
| `PUSHPLUS_TOKEN` | minimal | pushplus | Secret | - |
| `PUSHPLUS_TOPIC` | advanced | pushplus | Variable or Secret | - |
| `CUSTOM_WEBHOOK_URLS` | minimal | custom | Secret | - |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | advanced | custom | Secret | - |
| `CUSTOM_WEBHOOK_BODY_TEMPLATE` | advanced | custom | Variable or Secret | - |
| `WEBHOOK_VERIFY_SSL` | advanced | ntfy, gotify, custom, astrbot | Variable or Secret | `true` |
| `DISCORD_WEBHOOK_URL` | minimal | discord | Secret | - |
| `DISCORD_BOT_TOKEN` | minimal | discord | Secret | - |
| `DISCORD_MAIN_CHANNEL_ID` | minimal | discord | Secret | - |
| `FEISHU_APP_ID` | minimal | feishu | Secret | - |
| `FEISHU_APP_SECRET` | minimal | feishu | Secret | - |
| `FEISHU_CHAT_ID` | minimal | feishu | Variable or Secret | - |
| `FEISHU_RECEIVE_ID_TYPE` | advanced | feishu | Variable or Secret | - |
| `FEISHU_DOMAIN` | advanced | feishu | Variable or Secret | - |
| `FEISHU_SEND_AS_FILE` | advanced | feishu | Variable or Secret | - |
| `ASTRBOT_URL` | minimal | astrbot | Secret | - |
| `ASTRBOT_TOKEN` | advanced | astrbot | Secret | - |
| `SERVERCHAN3_SENDKEY` | minimal | serverchan3 | Secret | - |
| `SLACK_WEBHOOK_URL` | minimal | slack | Secret | - |
| `SLACK_BOT_TOKEN` | minimal | slack | Secret | - |
| `SLACK_CHANNEL_ID` | minimal | slack | Secret | - |
| `NOTIFICATION_REPORT_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_ALERT_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | advanced | noise | Variable or Secret | `0` |
| `NOTIFICATION_COOLDOWN_SECONDS` | advanced | noise | Variable or Secret | `0` |
| `NOTIFICATION_QUIET_HOURS` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_TIMEZONE` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_MIN_SEVERITY` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | advanced | noise | Variable or Secret | `false` |

Default Actions workflows intentionally do not auto-map `MARKDOWN_TO_IMAGE_CHANNELS` or `MERGE_EMAIL_NOTIFICATION`.

## Share Image Report Templates

When `MARKDOWN_TO_IMAGE_CHANNELS` is configured, stock reports, combined digests, and market reviews render a 1,080px-wide mobile poster card using the same routing subset:

- Single-stock reports render Conclusion -> Levels -> Technicals -> Risks -> Position cards; market reviews render Signals -> Indices -> Breadth -> Sectors -> Capital Flows -> Watchlist Focus -> Strategy -> Risks; multi-stock reports use a combined layout.
- Custom Xiaohongshu badge settings use `SHARE_IMAGE_XIAOHONGSHU_*` (when empty, defaults to bundled QR and `@霸天土小豆` without exposing numeric IDs or requiring external image hosts).
- Only report-native 0–100 scores, 8-state actions, and `battle_plan.sniper_points` appear on level cards; `wkhtmltoimage`, `markdown-to-file`, and `playwright` share the identical poster HTML (`MD2IMG_ENGINE`, `MARKDOWN_TO_IMAGE_MAX_CHARS`; Playwright requires `npx playwright install chromium`). See `docs/share-images.md` for field mapping details.

## CLI Diagnostics

```bash
python main.py --check-notify
```

Read-only diagnostic command: sends no messages, writes no files to `.env`, and exits immediately after config loading (`0` when free of error-level issues; `1` when zero channels are configured or paired keys are incomplete).

## Web One-Click Channel Testing

Under **Settings -> Notification Channels**, testing uses current page draft values to send a live test notification without saving `.env` or mutating runtime config:

- Covers all 14 static channels (excludes `UNKNOWN` and session-bound channels).
- Reports single attempt latency/status/error codes, or per-URL `attempts` summary counts for Custom Webhooks.
- Redacts tokens, secrets, passwords, Bearer values, webhook query strings, and probable path tokens.
- Returns `success=false` cleanly on missing configuration or delivery failure without disturbing scheduled workflows.

## Custom Webhook Body Templates

`CUSTOM_WEBHOOK_BODY_TEMPLATE` defines a global JSON payload template for Custom Webhooks (takes precedence over auto-detected Bark/Slack/Discord/DingTalk formats when set; falls back to auto payload if rendered output is not a valid JSON object):

- `$content_json` / `$title_json`: JSON-escaped strings (**recommended**).
- `$content` / `$title`: raw strings without JSON escaping (quotes/newlines can produce invalid JSON).
- In Docker Compose, both Web Settings saves **and manual edits** to your Compose `.env` file must double-escape placeholders as `$$content_json`, `$$title_json`, `$$content`, and `$$title` so Compose does not interpolate `$var` against empty host environment variables; runtime restores single `$` placeholders cleanly.

Generic webhook example:

```ini
# Plain local .env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"content":$content_json}

# Docker Compose .env (manual edit or saved from Web Settings)
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$$title_json,"content":$$content_json}
```

- **Bark (`api.day.app`)**: place the Bark URL in `CUSTOM_WEBHOOK_URLS`; without a global template, `title`/`body`/`group` are generated automatically, and `body` truncates safely near ~3,000 JSON bytes so APNs stays under Bark's 4,096-byte ceiling.
- **ntfy**: prefer first-class `NTFY_URL` + optional `NTFY_TOKEN`. Because ntfy enforces a 4,096-byte `message-size-limit` (8,192-byte JSON HTTP 413 ceiling), long reports split cleanly along section boundaries into `<= 3900`-byte chunks titled with `(1/N)`.
- **Gotify**: prefer first-class `GOTIFY_URL` (server base URL without `/message`, e.g., `https://example.com/gotify`) + `GOTIFY_TOKEN` (`X-Gotify-Key` header).
- **NapCat / OneBot**: adjust `user_id` / `group_id`, endpoint path, and auth to match your server, e.g. `CUSTOM_WEBHOOK_BODY_TEMPLATE={"group_id":123456789,"message":$content_json}` in a plain `.env` (or `{"group_id":123456789,"message":$$content_json}` when editing a Docker Compose `.env`).

## Notification Routing Strategy

P3 introduces three route filters (comma-separated channels from `wechat,dingtalk,feishu,telegram,email,pushover,ntfy,gotify,pushplus,serverchan3,custom,discord,slack,astrbot`):

| Route Type | Config Key | Current Producers |
| --- | --- | --- |
| `report` | `NOTIFICATION_REPORT_CHANNELS` | Single stock, batch daily report, market review, merged email, Feishu doc success links |
| `alert` | `NOTIFICATION_ALERT_CHANNELS` | `EventMonitor` triggered alert deliveries |
| `system_error` | `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | Analysis timeout partial reports (`runtime_scheduler.py` / `analysis_timeout_partial.py`, controlled by `DSA_TIMEOUT_PARTIAL_NOTIFY`, default `true`); when blank, broadcasts to all configured static channels |

- Blank: preserves legacy behavior (broadcasts to all configured static channels).
- Non-empty: sends only to the intersection of the route list and configured static channels (never falls back to all channels if empty).
- Interactive bot triggers (`send_to_context()`) reply directly to the originating chat session without route restrictions and skip static broadcast channels when a chat context is attached.
- Route filtering runs before `MARKDOWN_TO_IMAGE_CHANNELS` conversion; `--check-notify` flags unknown channel names as errors and enabled-missing routed targets as warnings.

## Batch Failure Isolation & Noise Controls

- **Per-channel failure isolation (P5)**: `_send_notifications()` isolates exceptions per channel and per email receiver group so one failing destination never aborts remaining deliveries or the core analysis pipeline. `decision_signal_summary` embeds only low-sensitivity action/horizon/risk summaries without exposing secrets or raw diagnostics (see `docs/decision-signals.md`).
- **Noise controls (P4)**: `NOTIFICATION_DEDUP_TTL_SECONDS`, `NOTIFICATION_COOLDOWN_SECONDS`, `NOTIFICATION_QUIET_HOURS` (`HH:MM-HH:MM`, supports overnight spans), `NOTIFICATION_TIMEZONE` (e.g., `Asia/Shanghai`), `NOTIFICATION_MIN_SEVERITY` (`info`, `warning`, `error`, `critical`), and reserved `NOTIFICATION_DAILY_DIGEST_ENABLED` (`false`). State is tracked in-memory per Python process (fail-open on error; in-flight reservations release if every static channel fails).

## WebPush / Apprise Evaluation

P6-D evaluated both without adding dependencies:
- **WebPush** requires HTTPS/Service Worker context, VAPID keypair rotation, user-gesture permission prompts, capability-URL redaction, multi-device persistence, and authenticated CSRF-protected subscription APIs.
- **Apprise** overlaps most existing first-class channels while enlarging Docker images and Actions caches; any future exploration should isolate it behind an optional extra and strict URL redaction.

## Environment-Specific Setup & Rollback

- **Local**: copy `.env.example` to `.env`, set at least one minimal channel key, and run `python main.py --check-notify`.
- **Docker**: pass env vars via `--env-file .env` or Compose `env_file` (avoid single-file bind-mounting `.env` over `/app/.env` if saving from Web Settings; set `ENV_FILE=/app/data/runtime.env`). When manually editing a Docker Compose `.env`, double-escape `$` placeholders in `CUSTOM_WEBHOOK_BODY_TEMPLATE` (`$$title_json`, `$$content_json`). Set `NOTIFICATION_TIMEZONE` explicitly inside containers and never disable `WEBHOOK_VERIFY_SSL` on public endpoints.
- **GitHub Actions**: only variables explicitly listed in `00-daily-analysis.yml` enter the workflow (`STOCK_GROUP_N` / `EMAIL_GROUP_N` numbered vars are not auto-imported).
- **Desktop**: shares Web Settings and single-channel testing; remember to save settings explicitly when persisting changes.
- **Rollback**: restore previous `.env` / export backup or clear the channel's minimal keys and restart (or remove Actions Secrets/Variables).
