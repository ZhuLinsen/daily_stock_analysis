# DSA 内部因子契约（#1902 P0）

本文件定义 DSA 内部因子契约的首版：后端 schema 与序列化，不含持久化、API、Agent/DecisionSignal 与前端改动。契约是纯新增结构，现有选股、API、回测与 DecisionSignal 行为不受影响。

## 版本

- 契约版本（`FACTOR_CONTRACT_VERSION`）：`1.0`。schema 结构变化时升级。
- 因子集版本（`FACTOR_SET_VERSION`）：`1.0`。9 因子清单或任一因子的计算方式变化时升级。

两个版本各自独立升级，且同时记录在每次快照与运行上，避免后验评估在不知情的情况下混合不同因子集。

## 因子清单

因子定义见 `src/services/screening/factor_mapping.py` 的 `factor_definitions()`；计算见 `src/services/screening/scorer.py`。测试 `test_factor_definitions_cover_all_scorer_factors` 保证清单与 `factor_score_columns()` 一致，因子清单变化时测试会失败，强制契约升级。

| `factor_id` | 评分列 | 分类 | 单位 | 窗口 |
|---|---|---|---|---|
| `value` | `factor_value_score` | valuation | `score_0_100` | — |
| `liquidity` | `factor_liquidity_score` | liquidity | `score_0_100` | — |
| `momentum` | `factor_momentum_score` | technical | `score_0_100` | `60d` |
| `reversal` | `factor_reversal_score` | technical | `score_0_100` | `60d` |
| `activity` | `factor_activity_score` | technical | `score_0_100` | — |
| `stability` | `factor_stability_score` | technical | `score_0_100` | `20d` |
| `size` | `factor_size_score` | liquidity | `score_0_100` | — |
| `theme_heat` | `factor_theme_heat_score` | theme | `score_0_100` | — |
| `topic_alignment` | `factor_topic_alignment_score` | theme | `score_0_100` | — |

所有分数为 0–100 浮点数，保留 4 位小数（`compute_screen_scores` 的 `series.round(4)`）。

## 类型

实现见 `src/schemas/factor_contract.py`（仅 Pydantic 与标准库，不依赖 pandas、screening 或 services）。

### `FactorDefinition`

单个因子的身份与计算来源，不含个股数据。

| 字段 | 类型 | 说明 |
|---|---|---|
| `factor_id` | 9 个 id 的 `Literal` | 封闭集合，扩展需契约升级 |
| `name` | `str` | 展示名，如 `Value` |
| `category` | `FactorCategory` | `valuation` / `liquidity` / `technical` / `theme`，仅描述性元数据，不影响评分 |
| `unit` | `str` | 现均为 `score_0_100` |
| `definition` | `str` | 一句话计算描述，来自 scorer 实现 |
| `version` | `str` | 单因子定义版本，默认 `"1"` |
| `source` | `str` | `screening.scorer:<评分列>` |
| `window` | `str \| None` | 回看窗口（如 `60d`），无固定窗口时为 `None` |
| `params` | `dict[str, float]` | 静态定义中的参数覆盖；空表示未记录覆盖，不代表实际策略未覆盖评分参数（见下注） |
| `factor_set_version` | `str` | `FACTOR_SET_VERSION` |

> **注意：** `factor_definitions()` 当前返回静态定义（见 `src/services/screening/factor_mapping.py`），`params` 默认为 `{}`。`params={}` 只表示静态定义未记录参数覆盖，不代表实际策略未覆盖评分参数；实际参数追溯（本次运行真实生效的评分参数）需在 P1 接线时补齐。

### `FactorDataQuality`

单次观测的数据质量。

| 字段 | 类型 | 说明 |
|---|---|---|
| `coverage` | `float \| None` | 0.0–1.0；未知时为 `None`，绝不编造 |
| `missing_rate` | `float \| None` | 0.0–1.0；未知时为 `None` |
| `status` | `FactorFieldStatus` | `available` / `missing` / `partial` / `fallback` / `stale` |
| `degradation_reason` | `str \| None` | 降级原因；干净时为 `None` |
| `limitations` / `warnings` | `list[str]` | 仅低敏自由文本 |

### `CandidateFactorScore`

