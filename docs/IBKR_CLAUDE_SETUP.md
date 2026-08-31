# Claude-first US Stock Analysis for IBKR Research

This guide configures `daily_stock_analysis` for a US-equity research workflow using Anthropic Claude via LiteLLM.

> This setup is research-only. It does **not** place orders in Interactive Brokers.

## 1. GitHub Actions secret

Create this repository secret:

- `ANTHROPIC_API_KEY` — your Anthropic API key

Optional news/search secret:

- `TAVILY_API_KEYS`

Optional email secret:

- `EMAIL_PASSWORD`

Path in GitHub:

`Settings -> Secrets and variables -> Actions -> Secrets`

## 2. Recommended repository variables

Create these under:

`Settings -> Secrets and variables -> Actions -> Variables`

| Variable | Recommended value |
|---|---|
| `LITELLM_MODEL` | `anthropic/claude-sonnet-4-6` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` |
| `LLM_TEMPERATURE` | `0.4` |
| `STOCK_LIST` | `AAPL,MSFT,NVDA,GOOGL,AMZN,META,SPY,QQQ` |
| `MARKET_REVIEW_REGION` | `us` |
| `MARKET_REVIEW_ENABLED` | `true` |
| `REPORT_LANGUAGE` | `en` |
| `REPORT_TYPE` | `simple` |
| `REPORT_SHOW_LLM_MODEL` | `true` |
| `SINGLE_STOCK_NOTIFY` | `false` |
| `TRADING_DAY_CHECK_ENABLED` | `true` |
| `MAX_WORKERS` | `1` |

Optional email variables:

- `EMAIL_SENDER`
- `EMAIL_RECEIVERS`
- `EMAIL_SENDER_NAME`

## 3. Workflow

The dedicated workflow is:

`.github/workflows/10-us-claude-analysis.yml`

It supports:

- scheduled US post-market analysis
- manual `full`, `market-only`, and `stocks-only` runs
- Claude Sonnet 4.6 through LiteLLM
- US market review defaults
- English reports
- report/log artifacts retained for 30 days

### Schedule

The workflow runs at:

`22:30 UTC, Monday-Friday`

This is `01:30 Africa/Nairobi` on the following calendar day.

The timing is intentionally after the regular US market close so closing prices have time to settle.

## 4. First test

After merging the PR:

1. Open `Actions`.
2. Select `US Claude Stock Analysis`.
3. Click `Run workflow`.
4. Choose `stocks-only` for the first test.
5. Keep `force_run` off unless testing outside a normal trading day.
6. Inspect the generated logs and report artifact.

Start with a short watchlist if you want to control API usage, for example:

`AAPL,MSFT,NVDA,SPY,QQQ`

## 5. Model selection

Default model:

`anthropic/claude-sonnet-4-6`

Claude is used for interpretation and narrative generation. Price retrieval, indicators, calculations, and backtesting remain in the project's Python code.

This separation is important: the LLM should interpret calculated market data rather than invent prices or indicators.

## 6. News search

For stronger catalyst/news context, add one of the supported search providers. Tavily is a simple starting option:

Secret:

`TAVILY_API_KEYS`

The workflow also accepts:

- `BRAVE_API_KEYS`
- `SERPAPI_API_KEYS`

## 7. Email reports

To enable email output configure:

Variables:

- `EMAIL_SENDER`
- `EMAIL_RECEIVERS`

Secret:

- `EMAIL_PASSWORD`

If Gmail is used, use a Gmail App Password rather than the normal account password when applicable.

## 8. IBKR safety boundary

This workflow does not connect to IBKR order execution.

Recommended progression:

1. daily equity research
2. backtest recommendation quality
3. add options screening using IV, Greeks, liquidity and max-loss filters
4. paper trading through IBKR
5. consider live execution only after explicit validation and risk controls

Do not convert an LLM-generated `BUY` rating directly into a live options order.

## 9. Duplicate schedule note

The repository's original workflow `.github/workflows/00-daily-analysis.yml` remains unchanged to preserve upstream compatibility. It currently has its own weekday schedule.

If you only want the US Claude workflow to run automatically, disable the original scheduled workflow in GitHub Actions or remove its schedule in a follow-up change after validating this setup.
