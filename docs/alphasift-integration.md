# AlphaSift 选股集成说明

数据源失败、fallback 链路和 Tushare / TickFlow / AkShare 等已接入源的推荐配置图示见 [数据源稳定性与故障处理图示](data-source-stability.md)。

AlphaSift 作为独立仓库维护的选股引擎接入 DSA。DSA 默认不启用它，也不把 AlphaSift 的策略逻辑复制进主仓库；后端依赖会随 `requirements.txt` 安装，启用后只通过 `alphasift.dsa_adapter` 稳定适配层调用 AlphaSift。

## 当前方案

- 默认关闭：`ALPHASIFT_ENABLED=false`。
- 启用入口：设置页或选股页点击开启，或在 `.env` 中配置 `ALPHASIFT_ENABLED=true`。
- 依赖来源：`requirements.txt` 固定到已验证的 AlphaSift 适配层 commit：`git+https://github.com/ZhuLinsen/alphasift.git@0a7b9cd59e81718f851890535241bc105d4ddc64#egg=alphasift`（对应提交 `https://github.com/ZhuLinsen/alphasift/commit/0a7b9cd59e81718f851890535241bc105d4ddc64`，覆盖 PR `https://github.com/ZhuLinsen/alphasift/pull/16`、`https://github.com/ZhuLinsen/alphasift/pull/19`、`https://github.com/ZhuLinsen/alphasift/pull/22`、`https://github.com/ZhuLinsen/alphasift/pull/23`、`https://github.com/ZhuLinsen/alphasift/pull/24`、`https://github.com/ZhuLinsen/alphasift/pull/25`、`https://github.com/ZhuLinsen/alphasift/pull/26`、`https://github.com/ZhuLinsen/alphasift/pull/28`、`https://github.com/ZhuLinsen/alphasift/pull/29`、`https://github.com/ZhuLinsen/alphasift/pull/30`、`https://github.com/ZhuLinsen/alphasift/pull/31`、`https://github.com/ZhuLinsen/alphasift/pull/32`、`https://github.com/ZhuLinsen/alphasift/pull/33` 与 `https://github.com/ZhuLinsen/alphasift/pull/35`）。该来源覆盖 `alphasift.dsa_adapter` 契约、`screen/list_strategies/get_status` 调用、Tencent 日 K、Sina snapshot、source health、stale daily fallback、候选级 quote context、日线数据源健康度/降级诊断、硬过滤瀑布诊断、策略评估摘要、题材匹配得分，以及 LLM ranking 的 `LLM_MAX_TOKENS` 输出上限、timeout 后不重复 JSON-mode 重试和更稳健的 JSON 解析边界。
- 修复安装来源：`ALPHASIFT_INSTALL_SPEC` 仍保留，默认等于同一个受信任 commit。它不再是策略列表或选股接口的运行时安装主路径，只用于显式调用 `/api/v1/alphasift/install` 时做修复安装和来源校验；未显式配置时才按代码常量 `DEFAULT_ALPHASIFT_INSTALL_SPEC` 回退。
- 迁移边界（显式 `.env` 优先）：
  - 若 `.env` 中显式保留旧 pin（如 `...de54ea0da367be85770d9589a5bf7ded4f62d386`），DSA 会把该值当作用户覆盖，不会在运行期自动替换为新 pin；
  - 升级后若要启用新 commit，请手动清理该行/改写后并重建依赖；
  - `ALPHASIFT_INSTALL_SPEC` 与 `/api/v1/alphasift/install` allow-list 强绑定，单改 `.env` 而不同时回退 `requirements.txt` 与 `src/config.py` 常量会被 `alphasift_install_spec_not_allowed` 拒绝。
- 回退方式：
  - 路径 A（业务快速回退，约 5 分钟）：设置 `ALPHASIFT_ENABLED=false` 并重启，恢复原始分析链路；
  - 路径 B（适配层版本回退）：同步回退 `requirements.txt`、`src/config.py`（`DEFAULT_ALPHASIFT_INSTALL_SPEC`）与 `.env.example` 示例值，重新安装依赖后重建后端镜像/桌面产物。