一次运行中一只候选股的一个因子值，即 `Pick.factor_scores` 中一个条目的类型化替代。

| 字段 | 类型 | 说明 |
|---|---|---|
| `factor_id` | `str` | 自由字符串，观测需经受 scorer 漂移 |
| `value` | `float` | 0–100 闭区间；非有限值拒绝 |
| `weight` | `float \| None` | `ScreenResult.effective_factor_weights` 中的有效权重；`None` 表示未加权，`0.0` 表示显式禁用，两者不等同 |
| `quality` | `FactorDataQuality` | 默认干净；`coverage` / `missing_rate` 在 `Pick` 层恒为 `None`（见下） |
| `computed_at` | `datetime` | UTC |

### `FactorSnapshot`

一次运行中一只候选股的全部因子分数。

| 字段 | 类型 | 说明 |
|---|---|---|
| `contract_version` | `Literal["1.0"]` | `FACTOR_CONTRACT_VERSION`，不可变 |
| `candidate_pool_run_id` | `str` | `ScreenResult.run_id`，非空 |
| `code` / `name` | `str` / `str \| None` | `Pick.code` / `Pick.name`；`code` 非空 |
| `rank` | `int \| None` | 候选股在候选池中的整体排名，来自 `Pick.rank`（1 起）；未知时为 `None`，永不为 0 |
| `factor_set_version` | `str` | `FACTOR_SET_VERSION` |
| `scores` | `dict[str, CandidateFactorScore]` | 按 `factor_id` 索引；仅含 `Pick.factor_scores` 中存在的因子；键必须与条目的 `factor_id` 一致；原地写入（`scores[key] = ...`）同样拒绝键与 `factor_id` 不一致的条目 |
| `screen_score` | `float \| None` | `Pick.screen_score`，只读追溯字段；非有限值拒绝 |
| `quality` | `FactorDataQuality` | 聚合质量：`coverage` = 存在的已知因子数 / 9 |
| `source` | `str` | `screening.pipeline` |
| `computed_at` | `datetime` | UTC |

### `CandidatePoolRun`

运行信封：`ScreenResult` 头字段的类型化视图。P0 不持久化，持久化归 P1。

字段：`contract_version`、`run_id`（非空）、`strategy`、`strategy_version`、`strategy_category`、`market`、`factor_set_version`、`effective_factor_weights`（原样复制，含显式 `0.0`；非有限值拒绝）、`candidate_count`、`snapshot_count`、`after_filter_count`（三者均 `>= 0`）、`snapshot_source`、`source_errors`、`degradation`、`ranking_mode`、`created_at`。

## 封闭性约定

- 不引入 `metadata` 万能字段：契约封闭且版本化，新增内容需随版本升级加入；将来 P2/P3 若确实需要，可在向后兼容的 minor 升级中加入。
- 未知 JSON 键按 Pydantic 默认忽略（不使用 `extra="forbid"`），与 `AnalysisContextPack` 一致：同一 `contract_version` 下新版本生产者写入的载荷可被旧版本读取，保证前向兼容。不同 `contract_version` 的载荷会被版本字面量拒绝，不适用该兼容性说明。

## 暂缓字段与原因

以下字段在 issue #1902 的 P0 草图中出现，但当前 scorer / 引擎中不存在对应数据，或语义尚不属于因子契约，故暂缓；需要时随版本升级加入，不得编造。

| 字段 | 原因 |
|---|---|
| `FactorDefinition.direction`（因子方向） | scorer 只产出 0–100 分数，没有方向字段；方向需 scorer 先支持 |
| `FactorDefinition` 适用市场 | 因子计算不区分市场；市场归属在运行层（`CandidatePoolRun.market`） |
| `FactorDefinition` 计算依赖 | 依赖已由 `source` / `window` / `params` 承载其实际可得的部分；完整依赖图需 scorer 先暴露 |
| `CandidateFactorScore.rank`（单因子池内排名） | 需要整池数据，逐 `Pick` 映射无法计算；快照级的整体排名见 `FactorSnapshot.rank` |
| `FactorSnapshot.final_score` | 构造时与 `screen_score` 相同，之后经 LLM 混合、DSA 叠加、风险惩罚等流水线后处理改写，含义随调用点变化且不再是纯因子数据；因子追溯字段为 `screen_score` |

