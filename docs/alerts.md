# 实时告警中心

本文档记录 Issue #1202 告警中心的运行基线、数据契约、分阶段实现范围和兼容边界。

## 当前基线

当前运行时告警由 `src/services/alert_worker.py` 中的后台 worker 统一调度，底层规则评估复用 `src/services/alert_service.py` 与 `src/agent/events.py` 中的 EventMonitor 规则模型。

- 配置入口：`AGENT_EVENT_MONITOR_ENABLED`、`AGENT_EVENT_MONITOR_INTERVAL_MINUTES`、`AGENT_EVENT_ALERT_RULES_JSON`。
- 运行入口：`main.py` 在 schedule 模式中注册 `agent_event_monitor` 后台任务；后台 worker 每轮读取持久化 active rules，并继续兼容 legacy `AGENT_EVENT_ALERT_RULES_JSON`。
- 通知投递：触发后复用 `NotificationService.send(..., route_type="alert")`，继续遵守通知网关的 alert 路由配置。
- Web/System 配置校验：`src/services/system_config_service.py` 会对 `AGENT_EVENT_ALERT_RULES_JSON` 做 JSON 与规则语义校验。

当前 runtime 支持三类规则：

| `alert_type` | 方向字段 | 阈值字段 | 当前语义 |
| --- | --- | --- | --- |
| `price_cross` | `direction`: `above` / `below` | `price` | 实时价格上破或下破固定价格 |
| `price_change_percent` | `direction`: `up` / `down` | `change_pct` | 实时涨跌幅达到指定百分比 |
| `volume_spike` | - | `multiplier` | 最新成交量超过近 20 日均量的指定倍数 |

`sentiment_shift`、`risk_flag`、`custom` 等类型只作为未来扩展占位；当前运行时不接受这些类型作为可执行规则。

## Legacy 配置兼容

`AGENT_EVENT_ALERT_RULES_JSON` 作为 legacy 运行时规则来源继续保留，不自动迁移、删除、覆盖或改写用户已有 `.env` / Web 配置。

- 空字符串或空数组表示未配置 legacy 规则；schedule 模式仍会注册后台 worker，以便后续 API 创建的持久化 active rules 无需重启即可被评估。
- Web/System 配置保存时执行严格校验，JSON 无效、字段缺失、方向非法、阈值非法或 unsupported rule type 都应返回配置错误。
- 运行时加载时允许跳过单条无效规则，剩余有效规则继续工作，避免单条配置破坏整个 schedule 进程。
- 当前 worker 使用进程内 fingerprint 避免持续触发条件重复推送；这不是告警中心冷却模型，也不提供跨进程或重启后的冷却状态。

## 数据契约

以下契约用于后续 P1+ API、worker、Web 和存储实现对齐。P0 只定义字段和语义边界，不代表当前已经存在这些持久化实体。

### `alert_rule`

可管理的告警规则。

| 字段 | 说明 |
| --- | --- |
| `id` | 规则 ID；legacy JSON 规则在 P0 中没有持久化 ID |
| `name` | 用户可读名称；没有提供时可由规则类型和目标生成 |
| `target_scope` | 目标范围，例如 single symbol、watchlist、portfolio、market |
| `target` | 目标标的或目标引用，例如股票代码、watchlist ID、portfolio ID |
| `alert_type` | 规则类型；P1 初始只允许 `price_cross`、`price_change_percent`、`volume_spike` |
| `parameters` | 规则参数，例如 `direction`、`price`、`change_pct`、`multiplier` |
| `severity` | 告警等级，例如 info、warning、critical |
| `enabled` | 是否启用 |
| `cooldown_policy` | 冷却策略；P0 只定义字段，P4 才实现执行语义 |
| `notification_policy` | 通知策略；默认复用 `NotificationService` 的 alert 路由 |
| `source` | 创建来源，例如 legacy_env、web、api、import |
| `created_at` / `updated_at` | 创建和更新时间 |

### `alert_trigger`

一次真实或可记录的规则触发。

| 字段 | 说明 |
| --- | --- |
| `id` | 触发记录 ID |
| `rule_id` | 对应规则 ID；legacy env 规则可记录临时引用 |
| `target` | 实际触发目标 |
| `observed_value` | 观察值，例如现价、涨跌幅、成交量倍数 |
| `threshold` | 触发阈值 |
| `reason` | 可读触发原因 |
| `data_source` | 数据源或 provider |
| `data_timestamp` | 数据时间；缺失时不得伪造为当前时间 |
| `triggered_at` | 触发时间 |
| `status` | 触发状态，例如 triggered、skipped、degraded、failed |
| `diagnostics` | 脱敏后的诊断信息 |

### `alert_notification`

一次触发对应的通知尝试。

| 字段 | 说明 |
| --- | --- |
| `id` | 通知尝试 ID |
| `trigger_id` | 对应触发记录 ID |
| `channel` | 通知渠道 |
| `attempt` | 第几次尝试 |
| `success` | 是否成功 |
| `error_code` | 结构化错误码 |
| `retryable` | 是否建议重试 |
| `latency_ms` | 耗时 |
| `diagnostics` | 脱敏后的发送诊断，不得包含 token、完整 webhook URL、邮箱密码或 bot secret |
| `created_at` | 尝试时间 |

### `alert_cooldown`

规则或目标维度的冷却状态。