- 缺失依赖边界：如果运行环境缺少 `alphasift.dsa_adapter`，`status` 返回 `available=false + diagnostics.reason=missing_module`；`strategies` 和 `screen` 返回 `424` 并提示执行 `pip install -r requirements.txt` 或重建 Docker/桌面后端产物，不会在业务请求中自动 `pip install`。
- 运行异常边界：若适配层可导入但 `get_status()` 报错或返回 `available=false`，DSA 返回 `424 + diagnostics`，保留故障诊断，防止用重装掩盖真实运行时错误。
- 策略归属：策略列表、策略参数、全市场快照、初筛、因子评分和 LLM 重排由 AlphaSift 负责；DSA 负责开关、API 壳、数据 provider、展示和错误提示。

## 外部契约来源与迁移边界

- 外部契约依据：本次 AlphaSift 运行契约（含 `schema_version=2` 的热点缓存与题材详情字段）对应 GitHub 提交 `https://github.com/ZhuLinsen/alphasift/commit/0a7b9cd59e81718f851890535241bc105d4ddc64`。
  该 commit 在 DSA 中通过以下链路生效：`requirements.txt` 安装 pin、`src/config.py` 默认 `DEFAULT_ALPHASIFT_INSTALL_SPEC`、`.env.example` 默认示例值。
- 升级路径：
  - 部署侧只需按部署方式 `git pull` + `pip install -r requirements.txt` + 重启服务；
  - 接入新行为前请确认 `ALPHASIFT_INSTALL_SPEC` 未显式覆盖为旧值；
  - 已手动配置 `ALPHASIFT_INSTALL_SPEC` 时，DSA 仅在调用 `install` 时校验来源，不做运行期静默迁移，不会替换原值。
- 回滚边界（两条路径）：
  - 路径 A（业务临时回退，5 分钟内可执行）：将 `ALPHASIFT_ENABLED=false` 并重启服务/进程。核心分析、日报报表与原有 LLM 调用链路不受该开关影响；此路径不影响依赖版本。
  - 路径 B（适配层版本回滚）：恢复到上一个版本的 `requirements.txt` 与 `src/config.py`（`DEFAULT_ALPHASIFT_INSTALL_SPEC`）到旧值，并同步回退 `.env.example` 的默认示例，重建后端镜像/桌面后端产物（等价于完整 revert 本次 PR）后重启。仅改 `.env` 回退 `ALPHASIFT_INSTALL_SPEC` 会被当前 allow-list 拒绝，必须与 `requirements.txt` 与代码 allow-list 一起回退。
  - 安装入口说明：`/api/v1/alphasift/install` 仅允许当前代码 `ALLOWED_ALPHASIFT_INSTALL_SPECS`（目前为单值集合）中的来源。若确有需要临时接入其他来源，先在环境中手动安装并确认适配层可导入，再重启服务。
- 兼容说明：`ALPHASIFT_INSTALL_SPEC` 只影响 `install` 调用时的来源校验；`requirements.txt` 与 `src/config.py` 的常量是实际运行时源码约束。`status` 返回 `install_spec_is_default` 可快速判断当前配置是否与 DSA 代码默认源一致。

