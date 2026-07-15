# DecisionSignal 决策信号专题

本页收口 #1390 P7，说明 DSA 如何把个股分析、Agent、告警和组合风险中的 AI 建议沉淀为可查询、可反馈、可后验评估的 `DecisionSignal` 资产。它是报告之上的结构化索引，不替代 Markdown 报告、`operation_advice`、三态 `decision_type`、告警规则或真实交易系统。

## 能力边界

- `DecisionSignal` 只记录建议、证据摘要、风险、观察条件、生命周期和来源，不执行下单或调仓。
- 写入失败、提取失败、告警信号关联失败和通知发送失败都不阻断主分析、告警触发或报告保存。
- #1756 已将 `decision_profile` 字段化并修正 server-side filter、去重、续期和 active 失效语义；#1757 在该正式字段契约上增加用户确认后的 reassess persist。两者都不新增环境变量、config registry 项或 `.env.example` 内容。
- 当前没有 `DECISION_SIGNAL_*` 开关；信号功能的关闭或回滚通过 revert 对应代码完成。

## 字段与枚举

核心字段由 `api/v1/schemas/decision_signals.py` 定义，主要包括：

- 身份与来源：`stock_code`、`stock_name`、`market`、`source_type`、`source_agent`、`source_report_id`、`trace_id`、`decision_profile`、`trigger_source`。
- 建议语义：`action`、`action_label`、`confidence`、`score`、`horizon`、`market_phase`、`plan_quality`、`status`。
- 计划与解释：`entry_low`、`entry_high`、`stop_loss`、`target_price`、`invalidation`、`watch_conditions`、`reason`、`risk_summary`、`catalyst_summary`。
- 证据与质量：`evidence`、`data_quality_summary`、`metadata`。
- 生命周期：`expires_at`、`created_at`、`updated_at`。

枚举取值：

| 字段 | 取值 |
| --- | --- |
| `market` | `cn`、`hk`、`us`、`jp`、`kr`、`tw` |
| `source_type` | `analysis`、`agent`、`alert`、`market_review`、`manual` |
| `market_phase` | `premarket`、`intraday`、`lunch_break`、`closing_auction`、`postmarket`、`non_trading`、`unknown` |
| `action` | `buy`、`add`、`hold`、`reduce`、`sell`、`watch`、`avoid`、`alert` |
| `horizon` | `intraday`、`1d`、`3d`、`5d`、`10d`、`swing`、`long` |
| `decision_profile` | `conservative`、`balanced`、`aggressive`；数据库 `NULL` 表示 legacy / unknown |
| `plan_quality` | `complete`、`partial`、`minimal`、`unknown` |
| `status` | `active`、`expired`、`invalidated`、`closed`、`archived` |

Web 展示必须把这些 wire value 映射为当前 UI 语言的用户可读标签；API 响应继续保留原始枚举值。

## Canonical 评分与 action 口径

个股分析、技术评分 fallback、报告展示 fallback 与 `DecisionSignal` 提取共用 `decision-scale-v1` 口径。`decision_type` 只保留 `buy|hold|sell` 兼容统计；更细的可执行语义以八态 `action` 为准。

- 用户侧可见面存在两类字段：`operation_advice` 保留文本口径（如“持有观察”），`action` 作为统一 8 态决策口径（如 `hold/watch/reduce`）用于风控、回测与列表展示。新生成或最终保存前重算的个股报告应优先让两者保持一致；历史记录或兼容载荷仍出现语义冲突时，默认以 `action` 为列表、回测、DecisionSignal 等结构化展示的优先字段，`operation_advice` 仅作说明文本保留。

| score | signal key | `action` | legacy `decision_type` | 语义 |
| --- | --- | --- | --- | --- |
| 80-100 | `strong_buy` | `buy` | `buy` | 强烈买入，高胜率机会，可执行买入/加仓计划 |
| 60-79 | `buy` | `buy` | `buy` | 偏积极机会，允许少量待确认项 |
| 40-59 | `watch` | `watch` | `hold` | 信号分歧或确认不足，等待触发条件 |
| 20-39 | `reduce` | `reduce` | `sell` | 风险明显抬升，优先降低暴露 |
| 0-19 | `sell` | `sell` | `sell` | 趋势或风险显著恶化，优先退出 |