| 字段 | 说明 |
| --- | --- |
| `rule_id` | 对应规则 ID |
| `target` | 冷却目标 |
| `severity` | 可选等级维度 |
| `last_triggered_at` | 最近触发时间 |
| `cooldown_until` | 冷却截止时间 |
| `reason` | 冷却原因 |
| `state` | 当前状态，例如 active、expired |
| `updated_at` | 更新时间 |

## 存储方案评估

当前仓库已有 SQLite 存储层和 repository/service 分层：

- `src/storage.py` 管理 SQLite 连接、SQLAlchemy ORM 模型和 `DatabaseManager`。
- `src/repositories/` 放置数据访问层，例如 `PortfolioRepository`。
- `src/services/` 放置业务服务层，例如 `PortfolioService`、`PortfolioRiskService`。
- 默认数据库路径跟随现有配置，通常落在 `data/stock_analysis.db`。

P1/P2 实现告警持久化时，推荐优先复用以上模式：在 storage 层定义 alert ORM 模型，在 repository 层封装 CRUD 和查询，在 service 层处理规则校验、评估状态、通知结果和冷却语义。P0 不新建表，不改变现有数据库。

如果后续 PR 需要 schema 变更，必须同时给出：

- 幂等初始化：重复启动或重复执行初始化时不得破坏已有数据。
- 向后兼容：未配置告警中心时不影响每日分析、问股、通知、大盘复盘和持仓功能。
- 回滚说明：最小回滚方式至少包括 revert PR；若创建了新表或索引，需要说明是否保留数据、如何手动清理。
- 数据迁移边界：不得自动迁移、删除或覆盖 `AGENT_EVENT_ALERT_RULES_JSON`，除非用户显式执行导入动作。

## P1 Alert API MVP

P1 新增后端 Alert API 与 schema，锁定告警中心最小 API 契约，不接入 Web 页面或后台 worker。

- 新增 API 文件：`api/v1/endpoints/alerts.py`。
- 新增 schema 文件：`api/v1/schemas/alerts.py`。
- API 范围：
  - `GET /api/v1/alerts/rules`
  - `POST /api/v1/alerts/rules`
  - `GET /api/v1/alerts/rules/{rule_id}`
  - `PATCH /api/v1/alerts/rules/{rule_id}`
  - `DELETE /api/v1/alerts/rules/{rule_id}`
  - `POST /api/v1/alerts/rules/{rule_id}/enable`
  - `POST /api/v1/alerts/rules/{rule_id}/disable`
  - `POST /api/v1/alerts/rules/{rule_id}/test`
  - `GET /api/v1/alerts/triggers`
  - `GET /api/v1/alerts/notifications`
- 首版规则仍只支持 `price_cross`、`price_change_percent`、`volume_spike`；`sentiment_shift`、`risk_flag`、`custom` 等未来类型返回结构化 unsupported 错误。
- `test` 接口只做一次性 dry-run 评估，不发送通知，不写入真实触发记录或通知 attempt。
- `cooldown_policy` / `notification_policy` 在 P1 中只是保留字段：API 可存储和返回这些 opaque 配置，但不执行冷却或自定义通知语义。
- API 响应必须脱敏，不回显 token、完整 webhook URL、邮箱密码、cookie、bot secret。
- `AGENT_EVENT_ALERT_RULES_JSON` 继续保留为 legacy 配置入口；P1 不自动迁移、删除、覆盖或改写 legacy 配置。

P1 不做：

- 不新增 Web 告警中心页面、路由或侧边栏入口。
- 不让 schedule worker 加载持久化 active rules，也不实现持久化规则与 legacy JSON 的合并/去重。
- 不实现真实 `alert_trigger` / `alert_notification` 写入；P1 只提供查询接口和表结构。
- 不实现 `alert_cooldown` 执行语义。
- 不实现 MACD、KDJ、CCI、RSI、持仓风险或 Market Light 告警规则。

## P2 告警评估 Worker

P2 将 schedule 运行时从启动时一次性构建 legacy `EventMonitor`，切换为每轮后台 worker 评估持久化 active rules 与 legacy JSON 规则。

- `AGENT_EVENT_MONITOR_ENABLED` 继续作为总开关，后台任务名保持 `agent_event_monitor`。
- worker 每轮读取 DB 中 `enabled=true` 的 `alert_rules`，并重新解析 `AGENT_EVENT_ALERT_RULES_JSON`；新增 API 规则不需要重启 schedule 进程。
- DB 规则与 legacy 规则按 `target_scope + target + alert_type + canonical(parameters)` 去重，冲突时 DB 规则优先；legacy 配置不自动迁移、删除或改写。
- 每条规则独立评估，单条失败只写 `failed` 评估状态，不影响同轮其他规则或主分析流程。
- `alert_triggers` 在 P2 用于记录最小评估历史：`triggered`、`skipped`、`degraded`、`failed`；正常 `not_triggered` 不写历史，避免轮询刷表。
- 实时行情缺失、字段缺失或非可评估场景记录 `skipped`；日线数据不可用或结构不完整记录 `degraded`；诊断信息会脱敏。
- 触发后仍调用 `NotificationService.send(..., route_type="alert")`；进程内 fingerprint 只避免持续触发条件重复推送，不执行 `cooldown_policy`。

P2 不做：

- 不新增 Web 告警中心页面、路由或侧边栏入口。
- 不写 `alert_notifications`，不记录 per-channel notification attempt。
- 不实现 `alert_cooldown`、`cooldown_policy` 或 `notification_policy` 执行语义。
- 不实现 MACD、KDJ、CCI、RSI、持仓风险或 Market Light 告警规则。

