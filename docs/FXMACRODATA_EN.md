# FXMacroData for Daily Stock Analysis

The stock report and chat agent can call native macroeconomic tools. Each tool retains the complete public input schema, original payload, release timestamps and source provenance. The factory adds these tools to the same registry as the existing market tools.

The core integration uses [FXMacroData](https://fxmacrodata.com/?utm_source=github&utm_medium=referral&utm_campaign=open_source_integrations&utm_content=daily_stock_analysis_readme) always-free public USD endpoints and requires no API key, account or credit card. Public indicator history currently covers the most recent 90 days; catalogue and release-calendar access also work without a key. Optional authenticated coverage follows the API contract.

## Installation

The integration is included in the application dependencies. Install them using the project's normal command:

```sh
python -m pip install -r requirements.txt
```

Public USD data requires no API key. Optional authorization is configured below.

## Use

The optional FXMACRODATA_API_KEY environment variable uses the host process configuration. For the scheduled GitHub Actions analysis, store it as the repository secret `FXMACRODATA_API_KEY`; `00-daily-analysis.yml` maps that secret into the analysis step environment. The key never enters a tool schema, model invocation or response. The application must be in Agent mode for these report/chat tools to be used. No report layout changes are required. The Codex chat backend only exposes tools registered as cancellation-safe, and the FXMacroData tools are not, so they are currently available through the other chat backends and the report agents.

In multi-agent mode, the Intelligence specialist can discover and execute all 72 operations in the pinned client v0.1.0 snapshot through its native tool allowlist. Risk and Portfolio specialists also receive the operations relevant to release, macro and cross-market risk. Existing specialist tool restrictions remain in force.

Start with `data_catalogue` and parameters `{"currency":"USD"}`, then `indicator_history` with `{"currency":"USD","indicator":"policy_rate","limit":5}` or `release_calendar` with `{"currency":"USD"}`. Agent tool names have an `fxmacrodata_` prefix. The operation catalogue includes exact required parameters and supported options.

The `data` field preserves the original public response; `records` is an additive table view. Keep source fields, assumed-time flags and timezone offsets when using the data. The API contract distinguishes official forecasts, market consensus and FXMacroData-generated outputs. Historical observation filters do not by themselves establish point-in-time vintage safety. Streaming is bounded by the client; it is not a persistent subscription.

[Public API reference](https://fxmacrodata.com/documentation/reference?utm_source=github&utm_medium=referral&utm_campaign=open_source_integrations&utm_content=daily_stock_analysis_docs)

## Coverage

The table below is the operation catalogue bundled with the pinned `fxmacrodata-public-client` v0.1.0 (23 REST operations and 49 hosted MCP tools). Operations added to the live API after that release appear here once the pinned client is updated. Every operation in this snapshot is available through the native consumer above. Access requirements depend on the operation and currency. MCP tools, non-USD data and other protected datasets may require authorization; they are not required for the public USD baseline.

| Operation | Transport | Native consumer | Status |
| --- | --- | --- | --- |
| `health` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `ping` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `forex` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `intraday_reference_rates` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `fx_sources` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `fx_source_universe` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `data_catalogue` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `release_calendar` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `market_sessions` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `rate_differentials` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `curves` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `financial_prices` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `press_releases` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `risk_sentiment` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `factors` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `event_predictions` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `latest_announcements` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `indicator_history` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `cot` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `latest_commodities` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `commodities` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `announcement_changes` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `stream_events` | GET | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_ping` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_mcp_capabilities` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_mcp_auth_guide` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_subscribe_for_mcp_access` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_data_catalogue` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_risk_sentiment` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_macro_news` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_release_calendar` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_release_calendar_visual_artifact` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_event_predictions` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_latest_announcements` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_announcement_changes` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_press_releases` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_macro_factor` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_fx_reference_sources` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_fx_reference_universe` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_fx_intraday_reference_rates` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_rate_curve` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_rate_differentials` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_latest_commodities` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_forex` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_seasonality` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_indicator_query` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_plot_visual_artifact` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_indicator_visual_artifact` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_forex_visual_artifact` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_commodities_visual_artifact` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_cot_visual_artifact` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_policy_rate_differential_visual_artifact` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_macro_briefing_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_indicator_intel_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_pair_intel_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_macro_heatmap_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_policy_scenario_modeler_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_macro_war_room_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_event_impact_replay_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_quant_scenario_lab_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_known_at_time_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_macro_regime_classifier_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_release_risk_score_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_portfolio_risk_engine_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_fx_trade_setup_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_fx_backtest_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_macro_research_pack_task` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_market_sessions` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_cot_data` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_commodities` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_financial_prices` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |
| `mcp_official_dataset_family` | MCP | `src/agent/tools/fxmacrodata_tools.py` | Implemented |

## Validation

Offline tests cover tool registration and schema for every operation, factory registration for report and chat, the multi-agent specialist filters, and the degraded `unavailable` paths (client construction, transport and close failures, missing operation catalogue). They do not make real provider requests or exercise report routing end to end.

```sh
python -m pytest tests/test_fxmacrodata_tools.py -o addopts= -q -n 8 --dist load
```

These focused tests do not replace the target project's full CI gate. No live credentials or private datasets are fixtures.

## Attribution

Rob Tidball owns FXMacroData and maintains this adapter. Website links identify the provider; campaign parameters distinguish repository documentation visits from integration application visits. API/MCP requests have no campaign parameters, and the adapter sends no click telemetry.