如果 `score >= 60` 但最终 `action` 是 `hold/watch`，或 `score < 40` 但最终 `action` 仍是 `hold/watch`，必须有明确 guardrail 解释，例如 `dashboard.decision_stability.reason`、`dashboard.decision_score_calibration.guardrail_reason` 或 `metadata.guardrail_reason`。风控降级会保留 `raw_score`、`adjusted_score`、`raw_action`、`final_action` 和原因；没有明确原因的中性动作在 DecisionSignal 提取时会按 canonical score 对齐为 `buy/reduce/sell`。

## 生命周期、去重与状态

`src/services/decision_signal_service.py` 是信号生命周期的主入口：

- `horizon` 和 `expires_at` 显式传入时优先。
- 未传 `horizon` 时，`alert` 或盘前/盘中/午间休市/集合竞价阶段默认 `intraday`，盘后、非交易时段、未知阶段或缺少阶段时默认 `3d`。
- `intraday` 过期时间优先读取低敏 `metadata.market_phase_summary.minutes_to_close/minutes_to_open`；缺失时按市场 fallback TTL。
- `expired`、`invalidated`、`closed`、`archived` 不能通过 `PATCH /status` 直接恢复为 `active`。
- 同源去重优先使用 `(source_report_id, source_type, market, stock_code, decision_profile, action, horizon, market_phase)`；没有 report 但有 `trace_id` 时使用 trace 维度。
- `decision_profile` 参与信号身份：`NULL` 只与 `NULL` 匹配，非空 profile 只与相同 profile 匹配。Exact dedup、relaxed dedup、horizon/phase fill、expired refresh、active invalidation 和 stale backfill invalidation 都遵循该 same-profile 语义。
- 新的相反 active 信号只会把同 profile 的旧 active 信号标记为 `invalidated`，并把失效来源写入 metadata。不同非 `NULL` profile 可并存，即使 action 相反。
- Expired duplicate refresh 不会改写 `decision_profile`，只能刷新同 profile 记录。

## API

当前公开接口由 `api/v1/endpoints/decision_signals.py` 和 `docs/architecture/api_spec.json` 描述：

- `POST /api/v1/decision-signals`：创建或按同源键去重，返回 `{ item, created }`。
- `GET /api/v1/decision-signals`：分页查询，支持市场、股票、动作、阶段、`decision_profile`、来源、状态、时间范围和持仓过滤。省略或传空 `decision_profile` 不加 profile 条件，返回所有 profile；`decision_profile=unknown` 查询 `NULL` 行；合法 profile 精确匹配。
- `GET /api/v1/decision-signals/{signal_id}`：查询单条。
- `PATCH /api/v1/decision-signals/{signal_id}/status`：更新状态和可选 metadata。
- `GET /api/v1/decision-signals/latest/{stock_code}`：查询股票最新 active 信号。
- `POST /api/v1/decision-signals/outcomes/run`：显式触发后验评估。
- `GET /api/v1/decision-signals/outcomes`、`GET /api/v1/decision-signals/outcomes/stats`、`GET /api/v1/decision-signals/{signal_id}/outcomes`：查询后验结果与统计。
- `GET/PUT /api/v1/decision-signals/{signal_id}/feedback`：查询或写入 useful / not useful 反馈。
- `POST /api/v1/decision-signals/reassess`：基于来源历史报告快照重新计算不同决策风格下的信号；`persist=false` 只预览，`persist=true` 由服务端重算并保存通过 guardrail 的结果。

这些接口继承现有 `/api/v1/*` 管理员鉴权；`ADMIN_AUTH_ENABLED=true` 时需要有效管理员会话 Cookie。

## Reassess preview 与 persist

`reassess` 只使用 `source_report_id` 对应的持久化历史报告快照。`persist=false` 用于用户确认前预览；`persist=true` 会以相同 `source_report_id + decision_profile` 在服务端重新计算，不信任之前 preview 或客户端缓存的任何决策字段。

请求只支持：

```json
{
  "source_report_id": 123,
  "decision_profile": "aggressive",
  "persist": false
}
```

契约边界：