## P3 Web 告警中心 MVP

P3 在 WebUI 中新增 `/alerts` 告警中心入口，让用户不需要直接编辑 legacy JSON 即可管理当前三类运行时规则。

- 侧边栏新增“告警”入口，页面支持规则列表、分页、启停筛选和规则类型筛选。
- 规则创建表单只支持 `single_symbol` 目标范围和当前已可执行的三类规则：
  - `price_cross`：`direction` 为 `above` / `below`，并填写 `price`。
  - `price_change_percent`：`direction` 为 `up` / `down`，并填写 `change_pct`。
  - `volume_spike`：填写 `multiplier`。
- 规则操作支持启用、停用、删除和一次性 dry-run 测试。
- dry-run 测试只展示 `AlertRuleTestResponse` 已声明字段：规则 ID、状态、是否触发、观察值和消息；`threshold`、`data_source`、`data_timestamp` 等扩展诊断字段需要后端 schema 明确暴露后再展示。
- 触发历史展示 P2 worker 已写入的 `triggered`、`skipped`、`degraded`、`failed` 记录；正常 `not_triggered` 仍不会写入历史。
- 通知尝试区域只查询现有 `GET /api/v1/alerts/notifications`；由于 P2 运行时不写 per-channel notification attempt，当前通常显示“暂无通知尝试记录”空态，不把触发状态推断为通知投递结果。
- Web 页面不暴露 `AGENT_EVENT_ALERT_RULES_JSON` 编辑入口，不自动迁移、删除或改写 legacy 配置。

P3 不做：

- 不新增或修改后端 API、schema、storage 或 worker 行为。
- 不实现规则编辑、target/source 高级筛选、watchlist/portfolio 目标、技术指标规则或 Market Light 联动。
- 不执行 `cooldown_policy` / `notification_policy`，不写 `alert_notifications`。

## P4 通知结果与持久化冷却

P4 让真实告警触发具备可排障的通知结果，并让通过 Alert API 创建的持久化规则具备可重启保持的业务冷却状态。

- DB 持久化规则的 `triggered` 历史按 `rule_id + target + data_source + data_timestamp` 做同一数据点去重：同一触发事件只保留最早一条 `alert_triggers`，重复轮询命中会复用已有触发记录；`data_timestamp` 缺失时不做去重，避免误合并无法证明同源的数据点。即使后续被冷却或通知降噪抑制，仍通过 `alert_notifications` 记录对应的通知尝试或 synthetic 抑制状态。
- `alert_notifications` 记录真实 per-channel notification attempt，包括 `channel`、`success`、`error_code`、`retryable`、`latency_ms` 和脱敏后的 `diagnostics`。
- 非渠道发送状态使用 synthetic channel 记录：
  - `__cooldown__`：告警业务冷却抑制，`error_code="cooldown_active"`。
  - `__cooldown_read_failed__`：读取持久化冷却状态失败后，由 worker 进程内临时兜底抑制，`error_code="cooldown_read_failed"`。
  - `__noise_suppressed__`：通知基础设施降噪抑制，`error_code="noise_suppressed"`。
  - `__no_channel__`：alert 路由未命中任何可用通知渠道。
  - `__dispatch__`：通知调度级 fallback 或异常。
- cooldown 分层：
  - DB 持久化规则正常路径使用 `alert_cooldowns` 作为告警业务冷却，不再由 worker 进程内 fingerprint 决定；仅当读取持久化冷却状态失败时，临时使用进程内 fingerprint 防止同一规则在 DB 异常期间每轮重复推送。
  - legacy `AGENT_EVENT_ALERT_RULES_JSON` 规则继续使用 worker 进程内 fingerprint，不写 `alert_cooldowns`。
  - `notification_noise.py` 仍作为通知基础设施层的全局安全网；它不是告警业务 cooldown，且被其抑制时不会写入或延长 `alert_cooldowns`。
- DB 规则的 `cooldown_policy.cooldown_seconds` 归一为非负整数；缺失时使用默认 24 小时业务冷却，`0` 表示关闭 DB 业务冷却。
- `GET /api/v1/alerts/rules` 会返回只读 `last_triggered_at` / `cooldown_until` / `cooldown_active` 摘要；`cooldown_active` 由后端按同一冷却时间语义计算，Web 不在浏览器本地解析 naive ISO 字符串来推断状态。
- Web 告警中心只读展示冷却状态和通知结果，不提供 cooldown policy 编辑表单。

P4 不做：

- 不新增技术指标、持仓、自选股、portfolio、watchlist 或 Market Light 告警规则。
- 不实现 target-level 跨规则合并冷却；目标级合并留到持仓/市场联动阶段。
- 不重写通知渠道网关；`NotificationService.send()` 继续保持布尔返回兼容，结构化结果通过新增兼容接口提供。
- 不自动迁移、删除或改写 legacy `AGENT_EVENT_ALERT_RULES_JSON`。

## P5 技术指标规则

P5 在现有 Alert API、Web 告警中心和 `src/services/alert_worker.py` 评估链路中新增日线技术指标规则。规则仍写入 `alert_rules`，触发、降级、失败、通知结果和持久化冷却继续复用 P2-P4 的 `alert_triggers`、`alert_notifications` 与 `alert_cooldowns` 语义。

P5 支持的 `alert_type` 与 `parameters`：

