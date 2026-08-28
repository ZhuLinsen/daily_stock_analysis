# 大师工具包（Master Toolkit）

本专题收口三个面向“大师级能力”的新特性：交易日记/复盘、市场温度计、大师视角多空辩论。
三者均无新增环境变量，开箱即用；全部走现有 `/api/v1/*` 管理员鉴权（`ADMIN_AUTH_ENABLED=true` 时需要有效管理员会话 Cookie）。

## Web UI 入口

前端新增三个页面并已接入侧边导航：

- `/journal`：交易日记（记录成交 + 复盘统计 + 列表删除）。
- `/market-temperature`：市场温度计 + 大盘仪表盘（实时全市场温度、指数、涨跌结构、热门板块/概念、板块资金流、候选观察池、历史、本地自选股兜底）。
- `/master-debate`：大师视角多空辩论（发起辩论 + 分歧度/共识 + 六位大师立场 + 历史）。

## 1. 交易日记 / 复盘（`/api/v1/trade-journals`）

把“计划 → 执行 → 记录 → 复盘”闭环补上：记录真实成交，自动对齐 AI 决策信号计算纪律分，并按 FIFO 计算已实现盈亏。

### 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/trade-journals` | 记录一笔交易（buy/sell，支持 add/reduce/加仓/减仓 别名） |
| GET | `/api/v1/trade-journals` | 分页查询，支持 market/code/side/strategy/emotion/日期过滤 |
| GET | `/api/v1/trade-journals/{id}` | 查询单笔 |
| PATCH | `/api/v1/trade-journals/{id}` | 修改单笔 |
| DELETE | `/api/v1/trade-journals/{id}` | 删除单笔 |
| GET | `/api/v1/trade-journals/{id}/discipline` | 评估该笔与关联信号的纪律对齐（aligned/contradicted/neutral/no_signal） |
| GET | `/api/v1/trade-journals/pnl?market=&code=` | 按 FIFO 计算某持仓已实现盈亏 |
| GET | `/api/v1/trade-journals/review` | 复盘统计（胜率/盈亏比/纪律分/情绪分布） |

### 语义

- 买入时费用摊入成本（每股成本 = 价格 + 费用/数量），卖出时费用从净收益扣除，FIFO 匹配计算已实现盈亏。
- `discipline`：买入对齐 buy/add 信号、卖出对齐 reduce/sell/avoid 信号为 `aligned`；反向为 `contradicted`；hold/watch/alert 或未关联信号为 `neutral`/`no_signal`。
- `review` 的纪律分 = (按计划执行数 + 对齐信号数) / (声明计划数 + 关联信号数) × 100。

### 示例

```json
POST /api/v1/trade-journals
{
  "code": "600519", "name": "贵州茅台", "market": "cn",
  "side": "buy", "quantity": 100, "price": 1500,
  "fee": 5, "trade_date": "2026-01-05",
  "thesis": "回踩 MA20 支撑，基本面未变", "strategy": "trend",
  "emotion": "calm", "plan_followed": true, "linked_signal_id": 123,
  "tags": ["趋势", "价值"]
}
```

## 2. 市场温度计 / 恐惧贪婪指数（`/api/v1/market-temperature`）

将多个市场宽度/资金/情绪子指标合成为一个 0-100 温度：0 = 极度恐惧，100 = 极度贪婪。

### 子指标与权重

| key | 名称 | 权重 | 归一化 |
| --- | --- | --- | --- |
| breadth | 市场宽度 | 0.25 | 涨家 / (涨家+跌家) × 100 |
| limit | 涨跌停比 | 0.20 | 涨停 / (涨停+跌停) × 100 |
| high_low | 新高新低比 | 0.20 | 新高 / (新高+新低) × 100 |
| northbound | 北向资金 | 0.10 | 50 + 净流入/100 亿 × 50 |
| margin | 两融余额 | 0.10 | 50 + 单日变化%/10 × 50 |
| turnover | 换手率 | 0.05 | 50 + 换手%/10 × 50 |
| index | 指数涨跌 | 0.10 | 50 + 涨跌%/10 × 50 |

缺失维度会被剔除，剩余权重归一化；无任何有效维度时按中性 50 计。

### 温度区间

| 分值 | label_key | 标签 |
| --- | --- | --- |
| 0-20 | extreme_fear | 极度恐惧 |
| 20-40 | fear | 恐惧 |
| 40-60 | neutral | 中性 |
| 60-80 | greed | 贪婪 |
| 80-100 | extreme_greed | 极度贪婪 |

