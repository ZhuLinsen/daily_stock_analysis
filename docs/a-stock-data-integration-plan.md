# a-stock-data 免费源迁移计划

本项目不直接复制 `a-stock-data/SKILL.md`，而是迁移其中可工程化的抓取方法和稳定零 key 端点。

## 已迁移的工程方法

- 零 key 数据源优先，降低运行门槛。
- 不把新闻、热点、公告强塞进日线 `BaseFetcher`，而是单独提供 A 股情报源适配器。
- 统一 HTTP client：
  - `requests.Session` 复用连接。
  - 默认浏览器 UA。
  - 有界超时。
  - 429 / 5xx 自动重试。
  - 东方财富域名串行限流、随机抖动。
- fail-open：免费情报源失败时记录日志并返回空列表，不中断日报主流程。
- 输出结构保留 `source` 字段，后续进入 LLM prompt 时可做来源标注。

## 第一批已接入源

| 能力 | 方法 | 来源 | 是否 key | 价值 |
|---|---|---|---|---|
| 7×24 快讯 | `DataFetcherManager.get_free_market_news()` | 财联社 CLS | 否 | 补市场突发消息，与东财快讯互备 |
| 强势股题材归因 | `DataFetcherManager.get_free_hot_reasons()` | 同花顺热点 | 否 | 补“为什么涨”的人工题材标签 |
| 公告增强 | `DataFetcherManager.get_free_announcements()` | 巨潮 CNINFO | 否 | 补正式披露公告与 PDF 链接 |

## 第二批已接入 fallback

| 能力 | 方法 | 来源 | 是否 key | 触发场景 |
|---|---|---|---|---|
| 日度资金流备用源 | `DataFetcherManager.get_fallback_fund_flow()` | 新浪 | 否 | 东财资金流失败、风控或返回空 |
| 龙虎榜官方备用源 | `DataFetcherManager.get_fallback_dragon_tiger()` | 上交所 / 深交所官方 | 否 | 东财龙虎榜失败或需官方交叉验证 |
| 公告备用源 | `DataFetcherManager.get_fallback_announcements()` | 深交所官方 / 东财公告 PDF | 否 | 巨潮公告失败或返回空 |

## 新增配置

这些开关默认启用；生产环境可在 `.env` 中关闭。

```env
FREE_A_STOCK_SOURCES_ENABLED=true
CLS_TELEGRAPH_ENABLED=true
THS_HOT_REASON_ENABLED=true
CNINFO_ANNOUNCEMENT_ENABLED=true
SINA_FUND_FLOW_FALLBACK_ENABLED=true
OFFICIAL_DRAGON_TIGER_FALLBACK_ENABLED=true
ANNOUNCEMENT_FALLBACK_ENABLED=true

FREE_SOURCE_TIMEOUT=15
EASTMONEY_MIN_INTERVAL=1.2
EASTMONEY_JITTER=0.5
EASTMONEY_MAX_RETRIES=3
```

## 下一批建议

1. 将公告 fallback 串到 CNINFO 失败路径，而不是只暴露管理器方法。
2. 将资金流 fallback 串到个股资金流分析失败路径。
3. 将龙虎榜 fallback 串到主龙虎榜获取失败路径。
4. 将第一批结果注入 `DailyMarketContext` 和个股 `news_context`。

## 验收标准

- 离线单元测试覆盖 schema normalization、签名、orgId fallback。
- Docker 内无需新增付费 key。
- 新源失败不影响 `server` / `analyzer` 健康状态。
- 后续进入日报 prompt 时，必须带来源字段，避免 LLM 混淆事实来源。
