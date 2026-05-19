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

- 每次真实触发仍写入本轮 `alert_triggers`；即使后续被冷却或通知降噪抑制，也保留“规则确实触发”的审计记录。
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