- DSA 增强：AlphaSift 通过 DSA provider context 在 LLM 重排前只补充 Top 候选的轻量实时行情和基本面上下文，不在初筛阶段抓新闻；DSA API 返回阶段会对最终 Top 候选补新闻和辅助摘要，并通过 `dsa_enrichment` 记录复用或补全情况。
- 日 K 线补特征：DSA 调用 AlphaSift 时会优先复用 DSA 历史行情加载链路（数据库缓存、Tushare、Efinance、Akshare、Pytdx、Baostock、Yfinance 等 fallback），仅在 DSA 链路无可用数据时回退到 AlphaSift 原始日线数据源，减少单一上游超时拖垮选股。
- LLM 环境：DSA 调用 AlphaSift 时会桥接 DSA 已解析的 `LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`LLM_CHANNELS`、`LLM_<NAME>_*`、`LITELLM_CONFIG`、渠道额外请求头和各模型密钥；AlphaSift 独立运行时仍使用自己的 `.env`/环境变量。`LLM_TIMEOUT_SEC` 与 `LLM_MAX_TOKENS` 可被 AlphaSift 选股 LLM 重排读取，分别限制单次请求耗时和输出 token 上限。
- 快照源：DSA 调用 AlphaSift 时，未显式配置 `SNAPSHOT_SOURCE_PRIORITY` 会按 token-aware 顺序注入：有 `TUSHARE_TOKEN` 时为 `tushare,sina,efinance,akshare_em,em_datacenter`，无 token 时为 `sina,efinance,akshare_em,em_datacenter`；同时注入 `DAILY_SOURCE=auto`、`DAILY_FETCH_RETRIES=3`、`DAILY_FETCH_MAX_WORKERS=1` 和默认候选上下文 `news,fund_flow,announcement,quote`。显式配置的源顺序、日线源和候选上下文 provider 会原样保留。
- 最新 AlphaSift 能力：锁定 commit `0a7b9cd59e81718f851890535241bc105d4ddc64` 包含选股 pipeline 性能优化、Tencent 日 K、Sina snapshot、source health、stale daily fallback、candidate quote context、LLM ranking timeout/max tokens 边界、last-good snapshot fallback、日线历史缓存、行业/概念 provider cache、热点/行业热度因子、hotspot 热点题材榜单、本地 scorecard/post-analysis 元信息、日线数据源健康度排序与告警、硬过滤瀑布诊断、策略评估摘要、多窗口价格路径评估和题材匹配得分。DSA 调用时会注入隔离缓存默认路径 `data/alphasift`、`data/alphasift/snapshot.last_good.json`、`data/alphasift/daily_history`、`data/alphasift/industry_provider_cache`；Web 选股页提供“热点题材”手动刷新入口，请求 `/api/v1/alphasift/hotspots` 时会显式使用 `akshare` provider 优先拉取具体概念/题材异动（例如钼、铅锌、铜、诊断服务等实时板块异动），行业板块仅作为兜底；默认打开页面时优先读取上一次成功且不少于 3 条的热点题材缓存，点击刷新才实时拉取并覆盖缓存，实时拉取失败时会尽量回退旧缓存；如果 AlphaSift 合约层只返回少量或缺少涨跌幅等关键字段的热点，DSA 会用东方财富板块异动直连榜单替代。点击题材会请求 `/api/v1/alphasift/hotspots/{topic}` 展示发酵路线与概念股；题材详情另有 DSA 侧 30 分钟磁盘缓存，路径为 `data/alphasift/hotspot_details` 或自定义 `ALPHASIFT_DATA_DIR/hotspot_details`，重复点开同一题材会优先返回缓存，实时详情失败时可回退过期缓存；手动刷新热点榜单并保留当前题材时会对详情请求传入 `refresh=true` 绕过详情缓存；不会默认触发 AlphaSift 的 DSA deep-analysis 回调，避免无提示扩大递归调用面。
- 热点刷新容错：`/api/v1/alphasift/hotspots` 未显式传入 provider 且未配置 `INDUSTRY_PROVIDER` 时，默认使用 DSA EastMoney 兜底 provider（响应中 provider 为 `akshare`），避免落到 AlphaSift 的空 provider 路径；东方财富热点直连源遇到连接中断、超时或 `Connection aborted` 会做短 backoff 重试；手动刷新失败且没有可用热点缓存时返回稳定空态 payload、`source_errors=["eastmoney_hotspot_unavailable"]` 和用户可读 `message`，原始异常仅保留在服务端日志或诊断链路中。桌面端更新会保留 `data/alphasift/hotspots.json`、`data/alphasift/hotspot.history.jsonl`、`data/alphasift/hotspot_details` 与 `data/alphasift/snapshot.last_good.json`，避免更新后丢失 last-good 缓存。
- 热点数据源补充：DSA provider 使用直连 HTTP 思路，东财板块兜底源使用 `push2.eastmoney.com/api/qt/clist/get` 并保留涨跌幅、领涨股、上涨/下跌家数等字段；题材详情会在一次 provider 生命周期内缓存并合并东方财富成分股、同花顺页面解析和板块异动龙头兜底，优先返回多只概念股，发酵路线按日期聚合展示，避免把同一盘中观察拆成多条同时间节点；事件催化不再使用 DSA 内置静态文案，只展示 AlphaSift 合约时间线、同花顺摘要、已配置新闻搜索源或东财板块异动结构拿到的真实信息；新闻搜索命中的消息会优先通过已配置 LLM 压缩成一句题材催化摘要，LLM 不可用时回退本地短摘要，避免在时间线中展示完整报道。
- 风险提示：前端设置页和选股页展示第三方来源与投资风险说明；不会弹窗打断用户。

## AlphaSift 适配层要求

AlphaSift 需要提供 `alphasift.dsa_adapter` 模块，并保持以下稳定函数：

- `/api/v1/alphasift/hotspots` 支持 `include_details=true`：列表响应会尽量附带 Top 题材的 `details` 映射，Web 端默认启用，用于批量复用发酵路线和概念股缓存，减少切换不同题材时的二次等待。

```python
def get_status() -> dict: ...
def list_strategies() -> list[dict]: ...
def screen(
    strategy: str,
    *,
    market: str = "cn",
    max_results: int = 20,
    use_llm: bool = True,
    context: dict | None = None,
) -> dict: ...
```

`get_status()` 建议返回：

```json
{
  "available": true,
  "contract_version": "1",
  "version": "0.2.0",
  "strategy_count": 8,
  "supported_markets": ["cn"]
}
```

`list_strategies()` 至少返回 `id`，建议同时返回 `name`、`description`、`category`、`tags`、`market_scope`。

`screen()` 返回值建议包含：

```json
{
  "run_id": "20260531-...",
  "strategy": "dual_low",
  "market": "cn",
  "snapshot_count": 100,
  "after_filter_count": 5,
  "llm_ranked": true,
  "llm_coverage": 1.0,
  "warnings": [],
  "source_errors": [],
  "candidates": []
}
```

候选项建议包含 `code`、`name`、`score`、`reason`、`risk_level`、`risk_flags`、`price`、`change_pct`、`amount`、`industry`、`factor_scores`，以及 LLM 字段：`llm_score`、`llm_confidence`、`llm_thesis`、`llm_catalysts`、`llm_risks`、`llm_watch_items` 等。

DSA 会在支持 `context` 的适配层中传入：

```python
context = {
    "llm": {
        "model": "...",
        "fallback_models": [...],
        "channels": [...],
        "model_list": [...],
    },
    "dsa": {
        "contract_version": "1",
        "mode": "pre_rank_light",
        "max_candidates": 3,
        "include_news": False,
        "news_max_results": 0,
        "capabilities": ["candidate_context", "daily_history", "realtime_quote", "fundamental_context"],
        "get_candidate_context": callable,
        "get_daily_history": callable,
        "get_realtime_quote": callable,
        "get_fundamental_context": callable,
    },
}
```

AlphaSift 会在 L1 初筛后、LLM 重排前调用 `context["dsa"]` 中的 provider，为有限 Top 候选补充 DSA 行情和基本面轻量上下文，并把 `dsa_context` 随候选返回。新闻搜索、完整摘要和缺失字段补全由 DSA API 在最终 Top 候选阶段执行；若候选已经携带完整新闻上下文，DSA API 返回阶段会复用这些字段，避免重复请求。

AlphaSift 侧已在 `ZhuLinsen/alphasift@0a7b9cd59e81718f851890535241bc105d4ddc64` 提供 DSA provider context 支持、DSA adapter contract，并支持复用 DSA 的 `LLM_TIMEOUT_SEC`；同一 pin 还会读取 `LLM_MAX_TOKENS` 限制 LLM 重排输出，且 timeout 后不再盲目重试无 JSON mode 请求。

## DSA 后端行为

- `/api/v1/alphasift/status`：返回开关、可用性、默认安装来源标识、适配层元信息和 AlphaSift 进程内 snapshot/daily source health；不会暴露完整安装来源。
- `/api/v1/alphasift/install`：显式修复安装入口。桌面模式（`DSA_DESKTOP_MODE=true`）不要求管理员会话，非桌面部署必须启用 `ADMIN_AUTH_ENABLED=true` 并携带有效管理员会话，否则返回 `401/403`。接口只允许默认受信任安装来源，并会强制重装锁定 commit，避免旧版 `alphasift` 包残留。
- `/api/v1/alphasift/strategies`：读取 AlphaSift 策略列表；如果 `ALPHASIFT_ENABLED=true` 但适配层缺失或状态异常，返回 `424 + diagnostics`，不触发运行时安装。
- `/api/v1/alphasift/screen`：调用适配层 `screen(..., use_llm=True)`，并在调用期间临时注入 DSA 已解析的 LLM 运行环境，同时向适配层传入结构化 LLM/DSA provider 配置；AlphaSift 在 LLM 前只消费轻量 DSA provider context，并优先通过 DSA 日线链路补齐 AlphaSift 因子特征，DSA 返回阶段对最终 Top 候选补新闻并复用已增强字段。适配层缺失或运行时异常返回 `424 + diagnostics` 并保留原始错误边界。
- `/api/v1/alphasift/screen/tasks`：Web/桌面选股页使用的后台任务入口，提交后立即返回 `task_id`，实际选股在共享任务队列中继续执行，避免浏览器长请求被外部快照、行情、新闻或 LLM 延迟拖到超时。
- `/api/v1/alphasift/screen/tasks/{task_id}`：查询后台选股任务状态。进行中返回 `pending/processing + progress/message`，完成后在 `result` 中返回与 `/screen` 相同的候选结构，失败时返回 `failed + error`；仅接受 `report_type=alphasift_screen` 的任务 ID，普通分析任务不会被误读为选股结果。

## 配置兼容边界（LLM / LiteLLM / Base URL）

- 兼容语义与版本证据（可追溯）：
  - 运行依赖约束：`requirements.txt` 中将 LiteLLM 固定到 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`，并通过 `git+https://github.com/ZhuLinsen/alphasift.git@0a7b9cd59e81718f851890535241bc105d4ddc64` 安装 AlphaSift 适配层。
  - 文档依据：
    - LiteLLM Providers: https://docs.litellm.ai/docs/providers
    - LiteLLM OpenAI-compatible: https://docs.litellm.ai/docs/providers/openai_compatible
    - LiteLLM model_list/proxy 配置（含 `api_base`、`api_key`、`extra_headers`）: https://docs.litellm.ai/docs/proxy/configs
    - OpenAI 请求语义与授权头: https://platform.openai.com/docs/api-reference/making-requests、https://platform.openai.com/docs/api-reference/authentication

