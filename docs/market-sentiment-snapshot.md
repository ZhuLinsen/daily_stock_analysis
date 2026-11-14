# 市场情绪快照（Market Sentiment Snapshot）

上游 issue #1939 一期（后端）说明文档。该能力在 A 股收盘后按交易日把市场情绪指标**确定性计算并落库**，通过只读 API 查询；LLM 仅预留字段位（`narrative: null`），一期零 LLM 调用。

## 能力概述

- 只做 A 股（`market='cn'`）、**手动触发**、只读查询；不接定时任务、无默认抓取、零后台成本。
- 每个交易日快照按 `(market, trade_date)` 幂等保存，带 `quality_status`（complete/partial）、`completeness`（0~1，必备组粒度）与 `provider_trace`（逐接口取数轨迹）。
- 指标全部为规则计算（无模型），任何指标取不到时输出 `null + missing_reason`，**绝不静默补零**。
- 默认关闭：`MARKET_SENTIMENT_SNAPSHOT_ENABLED=false` 时 `/market-sentiment` 路由不注册（OpenAPI 不可见，请求 404）。

## 口径对照表（14 指标）

通用纪律：任何指标分母为 0/缺失 → 结果 `null` + `missing_reason`（如 `zero_denominator`/`empty_pool`/`missing_prev`），不硬算、不补零。"昨日"一律指**上一交易日**（交易日历解析），非自然日 T-1。

| # | 指标 | 公式 | 分母与剔除 | 数据源接口 | W1 实测结论（2026-11-13，akshare 1.18.97） |
|---|---|---|---|---|---|
| M1 | 涨跌家数差 | `up_count - down_count` | 同 breadth 域，无额外剔除 | `get_market_stats()`（东财→新浪双 fallback） | 新浪源 5578 行全市场：up+down+flat=5570=有效样本，对账通过 |
| M2 | 涨跌比 | `up / down`（down=0 → null + `zero_denominator`） | 同上 | 同上 | 同上 |
| M3 | 涨停家数 | 涨停池行数（主口径） | 涨停池域；价差推算值入 provider_trace 交叉校验 | `ak.stock_zt_pool_em(date)` 全量 | T0=37 行；EM 池历史保留期 T-14 .. T0，T-15 起静默空返回 |
| M4 | 跌停家数 | 跌停池行数 | 跌停池域 | `ak.stock_zt_pool_dtgc_em(date)` | 接口可用（T0=33/T-1=5），**保留不降级**；空池=0 跌停为合法市场态 |
| M5 | 全市场成交额（亿元） | spot 全样本成交额求和 | 同 breadth 域 | `get_market_stats()` | T0=16668.97 亿（新浪源实测） |
| M6 | 成交额环比 | `今日总额 / 上一交易日总额 - 1` | 分母优先回查**快照表自身**上一交易日记录；无记录 → null + `missing_prev` | 快照表回查 + M5 | 冷启动无环比属预期；指数成交额兜底（`stock_zh_index_daily` 无成交额、`index_zh_a_hist` 窗口不可用）验证失败，维持默认不启用 |
| M7 | 炸板率 | `炸板家数 / (涨停家数 + 炸板家数)` | 分母=当日曾封板家数；分母 0 → null | `ak.stock_zt_pool_zbgc_em(date)` | 接口可用（T0=21 行）；实例 21/(37+21)=36.2%，与涨停池口径自洽（曾封板=37+21=58） |
| M8 | 最高板 | `max(涨停池.连板数)` | 涨停池域；空池 → null + `empty_pool` | 同 M3 | `连板数` 为 int；`涨停统计` 为 "X天/Y板" 紧凑串（18/10=18 天 10 板，非连续） |
| M9 | 连板梯队 | `{N: 家数}`，仅连板数≥2 | 涨停池域，同主口径不剔除 | 同 M3 | T0 分布 1板30/2板4/3板2/4板1 |
| M10 | 分板晋级率 | `今日 N 板家数 / 昨日(N-1)板家数`（N=2..最高板） | 分母 0 → 该档 null + `zero_denominator`；昨日池缺失 → 全组 null | 今日+昨日 `stock_zt_pool_em` | 昨日池（T-1）在保留期内 100% 可靠 |
| M11 | 总晋级率 | `今日连板≥2 家数 / 昨日涨停家数` | 分母=昨日池行数；0/缺失 → null | 同上 | 同上 |
| M12 | 昨日涨停今日反馈（收盘口径） | 样本=昨日涨停池全量：`avg/median(涨跌幅)`、`红盘率=涨跌幅>0 占比`、`sample_size` | 分母=样本数并随 payload 明示；样本必须取前一交易日 | `ak.stock_zt_pool_previous_em(date)` | `previous_em(T)` 返回 T-1 涨停股 T 日表现；与 `zt_pool_em(T-1)` 对账 37=37、代码交集 37/37 |
| M13 | 昨日涨停竞价反馈（可选子块） | `avg(竞价涨幅)`、`高开率` | 仅当接口有竞价字段 | 同 M12 | `previous_em` 16 字段**无任何竞价/开盘字段** → 整块省略 + `auction_missing_reason='field_unavailable'`（D3 门触发，预期内降级） |
| M14 | 行业板块强度摘要 | 涨幅 Top5 / 跌幅 Bottom5（名称+涨跌幅） | 东财行业板块全集排名，无剔除 | `get_sector_rankings(n=5)` | 接口现成可用（T0 实测 14.5s 返回） |

