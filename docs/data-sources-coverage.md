# Data Source 接口覆盖矩阵

> 最近更新：2026-07-23（伴随 data_provider 接口补齐 PR）
> 关联 spec：`docs/superpowers/specs/2026-07-23-data-provider-free-source-coverage-design.md`

本文件记录 `data_provider/` 中每个 fetcher 的接口实现情况，供日常开发、数据源选型、故障排查参考。

## 接口清单

`BaseFetcher`（`data_provider/base.py`）定义的可选/必选接口：

| 接口 | 说明 | 调用入口 |
|---|---|---|
| `_fetch_raw_data` | 日线原始数据（abstract） | `DataFetcherManager.get_daily_data` |
| `_normalize_data` | 列名标准化（abstract） | 同上 |
| `get_main_indices` | 大盘指数实时 | `DataFetcherManager.get_main_indices` |
| `get_market_stats` | 涨跌家数 / 成交额 | `DataFetcherManager.get_market_stats` |
| `get_sector_rankings` | 板块涨跌榜 | `DataFetcherManager.get_sector_rankings` |
| `get_concept_rankings` | 概念涨跌榜 | `DataFetcherManager.get_concept_rankings` |
| `get_hot_stocks` | 人气股榜 | `DataFetcherManager.get_hot_stocks` |
| `get_limit_up_pool` | 涨停池 / 连板梯队 | `DataFetcherManager.get_limit_up_pool` |
| `get_realtime_quote` | 个股实时行情 | `DataFetcherManager.get_realtime_quote` |
| `get_chip_distribution` | 筹码分布 | `DataFetcherManager.get_chip_distribution` |
| `get_stock_name` | 股票中文名 | `DataFetcherManager.get_stock_name` |
| `get_stock_list` | 全市场列表（批量名称） | `DataFetcherManager.batch_get_stock_names` |
| `get_belong_board` | 所属板块 | `DataFetcherManager.get_belong_boards` |
| `prefetch_realtime_quotes` / `prefetch_daily_klines` | TickFlow 批量预取 | `DataFetcherManager.prefetch_*` |

## Free 源接口矩阵

| 接口 | efinance | tencent | akshare | pytdx | baostock | yfinance |
|---|---|---|---|---|---|---|
| `_fetch_raw_data` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `_normalize_data` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `get_main_indices` | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ |
| `get_market_stats` | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `get_sector_rankings` | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `get_concept_rankings` | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `get_hot_stocks` | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `get_limit_up_pool` | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `get_realtime_quote` | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ |
| `get_chip_distribution` | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `get_stock_name` | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ |
| `get_stock_list` | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ |
| `get_belong_board` | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |

**单点故障接口**（只剩 1 个 fetcher 实现，且 free 源侧没有替代方案）：
- `get_hot_stocks` —— 仅 akshare；efinance 底层无对应 API，无法补
- `get_limit_up_pool` —— 仅 akshare；efinance 底层无对应 API，无法补
- `get_chip_distribution` —— 仅 akshare（A股）；付费源 tushare 有但需高级积分

## 付费 / Key 源接口需求

| 数据源 | 需要的凭据 / 积分 | 实现的关键接口 | 适用市场 |
|---|---|---|---|
| Tushare | `TUSHARE_TOKEN` + 各接口对应积分（基础 2000、进阶 5000、高级 10000+） | `get_realtime_quote`（5000+）、`get_chip_distribution`（10000+）、`get_main_indices`、`get_market_stats`、`get_sector_rankings`、`get_stock_name`、`get_stock_list` | A 股、港股 |
| TickFlow | `TICKFLOW_API_KEY` | 几乎所有非日线接口（`get_realtime_quote`、`get_main_indices`、`get_market_stats`、`get_sector_rankings`、`get_stock_name`、`get_stock_list`）以及 `prefetch_realtime_quotes`、`prefetch_daily_klines` | A 股 |
| Longbridge | `LONGBRIDGE_APP_KEY` / `LONGBRIDGE_APP_SECRET` / `LONGBRIDGE_ACCESS_TOKEN`（OAuth 或 Legacy 凭据） | `get_realtime_quote`、`get_stock_name` | 港股、美股 |
| Finnhub | `FINNHUB_API_KEY` | `get_realtime_quote`、`get_stock_name` | 美股 |
| AlphaVantage | `ALPHAVANTAGE_API_KEY` | `get_realtime_quote`、`get_stock_name` | 美股 |

> **积分等级**以 Tushare 官方文档为准，会随时间变化。本表只是粗略指引，调用前请确认对应接口的积分要求。

## manager failover 策略

`DataFetcherManager` 总是按 fetcher.priority 升序遍历可用的 fetcher，第一个返回非空数据的胜出。优先级由各 fetcher 的 `__init__` 决定，运行时可通过 `add_fetcher` / config 调整。

特别规则：
- **港股 / 美股**：优选 Longbridge（配置凭据后），否则 YfinanceFetcher（美股）/ AkshareFetcher(source="hk", 港股)。
- **美股指数**：永远 YfinanceFetcher 首选（Longbridge 不提供指数 K 线）。
- **TickFlow**：仅在配置 `TICKFLOW_API_KEY` 时启用，priority 默认 2。
- **Tushare**：仅在配置 `TUSHARE_TOKEN` 时启用，会按配置自动调整 priority。

## 维护建议

- 新增 fetcher：补完 abstract 方法 + 至少 `get_realtime_quote` + `get_stock_name`。
- 新增接口：先在 `BaseFetcher` 加 default `return None`，再在需要的 fetcher 里覆盖。
- 接口矩阵更新：每次 fetcher 增删接口，同步更新本文件 `Free 源接口矩阵` 表格。