### 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/market-temperature` | 传入宽度快照计算并持久化（按 market+trade_date upsert） |
| GET | `/api/v1/market-temperature` | 温度历史 |
| GET | `/api/v1/market-temperature/latest?market=` | 最新温度（无快照时返回 `null`） |
| POST | `/api/v1/market-temperature/compute?market=cn` | 从实时数据源抓取**全市场**涨跌家数/涨跌停/指数涨跌，计算并落库（当前仅 A 股） |
| POST | `/api/v1/market-temperature/dashboard?market=cn` | 大盘仪表盘：温度 + 指数 + 涨跌结构 + 热门板块/概念 + 板块资金流排行 + 候选观察池（仅 A 股，可能耗时数十秒） |
| POST | `/api/v1/market-temperature/from-database?market=` | 基于本地自选股日线兜底计算宽度温度（每只股票各取最新一条，结果落库） |

**数据来源优先级**：`/compute`（实时全市场宽度，复用 `MarketAnalyzer.get_market_overview()` 的数据源，仅 A 股）> POST 手动快照（支持全部市场与全部维度）> `/from-database`（本地自选股兜底，样本有限，结果中会标注来源与样本提示）。三类计算结果都会以 market+trade_date upsert 落库， `latest` 与历史立即可见。

**大盘仪表盘（`/dashboard`）**：一次聚合温度、主要指数、涨跌家数/涨跌停/两市成交额、板块与概念涨跌榜、板块主力资金净流入排行、候选观察池。各分块独立 fail-open，数据源不可用时对应分块留空并在 `notes` 中说明（例如部分网络环境下东财资金流接口不可达）。候选观察池取当日涨幅前列行业板块的成份股领涨股（每板块至多 2 只、共至多 6 只，过滤 ST/退市、跨板块去重），仅为数据观察结果，不构成投资建议。

`from-database` 仅在本地 `stock_daily` 最新交易日的全量涨跌家数基础上计算宽度，作为无外部广度数据源时的兜底。

## 3. 大师视角多空辩论（`/api/v1/master-debate`）

让六位投资大师各自对同一标的给出立场与论据，再聚合成多空分歧度。

### 与会大师

| id | 大师 | 视角 |
| --- | --- | --- |
| warren_buffett | 巴菲特 | 价值投资：护城河/现金流/估值安全边际 |
| george_soros | 索罗斯 | 反身性：预期与基本面的反馈与拐点 |
| jesse_livermore | 利弗莫尔 | 趋势与关键点位：顺势 + 严格止损 |
| peter_lynch | 彼得林奇 | 成长与常识：成长性/PEG/身边常识 |
| william_oneil | 欧奈尔 | CANSLIM：盈利加速度/新高/机构认同 |
| chan_theory | 缠论 | 结构买卖点：中枢/级别/背驰 |

### 聚合口径

- `consensus`：多数立场；并列时取 `neutral`（分歧）。
- `divergence` = round(100 × (1 − 多数派占比))，衡量分歧程度。
- `conviction` = round(100 × 多数派占比)，衡量共识强度。

### 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/master-debate` | 发起辩论（需已配置 LLM；可传 `context` 或 `analysis_history_id` 复用历史报告） |
| GET | `/api/v1/master-debate` | 辩论历史 |
| GET | `/api/v1/master-debate/{id}` | 单次辩论记录 |

辩论依赖大模型生成（复用现有 `StockAnalyzer.generate_text` 入口与渠道配置）；未配置 LLM 时返回 400 并说明原因。

**LLM 稳健性降级链**：发起辩论会先带上最近一次个股分析作为上下文；若该渠道对长 prompt 返回空内容或坏 JSON，自动降级为无上下文重试（仅基于标的与市场常识），每级各含一次空响应重试。全部失败时返回 400 并附可操作提示（检查/更换模型渠道），不再出现 500。

## 数据模型

三张新表由 SQLAlchemy `create_all` 自动创建，无需手工迁移：

- `trade_journal_entries`：交易日记条目。
- `market_temperature_snapshots`：市场温度快照（market+trade_date 唯一）。
- `master_debate_records`：辩论记录。

## 测试

```bash
python -m pytest tests/test_trade_journal_service.py tests/test_market_temperature_service.py tests/test_master_debate_service.py -q
```