### 涨停池域定案（W1）

- **主口径：全量计数，不剔除** ST/北交/新股（保持东财池原貌，不自造口径）；payload 附分解字段 `st_count`/`bse_count`/`new_stock_count`（名称含 ST / 代码首位 8、4、9 / 名称 N 或 C 开头）。北交占比低但不恒为 0（T-7 样本 118 行中 2 只）。
- M8/M9/M10/M11 随主口径同域。

### 涨跌停制度差异（记录节）

| 板块 | 涨跌幅限制 | 备注 |
|---|---|---|
| 沪深主板 | ±10% | ST/*ST 风险警示股 ±5% |
| 创业板 | ±20% | ST 创业板股仍 ±20% |
| 科创板 | ±20% | — |
| 北交所 | ±30% | 无 ST 差异 |
| 新股上市初期 | 无涨跌幅 | 主板/创业板/科创板注册制新股前 5 日、北交所首日无限制 |

含义：跨板块"涨停"阈值不同（5%/10%/20%/30%），涨停/跌停池是东财按各自板块阈值**规则判定的结果**，指标层直接采信池行数，不自行按涨幅判定。

### 指标组与质量态

| metric_status 组键 | 成员指标 | 必备/增强 | 数据源 |
|---|---|---|---|
| `breadth` | M1、M2 | 必备 | spot（get_market_stats） |
| `limit_up_pool` | M3、M4、M8、M9 | 必备 | 涨停池/跌停池 |
| `broken_pool` | M7 | 必备 | 炸板池 |
| `turnover` | M5、M6 | 必备 | spot + 快照表回查 |
| `promotion` | M10、M11 | 必备 | 今日池 + 昨日池（prev_pool） |
| `prev_feedback` | M12（M13 竞价子块省略） | 必备 | previous_em / 昨日池 |
| `sector` | M14 | 增强 | get_sector_rankings |

- `quality_status='complete'` = 6 个必备组全部 ok；任一必备组非 ok → `partial`。增强组 `sector` 缺失**不降级** complete。
- `completeness` = ok 的必备组数 / 6（组粒度，分母固化为 payload 的 `required_groups`）。
- 预期内缺失（`zero_denominator`/`empty_pool`/`missing_prev`/`field_unavailable`）视为组 ok；仅 `source_error`（数据链断裂）降组。

## 触发语义（单一目标 + 时区 + 收盘门）

- 一期**只支持触发"最近已收盘交易日"**这一个目标：按 **Asia/Shanghai 固定时区**解析（不依赖部署主机时区）——now ≥ 15:00 且当日为交易日 → 目标=当日；否则 → 上一交易日。
- 显式传 `trade_date` 时必须严格等于解析目标：不等（含未来日/历史日）→ `400 invalid_target_date`（message 说明当前唯一可触发目标日）；相等 → 与缺省同效。
- 15:00 之前触发目标=上一交易日（收盘后复盘的自然语义）；当日盘中数据绝不成为触发目标、绝不入库。
- 触发为异步后台任务（`202 Accepted` + `task_id`，经 `submit_background_task` 执行）；全局进程内锁防并发触发，锁冲突 `409 snapshot_running`。
- 已有 complete 快照且 `force=false` → `200` 直接返回既有快照摘要 + `superseded_by_existing_complete=true`（不启动任务、零抓取成本）；`force=true` 仅绕过短路、仍受合并规则约束。

## 幂等合并规则（同 (market, trade_date) 重复触发）

1. 无既有行 → 直接 insert（partial 或 complete 均允许）。
2. 新结果 complete → **整体替换** payload/provider_trace/quality_status/completeness（允许同日重算修正）。
3. 新结果 partial、旧行 complete → **不写入**，保留 complete 行（不动 updated_at），响应与日志标注 `superseded_by_existing_complete=true`。
4. 新结果 partial、旧行 partial → **组级填空合并**：旧组 ok 先到先得，新组 ok 填充缺失组并同步 trace；合并后重算 completeness/quality_status（全 ok 可升级 complete）。
5. 并发防重：全局单锁 409；跨进程由 UniqueConstraint 兜底，IntegrityError 重试一次 select-then-merge，仍失败读取既有行幂等返回。

## API（4 端点，前缀 `/api/v1/market-sentiment`）

| 端点 | 语义 | 主要校验/错误码 |
|---|---|---|
| `POST /snapshots` | 手动触发（body 可选 `{trade_date, force}`，camelCase `tradeDate` 兼容） | 202 accepted；200 short_circuited；400 `invalid_date`/`invalid_target_date`；409 `snapshot_running`；503 `trade_calendar_unavailable`；500 `submit_failed` |
| `GET /snapshots` | 日期列表 `limit`（默认 30，1~200）/`offset`（≥0）/`order`（asc/desc） | 400 `invalid_limit`/`invalid_offset`/`invalid_order`；只列实际存在的快照，不插值不补零 |
| `GET /snapshots/{trade_date}` | 详情：完整 payload + provider_trace + quality_status + completeness | 400 `invalid_date`；404 `snapshot_not_found` |
| `GET /trend` | 趋势：`metric` 枚举（advance_decline_diff/turnover_mom/limit_up_count/failure_rate/max_boards/overall_promotion_rate/feedback_avg_change_pct）、`days`（1~366）或 `start_date+end_date` | 400 `invalid_metric`/`invalid_days`/`invalid_date_range`/`invalid_date`；空序列 200 `points:[]` |

趋势边界语义：查询统一 `trade_date <= end_date`（包含端点）；`end_date` 缺省=最新快照日且 days 模式自动钳制 `min(上海今天, 最新快照日)`——未来日期的数据永不入序列；跳空日期保留 gap，不伪造点。（二期分位将采用严格 `trade_date < target_date`，边界语义已在仓储查询构造中固化。）

## 配置键

| 键 | 默认 | 说明 |
|---|---|---|
| `MARKET_SENTIMENT_SNAPSHOT_ENABLED` | `false` | 路由总开关。关闭时 `/market-sentiment` 路由不注册（404）；开启仅暴露只读端点 + 手动触发，零后台成本。路由在进程启动时挂载，**修改需重启**。 |
| `MARKET_SENTIMENT_FETCH_TIMEOUT_SECONDS` | `45` | 池接口（涨停/跌停/炸板/昨日池）单次子进程取数超时（秒），范围 5~300，越界回退默认。 |

两键均已注册 Web 设置（config_registry），帮助文案见设置页；`.env.example` 有中文注释与 Issue 标注。

## 数据源失败行为

- **fail-open**：任一接口超时/异常/空返回只影响自己所属指标组（该组 `metric_status` 降级、payload 置 `null + missing_reason`），其余组不受影响；provider_trace 逐接口落一条 `{metric_group, provider, api, params, status: ok|timeout|error|empty, elapsed_ms, error, fetched_at}`。
- **partial 而非失败**：必备组任一非 ok → 快照仍落库为 `partial` + `completeness<1`，不抛错、不回滚。
- **不补零**：缺失指标一律 `null`，绝不以 0 顶替（0 只在真实为 0 时出现，如跌停池空=0 跌停）。
- **交易日历不可用** → 触发接口 `503 trade_calendar_unavailable`（后端依赖暂时性失败、可重试）；job 内部对 prev 日期解析 fail-open（prev_trade_date 置空，依赖昨日池的组整组 `missing_reason`）。
- **历史保留期**：EM 池接口仅保留 T-14 及以内；超期表现为静默空返回，按行数判定为 `empty`，昨日池（T-1）实测无风险。
- **单源可复现验证**：触发前 stub 任一池接口使其抛 `TimeoutError` 重跑，可复现 partial 快照（该组 missing_reason 齐全、无 0 值顶替）。

## 回滚说明

- 变更纯增量：新增 `market_sentiment_snapshots` 表（既有表零变更）+ 新增路由/服务/取数模块 + 两个新配置键（默认关闭）。回滚 = revert 对应提交即可。
- 已产出的快照表**可保留无害**（默认关闭后无任何代码路径读写它）；如需彻底清理可执行：

```sql
DROP TABLE IF EXISTS market_sentiment_snapshots;
```
