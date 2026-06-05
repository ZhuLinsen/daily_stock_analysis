# AlphaSift 选股集成说明

AlphaSift 作为独立仓库维护的选股引擎接入 DSA。DSA 默认不启用它，也不把 AlphaSift 的策略逻辑复制进主仓库；后端依赖会随 `requirements.txt` 安装，启用后只通过 `alphasift.dsa_adapter` 稳定适配层调用 AlphaSift。

## 当前方案

- 默认关闭：`ALPHASIFT_ENABLED=false`。
- 启用入口：设置页或选股页点击开启，或在 `.env` 中配置 `ALPHASIFT_ENABLED=true`。
- 依赖来源：`requirements.txt` 固定到已验证的 AlphaSift 适配层 commit：`git+https://github.com/ZhuLinsen/alphasift.git@1a0ed8c99b3615c0cb1076e6029827ffc6de2344#egg=alphasift`。该来源覆盖 `alphasift.dsa_adapter` 契约与 `screen/list_strategies/get_status` 调用。
- 修复安装来源：`ALPHASIFT_INSTALL_SPEC` 仍保留，默认等于同一个受信任 commit。它不再是策略列表或选股接口的运行时安装主路径，只用于显式调用 `/api/v1/alphasift/install` 时做修复安装和来源校验。
- 缺失依赖边界：如果运行环境缺少 `alphasift.dsa_adapter`，`status` 返回 `available=false + diagnostics.reason=missing_module`；`strategies` 和 `screen` 返回 `424` 并提示执行 `pip install -r requirements.txt` 或重建 Docker/桌面后端产物，不会在业务请求中自动 `pip install`。
- 运行异常边界：若适配层可导入但 `get_status()` 报错或返回 `available=false`，DSA 返回 `424 + diagnostics`，保留故障诊断，防止用重装掩盖真实运行时错误。
- 策略归属：策略列表、策略参数、全市场快照、初筛、因子评分和 LLM 重排由 AlphaSift 负责；DSA 负责开关、API 壳、数据 provider、展示和错误提示。
- DSA 增强：AlphaSift 通过 DSA provider context 在 LLM 重排前只补充 Top 候选的轻量实时行情和基本面上下文，不在初筛阶段抓新闻；DSA API 返回阶段会对最终 Top 候选补新闻和辅助摘要，并通过 `dsa_enrichment` 记录复用或补全情况。
- 日 K 线补特征：DSA 调用 AlphaSift 时会优先复用 DSA 历史行情加载链路（数据库缓存、Tushare、Efinance、Akshare、Pytdx、Baostock、Yfinance 等 fallback），仅在 DSA 链路无可用数据时回退到 AlphaSift 原始日线数据源，减少单一上游超时拖垮选股。
- LLM 环境：DSA 调用 AlphaSift 时会桥接 DSA 已解析的 `LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`LLM_CHANNELS`、`LLM_<NAME>_*`、`LITELLM_CONFIG`、渠道额外请求头和各模型密钥；AlphaSift 独立运行时仍使用自己的 `.env`/环境变量。
- 快照源：DSA 调用 AlphaSift 时，未显式配置 `SNAPSHOT_SOURCE_PRIORITY` 会默认优先使用 `em_datacenter`，减少 Tushare/东方财富行情接口在夜间或网络抖动时逐个失败造成的等待；显式配置的源顺序会原样保留。
- 风险提示：前端设置页和选股页展示第三方来源与投资风险说明；不会弹窗打断用户。

## AlphaSift 适配层要求

AlphaSift 需要提供 `alphasift.dsa_adapter` 模块，并保持以下稳定函数：

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

AlphaSift 侧已在 `ZhuLinsen/alphasift@1a0ed8c99b3615c0cb1076e6029827ffc6de2344` 提供 DSA provider context 支持、DSA adapter contract，并支持复用 DSA 的 `LLM_TIMEOUT_SEC`。

## DSA 后端行为

- `/api/v1/alphasift/status`：返回开关、可用性、默认安装来源标识和适配层元信息；不会暴露完整安装来源。
- `/api/v1/alphasift/install`：显式修复安装入口。桌面模式（`DSA_DESKTOP_MODE=true`）不要求管理员会话，非桌面部署必须启用 `ADMIN_AUTH_ENABLED=true` 并携带有效管理员会话，否则返回 `401/403`。接口只允许默认受信任安装来源，并会强制重装锁定 commit，避免旧版 `alphasift` 包残留。
- `/api/v1/alphasift/strategies`：读取 AlphaSift 策略列表；如果 `ALPHASIFT_ENABLED=true` 但适配层缺失或状态异常，返回 `424 + diagnostics`，不触发运行时安装。
- `/api/v1/alphasift/screen`：调用适配层 `screen(..., use_llm=True)`，并在调用期间临时注入 DSA 已解析的 LLM 运行环境，同时向适配层传入结构化 LLM/DSA provider 配置；AlphaSift 在 LLM 前只消费轻量 DSA provider context，并优先通过 DSA 日线链路补齐 AlphaSift 因子特征，DSA 返回阶段对最终 Top 候选补新闻并复用已增强字段。适配层缺失或运行时异常返回 `424 + diagnostics` 并保留原始错误边界。

## 配置兼容边界（LLM / LiteLLM / Base URL）

- 兼容语义与版本证据（可追溯）：
  - 运行依赖约束：`requirements.txt` 中将 LiteLLM 固定到 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`，并通过 `git+https://github.com/ZhuLinsen/alphasift.git@1a0ed8c99b3615c0cb1076e6029827ffc6de2344` 安装 AlphaSift 适配层。
  - 文档依据：
    - LiteLLM Providers: https://docs.litellm.ai/docs/providers
    - LiteLLM OpenAI-compatible: https://docs.litellm.ai/docs/providers/openai_compatible
    - LiteLLM model_list/proxy 配置（含 `api_base`、`api_key`、`extra_headers`）: https://docs.litellm.ai/docs/proxy/configs
    - OpenAI 请求语义与授权头: https://platform.openai.com/docs/api-reference/making-requests、https://platform.openai.com/docs/api-reference/authentication

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
- 失败可见性：`status`/`screen` 接口返回明确错误码与 `message`，前端在设置页或选股页会将 `403/424/400/422` 等错误直接提示给用户，便于定位并回退到“关闭 AlphaSift + 保持原有 LLM 运行链路”。