| alert_type | parameters | 触发语义 |
| --- | --- | --- |
| `ma_price_cross` | `direction=above|below`，`window` 默认 `20`，整数 `[2,250]` | close 相对 MA(window) 边缘上穿/下穿 |
| `rsi_threshold` | `direction=above|below`，`period` 默认 `12`，整数 `[2,250]`，`threshold` 必填且 `0..100` | RSI 相对阈值边缘上穿/下穿 |
| `macd_cross` | `direction=bullish_cross|bearish_cross`，`fast_period=12`，`slow_period=26`，`signal_period=9`，均为 `[2,250]` 且 `fast_period < slow_period` | DIF/DEA 边缘金叉/死叉 |
| `kdj_cross` | `direction=bullish_cross|bearish_cross`，`period=9`，`k_period=3`，`d_period=3`，均为 `[2,250]` | K/D 边缘金叉/死叉 |
| `cci_threshold` | `direction=above|below`，`period` 默认 `14`，整数 `[2,250]`，`threshold` 必填且为有限数值 | CCI 相对阈值边缘上穿/下穿 |

评估规则：

- 首版统一使用日线 close，不做分钟线。
- 边缘触发只比较最近两根已收盘日线；非边缘但当前 level 已满足阈值时仍返回 `not_triggered`，避免规则创建首日把历史状态误报为新触发。
- 边缘触发包含前一根刚好等于阈值或零轴的情况：`above` / `bullish_cross` 使用 `prev <= threshold < current`，`below` / `bearish_cross` 使用 `prev >= threshold > current`。
- partial bar 只使用服务器本地时区启发式：当前本地时间早于 16:00 时，最后一行日期等于本地今天或日期不可判定都会保守丢弃；不区分 A 股、港股、美股市场时区或交易日历。Issue #1386 P0 的市场阶段基线暂不接入技术指标规则，告警 partial bar 精确判定留到后续阶段。
- `src/services/alert_indicators.py` 自行归一化 OHLCV 并计算 MA、RSI、MACD、KDJ、CCI，不依赖 fetcher 预计算的 MA5/MA10/MA20。
- RSI 使用 Wilder's EMA / SMMA：`avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()`，`avg_loss` 同理，不使用 rolling SMA。
- MACD 使用 `EMA(fast_period) - EMA(slow_period)` 得到 DIF，DEA 为 DIF 的 `EMA(signal_period)`；金叉/死叉比较 DIF-DEA 相对 0 的边缘穿越。
- KDJ 使用最近 `period` 日最高/最低价计算 RSV，并用 `alpha=1/k_period`、`alpha=1/d_period` 的 EMA 得到 K/D；金叉/死叉比较 K-D 相对 0 的边缘穿越。
- CCI 使用典型价格 `(high + low + close) / 3`，按 `period` 日均值和平均绝对偏差计算 `(TP - MA(TP)) / (0.015 * mean_deviation)`。
- `compute_required_bars(alert_type, params)` 定义最少有效 closed bars：MA=`window+1`，RSI=`period+1`，MACD=`slow_period+signal_period+1`，KDJ=`period+k_period+d_period+1`，CCI=`period+1`。
- 拉取天数使用 `requested_days = min(max(required_bars * 3, required_bars + 30), 365)`；API 会拒绝 `required_bars > 365` 的组合周期，避免创建永久样本不足的规则；同一 worker 轮次按 `(stock_code, requested_days)` 缓存日线数据，轮次结束释放。
- 缺数据、缺列或有效样本少于 `required_bars` 写入 `degraded`；数据源异常沿用 `volume_spike` 语义返回 `evaluation_error` / `failed`，不发送通知。

兼容边界：

- `AGENT_EVENT_ALERT_RULES_JSON` 仍是 legacy JSON 路径，只支持 `price_cross`、`price_change_percent`、`volume_spike` 三类规则；P5 技术指标只通过 Alert API / Web 创建。
- 不扩展 `src/agent/events.py` 的 legacy `AlertType` 或 `_RUNTIME_SUPPORTED_ALERT_TYPES`。
- P5 创建/更新参数错误沿用现有 Alert API 错误契约：HTTP 400 + `validation_error`；unsupported 类型返回 HTTP 400 + `unsupported_alert_type`。
- Web 告警中心只扩展现有创建表单、列表展示、类型筛选和 dry-run 测试，不新增规则编辑器；dry-run 测试不写触发历史，且 API 响应仍沿用 `triggered` / `not_triggered` / `evaluation_error` 三态，worker 写入的 `degraded` 状态通过触发历史查看。
- 回滚 P5 PR 后，数据库中已创建的技术指标规则记录会保留；旧代码在 worker 加载阶段遇到 unsupported `alert_type` 会 skip，不影响 legacy 三类规则继续执行。如需清理，需要维护者确认后手动删除相关 `alert_rules` 记录。

P5 不做：

- 不支持 MACD 柱体放大/收缩。
- 不支持 KDJ 超买/超卖区规则。
- 不支持 MA 与 MA 双均线交叉。
- 不支持分钟线、市场日历精确判定或多市场时区精确 partial bar。
- 不支持 legacy `AGENT_EVENT_ALERT_RULES_JSON` 技术指标规则。
- 不引入 DSL、规则引擎、新数据库表或分析报告 pipeline 内的技术指标规则引擎。

## P6 持仓与自选股联动

