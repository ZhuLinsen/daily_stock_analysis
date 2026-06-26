# DecisionSignal 决策信号专题

本页收口 #1390 P7，说明 DSA 如何把个股分析、Agent、告警和组合风险中的 AI 建议沉淀为可查询、可反馈、可后验评估的 `DecisionSignal` 资产。它是报告之上的结构化索引，不替代 Markdown 报告、`operation_advice`、三态 `decision_type`、告警规则或真实交易系统。

## 能力边界

- `DecisionSignal` 只记录建议、证据摘要、风险、观察条件、生命周期和来源，不执行下单或调仓。
- 写入失败、提取失败、告警信号关联失败和通知发送失败都不阻断主分析、告警触发或报告保存。
- P7 不新增 API、数据库字段、环境变量、config registry 项或 `.env.example` 内容。
- 当前没有 `DECISION_SIGNAL_*` 开关；信号功能的关闭或回滚通过 revert 对应代码完成。

## 字段与枚举

核心字段由 `api/v1/schemas/decision_signals.py` 定义，主要包括：

- 身份与来源：`stock_code`、`stock_name`、`market`、`source_type`、`source_agent`、`source_report_id`、`trace_id`、`trigger_source`。
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
| `plan_quality` | `complete`、`partial`、`minimal`、`unknown` |
| `status` | `active`、`expired`、`invalidated`、`closed`、`archived` |

Web 展示必须把这些 wire value 映射为当前 UI 语言的用户可读标签；API 响应继续保留原始枚举值。

## 生命周期、去重与状态

`src/services/decision_signal_service.py` 是信号生命周期的主入口：

- `horizon` 和 `expires_at` 显式传入时优先。
- 未传 `horizon` 时，`alert` 或盘前/盘中/午间休市/集合竞价阶段默认 `intraday`，盘后、非交易时段、未知阶段或缺少阶段时默认 `3d`。
- `intraday` 过期时间优先读取低敏 `metadata.market_phase_summary.minutes_to_close/minutes_to_open`；缺失时按市场 fallback TTL。
- `expired`、`invalidated`、`closed`、`archived` 不能通过 `PATCH /status` 直接恢复为 `active`。
- 同源去重优先使用 `(source_report_id, source_type, market, stock_code, action, horizon, market_phase)`；没有 report 但有 `trace_id` 时使用 trace 维度。
- 新的相反 active 信号会把旧 active 信号标记为 `invalidated`，并把失效来源写入 metadata。

## API

当前公开接口由 `api/v1/endpoints/decision_signals.py` 和 `docs/architecture/api_spec.json` 描述：

- `POST /api/v1/decision-signals`：创建或按同源键去重，返回 `{ item, created }`。
- `GET /api/v1/decision-signals`：分页查询，支持市场、股票、动作、阶段、来源、状态、时间范围和持仓过滤。
- `GET /api/v1/decision-signals/{signal_id}`：查询单条。
- `PATCH /api/v1/decision-signals/{signal_id}/status`：更新状态和可选 metadata。
- `GET /api/v1/decision-signals/latest/{stock_code}`：查询股票最新 active 信号。
- `POST /api/v1/decision-signals/outcomes/run`：显式触发后验评估。
- `GET /api/v1/decision-signals/outcomes`、`GET /api/v1/decision-signals/outcomes/stats`、`GET /api/v1/decision-signals/{signal_id}/outcomes`：查询后验结果与统计。
- `GET/PUT /api/v1/decision-signals/{signal_id}/feedback`：查询或写入 useful / not useful 反馈。

这些接口继承现有 `/api/v1/*` 管理员鉴权；`ADMIN_AUTH_ENABLED=true` 时需要有效管理员会话 Cookie。

## Web 展示

Web 入口位于 `/decision-signals`：

- 默认查询 `status=active`。
- 支持按市场、股票代码、动作、市场阶段、来源、来源报告 ID 和状态筛选。
- market filter 在 API / 服务层与 Web 前端均已支持 `cn/hk/us/jp/kr/tw`；`jp/kr/tw` 的前端本地化标签均已补齐，`tw` 信号可经 API 正常写入、按 `market=tw` 查询，并可在 Web DecisionSignal 页面通过市场筛选项选择台股（tw）；告警（大盘红绿灯）市场仍为 cn/hk/us。
- 详情抽屉展示动作、状态、评分、置信度、周期、计划质量、市场阶段、价格计划、风险、观察条件、证据、数据质量和 metadata。
- Web 只能把信号标记为 `closed`、`invalidated` 或 `archived`，不提供 terminal 状态恢复为 active。
- 历史报告详情不再内嵌展示报告绑定的 `source_type=analysis` 信号，也不会因打开报告详情触发 `source_report_id` 信号查询；需要查看报告来源信号时统一进入 `/decision-signals` 页面按来源报告 ID 精确筛选，或打开 `/decision-signals?sourceReportId=<recordId>` deep link。该筛选和 deep link 都会使用 `source_type=analysis + source_report_id` 的精确查询，以保留旧报告的 best-effort 懒回填入口。
- 持仓页异步查询每个唯一持仓的 latest active 信号，单只查询失败只显示降级提示，不阻断组合快照或其他持仓信号。

所有用户可见枚举必须使用 i18n 标签；技术 ID、股票代码、API 字段名、env key、URL 示例可以保留英文。

## 告警、通知与组合风险

- 股票级真实告警触发会优先关联同标的 latest active 信号，并把低敏 `decision_signal_summary` 写入 `alert_triggers.diagnostics`。
- 没有 active 信号时，告警 worker 只创建最小 `source_type=alert/action=alert` 信号。
- 告警信号的 `trace_id=alert-rule-<hash>` 只用于同源重试的 best-effort 去重，不覆盖 active 信号本体。
- 通知只引用公开摘要字段：`action`、`horizon`、`reason`、`watch_conditions`、`risk_summary`、`source_report_id`。
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

本功能在 P1-P6 已完成所需表和 sidecar 结构；P7 不新增 migration。

迁移说明：

- 升级后无需新增 `.env`、`.env.example` 或 Web 设置项。
- 旧历史报告不会批量回填。只有显式调用信号列表接口或在 Web AI 建议页按来源报告 ID 触发精确查询 `source_type=analysis + source_report_id` 且无命中时，才会 best-effort 懒回填。
- 已存在的 `decision_signals`、feedback 和 outcome 数据保持兼容。

回滚说明：

- 当前没有 `DECISION_SIGNAL_*` 开关；关闭信号提取/写入的回滚方式是 revert 相关代码。
- 回滚后，普通报告保存、告警触发、通知发送和组合风险主流程仍按既有路径运行。
- 回滚不会自动删除历史 `decision_signals`、`decision_signal_feedback` 或 `decision_signal_outcomes` 数据；如需清理，应由维护者单独制定数据清理策略。
