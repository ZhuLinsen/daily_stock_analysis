# AlphaSift 选股集成说明

AlphaSift 作为第三方选股能力接入 DSA。DSA 默认不启用它，也不把 AlphaSift 的策略逻辑复制进主仓库；启用后只通过 `alphasift.dsa_adapter` 稳定适配层调用 AlphaSift。

## 当前方案

- 默认关闭：`ALPHASIFT_ENABLED=false`。
- 启用入口：设置页或选股页点击开启，或在 `.env` 中配置 `ALPHASIFT_ENABLED=true`。
- 安装来源：默认固定到已验证的 AlphaSift 适配层 commit：`ALPHASIFT_INSTALL_SPEC=git+https://github.com/ZhuLinsen/alphasift.git@b2ca66dd47001b9a09890cfe21c2b18c7219ccf5`；桌面发布包和 Docker 镜像在构建阶段预置该依赖，运行时开关只控制是否启用。
- 源码部署：如果不是桌面发布包，需要先把 AlphaSift 安装到 DSA 后端使用的 Python 环境，再开启 `ALPHASIFT_ENABLED`。
- 策略归属：策略列表、策略参数、选股计算和 LLM 重排由 AlphaSift 负责，DSA 只负责开关、调用、展示和错误提示。
- LLM 环境：AlphaSift 直接复用 DSA 进程环境变量，包括 `LLM_CHANNELS`、`LITELLM_CONFIG`、各模型密钥和 `LLM_TIMEOUT_SEC`，不要求单独维护一套 AlphaSift `.env`。
- 风险提示：前端设置页和选股页展示第三方来源与投资风险说明；不会弹窗打断用户。

## AlphaSift 适配层要求

AlphaSift 需要提供 `alphasift.dsa_adapter` 模块，并保持以下稳定函数：