P6 在现有 Alert API、Web 告警中心和 `src/services/alert_worker.py` 评估链路中新增 `watchlist`、`portfolio_holdings`、`portfolio_account` 三类目标范围。规则仍写入 `alert_rules`，触发、降级、失败、通知结果和持久化冷却继续复用 P2-P4 的 `alert_triggers`、`alert_notifications` 与 `alert_cooldowns` 语义，不新增表或迁移。

### P6 scope/type 矩阵

| `target_scope` | `target` | 允许的 `alert_type` | 评估方式 |
| --- | --- | --- | --- |
| `single_symbol` | 股票代码 | P1 三类价格/成交量规则 + P5 技术指标 | 单规则单标的 |
| `watchlist` | `default` | P1 三类价格/成交量规则 + P5 技术指标 | 每轮刷新并读取当前 `STOCK_LIST`，按股票代码展开 |
| `portfolio_holdings` | `all` 或 active account ID | P1 三类价格/成交量规则 + P5 技术指标 | 从持仓 snapshot 的非零持仓展开 symbol，按 symbol 去重 |
| `portfolio_account` | `all` 或 active account ID | `portfolio_stop_loss`、`portfolio_concentration`、`portfolio_drawdown`、`portfolio_price_stale` | 账户级风险评估，不展开为单标的 |

创建/更新规则时，`watchlist` / `portfolio_holdings` 不把父级 `target` 当股票代码校验；`portfolio_account` 禁止 price/volume/技术指标类型；`portfolio_holdings` 和 `portfolio_account` 在 `target=<id>` 时会校验账户存在且 active，不存在返回 HTTP 400 + `validation_error`。legacy `AGENT_EVENT_ALERT_RULES_JSON` 不支持 watchlist、portfolio 或技术指标扩展，继续仅支持 `single_symbol` 的 `price_cross`、`price_change_percent`、`volume_spike`。

### Target Identity Contract

P6 将可展示目标与可持久化目标分离：

| 场景 | `effective_target` | `display_target` |
| --- | --- | --- |
| `single_symbol` | `<symbol>` | `<symbol>` |
| `watchlist` 展开子目标 | `<symbol>` | `自选股 - <symbol>` |
| `portfolio_holdings` 展开子目标 | `<symbol>` | `持仓 - <symbol>` |
| `portfolio_account target=all` | `account:all` | `全部账户` |
| `portfolio_account target=<id>` | `account:<id>` | `账户 <id>` |

- `alert_triggers.target`、`alert_cooldowns.target`、P4 `rule_id + target + data_source + data_timestamp` 去重全部使用 `effective_target`。
- `RuntimeAlertRule.key` 对展开后的子目标使用 `{parent_key}|{effective_target}`，避免 DB cooldown 读取失败时的进程内 fallback 把同一父规则下的不同子目标互相 suppress。
- `display_target` 不写入 `alert_triggers.target`，仅用于通知标题、dry-run `target_results` 和 Web 展示。
- P6 不做跨规则同标的通知合并；同一股票若同时命中 watchlist 子规则和独立 `single_symbol` 规则，会按每条规则独立记录和通知。

### Dry-run 聚合

- `POST /api/v1/alerts/rules/{rule_id}/test` 对批量规则返回聚合字段：`evaluated_count`、`triggered_count`、`degraded_count`、`skipped_count`、`target_results`。
- 展开目标 soft cap 为 100；dry-run 中超过 soft cap 的目标记为 `degraded` 聚合结果并写日志。worker 运行时只评估前 100 个展开目标并写 warning，不为 overflow 本身写 `alert_triggers` 历史。
- dry-run 使用受限并发评估，单目标超时 10 秒，总评估超时 30 秒；未完成目标记为 `skipped`。
- 任一目标 triggered 时顶层 `status=triggered`；无触发但存在成功评估、skipped 或 degraded 时顶层 `status=not_triggered`；无法展开或全部失败时才返回 `evaluation_error`。
- 空 watchlist / 空 holdings：dry-run 返回 `not_triggered` 并在 `target_results` 中给出 `record_status=skipped`；worker 会写 `skipped` 历史。
- `degraded_count` 统计全部展开评估结果中 `record_status=degraded` 的条目；`target_results` 仅展示前 20 条，排序为 triggered 优先，其次 degraded/failed，再按 target 排序。

### 持仓风险规则

| `alert_type` | 参数 | 观察值 | 触发语义 |
| --- | --- | --- | --- |
| `portfolio_stop_loss` | `mode=near|breach`，默认 `near` | 受影响标的最大 `loss_pct` | `near` 使用 `stop_loss.near_alert`，`breach` 只统计 `is_triggered=true` 的 items；每账户每轮最多一条 trigger |
| `portfolio_concentration` | - | `concentration.top_weight_pct` | `top_weight_pct >= portfolio_risk_concentration_alert_pct` |
| `portfolio_drawdown` | - | `drawdown.max_drawdown_pct` | 复用 `PortfolioRiskService` 的 `drawdown.alert`；`current_drawdown_pct` 写 diagnostics |
| `portfolio_price_stale` | - | stale/missing 价格持仓数量 | 任一 position `price_stale=true` 或 `price_available=false` |

portfolio diagnostics 必含 `account_id`（或 `all`）、`currency`、`as_of`、`price_stale`、`fx_stale`、`data_available`、`top_affected_symbols`。`portfolio_stop_loss`、`portfolio_concentration`、`portfolio_drawdown` 复用 `PortfolioRiskService.get_risk_report()`；`portfolio_price_stale` 复用 `PortfolioService.get_portfolio_snapshot()` 的 position price metadata。