- 结构化检测澄清：本 PR 触及 `.env.example`、`requirements.txt`、`src/config.py` 与本文档，是因为 AlphaSift 依赖 pin 更新和调用期 runtime bridge 需要把既有 DSA LLM 配置透传给外部适配层；本 PR 没有升级 LiteLLM 主版本、没有新增或改名 provider 协议、没有修改 `LITELLM_MODEL`/`LITELLM_FALLBACK_MODELS`/`LLM_CHANNELS`/`LLM_<NAME>_*` 的持久化解析语义。
- LLM 运行时兼容边界：AlphaSift 不改变主配置链路，只在调用期注入已解析的 `LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`LLM_CHANNELS` 与 `LLM_<NAME>_*` 到进程环境；受管 provider 的 fallback 过滤行为保持现有策略，不做历史配置的静默迁移。`ALPHASIFT_ENABLED` 是当前场景唯一新增持久化分支。
- 注意：本注入是**短时内存注入**，不会改写 `.env`、不会回写历史配置、不会静默迁移用户自定义 provider/model 路由；失败或未开启时，除了 AlphaSift 选股能力本身，其它 DSA 业务链路保持既有配置执行。
- 注入来源与回滚原则：
  - `LITELLM_MODEL` 与 `LITELLM_FALLBACK_MODELS`优先来自 DSA 已声明路由：`LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`llm_model_list`；未声明的自定义 provider/model 将保留用户原始配置，不被重写。
  - `OPENAI_BASE_URL` 优先复用主配置的 `OPENAI_BASE_URL`，只有未配置时才会回退到声明为 openai 的 `LLM_CHANNEL` base_url；不会覆盖主配置中的私有网关或别名配置。
  - `LLM_<NAME>_API_KEYS/BASE_URL/MODELS` 仅按声明渠道合并注入；未声明渠道不会新增注入字段。