## 兼容验收索引（发布前核验）

- 依赖与源码约束核验：`requirements.txt` 中的 `litellm` 约束与 `src/config.py`/`requirements.txt` 一致。
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
- 选股请求使用独立长超时，避免 LLM 重排未完成时被普通 API 超时截断。
- 结果页展示运行 ID、样本数量、过滤后数量、LLM 是否重排、LLM 覆盖率和 DSA 增强计数；如果 AlphaSift 返回 warning/source error/LLM parse error 或 `llm_ranked=false`，页面会明确显示降级原因，避免把本地因子结果误展示成正常 LLM 判断；重复的快照源 fallback warning/source error 会在前端合并展示为一条“数据源降级”提示。
- 展开候选时展示 AlphaSift 摘要、因子和 LLM 判断；若 DSA 已增强，还会展示 `DSA 增强摘要`、`DSA 新闻` 和 `DSA 增强提示`。

## 桌面端说明

源码运行的桌面端复用同一个 Python 后端环境，并设置 `DSA_DESKTOP_MODE=true`；通过设置页开启时如缺少适配层，会提示更新依赖或重建后端产物。

打包后的桌面端不依赖运行期 `pip install`：Windows/CI 使用 `scripts/build-backend.ps1`，macOS 使用 `scripts/build-backend-macos.sh`，两者均先执行 `pip install -r requirements.txt`，再校验并收集 `alphasift.dsa_adapter` 进 PyInstaller 产物。发布包默认仍关闭；用户在 Web 设置页开启后会先检查适配层，若打包产物异常缺失，应重建或更新桌面后端。

## Docker 说明

Docker 镜像与桌面发布包保持一致：`docker/Dockerfile` 会通过 `requirements.txt` 安装 AlphaSift 并校验 `alphasift.dsa_adapter` 可导入。容器运行时默认仍关闭 AlphaSift；用户通过 `ALPHASIFT_ENABLED=true` 或 Web 设置页开启后使用镜像内置依赖，若运行环境缺失适配层，应重新构建镜像。

## 验证记录

- `python -m pytest tests/test_alphasift_api.py -q`
- `python -m py_compile api/v1/endpoints/alphasift.py src/services/alphasift_service.py tests/test_alphasift_api.py src/config.py src/core/config_registry.py`
- `cd apps/dsa-web && npm run test -- alphasift.test.ts StockScreeningPage.test.tsx SettingsPage.test.tsx --run`
- `cd apps/dsa-web && npm run lint`
- `cd apps/dsa-web && npm run build`

## 回滚

- 关闭功能：设置页关闭 AlphaSift，或配置 `ALPHASIFT_ENABLED=false`。
- 禁止启用：保持 `ALPHASIFT_ENABLED=false`；如需使用默认来源之外的 AlphaSift 安装包，先在后端 Python 环境完成手动安装并确认 `alphasift.dsa_adapter` 可导入。
- 回滚代码：移除 AlphaSift API 注册、Web 选股入口和相关配置项即可恢复到集成前流程；默认关闭状态下不会影响原有股票分析、报告生成和通知流程。