- `source_report_id` 是唯一事实来源，重评估只读取对应持久化历史报告快照。
- Request 只允许 `source_report_id`、`decision_profile`、`persist`。不支持 `signal_id`，也不接受客户端提交 `action`、`score`、`confidence`、`horizon`、`invalidation`、`stop_loss`、`target_price`、`metadata`、`scoring_breakdown` 或 `guardrail_result` 等权威字段；额外字段会返回 HTTP 422，不会被静默忽略。
- 重评估不会静默抓取实时行情，也不会用当前市场数据补齐历史快照。
- 来源报告内容验证在 preview/persist 中一致：缺失或非法 `source_report_id` 返回 HTTP 422；报告不存在返回 HTTP 404 `source_report_not_found`；非个股报告返回 HTTP 400 `unsupported_report_type`；持久化快照不足以生成决策信号时返回 HTTP 400 `unsupported_report_snapshot`。Persist 还要求来源报告具有有效 `created_at`，否则返回 HTTP 400 `unsupported_report_snapshot` 且不写库；preview 不依赖该存储生命周期字段。
- data quality 会归一为 `high`、`medium`、`low`、`poor`、`unknown`，guardrail 只使用归一化后的等级。
- Preview 成功返回 `preview`、`item=null`、`created=false`；它不写库，也不进入列表、latest 或时间线。
- Persist 成功返回 `preview=null`、后端权威 `item` 和 `persist_status`。`persist_status=created` 表示新建；`existing` 表示同一字段化 identity 的记录已存在且未被改写；`refreshed` 表示按既有 expired refresh / dimension-fill 语义复用并刷新记录。兼容字段 `created` 只在 `created` 时为 `true`。`persist_status` 只描述本次写入 disposition，不代表 `item.status` 必然为 active；新建的历史信号也可能因到期或被较新相反信号取代而以 `expired/invalidated` 返回。
- Reassess persist 与 lazy backfill 使用同一历史生命周期：`created_at` 锚定来源报告时间，`expires_at` 从报告时间、horizon、market 及持久化的 `market_phase_summary` 计算。阶段摘要只保留 `phase/session_date/minutes_to_open/minutes_to_close`；不会用保存当天或实时行情重新赋予有效期。
- 同 profile 相反信号的失效顺序同样按历史信号不可变的 `created_at` 判断，expired refresh 的 `updated_at` 不改变历史优先级。保存旧报告不得淘汰较新的相反信号；仍在有效期内但已被较新相反信号取代的历史 item 会以 `invalidated` 返回，且 API 返回失效处理后的最终数据库状态。
- `created` item 写入 `source_type=analysis`、原 `source_report_id`、`source_agent=decision_profile_reassess`、`trigger_source=web:decision_profile_reassess` 和正式 `decision_profile`；metadata 保存 `profile_source=user_selected`、`profile_policy_version`、`signal_generation_version`、`scoring_version`、`scoring_breakdown`、`data_quality_level` 和完整 `guardrail_result`。
- `existing` item 原样保留最初的 source fields 和 metadata。例如普通分析已经自动生成同 identity 的 `balanced/auto_default` 信号时，用户再次确认 balanced reassess 会返回该记录，不覆盖为 `user_selected`，也不会声称新建成功。终态 existing 不会重新激活。
- `refreshed` item 保留不可变的原始创建 provenance（`source_type`、`source_report_id`、`source_agent`、`trigger_source`、`created_at` 等），并沿用 #1756 repository 的两个既有子语义：expired refresh 会更新允许变化的决策字段、有效期和本次 reassess audit metadata；active relaxed dimension-fill 只补齐缺失的 horizon/market phase，保留原 metadata。客户端必须以后端返回 item 为准，不能仅凭 `refreshed` 推断 metadata 已被替换。
- `guardrail_result` 是机器审计数据，记录 `raw_action`、`final_action`、`passed`、`violations`、`adjustments`、`adjusted`；`warnings` 是用户可读摘要。测试和客户端逻辑应优先依赖 warning 的稳定 `code`，`message` 只用于首版展示。
- `MIN_ACTIONABLE_CONFIDENCE = 0.5`。所有 `buy/add` 还必须具备 horizon、invalidation 或 stop loss、合法价格关系，且 data quality 不能是 `poor/unknown`；aggressive `buy/add` 额外要求明确 invalidation，且不接受 `long` horizon。
- 缺失置信度/invalidation 或数据质量不足时，可审计地降级为 `watch`，并记录 `passed=true, adjusted=true`。价格关系互相矛盾时无法在不改写历史快照语义的前提下保存有效计划，因此记录 `passed=false`。
- Preview-only 的 `passed=false` 仍以 HTTP 200 展示，UI 必须突出 `blocked_reason`。Persist 重算得到 `passed=false` 时返回 HTTP 400 `guardrail_blocked`，包含 `blocked_reason` 和结构化 `warnings`，不写库，也不返回 `created=true`。
- 每次 persist 重算都必须先满足 `guardrail_result.passed=true` 才能进入写入链；`created/refreshed` 的 `item.action` 等于本次 `guardrail_result.final_action`。`existing` 返回原记录及其原始 metadata，不伪造本次 guardrail audit。
- 默认分析和 lazy backfill 仍只自动生成 `balanced`；用户可显式选择并确认保存 balanced、conservative 或 aggressive，其中 conservative/aggressive 不会自动生成。
- aggressive 不是模型采样温度语义，也不会自动生成三套 profile 信号。