### Web 与 cooldown 摘要

- Web 创建表单新增目标范围选择；`watchlist` / `portfolio_holdings` 只显示 price/volume/P5 技术指标类型，`portfolio_account` 只显示四类 portfolio 风险类型。
- `portfolio_holdings` / `portfolio_account` 加载账户列表失败时，表单保留 `all` 选项并展示错误。
- 规则列表上的 `cooldown_active` 对 `single_symbol` 和 `portfolio_account` 准确；`watchlist` / `portfolio_holdings` 是父规则摘要，不代表每个子目标的冷却状态，子目标冷却以触发历史和 `effective_target` 为准。
- dry-run UI 展示聚合计数和最多 20 条 `target_results` 明细。

P6 不做：

- 不做 P7 Market Light。
- 不做财报日前、分红除权日前提醒；这类规则需要稳定日期契约后另起 follow-up。
- 不做 sector 级集中度告警；P6 集中度使用 symbol 维度 `top_weight_pct`。
- 不做跨规则同标的通知合并、分钟线、多市场时区精确判定或 legacy JSON 扩展。

## 阶段感知与公开摘要联动（Refs #1386 P6）

本节描述 #1386 P6 的告警可见性联动，区别于上面的“P6 持仓与自选股联动”。本联动不新增告警表、不做 migration、不自动触发轻量 LLM 分析，只把触发当时可公开的 phase/pack 摘要写入既有触发历史。

- `AlertTriggerItem` 保留 `diagnostics` 字符串，并新增派生字段 `market_phase_summary`、`analysis_context_pack_overview`、`analysis_visibility_source`。
- 真实 `status=triggered` 的 worker 记录会在 JSON diagnostics 中合并 sibling key `analysis_visibility`，包含 `market_phase_summary`、`analysis_context_pack_overview`、`source`。旧纯文本 diagnostics 保留原文，API 派生字段返回 `null`，source 返回 `legacy_text`。
- `analysis_visibility_source` 取值为 `alert_trigger_market_context`、`analysis_history_snapshot`、`evaluator_snapshot`、`legacy_text` 或 `null`。
- symbol 目标使用 `get_market_for_stock(normalize_stock_code(effective_target))` 构造触发时 phase；`target_scope=market` 直接用 `normalize_market_region(target)`，不会把 `cn|hk|us` 当作股票代码推断；账户级无法唯一定位市场时允许 summary 落为 `unknown`。
- `analysis_context_pack_overview` 只来自 evaluator 已带 overview 或最近 30 天内的历史 snapshot。最近历史查询复用历史服务的代码变体候选，并以 best-effort + 批内短缓存方式执行；缺失或解析失败返回 `null`，不伪造 pack。
- 告警通知只输出公开摘要：阶段标签、trigger source、partial-bar warning、数据质量等级和前两条 limitations。通知不得输出 raw context pack、Prompt、新闻正文、完整 diagnostics JSON、webhook URL、token 或持仓敏感细节。
- Web 告警历史展示 phase badge、数据质量等级和 limitations 空态；旧触发记录缺少公开摘要时不影响列表读取。

#1386 P7 的用户边界：告警联动只解释触发时已经可公开的阶段和数据质量摘要，不会自动发起轻量 LLM 盘中分析，也不会新增告警表、规则类型、环境变量或 migration。需要阶段化分析时，仍应通过分析 API / Web 手动分析入口触发；告警通知只保留阶段标签、trigger source、partial-bar warning、数据质量等级和前两条 limitations。

回滚本联动只需要 revert 对 worker/API/Web 的改动；已有 `diagnostics.analysis_visibility` 会作为普通 JSON diagnostics 保留，旧代码不会读取该 sibling key。

## P7 大盘红绿灯结构化告警

P7 在现有 Alert API、Web 告警中心和 `src/services/alert_worker.py` 中新增 `target_scope=market`，消费结构化 `MarketLightSnapshot`，不解析 Markdown，不扩展 legacy `AGENT_EVENT_ALERT_RULES_JSON`，不新增表。大盘复盘历史仍写一条 `analysis_history(code=MARKET, report_type=market_review)`；多市场复盘通过 `context_snapshot.market_light_snapshots` 按 region 保存本次实际复盘的快照 map。

### P7 scope/type 矩阵

| `target_scope` | `target` | 允许的 `alert_type` | 参数 | 触发语义 |
| --- | --- | --- | --- | --- |
| `market` | `cn` / `hk` / `us` | `market_light_status` | `statuses=["red","yellow"]`，只允许 `red/yellow`，默认 `["red","yellow"]` | 当前 `MarketLightSnapshot.status` 命中列表时触发 |
| `market` | `cn` / `hk` / `us` | `market_light_score_drop` | `min_drop > 0` | `prev.score - current.score >= min_drop`，且 `prev.trade_date < current.trade_date` |

scope/type 校验是双向约束：`target_scope=market` 只能使用两类 Market Light 规则；`market_light_*` 规则也只能使用 `target_scope=market`。`target` 会 `strip().lower()` 后严格限定为 `cn|hk|us`，非法 target 返回 HTTP 400 + `validation_error`。

### `MarketLightSnapshot` 契约

结构化快照字段为：`region`、`trade_date`、`status`、`score`、`label`、`temperature_label`、`reasons`、`guidance`、`dimensions`、`data_quality`。`trade_date` 首版固定取 `MarketOverview.date`；P7 不解析 provider quote as-of。