```python
def get_status() -> dict: ...
def list_strategies() -> list[dict]: ...
def screen(strategy: str, *, market: str = "cn", max_results: int = 20, use_llm: bool = True) -> dict: ...
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

AlphaSift 侧已在 `ZhuLinsen/alphasift@b2ca66dd47001b9a09890cfe21c2b18c7219ccf5` 提供 DSA adapter contract，并支持复用 DSA 的 `LLM_TIMEOUT_SEC`。

## DSA 后端行为

- `/api/v1/alphasift/status`：返回开关、可用性、默认安装来源标识和适配层元信息；不会暴露完整安装来源。
- `/api/v1/alphasift/install`：保留给受控部署场景；普通 Web/桌面开关不会调用它。接口要求有效管理员会话，只允许默认受信任安装来源。
- `/api/v1/alphasift/strategies`：读取 AlphaSift 策略列表。
- `/api/v1/alphasift/screen`：调用适配层 `screen(..., use_llm=True)`，返回候选、运行元信息和 LLM 展示字段。

## 配置兼容边界（LLM / LiteLLM / Base URL）

- 本次集成仅复用 DSA 已有配置语义，不新增 LLM 模型名、provider、路由、`OPENAI_BASE_URL`、`LITELLM_MODEL`、`AGENT_LITELLM_MODEL`、`OPENAI_MODEL` 或 `LLM_TIMEOUT_SEC` 的兼容改写/迁移规则。
- 任何配置清理、回退与告警仍沿用当前后端配置解析链路（包括运行时保存前验证、兼容别名解析和非法值 fallback）；AlphaSift 功能本身不引入额外清理/迁移副作用。
- 如果用户已在 `.env`/设置页配置过历史值，AlphaSift 开启前后应保持可用行为一致；需要恢复旧行为时，按既有方式回退到原配置（例如恢复旧的模型名/BASE URL，或关闭相关模型通道）即可。
- 失败可见性：`status`/`screen` 接口返回明确错误码与 `message`，前端在设置页或选股页会将 `403/424/400/422` 等错误直接提示给用户，便于定位并回退到“关闭 AlphaSift + 保持原有 LLM 运行链路”。
- 状态诊断：`/api/v1/alphasift/status` 对 AlphaSift 包或 `alphasift.dsa_adapter` 未安装仍保持 `200` + `available=false` 的兼容语义；如果导入过程、`get_status()` 调用或返回结构出现非预期异常，后端会记录 warning，并在响应中追加不含安装来源明文的 `diagnostics` 字段，便于从接口状态和服务端日志定位问题。

错误策略：

- 未开启返回 `403 alphasift_disabled`。
- 受控安装接口未开启管理员认证或没有有效管理员会话时返回 `403 alphasift_install_auth_required` 或 `401 alphasift_install_unauthorized`。
- 受控安装接口来源不受信任返回 `403 alphasift_install_spec_not_allowed`。
- AlphaSift 未安装、缺少适配层或适配层不可调用返回 `424`。
- 市场或策略被适配层拒绝时返回 `400/422`。
- 运行失败返回 `424 alphasift_screen_failed`。

## Web 行为

- 设置页提供 AlphaSift 开关，开启后写入 `ALPHASIFT_ENABLED=true` 并检查适配层是否可用；不会要求用户再点一次安装。
- 选股页未开启时展示开启按钮；开启后读取 AlphaSift 策略列表。
- 当前只暴露 A 股 `cn` 市场。
- 默认返回数量为 3，避免一次选股过慢或结果过多。
- 选股请求使用独立长超时，避免 LLM 重排未完成时被普通 API 超时截断。
- 结果页展示运行 ID、样本数量、过滤后数量、LLM 是否重排、LLM 覆盖率；展开候选后展示 LLM 判断、主要因子、风险、关注项和催化因素。

## 桌面端说明

源码运行的桌面端复用同一个 Python 后端环境，因此与 Web 端一致，可以通过设置页或 `.env` 开启。

打包后的桌面端不依赖运行期 `pip install`：`scripts/build-backend.ps1` 会在构建阶段安装默认 `ALPHASIFT_INSTALL_SPEC` 并把 `alphasift.dsa_adapter` 收集进 PyInstaller 产物。发布包默认仍关闭；用户在 Web 设置页开启后只切换 `ALPHASIFT_ENABLED` 并检查适配层可用性。

## Docker 说明

Docker 镜像与桌面发布包保持一致：`docker/Dockerfile` 会在构建阶段安装默认 `ALPHASIFT_INSTALL_SPEC` 并校验 `alphasift.dsa_adapter` 可导入。容器运行时默认仍关闭 AlphaSift；用户通过 `ALPHASIFT_ENABLED=true` 或 Web 设置页开启后直接使用镜像内置依赖，不需要在容器运行期执行额外安装。

## 验证记录

- `python -m pytest tests/test_alphasift_api.py -q`
- `python -m py_compile api/v1/endpoints/alphasift.py tests/test_alphasift_api.py src/config.py src/core/config_registry.py`
- `cd apps/dsa-web && npm run test -- alphasift.test.ts StockScreeningPage.test.tsx SettingsPage.test.tsx --run`
- `cd apps/dsa-web && npm run lint`
- `cd apps/dsa-web && npm run build`

本地联调已验证：`/api/v1/alphasift/status` 可读取适配层，`/api/v1/alphasift/screen` 在 `use_llm=True` 下返回 LLM 重排结果，选股页可运行并展开查看候选详情。

## 回滚

- 关闭功能：设置页关闭 AlphaSift，或配置 `ALPHASIFT_ENABLED=false`。
- 禁止启用：保持 `ALPHASIFT_ENABLED=false`；源码部署如需更换来源，先在后端 Python 环境完成安装。
- 回滚代码：移除 AlphaSift API 注册、Web 选股入口和相关配置项即可恢复到集成前流程；默认关闭状态下不会影响原有股票分析、报告生成和通知流程。