## Web 展示

Web 入口位于 `/decision-signals`：

- 默认查询 `status=active`。
- 页面顶部提供页面级“当前股票”主路径，独立于高级列表筛选。用户提交主股票、选择自动补全候选或点击候选 chip 后，latest active 与时间线共用同一个已应用股票上下文；只修改输入草稿不会触发 latest 或时间线查询。
- 当前股票候选优先展示最近分析过的股票；如果没有历史候选，或历史候选加载失败，则降级展示股票索引中 active 且 popularity 较高的热门股票。候选只作为手动点击入口，页面加载时不会自动提交查询；历史和股票索引都不可用时仅显示无候选降级文案。
- 当前股票上下文会显示已应用的代码、名称和可推导市场，并提供清空入口。清空会让 latest 与时间线回到引导态，不影响高级列表筛选或列表来源详情抽屉。
- 支持按市场、股票代码、动作、市场阶段、来源、来源报告 ID 和状态进行高级列表筛选；这些筛选不等同于当前股票上下文，也不会污染 latest active 查询。
- 单支股票信号时间线复用现有 `GET /api/v1/decision-signals` list API，不新增 timeline endpoint。时间线必须先应用非空当前股票后才会查询；没有当前股票时只显示引导态，不拉取 market-only 或 global timeline。
- 时间线只支持 `30d`、`90d`、`180d` 三个时间范围，默认 `90d`；每次最多请求 100 条。若返回 `total > items.length`，Web 会显示“仅展示最近 100 条信号，请缩小时间范围”，避免静默展示不完整轨迹。
- 时间线筛选保留独立的 market、range、status 表单和查询按钮。选择新当前股票时，如果能推导市场，只在这一次初始化时间线 market；用户之后可以手动改 market，查询以按钮提交时的表单快照为准。
- 时间线 status filter 只支持 `all` 与 `active`：`all` 不传 `status`，`active` 传 `status=active`。P1 不提供 terminal status filter，也不做前端 terminal 过滤。
- 时间线支持 profile filter，复用 list API 的 server-side `decision_profile` 查询；`unknown` 只用于筛选和展示 legacy `NULL` 行。普通高级列表不新增 profile filter。
- 信号表现统计保持全局已复盘 outcome 口径，不等于当前可见信号数量，也不随当前股票或高级列表筛选变化；当已复盘样本数为 0 时，Web 显示零样本空状态而不是一组 `0/-` 指标。
- Web 展示优先读取正式 `decision_profile` 字段，只有字段缺失时才回退 legacy metadata；历史缺失或非法 profile 的信号显示为 `unknown`，不会误标为 `balanced`。
- market filter 在 API / 服务层与 Web 前端均已支持 `cn/hk/us/jp/kr/tw`；`jp/kr/tw` 的前端本地化标签均已补齐，`tw` 信号可经 API 正常写入、按 `market=tw` 查询，并可在 Web DecisionSignal 页面通过市场筛选项选择台股（tw）；告警（大盘红绿灯）市场支持 `cn/hk/us/jp/kr`。
- 详情抽屉展示动作、状态、评分、置信度、周期、计划质量、市场阶段、价格计划、风险、观察条件、证据、数据质量和 metadata。
- 详情抽屉或已有来源报告 ID 的页面上下文可以发起 reassess preview；没有可用来源报告 ID 时入口禁用。Preview 本身不加入列表、latest 或时间线；通过 guardrail 后可由用户二次确认保存。保存会重新请求 `persist=true`，成功后只使用响应中的后端 `item`；`created`、`existing`、`refreshed` 使用不同反馈，existing 不会被描述为新建，终态 existing 不会被乐观注入 active latest/时间线，created/refreshed 才按返回状态更新并刷新相关视图。Web 不会把 preview 拼成本地信号。
- 保存时的 guardrail 调整 warning 会保留显示。如果 persist 重算被 guardrail 阻断，Web 会显示 `blocked_reason` 和结构化 warning，保留 preview 供用户理解，且不会把失败结果加入时间线。
- 首页分析表单不提供 `decision_profile`；默认自动生成路径仍只使用 `balanced`。
- Web 只能把信号标记为 `closed`、`invalidated` 或 `archived`，不提供 terminal 状态恢复为 active。
- 历史报告详情不再内嵌展示报告绑定的 `source_type=analysis` 信号，也不会因打开报告详情触发 `source_report_id` 信号查询；需要查看报告来源信号时统一进入 `/decision-signals` 页面按来源报告 ID 精确筛选，或打开 `/decision-signals?sourceReportId=<recordId>` deep link。该筛选和 deep link 都会使用 `source_type=analysis + source_report_id` 的精确查询，以保留旧报告的 best-effort 懒回填入口。
- 持仓页异步查询每个唯一持仓的 latest active 信号，单只查询失败只显示降级提示，不阻断组合快照或其他持仓信号。