`dimensions` 使用 canonical scorer 单一来源，`build_market_light_snapshot()`、大盘复盘注入块和告警 service 不重复实现 scoring。`_build_market_temperature()` 只是 thin wrapper；红绿灯 `status` 阈值保持 `60/40`，temperature label 阈值保持 `70/55/40`。

| dimension | `available=true` 条件 | fallback score |
| --- | --- | --- |
| `breadth` | `has_market_stats && (up_count + down_count) > 0` | `50` |
| `index` | `indices` 非空且至少一个 `change_pct != None` | `50` |
| `limit` | `has_market_stats && (limit_up_count + limit_down_count) > 0` | `50` |

`data_quality=unavailable` 表示 `index.available=false`，两类 market rule 都返回 `skipped` 且不触发通知；`partial` 表示至少一个维度 fallback，`ok` 表示三项均 available。`market_light_status` 在 `ok/partial` 下可触发；`partial` 触发时 diagnostics 必含 `missing_dimensions`。`market_light_score_drop` 直接比较 canonical aggregate score；任一侧 `partial` 仍允许比较，但 diagnostics 必含 `partial_comparison=true` 和 `missing_dimensions`。

### 基线、交易日与去重

- 大盘复盘持久化必须使用与报告生成共用的同一份 `MarketOverview` 生成 `MarketLightSnapshot`，禁止 persist 阶段二次拉行情。
- `load_previous_snapshot(region, before_trade_date)` 扫描 `analysis_history(code=MARKET, report_type=market_review)`，跳过缺少 `context_snapshot.market_light_snapshots[region]` 的 legacy 记录，先选出小于 `before_trade_date` 的最大 `snapshot.trade_date`，再在同一 `trade_date` 内按 `created_at DESC, id DESC` 取最新 valid 快照；更晚插入的旧交易日 backfill 不会覆盖正确基线。
- 若目标 `trade_date` 只有损坏快照，`market_light_score_drop` 返回 `degraded`，不会自动退回更旧交易日做 best-effort 比较。
- `market_light_score_drop` 首版只做跨交易日比较；无上一交易日基线或同日基线返回 `skipped`，查询/解析异常返回 `degraded`。
- worker 对 `target_scope=market` 做 region 交易日 gate，并尊重 `TRADING_DAY_CHECK_ENABLED` / `config.trading_day_check_enabled`；检查关闭时允许评估，检查开启且 region 非交易日时返回 `skipped`，不拉取当前快照。
- 触发历史写 `target=<region>`、`observed_value=<score>`、`data_source=market_light`、`data_timestamp=<trade_date 00:00:00>`，继续复用 P4 的 `rule_id + target + data_source + data_timestamp` 去重。

### Web 与回滚边界

- Web 告警中心新增 `market` scope、region 选择、两类 market rule 参数控件、类型筛选、region 展示和参数展示；API snake_case 映射使用 `statuses` 与 `min_drop`。
- legacy `AGENT_EVENT_ALERT_RULES_JSON` 不支持 market 规则；P7 不更新 `.env.example`，因为没有新增配置项。
- P7 不做指数跌幅、板块异动、涨跌停结构恶化、分钟线、多市场时区精确 quote as-of 解析，也不新增 DSL/规则引擎。

## P8 用户配置与部署边界

P8 不新增规则类型、API、表结构或 worker 行为；它把 P0-P7 已合并能力整理成面向用户和部署者的配置说明。告警 worker 只在 schedule 模式注册，核心开关仍是 `AGENT_EVENT_MONITOR_ENABLED`，轮询间隔仍是 `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`。通知渠道继续走 alert 路由，详见 [通知配置](notifications.md) 中的 `NOTIFICATION_ALERT_CHANNELS` 与 `route_type=alert`。

### 本地配置

本地运行 `python main.py --schedule`、`python main.py --serve --schedule` 或等价内置调度模式时，设置 `AGENT_EVENT_MONITOR_ENABLED=true` 后会启动后台告警 worker；`AGENT_EVENT_MONITOR_INTERVAL_MINUTES` 控制轮询间隔。

规则来源有两类：

- Alert API / Web 告警中心持久化规则：推荐入口，支持 `single_symbol`、`watchlist`、`portfolio_holdings`、`portfolio_account`、`market`，覆盖实时价、涨跌幅、成交量、日线技术指标、持仓风险与大盘红绿灯规则。
- legacy `AGENT_EVENT_ALERT_RULES_JSON`：只兼容 `single_symbol` 的 `price_cross`、`price_change_percent`、`volume_spike` 三类基础规则；不支持 P5 技术指标、P6 watchlist/portfolio 或 P7 market light。系统不会自动迁移、删除或改写 legacy JSON。

### Docker

仓库 `docker/Dockerfile` 默认命令是 `python main.py --schedule`，因此容器内只要配置 `AGENT_EVENT_MONITOR_ENABLED=true` 就会在 schedule 模式中启用告警 worker。Web/API 持久化规则依赖应用数据库；Docker 部署时需要保留 `data/` 数据库卷，避免容器重建后丢失规则、触发历史、通知尝试和冷却状态。legacy JSON 仍通过环境变量注入，不是 Docker 专用配置体系。

### GitHub Actions