- 若已有自定义模型名、channel、Base URL 或额外头信息，开启/重试 AlphaSift 不会自动覆写 `.env`。如需回退可按原配置恢复：
  - 回退到旧模型名：直接修改 `LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`，或清空自定义 `LLM_CHANNELS`。
  - 恢复旧渠道：保留历史 `LLM_<NAME>_API_KEYS/BASE_URL` 并重启配置生效，不需执行额外迁移脚本。
- 兼容校验依据（运维核验）：
  - 依赖版本依据：当前服务端约束为 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`（见 `requirements.txt`），AlphaSift 只复用该依赖的 provider/model 解析、`model_list` 与调用参数语义。
  - 官方 provider/model 依据：LiteLLM Providers 文档（[https://docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers)）定义 provider 前缀；OpenAI-compatible 文档（[https://docs.litellm.ai/docs/providers/openai_compatible](https://docs.litellm.ai/docs/providers/openai_compatible)）说明 `openai/<model>`、`api_base`、`api_key` 的兼容语义。
  - 官方 `model_list`/额外头依据：LiteLLM config 文档（[https://docs.litellm.ai/docs/proxy/configs](https://docs.litellm.ai/docs/proxy/configs)）说明 `litellm_params` 支持 `model`、`api_base`、`api_key` 与 `extra_headers`。DSA 只把已声明渠道转换为同类结构传给 AlphaSift，不新增模型路由映射，不做 provider 模式迁移。
  - 兼容头部语义依据：OpenAI 调用约定（[https://platform.openai.com/docs/api-reference/making-requests](https://platform.openai.com/docs/api-reference/making-requests)）与鉴权约定（[https://platform.openai.com/docs/api-reference/authentication](https://platform.openai.com/docs/api-reference/authentication)）对应 `Authorization` 与自定义 header 传递行为，`extra_headers` 仅用于补充会话头，不改写模型路由。
  - 回退路径为“设置页关闭 AlphaSift 或保留 `ALPHASIFT_ENABLED=false`”，并保持原有 `LITELLM_*` 与 `LLM_*` 配置，触发失败时可先核对 `status`/`screen` 的 `diagnostics` 后执行服务重启。
- 旧配置保留证据：
  - `src/services/alphasift_service.py` 的 `_alphasift_runtime_env()` 会在调用前保存同名 `os.environ` 值，并在调用后逐项恢复或删除本次临时新增键；该路径不调用 `dotenv_values()` 写回，也不修改 `.env` 文件。
  - `src/services/alphasift_service.py` 的 `_build_alphasift_runtime_env()` 只从当前 `Config` 生成临时 env dict；未声明渠道不会生成 `LLM_<NAME>_*`，已有自定义 provider/model/base URL 不会被重命名或清理。
  - `tests/test_alphasift_api.py` 覆盖 `test_screen_bridges_dsa_llm_config_into_alphasift_runtime`、`test_screen_bridges_legacy_openai_fields_into_alphasift_runtime_env`、`test_screen_injects_openai_compatible_model_headers_into_alphasift_litellm_calls`、`test_screen_disabled_preserves_existing_llm_env_state` 和 `test_screen_filters_undeclared_managed_fallbacks_for_dsa_routes`，用于证明注入、OpenAI-compatible header/base URL、关闭状态和未声明 fallback 均不改写用户原始配置。
- 失败可见性：`status`/`screen` 接口返回明确错误码与 `message`，前端在设置页或选股页会将 `403/424/400/422` 等错误直接提示给用户，便于定位并回退到“关闭 AlphaSift + 保持原有 LLM 运行链路”。

## 兼容验收索引（发布前核验）

- 依赖与源码约束核验：`requirements.txt` 中的 `litellm` 约束与 `src/config.py`/`requirements.txt` 一致。
- Hotspot 契约兼容核验：`docs/alphasift-integration.md` 与 `api/v1/endpoints/alphasift.py`、`src/services/alphasift_service.py` 保持 `hotspots`/`hotspots/{topic}` 字段与 `tests/test_alphasift_api.py` 一致，调用前后默认使用 `snapshot.last_good` 缓存兜底。
- 外部版本来源：本次集成依赖来源为 `https://github.com/ZhuLinsen/alphasift/commit/0a7b9cd59e81718f851890535241bc105d4ddc64`，需在复验时按该 commit pin 回放导入与接口契约。
- 行为核验：`src/services/alphasift_service.py` 的 `_build_alphasift_runtime_env` 与 `_build_alphasift_context` 仅在调用期写入进程环境；`/api/v1/alphasift/screen`、`strategies`、`status` 在运行期不回写 `.env`。
- 回退核验：关闭 `ALPHASIFT_ENABLED` 并重启配置链路后，系统恢复原始 `LITELLM_MODEL/FALLBACK_MODELS`、`LLM_CHANNELS` 与 `LLM_*` 运行语义，不执行迁移清理脚本。
- 语义来源核验：LiteLLM 文档（https://docs.litellm.ai/docs/providers）、OpenAI-compatible 文档（https://docs.litellm.ai/docs/providers/openai_compatible）与 LiteLLM 配置文档（https://docs.litellm.ai/docs/proxy/configs）用于核对 provider/model/base_url/extra_headers 映射链路。
- 状态诊断：`/api/v1/alphasift/status` 对 AlphaSift 包或 `alphasift.dsa_adapter` 未安装仍保持 `200` + `available=false` 的兼容语义；如果导入过程、`get_status()` 调用或返回结构出现非预期异常，后端会记录 warning，并在响应中追加不含安装来源明文的 `diagnostics` 字段，便于从接口状态和服务端日志定位问题。

