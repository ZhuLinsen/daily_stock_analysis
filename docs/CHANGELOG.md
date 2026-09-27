# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) page.

## [Unreleased]

- [新功能] 新增同花顺 fuyao (aicubes REST) 作为 fundamental 数据第 4 cross-validation 验证源（opt-in 默认关）：`data_provider/fuyao_adapter.py` 新增 `FuyaoFetcher`（`requests.Session` + `urllib3.Retry` 限流/服务端重试，`Bearer` 鉴权，fail-open）+ `FuyaoSource`（SourceAdapter）+ `_to_thscode`（项目 ticker → thscode 带交易所后缀：A 股按 60/688/9 → SH、00/30/20 → SZ、8/4 → BJ 分桶；港股 5 位 → HK；美股字母 → US）+ `_map_period`（用户可见 period → fuyao `YYYY-N`）+ Pydantic v2 `FuyaoResponse/FuyaoItem`（strict + frozen + extra=ignore）。字段 → endpoint 路由：行情 / 估值 / 财务三组 endpoint 分别覆盖 current_price / total_mv / circ_mv / pe / pb / revenue / net_profit / roe / gross_margin / revenue_yoy / net_profit_yoy
- [改进] `src/config.py` 新增 `ENABLE_FUYAO` / `FUYAO_ENDPOINT` / `FUYAO_API_KEY` / `FUYAO_TIMEOUT_SECONDS` 4 个配置项（沿用 Choice MCP 的 None/"" 区分契约与 `parse_env_float(1.0~300.0)` 边界） + `.env.example` 同段新增（`FUYAO_ENDPOINT` 留空占位符，由 fetcher 内置默认回落）；`src/agent/tools/cross_validation_helpers._build_sources` 追加 `FuyaoSource` 装配块（enable=true + key 非空时才挂入第 4 源，默认零回归）
- [测试] `tests/test_fuyao_adapter.py` 新增 85 用例（`_to_thscode` 19 + `_map_period` 16 + `_endpoint_for` 3 + `_parse_fuyao_response` 15 + Pydantic schema 4 + `FuyaoFetcher` mocked 17 + `FuyaoSource` 8 + 凭据脱敏 1；mock 覆盖 401/429/500/timeout/ConnectionError/business error_code≠0/None payload/null fields）；`tests/test_cross_validation_helpers.py` 追加 4 个 fuyao 装配矩阵（opt-in 关/开无 key/开有 key/与 Choice MCP 同开四源装配）。运行时凭据仍走 `~/.config/dsa/credentials` → `FUYAO_API_KEY`（不进 .env、不进 git、不打印任何片段）
- [修复] 东财 Choice MCP（妙想 MCP）生产端到端打通：`MxMcpFetcher.__init__` 区分 `None`（回落默认）与空字符串（显式禁用）endpoint 语义；`_extract_key_value_pairs` 新增 `{"data":[{"columns":[],"items":[["<metric>","<value>",...]]}]}` 真实 shape 分支（先前只认 `{response:{...}}`/Markdown，生产整体读不出）；`_MX_MCP_ANCHOR_QUERIES` 扩展 current_price（加「收盘价（元）」「收盘价」）、pb_ratio（加「市净率PB」）、net_profit（加「归属于母公司股东的净利润」），与服务端真实指标名对齐；`_safe_float` 新增「倍」后缀剥离（pe/pb 倍数指标可解析）。验证：活体 600519 六锚点（current_price/pe_ratio/pb_ratio/total_mv/revenue/net_profit）全部拿到 AnchorReading、走通 `build_cross_validation_block` 双源验证（5/6 conf=high，1/6 conf=low 是 mock primary 偏 1% 的预期行为）；`tests/test_mx_mcp_adapter.py` 新增 4 个真实 shape fixture 用例；39/39 单测通过。运行时凭据仍走 `~/.config/dsa/credentials`（不进 .env / 不进 git），`docs/.env.example` 模板注释保留 opt-in 配置项。
- [修复] Choice MCP 端到端审计闭环：`_judge_numeric` / `_judge_direction` 接受可选 `tertiary` 参数，当 3 源同时返回读数时走 majority vote —— primary+secondary 一致 → high（含 3rd sources tuple）；不一致时 tertiary 偏任一方 → medium（少数派标 outlier，verdict 仍以 primary 值为基准）；3-way 真冲突 → low；2-source 行为字节不变（drop-in 兼容）。`src/config.py` MX_MCP 配置 3 项对齐 `MxMcpFetcher.__init__` 的 None/"" 契约：endpoint 由 `os.getenv("MX_MCP_ENDPOINT") or "default"` 改为「None 回落默认 / "" 透传」分支；`mx_mcp_api_key` 直接读 env 不再 `or None`；`mx_mcp_timeout_seconds` 改用 `parse_env_float(field_name=..., minimum=1.0, maximum=300.0)`（非法输入 warn + fallback，不再阻塞进程启动）。`_safe_float` 「倍」后缀剥离在 ifind 单测加 3 个显式 case（`18.99倍`/`6.155倍`/`18.99元倍`）。验证：146 单测 + 2 xpass 全过（含新增 9 个 3-way 测试覆盖：3-way 全一致 high / tertiary 偏 primary medium / tertiary 偏 secondary medium / 3-way 真冲突 low / direction 偏 primary medium / direction 偏 secondary medium / direction tertiary=0 medium / caliber mismatch 不进入 3-way / tertiary 缺失退化为 2-source）。
- [新功能] 趋势罗盘页新增「罗盘原理说明」（白话为主 + 关键技术参数括注，zh/en 双语，前端静态内联）：输入区下方默认折叠的五段式说明——模块定位与边界（不做无约束短期预测）、四层结构逐层解释（L0 仓位上限三档 / L1 年线 / L2 趋势段 / L3 节奏 + 阶段合成观察窗）、动作改写原则（约束只否决不升级 + 三个真实实例）、择时信号三形态与纪律（触发价/失效价/逆势博弈仓分离）、失效条件与数据纪律；动作改写节内含「全部 14 条硬约束速查表」（§4.5.2 全表白话化）；五段说明整合为单一「罗盘原理说明」折叠框（框内顶部迷你目录 + 各节锚点跳转，表格整表直出不嵌套，小节标题无编号），Collapsible 组件新增 `maxHeightPx` 参数（展开高度走内联 style，避免 Tailwind 动态类名 JIT 缺失）。纯前端改动（TrendCompassPage + Collapsible 复用），无 API/schema 变更
- [修复] 趋势罗盘 L4 择时审计修复（`.claude/reviews/l4-timing-audit.md`，P1-1 + P2 五项）：`derive_l4(timing_enabled=...)` 函数级默认值改为 false（与 `COMPASS_TIMING_ENABLED` 默认关一致，消除未来调用方漏传参绕过开关的隐患）；top_escape 按命中路径输出变体 reason code（`top_escape_exhaustion`/`top_escape_divergence`/`top_escape_ema_loss`，可并存），长卡与前端卡片可区分衰竭/背离/破位三类逃顶触发；前端 `compass.timing` 增加空值防御（旧后端/异常 payload 不再白屏）；rewriter 删除 B7 放行分支与 row 3 互斥的冗余条件；`.env.example` 与 plan §13.8 补充「开关切换需重启当日生效（当日按标的缓存）」与「放行 ≠ 保证买入（仅解除周线否决，其余硬约束照常生效）」语义说明
- [新功能] 趋势罗盘新增日线 L4 择时信号（plan §13.8 冻结决策）：`pullback_entry`（顺势回踩：EMA20 回踩+RSI 复位 40-55+收复+斜率为正）、`bottom_fishing`（RSI<30 超卖+底背离+止跌；weekly_bear 下可出明确买入信号但仓位提示固定「轻仓」，属逆势博弈仓与趋势仓位分离，携带 5 个交易日时间止损）、`top_escape`（超买衰竭/顶背离/跌破 EMA20，全多头 shielded 结构不输出）；信号统一「触发价+失效价+条件说明」形态（armed 状态仅有条件），是条件触发的交易计划而非价格预测，免责声明按新章程改写；实现：`engine.derive_l4`（compute() 签名不变）+ `fetcher.fetch_daily_ohlcv` 零成本取 OHLCV；rewriter §13.1 修正案（B7）：`weekly_bear` 仅放行 bottom_fishing 的 buy（新 reason code `weekly_bear_bottom_fishing_pass`），其余买入照常否决，API 携带 draft 时自动透传罗盘已发出的 bottom_fishing 信号；schema 增量 `MidtrendCompass.timing`（追加字段，compass_version 不变）；长卡新增第 9 节「择时信号（日线 L4）」（无信号亦渲染说明），Web 页新增「择时信号」卡片（状态徽章/逆势警示/触发价/失效价/有效期/仓位提示，reason code 中文解释+hover 原文）；新配置 `COMPASS_TIMING_ENABLED=false`（默认关）+ `.env.example` + config_registry；新增测试 18 个（timing 12 / render 2 / rewriter 3 / api 1，另存量用例补 timing 透传断言）
- [修复] 趋势罗盘长卡第 5 节与改写结果脱节：`long_card` 新增可选 `rewrite=(draft, RewriteResult)` 参数，携带初稿动作时端点将改写结果注入长卡（结论=最终动作，触发约束按评估顺序渲染编号链路「约束说明（动作：X → Y）」），未携带时明确标注「未指定初稿动作，本节为罗盘默认中性结论」；删除指向 API 内部字段的「rewrite 字段」指路注。顺带修正存量类型漂移：`CompassRewriteView.decision_action` 从 3 态放宽为 8 态 `DecisionAction`（与 action_mapper 契约一致，前端类型同步）
- [改进] 趋势罗盘「动作改写」面板全中文化因果链：rewriter 新增 `RewriteStep`（每步记录触发约束与动作值，`RewriteResult.steps` 按评估顺序下发，API `CompassRewriteView` 增量加 `steps` 字段），前端改画「初稿动作 → ①条件——说明，动作由 X 改为 Y → … → 最终结果 + 投资结论」编号链路，并新增「判定依据」行展示触发判定时的实际状态值（周线/年线/主趋势段/节奏/阶段/K线）；reason code 英文标识默认隐藏（移至 hover tooltip），面板标题去文档编号（§4.5.2 仅留 tooltip）；15 个约束码的中文条件标题+效果文案表与后端 i18n `_REASON` 语义对齐
- [改进] 趋势罗盘长卡（long_card）重写为「结论 → 原理 → 关键数字 → 怎么做」四段式：8 节全部双语化（此前第 4/6/7/8 节硬编码中文，en 输出中英混杂）；第 1 节周线过滤新增结论句、原理说明、现价（日线收盘）相对 200 周线百分比距离（weekly_ema200 缺失时自动跳过）与仓位上限操作指引；第 2 节观察量级补执行窗含义说明；第 3 节指标加方向箭头（▲/▼/→）与 EMA20×EMA50 关系表述；第 5 节移除过期的「P1 placeholder」文案，reason codes 逐条展开为解释语句（i18n 表与前端 TrendCompassPage REASON_TEXT 对齐）；价格精度 4 位小数收敛为 2 位、百分比 1 位；头部新增数据截至日期
- [修复] 趋势罗盘 L0 周线过滤层此前对所有股票恒为「样本不足」：fetcher 默认窗口 600 交易日仅产出 ~170 根周 K，低于引擎播种周线 EMA200 所需的 200 根阈值；默认窗口提升至 1200（~5 年），实测 600519 周 K 337 根、L0 正常输出 weekly_bear
- [新功能] 趋势罗盘 Web 页面（`/trend-compass`）：导航新增「趋势罗盘」菜单（首页之下、深度投研之上）；后端新增 `POST /api/v1/compass/analyze`（复用 P2 fetcher/engine/rewriter/action_mapper/render，当日按标的缓存，不写 history 不进 guardrail 链，独立于 COMPASS_ENABLED）；支持可选「假设初稿动作」演示 §4.5.2 硬约束改写与 reason codes；zh/en 双语；bar_status 判定改统一启发式（当日 K 线 15:30 本地时间后视为收盘确认，pipeline 与 API 共用）；前端 TrendCompassPage（股票搜索复用 StockAutocomplete、长卡复用 ReportMarkdownBody）。E2E 实测：600519 真实行情闭环、422/404 契约正确。
- [新功能] 中期趋势罗盘 P2：动作改写接入个股分析主流程。新增 `compass_rewriter`（plan §4.5.2 硬约束表，按 §13 冻结决策实现：weekly_bear 禁 buy / weekly_transition 仅降级 confidence 不改写动作 / L1+L2 bear 默认 sell 且 L3 exhausted 降 watch）与 `compass_action_mapper`（CompassAction → DecisionAction 8 档 / InvestmentConclusion 6 档单一映射函数）；pipeline guardrail 链在 `daily_market_context_guardrail` 之后挂入罗盘改写（普通与 agent 双路径），改写结果写回 `decision_type/action/operation_advice/investment_conclusion`，降级路径 fetch 失败透传不改写；罗盘快照（final_action + reason codes + L0-L3 + phase）按 §13.7 仅 cron/批量路径落盘 `context_snapshot.midtrend_compass`（`run_full_analysis` 开启 `compass_snapshot_write`，Web 手动分析不落盘）；新增 `COMPASS_ENABLED` 配置（默认 false，§13.4 默认关）+ `.env.example` + config_registry；新增 `strategies/midtrend_compass.yaml`（`default_active=false`）；新增测试 57 个（rewriter 27 / action_mapper 11 / pipeline 接线 12 / strategy yaml 7）。PR-B3 周线独立 fetcher 维持 P1 resample 兜底未动。
- [文档] 中期趋势罗盘（Midtrend Compass）设计文档 v2（`docs/midterm-trend-compass-plan.md`）与 P2 实施计划（`docs/midterm-trend-compass-p2-plan.md`）合回 main；plan v2 §13 待确认项第 1-7 条经 maintainer 冻结（周线偏空分级处置 / L1+L2 bear 默认 sell 且 L3 exhausted 降 watch / 大盘复盘部分复用 / 策略默认关 / 配置项命名定稿 / 一期仅 zh+en / 罗盘快照仅 cron 落盘），第 8 条 backtest 时间点待定；P2 前置阻塞解除。P1 可计算内核为 PR #41（schema + engine + i18n + fetcher + render + CLI + 50 测试）。

- [改进] 前端性能：stocks.index.json（3.3MB）改为模块级单例加载（全会话仅 fetch+parse 一次）+ 首屏后 idle 预载/输入框 focus 兜底（此前每页面挂载即拉取并重复主线程解析）；看板 30s 轮询在页面隐藏时跳过（此前后台标签页每小时 ~480 个无用请求）；SSE 断线重连改指数退避（2s 起、封顶 30s、连续 10 次上限），替代固定 3s 无限重连。
- [改进] 长任务线程隔离：agent/chanlun/deep_research/policy_minesweeper/supply_chain_reports 的 SSE 与同步生成任务改投专用有界线程池（8 worker，池满快速 429 而非无限排队），不再与全部同步 API 端点共享 anyio 默认 40 线程池。
- [改进] /api/v1/schedule/trigger 改为 202 异步执行（后台任务队列），不再占用 HTTP 线程跑完整分析；兼容 query param 与 JSON body 两种调用形式（docs 既有 curl 示例不受影响）；gzip 压缩与静态资产缓存头（/assets immutable、stocks.index.json max-age=3600、SSE 排除压缩）
- [修复] Serenity 方案 C（定时自选股后异步生成供应链深度报告 + 30 天缓存复用）审计修复：存量数据库补 `analysis_trace_id` 列迁移（`_ensure_supply_chain_trace_id_column`，此前已有库全部供应链报告读写直接报错）；后台生成改基于 `run_full_analysis` 实际返回的 (query_id, 股票列表) 触发（此前依赖恒为 None 的变量，整段不执行）；Serenity 报告回填 history 改按 `(query_id, code)` 精确关联（此前按"最新一条"可能回填到无关记录）；缓存命中时保留产业链实数据仅叠加 report 字段（此前 upstream/downstream 等全部置空构成回归）；移除无任何消费方的 `report_status=pending` 僵尸占位；修复 `_backfill_serenity_report_url` 的 `get_db` 作用域错误（运行时 NameError + CI F82 门禁必挂）；港股/美股代码支持单股绑定（此前落 NULL 导致缓存永久 miss）；report_id 生成与 executor 单例初始化加锁修复并发竞态；缓存查询只复用 `status=success` 报告；`update_analysis_history_supply_chain` 记录不存在时正确返回 False。
- [测试] 新增方案 C 回归测试：`tests/test_research_framework_serenity_cache.py`（缓存命中保留实数据 / 不重复追加 serenity / 未命中不写 pending）；`tests/test_supply_chain_report_storage.py` 新增 `TestPlanCAuditFixes`（旧库迁移补列、缓存 status 过滤、(query_id, code) 精确查询、update 返回值语义）；`tests/test_supply_chain_report_service.py` 新增 `TestNormalizeStockCode`（A股/港股/美股归一化）。
- [新功能] 供应链深度报告新增 §10.b 产能展望与预测：基于历史产能数据（来自 §10 FinancialQualityV3）+ 下游需求信号（来自 §9 IndustryOutlookV3）+ 扩产进度，由 LLM 推断未来1-12个月产能走势。短期预测（1-3个月）+ 中期展望（6-12个月），支持需求驱动推断 + 行业模板降级。新增 Schema：CapacityOutlookV3 / CapacityForecastPeriodV3 / ExpansionProjectV3；新增工具：analyze_capacity_outlook；新增渲染函数：render_capacity_outlook；扩展行业模板 _INDUSTRY_INFERENCE_TEMPLATES 增加 capacity_unit_hint / benchmark_utilization / seasonal_pattern 字段；扩展 annual_report_provider.py PDF 扫描至50页 + 新增 extract_capacity_disclosures helper。
- [测试] 新增 `tests/test_supply_chain_capacity_outlook.py`（capacity outlook Schema + 渲染器 + 行业模板测试）；修复 `tests/test_supply_chain_v3_tools.py` 和 `tests/test_supply_chain_services.py` 工具计数断言（10 → 11） + name-based 替代 positional 查找。

- [新功能] 首页新增 `WatchlistPanel` 渲染 `STOCK_LIST` 自选股列表：侧边栏顶部新增面板，把后端 `GET /api/v1/stocks/watchlist` 返回的股票代码以 chip 形式展示，点击 chip 复用现有 `handleSubmitAnalysis` 触发单股分析；超过 `maxVisible`（默认 24）折叠为「还有 N 只」徽标。文件：`apps/dsa-web/src/components/dashboard/WatchlistPanel.tsx`（新）+ `__tests__/WatchlistPanel.test.tsx`（新，5 用例）+ `HomePage.tsx` 接入 + i18n zh/en 新增 5 个 `home.watchlist*` 文案键。`useWatchlist` 现有 `isInWatchlist/toggleWatchlist` 行为保持不变。GitHub issue 已在 `.claude/reviews/issue-watchlist-not-shown.md` 落档（仓库 issues 当前禁用）。
- [新功能] `WatchlistPanel` 新增「分析全部」按钮：自选股 ≥ 2 只时显示，点击复用 `submitAnalysis` store action 新增的 `stockCodes` 批量路径（`stockPoolStore.ts` 新增 `submitAnalysisBatch` 顺序循环助手，按 `analyzeBatchSeq` 中断安全），逐个调 `analysisApi.analyzeAsync` + 现有 dedup + DuplicateTaskError 错误面。HomePage 通过现有 `actions` prop slot 传按钮。WatchlistPanel 测试新增 1 例 actions 渲染。`docs/CHANGELOG.md` 入口同段，扁平格式。
- [文档] Loop Engineering Phase 2 完成：新增 `.github/workflows/loop-triage.yml`（每日 Issue/PR 分流）和 `.github/workflows/loop-ci-sweeper.yml`（CI 失败分析）。
- [文档] Loop Engineering Phase 3 完成：新增 `.github/workflows/loop-dep-sweeper.yml`（依赖检查工作流）；更新 `scripts/check_ai_assets.py` 添加 Loop Skills 检查。
- [文档] Loop Engineering Phase 4 完成：新增 `docs/loop-failure-modes.md`（10 种失败模式与应对策略）、`docs/loop-operating.md`（日常运营手册）和 `docs/loop-design-guide.md`（新 Loop 设计指南与检查清单）。Loop Ready Score 达到 80/110 (L2)。
- [文档] Loop Engineering 用户指南：新增 `docs/loop-user-guide.md`，包含快速开始、核心文件速查、日常使用场景（7 个场景）、AI 协作模板（4 个模板）、命令速查、故障排查和最佳实践。
- [文档] Loop Engineering Phase 1 完成：新增核心文件（LOOP.md/STATE.md/LOOP_BUDGET.md/LOOP_CONSTRAINTS.md/gate.yaml/loop-run-log.md）、4 个 Loop Skills（loop-triage/loop-verify/loop-context/loop-plan）和 3 个脚本（loop-gate.sh/loop-audit.sh/loop-budget.sh）。Loop Ready Score 从 0 提升至 74/100。

- [新功能] BaostockFetcher.get_financial_data()：季频财务数据备份链，6 个 Baostock 接口（profit/operation/growth/balance/cash_flow/dupont）合并为统一 DataFrame，35 个字段映射到项目标准字段名（gross_margin_pct/roe_pct/revenue_yoy_pct/debt_to_asset_pct/inventory_turnover_days/operating_cf_to_revenue 等），返回 index=statDate 的季频数据，失败返回 None。文件：`data_provider/baostock_fetcher.py`（`_map_financial_columns` + `get_financial_data`）；`docs/data-sources.md` 新增 §2.3 Baostock 备份链说明。
- [新功能] §10.b 产能展望 Baostock 财务数据注入：`SupplyChainExecutor._call_v3_tools_directly` 在调用 analyze_capacity_outlook 前调用 BaostockFetcher.get_financial_data() 获取最近 4 期季频数据（营收同比/毛利率/ROE/资产负债率/存货周转天数/经营现金流/营收），格式化后注入 analyze_capacity_outlook 的 financial_context 参数，替换或补充 LLM 推断。
- [修复] analyze_capacity_outlook Decimal JSON 序列化：CapacityOutlookV3 的 Decimal 类型字段（predicted_utilization_pct/predicted_output_volume）通过 model_dump() 后无法被 json.dumps 序列化，导致工具返回异常并 fallback insufficient_data。修复：在 `_finalize_capacity_outlook` 和 `_build_fallback_capacity_outlook` 返回前调用 `_json_safe()` 将 Decimal 递归转为 float。

- [修复] 六维详情"宏观与地缘"维度数据源补齐（P5-fix 第三阶段）：
- [修复] 六维详情"宏观与地缘"维度数据源补齐（P5-fix 第三阶段）：扩 LLM `six_dimension_inputs` schema，开放 2 个 LLM 主观键 `us_china_impact`（minimal/limited/significant/severe，宏观与地缘层面中美关系整体冲击，与 `us_china_risk` 产业链脱钩风险区分）和 `regulatory_risk`（low/medium/high，国内监管风险）。`src/analyzer.py` `_SIX_DIM_KEYS` 加 2 键、`_ENUM_LIKE_KEYS` 加 2 键、`_KNOWN_ENUM_TOKENS` 加 4 个 `us_china_impact` 枚举值（`minimal`/`limited`/`significant`/`severe`），SYSTEM_PROMPT 章节（line 4282）追加 2 键 schema + 显式 disambiguation 提示。`src/services/research_framework_integration.py` `_merge_six_dim` `_STR_KEYS` 加 2 键映射（仅当 raw_data 未填时 setdefault，保留 P4/P5 客观值优先权）。这样 macro 维度 5 键全部可填：客观 3 键（P5 第一阶段 sector_policy + P5 第二阶段 monetary/liquidity）+ 主观 2 键（us_china_impact/regulatory_risk 本阶段）。
- [测试] 新增 `tests/test_six_dimension_inputs_p5_keys.py`（30 用例）：`_SIX_DIM_KEYS` 含 2 新键 + `_ENUM_LIKE_KEYS` 含 2 新键 + `_KNOWN_ENUM_TOKENS` 4 枚举值 + `_coerce_six_dim_value` 4×2 枚举解析（含 null/parenthetical/prose noise 鲁棒性）+ `_merge_six_dim` 7 用例（含不覆盖已有值、防御性输入）+ prompt 文本含 2 新键 + 显式 disambiguation。
- [修复] main_indices 代码前缀兼容（生产实测发现 bug）：`_infer_monetary_policy_from_indices` 原 target_codes 只接受 6 位裸代码（`000300`），但实际数据源返回 `sh000300` / `sz399006` / `bj000xxx` 等带前缀格式，导致**所有 main_indices 被过滤为 non-target，永远返回 None**。修复后用 `_NORMALIZE_CODE` 映射表同时接受带/不带前缀的代码，monetary_policy 真实命中率 0% → 100%。
- [测试] `tests/test_macro_indicators_from_market.py` 新增 5 用例：`sh` / `sz` / `bj` 前缀变体 + 真实今日数据 -1.7% 中性场景 + 混合前缀格式。
- [验证] 11 只自选股端到端重跑：macro 维度 **0 DATA_MISSING**（was 11/11） + 10/11 拿到全部 5 个 indicators + 1/11 PARTIAL（2 个指标，LLM sector_position 输出为空，不属代码 bug）。

- [修复] 六维详情"宏观与地缘"维度数据源补齐（P5-fix 第二阶段）：在 P5 第一阶段（`sector_policy` 多源兜底）基础上，从大盘指数 + 市场总成交额客观推断 `liquidity_indicator` + `monetary_policy`，完全不依赖 `daily_market_context` 大盘分析链路。新建 `src/services/macro_indicators_from_market.py`：`infer_objective_macro_indicators(main_indices, market_stats)` 顶层函数 + `_infer_liquidity_from_market_stats`（两市总成交额 1.5 万亿/0.8 万亿阈值，输出 abundant/moderate/scarce）+ `_infer_monetary_policy_from_indices`（沪深300/创业板指/上证指数 涨跌幅均值 > +2% → accommodative / < -2% → tight / 否则 neutral；⚠️ 临时近似，CHANGELOG 明确标注）。`src/core/pipeline.py` 新增 `_attach_market_overview` 方法（在 `_attach_daily_market_context` 后立即调），单只/批量分析都走这条路径，fail-open 静默失败。`src/services/research_framework_integration.py` `_extract_raw_data_from_context` 在 P4 daily_market_context 注入后增加 P5 客观推断（仅当 daily_market_context 未提供时启用，软导入不破坏现有调用链），用 `setdefault` 保证 P4 优先。
- [新功能] macro 维度 objective 路径完全绕开大盘分析：单只/批量分析均可拿到 `liquidity_indicator` + `monetary_policy` 真实数据（之前依赖 `daily_market_context` 永为 None）。
- [测试] 新增 `tests/test_macro_indicators_from_market.py`（36 用例）：abundant/moderate/scarce 三档边界（>= 闭区间） + tight/accommodative/neutral 边界（严格比较） + 字段别名（change vs change_pct） + 非目标 code 过滤 + 部分缺 change 字段 + 防御性输入（None/garbage）。
- [测试] 新增 `tests/test_pipeline_attach_market_overview.py`（10 用例）：正常注入 + 空 fetcher 结果 + None 输入 + 单边 fetcher 异常 + 双边 fetcher 异常 + 空 market 字符串 + purpose 参数可观测性 + 已有 key 不被覆盖。
- [测试] `tests/test_macro_dimension_data_source.py` 扩展 `TestObjectiveMacroIndicatorsIntegration`（5 用例端到端）：market_stats → liquidity 注入 + main_indices → monetary 注入 + daily_market_context 优先于客观推断 + 完整 5 键 macro 注入 + 完全无数据时不抛异常。

- [修复] 六维详情"宏观与地缘"维度数据源补齐（P5-fix）：在 P4 基础上绕开 `daily_market_context` 大盘依赖，从个股路径直接推断 `sector_policy`：`src/services/research_framework_integration.py` `_infer_sector_policy` 升级为 4 级优先级链（LLM 文本 regex → 行业 KB `policy_lean` 静态兜底 → 板块涨跌幅动态兜底 → 中性分）；新增 `_build_industry_hint` 从 `result.sector_position` + `enhanced_context.fundamental_context.boards` 抽取行业关键词（自动过滤宽基/概念噪声）；新增 `_resolve_sector_policy_hints` 串联 hint + rankings 解析。`src/services/supply_chain/industry_dna_loader.py` 新增 `lookup_industry_policy_lean(industry_hint)` 函数；5 个行业 DNA YAML（医药/半导体/电池/白酒/玻纤）各加 `policy_lean` 字段（supportive / neutral / restrictive）+ `policy_lean_rationale` 解释。`src/scoring/indicators/macro.py` 加节流版 observability：5 键全缺失时打 warning（60s 同 evidence 前缀最多 1 条，避免批量日志洪水）。
- [新功能] 行业 KB 静态 policy_lean 暴露：通过 `IndustryDNA.extra["policy_lean"]` 透出，可被 `to_dict()` 序列化为下游消费方使用。
- [测试] 新增 `tests/test_industry_policy_lean.py`（15 用例）：5 个行业映射 + 2 个未命中 + 多关键词优先级 + 中英文逗号分隔 + 非字符串输入防御性 + IndustryDNA.to_dict 透出 + 非法值白名单校验。
- [测试] 新增 `tests/test_sector_policy_multi_source.py`（22 用例）：4 级优先级链（regex > KB > rankings > None）+ rankings 字段别名 + 噪声 board 过滤 + hint 限 3 词 + 空输入防御。
- [测试] `tests/test_score_macro_contract.py::TestScoreMacroObservability`（3 用例）：warning 触发 + 60s 节流 + 数据填入时不打 warning。
- [chore] 11 只自选股模拟：9/11 命中 `sector_policy`（was 1/11），2 只新材料/智能制造无 KB 映射（待 PR-A 扩 KB）。

- [修复] 六维详情"宏观与地缘"维度数据源补齐：`src/services/daily_market_context.py` 新增 `_extract_macro_indicators` + `_MACRO_MONETARY_PATTERNS` + `_MACRO_LIQUIDITY_PATTERNS`（顺序敏感，宽松 > 中性 > 紧缩），从市场复盘文本抽取 `monetary_policy` / `liquidity_indicator`；`DailyMarketContext` 扩 3 个 Optional 字段（`monetary_policy` / `liquidity_indicator` / `sector_policy`）+ `to_safe_dict` + `format_daily_market_context_prompt_section` 同步（中英文双语）；`src/services/research_framework_integration.py` `_extract_raw_data_from_context` 注入 daily_market_context（`monetary_policy` / `liquidity_indicator`）+ 个股行业维度推断 `sector_policy`（`_infer_sector_policy` + `_SECTOR_POLICY_PATTERNS`），`setdefault` 顺序保证客观数据先于 LLM 主观值；`src/scoring/indicators/macro.py` 顺手修 `regulatory_risk` 形参从未使用问题（新增 `_score_regulatory_risk`，权重重新平衡：monetary 0.22 / liquidity 0.18 / sector 0.22 / us_china 0.28 / regulatory 0.10，权重之和=1.0）。
- [测试] 新增 `tests/test_score_macro_contract.py`（17 用例，icontract Layer 2）：覆盖 `score_macro` 落域 / `regulatory_risk` 单调性 / `_extract_first_match` 顺序优先级 / `_extract_macro_indicators` partial match / 中英文 case-insensitive / `_MACRO_*_PATTERNS` 存在性 + icontract 违规反例。
- [测试] 新增 `tests/test_macro_dimension_data_source.py`（5 用例端到端）：`_extract_raw_data_from_context` 注入 daily_market_context 字段 + `_infer_sector_policy` supportive/restrictive 推断 + 无关键词回退 + 完整 `ResearchScoringService.process` 链路断言宏观与地缘维度 indicators 不再含"数据缺失"占位 + macro_score > 60。
- [测试] `tests/test_daily_market_context.py` 新增 5 用例：`DailyMarketContext` 字段填入 + `to_safe_dict` 序列化 + `format_*_prompt_section` 中英文 macro 字段透出 + payload 抽取宽松/充裕关键词。
- [测试] `tests/scoring/test_indicators.py::TestMacro` 新增 4 用例：`regulatory_risk` low/high + 全字段填充时权重归一 + 任一字段填入不再走"数据缺失"占位。