## 映射规则

实现见 `src/services/screening/factor_mapping.py`，纯函数，无副作用，P0 无调用方。

- 只映射 `Pick.factor_scores` 中存在的条目；不重算分数，不读 DataFrame，不碰 scorer。
- `Pick.rank` 原样映射到 `FactorSnapshot.rank`（整体排名，1 起）；`Pick.final_score` 不映射（见暂缓字段表）。
- 缺失的因子不合成为 `0.0` 或 `50.0`。快照聚合质量按已知因子存在数 / 9 计算；全部缺失时 `status` 为 `missing`，部分缺失时为 `partial`。
- 未知的 `factor_id` 照常携带，并在 `quality.warnings` 与 `degradation_reason` 中记录，绝不静默丢弃。
- 非有限值（NaN/±Inf）在映射层以 `ValueError` 大声失败，不进入契约；契约内所有浮点字段亦由 `allow_inf_nan=False` 统一拒绝非有限值。
- 输入（`Pick`、`ScreenResult`）绝不修改；输出为全新的 Pydantic 模型。
- 覆盖率诚实约束：`Pick` 层只能知道某因子存在与否，无法知道其输入列覆盖率，因此单个 `CandidateFactorScore.quality` 的 `coverage` / `missing_rate` 恒为 `None`；只有快照聚合的 存在数/9 是诚实的分数。
- 时间戳语义：`ScreenResult.created_at` 自 86cd500 起为带本地偏移的 ISO 字符串（`datetime.now().astimezone()` 在部署进程时钟上产生，部署默认 `TZ=Asia/Shanghai`）；旧的无偏移值在回拨期间按第一次出现映射，并在 `CandidatePoolRun.degradation` 与快照 `quality.warnings` 中记录歧义。映射时无时区值按本地时间读取并换算为 UTC，换算按输入日期的本地时区规则确定偏移（夏令时感知，跨夏令时日期不套用执行当天的固定偏移），绝不直接贴 `Z`，带偏移的值转为 UTC，仅日期字符串按当日本地午夜换算为 UTC，无法解析时回退到映射执行时间（UTC）并在 `CandidatePoolRun.degradation` 中记录一条降级条目，绝不静默回退。契约内一律使用带时区的 `datetime`，不混用 naive/aware（schema 层对三个时间戳字段做归一化兜底）。P1 可进一步推动 `models.py` 直接发出 UTC 时间戳，消除对本地时钟的依赖。

## P1 接入示意

P0 无调用方；P1 预期在 `pipeline.screen()` 返回 `ScreenResult` 后调用映射函数（P1 决定唯一调用点，不在 `_df_to_picks` 内接线）：

```python
from src.services.screening.factor_mapping import (
    screen_result_to_factor_snapshots,
    screen_result_to_pool_run,
)

pool_run = screen_result_to_pool_run(result)
snapshots = screen_result_to_factor_snapshots(result)
```

## 非目标

- 无持久化/仓储，无 API 端点/字段，无 Agent/DecisionSignal 接线，无前端改动，无新配置项与环境变量。
- 不改变 `BacktestService.get_skill_summary` 返回 `None` 的既有行为；不把全局胜率复制进任何因子类型。
- 不引入 `metadata` 万能字段：契约封闭且版本化，新增内容需随版本升级加入。

## 升级规则

- schema 结构变化（增删字段、改类型、改约束）→ 升级 `FACTOR_CONTRACT_VERSION`，并同步更新 `Literal["1.0"]` 字段与版本守卫。
- 因子清单或任一因子计算变化 → 升级 `FACTOR_SET_VERSION`，并同步更新 `factor_definitions()` 与本文件的因子表；`test_factor_definitions_cover_all_scorer_factors` 只检测因子清单漂移（新增/删除/改名），同名因子的计算公式变化它检测不到，改公式时必须随手升级版本，不能等测试提醒。
- 权重语义见 `docs/screening-engine.md`：运行元数据保留有限非负权重（含 `0.0`），理由/解释文本只消费正权重。

## 关联

- Issue #1902（P0 阶段：先落 DSA 内部因子契约）。
- 前例：`src/schemas/analysis_context_pack.py`（#1389 P1 契约）与 `tests/test_analysis_context_pack_schema.py`。