错误策略：

- 未开启返回 `403 alphasift_disabled`。
- 修复安装接口来源不受信任返回 `403 alphasift_install_spec_not_allowed`。
- AlphaSift 未安装、缺少适配层或适配层不可调用返回 `424`。
- 市场或策略被适配层拒绝时返回 `400/422`。
- 运行失败返回 `424 alphasift_screen_failed`。

## Web 行为

- 设置页提供 AlphaSift 开关，开启后写入 `ALPHASIFT_ENABLED=true` 并检查适配层是否可用；若缺失，会回滚开关并提示执行 `pip install -r requirements.txt` 或重建 Docker/桌面后端产物。
- `ALPHASIFT_ENABLED` 是“开启选股”按钮背后的持久化状态，不作为普通数据源配置项重复展示。
- 选股页未开启时展示开启按钮；开启后读取 AlphaSift 策略列表。
- 当前只暴露 A 股 `cn` 市场。
- 默认返回数量为 3，避免一次选股过慢或结果过多。
- 选股页通过后台任务提交和状态轮询获取结果；任务 ID 会保存在当前浏览器 tab 的 `sessionStorage`，切换页面后返回选股页会继续恢复进度或最终结果。后端重启或任务被清理时，前端会提示任务不可恢复并允许重新运行。
- 结果页展示运行 ID、样本数量、过滤后数量、LLM 是否重排、LLM 覆盖率和 DSA 增强计数；如果 AlphaSift 返回 warning/source error/LLM parse error 或 `llm_ranked=false`，页面会明确显示降级原因，避免把本地因子结果误展示成正常 LLM 判断；重复的快照源 fallback warning/source error 会在前端合并展示为一条“数据源降级”提示。
- 展开候选时展示 AlphaSift 摘要、因子和 LLM 判断；若 DSA 已增强，还会展示 `DSA 增强摘要`、`DSA 新闻` 和 `DSA 增强提示`。