所有用户可见枚举必须使用 i18n 标签；技术 ID、股票代码、API 字段名、env key、URL 示例可以保留英文。

## Decision profile identity

#1756 后 `decision_profile` 是 `decision_signals` 的正式 nullable 字段，同时 metadata 保留兼容字段：

- `decision_profile=balanced`
- `profile_source=auto_default`：普通新分析生成路径。
- `profile_source=backfill_defaulted`：历史报告 lazy backfill 路径。
- `profile_policy_version=decision-profile-v1`
- `signal_generation_version=legacy-report-extractor-v1`
- `decision_signal_metadata_version=decision-signal-metadata-v1`

- 新写入时，顶层合法 `decision_profile` 优先；顶层显式 `null`、空值或非法值直接拒绝。顶层缺失时才 fallback 合法 `metadata.decision_profile`；二者都缺失或 metadata profile 非法时默认写入 `balanced`。
- 新写入会同步 `metadata.decision_profile` 为正式字段值，避免双源冲突；metadata 省略或显式 `null` 均按无 metadata 处理，object 会浅复制，非 object 会被拒绝。
- PATCH metadata 省略时保留原值，显式 `null` 时清空为 SQL `NULL`，object 时整包替换。正式 profile 非 `NULL` 时会覆盖 metadata 中的冲突值；正式 profile 为 legacy `NULL` 时会移除请求 object 中的 profile key，且不会提升正式字段。
- 自动失效写入同样遵循正式字段权威语义：正式 profile 非 `NULL` 时同步 metadata profile；legacy `NULL` 时只追加失效信息，保留原 legacy metadata，不注入或删除 profile。
- Legacy / unknown 只用数据库 `NULL` 表示。普通自动生成与 lazy backfill 不写入 `scoring_version` 或 `scoring_breakdown`；只有用户显式发起的 reassess 路径根据 profile policy 生成并审计这些字段。这不代表自动生成三套 profile，也不包含 #1758 的 profile-aware outcome calibration。
- Lazy backfill 语义：省略 profile 保留旧的 `source_type=analysis + source_report_id` 懒回填；`decision_profile=balanced` 可生成 balanced 回填；`decision_profile=unknown`、`conservative`、`aggressive` 不自动创建行。回填与 reassess persist 共享来源报告时间、历史 TTL 和 superseded 判断，不存在第二套历史生命周期。

## 市场结构 metadata

普通个股分析和 Agent 个股分析如果携带 `market_structure_context`，自动提取 `DecisionSignal` 时会把以下低敏字段追加到 metadata：

- `market_structure_version`
- `market_theme_version`
- `stock_market_position_version`
- `market_structure_status`
- `primary_theme`
- `theme_phase`
- `stock_role`
- `market_structure_risk_tags`

这些字段只用于解释信号所处题材背景，不参与 `action`、`score`、`horizon`、同源去重键或生命周期计算。它们也不是题材龙头证明；当 `market_structure_risk_tags` 或缺失证据显示成分股、leader stocks 不完整时，客户端和后验分析应按降级题材证据处理。

快照字段中的 `provider` / `dataset` 来自市场结构抽取链路元数据，属于运行后持久化证据，不参与 LLM provider/model 路由、`base URL` 解析、`.env` 写回或配置迁移；可核验范围见 `src/schemas/market_structure.py`。

