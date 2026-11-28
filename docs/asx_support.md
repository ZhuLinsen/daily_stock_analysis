# Australian ASX market support / 澳大利亚 ASX 市场支持

## Explicit identity / 显式市场代码

Use Yahoo ASX symbols with the `.AX` suffix: `A2M.AX`, `NXT.AX`, `BHP.AX`, `GAME.AX`, `A200.AX`.

The shared symbol resolver maps ASCII alphanumeric bases of one to six characters ending `.AX` to market **`au`**, not `us` or `cn`. Image-import plain-text fallback preserves valid `.AX` symbols and rejects malformed symbol-like tokens instead of extracting bare US fragments; sentence punctuation can delimit tokens. 图片导入纯文本回退保留有效 `.AX` 代码并拒绝格式错误的类符号 token，而非提取裸美股片段；句子标点可分隔 token。 Recognition is syntactic, not proof of a current listing or Yahoo coverage. Bare symbols keep their existing interpretation: `NXT` and `GAME` can refer to unrelated US companies and are never automatically rewritten to Australian securities.

澳股必须带 `.AX`；市场标识为 `au`。支持含数字代码，例如 `A2M.AX` 与 `A200.AX`。裸代码不能自动当作澳股。

## Data and reports / 数据与报告

- Australian daily history, quotes and market-index requests use the existing Yahoo Finance provider. Missing ASX data does not fall back to a Chinese provider, a bare US symbol, or an unknown provider.
- Quote currency remains provider metadata. Preserve financial-statement currency separately: an AUD-quoted stock may report financial statements in NZD or another currency. AUD/NZD have explicit Chinese display labels.
- Provider instrument type is retained as optional `quote_type` metadata. Prompts distinguish company stocks from ETFs using metadata rather than guessing from a ticker/name.
- System prompts identify Australian ASX securities and exclude US/China-specific market assumptions. Australian market reviews use S&P/ASX 200 (`^AXJO`) and All Ordinaries (`^AORD`). Unsupported breadth, flow, sector-ranking and news data must remain unavailable, not invented.
- ASX history fetch failure or cached bars from unsupported providers stops the stock analysis. Legacy rows are not silently deleted; users must explicitly repair contaminated caches before reuse.
- Existing reports are not retroactively repaired or validated by changing market detection.
- Cross-asset context remains opt-in (`CROSS_ASSET_CONTEXT_ENABLED=true`, default off). When enabled for `au`, its risk-appetite header identifies `澳股` in Chinese and `Australia ASX` in the English framing used by English/Korean prompts, including degraded/unknown signals; it must not fall back to `A股` / `A-share`.

缺失或污染数据不能用“观望”评分代替。财务报表币种不可随报价币种强制重标。跨资产上下文默认关闭；开启后，澳股风险偏好标题使用“澳股 / Australia ASX”，信号不足时也不能回退为“A股 / A-share”。

## Calendar / 交易日历

Market `au` uses `exchange_calendars` **XASX** and **Australia/Sydney**, including the calendar's holidays, early-close sessions and daylight saving.

Regular-session phases approximate exchange hours, not exact randomized opening or closing-auction boundaries. Reuse of an Australian same-day daily bar waits conservatively until at least 16:11 Sydney, including early-close days. This is not proof of provider daily-bar finality; explicit approximation/finality warnings remain in the context.

Official reference: https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours

## Usage / 使用

With the existing model/provider configuration, run from the repository root:

```bash
MARKET_REVIEW_REGION=au python main.py --stocks A2M.AX,NXT.AX,GAME.AX,XMET.AX --workers 1 --no-notify
# Fetch-only verification, without model inference or notifications:
python main.py --stocks BHP.AX,A200.AX --dry-run --workers 1 --no-market-review --no-notify
```

`MARKET_REVIEW_REGION=au` and comma-separated market subsets are supported. `both` now expands to AU plus the existing six markets. The default region remains `cn`; an explicit Australian stock list does not silently rewrite a user's configured market-review region. Configure the recap region explicitly when running ASX analysis.

## Compatibility and limits / 兼容性与限制

- This is backend/CLI support, not complete web-chat support: the free-text web-chat tokenizer can still split or misidentify `.AX` tokens. Use explicit CLI symbols; do not rely on chat parsing for AU.
- The web UI offers AU in the portfolio account form (default currency AUD), the decision-signal market filter and the market-review region selector. The region selector serializes its exact selection rather than `both`.
- Existing CN/HK/US/JP/KR/TW routing is preserved. AU is added to backend market schemas and capability reporting; no database migration or dependency addition is required.
- Public Yahoo data can be delayed and is not an executable broker quote. Yahoo does not guarantee coverage of every ASX security. Missing-symbol handling must remain fail-closed.
- AU does not enable unsupported Market Light/breadth feeds. Portfolio valuation retains explicit partial-support limitations.
- News search still requires the existing search-provider configuration. Correct routing does not establish model recommendation accuracy.
- Relevant deterministic tests: `tests/test_asx_routing.py`, `tests/test_asx_report_context.py`, `tests/test_asx_context_calendar.py`, plus existing symbol, provider, calendar and market-review suites.
- This change does not include broker authentication, trading actions, user-specific launchers, schedules, credentials or saved research reports.