## 桌面端说明

源码运行的桌面端复用同一个 Python 后端环境，并设置 `DSA_DESKTOP_MODE=true`；通过设置页开启时如缺少适配层，会提示更新依赖或重建后端产物。

打包后的桌面端不依赖运行期 `pip install`：Windows/CI 使用 `scripts/build-backend.ps1`，macOS 使用 `scripts/build-backend-macos.sh`，两者均先执行 `pip install -r requirements.txt`，再校验并收集 `alphasift.dsa_adapter` 进 PyInstaller 产物。发布包默认仍关闭；用户在 Web 设置页开启后会先检查适配层，若打包产物异常缺失，应重建或更新桌面后端。

## Docker 说明

Docker 镜像与桌面发布包保持一致：`docker/Dockerfile` 会通过 `requirements.txt` 安装 AlphaSift 并校验 `alphasift.dsa_adapter` 可导入。容器运行时默认仍关闭 AlphaSift；用户通过 `ALPHASIFT_ENABLED=true` 或 Web 设置页开启后使用镜像内置依赖，若运行环境缺失适配层，应重新构建镜像。

## 验证记录

- `python -m pytest tests/test_alphasift_api.py -q`
- `python -m pytest tests/test_main_schedule_mode.py -q -k "start_api_server_fails_before_thread_when_port_is_busy"`
- `python -m py_compile api/v1/endpoints/alphasift.py src/services/alphasift_service.py tests/test_alphasift_api.py src/config.py src/core/config_registry.py`
- `cd apps/dsa-web && npm run test -- alphasift.test.ts StockScreeningPage.test.tsx SettingsPage.test.tsx --run`
- `cd apps/dsa-web && npm run lint`
- `cd apps/dsa-web && npm run build`

## 回滚

- 关闭功能：设置页关闭 AlphaSift，或配置 `ALPHASIFT_ENABLED=false`。
- 版本回退：如需降级 alphasift 适配层，必须同时回退仓库 `requirements.txt` 与 `src/config.py` 中受信任的 pin，否则仅改 `.env` 的 `ALPHASIFT_INSTALL_SPEC` 会被 `alphasift_install_spec_not_allowed` 拒绝；确认后重建依赖与重启服务。
- 特殊来源：如需使用默认来源之外的 AlphaSift 安装包，先在后端 Python 环境完成手动安装并确认 `alphasift.dsa_adapter` 可导入，随后再重启服务（安装前不要触发 `/api/v1/alphasift/install` 的 allow-list 校验路径）。
- 回滚代码：移除 AlphaSift API 注册、Web 选股入口和相关配置项即可恢复到集成前流程；默认关闭状态下不会影响原有股票分析、报告生成和通知流程。