仓库自带 `.github/workflows/00-daily-analysis.yml` 是一次性分析 workflow，实际调用 `python main.py`、`python main.py --market-review` 或 `python main.py --no-market-review`，不运行 `--schedule` 后台 alert worker，也没有映射 `AGENT_EVENT_*` 变量。仅在 repository Secrets / Variables 中新增 `AGENT_EVENT_MONITOR_ENABLED` 或 `AGENT_EVENT_ALERT_RULES_JSON` 不会让默认 Actions 开始持续轮询告警。

如需 GitHub Actions 里的告警轮询，需要后续单独 PR 明确 schedule 启动方式、env 映射、规则来源和持久化数据库策略；P8 不改变现有 workflow。

### Web 与 Desktop

Web 告警中心 `/alerts` 是持久化规则的主要入口：可以创建、启停、删除规则，执行一次性 dry-run 测试，查看触发历史、通知尝试和只读冷却状态。批量规则的列表冷却状态是父规则摘要，子目标是否冷却以触发历史中的 `target` / `effective_target` 为准。

Desktop 不新增原生告警管理界面；桌面用户复用内置或外部 WebUI 的 `/alerts` 页面。Desktop 回滚不需要清理额外状态。

### 状态、通知与回滚

worker 会把 `triggered`、`skipped`、`degraded`、`failed` 写入 `alert_triggers` 作为评估历史；正常未触发不写历史。`skipped` 表示规则本轮没有可评估条件，例如 market 非交易日或缺少上一交易日基线；`degraded` 表示数据源、持仓快照、历史快照或解析过程出现异常，结果不可用于触发通知。

真实触发后会写入 `alert_notifications` 和 `alert_cooldowns`；DB 持久化规则按 `rule_id + target + data_source + data_timestamp` 对同一数据点做 best-effort 去重。legacy JSON 规则继续只使用进程内 fingerprint，不写持久化冷却。

回滚 P8 只需 revert 文档、配置说明和 Web 文案改动；没有数据库迁移或用户数据清理。回滚早期 Phase 时，已创建的持久化规则不会自动删除，按下方 Phase 回滚说明处理。

## Phase 边界

- P0：本文档、契约、存储评估和兼容测试。
- P1：Alert API MVP，首版只覆盖现有三类 runtime 规则。
- P2：告警评估 worker 与 runtime 统一，让持久化 active rules 与 legacy JSON 共存。
- P3：Web 告警中心 MVP。
- P4：触发历史、通知结果与冷却状态。
- P5：技术指标规则。
- P6：持仓与自选股联动。
- P7：大盘红绿灯与市场联动。
- P8：文档、迁移与收口。

## P0 不做

- P0 阶段不新增 `api/v1/schemas/alerts.py` 或 Alert API。
- P0 阶段不新增 Web 告警中心页面、路由或侧边栏入口。
- P0 阶段不新增数据库表、repository 或 migration。
- P0 阶段不实现触发历史、通知结果或冷却状态写入。
- P0 阶段不自动迁移、删除或覆盖 `AGENT_EVENT_ALERT_RULES_JSON`。
- P0 阶段不实现 MACD、KDJ、CCI、RSI、持仓风险或 Market Light 告警规则。
- P0 阶段不重写 `NotificationService` 或通知路由框架。

## 回滚

- P0 是文档和测试收口。若只回滚 P0，revert 对应 PR 即可；没有数据库、配置或用户数据迁移需要额外处理。
- P1 新增 Alert API 代码和 `alert_rules` / `alert_triggers` / `alert_notifications` SQLite 表。最小回滚方式是 revert P1 PR；revert 会移除 API、service、repository、schema 和 ORM 定义，但已经由 `Base.metadata.create_all()` 创建的 SQLite 表与数据不会自动删除。如需清理，需要维护者在确认不再需要历史数据后手动删除相关表。
- P3 是 Web 和文档改动。最小回滚方式是 revert P3 PR；不会删除已有规则、触发历史或 legacy JSON 配置。
- P4 新增 `alert_cooldowns` SQLite 表并开始写入 `alert_notifications`。最小回滚方式是 revert P4 PR；已经创建的 `alert_cooldowns`、`alert_triggers`、`alert_notifications` 数据不会自动删除。如需清理，需要维护者确认后手动删除对应表或记录。
- P5 新增 Alert API/Web 支持的技术指标规则。最小回滚方式是 revert P5 PR；已创建的 P5 `alert_rules` 记录不会自动删除，旧代码会在 worker 加载阶段 skip unsupported `alert_type`，不影响 legacy 三类规则执行。如需清理，需要维护者确认后手动删除相关规则记录。
- P6 新增 Alert API/Web 支持的 watchlist、portfolio holdings 与 portfolio account 规则。最小回滚方式是 revert P6 PR；没有新表或迁移，已创建的 P6 `alert_rules` 会保留。回滚前建议 disable/delete 非 `single_symbol` 的 P6 规则；否则旧 worker 可能把 `watchlist` / `portfolio_holdings` 的父级 `target` 当作股票代码评估并产生 failed/skipped 噪声，portfolio 专用 `alert_type` 会在 worker 加载阶段被 skip。
- P7 新增 Alert API/Web 支持的 `market` 规则和大盘复盘 `market_light_snapshots` 历史快照。最小回滚方式是 revert P7 PR；没有新表或迁移，已创建的 P7 `alert_rules` 会保留。回滚前建议 disable/delete `target_scope=market` 规则；旧 worker 会 skip unsupported `market_light_*` 类型或因 scope/type 不识别产生配置噪声。
