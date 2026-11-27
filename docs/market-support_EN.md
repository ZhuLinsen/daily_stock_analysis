# Market Support & Boundaries

## Japan / South Korea Stock Suffix-Only MVP (Issue #1718, Refs #1718)

Manual entry of Japan and South Korea stock symbols using Yahoo Finance suffixes flows into single-stock analysis, history persistence, and baseline report rendering. Web autocomplete includes a curated seed index covering major JP/KR names so users can search by suffix code, localized name, or common aliases.

Supported formats:

- Japan: `7203.T`, `6758.T`
- South Korea KOSPI: `005930.KS`
- South Korea KOSDAQ: `247540.KQ`

Constraints & boundaries:

- Entering bare codes searches the local/remote stock pool first; if bare codes like `005930` or `000660` match `005930.KS` / `000660.KS` in the registry, submission targets the matched market. Unmatched 6-digit bare codes still default to A-share semantics and remain a documented cross-market ambiguity boundary.
- JP/KR suffix recognition is centralized in the shared market-code utility so fetcher routing, prompt market semantics, trading calendars, and registry bare-code resolution stay consistent.
- JP/KR daily K-lines and basic live/near-live quotes use only `YfinanceFetcher`, bypassing A-share-only sources (`AkShare`, `Tushare`, `Efinance`, `Pytdx`, `Baostock`). Quotes attach quality metadata including `market`, `currency`, `data_quality`, and `missing_fields` where available.
- Fundamentals reuse the existing lightweight offshore yfinance path; A-share-only capabilities such as capital flow, Dragon-Tiger List, and sector boards degrade as `not_supported`, while offshore fundamental context preserves `provider`, `as_of`, `data_quality`, and missing-block annotations.
- Report prompts adapt JP/KR market rules so A-share price-limit bands, Northbound flow, Dragon-Tiger List, or margin-financing concepts are not applied.
- Trading calendars register `jp: XTKS / Asia/Tokyo` and `kr: XKRX / Asia/Seoul`. Regular market-phase detection covers pre-market, intraday, lunch break, 15:25–15:30 closing auction, post-market, and non-trading days for JP, and pre-market, intraday, 15:20–15:30 closing auction, post-market, and non-trading days for KR. Existing fail-open/fail-closed behavior applies if `exchange-calendars` lacks a given calendar.

Compatibility & rollback notes (for configuration/API stability checks):