- [修复] 供应链 `_validate_deep_dive_payload` 用 `model_dump(mode="json")` 替代默认 `model_dump()`，让 Pydantic 自动把 `datetime` / `date` 等转 ISO 字符串；修复后 `_collect_deep_dive_json` 走 `json.dumps` 不再抛 `TypeError: Object of type datetime is not JSON serializable`，未来 executor 挂 `deep_dive_obj` 时整条 `generate_report` 不再因 datetime 字段失败。
- [测试] 新增 `tests/test_supply_chain_freshness.py`（12 用例）：覆盖报告生成时间（`created_at` 落库 + md 文件 mtime 落在调用窗口）/ `deep_dive_obj.fetched_at` 落盘（含 datetime）/ v3 tool 实时数据缓存（TTL=300s / `_STOCK_INFO_PAYLOAD` 复用 quote dict / `_STOCK_INFO_INFLIGHT` 并发锁）/ 端到端时长 < 1s。
- [测试] 在 `tests/test_supply_chain_contract.py` 新增 `TestDeepDivePayloadDatetimeContract`（5 用例）：datetime → ISO 字符串契约（`model_dump(mode='json')` 把 `datetime(2026,7,31,10,0,0,tzinfo=utc)` 转 `"2026-07-31T10:00:00Z"`）+ naive datetime 同样序列化 + 无 datetime 字段行为不变 + ISO 字符串反例（`"2026-07-31T10:00:00+00:00"` 字符串输入校验失败走备份层）。
- [修复] 11 个超默认阈值（mcCabe>10）业务函数全部拆分（11→≤10）：`_run_concurrent_v3_fetches` (4 个 fetcher 抽模块级 helper) / `_format_fundamental_lines` (4 字段段落拆 4 个 `_append_*` helper) / `_format_industry_dna_for_prompt` (3 子任务拆 4 个 helper + `_INDUSTRY_DNA_TEMPLATE` 字典) / `_fill_product_revenue_margin` (加权分配 / gross_margin 填充分 2 helper) / `_handle_analyze_product_matrix` (LLM 调用 / ProductLineV3 校验分 2 helper) / `_resolve_v1_legacy_fields` (position+drivers / chokepoints / us_china_chain 分 3 helper) / `generate_report` (入参归一化 / 代码归一化 / deep_dive 合并 / 写文件 / 落库分 5 helper)；拆分过程行为不变，524 测试全过。
- [改进] 5 个供应链核心业务公式加 icontract 契约（15 处装饰器）：`cross_source` 4 公式（`normalize_a_share_code` / `board_match_level` / `constituent_overlap_ratio` / `judge_verification` 落域断言 + 5 档 status / 3 档 confidence / [0,1] overlap_ratio）+ `serenity_scorer` 3 公式（`score` ticker/company 非空 + final_score ∈ [0,100] + verdict 4 档中文；`_kb_relevance` / `_industry_prior` 落 [0,1]）+ `kb_retriever.recency_weight` (half_life 整型 + (0,1] 落域）+ `SupplyChainDeepDiveV3.compute_aggregate_confidence` 3 档返回；命中 `AGENTS.md §1.3` Layer 2 强约束。
- [修复] 9 个 lint 问题（`F401` 未使用导入 4 项 / `F841` 未使用变量 2 项 / `F541` 无占位符 f-string 3 项 + 2 项顺手清理）：`annual_report_provider` 删除 `import os`、修 f-string；`cross_source` 删除 `timedelta` 未用导入；`supply_chain_tools` 删除 `industry_dna_loader.list_slugs` / `find_dna_by_keywords` / `FinancialQualityV3` 未用导入 + `pe/pb/mv_yi` 未用变量；`data_service` 修 2 处无占位符 f-string。
- [改进] 5 个 v1/v2 兼容 Pydantic model 补 `validate_assignment=True`（`KBHitRef` / `DataCompleteness` / `SupplyChainReport` / `SerenityFactorScore` / `SerenityPenaltyScore` / `SerenityScoreResult`），跟 v3 schemas（`ChainNodeV3` / `SupplyChainGraph` / `MarketPositionV3` / `IndustryOutlookV3` / `FinancialQualityV3` / `KeyPartnerV3` / `SupplyChainDeepDiveV3`）配置对齐；7 个 v3 schema 已含 `extra="forbid"`，7 个 v1/v2 故意不加（保护旧数据 roundtrip 兼容）。
- [新功能] `SupplyChainReportService._validate_deep_dive_payload` 静态方法（PR-C+ schema 校验闭环）：识别「顶层含 ticker/company 且不含 `_raw_markdown_section`」的 dict → 走 `SupplyChainDeepDiveV3.model_validate` 触发完整 `@model_validator`（一致性 / TAM 不崩 / 占比加和容忍）→ `model_dump(mode="json")` 后合并到 `deep_dive_data["deep_dive_obj"]`；非法 payload 返回 None 走 markdown 备份层（旧报告完全兼容）。`generate_report` 主流程自动检测 `result.deep_dive_obj` 属性，挂上则走结构化层，否则仅备份层。
- [ci] `.github/workflows/type-safety.yml` 治理模块列表补 `-p src.services.supply_chain.industry_dna_loader`，对齐 `pyproject.toml` `[[tool.mypy.overrides]]` 模块声明（PR-A 引入的 `industry_dna_loader` 已声明严格类型扫描但 CI 未实际跑，本次对齐）。
- [修复] `_section_has_strong_evidence` mypy narrowing 失真（5 个 elif 分支推断为 union of 5 个 list，line 801 推断为 `List[ProductLineV3]` 而非 `List[FinancialQualityV3]`）：显式 `items: Any` 标注 + 注释说明 mpy 类型推断在跨 schema list 上无法正确收窄（行为不变，运行 5 个契约测试覆盖 `compute_aggregate_confidence` 全部行为）。
- [修复] 定时批量分析 Agent 路径下六维数据丢失（pipeline.py Agent path `initial_context` key 名与评分引擎 `_extract_raw_data_from_context` 不匹配：`realtime_quote`→`realtime`、`trend_result`→`trend_analysis`，缺 `today`/`yesterday`。修正：注入正确命名的 key 后传给 `_integrate_research_framework`，同时在提取函数中加 `realtime_quote`/`trend_result` 防御性 fallback）
- [修复] 六维详情「产业链定位」对 LLM 未产出 `six_dimension_inputs` 的股票显示「该维度暂无可用数据」：新增 `_fallback_supply_chain_from_knowledge_base`，当 LLM 仅文本回退（非结构化 JSON）时从 SupplyChainDataService 知识库推导 `chain_position`/`moat_type`/`moat_strength`/`us_china_risk`，覆盖 LLM 文本回退恢复的错误值
- [新功能] 供应链深度小节 v3 PR-C（报告渲染 + DB + API 集成）：① `src/agent/supply_chain_executor.py` system prompt 末尾追加 v3 触发规则段（§10-§14 + 数据完整性披露脚注 + 灰度开关 + 工程约束继承），不动原 9 节骨架；② 新增 `src/services/supply_chain/deep_dive_renderer.py`（8 个独立函数：render_product_matrix / render_market_position / render_key_customers / render_key_suppliers / render_industry_outlook / render_financial_quality / render_section_status / render_deep_dive_sections + extract_deep_dive_section_from_markdown）—— 单节为空跳过整节，单节渲染异常 fail-open，绝不阻断整篇报告；③ `src/storage.py` `SupplyChainReport` 新增 `deep_dive_json` 字段（Text nullable），`to_dict()` 同步暴露（向后兼容历史报告默认 NULL）；新增 `_ensure_supply_chain_deep_dive_column()` 走 best-effort `ALTER TABLE ADD COLUMN deep_dive_json TEXT`（已有 DB 自动迁移，新装走 `Base.metadata.create_all`），`save_supply_chain_report` 增加 `deep_dive_json: Optional[str]` 形参；④ `src/services/supply_chain_report_service.py` `SupplyChainReportService._is_deep_dive_enabled()` 读取 `SERENITY_DEEP_DIVE_V3_ENABLED` 环境变量（默认 false / 1-true-yes-on 启用）+ `_extract_deep_dive_section()` 从 LLM 输出提取 §10-§14 段 + `generate_report` 落库时把 deep_dive_json 透传（灰度关闭时不传，零侵入）；⑤ `api/v1/endpoints/supply_chain.py` `SUPPLY_CHAIN_TOOL_DISPLAY_NAMES` 追加 5 个 v3 工具中文显示名（产品矩阵 / 市场地位 / 客户供应商 / 行业前景 / 财务质量）；`GET /api/v1/supply-chain/reports/{id}` 返回体 `data` 已自动含 `deep_dive_json`（Dict[str, Any] 直接暴露，无需 schema 改动）。新增 `tests/test_supply_chain_deep_dive_renderer.py` 36 用例（6 个单节渲染 + 顶层入口 + extract + 6 个灰度开关 + 2 个 storage roundtrip + 1 个 E2E），`flake8 --select=E9,F63,F7,F82,F821` 0 错误，PR-A 50 + PR-B 37 + PR-C 36 + 旧 supply_chain 155 共 278 用例全过；零现有 9 节骨架改动，零现有工具 / schema / 渲染函数改动。
- [改进] 供应链深度小节章节编号收敛与 §5 白话摘要兜底：① `src/services/supply_chain/deep_dive_renderer.py` 把 §12-§16 全部改为 §6-§10，与 `src/agent/supply_chain_executor.py` system prompt 4 大部分骨架（投资结论 §1-§3 / 基本面分析 §4-§10 / 交易分析 §11-§14 / 附录 §15）一致，避免 LLM 主报告与 renderer 二次渲染出现两套编号并存的契约漂移；`extract_deep_dive_section_from_markdown` 起点从 `## 12.` 改为 `## 6.`；`render_section_status` 脚注标题与 `## 5.1/5.2/5.3/5.4` 子节编号同步；② 新增 `render_market_position_summary(deep_dive, llm_markdown)` —— 基于 `MarketPositionV3` / `ProductLineV3` 结构化数据派生 §5「市场地位与竞品」白话摘要（5.1 行业定位 / 5.2 核心竞争优势与 5.3 与主要竞争对手对比合并表 / 5.4 数据来源），由 `render_deep_dive_sections` 在 LLM 未写 §5 时自动顶位；LLM 已写 `## 5.` 时跳过以避免「白话+量化」重复描述；③ `src/agent/supply_chain_executor.py` system prompt §5.3 与 §7 去重规则段追加：LLM 已写 §5.3 时 §7 `top_competitors` 列不重复列竞品优劣势；LLM 没写 §5 时 §5.2/§5.3 由 §7 数据反推紧凑表，避免割裂；④ schema 注释 `§12-§16` → `§6-§10`（`src/schemas/supply_chain.py`）+ supply_chain_tools 工具 prompt 注释同步（`# §10-§14` → `# §6-§10`）；⑤ `tests/test_supply_chain_deep_dive_renderer.py` 新增 5 个 §5 兜底用例（无数据 / LLM 已写跳过 / 只有 market_position / 只有 product_matrix / 龙头 vs 领先识别）+ 2 个 `TestRenderDeepDiveSections` LLM 已写 §5 跳过兜底与全空不派生 §5 断言；既有 §6-§16 编号断言全部迁移至 §6-§10；`tests/test_supply_chain_deep_dive_v3.py` + `tests/test_supply_chain_v3_tools.py` 章节注释 §10-§14 → §6-§10 同步；renderer 42 + v3 schema 50 + v3 tools 37 + services 17 共 146 用例全过；零现有 schema / 工具 / 业务逻辑改动，仅 renderer 编号常量 + 新增 1 个兜底渲染函数。
- [新功能] 供应链深度小节 v3 PR-B（5 个 LLM 工具层）：`src/agent/tools/supply_chain_tools.py` 追加 5 个新工具 `analyze_product_matrix`（§10 产品矩阵）/ `analyze_market_position`（§11 市场地位）/ `extract_key_partners`（§12 客户供应商）/ `analyze_industry_outlook`（§13 行业前景）/ `analyze_financial_quality`（§14 财务质量），全部 `ToolDefinition` 形式 + `category="analysis"` + 统一三段式契约（输入 ticker/company/market/industry_hint/top_k → KB 检索 → LLM 综合 → Pydantic 校验 → 返回结构化 dict）；共享 3 个辅助函数 `_get_v3_kb_retriever` / `_format_v3_kb_hits` / `_get_v3_chat_llm`（LLM adapter 复用 `LLMToolAdapter.call_text`）+ `_parse_v3_json`（markdown 围栏 + 嵌套 JSON 容错解析）。工具 prompt 强制「找不到字段返回 null 禁止估算」「年报『客户A/前五大之一』`is_anonymous=true` name 保留占位」「分业务占比加和须在 95-105%」「衰退行业 TAM 可豁免 50% 阈值」等 7 项契约。LLM 输出任何一条不通过 Pydantic 校验 → 跳过该条 + 保留其它 + 不抛异常（fail-open）。`ALL_SUPPLY_CHAIN_TOOLS` 从 5 → 10 个工具；`build_supply_chain_executor` 自动通过 `ALL_SUPPLY_CHAIN_TOOLS` 引用复用（零额外注册代码）。`tests/test_supply_chain_services.py` 工具数断言同步更新（5→10）；新增 `tests/test_supply_chain_v3_tools.py` 37 用例（注册 + 5 套 prompt 模板 + 5 个 handler fail-open/正常路径/契约违反跳过 + JSON 解析 + KB 命中格式化 + factory 源码引用校验），`flake8 --select=E9,F63,F7,F82,F821` 0 错误，PR-A 50 + PR-B 37 + 旧 supply_chain 155 共 242 用例全过。零现有工具改动（5 个旧工具 handler/prompt 0 改），仅追加；PR-C（executor system prompt 追加 + report_service 渲染 + DB 列 + API 字段）后续 PR 推进。
- [新功能] 供应链深度小节 v3 PR-A（基础设施层）：`src/schemas/supply_chain.py` 追加 6 个 Pydantic v2 模型（`ProductLineV3` §10 / `MarketPositionV3` §11 / `KeyPartnerV3` §12 / `IndustryOutlookV3` §13 / `FinancialQualityV3` §14 / 顶层 `SupplyChainDeepDiveV3`），全部走 `ConfigDict(strict=True, frozen=True, validate_assignment=True, extra="forbid")` + `@model_validator` 守业务不变式（TAM 衰退豁免 / 营收占比加和容忍 5% / rank-share 一致性）；新增 `src/services/supply_chain/industry_dna_loader.py` 静态兜底数据加载器（lru_cache 缓存 + YAML 安全解析 + PyYAML/JSON 降级 + fail-open 单文件异常隔离），新增 4 个核心行业 DNA（半导体/白酒/新能源电池/医药），`src/services/supply_chain/paths.py` 追加 `industry_dna_dir` / `industry_dna_path` 路径辅助（`SUPPLY_CHAIN_DNA_DIR` 环境变量覆盖）；`.env.example` 新增灰度开关 `SERENITY_DEEP_DIVE_V3_ENABLED=false`（PR-B/PR-C 完成后逐步开启）。零现有代码改动（6 个新模型全部追加到 schema 文件末尾，不动 v1/v2 任何模型）；`pyproject.toml` 把 `industry_dna_loader` 加入 pyright 严格类型扫描列表；新增 `tests/test_supply_chain_deep_dive_v3.py` 50 用例（schema 边界 / 契约校验 / DNA loader 全路径 / 损坏 YAML 容错），`flake8 --select=E9,F63,F7,F82,F821` 0 错误，旧 supply_chain 测试套件 155 用例全过（共 205 passed）。PR-B（5 个 LLM 工具 + handler + prompt）/ PR-C（executor system prompt 追加 + report_service 渲染 + DB 列 + API 字段）后续 PR 推进。
- [新功能] 供应链分析报告生成链路深度优化（v2）：① 新增 `src/services/supply_chain/kb_retriever.py` `SupplyChainKBRetriever` —— 包装共享 `KnowledgeBaseService.search`，多路召回（stock_code/stock_name/industry_hint/默认关键词）+ 多维加权（tag_weight × stock_match × recency_decay，half-life=180 天）+ cold start 4 段策略（cold_start / sparse / partial / rich），KB 命中作为一等公民流入报告生成；② 新增 `two_pass_extractor.py` `TwoPassSupplyChainExtractor` —— 解决 v1 一次抽取丢失"前五大供应商"等关系强度信息的痛点，第一轮识别实体、第二轮对每个候选实体反向检索 KB 全文 + 调公开数据补字段；③ 新增 `field_enrichment.py` `SupplyChainFieldEnricher` —— 接入 Tushare `top10_holders` / `main_business` 补 `concentration_pct` 和 `geographic_distribution`（失败降级，绝不编造），KB 二次检索补 `substitutability`；④ 新增 `graph_builder.py` `SupplyChainGraphBuilder` —— 合并 KB/LLM/公开数据产出 `SupplyChainGraph` 结构化图谱，自动算数据完整度披露（DataCompleteness）和 KB 覆盖率；⑤ 新增 `serenity_scorer.py` `SerenityScorer` —— 统一两条评分路径（修复 v1 单股路径与主题路径不一致的定时炸弹），按 `KB_DRIVEN_FACTORS` / `INDUSTRY_PRIOR_FACTORS` 分类加权（KB 加成上限 0.2 防止 KB 丰富标的上评分虚高），`SERENITY_SCORER_V2=false` 环境变量回退旧启发式。⑥ `src/services/supply_chain_data_service.py` 新增 `fetch_all_v2()` 主入口返回 `SupplyChainV2`（同时容纳 v1 字段向后兼容），`fetch_all_v2_legacy_compat()` 同时返回 v1+v2 dict 便于平滑迁移；⑦ `src/agent/tools/supply_chain_tools.py` 新增 `search_supply_chain_kb` 工具（category=knowledge），`SupplyChainExecutor` system prompt 强制要求第一步必调 KB 检索 + 报告新增「知识库参考」小节 + 「数据完整性披露」小节；⑧ `src/schemas/supply_chain.py` 新增 `ChainNodeV3`（每字段来源标注 + 字段来源一致性契约）/ `SupplyChainGraph` / `KBHitRef` / `DataCompleteness` / `SupplyChainV2` / `SerenityScoreResult` 等 v2 schema，全部走 Pydantic v2 `ConfigDict(strict=True, frozen=True, validate_assignment=True)`。完整 41 个新增测试全过（`tests/test_supply_chain_v2/`），旧 supply_chain 测试套件 267 个全过（共 308 passed），`py_compile` / `flake8` 0 错误。
- [改进] 报告页（深度投研 / 政策与公告双维度排雷 / 供应链分析 / 知识库）页面级布局改为「整页可滚动 + 报告区自然撑开」：根容器从 `h-[calc(100vh-...)] overflow-hidden` 改为 `min-h-[calc(100vh-...)]`，报告容器去掉 `flex-1 overflow-y-auto` 改为自然高度，桌面侧栏改为 `sticky top-X self-start max-h-[calc(100vh-Xrem)]` 自己滚自己。解决浏览器放大（zoom 200%+）后报告区域被 `overflow-hidden` 截断、用户只能看到一小段内容的问题；聊天类页面（缠论 / 郑希 / SupplyChain Chat / ChatPage）保持原有锁高度 + 消息流内部滚动模式。
- [修复] 六维详情「产业链定位」对 600176 / 601208 / 688002 等被标记「该维度暂无可用数据」：`src/analyzer.py:4213-4217` 之前用 `cleaned_text.find("{")` + `rfind("}")` 取 JSON 范围，遇到 LLM 在 prose 中夹带 `{` `}`（如 prompt 文本 "Start with { and end with }"）或在 JSON 后追加不完整第二段时会取错区间，导致 `result.six_dimension_inputs` 解析失败、`score_supply_chain` 7 个主观键全空、回退到 `数据缺失，使用中性分` 占位指标。新增 `GeminiAnalyzer._extract_json_candidate` 与模块级 helper `_candidate_json_open_positions` + `_scan_json_object_end`：① 优先解析 `\`\`\`json ... \`\`\`` 围栏块（手工 bracket-match 跨越嵌套对象）；② 否则从 `,` `:` `[` `{` `换行` 后出现的 `{` 起步，逐个候选做 bracket-match + JSON 解析；③ 优先选最大且带 `dashboard` / `six_dimension_inputs` / `code + operation_advice` 根键的对象，避免被 `intelligence.latest_news` 这种嵌套子对象抢匹配；④ fallback 找不到合法 JSON 时，扫描 LLM 思维链中的 "Six Dimension Inputs" markdown 子弹列表（`- chain_position: midstream (电子材料产业链中游)` 之类）通过 `_recover_six_dimension_inputs_from_prose` 重构出 `six_dimension_inputs` 子对象并合成最小 JSON 信封（标 `_recovered_from_prose: true`），让被 token 截断的 601208 / 688002 也能恢复 7 个键中的若干。新增 `tests/test_analyzer_json_extract.py` 15 用例：覆盖纯 JSON / prose 含 stray brace / markdown 围栏 / 嵌套对象 / 字符串含 `{}` / 转义引号 / 第二段不完整 JSON / 真实 600176 截断响应 / 真实 688002 围栏响应 / 截断 prose 恢复 / 思维链 prose 恢复 / 最小键数守卫。e2e 验证 8 只自选股全部 OK（修复前 600176 / 601208 / 688002 三只 NO_ROOT_KEYS，现全部 OK，其中 601208 / 688002 走 prose 恢复）。
- [修复] Web UI 治理与可访问性收敛：① `DeepResearchPage` 删除按钮（`<span role="button">`）和历史刷新按钮移除原生 `title=` 属性，改用 `aria-label` + 图标 `aria-hidden="true"`，符合 `tests/ui_governance.test.ts` 治理规则（禁止 `<button|a|input|textarea|select|div|span>` 出现 native title）。② `PolicyMinesweeperPage` 状态徽章 `<span>` 移除 `title={ok ? '成功' : '失败/降级' : '未知'}` 原生属性，改为 `aria-label="${label}：成功 | 失败或降级 | 状态未知"`。③ `ReportOverview` 市场阶段 Badge 和日线未完成 Badge 加 `role="img" aria-label=`，满足 `getByLabelText` 测试；关联板块容器由 `<div>` 升级为 `<section role="region" aria-label={text.relatedBoards}>`，内部 `<div>` 加 `home-related-board-list flex flex-nowrap gap-2 overflow-x-auto` 类，让 `getByRole('region', { name: '关联板块' })` 和 `.home-related-board-list` 选择器都能命中。④ `apps/dsa-web/src/index.css` 新增 `.home-related-board-list` 滚动条样式（`scrollbar-width` + WebKit `::-webkit-scrollbar` 配套），让 flex-nowrap + overflow-x-auto 在窄屏滚动时视觉一致。⑤ `apps/dsa-web/src/setupTests.ts` 增加全局 `afterEach` 自动清理 `localStorage`，降低跨测试并发污染导致 `ChatPage` / `StockScreeningPage` 等偶发失败；同步在 `ChatPage.test.tsx` 顶部 `afterEach` 中调用 `vi.restoreAllMocks()`。⑥ `DeepResearchPage` 删除按钮 aria-label 使用 `item.stock_name || item.stock_code || item.id`（与 `DeepResearchReportItem` 类型字段对齐）。
- [改进] 设置功能中英混搭收敛（v2）：① 新建 `apps/dsa-web/src/locales/settingsText.ts` 与 helper（`getSettingsProtocolLabel` / `getSettingsCapabilityLabel|Hint` / `getSettingsChannelStatusLabel` / `getSettingsStageLabel` / `getNotificationErrorCodeLabel` / `getNotificationChannelDisplayName` / `formatSettingsText`），覆盖 LLM 渠道、通知测试、设置占位等高频用户场景；② `LLMChannelEditor` 协议下拉改为「OpenAI 兼容协议 / DeepSeek / Gemini / Anthropic / Vertex AI / Ollama」；渠道卡 `protocol` 徽章通过 `getSettingsProtocolLabel` 渲染（不再裸露 `openai` / `vertex_ai` / `ollama` 等原始 enum）；能力选择和结果徽章（`JSON` / `Tools` / `Stream` / `Vision`）本地化为「JSON 输出 / 工具调用 / 流式输出 / 视觉能力」；状态徽章 `连接正常 / 连接失败 / 测试中 / 未填写 API Key`；阶段标签 `model_discovery` 「模型发现」→「模型列表获取」、`chat_completion` 「聊天调用」→「模型调用」；保存按钮「保存中...」→「保存中…」「保存 AI 配置 / 保存渠道配置」；模型计数「`{n} 个模型已配置` / `未配置模型`」按 `useUiLanguage` 切换；能力检测摘要「通过 {n} 项，失败 {n} 项，跳过 {n} 项」；发现提示「支持 `/models` 的 OpenAI Compatible 渠道可自动拉取模型」→「支持 /models 接口的 OpenAI 兼容渠道可自动拉取模型列表」；YAML 路由提示由「运行时主模型 / 备选模型 / Vision / Temperature ……」「运行时主模型、备用模型、视觉模型和采样温度 ……」；`buildLlmFailureText` 拼接「（原始摘要：…）」→「（{语言}rawMessagePrefix：…）」；③ `NotificationTestPanel` 渠道下拉复用 `getNotificationChannelDisplayName`（企业微信 / WeCom、飞书 Webhook / Feishu Webhook、邮件 / Email、Server酱 3 / ServerChan 3、自定义 Webhook / Custom Webhook）；尝试列表 `Attempt {n}`→「第 {n} 次尝试」；`HTTP {code}`→「HTTP 状态码 {code}」；`{n} ms`→「耗时 {n} 毫秒」；`errorCode` 原始值映射为「配置不完整 / 网络异常 / 请求超时 / HTTP 错误 / 鉴权失败」（含 `http_500/502/503/504`）；`target` 缺失时回落到「通知渠道：{label}」而非显示原始 `serverchan3` / `wechat`；④ `SettingsField` `normalizeSelectOptions` 在「label === option value」时渲染为「未知选项 ({raw})」替代直接展示原始 enum；⑤ `SettingsHelpButton` 头部新增「配置键 / Configuration key」副标题 + 等宽字体 `fieldKey`，避免与正标题混淆；⑥ `systemConfigI18n.ts` 修订：分类描述 `与多 Agent 编排` → `和多 Agent 编排`；`TELEGRAM_MESSAGE_THREAD_ID` 「Telegram 话题 Thread ID」→「Telegram 话题 ID」；`PUSHPLUS_TOPIC` 「PushPlus 分组 Topic」→「PushPlus 分组主题」；`PUSHOVER_USER_KEY` 「Pushover User Key」→「Pushover 用户 Key」；`CUSTOM_WEBHOOK_BODY_TEMPLATE` 「Body 模板」→「请求体模板」；`ADMIN_AUTH_ENABLED` 「鉴权」→「认证」；`AGENT_DEEP_RESEARCH_BUDGET` 加「深度研究」中文主名；`AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS` 「tokens」→「Token 数」；`AGENT_CONTEXT_PROTECTED_TURNS` 「轮次」→「轮数」；`REPORT_LANGUAGE` 描述补「zh 表示中文，en 表示英文」；`MARKET_REVIEW_REGION` 描述补「例如 A 股 cn / 港股 hk / 美股 us」；`MARKET_REVIEW_COLOR_SCHEME` 描述 raw enum 用 `` `green_up` `` / `` `red_up` `` 反引号包裹。⑦ 同步更新 `SettingsField.test.tsx` / `LLMChannelEditor.test.tsx` / `NotificationTestPanel.test.tsx`；新增 `apps/dsa-web/src/locales/__tests__/settingsText.test.ts`（7 用例覆盖协议 / 能力 / 阶段 / 状态 / 错误码 / 渠道 / 模板）。
- [改进] 中英混搭 UI 文案收敛（v1）：① 新建 `apps/dsa-web/src/locales/knowledgeText.ts`，`KnowledgeSearchResults` / `KnowledgeDocumentList` 接入 `useUiLanguage()` 并将 `source_type`（text/markdown/pdf/url）、`validation_status`（VERIFIED/CONFLICT/USER_ONLY/PENDING）、`chunks`、删除按钮 aria 等原始枚举/英文单位映射为中英本地化文案；② 新建 `getRunFlowEventTypeLabel`，`RunFlowEventList` 事件 `type` 不再直接渲染后端内部事件名（`task_created`、`provider_fallback` 等），未知类型回落到「其他事件 / Other event」；③ `uiText.ts` 关键文案修订：`usage.breakdown` 「Breakdown」→「用量明细」；`usage.promptTokens`/`usage.completionTokens`/`usage.totalTokens` 统一为「输入 Token / 输出 Token / 总 Token 数」；`usage.callTypeDetail` 同步；`usage.eyebrow` 「Usage」→「用量」；`usage.recentCallsDescription` 中 `token` 大小写统一；`decisionSignals.activeOnly` / `archiveConfirm` / `invalidateConfirm` / `latestDescription` / `noLatestDescription` 中「active」改为「有效」；`runFlow.summary.task`/`trace` 「Task/Trace」→「任务 ID / 链路 ID」；`runFlow.events.filter.problems`「失败/告警」→「失败或告警」；`runFlow.events.filter.fallback`「降级回退/重试」→「降级或重试」；`runFlow.summary.fallbackCount` 同步；`runFlow.status.fallback`「降级回退」→「已回退」；`runFlow.edge.fallback` / `nodeDetails.count.fallback`「降级回退」→「降级或回退」；`runFlow.graph.startedAt`「开始」→「开始时间」；`settings.authSetPasswordPlaceholder` 中文括号 `()` → `（）`；`settings.fieldAddKey`「添加 Key」→「添加密钥项」；`layout.appFallbackDescription` 中文「Web workspace」→「Web 工作台」；④ `featureText.ts` 告警 `scoreDropAtLeast`「Score 下降 >= {value}」→「评分下降不少于 {value}」；`ALERT_FORM_TEXT.scoreDropThreshold` 同步；`ALERT_MARKET_REGION_OPTIONS` 中文选项去除 `(cn)/(hk)/(us)` 内嵌代码（与 A 股 / 港股 / 美股等用户视角一致），同步 `components/alerts/AlertRuleForm.tsx` 与 `pages/PortfolioPage.tsx`；⑤ 桌面端 `apps/dsa-desktop/renderer/loading.html` 启动页全英文文案 → 中文（`<html lang="zh-CN">`，标题/状态/提示/错误全部本地化，保留 CJK 字体栈），错误块从「Error: raw」改为「本地服务启动失败，请查看桌面端日志后重试：raw」；⑥ 同步更新 `KnowledgeSearchResults.test.tsx` / `KnowledgeDocumentList.test.tsx` / `RunFlowEventList.test.tsx` / `RunFlowPanel.test.tsx` / `RunFlowGraph.test.tsx` / `AlertRuleList.test.tsx` 断言。新增 `apps/dsa-web/src/locales/knowledgeText.ts` 与 `getRunFlowEventTypeLabel` 工具函数。
- [修复] type-safety CI 阻断：pyright 在 `src/scheduler.py:225` 报 `Object of type "None" cannot be called`（`_task_callback: Optional[Callable]` 在 `_wrapped()` 闭包内调用），闭包无法跨函数追踪 `set_daily_task` 已通过的 None 守卫。改为在调用闭包前先把 `self._task_callback` 抓取到本地变量 `task_callback` 并显式 None 守卫，再让闭包只引用本地变量；同时 20 个 `__all__` 含 `__getattr__` lazy import 的 `reportUnsupportedDunderAll` warning（在 `src.agent` / `src.services` / `src.agent.skills` 等通过模块级 `__getattr__` 延迟加载重依赖的包中产生，pyright 不跟踪 `__getattr__`）在 `pyproject.toml` 关闭该规则以保留 lazy import 契约。
- [修复] 基本面 snapshot 陈旧数据被错标 `ok`：根因 `data_provider/base.py` 的 `_infer_block_status` 只看 payload 是否非空，AkShare 三个失败接口（`stock_yjyg_em` / `stock_yjkb_em` / `stock_gdfx_top_10_em`）在异常路径上回退到的旧文本（如 `earnings.forecast_summary="预计2020年1-3月..."`、`quick_report_summary="2023-04-14"`）仍被标 `ok`，下游五段式投研（`research_integration_service`）直接消费 payload 生成供应链/价值/情景章节，导致报告"停在 2023/2024 年"。新增 `DataFetcherManager._detect_payload_staleness`（扫描字符串中的 4 位年份，最新年份 < `current_year - 1` 视为陈旧）+ `_downgrade_for_staleness`（仅作用于 `ok`→`partial`），在 `growth` / `earnings` / `valuation` / `institution` 四处 `_infer_block_status` 之后插入降级；下游 `block_statuses` 聚合 `result_ctx.status` 自动落 `partial`（多级降级：陈旧 → partial → 失败链路可继续降为 failed）。正则原用 `\b` 单词边界，**中文文本里 `2020年` 后续是汉字而非 word boundary 会漏匹配**（验证中先误报 22/48 命中），改为 `(?<![0-9])(20[12]\d)(?![0-9])` 数字邻接界定后命中 48/268，且不误判 `12020` / `20205`。零依赖新增、零 schema 变更、不动 `fundamental_snapshot` 表结构、不影响 `_should_cache_fundamental_context`（陈旧块仍不缓存）。新增 `tests/test_fundamental_staleness.py`（10 用例覆盖：空 payload / 阈值年 / 陈旧年 / 嵌套 dict 扫描 / 无年份 / `_downgrade_for_staleness` 仅降 `ok` / 中文字符后年份 / 数字邻居非年份）；现有 `test_fundamental_context.py` / `test_fundamental_adapter.py` / `test_yfinance_fundamental_adapter.py` 81 用例全过；`py_compile data_provider/base.py` 通过；`flake8 --select=E9,F63,F7,F82` 0 错误。真实 DB 复现：268 条 snapshot 中 48 条 `earnings` 块从 `ok` 自动降 `partial`（覆盖 8 只代码：300260/300623/300054/300003/002957/002617/688002/688486）；e2e 模拟用真实陈旧 bundle 走完整 `get_fundamental_context` 路径：整体 `result_ctx.status` 从 `ok` 落 `partial`，各 block 经多级降级到 `failed`，**真实新鲜数据**（如 600519 snapshot 270 `institution.institution_holding_change=0.0`）不被误杀保持 `ok`。iFinD 3 个测试失败为历史测试顺序污染（iFinD fetcher 单例缓存 `available=True` 跨测试泄漏），与本改动无关。
- [修复] AkShare 三个失败接口下 Tushare/iFinD 兜底缺失：原 `get_fundamental_context` A 股路径只调一次 `AkshareFundamentalAdapter.get_fundamental_bundle`，AkShare 三个失败接口（`stock_yjyg_em` / `stock_yjkb_em` / `stock_gdfx_top_10_em`）在当前 Python 环境抛 `TypeError` / `KeyError` / `FileNotFoundError` 时**直接吞掉**——`growth.data` 4 个 anchor 全 `None`、`earnings` 空、`institution` 空，五个核心字段（`revenue_yoy` / `net_profit_yoy` / `roe` / `gross_margin` / `top10_holder_change`）从未到达 `fundamental_snapshot` 表，下游 `_assemble_five_section_report` 全部用 null/旧文本。即便 #1 修复把陈旧数据降级为 partial，**根因**（无真实数据流入）仍未解决。新增 `data_provider/tushare_ifind_fundamental_adapter.py`（`TushareIfindFundamentalAdapter`），与 `AkshareFundamentalAdapter.get_fundamental_bundle` 同形态；优先 iFinD MCP（13 个 anchor 真实可调），Tushare 在 basic-plan token 缺财务接口时 fail-open 静默跳过；iFinD 不支持文本类字段（`forecast_summary` / `quick_report_summary`）时**不构造虚假文本**，避免再产生 #1 描述的 2020 陈旧数据。`growth` 4 个 anchor 用 `asyncio.gather` 并发（`asyncio.run` 在 worker thread 内启动独立事件循环）以应对 iFinD MCP 高延迟；测试用 fake 验证 `max_in_flight=4` 真的并发。`_normalize_ts_code` 把 6 位 A 股归一为 ts_code（600xxx→SH/000xxx→SZ/300xxx→SZ/688xxx→SH/920xxx→BJ）。`data_provider/base.py` 新增 `_is_growth_block_thin` / `_is_earnings_block_thin` / `_is_institution_block_thin` 三个 thin 检测；A 股路径在 AkShare bundle 后插入 fallback 触发：仅当任一块 thin 且 adapter.available=True 时调用，**只填 None 字段**不覆盖 AkShare 已返回的非空值。`fallback_budget` 用 `max(min(8.0, fetch_timeout), remaining_seconds - 4.0)` 保证 capital_flow / dragon_tiger / boards 后续阶段还有 budget（修复 `test_non_etf_board_budget_not_forced_to_zero` 回归）。source_chain 通过 `bundle_chain.extend(fallback_chain)` 把 iFinD 溯源（4 个 anchor）注入到 `growth` 块的 source_chain，blocks aggregation 阶段把同一 list 复制给 3 个块导致重复 3 次——这是历史行为，非本次引入，未触动。新增 `tests/test_fundamental_fallback.py`（15 用例：薄块检测 6 + adapter 行为 6 + ts_code 归一 3 + concurrent 路径 1 `max_in_flight=4`）；`test_fundamental_staleness.py` 10 + `test_fundamental_context.py` 21 + `test_fundamental_adapter.py` 19 + `test_yfinance_fundamental_adapter.py` 18 共 83 个相关用例全过；`py_compile` / `flake8 --select=E9,F63,F7,F82` 0 错误。E2E（用工作的 iFinD fake 通过 service 路径）：`get_fundamental_context("600519")` 跑通，`growth` 块从 `failed` 升为 **`ok`**，4 个 anchor 注入 `revenue_yoy=8.5 / net_profit_yoy=-4.5 / roe=33.5 / gross_margin=91.0`，source_chain 写入 12 条 iFinD 溯源。**未验证项**：真实 iFinD MCP 在当前服务端对 `get_stock_financials` 返回 `Received session ID → Negotiated protocol → GET stream disconnected, reconnecting in 1000ms` 无限循环（已通过日志观察到 13 次 session id），是上游 iFinD MCP 服务端问题而非本代码 bug——`IfindFetcher._async_fetch` 真实网络路径下被 8-30s budget 截断时 `AnchorReading` 返回 None。修复路径建议：把 `IfindFetcher` 改为常驻事件循环 + 复用 MCP session（已在文件注释中标记 Phase 0），下次单独 PR。
- [新功能] `fundamental_snapshot` 表新增 `as_of_date` 列（`YYYY-MM-DD`），把 AkShare / iFinD / Tushare 三层数据源真正"锚定到哪一天"写进 schema，让 staleness 检测器、报告模板和未来回测都能直接读这个字段而不用再扫文本。`src/storage.py` 在 `FundamentalSnapshot` model 加 `as_of_date = Column(String(10), nullable=True, index=True)` + `__table_args__` 新增 `ix_fundamental_snapshot_as_of` 索引（与 `created_at` 索引并列）；`save_fundamental_snapshot` 增加 `as_of_date: Optional[str] = None` 形参，调用方 `src/core/pipeline.py:482` 显式 `as_of_date=fundamental_context.get("as_of")` 透传。新增 `scripts/migrate_fundamental_snapshot_as_of_20260708.py`（幂等迁移）：先 `PRAGMA table_info` 探测列再 `ALTER TABLE ADD COLUMN`，避免重复迁移报错；索引同样 `IF NOT EXISTS`；回填两步：① 从 `payload` 内 `earnings` / `growth` / `institution` / `valuation` 块扫描最大 4 位年份（用 `(?<![0-9])(20[12]\d)(?![0-9])` 避免误匹配 `12020` / `20205`），② 当 payload 完全没有年份时按 `created_at` 上一年 12-31 回填（A 股年报披露窗口 1-4 月，保守锚点用 prior year）。运行结果：279 行 100% backfill，分布 `2020-12-31 × 26`（含 2020 文本的旧 AkShare forecast）+ `2023-12-31 × 22`（含 2023 文本的旧 quick_report）+ `2025-12-31 × 231`（基于 created_at 推算），再跑一次 `[SKIP] no NULL as_of_date rows to backfill` 确认幂等。`data_provider/base.py` 新增 `_derive_as_of_date(result_ctx)`：① 优先 `result_ctx["as_of"]`（iFinD 兜底写为 `YYYY1231` 紧凑格式，归一为 `YYYY-MM-DD`），② fallback 扫 earnings→growth→institution→valuation 取最大年份→`YYYY-12-31`，③ 都没有返回 `None`。两处 `get_fundamental_context` 路径（离岸 + A 股）都在 `result_ctx["status"]` 聚合后立刻写入 `result_ctx["as_of"] = self._derive_as_of_date(result_ctx)`。iFinD/Tushare 兜底块在合并完 anchor 后用 `result_ctx.setdefault("as_of", fb_as_of)` 把 iFinD 报告的 `as_of` 透传——这是真实路径中 as_of 真正落库的关键。`_detect_payload_staleness` 增加 `isinstance(payload, dict) and "as_of" in payload` 早返回：拿到 result ctx 时**优先信任 as_of_date 而不是文本扫描**，确保"新 2025 数据里残留一段 2020 历史注释"不会被误判陈旧；block-level fallback 路径仍走文本扫描。`_parse_as_of_year(as_of)` 静态方法：`YYYY-MM-DD` 和 `YYYYMMDD` 都接受。新增 `tests/test_fundamental_as_of.py`（13 用例：`_derive_as_of_date` 7 含 `YYYY1231` / `YYYY-MM-DD` 归一 / 块内 fallback / max across blocks / None cases；`_detect_payload_staleness` 4 含 "fresh as_of 覆盖 stale text" / "stale as_of 强制降级" / 边界 / 文本扫描 fallback；`_parse_as_of_year` 3）。全 fundamental suite 79 用例全过（含已有 66 + 新增 13）。E2E（真实 service 路径）：`POST /api/v1/analysis/analyze {"stock_code":"600519","force_refresh":true}` 跑通后 snapshot 281 写入 `as_of_date=2025-12-31`，`payload` 顶层 `as_of=2025-12-31`，`growth` 块 status 从 `#1/#2 修复`后的 `failed/partial` 进一步升 **`ok`**，4 个 anchor 中 `net_profit_yoy=-4.5323` 和 `gross_margin=91.2934` 是 iFinD 兜底拿到的真实 2025-12-31 期间数据（`revenue_yoy` / `roe` 在当前 iFinD 服务端仍 reconnect 循环中未拿到，与 `#2 修复` 文末已记录的"上游 iFinD MCP 服务端问题"一致）。`flake8 --select=E9,F63,F7,F82` 0 错误；`py_compile` 通过。**未验证项**：旧的 `save_fundamental_snapshot` 调用方若不传 `as_of_date` 也能兼容（默认 None，列 NULL-able）；`get_latest_fundamental_snapshot` 等读路径未变（write-only 仍写优先）；报告模板未在本 PR 改动——`as_of` 在 payload 顶层已可用，下游模板可选择性展示。
- [改进] iFinD MCP 客户端升级为常驻 daemon 循环 + 共享 session：`IfindFetcher.__init__` 默认 timeout 30s（之前 8s）+ 新增 `_ensure_loop` 在首次 `fetch` 时启动 daemon 线程 + `_submit` 通过 `asyncio.run_coroutine_threadsafe` 把协程投到该 loop（而不是每次 `asyncio.run` 启停 loop + 重建 streamablehttp 连接）；`_async_fetch` 改为通过 `_ensure_session` 共享 `ClientSession`，跨 anchor 复用同一 session；`_close_session` 在 transport error 时主动 teardown 让下次 call 重连；`fetch_main_inflow_series` 同样走 daemon loop 替代 `asyncio.run`。`TushareIfindFundamentalAdapter._gather_growth_reads` 改为 `ThreadPoolExecutor(max_workers=4)` + `as_completed` 并发读 4 个 anchor + 5 个 period 候选，每个 worker 调 `IfindSource.read` 同步（不创建新 event loop），测试用 `max_in_flight=4` 验证真并发。`DataFetcherManager.__init__` 仅在 `IFIND_MCP_TOKEN` 和 `IFIND_MCP_ENDPOINT` 都配置时才创建 IfindSource（避免无 env 时也建 daemon thread）；fallback 块 `if isinstance(fallback_bundle, dict):` 缩进修正（之前 `fb_earnings` / `fb_institution` 没缩进到 if 块内导致 `NoneType.get` AttributeError）。新增 `TestIfindFetcherDaemonLoop` 2 用例（loop 幂等 + available=False 时不启动）；`test_concurrent_path_with_async_fetcher` 改为 `test_concurrent_path_with_thread_pool`（fake 用 `read` 同步，验证 `max_in_flight=4`）。`test_etf_market_downgrades_to_partial_or_not_supported` 显式 mock `manager._tushare_ifind_adapter` 为 `available=False` 避免触发真实 iFinD 客户端。所有 fundamental suite 122 用例全过（含已有 79 + #2 fallback 17 + ifind daemon 2 + ETF 1 修复 + #3 as_of 13 + concurrency test refactor）。`flake8 --select=E9,F63,F7,F82` 0 错误；`py_compile` 通过。**未验证项**：当前 iFinD MCP 服务端 `Received session ID → Negotiated protocol → GET stream disconnected, reconnecting in 1000ms` 无限循环（13+ 次 session id），`fallback` 块触发但 `IfindFetcher._async_fetch` 内部 `_ensure_session` 阻塞在 streamable_http_client 握手，**4 个 anchor 全部返回 None**。snapshot 286/289 在新代码下 0 anchor（之前 snapshot 281 拿到 2 个 anchor 仅为服务端瞬时正常）——这是上游 iFinD MCP 服务端问题不是本客户端代码 bug。修复路径建议：把 `streamablehttp_client` 换为 long-lived SSE 流（已在 iFinD fetcher 注释中标记 Phase 1.5），单独 PR。
- [新功能] 报告模板加陈旧数据提示 + `as_of` 日期透出：原模板只渲染 `score / signal_emoji / operation_advice / trend_prediction`，用户看不到"基本面数据是哪一天的"，出现 `#1` 修复描述的"供应链分析停在 2023/2024 年"时无任何 UI 提示。`src/services/report_renderer.py` 把 `_is_stale` / `data_freshness_line` 提取到 module 顶层（可被测试 import）：`_is_stale(as_of, current_year)` 返回 `True` 当 as-of 年份 < current_year - 1；`data_freshness_line(as_of, language, current_year)` 中文返回 `📅 数据截至 YYYY-MM-DD。`（新鲜）/ `⚠ 数据截至 YYYY-MM-DD，可能已陈旧，请结合最新公告判断。`（陈旧），英文对应 `📅 Data anchored to YYYY-MM-DD.` / `⚠ Data is anchored to YYYY-MM-DD — content may be stale. Treat with caution.`。`render` 路径：每个 `enriched` 条目从 `result.fundamental_context["as_of"]` 提取 as-of 计算 `is_stale_fundamental` + 生成 `data_freshness_badge`，注入 Jinja context。`templates/report_markdown.j2` 在每个 stock heading 后插入 `{% if e.data_freshness_badge %}{{ e.data_freshness_badge }}{% endif %}`；summary 列表每行末尾追加 `{% if e.is_stale_fundamental %} · ⚠{{ e.as_of_date }}{% endif %}` 让 summary 也能一眼看出陈旧。`templates/report_wechat.j2` 同样在 `###` 标题行后插入 freshness 行。`templates/report_brief.j2` 不加（summary_only 风格一致）。新增 `tests/test_report_freshness.py`（12 用例：`_is_stale` 4 含新鲜/阈值/陈旧/无效输入；`data_freshness_line` 5 含中英文新鲜/陈旧/空；render 端到端 3 含 markdown 模板含 / 不含 as-of 各场景）。`py_compile` / `flake8` 0 错误。**E2E**：用 `AnalysisResult(fundamental_context={"as_of":"2023-12-31"})` 调 `render("markdown", [result])`，输出含 `🟡 **新莱应材(300260)**: 持有 | 评分 55 | 震荡 · ⚠2023-12-31` 摘要行 + 详细行 `⚠ 数据截至 **2023-12-31**，可能已陈旧，请结合最新公告判断。`——用户报告的"供应链/价值停在 2023 年"现象**现在 UI 明确警示**。
- [修复] 供应链分析 PDF 下载文件名被前端硬编码覆盖：根因 `apps/dsa-web/src/api/supplyChainReports.ts` 的 `downloadPdf` 仍走旧的 `a.download = `supply_chain_${reportId}.pdf` 直接覆盖，导致后端 `FileResponse` 正确发出的 `科瑞技术（002957）供应链分析报告20260630.pdf` / `AI半导体供应链供应链分析报告20260630.pdf` 在浏览器侧丢失，始终下载到 `supply_chain_sc_xxx_1.pdf`。改为复用共享 `downloadPdfFromUrl(url, 'supply_chain', reportId)`（与 `deepResearch.ts` / `policyMinesweeper.ts` 一致），由 helper 解析 `Content-Disposition: filename*=UTF-8''...` 后写入 `a.download`。测试 `apps/dsa-web/src/api/__tests__/supplyChainReports.test.ts` `downloadPdf 成功` 用例补 `content-disposition` 头 mock（业务文件名断言与 `policyMinesweeper.test.ts` 对齐），验证 helper 路径生效。供应链后端逻辑（`api/v1/endpoints/supply_chain_reports.py` 已正确分支单股型 / 主题型）零改动。
- [新功能] PDF 业务文件名（按 `docs/pdf-download-filename-plan.md`）：单股报告（深度投研 / 政策与公告排雷）用 `股票名（代码）报告类型YYYYMMDD.pdf` 命名（如 `科瑞技术（002957）深度投研报告20260630.pdf`）；供应链分析用主题型 `主题供应链分析报告YYYYMMDD.pdf`（阶段 1，按文档 §供应链报告边界）。日期取 `created_at` 而非下载当天，股票名为空 fallback 到代码；后端新增 `src/services/report_filename.py` 共享 helper，前端新增 `apps/dsa-web/src/api/download.ts` 解析 RFC 5987 `filename*=UTF-8''...`，三 API wrapper 改用共享 helper 不再硬编码 `<a download>`。
- [修复] 政策与公告双维度排雷：放宽 Pydantic `stock_code` 入口约束并加 `field_validator` 调 `normalize_code` 自动归一化（`600519.SH` / `SH600519` / `920493.BJ` → `600519` / `600519` / `920493`），与 deep_research 的 `endpoint 层 normalize_a_share 兜底` 行为一致；保留 `model_config=ConfigDict(strict=True, frozen=True, validate_assignment=True)`，畸形输入（空 / 美股 / 港股 / 乱码）仍 422。修复前端 `StockAutocomplete` 传 `canonicalCode`（含 `.SH/.SZ/.BJ` 后缀）触发的 422 报错。
- [文档] 审计并重写知识库功能方案，收敛为 SQLite FTS5 优先的私有资料库 MVP，明确知识库证据优先级、API/数据模型、安全边界、报告集成规则、测试矩阵与向量 RAG 后续阶段。
- [新功能] 知识库 MVP（Phase 0）：SQLite FTS5 全文检索私有资料库。新增 schemas/knowledge_base.py（Pydantic v2 schemas）、services/knowledge_base_parser.py（文本/Markdown/PDF 解析 + SSRF 防护）、services/knowledge_base_service.py（文档 CRUD + 全文检索）、api/v1/endpoints/knowledge.py（REST API）、agent/tools/knowledge_base_tools.py（Agent 工具 search_knowledge_base）。支持文本/Markdown 上传、PDF 解析、URL 抓取（best-effort）、文档管理（增删列表）、全文检索（支持股票代码/名称/标签过滤）。新增 .env.example 知识库配置项。知识库证据优先级低于公告/结构化数据。
- [测试] 新增知识库测试套件（78 用例）：test_knowledge_base_schema.py（schema 验证）、test_knowledge_base_parser.py（文本/Markdown 解析 + SSRF 防护）、test_knowledge_base_service.py（服务层 CRUD + 检索）、test_knowledge_base_tools.py（Agent 工具）、test_knowledge_base_api.py（API 端点）。
- [新功能] 消息源新增 x.com（海外媒体，复用 adanos per-ticker，全市场）：新增 `XSearchProvider`（`src/search_service.py`），经查证复用现有 adanos `/x/stocks/v1/stock/{ticker}`（一次调用同时返回聚合舆情 buzz/sentiment/bullish/bearish + `top_tweets`），**零新外部依赖、零新 env**（复用 `SOCIAL_SENTIMENT_API_KEY`/`SOCIAL_SENTIMENT_API_URL`，与 `SocialSentimentService` 共享同一账号）。按市场自适应解析 ticker（新增纯函数 `resolve_x_ticker`：US 代码即 ticker、HK/A 股非美格式返回 None），`top_tweets` → `SearchResult`（合成稳定 `x.com/{author}/status/{...}` URL 便于 NewsIntel 去重），聚合舆情作首条摘要行。经 SearchService 自动流入 `search_stock_news`/`search_comprehensive_intel`（`isinstance(XSearchProvider)` 分支传 `ticker`，类比 Tavily `topic`/Brave `search_lang` 特殊参数处理）。可靠性复用 `BaseSearchProvider` key 轮询 + tenacity 重试 + per-ticker TTL 缓存（单飞）+ 熔断（连续失败冷却跳过）+ fail-open（`found:false`/无 ticker/HTTP 错误/异常 → 空结果，绝不抛）。现实覆盖：美股全直连、港股靠 ADR、A 股大概率 `found:false` 静默跳过（x.com 客观现实，非设计缺陷）。仅作 LLM 文本上下文，**不改** `score_sentiment()`。新增 `tests/test_x_search.py`（39 用例 + 2 个 opt-in 真 API 集成测试，离线 mock adanos，新代码 100% 覆盖）。
- [改进] PDF 渲染器统一（按 `docs/pdf-generation-unification-plan.md`）：`src/md2pdf.py` 不再依赖 `formatters.markdown_to_html_document`（其面向 web/邮件的 `table { display: block; overflow-x: auto }`、`:hover`、`max-width: 900px` 等 CSS 污染 PDF 分页）。改为 `markdown2.markdown` + 静态 HTML 模板 + PDF 专用 CSS（`@page 20mm 18mm`、CJK 字体栈、表格 `table-layout: auto` + `overflow-wrap: anywhere`、h1-h6 机构研报样式）。公共契约 `markdown_to_pdf_file(md, out) -> Optional[str]` 不变；保留 `_prepare_weasyprint_env`/`_pdf_lock`/`_PDF_LOCK_TIMEOUT` 三个底层基础设施；不传 `base_url`、不加载远程资源、输入仅系统生成 markdown。
- [改进] 彩色 emoji 剥离下沉到 `src/md2pdf.py`（共享 `strip_emoji_for_pdf`），删除 `src/services/supply_chain_report_service.py` 局部 `_EMOJI_STRIP_RE` + `strip_emoji_for_pdf`（旧 import 路径保留为 back-compat re-export 不破坏现有调用方）。深度投研 / 政策与公告排雷 / 供应链分析三处报告自动受益，避免单点补丁式修复。
- [改进] 三个 PDF 下载端点（`api/v1/endpoints/{deep_research,policy_minesweeper,supply_chain_reports}.py`）的 `FileResponse` 增加 `Cache-Control: no-store, no-cache, must-revalidate` + `Pragma: no-cache` + `Expires: 0`，禁止浏览器/中间层缓存旧 PDF（服务端 `pdf_path` 缓存仍复用，no-store 只要求浏览器回源）。
- [改进] 补 h1-h6 默认样式（PDF 必有标题，文档 §6.3 漏规定，PR 实施时补充）：h1=18pt、h2=15pt、h3=13pt、h4=12pt、h5=11pt、h6=11pt #555。防止 h1 跳到 WeasyPrint UA 默认 24pt（过大）、h5/h6 比正文 11pt 还小（反直觉）。
- [文档] 新增 `docs/x-media-source-plan.md`（v3 查证定稿）：x.com 海外媒体消息源接入方案，记录 adanos 查证结论（标准账号可用 per-ticker 情绪 + top_tweets）、Path A 集成架构、市场覆盖现实、可靠性策略、TDD 实现计划与回滚路径。
- [文档] 新增 PDF 下载文件名统一方案，规划深度投研、政策与公告排雷、供应链报告的中文可读下载名、前后端收口、测试矩阵与供应链主题型报告边界。
- [新功能] 新增 `AgentReachService` 底层数据源服务（`src/services/agent_reach_service.py`）：封装 Agent-Reach web（Jina Reader，零配置） + 雪球（官方 API + cookie）双渠道，统一输出 frozen dataclass；懒加载委托，fail-open（未安装/渠道异常返回 `None`/`[]`），绝不拖垮主流程；`agent_reach` 零依赖声明。公共 API：`read_url(url)` / `get_xueqiu_hot_posts/stock_quote/search_stocks/hot_stocks` / `health_check()` / `is_available()` / `unavailable_reason()`。`tests/test_agent_reach_service.py`（33 用例，100% 行覆盖，零真实网络）。
- [新功能] 供应链分析新增「双源校验」工具 `verify_supply_chain_evidence`：对报告中的「公司 / 板块归属」事实做东方财富 + 同花顺结构化双源校验，返回 `status`（confirmed/partial/conflict/unverified/not_applicable）+ `confidence`（high/medium/low）+ 两源证据 + 成分股重合度 + matched_by 维度。新增 `data_provider/supply_chain/cross_source.py`（纯逻辑判定层，镜像 `data_provider/cross_source_validator.py` 的 Protocol + fail-open 设计）：归一纯函数（A 股 6 位代码归一 / 名称标准化 / 板块匹配 / 成分股 Jaccard 重合度）+ 决策表纯函数 `judge_verification` + `SupplyChainSourceProbe` Protocol（N 源可插拔）+ `EastMoneyProbe`（复用 `ConceptBoardProvider`）+ `ThsAkshareProbe`（akshare `stock_board_concept_name_ths` 概念列表 + 同花顺概念详情页分页抓取成分股——akshare 1.18 已无 `stock_board_concept_cons_ths`，成分股走 `q.10jqka.com.cn/gn/detail/code/{code}/order/desc/page/{N}/` GBK 正则翻页，封顶 10 页；`http_get` 可注入便于离线单测，源标记 `akshare_ths`）+ `SupplyChainCrossSourceValidator` 编排（归一 → 逐源 fail-open 收集 → 判定，单源异常绝不拖垮另一源，"未核验"语义非"否定"）。非 A 股（港股/美股/无法归一 6 位）直接 `not_applicable` 不联网；校验失败不阻断报告生成。iFinD 当前仅覆盖数值锚点不支持板块成分股，留 Protocol seam 后续接入，不建未测的 NL 解析。仅注册进供应链 executor（`ALL_SUPPLY_CHAIN_TOOLS`，4 个专属工具），问股/郑希/排雷零影响。真实数据端到端实测：贵州茅台/白酒=confirmed(high,overlap0.75)、比亚迪/新能源车=partial(同花顺无该概念)、宁德时代/锂电池=conflict(东财含300750而同花顺锂电池概念55只不含，真实口径差)、腾讯=hk→not_applicable。
- [改进] 供应链 system prompt 增加「A 股双源校验规则」standing 段 + 最终报告表格契约：A 股候选标的进最终候选表前必调 `verify_supply_chain_evidence`；未得 `confirmed` 不得写成已确认事实，按 status 如实落字（双源确认/单源支持待核验/口径冲突/待核验/不适用）；最终表格新增「东财校验 / 同花顺校验 / 双源状态」三列（未调写「待核验」不得省略）；明确搜索型线索（`search_clue_hype`/`search_semianalysis`）只证「被提及」≠ 板块归属证据，不得混用。
- [测试] 新增 `tests/test_supply_chain_cross_source_validation.py`（88 用例：归一纯函数全分支 / 板块匹配 / 重合度阈值 / 决策表全分支 confirmed-partial-conflict-unverified-not_applicable / fail-open 探针异常隔离 / keyword 回退 / 工具注册+handler 输出契约+前缀代码归一 / prompt 14 项约束，镜像 clue_hype 测试的鸭子类型 fake，无真实网络）；`data_provider/supply_chain/cross_source.py` 100% 覆盖（194 语句 0 miss）。同步 `test_supply_chain_services.py` 工具数断言 3→4（`ALL_SUPPLY_CHAIN_TOOLS`）。
- [文档] 新增供应链报告东方财富 + 同花顺双源校验方案文档，明确 A 股范围、iFinD/公开同花顺降级、待核验输出、工具契约、判定规则、测试矩阵与回滚路径。
- [修复] 供应链分析报告 PDF `⚠️` 等彩色 emoji 乱码（豆腐块）：WeasyPrint 无法把彩色 emoji 位图（sbix/CBDT）嵌入 PDF，`⚠️`(U+26A0+U+FE0F) 路由到 `Apple-Color-Emoji` 字体时渲染成空白豆腐块。新增 `supply_chain_report_service.strip_emoji_for_pdf` 纯函数，在 `_generate_pdf` 渲染前剥掉彩色 emoji + 变体选择符（**保留** CJK / ①②③④⑤ / ≤ / μm / • / → / —— 等信息性字符，这些经 PingFang SC 正常渲染）。`.md` 原文不动（Web/Markdown 视图仍显示 emoji），**只影响 PDF 渲染**；作用域仅供应链（深度投研/排雷同 renderer 但报告基本无 emoji，零影响）。真实报告 `sc_202606280945_1` 重生成后 PDF 无 `⚠`、警告正文保留、不再嵌入 Apple-Color-Emoji。新增 `tests/test_supply_chain_report_pdf_emoji.py`（12 用例：纯函数 10 + 渲染回归 2）。
- [新功能] 供应链分析新增「线索多源炒作检索」工具 `search_clue_hype`：用户提供了「供应链线索」时必调，跨 5 个固定国内财经源——新浪财经（`site:finance.sina.com.cn`）/雪球（`site:xueqiu.com`）/同花顺（`site:10jqka.com.cn`）/巨潮公司公告（`site:cninfo.com.cn`）/全网 Google（不限）——用 `site:` 限定逐源检索线索（半年窗 180 天，每源样本默认 3 条）。**任一媒体提及即题材炒作加分项**，返回每源提及情况 + 提及源列表 + 信号强度（无/弱/中/强，按提及源数 0/1-2/3-4/≥5）。**单源异常/失败不拖垮整体**（逐源 try/except，失败源计 0 提及）。复用本文件已有 `_get_search_service`/`_pick_search_provider`（SemiAnalysis 引入，零重复），仅注册进供应链 executor（`ALL_SUPPLY_CHAIN_TOOLS`，3 个专属工具），问股/郑希/排雷零影响；服务不可用 fail-open 返回 error 让 agent 标「待核验」。实测 Tavily 命中新浪/雪球/同花顺/巨潮/全网 5 源真实文章。
- [改进] 供应链 system prompt「线索核验规则」加第 6 条 standing 规则（仅用户提供线索时触发）：必须调用 `search_clue_hype` 加大搜索面跨国内财经媒体检索线索；任一媒体提及=题材炒作加分项——报告新增「题材炒作信号」小节列出提及媒体名+原文链接+每源条数+`hype_signal`，并把提及广度纳入既有 `hype_risk`（炒作风险）评分（提及源越多 hype_risk 越高，5 源全中=强炒作；未被任何源提及时不额外上调）。可用工具清单与中文显示名（「线索炒作检索」）同步。
- [测试] 新增 `tests/test_supply_chain_clue_hype_tool.py`（query 构造/hype_signal 分级/handler 多源逐源检索含单源容错/全源无命中/搜索失败/结果封顶/days 透传/工具元数据/prompt 规则，镜像 semianalysis 测试的鸭子类型 fake，无真实网络）；同步 `test_supply_chain_services.py` 工具数断言 2→3。pyright/mypy 新工具文件 0 error。
- [修复] 供应链分析报告 PDF 宽多列表格列宽塌缩（表头/单元格被压成「1 字竖排」格式错误）：根因 `formatters.markdown_to_html_document` 注入面向 web 的 `table { display: block; overflow-x: auto }`（GitHub 式横向滚动表格），WeasyPrint 分页 PDF 不支持横向滚动，把宽表渲染为块、列宽塌缩；`md2pdf._PDF_CSS`（注入在 formatters `<style>` 之后、同优先级后者生效）补 `display: table` + `table-layout: fixed` + 单元格 `overflow-wrap: anywhere` / `vertical-align: top` 覆盖，恢复真正表格布局（fixed 列宽均分 + 长 CJK 在格内换行）。供应链「线索验证」「核心标的」6 列长 CJK 表格恢复正常网格；深度投研/排雷报告同 renderer 无回归（深度投研以散文为主、表格少，重渲染 739KB 内容完整无乱码）。新增 `tests/test_md2pdf.py` 两条回归：`test_wide_table_columns_not_collapsed`（6 列宽表不塌缩）+ `test_pdf_css_overrides_table_display_block`（CSS 契约）。
- [新功能] 供应链分析新增 SemiAnalysis 检索工具 `search_semianalysis`：半导体/AI 主题（芯片/SoC、HBM/存储、先进封装/CoWoS、光刻/设备/材料、晶圆代工、GPU/AI 加速卡、数据中心 AI 硬件、硅光子/CPO/薄膜铌酸锂、电源/散热等）必调，按主题/卡点环节构造英文关键词检索 semianalysis.com 一级研究文章，返回标题/摘要/**原文 url**/来源/日期 + source_note。`site:semianalysis.com` 站点限定由 query 字符串承载（所有 provider 尊重 Google `site:` 操作符，**零改共享 `search_service`**），时间窗 365 天（长青研究）；复用共享 SearchService provider（配置 `TAVILY_API_KEYS` 等后可用），无可用 provider fail-open 返回 error 让 agent 标「待核验」。仅注册进供应链 executor（`ALL_SUPPLY_CHAIN_TOOLS`），问股/郑希/排雷零影响；本地自包含 `_get_search_service`/`_pick_search_provider`/`_build_semianalysis_query`，不跨 feature import。
- [改进] 供应链 system prompt 增加「半导体/AI 主题 SemiAnalysis 检索规则」standing 段（仅相关主题生效）：必调 `search_semianalysis`、证据强度 `analysis`（含产业链一手调研升 `primary`）、付费墙内容只引可见标题/摘要不编造、与行情/基本面/新闻交叉验证冲突标注、证据区 `[标题](url)` 渲染原文地址；非半导体/AI 主题（如锂电/光伏）不必调用。可用工具清单同步加 `search_semianalysis` 条目；工具中文显示名「SemiAnalysis 检索」。
- [测试] 新增 `tests/test_supply_chain_semianalysis_tool.py`（query 构造/provider 选择/handler DI 全路径——无 provider/service None/成功站点限定+days=365+max_results 透传/搜索失败/异常/长摘要截断/结果封顶/工具元数据/prompt 规则，镜像排雷公告检索测试的鸭子类型 fake，无真实网络）；新工具 100% 覆盖；同步 `test_supply_chain_services.py` 工具数断言 1→2（`ALL_SUPPLY_CHAIN_TOOLS`）。pyright/mypy 在新工具文件 0 error。
- [新功能] 供应链分析升级为表单式报告流：`/supply-chain` 由聊天式改为表单式报告页（输入分析主题 → SSE 生成 → 报告展示 → 历史列表 → PDF 下载），双栏布局（左历史报告 desktop w-64 / mobile Drawer，右表单+进度+报告+操作）+ 主题快捷模板按钮，报告正文复用 `ReportMarkdownBody`。新增 `SupplyChainReportPage`、`useSupplyChainReport` hook（idle/generating/done/error 状态机 + AbortController + 90s watchdog + 断线提示去历史列表）、`api/supplyChainReports.ts`（getReports/getReport/deleteReport 走 axios + generateStream/downloadPdf 走 fetch blob）。`App.tsx` 路由 element 改指新页，路径 `/supply-chain` 不变；旧聊天页/store/api 保留可回滚。新页面用 `aria-label` 符合 UI governance。
- [新功能] 供应链报告「增加供应链线索」一次性调查目标：线索非空时 service 把用户输入包装成高权重调查指令拼进本轮 user message（主动搜索/两类来源交叉验证/支持-冲突-证伪/写入「线索验证」小节），内部 session `supply_chain_report:{report_id}` 与旧聊天会话 `supply_chain:` 隔离；纯函数 `build_supply_chain_user_message` / `_status_from_result`。前端线索发送后清空、不回填历史线索。
- [新功能] 供应链报告 PDF 惰性下载与历史 CRUD：新增 `SupplyChainReport`（表 `supply_chain_reports`）+ 6 个 DatabaseManager CRUD（save/get/list 倒序/delete 返回路径/set_pdf/prune）、`supply_chain_report_service`（生成→落盘→清理，复用 `src/md2pdf.markdown_to_pdf_file` 惰性生成 PDF）、5 个 `/api/v1/supply-chain/*` 报告端点（新文件 `supply_chain_reports.py`，与旧 chat 同前缀路径不冲突，旧 chat 端点零改动保留）。`report_id` 白名单 `^sc_\d{12}(_\d+)?$`（纯 ASCII，topic 不进路径）+ `_resolve_safe_path` 双重防路径穿越；请求 schema Pydantic v2 `ConfigDict(strict/frozen)` + `Field(min/max_length)`（空/超长主题解析期 422），不新增配置项（保留数量用 service 常量 200）。从 `AgentResult` 派生 status success/partial/failed（partial 仍落盘可查）。
- [改进] 供应链 system prompt 增加线索核验规则段（`_SUPPLY_CHAIN_SYSTEM_PROMPT_TEMPLATE`，仅用户给线索时生效）：线索是调查目标非事实、优先级低于工具证据、必须找支持/冲突/证伪、订单/客户/供应商/产能/市占率/政策须标来源强度、不能因用户给线索就强行确认、报告须含「线索验证」小节（验证状态限已确认/部分确认/未找到可靠证据/存在冲突/已证伪）。仅改字符串常量，不改 `chat()`/`build_supply_chain_system_prompt()` 逻辑，旧聊天（无线索）行为不变。
- [测试] 新增供应链报告后端 3 个测试文件（78 用例：storage 18 + service 38 + api 22，镜像 policy_minesweeper 三件套，离线 mock 不依赖真实 LLM/网络）与前端 3 个测试文件（31 用例：api 8 + hook 14 + page 9）；pyright/mypy 在新文件 0 error；旧 supply_chain_services/e2e + md2pdf 回归全绿。
- [改进] 政策与公告排雷按「类型-契约-数据三层防御」规范（`docs/type-contract-data-defense.md`）硬化：① **Layer 3 Pydantic v2**——`PolicyMinesweeperRequest` 加 `model_config=ConfigDict(strict/frozen/validate_assignment)` + `stock_code: Annotated[str, Field(pattern=^\d{6}$)]` + `horizon: Literal["short","medium","long"]`，畸形输入解析期直接 422（不浪费 SSE 线程）；响应模型加 `model_config`；移除与 Pydantic 重复的 endpoint 层 `normalize_a_share` 调用（避免「重复校验」陷阱，语义校验下沉 service）。② **Layer 1 类型**——`policy_minesweeper_service` 3 处 `Any` 收窄为 `TYPE_CHECKING` 字符串注解（`PolicyMinesweeperExecutor`/`PolicyMinesweeperReport`）；scorecard `TIERS: List[Dict[str,Any]]` → `List[Tier]`（TypedDict）。③ **Layer 2 icontract**——scorecard `score()` 加 `@ensure(lambda r: -100<=r["final"]<=100)` 后置条件守公式结果。新增 `test_policy_minesweeper_scorecard_contract.py`（4 契约用例）+ API 测试改测 422 分层（畸形/空/非法 horizon）+ `generate_stream` 返回注解。pyright+mypy 在 PM 文件 0 error；4 模块仍 100% 覆盖（456 语句）；后端 PM 全量 174 用例通过。
- [新功能] 政策与公告双维度排雷后端：左侧菜单「深度投研」下方新增「政策与公告排雷」功能，真·三 Agent 并行裁决（α 公司公告/经营事件扫描 + β 国家政策/产业互动分析 用 ThreadPoolExecutor 并行 → Ω 综合裁决）。新增 `policy_minesweeper_scorecard`（六维加权确定性评分卡：事件重要性/政策暴露度/盈利影响/估值影响/股价敏感度/时间紧迫度 + 时间窗动态权重 short0.7/0.3·medium0.5/0.5·long0.3/0.7，综合分 -100~+100、5 档等级含仓位指令加仓/增持/持有观望/减持/清仓回避）、`policy_minesweeper_executor`（DI 注入 `loop_runner` 使并行编排与各级降级 100% 可测，任一腿失败走 partial/failed 降级）、`score_policy_minesweeper` 工具（Ω 调用）、`policy_minesweeper_service`（A 股校验→生成→落盘→best-effort 解析评分→清理）、SQLite 表 `policy_minesweeper_reports`、5 个 API `/api/v1/policy-minesweeper/*`（SSE 生成 + 报告 CRUD + PDF 下载，复用 WeasyPrint md2pdf）；`report_id` 白名单 `^\d{6}_\d{12}(_\d+)?$` + 路径收敛双重防路径穿越；`build_policy_minesweeper_executor` 在 factory 精确筛选 5 个问股工具 + 1 个评分工具装入独立 ToolRegistry（不污染问股单例）。报告含强制免责声明、证据来源+日期、「预期冲击为历史经验区间非预测」、「待核验」标注。
- [新功能] 政策与公告双维度排雷前端：表单输入 A 股代码/名称 + 时间窗口（短/中/长期）生成排雷报告，含 α/β/Ω 三角色执行状态指示、PDF 下载与历史报告列表（双栏 + mobile Drawer）。新增 `PolicyMinesweeperPage`、`usePolicyMinesweeper` hook（SSE + 90s 心跳 watchdog + 可取消）、`api/policyMinesweeper.ts`；路由 `/policy-minesweeper`、侧边栏 `ShieldAlert` 图标、i18n（zh「政策与公告排雷」/ en「Policy & Filing Minesweeper」）；新页面用 `aria-label` 符合 UI governance（无原生 `title=`）。
- [改进] 新增配置项 `POLICY_MINESWEEPER_MAX_REPORTS`（默认 200，保留排雷报告数量上限，超出删最旧含 .md/.pdf，`0`=不清理），同步 `.env.example`。
- [测试] 新增政策与公告排雷后端 7 个测试文件（147 用例：scorecard 31 + tools 13 + executor 23 + service 37 + storage 18 + api 18 + factory 7）与前端 3 个测试文件（14 用例：api 7 + hook 4 + page 3），离线 mock 不依赖真实 LLM/网络；scorecard/service/executor/tools 4 模块 100% 覆盖（409 语句 0 miss），factory 新增函数 100% 覆盖。详见 `docs/policy-minesweeper-test-report.md`。
- [文档] 新增 `docs/policy-minesweeper.md`（功能定位/架构/接口/评分模型/配置/边界/排障）与 `docs/policy-minesweeper-test-report.md`（测试报告）。
- [新功能] 政策与公告排雷新增「公司公告检索」工具 `search_company_announcements`：α 专属，复用共享 SearchService 的 Tavily provider（走原生 `.search()` 绕过面向新闻的过滤/再排序，保留一手公告源），返回带**公告原文地址 `url`** + `is_official`（巨潮资讯/交易所/官网标注一手，腾讯/新浪等媒体标注二手）的结果，实测命中巨潮资讯网/新浪证券 `vCB_AllBulletin`/东方财富公告页/公司官网；服务不可用时返回 error 让 α 标注「待核验」。仅注册进 PM executor（5 wengu + score + 公告检索 = 7 工具），**不改共享 `search_service.py`/`search_tools.py`**（零影响问股/供应链/深度投研）。配置 `TAVILY_API_KEYS` 后可用（`.env.example` 已有占位）。新增 16 用例（query 构造/provider 选择/源分类/handler DI 全路径），tools 模块 100% 覆盖（51 语句），后端 PM 全量 169 用例通过。
- [改进] 政策与公告排雷证据链补「公司公告原文地址」：α 公告扫描的公司公告类证据必须附**公告原文地址 `url`**（取自 `search_stock_news`/`search_comprehensive_intel` 结果中的 `url` 字段，非编造），报告证据区以 `[原文](url)` 可点击链接渲染，取不到地址的 `source` 标注「待核验」。三处同步：scorecard `to_markdown` 渲染 url + score 工具 evidence 参数文档化 url + system_prompt 红线（仅 PM 模块，不影响问股/供应链/深度投研）；新增 6 用例（scorecard 4 + tool 2），scorecard/tools 仍 100% 覆盖，后端 PM 全量 153 用例通过。
- [修复] 深度投研报告 PDF 列表项目符号乱码（渲染成"煉"）与「产业链图谱」代码块黑条：根因是 `xhtml2pdf` + reportlab CID 字体（`STSong-Light`）的 `<li>` list marker CMap 错位（bullet→"煉"）与 `<pre>` + CJK 元素级渲染整片黑条，无法靠字符净化根治。`src/md2pdf.py` 渲染引擎由 xhtml2pdf 切换为 **WeasyPrint**（Pango/Cairo），正确处理列表项目符号、`<pre>` 代码块、emoji、箭头、表格；接口契约不变（`markdown_to_pdf_file` 返回路径或 None，失败降级 404，不影响报告生成主流程）。macOS 自动探测 Homebrew lib 路径免手动配置 `DYLD_FALLBACK_LIBRARY_PATH`；Docker/CI 同步装 pango/cairo/fonts-noto-cjk。`requirements.txt` 移除 xhtml2pdf/reportlab、加 weasyprint；新增 `tests/test_md2pdf.py` 14 用例覆盖（含两条核心回归断言：bullet 不含"煉"、代码块"上游/→"可提取）。
- [修复] 深度投研报告 6.2 资金流向「主力净流入（5日累计）数据缺失（接口超时）」：根因是 akshare 三个资金流接口均打 `push2his`/`push2.eastmoney.com`，本机代理下 404/超时不可达且无 em 备份源，`inflow_5d`/`inflow_10d`/`main_net_inflow` 全超时为 None；MX 仅返回单日、无多日累计。现以 iFinD 为稳定多日源：新增 `capital_flow_provider`（纯函数 `compute_cumulative` 求 5/10 日窗口累计 + `get_main_inflow_cumulative` 编排 fail-open）、iFinD 新增 `_parse_ifind_markdown_series` 多行序列解析与 `fetch_main_inflow_series`（实测「近 N 个交易日」措辞才返回多行，「近 N 日」会被折叠为最新单值）；`get_capital_flow` 在交叉验证开关开时回填——`main_net_inflow` 优先 MX+iFinD 双源方向验证值（conf=high），`inflow_5d`/`inflow_10d` 取 iFinD 多日累计，已有值不覆盖，status 提升 partial 并附 `capital_flow_fallback` 来源标注，原 failed note 移除。开关关 / iFinD 未配 → 零回归。新增纯函数单测 100% 覆盖。
- [修复] 深度投研报告毛利率/营收增速「数据缺失，growth模块返回null」：这两字段原仅 AkShare 单源，东财爬虫限流/超时即全空且无兜底。现接入交叉验证层——新增 `gross_margin`/`revenue_yoy` 锚点规格（容差放宽、口径非标准化关 caliber 判定）、MX 新增 `_pick_growth_value` 专门取「同比增长率」列（与 `_pick_value` 取绝对值互补）并在 `query_financials` 增查毛利率/营收同比、iFinD 增两锚点查询；`get_stock_info` 在 growth 块为空时用验证结果回填 `revenue_yoy`/`gross_margin`/`roe` 并把 status 提升到 partial。同步修 revenue/net_profit/roe「单源 MX」：交叉验证传入最新年报报告期驱动 iFinD 财务类查询，MX 带期取不到自动回退最新（零回归）。新增纯函数单测覆盖。
- [修复] 定时任务调度：大盘复盘任务补充任务级文件锁避免重复执行；手动触发接口锁超时改为读取 `SCHEDULE_LOCK_TIMEOUT` 配置；清理 `tests/conftest.py` 测试收集警告。
- [修复] 端到端测试发现 `analysis_history` 表缺少 `research_framework`/`bayesian_framework`/`supply_chain`/`value_scenarios`/`investment_conclusion` 五段式投研新字段，导致报告保存失败；新增 `scripts/migrate_analysis_history_20250625.py` 迁移脚本对已有 SQLite 数据库自动补列，并兼容创建 `scheduled_task_log` 表。
- [修复] 双源适配器数值解析经 Phase 0 真实数据探测后修复三处缺陷：① `_safe_float` 增加中文金额单位换算（万亿/亿/万 + 元 复合单位，如「1709亿元」→1.709e11）；② MX 财务 query 跳过「同比增长率/增长率/环比」列，避免营收/净利关键词误命中增长率（15.66%）取到错误值；③ iFinD 适配器按 Phase 0 实测的真实 schema 重写——iFinD 工具均为自然语言 `query` 参数、返回 Markdown 表格（非结构化字段），新增 `_parse_ifind_markdown_table`/`_parse_ifind_response` 纯函数解析；缺失锚点 `value` 由占位 `0.0` 改为 `None`（不误导 LLM 编造为 0）。
- [新功能] 深度投研报告关键锚点支持 MX Data 主源 + iFinD 双源交叉验证：新增 `data_provider/cross_source_validator.py`（N 源可插拔验证核心，容差/口径/报告期三重判定）、`mx_data_adapter.py`（东财妙想主源，移植自 uzi-skill，30min 缓存控配额）、`ifind_fundamental_adapter.py`（同花顺 iFinD MCP 验证源，单例连接池），opt-in 开关 `DEEP_RESEARCH_CROSS_VALIDATE` 默认关闭零回归。
- [新功能] 资金流锚点按方向+量级验证：主力净流入因东财/同花顺算法口径不同，验证用「方向一致+量级同档」非严格数值比对；融资余额为交易所确定数据用 ±0.5% 严格一致；筹码集中度算法强依赖源仅作参考标注。
- [改进] `get_stock_info`/`get_realtime_quote`/`get_capital_flow` 三个工具在开关开启时注入 `cross_validation` 块进 LLM 上下文（当前价主源=盘中实时行情、估值/财务/资金主源=MX，均由 iFinD 验证），关闭时工具返回与改动前完全一致。
- [改进] 深度投研 prompt 新增「双源验证标注」原则，关键数字按置信度标 ✓双源一致（附差异%/口径/报告期）/ ⚠冲突 / 单源 / 数据缺失；validator 增加双源标注信息性统计（不参与 passed/score 判定）。
- [文档] 新增 `docs/data-sources.md` 三源职责、主源分流、锚点容差/口径/报告期语义、资金流验证策略说明。
- [测试] 新增 `cross_source_validator`/`mx_data_adapter`/`ifind_fundamental_adapter`/`cross_validation_helpers` 四模块单测，均 100% 覆盖（离线 mock，不依赖真实 key）。
- [chore] 新增 `scripts/probe_data_sources.py` Phase 0 可行性探测脚本；`requirements.txt` 加 `mcp>=1.0.0`；`.env.example` 加 `MX_APIKEY`/`IFIND_MCP_*`/`DEEP_RESEARCH_CROSS_VALIDATE`/`MX_CALL_BUDGET` 占位符。
- [修复] 深度投研报告多处「数据缺失」根因：fundamental pipeline 超时默认值过紧（fetch 3s/stage 8s），代理/限流环境下可达的 em 接口（realtime_quote ~4s、业绩报表 stock_yjbb_em 全量分页 ~5s）被误判超时 → 估值/财务/机构/龙虎榜全 failed。放宽默认值（fetch 3→10s、stage 8→25s，同步 `.env.example`），正常环境（em 快）用不到额外时间，仅慢接口受益；实测 valuation/growth/institution/dragon_tiger 从全 failed 恢复为 ok/partial。
- [改进] `get_capital_flow` 资金流失败诚实降级：资金流源 `stock_individual_fund_flow` 走 push2his.eastmoney.com（代理/限流不可达、无 em 备份源），失败时返回明确 `note`（"资金流数据源暂不可用，请结合成交量/换手率判断"），避免 LLM 误判「数据缺失」而编造。
- [修复] `get_chip_distribution` 工具筹码数据缺失：`ak.stock_cyq_em` 是唯一筹码源，em 网络/代理不可达时全失败且无 fallback。新增 fail-open 估算降级——em 失败时用历史K线（tencent 等可用源）按成交量加权估算 `avg_cost`/`profit_ratio`/`cost_70/90`/`concentration`，返回带 `estimated=True` 标记的数据供 LLM 标注精度；估算失败仍返回 error 不阻塞；只改工具层，不影响 base/fetcher。
- [修复] `get_stock_info` 工具估值「数据缺失」：`get_fundamental_context` 的 valuation 步骤受严格 fetch 超时（默认 3s）限制，而 `get_realtime_quote` 带 em→sina→tencent fallback 实测可达 4-5s，em 源失败时易超时 → pe/pb/市值全 None。新增 fail-open 兜底：`_handle_get_stock_info` 检测 valuation 缺 pe 时，用无超时的 `get_realtime_quote` 补全缺失字段（已有值不覆盖），兜底失败仍保持原值不阻塞；只改工具层，不影响 fundamental pipeline 主流程/alphasift。
- [改进] 深度投研报告保存健壮性：① `report_id` 同分钟同股票冲突保护——生成前检测 DB，已存在则追加 `_1/_2/...` 序号后缀（避免 `save` 的 merge 覆盖旧记录导致 .md/.pdf 文件孤儿），同步放宽 report_id 白名单为 `^\d{6}_\d{12}(_\d+)?$`（路径穿越防护不变）；② `stock_name` 缺省（前端未传）时反查真实中文名（复用 `get_realtime_quote.name`），避免元数据 `stock_name` 退化成代码，反查失败仍 fallback 到 code 不阻塞生成。
- [修复] 修复深度投研（及所有 agent）盘中报告「当前价」用过时昨收价的问题：`analyze_trend` 的 `current_price` 原取自历史日线最后一根 close（盘中今日未入库 → 昨收），现于 `_fetch_trend_data` 盘中自动合并今日实时行情 bar，使 `current_price`/MA/bias 等统一反映实时价；收盘后/非交易日/实时失败时零行为变化（优雅降级）。
- [修复] 深度投研报告 PDF 下载 404：重构 `src/md2pdf.py` 渲染引擎，从 `imgkit`（`wkhtmltoimage` 封装，PDF 非其原生能力）切换为 `xhtml2pdf`（纯 Python）+ `reportlab` 内置 CID 字体（`STSong-Light`），修复了 imgkit 找错二进制 + macOS Homebrew 6.0+ 无 `wkhtmltopdf` formula 的双重问题；纯 Python 零系统依赖，macOS / Linux / Docker 全平台一致；`download_pdf` 端点区分「报告不存在」与「渲染失败」两种 404 文案；前端 `downloadPdf` 解析后端 `detail` 回显更具体错误原因。
- [新功能] A股深度投研报告模块：左侧菜单（首页下方）新增「深度投研」入口（`/deep-research`），表单输入 A 股代码/名称生成机构级五层穿透（宏观/产业/财务/估值/博弈）深度研报，支持 PDF 下载与历史报告列表。
- [新功能] 深度投研后端：新增 `deep_research_executor`（复用问股 10 个工具 + 五层穿透 prompt）、`deep_research_validator`（三层防线质量校验）、`md2pdf`（wkhtmltopdf 惰性生成 + Semaphore 限流）、SQLite 存储表 `deep_research_reports`（替代易损坏的 index.json）、5 个 API 接口 `/api/v1/deep-research/*`（SSE 生成 + 报告 CRUD + PDF 下载，含路径穿越白名单防护）。
- [新功能] 深度投研前端：新增 `DeepResearchPage`（双栏：历史列表 + 表单/报告）、`useDeepResearch` hook（SSE + 心跳 watchdog + 可取消）、`api/deepResearch.ts`、`.deep-research-prose` 表格样式（修正 nowrap、数字右对齐）。
- [改进] `StockAutocomplete` 新增 `mode`（`instant`/`form`）参数，适配表单流（选中不立即提交）；`.env.example` 新增 `DEEP_RESEARCH_MAX_REPORTS` 配置项。
- [文档] 新增 `docs/deep-research.md` 深度投研报告专题文档。
- [改进] Web 端将「问股」导航菜单及对应页面标题、浏览器标签页标题、新消息提示与空状态引导文案统一更名为「A股分析」，同步更新相关单测与 e2e 断言文案；用量分类、配置说明、会话导出标题等非导航语境的「问股」保持不变。
- [修复] 修复供应链与郑希对话刷新页面后当前会话内容丢失的问题：后端会话列表返回的 session_id 去掉命名空间前缀（与前端 localStorage 无前缀格式对齐），GET/DELETE 会话端点兼容无前缀 id；问股不加前缀不受影响。
- [新功能] 五段式长线产业链投研报告（P0/P1/P2）：
  - [P0] 新增 `src/schemas/report_schema.py` 五段式字段（investment_conclusion/supply_chain/value_scenarios/bayesian_framework/research_framework）
  - [P0] 新增 `src/services/research_integration_service.py` 五段式报告编排服务
  - [P0] 新增 `apps/dsa-web/src/components/report/FiveSectionReportView.tsx` 五段式报告整合视图
  - [P0] 新增 `apps/dsa-web/src/components/report/SupplyChainPanel.tsx` 产业链解读面板
  - [P0] 新增 `apps/dsa-web/src/components/report/BayesianScoreTable.tsx` 贝叶斯评分表
  - [P0] 新增 `apps/dsa-web/src/components/report/InvestmentConclusionCard.tsx` 投资结论卡片
  - [P0] 新增 `apps/dsa-web/src/components/report/ValueScenariosCard.tsx` 价值情景卡片
  - [P0] 修改 `ReportSummary.tsx` 集成五段式报告展示
- [新功能] P1 六维详情展开面板：新增 `apps/dsa-web/src/components/report/DimensionDetailPanel.tsx` 展示六维每个细分指标的详细分析
- [新功能] P1 Feature Flag 配置：新增 `RESEARCH_FRAMEWORK_ENABLED`、`BAYESIAN_FRAMEWORK_ENABLED`、`SUPPLY_CHAIN_ANALYSIS_ENABLED`、`VALUE_SCENARIOS_ENABLED`、`ENABLE_AGENT_ANALYSIS` 环境变量配置
- [新功能] P2 数据提供者：验证 `data_provider/supply_chain/` 模块（概念板块/机构持仓/北向资金）已完整可用
- [新功能] P3 产业链 Agent：新增 src/agent/agents/supply_chain_agent.py，继承 BaseAgent，实现产业链定位分析、护城河评估、中美链风险识别和客户集中度分析。
- [新功能] P3 价值 Agent：新增 src/agent/agents/value_agent.py，继承 BaseAgent，实现长期价值情景分析（乐观/基准/悲观）、价值区间锚定和投资边缘计算。
- [新功能] P3 价值情景 Prompt：新增 src/agents/prompts/value_prompts.py，包含完整价值情景分析 Prompt 模板和摘要生成 Prompt。
- [新功能] P3 评分服务集成：ResearchScoringService 新增 _init_agents、analyze_supply_chain_agent、analyze_value_agent、enrich_with_agent_analysis 方法，支持 P3 Agent 自动调用和数据增强。
- [新功能] P3 前端 Agent 分析面板：新增 apps/dsa-web/src/components/report/AgentAnalysisPanel.tsx，展示产业链分析、价值情景分析和催化剂/风险。
- [新功能] P2 前端展示：新增 apps/dsa-web/src/components/report/ResearchFrameworkPanel.tsx 前端组件，展示六维评分、贝叶斯分析和仓位建议，支持紧凑和完整两种模式。
- [新功能] P2 产业链数据：新增 data_provider/supply_chain 数据提供模块，包含概念板块（ConceptBoardProvider）、机构持仓（InstitutionalHoldingsProvider）、北向资金（NorthboundFlowProvider）三个数据源，支持 akshare 数据接入和 mock 数据降级。
- [新功能] P2 产业链 Prompt：新增 src/agents/prompts/supply_chain_prompts.py，包含完整产业链分析 Prompt 模板和 LLM 分析指引。
- [新功能] P2 LLM 主观评分：新增 src/services/llm_subjective_service.py，实现基于 LiteLLM 的产业链、价值情景、情绪推断等主观评分服务。
- [新功能] P2 评分服务集成：ResearchScoringService 新增 enrich_with_p2_data 和 process_with_p2_enrichment 方法，支持 P2 数据自动增强和混合评分。
- [新功能] P1 长线投研框架：新增贝叶斯概率引擎（map_prior/calculate_edge/update_posterior/map_position）、六维评分引擎（产业链/基本面/资金面/技术面/情绪/宏观）、持仓/评分账本（PositionLedger/ScoreLedger）及对应 Repository/Service。
- [新功能] P1 新增 `/api/v1/research-framework/positions` 持仓 CRUD API、`/api/v1/research-framework/positions/concentration` 集中度查询 API、`/api/v1/research-framework/research/validate` 仓位验证 API。
- [新功能] P1 将研究框架集成到主分析流程（StockAnalysisPipeline._integrate_research_framework），分析结果包含 research_framework 和 investment_conclusion 字段。
- [新功能] P1 新增 `ENABLE_RESEARCH_FRAMEWORK` 配置开关，默认启用。
- [测试] P1 完成 72 项完整验证测试，覆盖贝叶斯引擎、六维评分、指标模块、持久化层、API 端点和主流程集成。
- [文档] P1 新增长线投研框架实施文档（docs/long-term-research-implementation-v2.md），规划 P1-P4 实施路线。
- [修复] AlphaSift 热点题材刷新在 EastMoney 瞬断且无缓存时返回友好空态，并让桌面更新保留 AlphaSift 热点缓存。
- [修复] 问股从历史报告进入后的追问会持续携带当前标的，切回或重载已有会话时可从历史消息恢复基础当前标的，并由后端阻断未明确切换时的错误股票工具调用、交易所片段和指标缩写误路由。
- [修复] 自选股加入和删除按等价股票代码匹配港股及大小写美股变体，避免 `00700`、`HK00700`、`00700.HK` 或 `aapl`、`AAPL` 被误判为不同标的。
- [改进] #1390 P0 为个股分析与历史/回测展示新增可选八态 `action` / `action_label` 建议动作字段，保留 `operation_advice` 自由文本和 `decision_type=buy|hold|sell` 统计口径，不新增迁移或配置项。
- [新功能] #1390 P1 新增独立 `DecisionSignal` 存储、Repository、Service 与 `/api/v1/decision-signals` API，支持按来源类型/市场/股票/动作/期限/阶段去重、按 `source_report_id` / `trace_id` 查询、同源过期信号续期且保留来源身份字段、禁止 expired 直接 PATCH 复活、价格计划校验、状态更新、懒过期、cache-only 持仓过滤、敏感信息脱敏、敏感 `trace_id` 拒绝和仅清理 `source_type=analysis` 历史绑定信号的历史删除联动。
- [改进] #1390 P1 补充 Web decision-signals typed API wrapper 与契约隔离测试，暂不接入 UI。
- [改进] #1390 P3 为 `DecisionSignal` 补齐默认生命周期、同源窄 relaxed 去重、相反 active 信号自动 invalidated、terminal 状态不可 PATCH 复活和自动提取低敏 market phase hints，保持 API 响应 schema 不变。
- [新功能] #1390 P4 新增 Web AI 建议页、持仓页最新 active 信号摘要和历史报告提取信号展示，复用既有 DecisionSignal API 且不新增后端契约或配置项。
- [修复] #1390 P4 修复 Web AI 建议页筛选/状态更新分页、价格计划单边入场价展示、持仓 latest 信号刷新、详情 JSON 安全渲染和卡片交互语义问题。
- [修复] #1390 收紧建议动作 legacy fallback：英文 `not to ...` 与 `avoid selling/reducing/trimming ...` 等否定/回避表达不再误判为买卖动作，Web 旧记录不再把中文金融上下文、`buy or sell`、多 guard 歧义文本或 `buyback` / `buy-back` / `buy back` / `selloff` / `sell-off` / `sell off` 等英文复合词渲染成 action badge，并在有结构化 `action` 时让回测/历史趋势等入口按界面语言显示 action 标签。
- [改进] 完善运行时日志上下文，补充 logger name、触发来源、市场统计与实时行情预取链路状态，便于排查调度、API、Bot 和数据源降级路径。
- [改进] #1595 P0a 新增 legacy LLM usage provider/cache telemetry 与 message HMAC 诊断字段，保持 prompt、provider 请求参数、fallback 与用量 summary API 行为不变。
- [新功能] 新增分析任务与历史报告运行流快照 API，提供 lanes、nodes、edges、events、summary 等统一契约，并从任务队列、运行诊断和 AnalysisContextPack overview 构建脱敏数据流/信息流。
- [新功能] Web 端为活跃任务、历史报告和大盘复盘报告补充运行流视图入口，支持查看运行摘要、拓扑节点、事件流和基础排障详情。
- [修复] 修复历史报告运行流快照在混合时区事件时间戳下返回 500 的问题。
- [改进] #1459 持仓管理页新增持仓账户删除入口，复用现有账户软删除接口，误建账户会从默认列表、快照、风险、录入入口和事件列表隐藏且不物理清理历史流水。
- [修复] 修复运行流 live SSE 事件未复用快照层递归脱敏规则的问题，避免本地路径、prompt/raw response、代理头等敏感诊断字段在 refetch 前短暂暴露。
- [修复] 修复 Web 首页分析任务卡片在窄侧栏下挤压股票信息、进度和运行诊断文案的问题。
- [修复] 隔离个股分析自动生成的大盘上下文运行诊断，避免大盘复盘与个股报告共用 query_id 导致运行流重复展示“保存报告”和“推送通知”，并兼容通知跳过时 `attempts=0` 的运行流快照。
- [改进] 运行流 active task 增加 provider 与 LLM started 实时事件，长耗时步骤开始时先显示 running 卡片，完成后复用同一节点更新结果，避免重复卡片。
- [修复] 运行流为筹码分布补齐 provider started/result 事件，个股分析触发筹码数据源调用时可显示“筹码结构”运行卡片并记录降级尝试。
- [修复] 修复个股运行流活跃任务后期 LLM/通知卡片临时重复、数据源聚合卡片过早显示成功，并为个股所属板块补齐运行流卡片。
- [新功能] #1649 新增 Token 用量监控看板与 `/api/v1/usage/dashboard` 接口，展示 LLM 调用总量、Prompt/Completion 拆分、模型用量、调用类型分布和最近调用明细。
<!-- 新条目格式：- [类型] 描述（类型取值：新功能/改进/修复/文档/测试/chore）-->
<!-- 每条独立一行追加到本段末尾，无需分类标题，合并时冲突最小 -->
- [修复] 发布说明生成查询 PR 作者失败时保留降级并输出包含 PR 编号和异常类型的 warning，便于排查 token、权限、网络或 GitHub API 异常。
- [改进] DSA 数据源链路新增 Tencent 日 K 直连 fetcher、daily source health 短期熔断，并升级 AlphaSift 默认 pin/runtime bridge，默认启用 `DAILY_SOURCE=auto`、Sina snapshot 优先级和候选级 quote context。
- [文档] 新增性能优化方案设计文档 `docs/performance-optimization-plan.md`，基于 2026-06-23 单股 dry-run `cProfile` 实测采样，覆盖真实热点（大盘分析占 89% 耗时）、修正后的 P0~P4 优先级清单、放弃项与待测场景规划。
- [文档] 补充 AlphaSift 迁移与回退边界：明确 `ALPHASIFT_INSTALL_SPEC` 显式覆盖语义、`requirements.txt + DEFAULT_ALPHASIFT_INSTALL_SPEC` 与运行时兼容边界、以及回滚路径（关闭功能/完整 revert）说明，覆盖旧 pin 用户升级行为。

- [新功能] 个股分析历史成功保存后会从最终报告 best-effort 提取 `DecisionSignal` 决策信号，复用现有信号去重、计划质量计算和脱敏契约。
- [文档] 新增个股分析报告优化设计文档（docs/report-optimization-design.md），规划长线产业链/供应链投研、贝叶斯概率框架（先验/Edge/后验/仓位）、中美平行竞争链与自反思记录系统，作为后续分阶段实现的真源。

- [新功能] 新增「郑希投研分析」对话框（侧栏 /zhengxi）：基于郑希公开观点语料、投资方法与真实基金数据的可溯源投研问答，数据迁移自 zhengxi-views 知识库（MIT，公开内容）。
- [新功能] 郑希专属 Agent executor（独立 ToolRegistry + 郑希 system prompt 注入 method/scorecard/诚实红线），3 个工具（语料检索/基金数据/六维评分），复用问股的 run_agent_loop/LLMToolAdapter/SSE/会话持久化基建，不污染问股工具集。
- [新功能] 郑希会话用 `zhengxi:` 前缀隔离（复用 storage 的 session_prefix 过滤，后端零 schema 改动）；前端 chat store 工厂化（createAgentChatStore）支持问股与郑希各自独立实例，问股行为零回归。
- [测试] 新增郑希数据完整性校验（scripts/check_zhengxi_data.py）与检索召回验证（scripts/check_zhengxi_retrieval.py，15 条溯源黄金集 + 主题同义词扩展表）。
- [文档] 新增郑希投研专题文档（docs/zhengxi-research.md），说明能力边界、诚实红线、数据时效与后续版本规划。

- [新功能] 新增「供应链分析」对话框（侧栏 /supply-chain）：基于 Serenity 9 步深度调研方法（市场故事→系统变化→产业链层级→稀缺卡点→候选公司→证据→证伪），集成自 serenity-skill（MIT）。
- [新功能] SupplyChainExecutor（复用问股 get_tool_registry 工具集 + 1 个供应链瓶颈打分工具；max_steps=40 / wall_clock=1200s 长任务，硬编码不碰问股/郑希的 config.agent_max_steps）；system prompt 注入 SKILL.md + 核心 5 个 references + 合规红线 + 工具结果摘要约束（防 context 爆炸）。
- [新功能] 供应链会话用 `supply_chain:` 前缀隔离（与问股/郑希 3 路不串台）；前端第 3 个 chat store 实例（createAgentChatStore 工厂化，问股/郑希零回归）。
- [改进] serenity_scorecard 纯函数通过 importlib 直接加载（无需 subprocess），包装为 score_supply_chain_bottleneck 工具（8 因子 + 8 惩罚，满分 100，含非法值容错）。
- [测试] 供应链数据完整性校验（scripts/check_supply_chain_data.py）+ scorecard/工具 pytest；serenity-skill 自带 6 个 evals 可作回归（3/5/6 廉价 CI smoke，1 离线完整评估）。
- [文档] 新增供应链分析专题文档（docs/supply-chain-research.md），含 nginx 部署超时配置（proxy_read_timeout 960s）与成本预期（50–200K tokens/次）。
- [改进] 深度投研框架迁移（按 `docs/deep-research-chain-news-logic-plan.md`）：分析重心由"五层穿透 + 技术节奏"改为"消息面+产业链主导"，技术面降权为择时辅助（≤ 15% 篇幅，不得推翻产业链主判断）。`data/deep_research/system_prompt.md` 替换为新八章骨架（投资结论 + 一~八：消息面与产业政策 / 产业链位置与瓶颈环节 / 国产替代与平行替换 / 材料工艺独特地位 / 中美产业链关系 / 财务与估值验证 / 技术面与筹码节奏 / 风险证伪），新增 10 条硬约束（消息面+产业链主导、国产替代/中美链必先答适用性、来源等级标注、社区源只做市场分歧线索、技术面降权、PE 估值口径一致性等）。`DeepResearchExecutor._build_user_message` / `_FALLBACK_SYSTEM_PROMPT` / `progress_callback` 文案同步更新。
- [改进] `DeepResearchValidator` 重新设计（新 `_LAYER_REQUIREMENTS` 七层 + 新 `_REQUIRED_SECTIONS` 九个 + 技术面层标记 `optional=True`）：旧"宏观/产业/财务/估值/博弈"五层映射为新"消息面与产业政策 / 产业链位置 / 国产替代 / 材料工艺独特地位 / 中美产业链关系 / 财务与估值 / 技术面与筹码节奏"。技术面层缺工具 / 缺关键词只降分不阻断（标记"缺少择时信息"）；国产替代 / 中美链章节未显式给出适用性判断（强相关 / 低相关 / 不适用）各扣 5 分；新增 `_extract_layer_section` / `_has_applicability_judgment` 辅助函数（适用性判断**限定到该层所在章节**，避免跨章节误判）。修复底层 `layer_score` 截断到 100 之前先扣分导致满分报告扣分不可见的 bug。PE 估值口径一致性检测保留（回归保护）。
- [新功能] P1：深度投研工具集新增 `verify_supply_chain_evidence`（东方财富 + 同花顺 A 股公司/板块归属双源校验，已注册到供应链 executor，深度投研也可用）。`src/agent/factory._DEEP_RESEARCH_TOOL_NAMES` 从 10 → 11 个工具，docstring 与注释同步更新。
- [新功能] P2：新增 `search_market_discussion` Agent 工具（`src/agent/tools/search_tools.py`），复用 `AgentReachService` 的雪球热帖渠道，输出结构含 `source_type`（community_cn / community_global）/ `source_name` / `title` / `snippet` / `url` / `published_date` / `claim` / `reliability_hint`（社区源固定 low，绝不标 high）。**fail-open**：agent_reach 不可用 / 渠道异常 / 海外渠道（x_global）未接入 → 返回 `status=unavailable` + 空 results + 真实错误信息，不抛异常不阻断主报告。未知 source 也返回 unavailable 而非抛错。已加入 `ALL_SEARCH_TOOLS` 列表。
- [测试] 新增 `tests/test_deep_research_chain_news_logic.py`（29 用例）：`_LAYER_REQUIREMENTS` / `_REQUIRED_SECTIONS` 结构性测试、新八章满分支满分、强相关行业缺适用性扣 10 分 / 单个缺扣 5 分、白酒低相关 + 缺技术面工具仍 passed（技术面降权）、空报告/缺必需层/概率和回归、`_has_applicability_judgment` 跨章节隔离、`search_market_discussion` 契约（fail-open / reliability_hint=low / 未知 source / x_global 海外渠道）、`_build_user_message` 反映新框架、`system_prompt.md` 含新八章标题、PE 估值口径一致性回归保护。同步更新 `tests/test_deep_research.py` 的 `GOOD_MD` / `FULL_TOOLS` / `test_empty_report_scores_zero`（5 → 7 层）/ `test_missing_tool_flags_layer`（宏观 → 消息面与产业政策）/ `test_missing_content_keyword_flags_layer` fixture。深研相关 117 个测试全过。
- [新功能] P3（按 `docs/deep-research-chain-news-logic-plan.md` §工具调整 P3）：news_intel 新增 `source_type`（official / news / industry / community_cn / community_global）+ `reliability_hint`（high / medium / low / unverified）两列；`_ensure_news_intel_source_columns` best-effort ALTER 老库（参考 `_ensure_supply_chain_stock_columns` 模式）。`save_news_intel` 接受 `source_type/reliability_hint` 入参。`search_market_discussion` 在 results 非空时按 `dimension=community_cn/community_global` + `source_type=community_cn/community_global` + `reliability_hint=low` 入库（构造最小 `SearchResponse` 走 `_persist_news_response` 通道，best-effort 不抛异常不阻断主报告）。社区源可靠性**绝不标 high**（按文档 §信息源策略）。
- [测试] 新增 `tests/test_deep_research_e2e_structure.py`（15 用例，**无 LLM**）：从 `deep_research_reports` 拉最近一份真实报告，跑结构断言覆盖文档 §测试计划 e2e mock 4 条（结论先给消息面/产业链 / 产业链章节含双源校验 / 国产替代含适用性 / 中美链含适用性）+ 3 条扩展（九大章节必含 / 技术面 ≤ 20% 篇幅 / 每章首句【结论】）+ 白酒 fixture（不硬套国产替代）+ 5 个结构工具单测。模块级 fixture（module-scope）避免 class-scope PytestRemovedIn10Warning。**真实报告验证**：688486 龙迅股份 2 份 deep research 报告全部 7 项断言通过（技术面 7.8% / 6.8% 远低于 15% 上限，国产替代/中美链均含"强相关 / 适用"判断，产业链章节含"东方财富+同花顺+confirmed"双源校验）。
- [修复] 修 `scripts/ci_gate.sh` 裸调 `python`（复盘文档 §6）：脚本环境假设与本地 venv 不一致导致 icontract/fastapi 等依赖缺失而失败。改为探测 `./venv/bin/python` → `./.venv/bin/python` → 系统 `python3` 的 fallback 链，未找到则报错退出。
- [修复] Chanlun DataFetcher 测试 vs 实现契约不一致（3 个失败）：`ChanlunDataFetcher` 缺类属性 `CRYPTO_SYMBOLS`（仅模块级）；缺 `_normalize_yfinance_df` 方法。补 `CRYPTO_SYMBOLS = CRYPTO_SYMBOLS` 类属性别名 + `_normalize_yfinance_df` 标准化 yfinance 风格（Open/High/Low/Close/Volume → 小写 + date 由索引推断）。
- [修复] 个股历史代码归一化：测试期望用任一写法（`.SH`/`.SS`/无后缀/`HK` 前缀/补 0）查询应返回**全部变体**的历史记录，但 `get_history_list` 只取 `candidates[0]` 单一查询。改为 `candidates` 多于 1 时传 `List[str]` 触发 `IN` 查询（`get_analysis_history_paginated` 已支持）。4 个 `test_history_list_matches_*` 用例全过。
- [修复] PDF 文件名日期漂移：endpoint 在 record 缺 `created_at` 字段（如测试 mock / 历史数据迁移）时回退到今天，违反 `docs/pdf-download-filename-plan.md` "日期取 `created_at` 而非下载当天"。改为从 `report_id`（格式 `{code}_{YYYYMMDDHHmm}[_seq]`）推断日期兜底。`test_no_store_coexists_with_content_disposition` 通过。

## [3.22.0] - 2026-06-13

### 发布亮点

- feat: 新增 DecisionSignal 独立存储与 API、运行流快照 API 和 Web 运行流视图，补齐建议动作结构化字段与历史/回测展示链路。
- feat: AlphaSift 热点题材链路升级为新版合约，支持热点榜单、题材详情、发酵路线、概念股详情、缓存与兜底数据源。
- feat: 个股分析默认注入当日大盘环境摘要，并在高风险/退潮环境下软化激进买入建议。
- fix: 修复问股历史追问标的上下文、自选股等价代码匹配、低质量新闻过滤、运行流脱敏与 AlphaSift 热点详情展示等稳定性问题。

### 新功能

- 新增独立 `DecisionSignal` 存储、Repository、Service 与 `/api/v1/decision-signals` API，支持来源/市场/股票/动作/期限/阶段去重、查询、续期、状态更新、懒过期、持仓过滤和敏感信息脱敏。
- 新增分析任务与历史报告运行流快照 API，提供 lanes、nodes、edges、events、summary 等统一契约，并从任务队列、运行诊断和 AnalysisContextPack overview 构建脱敏数据流/信息流。
- Web 端为活跃任务、历史报告和大盘复盘报告补充运行流视图入口，支持查看运行摘要、拓扑节点、事件流和基础排障详情。
- 新增 AlphaSift 热点题材链路：后端提供 `/api/v1/alphasift/hotspots` 与 `/api/v1/alphasift/hotspots/{topic}` API，Web 选股页新增热点题材区域并支持发酵路线与概念股查看。

### 改进

- 个股分析新增按当日/市场复用的大盘环境摘要，普通 Pipeline 与 Agent 分析 Prompt 可读取低敏大盘背景；新增默认开启的 `DAILY_MARKET_CONTEXT_ENABLED` 配置，用户仍可显式关闭。
- 个股分析与历史/回测展示新增可选八态 `action` / `action_label` 建议动作字段，保留 `operation_advice` 自由文本和 `decision_type=buy|hold|sell` 统计口径。
- 补充 Web decision-signals typed API wrapper 与契约隔离测试，暂不接入 UI。
- 完善运行时日志上下文，补充 logger name、触发来源、市场统计与实时行情预取链路状态，便于排查调度、API、Bot 和数据源降级路径。
- 持仓管理页新增持仓账户删除入口，复用现有账户软删除接口，误建账户会从默认列表、快照、风险、录入入口和事件列表隐藏且不物理清理历史流水。
- AlphaSift 依赖锁定更新到 `d038c52c468543726fc1fd830b53c27d3f09d6da`，并为新版 last-good snapshot、日线历史、行业/概念 provider cache、hotspot 榜单、题材发酵路线、概念股详情、上次成功热点缓存与 post-analysis 元信息补齐 DSA 运行期和 Web 适配。
- AlphaSift 热点题材读取默认优先使用上次成功缓存，手动刷新才实时拉取并覆盖缓存，实时拉取失败时尽量回退旧缓存。
- AlphaSift 热点题材区域改为默认折叠，展开并选中具体题材后再读取详情；发酵路线改为带时间标记的时间线展示，概念股可点击进入首页并直接启动分析。
- AlphaSift 热点题材数据链路复用同一次东方财富板块异动快照，并从真实涨跌幅、异动次数和高频个股推导趋势分、持续分、阶段与龙头样本。
- AlphaSift 热点题材刷新在合约层返回少量或缺少关键字段时改用 DSA 东方财富板块异动直连榜单，忽略少于 3 条的本地热点缓存，并补齐板块兜底字段。
- AlphaSift 热点题材卡片改为更紧凑的多列布局，概念股列表改为独立“分析”按钮触发个股分析；详情优先合并东方财富成分股、同花顺解析和板块异动龙头兜底并按日聚合发酵时间线。
- AlphaSift 热点题材详情新增 DSA 侧 30 分钟磁盘缓存，重复点开同一题材时复用发酵时间线与概念股详情；题材事件仅展示 AlphaSift 合约时间线、同花顺摘要、已配置新闻搜索或东财板块异动等真实来源。
- AlphaSift 热点题材消息催化改为摘要展示：配置 LLM 时优先压缩为一句题材催化摘要，未配置或调用失败时回退本地短摘要。
- AlphaSift 热点题材列表新增可选 `include_details` 详情预取，Web 默认随热点列表批量带回 Top 题材发酵路线与概念股并复用前端内存缓存；新闻催化在 LLM 不可用时改为本地事件归纳。
- 改造 `main.py --webui-only` 启动行为：若 FastAPI 监听端口已被占用，启动即 fail-fast 抛出明确错误并退出。

### 修复

- 问股从历史报告进入后的追问会持续携带当前标的，切回或重载已有会话时可从历史消息恢复基础当前标的，并由后端阻断未明确切换时的错误股票工具调用、交易所片段和指标缩写误路由。
- 自选股加入和删除按等价股票代码匹配港股及大小写美股变体，避免 `00700`、`HK00700`、`00700.HK` 或 `aapl`、`AAPL` 被误判为不同标的。
- 收紧建议动作 legacy fallback：否定/回避表达、中文金融上下文、`buy or sell`、多 guard 歧义文本以及英文复合词不再误渲染成 action badge；有结构化 `action` 时回测/历史趋势等入口按界面语言显示 action 标签。
- 股票新闻与多维情报搜索在相关度排序后新增域名无关的准入过滤，剔除下载/安装包/应用评分页及成人/招嫖服务垃圾页，并在同批已有有效标的/行业候选时移除 `score=0` 背景填充项。
- 修复历史报告运行流快照在混合时区事件时间戳下返回 500 的问题。
- 修复运行流 live SSE 事件未复用快照层递归脱敏规则的问题，避免本地路径、prompt/raw response、代理头等敏感诊断字段在 refetch 前短暂暴露。
- AlphaSift 热点题材默认加载在无缓存且旧适配层缺少 `alphasift.hotspot` 模块时返回空态，不再一打开选股页就显示 AlphaSift 未就绪；手动刷新仍会提示依赖需更新。
- 为 THS 发酵路线补充列名兜底：当 `stock_board_concept_summary_ths` 返回缺列时仅跳过该来源富化，不影响热点题材详情 API 返回。
- 桌面发布打包改用冻结可执行文件运行时探针校验 `alphasift.dsa_adapter`，避免 macOS PyInstaller 将模块内嵌进可执行文件时被文件系统/zip 扫描误判为缺失。
- AlphaSift 热点题材详情展示改为优先使用后端融合后的 `route`，避免旧 `timeline` 覆盖新闻/LLM 摘要；手动刷新热点榜单时会同步绕过同题材详情缓存。

### 文档

- README 与繁中 README 快速开始入口补充视频教程链接，并将桌面客户端入口文案调整为客户端配置教程。
- 补充 `docs/alphasift-integration.md`：明确 AlphaSift 锁定 commit 来源、Hotspot 契约边界、LLM/LiteLLM 兼容语义与关闭开关下回退路径。
- 补充 #1381 运行时范围、兼容边界、官方语义依据与常规发布回滚说明。

### 测试

- 覆盖 #1381 后端 runtime 与兼容核验：`tests/test_main_schedule_mode.py`、`tests/test_pipeline_daily_market_context.py`、`tests/test_daily_market_context.py`、`tests/test_daily_market_context_guardrail.py`、`tests/test_agent_executor.py`、`tests/test_config_env_compat.py`、`tests/test_config_registry.py` 与 `apps/dsa-web/tests/system_config_i18n.test.ts`。
- 新增/更新 AlphaSift 后端回归：`python -m pytest tests/test_alphasift_api.py -q`、`python -m pytest tests/test_docker_entrypoint.py -q`、`python -m pytest tests/test_main_schedule_mode.py -q -k "start_api_server_fails_before_thread_when_port_is_busy"`。

## [3.21.0] - 2026-06-07

### 发布亮点

- feat: 新增 Web UI 中英文界面语言切换和飞书 App Bot 通知模式，提升多人部署和企业通知场景体验。
- feat: 大盘复盘报告、历史入口和个股栏继续收口到结构化数据与统一 Markdown/GFM 渲染，Web/API 人工触发入口不再被交易日 gate 短路。
- feat: AlphaSift 选股链路改为可恢复后台任务，并完善 DSA LLM runtime bridge、默认适配层预置和兼容回归。
- fix: 修复英文界面残留中文、诊断展示、运行时环境变量展示、健康检查、桌面更新路径、工作流变量读取和多处 Web 窄布局问题。

### 新功能

- WebUI 新增独立界面语言状态与中英文切换入口，覆盖主导航、首页、登录、设置页和通用控件文案；UI 语言与 `report_language` 解耦，不改写报告语言链路。
- 飞书通知新增应用机器人（App Bot）模式，支持通过 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` 配置，无需额外创建自定义机器人。
- Web 大盘复盘报告新增专用展示视图，历史入口和首页即时结果统一使用 Markdown/GFM 渲染并隐藏个股专属模块。
- 大盘复盘新增结构化 `market_review_payload`，Web、历史详情和推送统一基于结构化数据渲染，并保留 Markdown 兼容展示。
- 新增默认关闭的 AlphaSift 选股页签，通过 `ALPHASIFT_ENABLED` 明确控制，并保留 `/install` 作为显式修复路径。

### 改进

- Web/API 大盘复盘人工触发入口不再因交易日检查或相关市场休市而短路跳过；定时任务、GitHub Actions 手动运行和 CLI 默认入口仍保持原交易日 gate。
- AlphaSift Web 选股改为后台任务提交与状态轮询，新增可恢复任务状态展示，避免外部快照、行情或 LLM 变慢时浏览器长请求超时。
- AlphaSift 选股 API 与服务层收敛到 `AlphaSiftService`，endpoint 仅做路由参数接收与错误映射。
- AlphaSift 与 DSA 的运行时 LLM 兼容桥接改为调用期注入，保留 `provider/model/base_url/custom headers/fallback` 语义链路，不做持久化迁移。
- Web 首页侧栏不再单独展示大盘复盘历史集合，最新大盘复盘作为 `MARKET` 并入个股栏，按最近分析时间参与排序，并复用个股栏的选择、删除、完整报告与历史趋势查看能力。
- 多股通知报告将市场阶段收敛为总览下方单行 `市场状态`，不再在每只股票摘要下重复展示数据质量和限制详情。
- API 错误响应构造收敛到共享 helper，保持既有错误 envelope 形状并降低 endpoint 重复代码。
- WebUI 绑定公网地址或 CORS 全开放且未启用管理员认证时新增运行时 warning；仅增加可观测性，不阻断启动、不改写配置。
- 数据库初始化新增 `schema_migrations` baseline 标记表与幂等记录，用于后续 schema 演进追踪；不迁移、不清理、不改写既有业务表数据。
- #1386 P6 复用市场阶段与 AnalysisContextPack 公开摘要联动告警、持仓手动分析、历史、回测和通知展示，不新增数据库迁移。

### 修复

- Web 英文界面补齐回测、组合风险与告警规则相关文案本地化，避免英文模式下残留中文筛选器、按钮和枚举标签。
- 综合情报搜索中的机构分析与业绩预期维度改用 180 天 provider 请求窗口，避免默认短新闻窗口漏掉财报、研报等周期性财经材料。
- Web 个股栏和历史卡片在窄布局下不再让市场阶段标签遮挡股票名称。
- 问股自由文本追问不再将 TTM、PE、YOY 等金融缩写误识别为新股票代码。
- [修复] GitHub Actions 每日分析工作流读取 SearXNG 自建实例地址时支持 Variables 优先、Secrets 回退，修复仅配置 Variables 时 URL 不生效的问题。
- Web/桌面端左侧导航选中态改用 border 实现，避免蓝色竖条指示器溢出侧栏边界；侧栏展开宽度 116px -> 136px，新增 rail 紧凑模式。
- Windows 桌面端自动更新安装目录不再预先加引号，避免带空格路径在自动安装时触发“缺少快捷方式 / 找不到 Daily Stock Analysis.exe”的系统弹窗。
- Agent 分析路径生成 AnalysisContextPack overview 前复用已落库日线分析上下文，避免日线已抓取成功仍显示 `daily_bars_missing`。
- 修正大盘复盘结构化 `breadth` 的可用性判断：当市场不支持或抓取失败时不下发 `breadth`，前端展示“暂无数据”，避免误导性 0 值。
- 大盘复盘语言行为遵循全局 `report_language`，并在美股中文场景下本地化市场标签与策略蓝图，避免混入英文策略段落。
- Docker Web 设置页读取配置时在活跃 `.env` 文件缺项时回退展示启动注入的同名环境变量，并补清相关挂载边界文档。
- 报告页运行诊断会区分数据源抓取成功与进入 LLM 分析输入，相关新闻区标注为报告页补充/后续检索资讯，避免与输入数据块状态互相误读。
- `/health` 根路径健康检查现在始终返回 JSON，避免静态 Web fallback 吞掉健康探针；`/api/health` 与 `/api/v1/health` 继续保持兼容。
- `ALPHASIFT_ENABLED` 关闭时不触发 `alphasift` 运行时注入；开启后优先复用已配置的 DSA/provider 配置并注入 `LITELLM_*` 与 `LLM_*` 运行时变量。
- 补齐 openai-compatible 场景下 base URL、`extra_headers` 与 `LITELLM_FALLBACK_MODELS` 的兼容路径与回退链验证。
- 桌面/镜像打包链路保持与运行时一致的 AlphaSift 适配层预置，避免 `pip install` 作为线上修复依赖。

### 文档

- 明确 Issue #777 UI 语言切换采用仓内 `UiLanguageContext` + `uiText` 实现，持久化 key 为 `dsa.uiLanguage`，并补充对应可视化验收指引。
- 明确大盘复盘展示链路、结构化 payload、语言行为、交易日 gate 差异和回滚边界。
- 补充 LLM / LiteLLM 兼容键在 Settings 展示与校验上下文中的回退边界，说明不改写、不迁移、不清理用户现有 provider/model/base URL 持久化配置。
- 补齐 #1602 运行诊断口径修复覆盖范围，说明仅统一输入与展示口径，回滚方式为常规发布回滚。
- 明确 AnalysisContextPack P6 文档、迁移与回滚边界，并同步既有 `SAVE_CONTEXT_SNAPSHOT` 到 `.env.example`、配置注册表、Web 设置帮助和完整指南。
- 补齐 #1386 P7 盘前/盘中/盘后分析的入口、迁移、回滚和用户可见说明。
- 为 AlphaSift runtime bridge 增加官方兼容依据落点，明确 provider/model/base_url/extra_headers/fallback 与回退边界。

### 测试

- Web 方向执行 `npm run lint`、`npm run build`、相关 Vitest 和 smoke 命令；未设置 `DSA_WEB_SMOKE_PASSWORD` 时 smoke 用例按设计 skip。
- Web 测试运行时声明 Node `>=20.19.0 <27` 与 npm `>=10`，并补 localStorage 测试兜底以稳定 Vitest。
- 增补 AlphaSift runtime bridge 与打包脚本静态验证，覆盖 `LLM_CHANNELS`、`LITELLM_FALLBACK_MODELS`、`alphasift.dsa_adapter`、`--collect-all alphasift`。

### chore

- 移除随 issue / PR 验收流程误入库的截图资产，并明确一次性截图证据应保留在 PR 描述、评论、附件或 artifact 中，不作为仓库文件合入。

## [3.20.0] - 2026-06-03

### 发布亮点

- feat: 新增 AlphaSift 选股入口、自动安装与稳定适配层，支持 Web 策略执行、LLM 重排展示和默认关闭的可控启用。
- feat: 完善个股历史、自选队列、市场阶段与 AnalysisContextPack 可见性，增强 Web 报告和 API 的结构化上下文能力。
- feat: MiniMax 默认模型升级到 `MiniMax-M3`，并补齐相关价格、预设和测试覆盖。
- fix: 修复健康检查、Windows 桌面更新与首次运行编码、ETF 日线 secid、LLM base_url 校验和 Agent 日线上下文误判等稳定性问题。

### 新功能

- 新增默认关闭的 AlphaSift 选股页签，通过 `ALPHASIFT_ENABLED` 开启后经由稳定适配层读取策略并执行选股。
- Web 首页左侧栏改为个股栏，按股票去重展示，大盘复盘置顶，点击个股加载最新报告，支持按代码变体（.SZ/.SH/.SS）归一化去重合并。保留全选、批量删除和删除确认入口；新增按股票代码批量删除 API `DELETE /api/v1/history/by-code/{stock_code}`。
- 报告详情右侧栏新增自选操作入口，支持查看当前股票是否在自选队列、一键加入或移除；大盘复盘报告不显示该操作。
- 问股页面输入区上方新增自选操作按钮，用户发送包含股票代码的消息后自动显示加入自选/从自选删除入口。
- Web 报告页新增同股历史趋势抽屉入口，历史列表摘要补充趋势、摘要、模型和分析时行情字段，支持按当前股票查看历史分析并加载更多。
- AnalysisContextPack P4 低敏 overview 接入历史详情、同步分析响应、completed 任务状态和 Web 报告页，展示数据块状态、来源、缺失原因与降级摘要。
- #1386 P5 为个股分析报告新增 `dashboard.phase_decision` 盘中决策护栏，并在保存历史前按市场阶段与数据质量限制高置信盘中买卖结论。
- #1386 P4a 新增 `analysis_phase=auto|premarket|intraday|postmarket` API 参数，并在异步任务 accepted、内存 status、list、SSE 与分析 pipeline 中透传请求阶段。
- #1386 P4b Web 报告页新增最终市场阶段标签，任务面板展示请求阶段，并复用 AnalysisContextPack 低敏数据质量摘要。
- MiniMax 渠道模型列表升级：新增 `MiniMax-M3` 并作为默认，按官方 OpenAI-compatible 文档支持 1M 输入上下文（项目保守注册为 `<=512K` 价格档：context_window 512K、`max_tokens` 128K，对应 $0.6/M 输入、$2.4/M 输出，>512K 输入价格档未建模），保留 `MiniMax-M2.7` 与 `MiniMax-M2.7-highspeed`，并保留 `MiniMax-M2.5` legacy 价格条目以兼容现有用户配置的成本估算。Web 设置页 MiniMax 预设模型与价格按 M3 刷新。
- 新增 AnalysisContextPack P1 内部契约与脱敏序列化测试。
- 市场阶段低敏摘要接入历史详情、同步分析响应和 completed 任务状态的 report metadata。

### 改进

- 首次运行配置校验补充缺失 AI Key、空 STOCK_LIST、Telegram/邮件成对字段和 Webhook URL 前缀诊断。
- AlphaSift 选股入口在 Web 侧边栏中移动到“问股”下方，贴近 Agent/研究辅助工作流。
- Docker 镜像构建阶段预置默认 AlphaSift 适配层，与桌面发布包一样避免运行期额外安装。
- AlphaSift 选股改为依赖 `alphasift.dsa_adapter` 的稳定接口，Web 策略列表由 AlphaSift 动态提供，不再在前端硬编码。
- AlphaSift 选股页补充 Run ID、快照数、过滤后数量、因子和风险详情，展开候选时展示真实明细，并暂时仅开放当前支持的 A 股市场。
- Web 设置页新增 AlphaSift 选股开关卡片，可直接开启或关闭选股页签。
- 开启 AlphaSift 选股时先切换 `ALPHASIFT_ENABLED` 并检查适配层可用性，缺失时自动调用受控安装接口，不再要求用户额外点击安装。
- AlphaSift 已开启但适配层缺失时，策略列表和选股接口会串行化自动安装锁定来源，并强制重装以覆盖旧版 `alphasift` 包。
- AlphaSift 选股页合并重复的快照源 fallback 提示，并保留 AlphaSift 自身的 Tushare 优先快照源逻辑。
- AlphaSift 选股页在 LLM 重排降级时展示 warning/source error/parse error，并避免把本地因子评分误显示为 LLM 判断。
- Web 设置页不再把 `ALPHASIFT_ENABLED` 作为普通数据源配置项重复展示，该值仅作为“开启选股”按钮背后的持久化状态。
- AlphaSift 关闭时隐藏 Web 左侧“选股”导航入口，避免误导未开启用户。
- 补充 AlphaSift 选股自定义策略显示逻辑，避免未匹配预设项时误显示“均衡多因子”。
- 新增 GET /api/v1/history/stocks 端点按 code 分组返回不重复个股列表；新增 GET /api/v1/stocks/watchlist、POST /api/v1/stocks/watchlist/add、POST /api/v1/stocks/watchlist/remove 端点支持自选队列增删查。STOCK_LIST 读写保持原样，不做自动归一化；add/remove 时归一化比较判断等价代码变体。
- 新增 useWatchlist hook 统一管理自选队列前端状态，复用 SystemConfigService 的 STOCK_LIST 配置项实现持久化。
- AnalysisContextPack P5 增加数据质量评分、`fetch_failed` 状态、Prompt 数据限制区块和 Web 低敏质量展示。
- #1386 P2-full 在 AnalysisContextPack Prompt 数据限制中追加市场阶段与降级数据的交叉约束，并修正中文分析 Prompt 的阶段化行情标签。
- 通知报告默认发送路径恢复既有渠道兼容转换与分片逻辑，新增 renderer 能力仅保留为未来扩展基础。
- 关联板块缺少类型数据时改为单行展示板块名称，避免生成整列 `N/A` 的板块表格。
- 优化 Web 报告详情页信息层级，将输入数据块和运行诊断下移为主体内容后的折叠辅助信息。
- 盘中分析补齐实时行情获取时间、provider 时间、stale、fallback 与 partial/estimated 标记，供 AnalysisContextPack 映射输入数据限制。

### 修复

- Agent 分析路径生成 AnalysisContextPack overview 前复用已落库日线分析上下文，避免日线已抓取成功仍显示 `daily_bars_missing`。
- 注册 /api/v1/health 路由并加入认证豁免，修复该路径返回 404 以及开启 ADMIN_AUTH_ENABLED 后健康探针收到 401 的问题。
- Windows 本地首次运行环境检查兼容非 UTF-8 控制台输出，并将 `requirements.txt` 注释改为 ASCII 以降低默认代码页下的依赖安装失败概率。
- AlphaSift DSA 适配层默认开启 LLM 重排，后端显式请求 `use_llm=True`，选股页展示 LLM 分数、判断、覆盖率和关注项。
- AlphaSift 嵌入 DSA 时复用 DSA 已解析的 LLM 模型、渠道和密钥配置，避免 Web 已配置 LLM 但选股 LLM 重排仍因缺少 provider key 降级。
- AlphaSift 选股复用 DSA LLM 路由时过滤未声明的托管 provider 备选模型，并把已声明渠道模型补入回退链，避免残留 Gemini fallback 覆盖可用的 DSA 渠道。
- AlphaSift 默认安装来源改为锁定 commit 的受信任 GitHub 地址；桌面模式自动安装不要求管理员会话，非桌面部署要求管理员认证会话，并继续限制安装来源。
- 修复 Web 开启 AlphaSift 时先安装后写配置导致默认关闭状态无法开启的问题。
- AlphaSift 状态与安装接口不再返回 `install_spec` 明文，仅返回 `install_spec_is_default` 等非敏感状态字段。
- AlphaSift 状态探测区分可选依赖缺失与非预期异常，异常场景记录 warning 并返回非敏感诊断信息。
- 调整 AlphaSift 筛选调用兼容：`screen` 以 `max_results` 为主并支持历史 `max_output` 关键词，同时允许策略透传以对齐前端手动策略参数。
- AlphaSift Web 选股请求使用独立长超时，避免开启 LLM 重排后被通用 30 秒 API 超时提前中断。
- 桌面端打包阶段预置 AlphaSift 并收集适配层，避免发布包运行时再要求管理员自动安装。
- AlphaSift 自动安装仅在 `status` 诊断为 `missing_module` 时触发（仅模块缺失场景）；适配层可导入但运行时异常不再自动 `pip install`，而是返回 `424` 并保留诊断，避免把真实运行时故障掩盖为重装。
- 收口 Web 中文界面残留英文文案与设置页 help 缺口，回测页改为中文展示，并让 Web 设置页仅展示已注册且带说明的配置项。
- Windows 桌面端自动更新静默安装时显式复用当前安装目录，避免自定义安装目录场景下卸载旧版本文件失败。
- Windows 安装器重试旧卸载器时对 `_?=` 安装目录参数加引号，修复旧版本安装在带空格路径时返回 2 导致自动更新失败。
- Windows 桌面端自动更新传给 NSIS 的 `/D=` 目录参数在包含空格时自动加引号，避免安装位置注册表被截断。
- 加固 LLM channel base_url 校验，避免解析差异导致 SSRF 绕过。
- 修正 efinance ETF 日线 Eastmoney secid 路由，避免沪市 ETF 被按深市 quote id 查询导致日线为空。

### 文档

- 明确 AlphaSift 与 LiteLLM 兼容边界：仅桥接 DSA 已声明 provider/model/base URL 为调用期注入，不对 `.env` 做 provider/model 路由迁移；回退方式为关闭 AlphaSift 并恢复原有 `LITELLM_*`/`LLM_*` 配置。
- 明确 AlphaSift 仅复用 DSA 现有 LLM/LiteLLM 配置语义，不新增 `LITELLM_MODEL`、`OPENAI_MODEL`、`OPENAI_BASE_URL`、`LLM_TIMEOUT_SEC` 等模型语义迁移；失败提示与回退路径统一沿用既有系统配置链路，仅影响 AlphaSift 选股能力本身。
- 明确 AlphaSift 自动安装来源锁定、`missing_module` 与运行时异常行为边界，以及 LLM/provider/base URL 与自定义通道回退路径，便于问题溯源与回滚到原有 LLM 配置。
- 明确同股历史趋势新增模型字段为历史快照展示元数据，不影响运行时 LLM Provider/Model/Base URL 路由与配置迁移清理；回退方式为按常规发布回滚本变更。
- 明确 #1311 的兼容性边界：渲染层仅消费分析结果 `model_used` 展示字段，未改动 `wechat/slack/feishu/telegram` sender 发送链路，不触发 provider/model/base_url 兼容迁移。
- 明确 AlphaSift 锁定 commit 的 `alphasift.dsa_adapter` 契约依据，以及当前 DSA API/Web 调用结构的兼容边界。
- 明确 Settings 页面对 LLM 配置仅做展示分组与字段归并，不改写或触发 LLM 迁移/回退路径；兼容现有 `LLM` 配置保存与回退语义。
- 新增 AnalysisContextPack P0 上下文盘点。
- 补齐告警中心 P8 文档与配置收口说明，明确 legacy JSON、高级规则、Web/API、Docker、GitHub Actions 与 Desktop 边界。

### 测试

- 同步更新 `llmProviderTemplates`、LiteLLM fallback pricing 与 MiniMax 预设相关单测，断言新默认模型。
- 补充 ETF 日线数据源路由、输入变体、fallback 与 MA 字段回归覆盖。

### chore

- 新增通知报告渠道能力画像、PreparedMessage 与结构感知 Markdown 分片基础设施，为 #1311 全渠道渲染适配打底。
- 预置企业微信、飞书、Telegram、钉钉、Slack 平台 renderer 元数据，暂不改变默认推送报告入口和可见版式。

## [3.19.0] - 2026-05-29

### 新功能

- 落地 #1391 Phase 1 运行诊断最小链路：任务/SSE 追加 trace_id，并记录日线与实时行情 ProviderRun 快照。
- 告警中心新增 P7 大盘红绿灯结构化规则，支持 `market_light_status` 与 `market_light_score_drop` 并复用现有 worker、触发历史、通知和冷却链路。
- 落地 #1391 Phase 2 运行诊断摘要：生成用户可读 RunDiagnosticSummary，提供历史报告诊断 API 与脱敏复制文本。
- 落地 #1391 Phase 3 运行诊断可见性：报告详情和任务面板默认折叠展示运行状态、trace 与可复制排障信息；后端通过 `api/v1/history/{record_id}/diagnostics` 与 `context_snapshot.diagnostics` 提供历史链路回填。
- 新增 AnalysisContextPack P1 内部契约与脱敏序列化测试。
- 新增 AnalysisContextPack P2 builder，从普通分析 pipeline 已有 artifacts 组装内部上下文包。
- 问股新增默认关闭的可见对话上下文压缩，支持 Web 开关、Agent 高级 preset、滚动摘要和最近轮次原文保护，降低长会话 token 消耗。
- 股票自动补全索引默认支持从 GitHub main 远程刷新并缓存到本地，Web/CLI 分析入口失败时自动降级到内置索引，降低摘帽和更名后旧简称污染分析的概率。
- 普通分析与 Agent 运行时 Prompt 接入 AnalysisContextPack 低敏摘要，保持 history/API/Web 输出兼容。

### 改进

- `scripts/fetch_tushare_stock_list.py` 可对 A 股中带 `XD`/`XR`/`DR`/`N`/`C` 前缀的名称进行回填修正，供自动补全刷新流程默认使用。
- Web 路由页面改为按需加载，降低首包体积并增加路由加载失败恢复提示。
- Web 完整报告 Markdown 抽屉改为按需加载。
- 新增市场阶段推断基线并明确盘前、盘中、午休、临近收盘、盘后和非交易日语义。
- 新增运行态市场阶段上下文构造与降级测试。
- 设置页配置帮助阶段性补齐 Web 设置页实际展示/可配置字段的中英双语文案，覆盖 Agent、回测、报告、通知路由、系统运行时、AI legacy、数据源和通知高级配置。
- P2-min：LLM Prompt 注入市场阶段上下文。

### 修复

- 股票自动补全索引生成缺少 `pypinyin` 时改为直接失败，避免写出缺失拼音字段的降级索引。
- 归一腾讯实时行情成交量为股口径，避免量能变化倍数被放大并误导分析报告。
- Docker 默认部署移除 `.env` 单文件挂载，避免 WebUI 保存配置时因 `os.replace` 更新挂载点触发 `Device or resource busy`。
- 收敛 #1391 Phase 0 A 股代码归属边界：补齐 `SH`/`SZ` 前缀场景的归属一致性，明确 `data_provider/baostock_fetcher.py`、`data_provider/pytdx_fetcher.py`、`data_provider/tushare_fetcher.py` 的本轮修复范围。
- 修复 `STOCK_LIST` 使用裸 A 股代码时 Baostock 等数据源 fallback 的内部格式转换，保持用户配置继续使用 6 位股票编号。
- Windows 桌面端自动更新在用户确认重启安装后改为静默执行安装器，并在停止内置后端后清理进程引用，降低安装器提示“每日股票分析无法关闭”的概率。
- macOS 桌面端将运行时配置迁移到用户数据目录，并在旧 `.app` 包内文件仍可访问时迁移 `.env`、数据库和日志，避免后续替换升级后重新配置。
- 恢复 Agent/历史兼容快照中的关联板块与板块联动字段提取，修复新版首页报告缺少“板块联动”的回归问题。
- 修正 Web 设置帮助中 legacy 告警 JSON 字段名与静默时段投递语义说明。
- 修复 Web 中文设置页在数据源、通知、系统与 Agent 区域的配置标题、说明和关键下拉选项漏翻问题。
- 修复问股会话切换和首页任务重连后可能残留 Agent/分析任务进行中状态的问题。
- 问股 single-agent 新增 provider-aware trace 分轨，跨轮保留 DeepSeek V4 thinking + tool-call 的 `reasoning_content` 与工具协议材料。
- 为 Akshare 新浪/腾讯 A 股历史兜底接口增加调用级超时，并补齐 Tushare `605xxx` 沪市代码路由回归测试，避免定时分析因数据源无响应而挂起。
- 将 `exchange-calendars` 依赖下限提升到 `4.13.0`，避免 pandas 3 环境导入交易日历时因 Timedelta 单位 `T` 失效导致分析失败。
- 交互式命令（钉钉会话、飞书会话、Telegram）触发的分析结果只回到来源会话，不再同时广播到静态通知渠道。
- 适配 Longbridge OAuth 2.0 认证与 token 缓存恢复，避免新后台无 Legacy Access Token 时长桥数据源被误判为未配置。
- Longbridge OAuth 路径在当前 SDK 不支持 `OAuthBuilder` / `Config.from_oauth` 时明确日志降级，避免 Linux/Docker 仅可安装旧 SDK 时构建失败。
- 兼容 YFinance 日线返回未命名日期索引的场景，避免标准化后缺少 `date` 列导致美股日线 fallback 中断。

### 文档

- 新增 #1391 Phase 0 运行诊断契约文档，明确 trace_id、诊断摘要、关键链路范围与脱敏/fail-open/retention 边界。
- 补齐告警中心 P8 文档与配置收口说明，明确 legacy JSON、高级规则、Web/API、Docker、GitHub Actions 与 Desktop 边界。
- 说明本次桌面修复仅覆盖 Windows NSIS 更新安装链路与后端进程生命周期清理；未改动设置项保存/模型运行时清理语义。移除此前误入的 `docker/Dockerfile` `npm registry` 变更，恢复部署构建与更新修复的职责隔离。
- 新增 AnalysisContextPack P0 上下文盘点，明确字段质量状态、现有状态映射和首版 pack 边界。
- 明确 #1391 Phase 2 的结构化检测告警为非配置迁移信号：`agent_max_steps`/`agent_orchestrator_timeout_s` 非法值会 fallback 至默认并产生日志告警，新增诊断链路仅新增 `context_snapshot`/`RunDiagnosticSummary` 读写字段，不改写 `litellm_model`、`agent_litellm_model`、`openai_base_url`、LLM channel 路由或配置迁移语义。
- 补充 #1391 Phase 3 兼容性说明：记录后端诊断持久化、历史查询与通知回写链路变更边界与回滚策略，并补齐后端门禁级验证要求。

### 测试

- 收敛 #1391 Phase 3 后端/API 与 Web 回归检查：`./scripts/ci_gate.sh`、`test_pipeline_market_phase_context.py`、`test_analysis_api_contract.py`、`test_analysis_history.py`、`npm run lint`、`npm run build`。
- 执行 `python -c "import exchange_calendars as xcals; xcals.get_calendar('XSHG'); print('ok')"` 通过验证，以覆盖导入与交易日历初始化兼容性。

## [3.18.0] - 2026-05-21

### 发布亮点

- feat: 告警中心扩展到 P2-P6，补齐后台评估、真实通知结果、业务冷却、技术指标规则，以及自选股 / 持仓 / 账户联动规则。
- feat: 个股分析支持策略选择，新增热点题材、事件驱动、成长质量和预期重估策略，并为 HK/US 报告补充基本面、财务摘要、股东回报和关联板块。
- feat: 新增 Finnhub / AlphaVantage 美股数据源适配器，扩展美股日线 failover 链，提升美股行情获取韧性。
- fix: 修复桌面端发布打包、分析状态接口、AlphaVantage 涨跌幅、持仓实时估值、告警历史去重、数据库冷启动和 fallback pricing 注册等稳定性问题。

### What's Changed

- feat: Add alert-center P2-P6, Web strategy selection, HK/US fundamental context, static-report financial sections, and Finnhub / AlphaVantage US-market fallback.
- improve: Refine LiteLLM parameter recovery, yfinance currency/dividend handling, RSI calculation, market-review presentation, stock-news relevance ranking, and report table rendering.
- fix: Harden desktop packaging/update assets, completed analysis-status responses, AlphaVantage pct_chg routing, portfolio realtime snapshots, alert trigger dedupe, DatabaseManager cold start, and fallback pricing registration.
- docs/tests: Add beginner setup and settings-help docs, document compatibility/rollback boundaries, and extend regression coverage for API, alert, packaging, and release paths.

## [3.17.1] - 2026-05-16

### 发布亮点

- fix: 桌面端 Windows / macOS 打包脚本显式关闭 electron-builder 自动发布，避免 tag 构建时因缺少 `GH_TOKEN` 在本地打包完成后失败；Release workflow 继续负责上传和发布产物。

### What's Changed

- fix: Add `--publish never` to the Windows and macOS Electron packaging scripts so tag builds only create local artifacts and GitHub Actions handles release upload/publish.

## [3.17.0] - 2026-05-16

### 发布亮点

- feat: 新增 Alert API MVP，支持告警规则 CRUD、启停、一次性测试以及触发/通知结果查询，首版覆盖 `price_cross` / `price_change_percent` / `volume_spike` 并保持 legacy 配置兼容。
- feat: 通知网关新增 ntfy 与 Gotify 一等渠道，并补齐通知降噪、静态渠道隔离、诊断、Web 测试和 GitHub Actions env 对照校验。
- feat: Windows 桌面安装版接入自动更新安装链路，支持后台下载、确认重启安装、运行时文件备份/恢复和发布产物元数据校验。
- improve: 大盘复盘新增概念排行、人气股、涨停池等底层数据源，支持指数涨跌颜色语义配置，并将复盘结果写入历史记录。
- improve: Web 设置页支持 `.env` 配置备份导入/导出和通知/Agent 区域局部错误兜底；报告新增 `REPORT_SHOW_LLM_MODEL` 开关控制模型信息展示。
- improve: Docker 启动入口自动修复挂载目录权限并在日志目录不可写时降级到控制台，减少普通部署的手动修复步骤。
- fix: 数据源缺凭据或连接失败时更温和降级，Longbridge / Pytdx 加入冷却，资金流缺失时避免输出高置信买入结论。
- fix: 分析与报告链路兼容 OpenAI-compatible `content_blocks` 响应，归一策略价格字段，并修复大盘复盘滚动和历史记录丢失问题。
- docs: 补齐通知、告警中心、桌面打包、README / 指南和 PR title 治理说明，明确多处配置兼容边界与回滚路径。
- test: 增加 Alert API、通知降噪/路由、Docker entrypoint、数据源预取、桌面更新链路和分析历史等回归覆盖。

### What's Changed

- feat: Add an Alert API MVP with rule CRUD, enable/disable, one-shot testing, trigger history, notification results, and legacy config compatibility.
- feat: Promote ntfy and Gotify to first-class notification channels with Web tests, routing, Actions integration, diagnostics, and noise control.
- feat: Add the Windows desktop auto-update install flow with runtime state backup/restore and release artifact metadata verification.
- improve: Extend market review data sources, add configurable index color semantics, and persist market review results into analysis history.
- improve: Add Web `.env` backup import/export, local settings panel error boundaries, and a report model visibility toggle.
- improve: Harden Docker startup by repairing mounted directory permissions and falling back to console logging when mounted logs are not writable.
- fix: Cool down unavailable optional fetchers, reduce noisy Longbridge/Pytdx retries, and downgrade buy advice when capital flow data is missing.
- fix: Handle OpenAI-compatible `content_blocks`, normalize strategy price fields, and recover market review scrolling/history behavior.
- docs/tests: Update notification, alert, desktop packaging, README/guide, and governance docs; add focused regression coverage for the new release paths.

## [3.16.0] - 2026-05-10

### 发布亮点

- feat: Web 首页新增“大盘复盘”触发入口、任务轮询与完成后报告直出；首次启动配置状态可提示缺口并引导到系统设置。
- feat: 新增通知路由策略，支持按 report、alert、system_error 将通知收窄到指定渠道；Web 设置页支持通知渠道一键测试。
- feat: 系统设置页新增配置项帮助入口与多语言帮助文案基础设施，首批覆盖自选股、LLM 主模型、LLM 渠道、飞书 Webhook 与 WebUI 监听地址。
- improve: 大盘复盘 API、CLI、Bot 共用 `build_market_review_runtime` 装配路径，补齐 `litellm_model` / `llm_model_list` 与 legacy key 回退说明。
- improve: 个股报告操作建议结合支撑/压力、量能、筹码与主力资金流校准，减少买入/卖出剧烈切换，并补强 Agent 决策兜底。
- improve: Docker 镜像支持非 root 用户运行，LiteLLM 依赖约束放宽到后续安全 1.x 修复版本。
- fix: 修正 LLM 渠道测试中 `Model disabled`、provider blocked 等错误分类，避免被误报为网络异常。
- fix: 港股日线跳过不支持港股的内置历史数据源；北交所 `BJ` 前缀与 `.BJ` 后缀代码校验保持一致。
- fix: Web 大盘复盘按钮可观测性、Windows fallback 锁进程探测和催化线索展示更稳健。
- docs: 新增文档中心与配置帮助维护说明，清理 README、完整指南与配置指南中的临时 PR/文档同步说明。

### What's Changed

- feat: Add a Web home market-review trigger with task polling and inline report display; setup status now points users to missing configuration.
- feat: Add notification routing by report, alert, and system_error; add one-click notification channel testing in Web settings.
- feat: Add settings field help infrastructure with multilingual help text for the first batch of core configuration fields.
- improve: Share `build_market_review_runtime` across API, CLI, and Bot market review paths; document `litellm_model` / `llm_model_list` and legacy key fallback behavior.
- improve: Calibrate stock advice with support/resistance, volume, chips, and main-force capital flow; strengthen Agent decision fallback behavior.
- improve: Run Docker images as a non-root user and relax LiteLLM constraints to allow safe future 1.x fixes.
- fix: Classify `Model disabled`, provider blocked, and related LLM channel test errors more accurately instead of reporting them as generic network failures.
- fix: Avoid unsupported built-in historical providers for Hong Kong daily data; align Beijing Stock Exchange `BJ` prefix and `.BJ` suffix validation.
- fix: Improve Web market-review observability, Windows fallback lock probing, and market catalyst snippet rendering.
- docs: Add the documentation index and settings-help maintenance guide; remove temporary PR/doc-sync notes from README and user-facing guides.

## [3.15.0] - 2026-05-05

### 发布亮点

- LLM 渠道配置体验继续升级：新增 Anspire OpenAI-compatible 网关接入，并补齐常用服务商预设、官方来源、能力标签、配置注意事项和 GitHub Actions 显式映射。
- Web LLM 配置检测更可诊断：细分错误 reason，并支持用户显式触发 JSON、tools、vision、stream 运行时 smoke。
- LLM 运行时配置清理更稳健：只清理托管 provider 的失效运行时选择，并保留 `cohere/*`、`google/*`、`xai/*` 等直连 provider 兼容语义。
- 通知与 Bot 状态可观测性增强：自定义 Webhook 支持 JSON body 模板，Bot `/status` 展示更完整的 LLM、Agent 与通知渠道状态。
- 大盘复盘、实时告警、Agent weak 兜底和持仓估值继续补强，降低默认值覆盖、缺价污染和配置排障成本。

### 新功能

- 支持 `ANSPIRE_API_KEYS` 默认接入 Anspire OpenAI-compatible 大模型网关，并在 LLM 渠道编辑器补充 Anspire Open 预设。
- 自定义 Webhook 支持 `CUSTOM_WEBHOOK_BODY_TEMPLATE` JSON body 模板，便于适配 AstrBot、NapCat 和自建推送服务。
- 大盘复盘结构化区块新增大盘红绿灯结论，基于盘面温度输出 green/yellow/red、核心原因和操作建议。
- EventMonitor 支持 `price_change_percent` 涨跌幅阈值规则，可按上涨或下跌方向触发实时告警。
- Web LLM 渠道编辑器新增常用服务商配置模板与预设，覆盖 MiniMax、火山方舟、OpenAI、Claude、Gemini、Kimi、Qwen、GLM、豆包等入口。

### 改进

- Web LLM 配置检测补充细分错误分类，并新增显式触发的 JSON/tools/vision/stream 运行时 smoke；默认测试和保存流程不变，检测结果仅作为当前配置的一次 best-effort 诊断。
- Bot `/status` 展示统一 LLM 主模型、Agent 模型、渠道模式、YAML 配置和更多通知渠道状态。
- Web LLM 渠道编辑器展示 provider 能力标签、官方来源链接和配置注意事项提示；这些标签仅用于配置参考，不代表运行时能力已验证通过。
- 抽出 Web LLM provider preset 单一模板数据源，保持现有配置保存语义不变。
- 补齐 LLM provider channel 在 GitHub Actions 中的显式映射，并同步 `.env` 示例与配置文档。

### 修复

- Agent weak 完整性兜底在模型缺少评分、趋势、操作建议或 dashboard 关键块时优先保留本地趋势分析结果，并只补齐真正缺失的仪表盘字段，避免首页评分被默认 50 覆盖。
- 统一持仓快照输出现价、市值、浮盈亏、收益率与价格元信息，避免缺价或 stale 价格污染持仓估值。
- LLM 渠道测试补充结构化诊断与设置页排障提示，便于定位 provider、模型、Base URL 和鉴权配置问题。
- 明确 runtime 清理兼容边界：仅对托管 provider（`gemini`、`vertex_ai`、`anthropic`、`openai`、`deepseek`）触发保存前失效值清理，`cohere/*`、`google/*`、`xai/*` 直连值按 legacy 兼容路径保留，不做无提示迁移或覆写。
- 将 MiniMax 预设调整为官方 OpenAI-compatible Base URL 和当前模型示例，并补充 MiniMax、火山方舟、LiteLLM 兼容来源与回退说明。
- 移除截图识别对 Gemini 3 Vision 模型的过时降级逻辑，默认推断改用当前 Gemini 模型配置。

### 文档

- 完善 LLM provider 配置文档，补充配置方式选择、Actions 变量对照、运行时检测边界、错误 reason 排障和回滚路径（#1180）。
- 补充 LLM 渠道编辑器的官方来源、依赖兼容窗口、保存时的运行时模型清理规则，以及旧配置回退路径说明。
- 为 `cohere/*`、`google/*`、`xai/*` 直连语义补充官方 provider/model 说明、`litellm>=1.80.10,<1.82.7` 兼容依据引用，并明确示例模型名仅为配置保留行为说明而非可用性背书。
- 明确 `price_change_percent` 事件告警仅为配置与运行时规则扩展，未变更模型/provider/base URL/LiteLLM 兼容语义；回退路径为关闭/移除 Event Monitor 配置。
- 同步 README、DEPLOY、full-guide、Anspire、AIHubMix 与 SerpAPI 相关说明，统一外链、配置口径和评审一致性说明。

### 测试

- 补齐 AI 配置页与 `task_queue` 的 LLM 运行时清理/同步回归证据：恢复渠道模型时保留 fallback、编辑模型列表期间不静默清空运行时选择，渠道无可用模型时清理失效 runtime 引用，并覆盖 legacy key 与 `cohere/*`、`google/*`、`xai/*` 直连 provider 保留语义。
- 覆盖 Web LLM 配置检测的细分错误分类，以及 JSON、tools、vision、stream 运行时 smoke 的显式触发路径。

## [3.14.2] - 2026-04-30

### 发布亮点

- 大盘复盘扩展到港股，并让 Bot `/market` 与 CLI/调度入口使用一致的交易日过滤语义。
- 问股与 Agent 链路增强配置缺失、决策 fallback 和多策略选择体验。
- LLM 与分析报告链路提升稳定性：非法 JSON 响应会继续尝试备用模型，LiteLLM DEBUG 日志默认降噪。
- 新增只读首次启动配置状态接口，为后续配置向导和 smoke run 奠定基础。

### 新功能

- 大盘复盘支持港股市场：`MARKET_REVIEW_REGION` 新增 `hk` 选项；`both` 扩展为 A股+港股+美股，并新增港股指数（HSI/HSTECH/HSCEI）复盘链路。
- 新增只读首次启动配置状态接口 `GET /api/v1/system/config/setup/status`，用于识别 LLM、Agent、自选股、通知和本地存储配置缺口；该接口不会重载运行时、写入 `.env` 或创建数据库文件。

### 改进

- 问股页面支持组合选择多个 Agent 策略。

### 修复

- Bot `/market` 命令复用 `get_open_markets_today()` / `compute_effective_region()` 做交易日过滤：结果作为 `override_region` 透传给 `run_market_review`；若结果为空字符串则跳过复盘并推送“今日相关市场休市”，与 CLI/调度入口行为一致。
- 问股 Agent 在未配置可用 LLM 时保留后端真实错误原因并维持 `done.success=false` 失败语义，避免前端把配置缺失误当成成功回答。
- Agent 模式未生成有效决策仪表盘时保留本地趋势分析的评分、趋势和操作建议，并将强买/强卖 fallback 归一到兼容的 `buy`/`sell` 决策类型，避免首页结果被 `50 / 观望 / 未知` 缺省值覆盖。
- 持仓快照现价缺失时不再静默回退为持仓成本；当天快照优先使用历史收盘价，仅在缺失时使用实时价 fallback，缺价持仓不再污染市值与未实现盈亏汇总，并为持仓明细返回价格来源、日期、stale 与缺价状态。
- 分析 Prompt 在注入 `trend_analysis` 前按最终 `trend_status` / `ma_alignment` 清洗互斥理由：空头结构移除看多理由、多头结构移除空头结构风险，并在事件/技术冲突与异常放量（>10 倍）时强制提示“事件先行、技术待确认”与量能降权。
- LLM 返回非 JSON 响应时同样触发备用模型切换：主模型成功返回但无法解析 JSON 时，不再立即降级为纯文本 fallback，而是依次尝试 `LITELLM_FALLBACK_MODELS` 中的备用模型；所有模型均无法返回合法 JSON 时，再降级为文本 fallback。
- LiteLLM 内部 DEBUG 日志默认压低到 WARNING，避免流式生成时 token 级日志污染 `stock_analysis_debug_*.log`；如需排查 LiteLLM 内部细节，可临时设置 `LITELLM_LOG_LEVEL=DEBUG`（Fixes #1156）。

### 文档

- 补充 LLM 配置指南与 FAQ，明确问股 Agent 对 `LITELLM_CONFIG` / `LLM_CHANNELS` / legacy `GEMINI_*` `OPENAI_*` `ANTHROPIC_*` 的兼容优先级、回退路径与“不静默迁移旧配置”的结论。

### 测试

- 新增 `tests/test_bot_market_command.py`，覆盖 `MARKET_REVIEW_REGION=both` + open markets `{"cn","us"}` / `{"cn","hk"}` 的 `override_region` 透传断言，并覆盖全市场休市跳过与关闭交易日检查路径；新增 `tests/test_yfinance_hk_indices.py` 覆盖港股指数符号映射与部分/全部失败降级路径。
- 补齐 `task_queue` 轻量导入 stub 的股票代码规范化函数，恢复 `tests/test_task_queue_config_sync.py` 收集与运行。

## [3.14.1] - 2026-04-26
- [测试] 修正大盘复盘 prompt 测试对“明日交易计划”标题的断言，并同步桌面端版本号，恢复发布 gate。

## [3.14.0] - 2026-04-26

### 发布亮点

- 📊 **大盘复盘升级为盘后工作台式结构** — A 股复盘固定输出盘面温度、指数明细、板块 Top 表、新闻催化、明日交易计划和风险提示，减少纯文字复盘的重复与空泛。
- 🖥️ **桌面端新增 GitHub Release 更新提醒** — Windows/macOS 桌面端启动后自动检测新版本，也可从设置页手动检查并跳转下载页。
- 🤖 **Pipeline Agent 数据加载大幅降噪** — K 线工具改为 DB-first 并预热 240 天历史数据，避免同一只股票重复 HTTP 请求。
- 🐳 **Docker 发布链路整理** — 发布工作流收敛为正式发布与手动补发两条路径，官方 Docker Hub 镜像名统一为 `zhulinsen/daily_stock_analysis`。
- 🔧 **LLM 渠道与 DeepSeek V4 配置补强** — GitHub Actions 定时分析补齐多渠道变量透传，DeepSeek 官方渠道预设与示例同步到 V4。
- 🧩 **桌面端静态资源一致性校验** — 打包链路和运行时都能更早发现静态资源错配，降低 Release 包白屏排查成本。

### 新功能

- 🏠 **Web 首页历史报告区新增重新分析入口** — 支持基于原始 prompt 重做同一只股票同日期的分析。
- 🖥️ **Windows/macOS 桌面端新增 GitHub Release 更新提醒** — 启动后自动检测新版本，并支持从设置页手动检查后跳转下载页。

### 改进

- 📊 **A 股大盘复盘报告改为结构化盘后工作台版式** — 固定输出盘面温度、指数明细、板块 Top 表、新闻催化和明日交易计划。
- 🐳 **Docker 发布工作流收敛** — 更清晰地区分正式发布与手动补发链路，并统一官方 Docker Hub 镜像名为 `zhulinsen/daily_stock_analysis`。
- 🤖 **Agent 日线工具优先复用本地缓存** — 同时持久化新获取的日线与新闻情报，减少重复数据源调用。

### 修复

- 🤖 **Pipeline Agent K 线工具 DB-first 加载** — `get_daily_history` / `analyze_trend` / `calculate_ma` / `get_volume_analysis` / `analyze_pattern` 改为优先读取本地 DB，消除同一只股票 9x5=45 次重复 HTTP 请求（Fixes #1066）。
- 🤖 **Pipeline Agent 执行前按需预热 240 天 K 线历史到 DB** — 正常情况下 K 线工具调用无需重复网络请求。
- 🕒 **冻结 `target_date` 并通过 ContextVar 透传到 Pipeline Agent K 线工具线程** — 消除跨收盘边界时间漂移。
- 🪟 **Windows 桌面端后端日志转抄编码修复** — 转抄 stdout/stderr 时优先使用 UTF-8，并兼容本地代码页回退，避免中文日志乱码。
- ⚙️ **GitHub Actions 每日分析工作流补齐 LLM 渠道变量透传** — 支持 `LLM_CHANNELS`、多 Key 与常用 `LLM_<NAME>_*`，避免本地可用的多模型配置在云端定时任务中失效（Fixes #1063, #872）。
- 📈 **历史报告详情接口修正 `change_pct` 取值** — 使用 `is None` 判断避免把 0.0（平盘）当作缺失值丢弃，移除错误的 `change_60d` 兜底，并在缺失时回退到原始实时行情字段（Fixes #1084）。
- 🔧 **DeepSeek 官方渠道预设与示例配置同步到 V4** — 保留 legacy `deepseek-chat` 默认值并增加废弃提示，同时修正模型发现后旧运行时选择导致保存失败的问题（Fixes #1108, #1109）。
- 🧩 **桌面端打包链路新增静态资源一致性检查** — `scripts/check_static_assets.py` 会在源 `static/` 与 PyInstaller 产物中校验 `index.html` 引用的资源是否真实存在，运行时也会在错配时写入明确日志，避免重现 Release 包打开后白屏（Refs #1064 / #1065 / #1050）。
- 🧩 **后端 `/assets/*` 改为显式路由托管** — 资源缺失时返回与请求扩展名匹配的 `text/javascript` / `text/css` 404，减少默认 JSON 错误响应带来的排查误导（Refs #1064）。
- 🌙 **`kimi-k2.6` 自动使用固定温度** — 主分析、大盘复盘和 Agent 调用该模型时自动使用 `temperature=1.0`，避免模型拒绝默认温度请求（Fixes #1102）。

### 文档

- 🐳 **补充官方 Docker 镜像使用说明** — 增加镜像拉取、`docker run` 用法与 `.env` / 数据目录映射说明，不再只覆盖 Compose 部署路径。
- 📨 **修正飞书自定义机器人 Webhook 示例** — `feishu_sender.py` 中的示例改为 interactive card JSON，并补充飞书自动化 Webhook 触发器配置教程。
- 📚 **优化根 README 结构** — 保留首页级功能特性、技术栈、快速开始、推送效果、Web、Agent、赞助商和新闻源入口，将细配置、交易纪律和基本面语义收口到完整指南，并将 Docker 徽章指向官方镜像页。
- 🌐 **同步英文与繁中 README 的精简入口结构** — 同时补齐完整指南中的 LLM 用量 API 与持仓管理说明。
- 🤝 **调整 AI 协作与 PR 模板中的 README 维护规则** — 明确 README 非必要不更新，细节优先进入专题文档。

### 测试

- 🧪 **稳定市场复盘相关测试的 LiteLLM stub 行为** — 避免本机安装的 LiteLLM 在测试收集顺序变化时影响市场复盘单元测试。
- 🧪 **pytest 默认跳过前端依赖目录** — 本地存在 `apps/dsa-web/node_modules` 时不再被后端测试递归扫描，避免发布前 gate 被无关目录拖慢。

## [3.13.0] - 2026-04-21

### 发布亮点

- 🌉 **长桥 OpenAPI 数据源接入** — 美股/港股行情优先使用 Longbridge，YFinance / AkShare 自动兜底；未配置时行为不变。
- 📈 **Tushare 港股全链路扩展** — 港股日线通过 `hk_daily` 获取；筹码分布对港股返回 `None`；换算单位跟随港股口径，不再套用 A 股手/千元规则。
- 🔍 **Anspire Search 语义搜索接入** — 配置 `ANSPIRE_*` 后即可使用 Anspire Search 获取实时行情及资讯，未配置时完全透明。
- 🚀 **普通分析链路支持 LLM 流式生成** — 首页任务 SSE 新增 `task_progress` 事件，进度更细化；不支持流式的 provider 自动回退到非流式调用。
- 🤖 **Web 渠道编辑器支持按需拉取可用模型列表** — `/v1/models` 统一模型发现入口，多选写回 `LLM_{CHANNEL}_MODELS`，拉取失败时保留手动输入降级。
- 🛡️ **Agent 稳定性与预算护栏全面补强** — `AGENT_MAX_STEPS` 语义统一、技能降级不中断管线、SSE 异常透传、技能加载 warning 日志补齐。
- 🛠️ **SQLite 写入链路原子化** — 批量原子 upsert + WAL + `busy_timeout` + 有限写入重试，显著降低批量分析并发锁竞争。

### 新功能

- 🌉 **集成 Longbridge OpenAPI 作为美股/港股可选数据源**（fixes #981）— 配置 `LONGBRIDGE_*` 后优先使用长桥获取日线与实时行情，YFinance / AkShare 兜底；未配置时行为与此前一致。联调使用 `tests/longbridge_live_smoke.py`（手动脚本，不参与 pytest 收集）。
- 📈 **Tushare 支持港股日线查询** — 配置 Tushare 凭证后调用 `hk_daily` 接口获取港股数据；权限不足时抛出异常，与原流程一致。
- 🔍 **集成 Anspire Search 可选语义搜索后端** — 配置 `ANSPIRE_*` 可使用 Anspire Search 获取实时行情及新闻资讯；未配置时行为与此前一致。联调使用 `tests/test_anspire_search.py`（手动脚本）。
- 🚀 **普通分析链路支持 LiteLLM 流式生成与更细任务进度** — 股票分析在 LLM 阶段优先尝试 `stream=True` 并在服务端累积 chunk，首页任务 SSE 新增 `task_progress` 事件与更细的 `message/progress` 更新；仅在最终 JSON 解析成功后持久化历史报告；不支持流式的 provider 自动回退到非流式调用。
- 🤖 **Web AI 模型配置支持按渠道获取可用模型列表** — 渠道编辑器支持调用 `/v1/models` 拉取可用模型，并以多选方式写回 `LLM_{CHANNEL}_MODELS`；拉取失败时保留手动输入作为降级路径。

### 改进

- 🔎 **SerpAPI 正文补抓范围收敛** — 自然搜索结果不再逐条同步抓取网页正文；仅对极少数高位且摘要不足的结果做延迟补抓，优先复用 SerpAPI 已返回的结构化摘要，降低搜索链路尾延迟与慢站点放大风险。
- 🤖 **LLM 接入体验简化** — 面向用户的 AI 模型接入文案统一为"主模型 / Agent 主模型 / 备选模型 / 模型渠道"，不再把 LiteLLM 当作普通用户必学概念，现有 `LITELLM_*` / `LLM_CHANNELS` 配置键保持兼容。
- 🧠 **IntelAgent 新增公司公告搜索与主力资金流工具** — 增加上交所/深交所/cninfo 公告搜索维度与 `get_capital_flow` 工具，修复 Agent 模式下公告和资金流数据经常缺失的问题。
- 📦 **后端股票名称解析优先复用 `stocks.index.json`** — 懒加载缓存前端静态索引，纯后端/缺失静态资源场景静默降级回 `STOCK_NAME_MAP` 与原有数据源回退链路。
- 📊 **TushareFetcher 港股单位适配** — `get_chip_distribution` 对港股直接返回 `None`（港股暂不支持筹码分布）；`_normalize_data` 对港股（`hk_daily`）不再做 A 股手→股、千元→元的缩放，与 Tushare 港股字段语义一致。
- ⏱️ **Agent 超步数错误增加 `AGENT_MAX_STEPS` 调整提示** — 帮助用户自助排查步数限制问题。
- ⚙️ **GitHub Actions 分析任务超时支持 `vars` 配置** — `daily_analysis.yml` 任务超时从 repository variables 读取，无需修改代码即可调整运行超时上限（fixes #1014）。

### 修复

- 📣 **大盘复盘链路接入 `REPORT_LANGUAGE`** — `REPORT_LANGUAGE=en` 时，A 股/合并复盘的 Prompt、章节标题、模板兜底文案与通知包装标题统一输出英文，避免英文正文搭配中文标题的混排问题。
- 📈 **EfinanceFetcher 指数开盘价映射兼容**（fixes #1043）— `get_main_indices()` 的开盘价映射改为兼容 `今开 → 开盘 → open`，修复部分 efinance 版本下指数开盘价被读成缺失值的问题。
- 🤖 **AGENT_MAX_STEPS 语义统一**（fixes #1026）— 在 orchestrator 多 Agent 模式下明确为"各子 Agent 步数上限而非硬覆盖"；TechnicalAgent 等高默认值 Agent 会被封顶，低默认值 Agent 保持原值；用户主动调高（>10）时统一覆盖所有子 Agent。修复了用户设置 12 但 TechnicalAgent 仍以默认 6 步运行并报 "Agent exceeded max steps" 的问题。
- 🛡️ **Specialist（Skill）Agent 失败改为优雅降级** — 技能 Agent 失败不再中断整个分析管线，与 intel/risk 保持相同的降级策略。
- 🔧 **MiniMax-M2.7 连接测试修复** — 修复 LLM 通道连接测试在 MiniMax-M2.7 下返回 "Empty response" 的问题；将 `max_tokens` 上限从 8 提升至 256 以容纳思考过程，并添加 `content_blocks` 格式解析逻辑。
- 📊 **移除 `sentiment_score` 范围约束**（fixes #942）— 移除 `HistoryItem` 与 `ReportSummary` 响应 Schema 中 `sentiment_score` 的 `ge=0/le=100` 约束，历史库中存储的超范围值不再触发 Pydantic ValidationError。
- 🖥️ **WebUI 前端资源缺失时发出明确警告** — `webui_frontend.py` 在 `static/index.html` 存在但 `static/assets/` 缺失时发出 warning，避免 CSS/JS 资源缺失导致页面异常变大却无从排查（fixes #944）。
- 🔗 **分析管线可选服务降级初始化** — `StockAnalysisPipeline` 搜索服务与社交舆情服务任一初始化异常时，记录 warning 并以禁用状态继续运行，避免外部依赖抖动阻塞主分析链路。
- 🖥️ **桌面端版本展示统一读取 `package.json`** — 统一读取 `apps/dsa-desktop/package.json`，移除 preload 中硬编码的 `0.1.0`，设置页展示真实桌面端版本；修复版本号显示错误（fixes #1048）。
- 🐋 **港股名称获取失败修复**（fixes #940）— 修复主数据源字段缺失时无法正确回退到备用字段获取港股名称的问题。
- 🔄 **SSE 任务流断开时 `CancelledError` 正确 re-raise**（fixes #967）— 修复 SSE 流中断时异常被静默吞掉导致故障无日志可查的问题。
- 🔄 **Agent SSE 清理阶段后台任务异常正确上报**（fixes #969）— 流结束时后台执行器异常现在正确记录并上报，避免错误无法感知。
- 🔇 **技能加载异常补充 `logger.warning` 日志**（fixes #970）— 在 `ask.py`、`skills/aggregator.py`、`skills/router.py` 的静默 except 块补充日志，确保技能列表为空时有日志可查。
- 🛠️ **SQLite 写入链路原子化**（fixes #878）— `stock_daily(code,date)` 使用批量原子 upsert；文件型 SQLite 连接默认启用 WAL + `busy_timeout` + 有限写入重试；"新增数"改按本次真正插入窗口计算。
- 💰 **多 Agent / 单 Agent 预算护栏语义统一** — 剩余预算低于最小阈值时主动跳过并降级；已完成阶段可构建降级报告时返回 `success=True` 并携带非空内容，否则返回 `success=False`。
- ⚙️ **GitHub Actions `daily_analysis.yml` 补齐 `REPORT_LANGUAGE` 注入**（fixes #1013）— 修复用户在 Secrets/Variables 中配置 `REPORT_LANGUAGE` 后不生效的问题。
- 📊 **任务状态 API 补齐实时价格字段**（fixes #983）— `GET /api/v1/analysis/status/{task_id}` 从数据库回填已完成任务时补齐 `current_price` / `change_pct`，修复首页报告股票名旁不显示实时价格的问题。
- 📅 **非交易日数据返回最近交易日**（fixes #1009）— 修复非交易日（周末/节假日）筹码分布与板块排行返回倒数第二个交易日数据的问题，现在正常返回最近交易日数据。
- 🔍 **A 股资讯搜索恢复中文优先** — `search_stock_news()` 在首个 provider 主要返回英文资讯时继续尝试后续引擎，并将同批结果中的中文资讯排到前面；非美股查询不再默认沿用 Brave 的 `en/US` 区域语言偏好。
- 📨 **飞书群机器人通知支持签名校验** — 飞书通知现在支持 `FEISHU_WEBHOOK_SECRET` / `FEISHU_WEBHOOK_KEYWORD`；Web 设置与文档明确区分 Webhook 推送模式和 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 应用模式，降低误配风险。
- ⚡ **LLM 适配层新增 `RateLimitError` 和 `ContextWindowExceeded` 检测** — 识别并处理速率限制与上下文窗口超出错误，提升分析链路在高负载或长文本场景下的健壮性（fixes #1002）。

### 测试

- 🧪 **TushareFetcher 港股相关单元测试** — 新增 `get_chip_distribution` 筹码分布获取与 `_normalize_data` 港股/A 股/ETF 单位处理的单元测试，覆盖港股特殊路径。

### 文档

- 📘 **DEPLOY.md 补充 UI 元素异常变大排查步骤** — 新增重建 Docker 镜像或手动执行 `npm run build` 的排查指南；`deploy-webui-cloud.md` 同步更新。
- 📨 **飞书 Webhook 配置说明补全** — 强调 `FEISHU_WEBHOOK_URL` 是群通知必填项、签名校验须两端同时启用或关闭、`FEISHU_APP_SECRET` 仅用于应用/Stream Bot 模式；`.env.example` 补充内联注释；同步英文指南。
- 🤝 **FAQ 补充 Ollama 连接失败排障条目（Q12c）** — 覆盖服务未启动、URL 配置错误、模型前缀缺失、模型未下载、远程防火墙等 5 个检查点（fixes #854）。
- 🌉 **README 补充长桥数据源使用说明** — 中/英/繁 README 明确长桥"首选 / 兜底 / 未配置不调用"边界；`docs/` 内相对路径链接修复；`LONGBRIDGE_PRINT_QUOTE_PACKAGES` 配置与代码及 `.env.example` 对齐。
- 🐋 **Docker 安装场景版本说明** — 补充最小化文档，明确 Docker 安装场景下应以 Git tag / 镜像 tag 判断版本（fixes #1091）。

## [3.12.0] - 2026-04-01

### 发布亮点

- 📊 **回测页新增"次日验证"视图** — 可按股票与日期范围查看 AI 预测 vs 次日实际涨跌，复用历史分析与 1 日回测结果，快速验证分析准确率。
- 🔧 **LLM 接入体验简化** — 用户侧文案统一收口为"主模型 / 备选模型 / 模型渠道"，不再把 LiteLLM 当作普通用户必学概念，现有配置键保持兼容。
- 🐳 **Docker / WebUI 运行时稳态补强** — 修复系统设置保存后配置不生效、启动早期日志缺失、预构建静态资源复用等问题，降低容器化部署的运维摩擦。
- 🔒 **安全与并发稳定性同步增强** — Discord 入站 Webhook 补齐 Ed25519 验签，修复并发执行时共享状态未加锁、单股推送模式通知并发复用等问题。
- 🖥️ **桌面端与定时任务细节打磨** — Windows 安装器支持自选安装目录，内置定时调度器感知运行中 SCHEDULE_TIME 变更，断点续传改按市场时区判断。

### 新功能

- 📊 **回测页新增"次日验证 / 1 日窗口"视图** — 可按股票代码与分析日期范围查看 AI 预测、次日实际涨跌及筛选区间准确率，复用历史分析与 1 日回测结果实现。
- 🏷️ **Web 设置页新增版本信息卡片** — `apps/dsa-web` 现在会在构建时注入前端包版本与构建时间，系统设置页新增只读"版本信息"区块，展示 `WebUI 版本 / 构建标识 / 构建时间`；当 `package.json` 仍为占位版本 `0.0.0` 时，会自动回退为构建标识，方便 Docker 重建后快速确认当前静态资源是否已经生效。
- 🪟 **Windows 桌面安装器支持自选安装目录** — 安装器改为支持在安装向导中自定义安装目录，安装到非默认盘符后仍沿用现有打包态目录逻辑在安装目录旁读写 `.env`、`data/stock_analysis.db` 和 `logs/desktop.log`，同时保留 `win-unpacked` 免安装分发方式。安装器仅支持当前用户安装、已禁用管理员提权（`allowElevation: false`），并通过 NSIS `.onVerifyInstDir` 阻止选择系统保护目录。

### 改进

- 🔎 **SerpAPI 正文补抓范围收敛** — 自然搜索结果不再逐条同步抓取网页正文；现在仅对极少数高位且摘要明显不足的结果，在更短超时预算内做延迟补抓，并优先复用 SerpAPI 已返回的结构化摘要，降低搜索链路尾延迟与慢站点放大风险。
- 🤖 **LLM 接入体验简化** — 面向用户的 AI 模型接入文案已统一收口为"主模型 / Agent 主模型 / 备选模型 / 模型渠道 / 高级模型路由配置"；Web 设置页、配置元数据、校验提示与中英文文档不再把 LiteLLM 当作普通用户默认必学概念，现有 `LITELLM_*` / `LLM_CHANNELS` 配置键仍保持兼容。

### 修复

- 🚀 **启动早期失败时暴露真实根因** — `python main.py` 现在通过 stderr 暴露真实根因，bootstrap 阶段不再向硬编码 `logs/` 目录写入文件日志，文件日志推迟到 `config.log_dir` 可用后创建，避免健康启动在非预期路径残留日志文件。
- 🐳 **Docker WebUI 运行时优先复用预构建静态资源** — `prepare_webui_frontend_assets()` 现在会先检查镜像内已有的 `static/index.html` 是否可直接复用；当容器运行时不包含 `apps/dsa-web` 源码目录且未安装 `npm` 时，也不会误报"未找到前端项目，无法自动构建"，从而恢复 Docker 部署后的 WebUI 打开能力。
- 🐳 **Docker WebUI 系统设置保存后配置生效** — Docker 场景下 WebUI 保存 `STOCK_LIST`、`SCHEDULE_ENABLED`、`SCHEDULE_TIME`、`SCHEDULE_RUN_IMMEDIATELY`、`RUN_IMMEDIATELY` 后，`Config` 会优先读取持久化 `.env` 中的新值，避免被容器创建时注入的旧环境变量覆盖。
- 📈 **市场复盘 LLM max_tokens 提升** — 市场复盘生成链路将 LLM `max_tokens` 从 `2048` 提升到 `8192`，降低长复盘输出因 `MAX_TOKENS` 提前截断导致内容未完成的概率。
- ⏰ **内置定时调度器感知 SCHEDULE_TIME 运行时变更** — 调度器现在会在运行中感知 WebUI 保存后的 `SCHEDULE_TIME` 变化，并在下一轮检查时重绑 daily job。
- 🪟 **Windows Release 渠道编辑器保留 MiniMax 模型前缀** — 渠道模式下填写 `minimax/<模型名>` 时，后端归一化与 Web 设置页运行时模型列表都会保留该值原样，不再误改写成 `openai/minimax/<模型名>`。
- 🤖 **Discord 入站 Webhook 补齐 Ed25519 验签** — `DiscordPlatform` 现在会基于 `X-Signature-Ed25519`、`X-Signature-Timestamp` 和原始请求体校验 Discord Interaction 签名；缺失签名头、公钥格式非法或签名不匹配时直接拒绝请求，同时对 timestamp 做 ±5 分钟时效窗口校验以防御重放攻击。
- ⚙️ **STOCK_GROUP_N / EMAIL_GROUP_N 配置关系明确化** — 明确与 `STOCK_LIST` 的关系，并在配置校验中对超出 `STOCK_LIST` 的邮件分组给出 warning。
- 🗓️ **断点续传改按市场时区和交易日历判断**（fixes #880）— 股票数据存在性检查不再直接使用服务器自然日，而是按 A 股 / 港股 / 美股各自市场时区解析"最新可复用交易日"。
- 📨 **单股推送模式不再并发复用共享通知实例** — `StockAnalysisPipeline.run()` 现在会保留个股分析并发，但把 `SINGLE_STOCK_NOTIFY=true` 下的即时通知挪到结果收集侧串行发送。
- 🔇 **实时行情降级提示收口为单次告警** — 分析主流程获取股票名称时不再提前触发一次实时行情查询，只有在全部数据源都不可用时才提示已降级为历史收盘价继续分析。
- 🔍 **A 股中文资讯搜索恢复中文优先** — `search_stock_news()` 现在会在首个 provider 主要返回英文资讯时继续尝试后续引擎，并将同批结果中的中文资讯排到前面。
- 🔒 **并发执行时共享状态补齐统一加锁** — 修复并发执行时共享状态缺少统一加锁的问题，避免多线程场景下的数据竞争。

### 测试

- 🧪 **补充设置页版本信息回归测试** — 新增 Web 设置页版本信息渲染断言，并覆盖占位版本 `0.0.0` 自动回退为构建标识的逻辑。
- 🧪 **UI 治理与关键路径回归补强** — 补充 `SidebarNav`、`ChatPage`、`BacktestPage` 等组件测试，并新增 UI governance 守卫，持续防止交互元素重新引入原生 `title` 属性或旧 `input-terminal` 样式回流。同步更新 smoke / markdown drawer 相关验证，覆盖主题升级后的关键主链路。

## [3.11.0] - 2026-03-27

### 发布亮点

- 🎨 **Web 工作台完成一轮 UI 统一与双主题升级** — 首页、问股、回测、持仓和设置页进一步收口到统一设计 token、输入表面和状态表达；新增完整浅色主题，并支持浅色 / 深色一键切换与持久化保存。
- 🤖 **Bot / Agent 能力重新补回主分支** — 恢复 `/history`、`/strategies`、`/research` 等命令，`/ask` 继续支持多股对比与组合视角；Deep Research、事件监控与 schedule 轮询链路重新接回主线能力。
- 🔒 **安全性与运行稳态同步补强** — 修复 `X-Forwarded-For` 限流绕过风险，恢复 LiteLLM 官方 PyPI 安装路径，Tushare 初始化不再依赖本地 SDK，降低 Docker、桌面打包和环境重建时的脆弱点。
- 🖥️ **日常使用细节继续打磨** — 修复首页港股自动补全提交、登录页首屏主题闪烁、历史长股票名重叠，以及 Telegram Markdown 解析失败时整条通知发送中断等问题。

### 新功能

- 🎨 **全新浅色主题与双主题切换上线** — Web 工作台新增完整浅色主题，并支持在侧边栏中一键切换浅色 / 深色模式；主题选择会持久化保存，刷新页面后仍保持当前偏好。此次升级不是局部配色微调，而是对卡片层级、边界对比、输入表面、状态提示和页面背景做了一整套 light theme 重绘。
- 🤖 **补回主分支缺失的 Agent / Bot 能力** — `#648` / `#649` 已重新补回 `main`：Bot 恢复 `/history`、`/strategies`、`/research`，`/ask` 保留多股对比与组合视角；Deep Research 与 Event Monitor 的配置重新在 Web 设置页可见并可编辑，schedule 模式也重新接入事件告警轮询。

### 改进

- 🖥️ **核心页面统一到同一套工作台视觉语言** — `Home / Chat / Backtest / Portfolio / Settings` 进一步收口到共享设计 token、`input-surface` 输入体系、空态/错误态表达和抽屉遮罩语义，减少页面之间的视觉割裂与局部私有样式漂移。
- 💬 **问股交互可达性与反馈增强** — 问股页补强了会话导出、通知发送、消息复制、历史删除与追问上下文提示；AI 回复操作不再过度依赖 hover，触屏设备和小屏场景下也能直接触达关键按钮。
- 📊 **回测与持仓页表面和状态表达继续标准化** — 回测页筛选控件、布尔状态、结果表格与汇总卡片统一到共享输入/状态原语；持仓页的导入反馈、汇率刷新提示、空态与警示信息进一步归口到共享组件，减少页面级重复实现。
- 🧭 **导航与页面壳层协同优化** — 侧边栏主题切换、问股完成角标、移动端抽屉遮罩和主内容滚动契约进一步统一，首页、问股和回测在桌面端与移动端的切页体验更稳定。

### 测试

- 🧪 **UI 治理与关键路径回归补强** — 补充 `SidebarNav`、`ChatPage`、`BacktestPage` 等组件测试，并新增 UI governance 守卫，持续防止交互元素重新引入原生 `title` 属性或旧 `input-terminal` 样式回流。同步更新 smoke / markdown drawer 相关验证，覆盖主题升级后的关键主链路。

### 修复

- 🌗 **Web 首屏默认主题预设为深色** — `apps/dsa-web/index.html` 现在会在 React 挂载前读取本地保存的主题偏好；若没有已保存值，则立即给 `<html>` 预设 `dark` 并同步 `color-scheme`，避免首页和登录页首屏先闪出浅色主题。
- 🔐 **登录页独立主题层收口** — 登录页输入框、标签、切换按钮和按钮文案现在使用独立的 `--login-*` 视觉 token，不再继承全局浅/深主题文字色；即使浏览器缓存了浅色主题，登录页仍保持稳定的深色视觉与青色密码输入表现，避免密码圆点和文案落成黑色。
- 🖥️ **首页港股代码输入修复** — Web 首页分析输入框现在可正确接受港股代码与自动完成选中的港股项，补齐 `00700.HK` / `HK00700` 等格式识别，避免提交时误报“请输入有效的股票代码或股票名称”。

- 🔒 **认证限流 X-Forwarded-For 取值修复（CWE-345）**（#841 / #842）— `get_client_ip()` 从取 `X-Forwarded-For` 最左值改为最右值，防止攻击者通过伪造首部旋转限流桶绕过暴力破解保护；仅影响 `TRUST_X_FORWARDED_FOR=true` 且单层可信反向代理的部署场景，多级代理环境需按部署文档评估配置。
- 📦 **恢复 LiteLLM 官方 PyPI 安装并锁定安全上限** — `requirements.txt` 重新使用 `pip install litellm` 的官方 PyPI 安装路径，并在保留历史最低要求 `>=1.80.10` 的同时增加 `<1.82.7` 的安全上限，避免误装已被移除的 `1.82.7` / `1.82.8` 风险版本；Windows 桌面打包脚本也同步回退到标准 `pip install -r requirements.txt` 链路，减少特殊下载分支带来的维护成本。
- 📨 **Telegram Markdown 解析失败回退纯文本**（fixes #850）— `src/notification_sender/telegram_sender.py` 现在会在 Telegram 返回 `HTTP 400` 且包含 `can't parse entities` / Markdown 解析错误时，自动去掉 `parse_mode` 后重试纯文本发送，避免 `*ST` 等正文内容直接导致整条通知失败。
- 🔢 **A 股同码实时行情保留交易所提示**（fixes #852）— `DataFetcherManager` 与 `TushareFetcher` 现在会保留 `SZ000001` / `000001.SZ` 这类显式沪深提示，旧版 Tushare 实时行情降级分支不再把深市 `000001` 误判成 `sh000001` 上证指数。
- 🎯 **多 Agent 次优买点不再盲目复制理想买点**（fixes #851）— 当多智能体结果缺少独立 `secondary_buy` 时，仪表盘现在优先展示 `N/A` 而不是把 fallback 值硬拷贝成与 `ideal_buy` 完全相同，减少误导性的双买点展示。
- 🧩 **Tushare 初始化不再强依赖本地 SDK 包** — `TushareFetcher` 现在直接使用内置 HTTP client 访问 Tushare Pro，不再在启动阶段先 `import tushare` 才能初始化；修复了 Docker、桌面打包或环境重建后因缺少 `tushare` 包而提前报 `No module named 'tushare'` 的问题，并补充对应回归测试。
- ⚙️ **`daily_analysis` 工作流补齐 `DEEPSEEK_API_KEY` 映射** — GitHub Actions 每日分析工作流现在会正确透传 `DEEPSEEK_API_KEY`，避免云端任务配置了密钥却在运行时拿不到对应环境变量。
- 🖥️ **历史列表过长股票名称截断与悬停展示**（fixes #815）— 历史列表中过长的股票名称, 现在会按字符类型自动截断（英文15/中文8/混合10字符），默认显示截断结果，悬停时展示完整名称；解决 1920x1080 分辨率下股票名称与右侧状态标签文字重叠的问题。新增 `stockName.ts` 工具函数并补充对应测试。

### 文档

- 🧾 **README 捐赠入口更新为小红书二维码** — README 及中英文说明中的赞助入口更新为小红书二维码素材，保持展示口径一致。

## [3.10.1] - 2026-03-24

### 新功能

- 🔔 **Web 端分析推送通知开关**（#808）— 首页分析按钮旁新增「推送通知」复选框，默认勾选；取消勾选时本次分析不发送 Telegram/企业微信等推送。API `POST /api/v1/analysis/analyze` 新增 `notify` 字段（`bool`，默认 `true`），不传时行为与修改前一致，Bot 和定时任务不受影响。

### 改进

- 🖥️ **问股 / 回测页面布局与壳层协同优化** — 统一 Chat / Backtest 页面容器、共享 UI 状态和跟随问答交互路径，移除部分硬编码高度限制，让导航框架内的填充与滚动行为更连贯。
- 🎨 **全局视觉与共享组件继续收敛** — Light theme 引入动态 HSL 阴影体系，统一侧边栏激活态、告警组件对比度和聊天气泡样式，并把部分零散内联样式收口为语义化 CSS 变量，提升一致性与可维护性。

### 修复

- 🖼️ **系统设置智能导入文件选择恢复** — 修复了“系统设置 > 基础设置 > 智能导入”模块中 “选择图片 / 选择文件” 两个按钮点击无响应的问题。
- 🖥️ **移动端滚动与交互层级修复** — 解决主题切换菜单在移动端被主内容遮挡的 z-index 冲突，并恢复首页长报告场景下的正常纵向滚动，不影响其他页面现有滚动行为。
- 🧾 **Markdown 纯文本复制清洗增强** — 改进纯文本导出算法，复制分析报告时会更稳定地清除表格分隔符等 Markdown 痕迹，提升分享和归档内容的纯净度。
- 🧠 **Trading philosophy injection 覆盖 legacy + Agent 全链路**（#810）— `GeminiAnalyzer`、单 Agent 模式和 skill-aware Prompt 现在共享同一套策略注入状态；只有隐式回落到内置默认 `bull_trend` 时才保留旧的趋势型提示，显式策略选择或自定义默认 skill 不再被偷偷叠加 `MA5>MA10>MA20` 多头基线。
- 🛠️ **后端 CI 依赖安装链路稳态化**（#835）— 拆分 backend gate 阶段、为依赖安装增加重试，并把 CI 用的 `litellm` 安装来源调整为更稳定的 GitHub 源，降低依赖解析抖动导致的 backend gate 偶发失败。
- 🪟 **Windows 桌面发版构建恢复 LiteLLM 安装兼容性** — `scripts/build-backend.ps1` 现在会先过滤 `requirements.txt` 中的 LiteLLM GitHub 源包，再下载对应 tag 的 zipball 到本地移除上游可选 `enterprise/` 目录后安装，绕过 Windows runner 上 Poetry 构建 wheel 时把目录误当文件打包导致的失败；同时补上 `pip install` 退出码检查，避免依赖安装失败后只在后续 `python-multipart` 校验阶段才暴露成次生报错。

### 测试

- 🧪 **问股 / 回测 / 智能导入回归覆盖补齐** — 同步更新 E2E 冒烟期望，补充 `DashboardStateBlock`、Chat 页、智能导入文件选择与相关交互回归断言，确保近期 UI 调整后的关键路径仍可稳定通过。

## [3.10.0] - 2026-03-24

### 发布亮点

- 🔎 **自动补全与索引工具扩展到三市场** — 补全索引生成链路现在同时覆盖 A 股、港股、美股，配套新增 Tushare 股票列表抓取工具与更完整的静态索引数据，让首页搜索入口从“能用”走向“更全、更稳”。
- 🖥️ **Dashboard 与报告查看体验继续收口** — 首页 Dashboard 面板、状态边界、字体层级和完整报告表格密度完成一轮统一；报告详情也补齐了 Markdown/纯文本复制与更可靠的按钮交互，减少历史报告查看与分享时的摩擦。
- 🤖 **Agent skill 与市场语义边界更清晰** — skill bundle、默认策略、回测汇总语义和兼容接口进一步收敛；同时分析 Prompt 不再默认写死 A 股上下文，美股和港股分析也能按各自市场规则生成更贴切的内容。
- ⏰ **定时与桌面配置能力更贴近真实使用场景** — 桌面端支持 `.env` 导入导出；`python main.py --schedule --stocks ...` 也不再把启动时股票快照错误带入后续计划执行，定时任务会跟随最新保存的 `STOCK_LIST`。
### 新功能

- 💾 **桌面端 `.env` 备份/恢复入口**（#754）— 桌面模式下的系统设置页新增 `导出 .env` / `导入 .env` 按钮，可直接备份当前已保存配置，或把备份文件中的键值合并恢复到当前桌面端 `.env`；导入沿用现有 `config_version` 冲突保护与运行时重载链路，不改变现有桌面端便携模式路径。
- 📊 **Tushare 股票列表获取工具** — 新增 `scripts/fetch_tushare_stock_list.py`，支持从 Tushare Pro 获取 A股、港股、美股列表信息并保存为 CSV，配有分页读取、智能限流、错误处理和进度提示；新增对应使用文档 `docs/TUSHARE_STOCK_LIST_GUIDE.md`。
- 🔎 **索引生成脚本多市场支持** — `generate_index_from_csv.py` 重构为支持 Tushare 和 AkShare 双数据源，同时覆盖 A股、港股、美股三个市场；新增按市场分类的别名映射（A股、港股常见别名，美股常用股票英文缩写）；添加 `--source` 参数切换数据源、`--test` 参数验证模式；严格过滤美股 DUMMY 记录。
- 🔎 **索引生成脚本增强** — `generate_stock_index.py` 新增 `--test`/`-t` 测试模式和 `--verbose`/`-v` 详细输出模式，添加市场分布统计，优化 JSON 输出格式。
- 📋 **首页完整报告支持双模式复制** — 历史报告详情头部新增“复制 Markdown 源码”和“复制纯文本”工具按钮；前者保留原始 Markdown 结构，后者去除常见 Markdown 格式符号，方便分享、归档和跨报告比对。复制按钮文案会跟随 `REPORT_LANGUAGE` 保持中英文一致，避免英文报告页出现中文固定文案。
- 🧩 **个股分析页补齐关联板块展示**（#669）— A 股分析写路径现在会把 `belong_boards` 一次性写入 `fundamental_context` / `fundamental_snapshot`，结构化报告详情同步新增 `belong_boards` 与 `sector_rankings` 字段，Web 个股分析页首屏可直接展示所属板块及其是否命中当日板块涨跌榜；无数据时保持 fail-open 隐藏，不影响现有分析主流程。

### 改进

- 🖥️ **Dashboard 面板统一化（PR7-2）** — 新增 `DashboardPanelHeader` 和 `DashboardStateBlock` 作为历史、报告、资讯、任务和透明度等面板的通用组件；统一了各面板标题层级、加载/空态/错误态和 CSS 变量 token。
- 🖥️ **HomePage 状态边界收口（PR7-2）** — 引入 `useHomeDashboardState` hook，集中 `stockPoolStore` 状态选取逻辑，移除 `HomePage` 中重复的本地状态派生和回调定义。
- 🧭 **Agent skill 统一到单一配置语义** — Multi-Agent runtime、API、Web chat 和配置元数据统一围绕 `skill` 概念收敛；`/api/v1/agent/skills` 成为主发现入口，`AGENT_SKILL_*` 成为主配置面，内置 skill 元数据也开始声明默认启用、排序优先级、market regime tag 等信息，减少默认策略散落在代码里的隐式耦合。
- 🔎 **自动补全索引数据更新** — 重新生成 `stocks.index.json`，涵盖 A股、港股、美股三个市场，提升自动补全覆盖率。
- 🧾 **Dashboard 字体与完整报告表格密度微调** — 收敛首页侧栏、空状态、历史操作区的字体层级，并将完整 Markdown 报告表格 `th/td` 的内边距调整到更紧凑的 4-6px 区间，让信息密度与现有 Dashboard 视觉节奏更一致。

### 修复

- ⏰ **定时模式不再锁定启动时 CLI 股票快照** — `python main.py --schedule --stocks ...` 现在不会让后续计划执行沿用启动时的旧股票列表；定时任务每次触发前都会重新读取最新保存的 `STOCK_LIST`，确保 WebUI 或 `.env` 更新后的自选股配置能参与后续推送。
- 🌍 **LLM Prompt 按股票市场动态注入上下文** — 分析链路不再把市场规则写死成 A 股；系统 Prompt 会根据股票代码识别 A 股、港股或美股，并注入对应的角色描述与交易规则提示，减少跨市场分析出现口径错位或结论失真的问题。
- 🔎 **美股自动补全复用 ticker 去重** — `generate_index_from_csv.py` 在导入 Tushare `us_basic` CSV 时会先按 `ts_code` 折叠复用的美股 ticker，优先保留更可能仍在使用的记录，避免 `stocks.index.json` 出现重复 `canonicalCode` 后让 Web 自动补全展示历史名称或提交歧义代码。
- 🧾 **Web 报告详情复制交互稳定性修复**（#749）— `ReportDetails` 中“原始分析结果 / 分析快照”的复制按钮补齐可点击层级，避免被下方 JSON 内容覆盖；两个面板的复制提示也改为各自独立，不再出现复制一个后两个按钮同时显示“已复制”的误导反馈。
- 📊 **Agent skill 回测与兼容接口语义收敛** — `get_skill_backtest_summary` 现在要求显式传入 `skill_id`，缺失时返回明确校验提示；仓库尚未持久化真实 skill 级汇总时会返回明确的 unsupported/info 响应，并保留 `normalized` 与 `*_pct` 兼容字段，避免沿用 overall 指标误导 Agent 或用户。
- 🔧 **Skill 默认选择与兼容层行为加固** — `allowed-tools` 会继续仅作为 `SKILL.md` bundle 元数据保留，不再泄露到运行时工具选择；`/api/v1/agent/strategies` 恢复旧 payload 形状；显式传入 `skills: []` 时会清空陈旧上下文；当用户明确选择策略 skill 时不再偷偷叠加默认 bull-trend，而在 `AGENT_SKILLS` 为空时则统一只回落到单一主默认 skill。

### 测试

- 🧪 **Dashboard 组件测试覆盖率扩展（PR7-2）** — 新增 `ReportNews` 和 `TaskPanel` 测试；对 `HistoryList`、`ReportDetails`、`HomePage`、`useDashboardLifecycle` 和 `stockPoolStore` 增强了断言覆盖，包括删除回退、移动端抽屉和任务生命周期等场景。
- 🧪 **多市场索引生成测试补齐** — 新增 `tests/test_generate_index_from_csv.py`，覆盖 Tushare/AkShare 双数据源解析、多市场判断、美股 DUMMY 过滤与重复 ticker 去重等核心路径。
- 🧪 **关联板块写入与 API 契约回归** — 新增 `tests/test_pipeline_related_boards.py`，并补充分析历史与分析接口契约测试，确保 `belong_boards` / `sector_rankings` 只做增量扩展且保持 fail-open。
- 🧪 **定时模式股票列表语义回归测试** — 新增 `tests/test_main_schedule_mode.py`，覆盖定时模式忽略启动时 `--stocks` 快照、单次运行仍保留 CLI 股票覆盖的边界场景。

### 文档

- 📘 **新增 Tushare 股票列表工具文档** — 新增 `docs/TUSHARE_STOCK_LIST_GUIDE.md`，说明股票列表抓取工具的使用方法、数据格式和常见问题。
- 🌍 **补齐定时模式与关联板块的双语说明** — `docs/full-guide.md` / `docs/full-guide_EN.md` 现在明确说明 scheduled mode 会在每次执行前重新读取 `STOCK_LIST`，并同步补充个股关联板块展示能力说明，减少配置预期偏差。
- 🧭 **调整 Agent 术语兼容文案** — README、双语文档、设置页与问股界面继续以“策略”作为用户入口主称呼，同时补充 `skill` 作为内部统一命名，降低迁移期理解成本。

## [3.9.0] - 2026-03-20

### 发布亮点

- 🤖 **模型链路与报告语言更灵活** — Agent 现在可以通过 `AGENT_LITELLM_MODEL` 独立选择模型链路，普通分析与 Agent 报告也可通过 `REPORT_LANGUAGE=zh|en` 输出统一语言，减少“英文内容 + 中文壳子”这类混排问题，并允许团队分别权衡主分析与 Agent 的成本、速度和能力。
- 🔎 **首页分析体验完成一轮闭环优化** — 首页新增 A 股自动补全，支持代码、中文名、拼音和别名检索；同时 Dashboard 状态收口到统一 store，历史、报告、新闻与 Markdown 抽屉的交互更稳定，“Ask AI” 追问也会优先携带当前报告上下文。
- 💬 **通知与检索能力继续外扩** — 新增 Slack 一等通知渠道；SearXNG 在未配置自建实例时可以自动发现公共实例并按受控轮询降级；Tavily 时效新闻链路修复后，严格时效过滤不再错误丢光有效结果。
- 💼 **持仓与市场复盘链路更稳** — A 股 market review 可选接入 TickFlow 强化指数与涨跌统计；持仓账本写入改为串行化以缩小并发超卖窗口；汇率刷新入口和禁用态提示也更加清晰，减少用户误判。

### 新功能

- 🔎 **Web 股票自动补全 MVP** — 首页分析输入框新增本地索引驱动的自动补全，支持股票代码、中文名、拼音和别名匹配；选中候选后会提交 canonical code，并透传 `stock_name`、`original_query`、`selection_source` 到分析请求、任务状态和 SSE 事件；索引加载失败时自动退回旧输入模式，不阻断原有提交流程。同步补充了静态索引加载器、索引生成脚本和前后端契约测试。分阶段进行开发，第一阶段仅支持 A 股。
- 💬 **Slack 一等通知渠道** — 新增 Slack 原生通知支持，同时支持 Bot Token 和 Incoming Webhook 两种接入方式；同时配置时优先使用 Bot API，确保文本与图片发送到同一频道；Bot Token 模式支持图片上传（raw body POST，不使用 multipart）；新增 `SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID`、`SLACK_WEBHOOK_URL` 配置项，GitHub Actions 工作流同步补齐对应 Secrets 传递。
- 🌍 **报告输出语言可配置**（Issue #758）— 新增 `REPORT_LANGUAGE=zh|en`，默认 `zh`；语言设置会同步注入普通分析与 Agent Prompt，并覆盖 Markdown/Jinja 模板、通知 fallback、历史/API `report_language` 元数据及 Web 报告页固定文案，避免“英文内容 + 中文壳子”的混合输出。
- 🚀 **Agent 与普通分析模型解耦**（Issue #692）— 新增 `AGENT_LITELLM_MODEL`（留空继承 `LITELLM_MODEL`，无前缀按 `openai/<model>` 归一）；Agent 执行链路与 `/api/v1/agent/models` 的 `is_primary/is_fallback` 标记改为基于 Agent 实际模型链路；系统配置与启动期校验补齐 `AGENT_LITELLM_MODEL` 的 `unknown_model/missing_runtime_source` 检查；Web 设置页新增 Agent 主模型选择并与渠道模式运行时配置同步。
- 🔎 **SearXNG 公共实例自动发现与受控轮询**（#752）— 新增 `SEARXNG_PUBLIC_INSTANCES_ENABLED`，在未配置 `SEARXNG_BASE_URLS` 时默认从 `searx.space` 拉取公共实例列表，并按受控轮询顺序选择实例；同次请求内遇到超时、连接错误、HTTP 非 200 或无效 JSON 会自动切换到下一个实例。已配置自建实例的用户保持原有优先级与语义不变；`daily_analysis` GitHub Actions 工作流也已支持显式透传该开关并在启动日志中展示当前状态。
- 📈 **TickFlow market review enhancement** (#632) — 新增可选 `TICKFLOW_API_KEY`；配置后，A 股大盘复盘的主要指数行情优先尝试 TickFlow；若当前 TickFlow 套餐支持标的池查询，市场涨跌统计也会优先尝试 TickFlow。失败或权限不足时立即回退到现有 `AkShare / Tushare / efinance` 链路；板块涨跌榜回退顺序保持不变。接入层同时适配了真实 SDK 契约：主指数查询按单次请求上限分批拉取，并将 TickFlow 返回的比例型 `change_pct` / `amplitude` 统一转换为项目内部的百分比口径。

### 改进

- **Dashboard state slice and workspace closure** — moved Home / Dashboard state into `stockPoolStore`, consolidated history selection, report loading, task syncing, polling refresh, and markdown drawer handling under a single state slice.
- **Dashboard panel standardization** — kept the current dashboard layout contract stable while unifying history, report, news, and markdown presentation with shared tokens, standardized states, and bounded in-panel scrolling for the history list.
- **Dashboard-to-chat follow-up bridge** — routed “Ask AI” follow-ups through report-context hydration instead of direct cross-page state coupling, while keeping chat sends usable when enriched history context is still loading.
- 💼 **持仓账本并发写入串行化**（#742）— 持仓源事件写入/删除现在会在 SQLite 下先获取串行化写锁，减少并发卖出把超售流水写入账本的窗口；直接持仓写接口在锁竞争时返回 `409 portfolio_busy`，CSV 导入保持逐条提交并把 busy 计入 `failed_count`。
- 💱 **持仓页汇率手动刷新入口补齐**（#748）— Web `/portfolio` 页面现在会在“汇率状态”卡片中展示“刷新汇率”按钮，直接调用现有 `POST /api/v1/portfolio/fx/refresh` 接口；刷新后会仅重载快照与风险数据，并以内联摘要反馈“已更新 / 仍 stale / 刷新失败”的结果，减少用户对 `fxStale` 长时间停留的误解。

### 修复

- 🔎 **Web 自动补全 Enter 提交语义修正** — 股票自动补全在搜索命中候选时不再默认高亮第一项；候选列表展开但用户尚未用方向键或鼠标明确选中时，按 Enter 会继续提交原始输入，避免手动输入被第一条候选静默覆盖。
- 🌍 **补齐 `REPORT_LANGUAGE` 启动解析与历史展示本地化边界** — `Config` 在启动时继续遵循“真实环境变量优先、`.env` 兜底”的既有语义，并在两者冲突时输出显式告警，减少 `REPORT_LANGUAGE` 来源不清带来的误判；同时 `/api/v1/history/{id}` 英文详情响应会同步本地化 `sentiment_label`，历史 Markdown 也会正确识别英文 `bias_status` 的风险等级 emoji，避免出现 `乐观` 或 `🚨Safe` 这类中英混排/误报展示。
- 📰 **Tavily 时效新闻检索发布时间映射修复**（#782）— Tavily 在股票新闻和严格时效的情报维度中现在会显式使用 `topic="news"`，并兼容 `published_date` / `publishedDate` 两种发布时间字段；修复了 Tavily 明明返回结果却在后续硬过滤阶段被全部记为 `drop_unknown` 丢弃的问题，同时将机构分析、业绩预期、行业分析等分析型维度恢复为宽源搜索，不再被统一压缩成新闻模式。
- 💱 **持仓页汇率刷新禁用语义修正**（#772）— 当 `PORTFOLIO_FX_UPDATE_ENABLED=false` 时，`POST /api/v1/portfolio/fx/refresh` 现在会返回显式 `refresh_enabled=false` 与 `disabled_reason`，Web `/portfolio` 页面会明确提示“汇率在线刷新已被禁用”，不再误报“当前范围无可刷新的汇率对”。
- 🤖 **Agent timeout and config hardening** — `AGENT_ORCHESTRATOR_TIMEOUT_S` now also protects the legacy single-agent ReAct loop, parallel tool batches stop waiting once the remaining budget is exhausted, and invalid numeric `.env` values fall back to safe defaults with warnings instead of crashing startup.
- 🌐 **CORS wildcard + credentials compatibility** — `CORS_ALLOW_ALL=true` no longer combines `allow_origins=["*"]` with credentialed requests, avoiding browser-side cross-origin failures in demo/development setups.
- 🧭 **Unavailable Agent settings hidden from Web UI** — Deep Research / Event Monitor controls are now treated as compatibility-only metadata in the current branch and are removed from the Settings page to avoid exposing non-functional toggles.

### 文档

- 新增 Ollama 本地模型配置说明，同步更新 `README.md` 与 `docs/README_EN.md`（Fixes #690）
- 完善 Ollama 配置说明：`docs/full-guide.md` / `docs/full-guide_EN.md` 环境变量表与 Note 补充 `OLLAMA_API_BASE`，避免英文用户误以为 Ollama 不能作为独立配置入口；合并重复的 `OLLAMA_API_BASE` 条目为单一条目
- 明确文档同步治理边界：补充 `README.md`、专题文档、双语文档与交付说明之间的默认同步规则，减少后续文档漂移

## [3.8.0] - 2026-03-17

### 发布亮点

- 🎨 **Web 界面完成一轮骨架升级** — 新的 App Shell、侧边导航、主题能力、登录与系统设置流程已经串成统一体验，桌面端加载背景也完成对齐。
- 📈 **分析上下文继续补强** — 美股新增社交舆情情报，A 股补齐财报与分红结构化上下文，Tushare 新接入筹码分布和行业板块涨跌数据。
- 🔒 **运行稳定性与配置兼容性提升** — 退出登录会立即让旧会话失效，定时启动兼容旧配置，运行中的 `MAX_WORKERS` 调整和新闻时效窗口反馈更清晰。
- 💼 **持仓纠错链路更完整** — 超售会被前置拦截，错误交易/资金流水/公司行为可以直接删除回滚，便于修复脏数据。

### 新功能

- 📱 **美股社交舆情情报** — 新增 Reddit / X / Polymarket 社交媒体情绪数据源，为美股分析提供实时社交热度、情绪评分和提及量等补充指标；完全可选，仅在配置 `SOCIAL_SENTIMENT_API_KEY` 后对美股生效。
- 📊 **A 股财报与分红结构化增强**（Issue #710）— `fundamental_context.earnings.data` 新增 `financial_report` 与 `dividend` 字段；分红统一按“仅现金分红、税前口径”计算，并补充 `ttm_cash_dividend_per_share` 与 `ttm_dividend_yield_pct`；分析/历史 API 的 `details` 追加 `financial_report`、`dividend_metrics` 可选字段，保持 fail-open 与向后兼容。
- 🔍 **接入 Tushare 筹码与行业板块接口** — 新增筹码分布、行业板块涨跌数据获取能力，并统一纳入配置化数据源优先级；默认按上海时间区分盘中/盘后交易日取数，优先使用 Tushare 同花顺接口，必要时降级到东财。
- 🧱 **Web UI 基础骨架升级** — 重建共享设计令牌与通用组件，新增 App Shell、Theme Provider、侧边导航，并同步调整 Electron 加载背景，为 Web / Desktop 的统一体验打底。
- 🔐 **登录与系统设置流程重做** — 重构 Login、Settings 与 Auth 管理流程，补上显式的认证 setup-state 处理，并让 Web 端与运行时认证配置 API 行为对齐。
- 🧪 **前端回归与冒烟覆盖补强** — 新增并扩展登录、首页、聊天、移动端 Shell、设置页、回测入口等关键路径的组件测试与 Playwright smoke coverage。

### 变更

- 🧭 **页面接入新 Shell 布局契约** — Home、Chat、Settings、Backtest 已统一接入新的页面容器、抽屉和滚动约定，降低 UI 迁移期间的页面行为不一致。
- 💾 **设置页状态同步更稳** — 优化草稿保留、直接保存同步与冲突处理，减少模块级保存后前后端配置状态不一致的问题。
- 🎭 **登录页视觉基线回归** — 登录页恢复到既有 `006` 分支的视觉基线，同时保留新的认证状态逻辑和统一表单交互模型。
- 🏛️ **AI 协作治理资产加固** — 收敛并加强 `AGENTS.md`、`CLAUDE.md`、Copilot 指令和校验脚本的一致性约束，降低治理资产长期漂移风险。

### Added

- **Web UI foundation refresh** — rebuilt shared design tokens and common primitives, introduced the app shell, theme provider, sidebar navigation, and Electron loading background alignment for the upgraded desktop/web experience
- **Settings and auth workflow overhaul** — rebuilt the Login, Settings, and Auth management flows, added explicit auth setup-state handling, and aligned the Web UI with the runtime auth configuration APIs
- **UI regression coverage and smoke checks** — expanded targeted frontend tests and added Playwright smoke coverage for login, home, chat, mobile shell, settings, and backtest entry flows

### Changed

- **Shell-driven page integration** — aligned Home, Chat, Settings, and Backtest with the new shell layout contract so routing, drawer behavior, and page-level scrolling are consistent during the UI migration
- **Settings state consistency** — refined draft preservation, direct-save synchronization, and conflict handling so module-level saves no longer leave the page out of sync with backend config state
- **Login visual baseline** — restored the login page visual treatment to the established `006` branch baseline while keeping the newer auth-state logic and unified form interaction model

### 修复

- ⏰ **定时启动立即执行兼容旧配置**（Issue #726）— `SCHEDULE_RUN_IMMEDIATELY` 未设置时会回退读取 `RUN_IMMEDIATELY`，修复升级后旧 `.env` 在定时模式下的兼容性问题；同时澄清 `.env.example` / README 中两个配置项的适用范围，并注明 Outlook / Exchange 强制 OAuth2 暂不支持。
- 🧵 **运行期 `MAX_WORKERS` 配置生效与可解释性增强**（#633）— 修复异步分析队列未按 `MAX_WORKERS` 同步的问题；新增任务队列并发 in-place 同步机制（空闲即时生效、繁忙延后），并在设置保存反馈与运行日志中明确输出 `profile/max/effective`，减少“参数未生效”误解。
- 🔐 **退出登录立即失效现有会话** — `POST /api/v1/auth/logout` 现在会轮换 session secret，避免旧 cookie 在退出后仍可继续访问受保护接口；同浏览器标签页和并发页面会被同步登出。认证开启时，该接口也不再属于匿名白名单，未登录请求会返回 `401`，避免匿名请求触发全局 session 失效。
- 🧮 **Tushare 板块/筹码调用限流与跨日缓存修复** — 新增的 `trade_cal`、行业板块排行、筹码分布链路统一接入 `_check_rate_limit()`；交易日历缓存改为按自然日刷新，避免服务跨天运行后继续沿用旧交易日判断取数日期。
- 💼 **持仓超售拦截与错误流水恢复**（#718）— `POST /api/v1/portfolio/trades` 现在会在写入前校验可卖数量，超售返回 `409 portfolio_oversell`；持仓页新增交易 / 资金流水 / 公司行为删除能力，删除后会同步失效仓位缓存与未来快照，便于从错误流水中直接恢复。
- 📧 **邮件中文发件人名编码**（#708）— 邮件通知现在会对包含中文的 `EMAIL_SENDER_NAME` 自动做 RFC 2047 编码，并在异常路径补充 SMTP 连接清理，修复 GitHub Actions / QQ SMTP 下 `'ascii' codec can't encode characters` 导致的发送失败。
- 🐛 **港股 Agent 实时行情去重与快速路由** — 统一 `HK01810` / `1810.HK` / `01810` 等港股代码归一规则；港股实时行情改为直接走单次 `akshare_hk` 路径，避免按 A 股 source priority 重复触发同一失败接口；Agent 运行期对显式 `retriable=false` 的工具失败增加短路缓存，减少同轮分析中的重复失败调用。
- 📰 **新闻时效硬过滤与策略分窗**（#697）— 新增 `NEWS_STRATEGY_PROFILE`（`ultra_short/short/medium/long`）并与 `NEWS_MAX_AGE_DAYS` 统一计算有效窗口；搜索结果在返回后执行发布时间硬过滤（时间未知剔除、超窗剔除、未来仅容忍 1 天），并在历史 fallback 链路追加相同约束，避免旧闻再次进入“最新动态/风险警报”。

### 文档

- ☁️ **新增云服务器 Web 界面部署与访问教程**（Fixes #686）— 补充从云端部署到外部访问的落地说明，降低远程自托管门槛。
- 🌍 **补齐英文文档索引与协作文档** — 新增英文文档索引、贡献指南、Bot 命令文档，并补充中英双语 issue / PR 模板，方便中英文协作与外部贡献者理解项目入口。
- 🏷️ **本地化 README 补充 Trendshift badge** — 在多语言 README 中同步补上新版能力入口标识，减少中英文说明面不一致。

## [3.7.0] - 2026-03-15

### 新功能

- 💼 **持仓管理 P0 全功能上线**（#677，对应 Issue #627）
  - **核心账本与快照闭环**：新增账户、交易、现金流水、企业行为、持仓缓存、每日快照等核心数据模型与 API 端点；支持 FIFO / AVG 双成本法回放；同日事件顺序固定为 `现金 → 企业行为 → 交易`；持仓快照写入采用原子事务。
  - **券商 CSV 导入**：支持华泰 / 中信 / 招商首批适配，含列名别名兼容；两阶段接口（解析预览 + 确认提交）；`trade_uid` 优先、key-field hash 兜底的幂等去重；前导零股票代码完整保留。
  - **组合风险报告**：集中度风险（Top Positions + A 股板块口径）、历史回撤监控（支持回填缺失快照）、止损接近预警；多币种统一换算 CNY 口径；汲取失败时回退最近成功汇率并标记 stale。
  - **Web 持仓页**（`/portfolio`）：组合总览、持仓明细、集中度饼图、风险摘要、全组合 / 单账户切换；手工录入交易 / 资金流水 / 企业行为；内嵌账户创建入口；CSV 解析 + 提交闭环与券商选择器。
  - **Agent 持仓工具**：新增 `get_portfolio_snapshot` 数据工具，默认紧凑摘要，可选持仓明细与风险数据。
  - **事件查询 API**：新增 `GET /portfolio/trades`、`GET /portfolio/cash-ledger`、`GET /portfolio/corporate-actions`，支持日期过滤与分页。
  - **可扩展 Parser Registry**：应用级共享注册，支持运行时注册新券商；新增 `GET /portfolio/imports/csv/brokers` 发现接口。

- 🎨 **前端设计系统与原子组件库**（#662）
  - 引入渐进式双主题架构（HSL 变量化设计令牌），清理历史 Legacy CSS；重构 Button / Card / Badge / Collapsible / Input / Select 等 20+ 核心组件；新增 `clsx` + `tailwind-merge` 类名合并工具；提升历史记录、LLM 配置等页面可读性。

- ⚡ **分析 API 异步契约与启动优化**（#656）
  - 规范 `POST /api/v1/analysis/analyze` 异步请求的返回契约；优化服务启动辅助逻辑；修复前端报告类型联合定义与后端响应对齐问题。

### 修复

- 🔔 **Discord 环境变量向后兼容**（#659）：运行时新增 `DISCORD_CHANNEL_ID` → `DISCORD_MAIN_CHANNEL_ID` 的 fallback 读取；历史配置用户无需修改即可恢复 Discord Bot 通知；全部相关文档与 `.env.example` 对齐。
- 🔧 **GitHub Actions Node 24 升级**（#665）：将所有 GitHub 官方 actions 升级至 Node 24 兼容版本，消除 CI 日志中的 Node.js 20 deprecation warning（影响 2026-06-02 强制升级窗口）。
- 📅 **持仓页默认日期本地化**：手工录入表单默认日期改用本地时间（`getFullYear/Month/Date`），修复 UTC-N 时区用户在当天晚间出现日期偏移的问题。
- 🔁 **CSV 导入去重逻辑加固**：dedup hash 纳入行序号作为区分因子，确保同字段合法分笔成交不被误折叠；同时在 `trade_uid` 存在时也持久化 hash，防止混合来源重复写入。

### 变更

- `POST /api/v1/portfolio/trades` 在同账户内 `trade_uid` 冲突时返回 `409`。
- 持仓风险响应新增 `sector_concentration` 字段（增量扩展），原有 `concentration` 字段保持不变。
- 分析 API `analyze` 接口异步行为契约文档化；前端报告类型联合更新。

### 测试

- 新增持仓核心服务测试（FIFO / AVG 部分卖出、同日事件顺序、重复 `trade_uid` 返回 409、快照 API 契约）。
- 新增 CSV 导入幂等性、合法分笔成交不误去重、去重边界、风险阈值边界、汇率降级行为测试。
- 新增 Agent `get_portfolio_snapshot` 工具调用测试。
- 新增分析 API 异步契约回归测试。

## [3.6.0] - 2026-03-14

### Added
- 📊 **Web UI Design System** — implemented dual-theme architecture and terminal-inspired atomic UI components
- 📊 **UI Components Refactoring** — integrated `clsx` and `tailwind-merge` for robust class composition across Web UI

- 🗑️ **History batch deletion** — Web UI now supports multi-selection and batch deletion of analysis history; added `POST /api/v1/history/batch-delete` endpoint and `ConfirmDialog` component.
- 🔐 **Auth settings API** — new `POST /api/v1/auth/settings` endpoint to enable or disable Web authentication at runtime and set the initial admin password when needed
- openclaw Skill 集成指南 — 新增 [docs/openclaw-skill-integration.md](openclaw-skill-integration.md)，说明如何通过 openclaw Skill 调用 DSA API
- ⚙️ **LLM channel protocol/test UX** — `.env` and Web settings now share the same channel shape (`LLM_CHANNELS` + `LLM_<NAME>_PROTOCOL/BASE_URL/API_KEY/MODELS/ENABLED`); settings page adds per-channel connection testing, primary/fallback/vision model selection, and protocol-aware model prefixing
- 🤖 **Agent architecture Phase 0+1** — shared protocols (`AgentContext`, `AgentOpinion`, `StageResult`), extracted `run_agent_loop()` runner, `AGENT_ARCH` switch (`single`/`multi`), config registry entries
- 🔍 **Bot NL routing** — two-layer natural-language routing: cheap regex pre-filter (stock codes + finance keywords) → lightweight LLM intent parsing; controlled by `AGENT_NL_ROUTING=true`; supports multi-stock and strategy extraction
- 💬 **`/ask` multi-stock analysis** — comma or `vs` separated codes (max 5), parallel thread execution with 150s timeout (preserves partial results), Markdown comparison summary table at top
- 📋 **`/history` command** — per-user session isolation via `{platform}_{user_id}:{scope}` format (colon delimiter prevents prefix collision); lists both `/chat` and `/ask` sessions; view detail or clear
- 📊 **`/strategies` command** — lists available strategy YAML files grouped by category (趋势/形态/反转/框架) with ✅/⬜ activation status
- 🔧 **Backtest summary tools** — `get_strategy_backtest_summary` and `get_stock_backtest_summary` registered as read-only Agent tools
- ⚙️ **Agent auto-detection** — `is_agent_available()` auto-detects from `LITELLM_MODEL`; explicit `AGENT_MODE=true/false` takes full precedence
- 🏗️ **Multi-Agent orchestrator (Phase 2)** — `AgentOrchestrator` with 4 modes (`quick`/`standard`/`full`/`strategy`); drop-in replacement for `AgentExecutor` via `AGENT_ARCH=multi`; `BaseAgent` ABC with tool subset filtering, cached data injection, and structured `AgentOpinion` output
- 🧩 **Specialised agents (Phase 2-4)** — `TechnicalAgent` (8 tools, trend/MA/MACD/volume/pattern analysis), `IntelAgent` (news & sentiment, risk flag propagation), `DecisionAgent` (synthesis into Decision Dashboard JSON), `RiskAgent` (7 risk categories, two-level severity with soft/hard override)
- 📈 **Strategy system (Phase 3)** — `StrategyAgent` (per-strategy evaluation from YAML skills), `StrategyRouter` (rule-based regime detection → strategy selection), `StrategyAggregator` (weighted consensus with backtest performance factor)
- 🔬 **Deep Research agent (Phase 5)** — `ResearchAgent` with 3-phase approach (decompose → research sub-questions → synthesise report); token budget tracking; new `/research` bot command with aliases (`/深研`, `/deepsearch`)
- 🧠 **Memory & calibration (Phase 6)** — `AgentMemory` with prediction accuracy tracking, confidence calibration (activates after minimum sample threshold), strategy auto-weighting based on historical win rate
- 📊 **Portfolio Agent (Phase 7)** — `PortfolioAgent` for multi-stock portfolio analysis (position sizing, sector concentration, correlation risk, cross-market linkage, rebalance suggestions)
- 🔔 **Event-driven alerts (Phase 7)** — `EventMonitor` with `PriceAlert`, `VolumeAlert`, `SentimentAlert` rules; async checking, callback notifications, serializable persistence
- ⚙️ **New config entries** — `AGENT_ORCHESTRATOR_MODE`, `AGENT_RISK_OVERRIDE`, `AGENT_DEEP_RESEARCH_BUDGET`, `AGENT_MEMORY_ENABLED`, `AGENT_STRATEGY_AUTOWEIGHT`, `AGENT_STRATEGY_ROUTING` — all registered in `config.py` + `config_registry.py` (WebUI-configurable)

### Changed
- 🔐 **Auth password state semantics** — stored password existence is now tracked independently from auth enablement; when auth is disabled, `/api/v1/auth/status` returns `passwordSet=false` while preserving the saved password for future re-enable
- 🔐 **Auth settings re-enable hardening** — re-enabling auth with a stored password now requires `currentPassword`, and failed session creation rolls back the auth toggle to avoid lockout
- ♻️ **AgentExecutor refactored** — `_run_loop` delegates to shared `runner.run_agent_loop()`; removed duplicated serialization/parsing/thinking-label code
- ♻️ **Unified agent switch** — Bot, API, and Pipeline all use `config.is_agent_available()` instead of divergent `config.agent_mode` checks
- 📖 **README.md** — expanded Bot commands section (ask/chat/strategies/history), added NL routing note, updated agent mode description
- 📖 **.env.example** — added `AGENT_ARCH` and `AGENT_NL_ROUTING` configuration documentation
- 🔌 **Analysis API async contract** — `POST /api/v1/analysis/analyze` now documents distinct async `202` payloads for single-stock vs batch requests, and `report_type=full` is treated consistently with the existing full-report behavior

### Fixed
- 🐛 **Analysis API blank-code guardrails** — `POST /api/v1/analysis/analyze` now drops whitespace-only entries before batch enqueue and returns `400` when no valid stock code remains
- 🐛 **Bare `/api` SPA fallback** — unknown API paths now return JSON `404` consistently for both `/api/...` and the exact `/api` path
- 🎮 **Discord channel env compatibility** — runtime now accepts legacy `DISCORD_CHANNEL_ID` as a fallback for `DISCORD_MAIN_CHANNEL_ID`, and the docs/examples now use the same variable name as the actual workflow/config implementation
- 🐛 **Session secret rotation on Windows** — use atomic replace so auth toggles invalidate existing sessions even when `.session_secret` already exists
- 🐛 **Auth toggle atomicity** — persist `ADMIN_AUTH_ENABLED` before rotating session secret; on rotation failure, roll back to the previous auth state
- 🔧 **LLM runtime selection guardrails** — YAML 模式下渠道编辑器不再覆盖 `LITELLM_MODEL` / fallback / Vision；系统配置校验补上全部渠道禁用后的运行时来源检查，并修复 `vertexai/...` 这类协议别名模型被重复加前缀的问题
- 🐛 **Multi-stock `/ask` follow-up regressions** — portfolio overlay now shares the same timeout budget as the per-stock phase and is skipped on timeout instead of blocking the bot reply; `/history` now stores the readable per-stock summary instead of raw dashboard JSON; condensed multi-stock output now renders numeric `sniper_points` values
- 🐛 **Decision dashboard enum compatibility** — multi-agent `DecisionAgent` now keeps `decision_type` within the legacy `buy|hold|sell` contract and normalizes stray `strong_*` outputs before risk override, pipeline conversion, and downstream统计/通知汇总
- 🛟 **Multi-Agent partial-result fallback** — `IntelAgent` now caches parsed intel for downstream reuse, shared JSON parsing tolerates lightly malformed model output, and the orchestrator preserves/synthesizes a minimal dashboard on timeout or mid-pipeline parse failure instead of always collapsing to `50/观望/未知`
- 🐛 **Shared LiteLLM routing restored** — bot NL intent parsing and `ResearchAgent` planning/synthesis now reuse the same LiteLLM adapter / Router / fallback / `api_base` injection path as the main Agent flow, so `LLM_CHANNELS` / `LITELLM_CONFIG` / OpenAI-compatible deployments behave consistently
- 🐛 **Bot chat session backward compatibility** — `/chat` now keeps using the legacy `{platform}_{user_id}` session id when old history already exists, and `/history` can still list / view / clear those pre-migration sessions alongside the new `{platform}_{user_id}:chat` format
- 🐛 **EventMonitor unsupported rule rejection** — config validation/runtime loading now reject or skip alert types the monitor cannot actually evaluate yet, so schedule mode no longer silently accepts permanent no-op rules
- 🐛 **P0 基本面聚合稳定性修复** (#614) — 修复 `get_stock_info` 板块语义回归（新增 `belong_boards` 并保留 `boards` 兼容别名）、引入基本面上下文精简返回以控制 token、为基本面缓存增加最大条目淘汰，并补齐 ETF 总体状态聚合与 NaN 板块字段过滤，保证 fail-open 与最小入侵。
- 🔧 **GitHub Actions 搜索引擎环境变量补充** — 工作流新增 `MINIMAX_API_KEYS`、`BRAVE_API_KEYS`、`SEARXNG_BASE_URLS` 环境变量映射，使 GitHub Actions 用户可配置 MiniMax、Brave、SearXNG 搜索服务（此前 v3.5.0 已添加 provider 实现但缺少工作流配置）
- 🤖 **Multi-Agent runtime consistency** — `AGENT_MAX_STEPS` now propagates to each orchestrated sub-agent; added cooperative `AGENT_ORCHESTRATOR_TIMEOUT_S` budget to stop overlong pipelines before they cascade further
- 🔌 **Multi-Agent feature wiring** — `AGENT_RISK_OVERRIDE` now actively downgrades final dashboards on hard risk findings; `AGENT_MEMORY_ENABLED` now injects recent analysis memory + confidence calibration into specialised agents; multi-stock `/ask` now runs `PortfolioAgent` to add portfolio-level allocation and concentration guidance
- 🔔 **EventMonitor runtime wiring** — schedule mode can now load alert rules from `AGENT_EVENT_ALERT_RULES_JSON`, poll them at `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, and send triggered alerts through the existing notification service
- 🛠️ **Follow-up stability fixes** — multi-stock `/ask` now falls back to usable text output when dashboard JSON parsing fails; EventMonitor skips semantically invalid rules instead of aborting schedule startup; background alert polling now runs independently of the main scheduled analysis loop
- 🧪 **Multi-Agent regression coverage** — added orchestrator execution tests for `run()`, `chat()`, critical-stage failure, graceful degradation, and timeout handling
- 🧹 **PortfolioAgent cleanup** — `post_process()` now reuses shared JSON parsing and removed stale unused imports
- 🚦 **Bot async dispatch** — `CommandDispatcher` now exposes `dispatch_async()`; NL intent parsing and default command execution are offloaded from the event loop, DingTalk stream awaits async handlers directly, and Feishu stream processing is moved off the SDK callback thread
- 🌐 **Async webhook handler** — new `handle_webhook_async()` function in `bot/handler.py` for use from async contexts (e.g. FastAPI); calls `dispatch_async()` directly without thread bridging
- 🧵 **Feishu stream ThreadPoolExecutor** — replaced unbounded per-message `Thread` spawning with a capped `ThreadPoolExecutor(max_workers=8)` to prevent thread explosion under message bursts
- 🔒 **EventMonitor safety** — `_check_volume()` now safely handles `get_daily_data` returning `None` (no tuple-unpacking crash); `on_trigger` callbacks support both sync and async callables via `asyncio.to_thread`/`await`
- 🧹 **ResearchAgent dedup** — `_filtered_registry()` now delegates to `BaseAgent._filtered_registry()` instead of duplicating the filtering logic
- 🧹 **Bot trailing whitespace cleanup** — removed W291/W293 whitespace issues across `bot/handler.py`, `bot/dispatcher.py`, `bot/commands/base.py`, `bot/platforms/feishu_stream.py`, `bot/platforms/dingtalk_stream.py`
- 🐛 **Dispatcher `_parse_intent_via_llm` safety** — replaced fragile `'raw' in dir()` with `'raw' in locals()` for undefined-variable guard in `JSONDecodeError` handler
- 🐛 **筹码结构 LLM 未填写时兜底补全** (#589) — DeepSeek 等模型未正确填写 `chip_structure` 时，自动用数据源已获取的筹码数据补全，保证各模型展示一致；普通分析与 Agent 模式均生效
- 🐛 **历史报告狙击点位显示原始文本** (#452) — 历史详情页现优先展示 `raw_result.dashboard.battle_plan.sniper_points` 中的原始字符串，避免 `analysis_history` 数值列把区间、说明文字或复杂点位压缩成单个数字；保留原有数值列作为回退
- 🐛 **Session prefix collision** — user ID `123` could see sessions of user `1234` via `startswith`; fixed with colon delimiter in session_id format
- 🐛 **NL pre-filter false positives** — `re.IGNORECASE` caused `[A-Z]{2,5}` to match common English words like "hello"; removed global flag, use inline `(?i:...)` only for English finance keywords
- 🐛 **Dotted ticker in strategy args** — `_get_strategy_args()` didn't recognize `BRK.B` as a stock code, leaving it in strategy text; now accepts `TICKER.CLASS` format
- ⏱️ **efinance 长调用挂起修复** (#660) — 为所有 efinance API 调用引入 `_ef_call_with_timeout()` 包装（默认 30 秒，可通过 `EFINANCE_CALL_TIMEOUT` 配置）；使用 `executor.shutdown(wait=False)` 确保超时后不再阻塞主线程，彻底消除 81 分钟挂起问题
- 🛡️ **类型安全内容完整性检查** (#660) — `check_content_integrity()` 现在将非字符串类型的 `operation_advice` / `analysis_summary` 视为缺失字段，避免下游 `get_emoji()` 因 `dict.strip()` 崩溃
- 📄 **报告保存与通知解耦** (#660) — `_save_local_report()` 不再依赖 `send_notification` 标志触发，`--no-notify` 模式下本地报告照常保存
- 🔄 **operation_advice 字典归一化** (#660) — Pipeline 和 BacktestEngine 现在将 LLM 返回的 `dict` 格式 `operation_advice` 通过 `decision_type`（不区分大小写）映射为标准字符串，防止因模型输出格式变化导致崩溃
- 🛡️ **runner.py usage None 防护** (#660) — `response.usage` 为 `None` 时不再抛出 `AttributeError`，回退为 0 token 计数
- 📋 **orchestrator 静默失败改为日志警告** (#660) — `IntelAgent` / `RiskAgent` 阶段失败现在记录 `WARNING` 而非静默跳过，便于诊断

### Notes
- ⚠️ **Multi-worker auth toggles** — runtime auth updates are process-local; multi-worker deployments must restart/roll workers to keep auth state consistent

## [3.5.0] - 2026-03-12

### Added
- 📊 **Web UI full report drawer** (Fixes #214) — history page adds "Full Report" button to display the complete Markdown analysis report in a side drawer; new `GET /api/v1/history/{record_id}/markdown` endpoint
- 📊 **LLM cost tracking** — all LLM calls (analysis, agent, market review) recorded in `llm_usage` table; new `GET /api/v1/usage/summary?period=today|month|all` endpoint returns aggregated token usage by call type and model
- 🔍 **SearXNG search provider** (Fixes #550) — quota-free self-hosted search fallback; priority: Bocha > Tavily > Brave > SerpAPI > MiniMax > SearXNG
- 🔍 **MiniMax web search provider** — `MiniMaxSearchProvider` with circuit breaker (3 failures → 300s cooldown) and dual time-filtering; configured via `MINIMAX_API_KEYS`
- 🤖 **Agent models discovery API** — `GET /api/v1/agent/models` returns available model deployments (primary/fallback/source/api_base) for Web UI model selector
- 🤖 **Agent chat export & send** (#495) — export conversation to .md file; send to configured notification channels; new `POST /api/v1/agent/chat/send`
- 🤖 **Agent background execution** (#495) — analysis continues when switching pages; badge notification on completion; auto-cancel in-progress stream on session switch
- 📝 **Report Engine P0** — Pydantic schema validation for LLM JSON; Jinja2 templates (markdown/wechat/brief) with legacy fallback; content integrity checks with retry; brief mode (`REPORT_TYPE=brief`); history signal comparison
- 📦 **Smart import** — multi-source import from image/CSV/Excel/clipboard; Vision LLM extracts code+name+confidence; name→code resolver (local map + pinyin + AkShare); confidence-tiered confirmation
- ⚙️ **GitHub Actions LiteLLM config** — workflow supports `LITELLM_CONFIG`/`LITELLM_CONFIG_YAML` for flexible AI provider configuration
- ⚙️ **Config engine refactor & system API** (#602) — unified config registry, validation and API exposure
- 📖 **LLM configuration guide** — new `docs/LLM_CONFIG_GUIDE.md` covering 3-tier config, quick start, Vision/Agent/troubleshooting

### Fixed
- 🐛 **analyze_trend always reports No historical data** (#600) — now fetches from DB/DataFetcher instead of broken `get_analysis_context`
- 🐛 **Chip structure fallback when LLM omits it** (#589) — auto-fills from data source chip data for consistent display across models
- 🐛 **History sniper points show raw text** (#452) — prioritizes original strings over compressed numeric values
- 🐛 **GitHub Actions ENABLE_CHIP_DISTRIBUTION configurable** (#617) — no longer hardcoded, supports vars/secrets override
- 🐛 **`.env` save preserves comments and blank lines** — Web settings no longer destroys `.env` formatting
- 🐛 **Agent model discovery fixes** — legacy mode includes LiteLLM-native providers; source detection aligned with runtime; fallback deployments no longer expanded per-key
- 🐛 **Stooq US stock previous close semantics** — no longer misuses open price as previous close
- 🐛 **Stock name prefetch regression** — prioritizes local `STOCK_NAME_MAP` before remote queries
- 🐛 **AkShare limit-up/down calculation** (#555) — fixed market analysis statistics
- 🐛 **AkShare Tencent source field index & ETF quote mapping** (#579)
- 🐛 **Pytdx stock name cache pagination** (#573) — prevents cache overflow
- 🐛 **PushPlus oversized report chunking** (#489) — auto-segments long content
- 🐛 **Agent chat cancel & switch** (#495) — cancel no longer misreports as failure; fast switch no longer overwrites stream state
- 🐛 **MiniMax search status in `/status` command** (#587)
- 🐛 **config_registry duplicate BOCHA_API_KEYS** — removed duplicate dict entry that silently overwrote config

### Changed
- 🔎 **Fetcher failure observability** — logs record start/success/failure with elapsed time, failover transitions; Efinance/Akshare include upstream endpoint and classified failure categories
- ♻️ **Data source resilience & cleanup** (#602) — fallback chain optimization
- ♻️ **Image extract API response extension** — new `items` field (code/name/confidence); `codes` preserved for backward compatibility
- ♻️ **Import parse error messages** — specific failure reasons for Excel/CSV; improved logging with file type and size

### Docs
- 📖 LLM config guide refactored for clarity (#583)
- 📖 `image-extract-prompt.md` with full prompt documentation
- 📖 AkShare fallback cache TTL documentation
## [3.4.10] - 2026-03-07

### Fixed
- 🐛 **EfinanceFetcher ETF OHLCV data** (#541, #527) — switch `_fetch_etf_data` from `ef.fund.get_quote_history` (NAV-only, no OHLCV, no `beg`/`end` params) to `ef.stock.get_quote_history`; ETFs now return proper open/high/low/close/volume/amount instead of zeros; remove obsolete NAV column mappings from `_normalize_data`
- 🐛 **tiktoken 0.12.0 `Unknown encoding cl100k_base`** (#537) — pin `tiktoken>=0.8.0,<0.12.0` in requirements.txt to avoid plugin-registration regression introduced in 0.12.0
- 🐛 **Web UI API error classification** (#540) — frontend no longer treats every HTTP 400 as the same "server/network" failure; now distinguishes Agent disabled / missing params / model-tool incompatibility / upstream LLM errors / local connection failures
- 🐛 **北交所代码识别失败** (#491, #533) — 8/4/92 开头的 6 位代码现正确识别为北交所；Tushare/Akshare/Yfinance 等数据源支持 .BJ 或 bj 前缀；Baostock/Pytdx 对北交所代码显式切换数据源；避免误判上海 B 股 900xxx
- 🐛 **狙击点位解析错误** (#488, #532) — 理想买入/二次买入等字段在无「元」字时误提取括号内技术指标数字；现先截去第一个括号后内容再提取

### Added
- **Markdown-to-image for dashboard report** (#455, #535) — 个股日报汇总支持 markdown 转图片推送（Telegram、WeChat、Custom、Email），与大盘复盘行为一致
- **markdown-to-file engine** (#455) — `MD2IMG_ENGINE=markdown-to-file` 可选，对 emoji 支持更好，需 `npm i -g markdown-to-file`
- **PREFETCH_REALTIME_QUOTES** (#455) — 设为 `false` 可禁用实时行情预取，避免 efinance/akshare_em 全市场拉取
- **Stock name prefetch** (#455) — 分析前预取股票名称，减少报告中「股票xxxxx」占位符
- 📊 **分析报告模型标记** (#528, #534) — 在分析报告 meta、报告末尾、推送内容中展示 `model_used`（完整 LLM 模型名）；Agent 多轮调用时记录并展示每轮实际使用的模型（支持 fallback 切换）

### Changed
- **Enhanced markdown-to-image failure warning** (#455) — 转图失败时提示具体依赖（wkhtmltopdf 或 m2f）
- **WeChat-only image routing optimization** (#455) — 仅配置企业微信图片时，不再对完整报告做冗余转图，避免误导性失败日志
- **Stock name prefetch lightweight mode** (#455) — 名称预取阶段跳过 realtime quote 查询，减少额外网络开销

## [3.4.9] - 2026-03-06

### Added
- 🧠 **Structured config validation** — `ConfigIssue` dataclass and `validate_structured()` with severity-aware logging; `CONFIG_VALIDATE_MODE=strict` aborts startup on errors
- 🖼️ **Vision model config** — `VISION_MODEL` and `VISION_PROVIDER_PRIORITY` for image stock extraction; provider fallback (Gemini → Anthropic → OpenAI → DeepSeek) when primary fails
- 🚀 **CLI init wizard** — `python -m dsa init` 3-step interactive bootstrap (model → data source → notification), 9 provider presets, incremental merge by default
- 🔧 **Multi-channel LLM support** with visual channel editor (#494)

### Changed
- ♻️ **Vision extraction** — migrated from gemini-3 hardcode to `litellm.completion()` with configurable model and provider fallback; `OPENAI_VISION_MODEL` deprecated in favor of `VISION_MODEL`
- ♻️ **Market analyzer** — uses `Analyzer.generate_text()` for LLM calls; fixes bypass and Anthropic `AttributeError` when using non-Router path
- ♻️ **Config validation refinements** — test_env output format syncs with `validate_structured` (severity-aware ✓/✗/⚠/·); Vision key warning when `VISION_MODEL` set but no provider API key; market_analyzer test covers `generate_market_review` fallback when `generate_text` returns None
- ⚙️ **Auto-tag workflow defaults to NO tag** — only tags when commit message explicitly contains `#patch`, `#minor`, or `#major`
- ♻️ **Formatter and notification refactor** (#516)

### Fixed
- 🐛 **STOCK_LIST not refreshed on scheduled runs** — `.env` or WebUI changes to `STOCK_LIST` now hot-reload before each scheduled analysis (#529)
- 🐛 **WebUI fails to load with MIME type error** — SPA fallback route now resolves correct `Content-Type` for JS/CSS files (#520)
- 🐛 **AstrBot sender docstring misplaced** — `import time` placed before docstring in `_send_astrbot`, causing it to become dead code
- 🐛 **Telegram Markdown link escaping** — `_convert_to_telegram_markdown` escaped `[]()` characters, breaking all Markdown links in reports
- 🐛 **Duplicate `discord_bot_status` field** in Config dataclass — second declaration silently shadowed the first
- 🧹 **Unused imports** — removed `shutil`/`subprocess` from `main.py`
- 🔧 **Config validation and Vision key check** (#525)

### Docs
- 📝 Clarified GitHub Actions non-trading-day manual run controls (`TRADING_DAY_CHECK_ENABLED` + `force_run`) for Issue #461 / PR #466

## [3.4.8] - 2026-03-02

### Fixed
- 🐛 **Desktop exe crashes on startup with `FileNotFoundError`** — PyInstaller build was missing litellm's JSON data files (e.g. `model_prices_and_context_window_backup.json`). Added `--collect-data litellm` to both Windows and macOS build scripts so the files are correctly bundled in the executable.

### CI
- 🔧 Cache Electron binaries on macOS CI runners to prevent intermittent EOF download failures when fetching `electron-vX.Y.Z-darwin-*.zip` from GitHub CDN
- 🔧 Fix macOS DMG `hdiutil Resource busy` error during desktop packaging

### Docs
- 📝 Clarify non-trading-day manual run controls for GitHub Actions (`TRADING_DAY_CHECK_ENABLED` + `force_run`) (#474)

## [3.4.7] - 2026-02-28

### Added
- 🧠 **CN/US Market Strategy Blueprint System** (#395) — market review prompt injects region-specific strategy blueprints with position sizing and risk trigger recommendations

### Fixed
- 🐛 **`TRADING_DAY_CHECK_ENABLED` env var and `--force-run` for GitHub Actions** (#466)
- 🐛 **Agent pipeline preserved resolved stock names** (#464) — placeholder names no longer leak into reports
- 🐛 **Code cleanup** (#462, Fixes #422)
- 🐛 **WebUI auto-build on startup** (#460)
- 🐛 **ARCH_ARGS unbound variable** (#458)
- 🐛 **Time zone inconsistency & right panel flash** (#439)

### Docs
- 📝 Clarify potential ambiguities in code (#343)
- 📝 ENABLE_EASTMONEY_PATCH guidance for Issue #453 (#456)

## [3.4.0] - 2026-02-27

### Added
- 📡 **LiteLLM Direct Integration + Multi API Key Support** (#454, Fixes #421 #428)
  - Removed native SDKs (google-generativeai, google-genai, anthropic); unified through `litellm>=1.80.10`
  - New config: `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`
  - Multi-key auto-builds LiteLLM Router (simple-shuffle) with 429 cooldown
  - **Breaking**: `.env` `GEMINI_MODEL` (no prefix) only for fallback; explicit config must include provider prefix

### Changed
- ♻️ **Notification Refactoring** (#435) — extracted 10 sender classes into `src/notification_sender/`

### Fixed
- 🐛 LLM NoneType crash, history API 422, sniper points extraction
- 🐛 Auto-build frontend on WebUI startup — `WEBUI_AUTO_BUILD` env var (default `true`)
- 🐛 Docker explicit project name (#448)
- 🐛 Bocha search SSL retry (#445, #446) — transient errors retry up to 3 times
- 🐛 Gemini google-genai SDK migration (Fixes #440, #444)
- 🐛 Mobile home page scrolling (Fixes #419, #433)
- 🐛 History list scroll reset (#431)
- 🐛 Settings save button false positive (fixes #417, #430)

## [3.3.22] - 2026-02-26

### Added
- 💬 **Chat History Persistence** (Fixes #400, #414) — `/chat` page survives refresh, sidebar session list
- 🎨 Project VI Assets — logo icon set, PSD, vector, banner (#425)
- 🚀 Desktop CI Auto-Release (#426) — Windows + macOS parallel builds

### Fixed
- 🐛 Agent Reasoning 400 & LiteLLM Proxy (fixes #409, #427)
- 🐛 Discord chunked sending (#413) — `DISCORD_MAX_WORDS` config
- 🐛 yfinance shared DataFrame (#412)
- 🐛 sniper_points parsing (#408)
- 🐛 Agent framework category missing (#406)
- 🐛 Date inconsistency & query id (fixes #322, #363)

## [3.3.12] - 2026-02-24

### Added
- 📈 **Intraday Realtime Technical Indicators** (Issue #234, #397) — MA calculated from realtime price, config: `ENABLE_REALTIME_TECHNICAL_INDICATORS`
- 🤖 **Agent Strategy Chat** (#367) — full ReAct pipeline, 11 YAML strategies, SSE streaming, multi-turn chat
- 📢 PushPlus Group Push — `PUSHPLUS_TOPIC` (#402)
- 📅 Trading Day Check (Issue #373, #375) — `TRADING_DAY_CHECK_ENABLED`, `--force-run`

### Fixed
- 🐛 DeepSeek reasoning mode (Issue #379, #386)
- 🐛 Agent news intel persistence (Fixes #396, #405)
- 🐛 Bare except clauses replaced with `except Exception` (#398)
- 🐛 UUID fallback for HTTP non-secure context (fixes #377, #381)
- 🐛 Docker DNS resolution (Fixes #372, #374)
- 🐛 Agent session/strategy bugs — multiple follow-up fixes for #367
- 🐛 yfinance parallel download data filtering

### Changed
- Market review strategy consistency — unified cn/us template
- Agent test assertions updated (`6 -> 11`)


## [3.2.11] - 2026-02-23

### 修复（#patch）
- 🐛 **StockTrendAnalyzer 从未执行** (Issue #357)
  - 根因：`get_analysis_context` 仅返回 2 天数据且无 `raw_data`，pipeline 中 `raw_data in context` 始终为 False
  - 修复：Step 3 直接调用 `get_data_range` 获取 90 日历天（约 60 交易日）历史数据用于趋势分析
  - 改善：趋势分析失败时用 `logger.warning(..., exc_info=True)` 记录完整 traceback

## [3.2.10] - 2026-02-22

### 新增
- ⚙️ 支持 `RUN_IMMEDIATELY` 配置项，设为 `true` 时定时任务触发后立即执行一次分析，无需等待首个定时点

### 修复
- 🐛 修复 Web UI 页面居中问题
- 🐛 修复 Settings 返回 500 错误

## [3.2.9] - 2026-02-22

### 修复
- 🐛 **ETF 分析仅关注指数走势**（Issue #274）
  - 美股/港股 ETF（如 VOO、QQQ）与 A 股 ETF 不再纳入基金公司层面风险（诉讼、声誉等）
  - 搜索维度：ETF/指数专用 risk_check、earnings、industry 查询，避免命中基金管理人新闻
  - AI 提示：指数型标的分析约束，`risk_alerts` 不得出现基金管理人公司经营风险

## [3.2.8] - 2026-02-21

### 修复
- 🐛 **BOT 与 WEB UI 股票代码大小写统一**（Issue #355）
  - BOT `/analyze` 与 WEB UI 触发分析的股票代码统一为大写（如 `aapl` → `AAPL`）
  - 新增 `canonical_stock_code()`，在 BOT、API、Config、CLI、task_queue 入口处规范化
  - 历史记录与任务去重逻辑可正确识别同一股票（大小写不再影响）

## [3.2.7] - 2026-02-20

### 新增
- 🔐 **Web 页面密码验证**（Issue #320, #349）
  - 支持 `ADMIN_AUTH_ENABLED=true` 启用 Web 登录保护
  - 首次访问在网页设置初始密码；支持「系统设置 > 修改密码」和 CLI `python -m src.auth reset_password` 重置

## [3.2.6] - 2026-02-20
### ⚠️ 破坏性变更（Breaking Changes）

- **历史记录 API 变更 (Issue #322)**
  - 路由变更：`GET /api/v1/history/{query_id}` → `GET /api/v1/history/{record_id}`
  - 参数变更：`query_id` (字符串) → `record_id` (整数)
  - 新闻接口变更：`GET /api/v1/history/{query_id}/news` → `GET /api/v1/history/{record_id}/news`
  - 原因：`query_id` 在批量分析时可能重复，无法唯一标识单条历史记录。改用数据库主键 `id` 确保唯一性
  - 影响范围：使用旧版历史详情 API 的所有客户端需同步更新

### 修复
- 修复美股（如 ADBE）技术指标矛盾：akshare 美股复权数据异常，统一美股历史数据源为 YFinance（Issue #311）
- 🐛 **历史记录查询和显示问题 (Issue #322)**
  - 修复历史记录列表查询中日期不一致问题：使用明天作为 endDate，确保包含今天全天的数据
  - 修复服务器 UI 报告选择问题：原因是多条记录共享同一 `query_id`，导致总是显示第一条。现改用 `analysis_history.id` 作为唯一标识
  - 历史详情、新闻接口及前端组件已全面适配 `record_id`
  - 新增后台轮询（每 30s）与页面可见性变更时静默刷新历史列表，确保 CLI 发起的分析完成后前端能及时同步，使用 `silent` 模式避免触发 loading 状态
- 🐛 **美股指数实时行情与日线数据** (Issue #273)
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 ^GSPC）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源
  - 消除重复的美股识别逻辑，统一使用 `is_us_stock_code()` 函数

### 优化
- 🎨 **首页输入栏与 Market Sentiment 布局对齐优化**
  - 股票代码输入框左缘与历史记录 glass-card 框左对齐
  - 分析按钮右缘与 Market Sentiment 外框右对齐
  - Market Sentiment 卡片向下拉伸填满格子，消除与 STRATEGY POINTS 之间的空隙
  - 窄屏时输入栏填满宽度，响应式对齐保持一致

## [3.2.5] - 2026-02-19

### 新增
- 🌍 **大盘复盘可选区域**（Issue #299）
  - 支持 `MARKET_REVIEW_REGION` 环境变量：`cn`（A股）、`us`（美股）、`both`（两者）
  - us 模式使用 SPX/纳斯达克/道指/VIX 等指数；both 模式可同时复盘 A 股与美股
  - 默认 `cn`，保持向后兼容

## [3.2.4] - 2026-02-18

### 修复
- 🐛 **统一美股数据源为 YFinance**（Issue #311）
  - akshare 美股复权数据异常，统一美股历史数据源为 YFinance
  - 修复 ADBE 等美股股票技术指标矛盾问题

## [3.2.3] - 2026-02-18

### 修复
- 🐛 **标普500实时数据缺失**（Issue #273）
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 `^GSPC`）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源

## [3.2.2] - 2026-02-16

### 新增
- 📊 **PE 指标支持**（Issue #296）
  - AI System Prompt 增加 PE 估值关注
- 📰 **新闻时效性筛查**（Issue #296）
  - `NEWS_MAX_AGE_DAYS`：新闻最大时效（天），默认 3，避免使用过时信息
- 📈 **强势趋势股乖离率放宽**（Issue #296）
  - `BIAS_THRESHOLD`：乖离率阈值（%），默认 5.0，可配置
  - 强势趋势股（多头排列且趋势强度 ≥70）自动放宽乖离率到 1.5 倍

## [3.2.1] - 2026-02-16

### 新增
- 🔧 **东财接口补丁可配置开关**
  - 支持 `EFINANCE_PATCH_ENABLED` 环境变量开关东财接口补丁（默认 `true`）
  - 补丁不可用时可降级关闭，避免影响主流程

## [3.2.0] - 2026-02-15

### 新增
- 🔒 **CI 门禁统一（P0）**
  - 新增 `scripts/ci_gate.sh` 作为后端门禁单一入口
  - 主 CI 改为 `backend-gate`、`docker-build`、`web-gate` 三段式
  - CI 触发改为所有 PR，避免 Required Checks 因路径过滤缺失而卡住合并
  - `web-gate` 支持前端路径变更按需触发
  - 新增 `network-smoke` 工作流承载非阻断网络场景回归
- 📦 **发布链路收敛（P0）**
  - `docker-publish` 调整为 tag 主触发，并增加发布前门禁校验
  - 手动发布增加 `release_tag` 输入与 semver/changelog 强校验
  - 发布前新增 Docker smoke（关键模块导入）
- 📝 **PR 模板升级（P0）**
  - 增加背景、范围、验证命令与结果、回滚方案、Issue 关联等必填项
- 🤖 **AI 审查覆盖增强（P0）**
  - `pr-review` 纳入 `.github/workflows/**` 范围
  - 新增 `AI_REVIEW_STRICT` 开关，可选将 AI 审查失败升级为阻断

## [3.1.13] - 2026-02-15

### 新增
- 📊 **仅分析结果摘要**（Issue #262）
  - 支持 `REPORT_SUMMARY_ONLY` 环境变量，设为 `true` 时只推送汇总，不含个股详情
  - 默认 `false`，多股时适合快速浏览

## [3.1.12] - 2026-02-15

### 新增
- 📧 **个股与大盘复盘合并推送**（Issue #190）
  - 支持 `MERGE_EMAIL_NOTIFICATION` 环境变量，设为 `true` 时将个股分析与大盘复盘合并为一次推送
  - 默认 `false`，减少邮件数量、降低被识别为垃圾邮件的风险

## [3.1.11] - 2026-02-15

### 新增
- 🤖 **Anthropic Claude API 支持**（Issue #257）
  - 支持 `ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`ANTHROPIC_TEMPERATURE`、`ANTHROPIC_MAX_TOKENS`
  - AI 分析优先级：Gemini > Anthropic > OpenAI
- 📷 **从图片识别股票代码**（Issue #257）
  - 上传自选股截图，通过 Vision LLM 自动提取股票代码
  - API: `POST /api/v1/stocks/extract-from-image`；支持 JPEG/PNG/WebP/GIF，最大 5MB
  - 支持 `OPENAI_VISION_MODEL` 单独配置图片识别模型
- ⚙️ **通达信数据源手动配置**（Issue #257）
  - 支持 `PYTDX_HOST`、`PYTDX_PORT` 或 `PYTDX_SERVERS` 配置自建通达信服务器

## [3.1.10] - 2026-02-15

### 新增
- ⚙️ **立即运行配置**（Issue #332）
  - 支持 `RUN_IMMEDIATELY` 环境变量，`true` 时定时任务启动后立即执行一次
- 🐛 修复 Docker 构建问题

## [3.1.9] - 2026-02-14

### 新增
- 🔌 **东财接口补丁机制**
  - 新增 `patch/eastmoney_patch.py` 修复 efinance 上游接口变更
  - 不影响其他数据源的正常运行

## [3.1.8] - 2026-02-14

### 新增
- 🔐 **Webhook 证书校验开关**（Issue #265）
  - 支持 `WEBHOOK_VERIFY_SSL` 环境变量，可关闭 HTTPS 证书校验以支持自签名证书
  - 默认保持校验，关闭存在 MITM 风险，仅建议在可信内网使用

## [3.1.7] - 2026-02-14

### 修复
- 🐛 修复包导入错误（package import error）

## [3.1.6] - 2026-02-13

### 修复
- 🐛 修复 `news_intel` 中 `query_id` 不一致问题

## [3.1.5] - 2026-02-13

### 新增
- 📷 **Markdown 转图片通知**（Issue #289）
  - 支持 `MARKDOWN_TO_IMAGE_CHANNELS` 配置，对 Telegram、企业微信、自定义 Webhook（Discord）、邮件发送图片格式报告
  - 邮件为内联附件，增强对不支持 HTML 客户端的兼容性
  - 需安装 `wkhtmltopdf` 和 `imgkit`

## [3.1.4] - 2026-02-12

### 新增
- 📧 **股票分组发往不同邮箱**（Issue #268）
  - 支持 `STOCK_GROUP_N` + `EMAIL_GROUP_N` 配置，不同股票组报告发送到对应邮箱
  - 大盘复盘发往所有配置的邮箱

## [3.1.3] - 2026-02-12

### 修复
- 🐛 修复 Docker 内运行时通过页面修改配置报错 `[Errno 16] Device or resource busy` 的问题

## [3.1.2] - 2026-02-11

### 修复
- 🐛 修复 Docker 一致性问题，解决关键批次处理与通知 Bug

## [3.1.1] - 2026-02-11

### 变更
- ♻️ `API_HOST` → `WEBUI_HOST`：Docker Compose 配置项统一

## [3.1.0] - 2026-02-11

### 新增
- 📊 **ETF 支持增强与代码规范化**
  - 统一各数据源 ETF 代码处理逻辑
  - 新增 `canonical_stock_code()` 统一代码格式，确保数据源路由正确

## [3.0.5] - 2026-02-08

### 修复
- 🐛 修复信号 emoji 与建议不一致的问题（复合建议如"卖出/观望"未正确映射）
- 🐛 修复 `*ST` 股票名在微信/Dashboard 中 markdown 转义问题
- 🐛 修复 `idx.amount` 为 None 时大盘复盘 TypeError
- 🐛 修复分析 API 返回 `report=None` 及 ReportStrategy 类型不一致问题
- 🐛 修复 Tushare 返回类型错误（dict → UnifiedRealtimeQuote）及 API 端点指向

### 新增
- 📊 大盘复盘报告注入结构化数据（涨跌统计、指数表格、板块排名）
- 🔍 搜索结果 TTL 缓存（500 条上限，FIFO 淘汰）
- 🔧 Tushare Token 存在时自动注入实时行情优先级
- 📰 新闻摘要截断长度 50→200 字

### 优化
- ⚡ 补充行情字段请求限制为最多 1 次，减少无效请求

## [3.0.4] - 2026-02-07

### 新增
- 📈 **回测引擎** (PR #269)
  - 新增基于历史分析记录的回测系统，支持收益率、胜率、最大回撤等指标评估
  - WebUI 集成回测结果展示

## [3.0.3] - 2026-02-07

### 修复
- 🐛 修复狙击点位数据解析错误问题 (PR #271)

## [3.0.2] - 2026-02-06

### 新增
- ✉️ 可配置邮件发送者名称 (PR #272)
- 🌐 外国股票支持英文关键词搜索

## [3.0.1] - 2026-02-06

### 修复
- 🐛 修复 ETF 实时行情获取、市场数据回退、企业微信消息分块问题
- 🔧 CI 流程简化

## [3.0.0] - 2026-02-06

### 移除
- 🗑️ **移除旧版 WebUI**
  - 删除基于 `http.server.ThreadingHTTPServer` 的旧版 WebUI（`web/` 包）
  - 旧版 WebUI 的功能已完全被 FastAPI（`api/`）+ React 前端替代
  - `--webui` / `--webui-only` 命令行参数标记为弃用，自动重定向到 `--serve` / `--serve-only`
  - `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` 环境变量保持兼容，自动转发到 FastAPI 服务
  - `webui.py` 保留为兼容入口，启动时直接调用 FastAPI 后端
  - Docker Compose 中移除 `webui` 服务定义，统一使用 `server` 服务

### 变更
- ♻️ **服务层重构**
  - 将 `web/services.py` 中的异步任务服务迁移至 `src/services/task_service.py`
  - Bot 分析命令（`bot/commands/analyze.py`）改为使用 `src.services.task_service`
  - Docker 环境变量 `WEBUI_HOST`/`WEBUI_PORT` 更名为 `API_HOST`/`API_PORT`（旧名仍兼容）

## [2.3.0] - 2026-02-01

### 新增
- 🇺🇸 **增强美股支持** (Issue #153)
  - 实现基于 Akshare 的美股历史数据获取 (`ak.stock_us_daily()`)
  - 实现基于 Yfinance 的美股实时行情获取（优先策略）
  - 增加对不支持数据源（Tushare/Baostock/Pytdx/Efinance）的美股代码过滤和快速降级

### 修复
- 🐛 修复 AMD 等美股代码被误识别为 A 股的问题 (Issue #153)

## [2.2.5] - 2026-02-01

### 新增
- 🤖 **AstrBot 消息推送** (PR #217)
  - 新增 AstrBot 通知渠道，支持推送到 QQ 和微信
  - 支持 HMAC SHA256 签名验证，确保通信安全
  - 通过 `ASTRBOT_URL` 和 `ASTRBOT_TOKEN` 配置

## [2.2.4] - 2026-02-01

### 新增
- ⚙️ **可配置数据源优先级** (PR #215)
  - 支持通过环境变量（如 `YFINANCE_PRIORITY=0`）动态调整数据源优先级
  - 无需修改代码即可优先使用特定数据源（如 Yahoo Finance）

## [2.2.3] - 2026-01-31

### 修复
- 📦 更新 requirements.txt，增加 `lxml_html_clean` 依赖以解决兼容性问题

## [2.2.2] - 2026-01-31

### 修复
- 🐛 修复代理配置区分大小写问题 (fixes #211)

## [2.2.1] - 2026-01-31

### 修复
- 🐛 **YFinance 兼容性修复** (PR #210, fixes #209)
  - 修复新版 yfinance 返回 MultiIndex 列名导致的数据解析错误

## [2.2.0] - 2026-01-31

### 新增
- 🔄 **多源回退策略增强**
  - 实现了更健壮的数据获取回退机制 (feat: multi-source fallback strategy)
  - 优化了数据源故障时的自动切换逻辑

### 修复
- 🐛 修复 analyzer 运行后无法通过改 .env 文件的 stock_list 内容调整跟踪的股票

## [2.1.14] - 2026-01-31

### 文档
- 📝 更新 README 和优化 auto-tag 规则

## [2.1.13] - 2026-01-31

### 修复
- 🐛 **Tushare 优先级与实时行情** (Fixed #185)
  - 修复 Tushare 数据源优先级设置问题
  - 修复 Tushare 实时行情获取功能

## [2.1.12] - 2026-01-30

### 修复
- 🌐 修复代理配置在某些情况下的区分大小写问题
- 🌐 修复本地环境禁用代理的逻辑

## [2.1.11] - 2026-01-30

### 优化
- 🚀 **飞书消息流优化** (PR #192)
  - 优化飞书 Stream 模式的消息类型处理
  - 修改 Stream 消息模式默认为关闭，防止配置错误运行时报错

## [2.1.10] - 2026-01-30

### 合并
- 📦 合并 PR #154 贡献

## [2.1.9] - 2026-01-30

### 新增
- 💬 **微信文本消息支持** (PR #137)
  - 新增微信推送的纯文本消息类型支持
  - 添加 `WECHAT_MSG_TYPE` 配置项

## [2.1.8] - 2026-01-30

### 修复
- 🐛 修正日志中 API 提供商显示错误 (PR #197)

## [2.1.7] - 2026-01-30

### 修复
- 🌐 禁用本地环境的代理设置，避免网络连接问题

## [2.1.6] - 2026-01-29

### 新增
- 📡 **Pytdx 数据源 (Priority 2)**
  - 新增通达信数据源，免费无需注册
  - 多服务器自动切换
  - 支持实时行情和历史数据
- 🏷️ **多源股票名称解析**
  - DataFetcherManager 新增 `get_stock_name()` 方法
  - 新增 `batch_get_stock_names()` 批量查询
  - 自动在多数据源间回退
  - Tushare 和 Baostock 新增股票名称/列表方法
- 🔍 **增强搜索回退**
  - 新增 `search_stock_price_fallback()` 用于数据源全部失败时
  - 新增搜索维度：市场分析、行业分析
  - 最大搜索次数从 3 增加到 5
  - 改进搜索结果格式（每维度 4 条结果）

### 改进
- 更新搜索查询模板以提高相关性
- 增强 `format_intel_report()` 输出结构

## [2.1.5] - 2026-01-29

### 新增
- 📡 新增 Pytdx 数据源和多源股票名称解析功能

## [2.1.4] - 2026-01-29

### 文档
- 📝 更新赞助商信息

## [2.1.3] - 2026-01-28

### 文档
- 📝 重构 README 布局
- 🌐 新增繁体中文翻译 (README_CHT.md)

### 修复
- 🐛 修复 WebUI 无法输入美股代码问题
  - 输入框逻辑改成所有字母都转换成大写
  - 支持 `.` 的输入（如 `BRK.B`）

## [2.1.2] - 2026-01-27

### 修复
- 🐛 修复个股分析推送失败和报告路径问题 (fixes #166)
- 🐛 修改 CR 错误，确保微信消息最大字节配置生效

## [2.1.1] - 2026-01-26

### 新增
- 🔧 添加 GitHub Actions auto-tag 工作流
- 📡 添加 yfinance 兜底数据源及数据缺失警告

### 修复
- 🐳 修复 docker-compose 路径和文档命令
- 🐳 Dockerfile 补充 copy src 文件夹 (fixes #145)

## [2.1.0] - 2026-01-25

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 📈 **MACD 和 RSI 技术指标**
  - MACD：趋势确认、金叉死叉信号（零轴上金叉⭐、金叉✅、死叉❌）
  - RSI：超买超卖判断（超卖⭐、强势✅、超买⚠️）
  - 指标信号纳入综合评分系统
- 🎮 **Discord 推送支持** (PR #124, #125, #144)
  - 支持 Discord Webhook 和 Bot API 两种方式
  - 通过 `DISCORD_WEBHOOK_URL` 或 `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` 配置
- 🤖 **机器人命令交互**
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
- 🌡️ **AI 温度参数可配置** (PR #142)
  - 支持自定义 AI 模型温度参数
- 🐳 **Zeabur 部署支持**
  - 添加 Zeabur 镜像部署工作流
  - 支持 commit hash 和 latest 双标签

### 重构
- 🏗️ **项目结构优化**
  - 核心代码移至 `src/` 目录，根目录更清爽
  - 文档移至 `docs/` 目录
  - Docker 配置移至 `docker/` 目录
  - 修复所有 import 路径，保持向后兼容
- 🔄 **数据源架构升级**
  - 新增数据源熔断机制，单数据源连续失败自动切换
  - 实时行情缓存优化，批量预取减少 API 调用
  - 网络代理智能分流，国内接口自动直连
- 🤖 Discord 机器人重构为平台适配器架构

### 修复
- 🌐 **网络稳定性增强**
  - 自动检测代理配置，对国内行情接口强制直连
  - 修复 EfinanceFetcher 偶发的 `ProtocolError`
  - 增加对底层网络错误的捕获和重试机制
- 📧 **邮件渲染优化**
  - 修复邮件中表格不渲染问题 (#134)
  - 优化邮件排版，更紧凑美观
- 📢 **企业微信推送修复**
  - 修复大盘复盘推送不完整问题
  - 增强消息分割逻辑，支持更多标题格式
  - 增加分批发送间隔，避免限流丢失
- 👷 **CI/CD 修复**
  - 修复 GitHub Actions 中路径引用的错误

## [2.0.0] - 2026-01-24

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 🤖 **机器人命令交互** (PR #113)
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
  - 支持选择精简报告或完整报告
- 🎮 **Discord 推送支持** (PR #124)
  - 支持 Discord Webhook 推送
  - 添加 Discord 环境变量到工作流

### 修复
- 🐳 修复 WebUI 在 Docker 中绑定 0.0.0.0 (fixed #118)
- 🔔 修复飞书长连接通知问题
- 🐛 修复 `analysis_delay` 未定义错误
- 🔧 启动时 config.py 检测通知渠道，修复已配置自定义渠道情况下仍然提示未配置问题

### 改进
- 🔧 优化 Tushare 优先级判断逻辑，提升封装性
- 🔧 修复 Tushare 优先级提升后仍排在 Efinance 之后的问题
- ⚙️ 配置 TUSHARE_TOKEN 时自动提升 Tushare 数据源优先级
- ⚙️ 实现 4 个用户反馈 issue (#112, #128, #38, #119)

## [1.6.0] - 2026-01-19

### 新增
- 🖥️ WebUI 管理界面及 API 支持（PR #72）
  - 全新 Web 架构：分层设计（Server/Router/Handler/Service）
  - 核心 API：支持 `/analysis` (触发分析), `/tasks` (查询进度), `/health` (健康检查)
  - 交互界面：支持页面直接输入代码并触发分析，实时展示进度
  - 运行模式：新增 `--webui-only` 模式，仅启动 Web 服务
  - 解决了 [#70](https://github.com/ZhuLinsen/daily_stock_analysis/issues/70) 的核心需求（提供触发分析的接口）
- ⚙️ GitHub Actions 配置灵活性增强（[#79](https://github.com/ZhuLinsen/daily_stock_analysis/issues/79)）
  - 支持从 Repository Variables 读取非敏感配置（如 STOCK_LIST, GEMINI_MODEL）
  - 保持对 Secrets 的向下兼容

### 修复
- 🐛 修复企业微信/飞书报告截断问题（[#73](https://github.com/ZhuLinsen/daily_stock_analysis/issues/73)）
  - 移除 notification.py 中不必要的长度硬截断逻辑
  - 依赖底层自动分片机制处理长消息
- 🐛 修复 GitHub Workflow 环境变量缺失（[#80](https://github.com/ZhuLinsen/daily_stock_analysis/issues/80)）
  - 修复 `CUSTOM_WEBHOOK_BEARER_TOKEN` 未正确传递到 Runner 的问题

## [1.5.0] - 2026-01-17

### 新增
- 📲 单股推送模式（[#55](https://github.com/ZhuLinsen/daily_stock_analysis/issues/55)）
  - 每分析完一只股票立即推送，不用等全部分析完
  - 命令行参数：`--single-notify`
  - 环境变量：`SINGLE_STOCK_NOTIFY=true`
- 🔐 自定义 Webhook Bearer Token 认证（[#51](https://github.com/ZhuLinsen/daily_stock_analysis/issues/51)）
  - 支持需要 Token 认证的 Webhook 端点
  - 环境变量：`CUSTOM_WEBHOOK_BEARER_TOKEN`

## [1.4.0] - 2026-01-17

### 新增
- 📱 Pushover 推送支持（PR #26）
  - 支持 iOS/Android 跨平台推送
  - 通过 `PUSHOVER_USER_KEY` 和 `PUSHOVER_API_TOKEN` 配置
- 🔍 博查搜索 API 集成（PR #27）
  - 中文搜索优化，支持 AI 摘要
  - 通过 `BOCHA_API_KEYS` 配置
- 📊 Efinance 数据源支持（PR #59）
  - 新增 efinance 作为数据源选项
- 🇭🇰 港股支持（PR #17）
  - 支持 5 位代码或 HK 前缀（如 `hk00700`、`hk1810`）

### 修复
- 🔧 飞书 Markdown 渲染优化（PR #34）
  - 使用交互卡片和格式化器修复渲染问题
- ♻️ 股票列表热重载（PR #42 修复）
  - 分析前自动重载 `STOCK_LIST` 配置
- 🐛 钉钉 Webhook 20KB 限制处理
  - 长消息自动分块发送，避免被截断
- 🔄 AkShare API 重试机制增强
  - 添加失败缓存，避免重复请求失败接口

### 改进
- 📝 README 精简优化
  - 高级配置移至 `docs/full-guide.md`


## [1.3.0] - 2026-01-12

### 新增
- 🔗 自定义 Webhook 支持
  - 支持任意 POST JSON 的 Webhook 端点
  - 自动识别钉钉、Discord、Slack、Bark 等常见服务格式
  - 支持配置多个 Webhook（逗号分隔）
  - 通过 `CUSTOM_WEBHOOK_URLS` 环境变量配置

### 修复
- 📝 企业微信长消息分批发送
  - 解决自选股过多时内容超过 4096 字符限制导致推送失败的问题
  - 智能按股票分析块分割，每批添加分页标记（如 1/3, 2/3）
  - 批次间隔 1 秒，避免触发频率限制

## [1.2.0] - 2026-01-11

### 新增
- 📢 多渠道推送支持
  - 企业微信 Webhook
  - 飞书 Webhook（新增）
  - 邮件 SMTP（新增）
  - 自动识别渠道类型，配置更简单

### 改进
- 统一使用 `NOTIFICATION_URL` 配置，兼容旧的 `WECHAT_WEBHOOK_URL`
- 邮件支持 Markdown 转 HTML 渲染

## [1.1.0] - 2026-01-11

### 新增
- 🤖 OpenAI 兼容 API 支持
  - 支持 DeepSeek、通义千问、Moonshot、智谱 GLM 等
  - Gemini 和 OpenAI 格式二选一
  - 自动降级重试机制

## [1.0.0] - 2026-01-10

### 新增
- 🎯 AI 决策仪表盘分析
  - 一句话核心结论
  - 精确买入/止损/目标点位
  - 检查清单（✅⚠️❌）
  - 分持仓建议（空仓者 vs 持仓者）
- 📊 大盘复盘功能
  - 主要指数行情
  - 涨跌统计
  - 板块涨跌榜
  - AI 生成复盘报告
- 🔍 多数据源支持
  - AkShare（主数据源，免费）
  - Tushare Pro
  - Baostock
  - YFinance
- 📰 新闻搜索服务
  - Tavily API
  - SerpAPI
- 💬 企业微信机器人推送
- ⏰ 定时任务调度
- 🐳 Docker 部署支持
- 🚀 GitHub Actions 零成本部署

### 技术特性
- Gemini AI 模型（gemini-3-flash-preview）
- 429 限流自动重试 + 模型切换
- 请求间延时防封禁
- 多 API Key 负载均衡
- SQLite 本地数据存储

---

[Unreleased]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.22.0...HEAD
[3.22.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.1...v3.22.0
[3.21.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.0...v3.21.1
[3.21.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.20.0...v3.21.0
[3.20.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.19.0...v3.20.0
[3.19.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.18.0...v3.19.0
[3.18.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.1...v3.18.0
[3.17.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.0...v3.17.1
[3.17.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.16.0...v3.17.0
[3.16.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.15.0...v3.16.0
[3.15.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.2...v3.15.0
[3.14.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.12.0...v3.13.0
[3.12.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.11.0...v3.12.0
[3.11.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.1...v3.11.0
[3.10.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.0...v3.10.1
[3.10.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.9.0...v3.10.0
[3.9.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.10...v3.5.0
[3.4.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.9...v3.4.10
[3.4.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.8...v3.4.9
[3.4.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.7...v3.4.8
[3.4.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.0...v3.4.7
[3.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.22...v3.4.0
[3.3.22]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.12...v3.3.22
[3.3.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.11...v3.3.12
[3.2.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.10...v3.2.11
[2.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.5...v2.3.0
[2.2.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.4...v2.2.5
[2.2.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.14...v2.2.0
[2.1.14]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.13...v2.1.14
[2.1.13]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.12...v2.1.13
[2.1.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.11...v2.1.12
[2.1.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.9...v2.1.10
[2.1.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.8...v2.1.9
[2.1.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.7...v2.1.8
[2.1.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.6...v2.1.7
[2.1.6]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.5...v2.1.6
[2.1.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.6.0...v2.0.0
[1.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v1.0.0

- [chore] Draft PR preparation: branch feat/watchlist-panel cut at f9f8641, awaiting review.
