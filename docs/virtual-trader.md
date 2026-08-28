# 虚拟交易员（Virtual Trader）

本地模拟盘：系统维护一个虚拟账户（默认 100 万人民币初始资金，A/港/美按 40%/30%/30% 分配，各市场预留 30% 备用金），每个交易日收盘后自动拉取真实日线行情，按**均值回归策略**决定虚拟买入/卖出，以真实收盘价模拟成交并计入交易成本。每笔策略性交易都会记录一条**预测**（方向 + 目标价 + 窗口），T+N 后自动对照真实走势标记命中/未命中，长期统计命中率验证策略是否有效。

> 全程不涉及真实资金与券商账户；数据全部存本地 SQLite。该功能默认关闭（opt-in），不影响现有部署。

## 快速开始

1. `.env` 中设置：

```env
VIRTUAL_TRADER_ENABLED=true
```

2. 启动常驻进程（或随 Web 服务一起运行，见下文"运行方式"）：

```bash
python main.py --virtual-trader
```

3. 首次运行会自动完成初始建仓：A 股（600519 / 300750）、港股（hk00700 / hk09988）、美股（AAPL / NVDA）等权配置，剩余资金留作备用金。
4. 打开 Web 页面 `虚拟交易` 查看持仓、净值曲线、交易流水与预测命中率；也可点击「立即运行」手动触发一轮。

## 运行方式

| 方式 | 命令/入口 | 说明 |
|---|---|---|
| 独立常驻进程 | `python main.py --virtual-trader` | 每 30 分钟检查各市场是否已收盘待执行；不跑全量分析、不发送通知 |
| 随 Web 服务 | `python main.py --serve` 且 `SCHEDULE_ENABLED=true` | 定时调度器挂载同一后台任务（需 `VIRTUAL_TRADER_ENABLED=true`） |
| 手动触发 | Web 页面「立即运行」或 API `POST /api/v1/virtual-trader/run` | 各市场幂等，当日已执行会跳过 |

每个市场的执行时机由交易日历自动判定：`get_effective_trading_date` 在收盘后归属当日、盘中归属上一交易日；因此重复触发不会重复成交（`(run_date, market)` 唯一约束保证幂等）。美股收盘为北京时间次日凌晨，`trade_date` 自动归属正确的交易日。

## 开机自启（Windows）

以管理员或当前用户身份运行一次：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_virtual_trader_task.ps1
```

脚本会创建 Windows 任务计划 "DSA Virtual Trader"，开机延迟 1 分钟启动常驻进程（进程崩溃自动重启）。移除任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_virtual_trader_task.ps1 -Remove
```

## 策略规则

纯技术指标、零 LLM 调用。指标基于 120 根日线（DB 缓存优先、网络兜底）：布林带（20, 2σ）+ 复用 `StockTrendAnalyzer` 的 RSI(6)/MACD(12,26,9)/MA。

- **买入**（使用备用金）：收盘价跌破布林下轨 且 RSI ≤ 30 超卖，同时 MA60 斜率向上（避免下跌趋势接飞刀）；预测目标价 = 布林中轨，窗口 10 个交易日。
- **卖出**（按优先级）：
  1. 止损：收盘价低于成本 8%（可配）；
  2. 回归兑现：触及布林上轨 或 20 日乖离 ≥ 8%；
  3. 动量衰竭：RSI ≥ 70 且 MACD 死叉。
- **仓位约束**：单票市值 ≤ 总资产 15%；单次买入不超过现金的 90%；A 股/港股整手（100 股）取整且不允许超出可用资金。
- **交易成本模拟**：A 股佣金万 2.5（最低 5 元）+ 卖出印花税 0.05%；港/美简化为成交额 0.1%。

## 配置项

全部有默认值，不配置即可运行：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VIRTUAL_TRADER_ENABLED` | `false` | 功能总开关（后台任务是否注册） |
| `VIRTUAL_TRADER_INITIAL_CASH_CNY` | `1000000` | 初始总资金（CNY） |
| `VIRTUAL_TRADER_CASH_RESERVE_PCT` | `30` | 初始备用金比例（%） |
| `VIRTUAL_TRADER_UNIVERSE` | 空 | 额外候选池（逗号分隔）；默认候选池 = 自选股 STOCK_LIST + 内置蓝筹组合 |
| `VIRTUAL_TRADER_MAX_POSITION_PCT` | `15` | 单票市值占总资产上限（%） |
| `VIRTUAL_TRADER_STOP_LOSS_PCT` | `8` | 止损阈值（%） |
| `VIRTUAL_TRADER_FX_USD_CNY` | `7.2` | 美元折 CNY 固定汇率（净值展示用） |
| `VIRTUAL_TRADER_FX_HKD_CNY` | `0.92` | 港币折 CNY 固定汇率（净值展示用） |

## 数据表

同库新增 6 张表（前缀 `virtual_trader_`）：`accounts`（账户/三币种现金）、`positions`（持仓）、`trades`（成交流水）、`predictions`（预测与复盘结果）、`snapshots`（每日净值快照，账户+日期唯一）、`runs`（每日运行日志，市场+日期唯一，用于幂等与排障）。

## API

统一前缀 `/api/v1/virtual-trader`（管理员会话鉴权，同其他设置类接口）：

- `GET /account` — 账户、持仓与最新估值（估值价取最近快照，不发网络请求）
- `GET /trades`、`GET /predictions` — 流水与预测记录（分页）
- `GET /equity-curve` — 净值曲线数据
- `GET /stats` — 预测命中率、买卖笔数、胜率、累计已实现盈亏
- `POST /run` — 手动触发（`{"market": "cn", "force": false}` 可选指定单一市场）
- `POST /reset` — 重置账户（必须显式传 `{"confirm": true}`），清空全部数据并重新初始建仓

## 已知简化模型

- 汇率为固定配置值（非实时汇率），仅影响总净值折算展示；
- 成交价使用当日收盘价，未建模滑点与盘口深度；
- 港/美费率为简化的单一比例；
- 预测评估基于 DB 中缓存的后续日线（`StockRepository.get_forward_bars`），若数据缺失标记为 `unable` 并在下次运行重试。
