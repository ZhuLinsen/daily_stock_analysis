# A 股收盘情绪快照

手动触发后，服务计算最近一个已收盘交易日的情绪指标并保存至现有 SQLite。定时任务、Web 页面及 LLM 总结属于后续阶段。

## 使用方法

运行 `python main.py --serve-only --host 127.0.0.1 --port 8000`。接口继承现有 API 的管理员认证设置。

| 接口 | 行为 |
| --- | --- |
| `POST /api/v1/market-sentiment/snapshots` | 返回 HTTP 202、`task_id`、`trace_id` 和按北京时间解析的目标交易日。一期接受最近一个已收盘交易日 |
| `GET /api/v1/market-sentiment/tasks/{task_id}` | 查询后台任务状态、进度和消息。落库成功会返回 `completed` 和情绪快照摘要 |
| `GET /api/v1/market-sentiment/snapshots` | 查看已保存的快照，可传 `end_date` 和 `limit` |
| `GET /api/v1/market-sentiment/snapshots/{trade_date}` | 查看单日指标及来源 |
| `GET /api/v1/market-sentiment/trend?end_date=2026-11-13&limit=30` | 查询目标日之前的 10、30 或 60 个实际交易日 |

相同交易日重复生成会返回 `unchanged` 并保留现有快照。单个服务进程同时执行一个情绪任务。并发提交返回 HTTP 409。任务失败时查询状态返回 `failed`。日期晚于已收盘交易日时，生成和历史查询均返回 HTTP 422。交易日历不可用时返回 HTTP 503。

接口在项目的 OpenAPI 中声明响应模型，并使用统一的 `error` 和 `message` 错误字段。例如并发时返回 `market_sentiment_in_progress`，日历不可用时返回 `trade_calendar_unavailable`。通用分析任务列表可按同一个 `task_id` 查到任务状态，情绪指标从快照接口读取。

## 指标与来源

- 涨停与跌停家数取供应商已核实的收盘涨跌停池。涨停、炸板、跌停和昨日涨停数据目前由 [东方财富涨停板行情](https://quote.eastmoney.com/ztb/detail) 提供。请求核对交易日期、记录总数和股票代码唯一性。经核实的空池可计为零。接口失效或缺失时保留 `null`，不会将现货价格推算的涨跌停数写入股票池指标。
- 炸板率为炸板家数除以曾触及涨停家数。前提为当天涨停池和炸板池均有效且互不重叠。分母为零时比例为空。
- 上一交易日的候选股票与按上一交易日请求的实际涨停池逐只核对代码和板数，再检查目标日报送的板数可连续衔接。晋级分子来自相应昨日候选中今天继续封板的股票。东方财富的历史涨停池响应有时会在 `qdate` 回显目标日。这样的非空响应仅用于和日期已核实的昨日候选逐只对账，响应日期保留在 `provider_trace`。
- 涨跌平家数、上涨占比和成交额复用上游 `DataFetcherManager.get_market_stats()` 的多源回退。目标日当天收盘后请求新行情，跳过 Efinance 进程内的共享实时缓存。来源记录包含实际适配器、服务器发起请求的时间 `requested_at` 和取得统计值的时间 `collected_at`。上游聚合统计没有可独立核验的供应商交易日期，数据覆盖以适配器为准。较早交易日只使用有日期的池数据。
- 升级前保存的快照如果缺少市场统计的采集时间，读取时将该组指标置空并标为 `freshness_unverified`，快照显示为 `partial`。已验证的股票池指标仍可查询，SQLite 行保留原始记录。

可用组独立返回。部分指标无法验证时，快照可保存为 `partial`。目标日涨停池和市场涨跌统计均没有可用数据时，生成任务失败。趋势结果包含完整交易日窗口、缺失日期及不同指标版本的日期。市场涨跌统计可能来自不同适配器，跨来源比较时应检查 `provider_trace.market_stats`。

## 验证与回滚

```bash
python -m pytest -q tests/test_market_sentiment.py
```

测试用合成数据验证源失败与回退、真实后台任务状态、SQLite 落库和按交易日查询。回滚代码可保留新增的 `market_sentiment_snapshots` 表。