## 告警、通知与组合风险

- 股票级真实告警触发会优先关联同标的 latest active 信号，并把低敏 `decision_signal_summary` 写入 `alert_triggers.diagnostics`。
- 没有 active 信号时，告警 worker 只创建最小 `source_type=alert/action=alert` 信号。
- 告警信号的 `trace_id=alert-rule-<hash>` 只用于同源重试的 best-effort 去重，不覆盖 active 信号本体。
- 通知只引用公开摘要字段：`action`、`horizon`、`reason`、`watch_conditions`、`risk_summary`、`source_report_id`。
- 通知中的 `reason` 在脱敏后完整展示，避免固定字符数在句中截断；`watch_conditions` 和 `risk_summary` 仍保持紧凑摘要上限。
- 通知不得输出 signal `metadata`、`evidence`、raw diagnostics、webhook URL、token 或 cookie。
- `GET /api/v1/portfolio/risk` 的 `decision_signal_risk` 只统计当前持仓中的 active `sell/reduce/alert` 信号，查询失败时 fail-open。

更多告警和通知细节见 `docs/alerts.md` 与 `docs/notifications.md`。

## 后验评估与反馈

P5 通过 sidecar 表保存用户反馈和后验结果，不扩展 `decision_signals` 主表：

- `decision_signal_feedback` 保存每个信号最新的 `useful|not_useful` 反馈、可选原因/备注和来源。
- `decision_signal_outcomes` 按 `(signal_id, horizon, engine_version)` 幂等保存后验评估结果。
- 当前 `engine_version=decision-signal-v1`。
- 后验评估只支持日线可验证的 `1d/3d/5d/10d`；`intraday/swing/long`、非方向动作、缺价和 forward bars 不足会写入 `eval_status=unable` 与明确 `unable_reason`。
- 评估时冻结 action、market、market_phase、source_type、source_agent、plan_quality、data_quality_level、holding_state 等统计维度，历史统计不依赖后续 live join。

## 脱敏与低敏边界

信号写入和状态更新使用 `src/utils/sanitize.py` 中的 `sanitize_decision_signal_text()` 与 `sanitize_decision_signal_payload()`：

- 文本字段、JSON 字段和展示型短文本写入前会脱敏。
- 覆盖敏感 key、Bearer、Authorization/Cookie header 或赋值、token-like 字符串、webhook URL、URL userinfo，以及带敏感 query/fragment 参数的 URL。
- 普通证据 URL 会保留，保证来源可追溯。
- `trace_id` 是同源去重身份字段；如果包含会被脱敏的 credential，API 会拒绝请求，而不是保存被 redaction 破坏后的身份值。
- Web 的 JSON 展示只显示后端已脱敏数据，不应重新拼接 raw diagnostics 或配置值。

P7 的全局验收是确认信号池、通知摘要和 Web 展示不泄露 token、cookie、webhook URL、API key、邮箱密码等敏感信息。

## 迁移与回滚

#1756 对 SQLite 执行非破坏性 migration。

迁移说明：

- 升级后无需新增 `.env`、`.env.example` 或 Web 设置项。
- Existing SQLite 只在缺列时 `ALTER TABLE ADD COLUMN decision_profile`，不会 drop/rebuild `decision_signals`，也不会删除旧 index。
- Migration 会幂等创建 profile-aware indexes，并 row-by-row 防御解析 `metadata_json`：仅合法 `metadata.decision_profile` 回填到正式字段；invalid JSON、非 object 或非法 profile 保持 `NULL`。启动日志会记录 backfilled、invalid JSON、non-object、invalid profile 和 skipped existing profile 统计，这些统计只用于诊断，不阻断启动。
- 旧历史报告不会批量回填。只有显式调用信号列表接口或在 Web AI 建议页按来源报告 ID 触发精确查询 `source_type=analysis + source_report_id` 且无命中时，才会 best-effort 懒回填。
- 已存在的 `decision_signals`、feedback 和 outcome 数据保持兼容。

回滚说明：

- 当前没有 `DECISION_SIGNAL_*` 开关；关闭信号提取/写入的回滚方式是 revert 相关代码。
- 回滚后，普通报告保存、告警触发、通知发送和组合风险主流程仍按既有路径运行。
- 回滚不会自动删除历史 `decision_signals`、`decision_signal_feedback` 或 `decision_signal_outcomes` 数据；如需清理，应由维护者单独制定数据清理策略。