- `#1815` only adds optional metadata fields (`market`, `currency`, `data_quality`, `missing_fields`, `provider`) in `yfinance` quote/fundamental contexts without changing LLM provider/model/base URL semantics, config schemas, runtime env vars, DB columns, serialized cache keys, or wire versions.
- No provider, model, or base URL routing/cleanup/migration branches are modified; saved configurations stay intact and rolling back reverts cleanly.
- External market calls stay confined to `yfinance` (`Ticker` / `history` / `fast_info`) with existing fallback behavior; `YFINANCE_PRIORITY` is the only affected config key. Main JP/KR benchmark indices on Yahoo Finance:
  - Nikkei 225: `^N225` (<https://finance.yahoo.com/quote/%5EN225/>)
  - TOPIX: `^TOPX` (<https://finance.yahoo.com/quote/%5ETOPX/>)
  - KOSPI: `^KS11` (<https://finance.yahoo.com/quote/%5EKS11/>)
  - KOSDAQ: `^KQ11` (<https://finance.yahoo.com/quote/%5EKQ11/>)
  - Dependency floor: `yfinance>=0.2.0` in `requirements.txt`; offline regression coverage resides in `tests/test_yfinance_jp_kr_indices.py` and `tests/test_yfinance_hk_indices.py`.
- `MARKET_REVIEW_REGION` preserves valid comma-separated subsets (such as `cn,us`) and keeps `both` covering all supported markets; invalid or empty values fall back to `cn` without overwriting saved configs.
- Runtime behavior: JP/KR indices fetch fail-open per index so a single failure never blocks other indices or markets; if both markets return empty/unavailable primary index data, the pipeline falls back gracefully using remaining markets.
- Compatibility verification: contexts pass optional fields downstream via existing `getattr`/optional contracts with no migration scripts.
- Rollback path: if metadata fields cause downstream issues, callers can ignore them and run standard market detection/display, or revert `jp`/`kr` `MarketSymbol` and routing extensions.

Explicit non-goals:

- No real-time quote SLA; Yahoo Finance feeds can lag or omit fields.
- No full fundamentals, sector/industry rankings, market breadth, or advancers/decliners counts. JP/KR market review v1 delivers primary indices, news clues, and template/LLM commentary only.
- No full JP/KR stock universe promise; autocomplete relies on the bundled seed list (~30 major symbols each), while unmatched tickers can always be typed directly with their suffix.
- No complete JPY/KRW FX conversion, cost-basis, or valuation rollup in Portfolio yet; market enums are permitted solely to avoid rejecting JP/KR records.

Rollback: Remove `jp`/`kr` market detection, trading calendar registration, YFinance routing extensions, Web/API market enum allowances, and `scripts/stock_index_seeds/` JP/KR seeds along with these capability notes.

## Japan / South Korea Market Review v1 (Issue #1815 Phase 2)

`MARKET_REVIEW_REGION` now supports `jp` and `kr` inside multi-market reviews; `both` currently expands in order `cn,hk,us,jp,kr,tw` (including Taiwan below).

Supported scope:

- `jp`: fetches Nikkei 225 (`^N225`) and TOPIX (`^TOPX`) via Yahoo Finance:
  - `^N225`: <https://finance.yahoo.com/quote/%5EN225/>
  - `^TOPX`: <https://finance.yahoo.com/quote/%5ETOPX/>
- `kr`: fetches KOSPI (`^KS11`) and KOSDAQ (`^KQ11`) via Yahoo Finance:
  - `^KS11`: <https://finance.yahoo.com/quote/%5EKS11/>
  - `^KQ11`: <https://finance.yahoo.com/quote/%5EKQ11/>
- In Web Settings, `MARKET_REVIEW_REGION` accepts comma-separated subsets (e.g., `cn,jp`, `cn,us,jp,kr`). Trading-day filters check `XTKS / Asia/Tokyo` and `XKRX / Asia/Seoul` when expanding `both`.
- Review strategies, search keywords, prompt market guidance, and bilingual notification titles use dedicated JP/KR profiles.

Compatibility & verification criteria:

- Live data availability follows Yahoo Finance quote contracts; offline test coverage lives in `tests/test_yfinance_jp_kr_indices.py`, `tests/test_yfinance_hk_indices.py`, and `tests/test_trading_calendar.py`. For optional live checks:

```bash
python - <<'PY'
from yfinance import Ticker
for symbol in ("^N225", "^TOPX", "^KS11", "^KQ11"):
    data = Ticker(symbol).history(period="5d")
    print(symbol, "rows", len(data))
PY
```

Boundaries:

- JP/KR market review v1 omits up/down counts, limit-up/down counts, sector rankings, and capital-flow totals; `breadth` only appears when breadth data exists.
- Single index failures skip fail-open without blocking remaining indices or markets.
- Missing exchange calendars preserve existing fail-open/fail-closed behavior.

Rollback: Remove `jp` / `kr` from `MARKET_REVIEW_REGION` allowed values, Web settings options, `MarketProfile`/`MarketStrategy`, `_MARKET_REVIEW_MARKETS`, and this document.

## Taiwan Stock Support (Suffix-Only, Issue #1772 / #1777)

Manual entry of Taiwan stocks with Yahoo Finance suffixes integrates into single-stock analysis, history storage, report rendering, `DecisionSignal`, Portfolio, and Intelligence pipelines. TWSE listings use `.TW` and TPEx (OTC) listings use `.TWO`; both normalize under the unified `tw` market tag.

The Taiwan pipeline has promoted from early MVP to first-class single-stock analysis: market classification, routing, trading calendar/phase detection, YFinance bars and quotes, primary indices, service/API/Web market enums, TWD currency labeling, the Three Institutional Investors flow block, and LLM prompt injection are all wired. Remaining boundaries: Taiwan seed/autocomplete coverage, Market Light traffic-light alerts, and full Taiwan breadth/sector leaderboards are not yet included.

Supported formats:

- TWSE: `2330.TW`, `0050.TW`
- TPEx (OTC): `6488.TWO`, `5483.TWO`
- Base tickers use 4–6 digits (4 digits for equities, up to 6 digits for ETFs/others such as `00878.TW`, `006208.TW`), wider than `.T` (4–5 chars).

Constraints & boundaries:

- **Strictly suffix-only**: bare codes such as `2330` or `00878` do not trigger Taiwan routing (`detect_market` / `get_market_for_stock` require explicit `.TW` or `.TWO` suffixes). Full seed autocomplete is not bundled; enter explicit suffix codes directly.
- Daily K-lines and basic quotes use `YfinanceFetcher` exclusively without trying A-share fetchers.
- Fundamentals reuse the lightweight offshore yfinance path; the `institution` block enriches reports with Taiwan Three Institutional Investors data, while A-share capital flow/board capabilities degrade as `not_supported`.
- Prompts incorporate Taiwan market semantics (TWD, Three Institutional Investors, TWSE/TPEx ±10% daily limits) and institutional net buy/sell context without A-share concepts.
- Trading calendar registers `tw: XTAI / Asia/Taipei`. TWSE trades continuously 09:00–13:30 without a lunch break; a 5-minute 13:25–13:30 closing auction window is modeled (`_CLOSING_AUCTION_WINDOW_MINUTES["tw"]=5`, emitting `market_phase = closing_auction`).
- Primary indices provide TAIEX (`^TWII`) and TPEx Index (`^TWOII`).
- Three Institutional Investors flow layer: `TwInstitutionalFetcher` (`data_provider/tw_institutional_fetcher.py`) reads TWSE T86 / TPEx OpenAPI daily net flows across foreign, investment trust, and dealer accounts (unit: **shares**, market-wide daily cache + symbol filtering, ROC calendar conversion tested). Upstream errors, rate limits, empty payloads, or missing fields always fail open without aborting stock analysis; applies strictly to `.TW`/`.TWO`. Data follows Taiwan Government Open Data License v1 (OGDL v1; commercial use & redistribution allowed with attribution).
- `TwInstitutionalFetcher` guards against cache stampedes with single-flight locking and separate TWSE/TPEx circuit breakers; because TPEx OpenAPI serves only the latest trading day, requests with a mismatched explicit date fail open rather than injecting stale wrong-date flows.
- Taiwan financial amounts annotate TWD clearly instead of defaulting to mainland RMB yuan semantics.

Explicit non-goals:

- No real-time quote SLA; Yahoo Finance data may lag or lack fields.
- No full fundamentals, sector leaderboards, or advance/decline breadth; Taiwan market review covers only indices and news below.
- No full Taiwan autocomplete pool yet; `MarketRegion` for alerts and Market Light backend checks remain `cn/hk/us`.
- No TWD FX conversion/cost-basis accounting in Portfolio yet (`tw` positions remain partial-valuation).

Rollback: Remove `tw` market detection, trading calendar registration, YFinance extensions, institutional fetcher/report blocks, TWD currency annotations, and API/Web market enum support.

## Taiwan Market Review: Indices & News (Issue #2482)

- Configure `MARKET_REVIEW_REGION=tw` or pick Taiwan in the Home market-review selector (`cn,tw` subsets supported; `POST /api/v1/analysis/market-review` accepts `{"region":"tw"}` as a one-shot override).
- Reuses existing YFinance primary index routes (`TWII`/`^TWII`, `TWOII`/`^TWOII`) and news search with no new market-data providers or credentials.
- Uses a dedicated Taiwan review profile, strategy, and news queries across Chinese/English reports and Korean prompt instructions. Delayed/partial index failures and missing-data boundary disclosures appear explicitly in reports and share images (preserving all boundary items, including history/portfolio disclosures); when all indices fail, reviews use available news/templates without falling back to A-share substitutes or hallucinating a range-bound call.
- Excludes market breadth, limit-up/down stats, institutional net-flow summaries, total turnover (renders `N/A`), sector rankings, Market Light scores, and alerts; currency displays as TWD.
- With trading-day checks enabled, filters via `XTAI / Asia/Taipei` independently of A-share holidays; history, notifications, context, and share images carry the `tw` label.
- `both` expands to all six markets (`cn,hk,us,jp,kr,tw`), increasing fetch/news/LLM duration; set `cn,hk,us,jp,kr` to keep prior scope. Default stays `cn` without mutating existing configs.

Rollback: Revert the Taiwan market-review commit and remove `tw` from configured regions; requires no DB schema changes and leaves Taiwan stock analysis untouched.

## Japan / South Korea Portfolio & Market Light Boundaries (Issue #1815 Phase 3)

Portfolio accepts JP/KR accounts, trades, and position snapshots while flagging `data_quality=partial` and attaching `realtime_quote_best_effort`, `fx_and_cost_basis_partial`, and `sector_and_risk_metrics_limited` limitations without promising full JPY/KRW FX, cost-basis, market-cap, or concentration accounting.

- Account, trade, cash-ledger, and corporate-action APIs remain available for JP/KR without introducing JPY/KRW FX feeders, fee/lot-size rules, or industry taxonomies.
- Market Light snapshots generated and archived by market reviews (`src/schemas/market_light.py`, `src/market_analyzer.py`, `src/core/market_review.py`) and Market Light alerts (`normalize_market_alert_region()`) remain scoped strictly to `cn` / `hk` / `us`; running market reviews for `jp` / `kr` / `tw` does not emit or archive `market_light` snapshots (only direct on-demand snapshot service helper calls via `src/services/market_light_service.py::normalize_market_region()` accept `cn` / `hk` / `us` / `jp` / `kr`).
- Web alert market dropdown excludes `jp` / `kr` (and `tw`); backend `normalize_market_alert_region()` rejects `jp` / `kr` (and `tw`) with an explicit unsupported error.
- In Web Settings, `MARKET_REVIEW_REGION` is a free-text comma-separated field (allowing `cn,us,jp`, `cn,hk,us`, etc.); this only governs market reviews and does not change Market Light alert enums.
- Existing `cn`, `hk`, `us` settings stay untouched (`both` now covers all six markets; set `cn,hk,us` for pre-JP/KR behavior or `cn,hk,us,jp,kr` for 5-market coverage).
- Configuration persistence remains unchanged: updates use atomic upsert (`ConfigManager.apply_updates`), leaving unsubmitted `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `OPENAI_BASE_URL`, etc. intact with no cleanup or migration branches.
- Compatibility verification references: LiteLLM OpenAI-compatible routing (<https://docs.litellm.ai/docs/providers/openai_compatible>), OpenAI Chat Completions API (<https://platform.openai.com/docs/api-reference/chat/create>), provider compatibility specs in `llm-providers.md`, dependency constraint `litellm>=1.80.10,!=1.82.7,!=1.82.8,<1.99.0` in `requirements.txt`, and tests `tests/test_system_config_service.py::SystemConfigServiceTestCase::test_update_market_review_region_does_not_trigger_runtime_model_cleanup` & `tests/test_config_env_compat.py::test_market_review_region_updates_do_not_change_llm_provider_model_contract`.
- Web UI evidence summary: targeting Market Light in Alerts exposes only CN/HK/US options, and `MARKET_REVIEW_REGION` in Settings renders a comma-separated text field, covered by `AlertRuleForm.test.tsx`, `SettingsField.test.tsx`, and `system_config_i18n.test.ts`.

Rollback: Revert Portfolio `data_quality`/`limitations` and alert enum bounds, or revert the full `jp/kr` market support extension along with this document.
