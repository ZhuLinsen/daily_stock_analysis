# LLM (大模型) 配置指南

欢迎！无论你是刚接触 AI 的新手小白，还是精通各种 API 的高玩老手，这份指南都能帮你快速把大模型（LLM）跑起来。

本项目对外提供统一的 AI 模型接入体验，支持主流官方 API、OpenAI 兼容平台以及本地模型。底层由 [LiteLLM](https://docs.litellm.ai/) 驱动，但大多数用户只需要理解“选服务商、填 API Key、选主模型/渠道”这条默认路径。为了照顾不同阶段的用户，我们设计了“三层优先级”配置，按需选择最适合你的方式即可。

如果你正在选择具体服务商、配置 GitHub Actions Secrets / Variables、排查 `details.reason` 错误或准备回滚配置，请优先查看 [LLM 服务商配置指南](./llm-providers.md)。该文档集中维护 provider 预设、Actions 变量对照、运行时能力检测边界和常见错误处理建议。

> 本页的 provider/model/Base URL 说明本次未新增外部兼容语义，仅用于同步现网约定；实际兼容判断仍按当前仓库锁定依赖与运行时实现执行：
> - 依赖边界：`litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`（与 `requirements.txt` 一致）。
> - 兼容验证入口：`tests/test_system_config_service.py`、`tests/test_system_config_api.py` 以及现有前端模型配置页回归用例。
> - 回退路径：优先使用 `.env` 配置备份 + `POST /api/v1/system/config/import` 恢复；也可在重启前手动回填旧 `LITELLM_MODEL` / `LLM_*` / `AGENT_LITELLM_MODEL` / `VISION_MODEL` / `LLM_TEMPERATURE` / `LLM_USAGE_HMAC_*`。

> **说明**：本页对 provider/model/base URL 的说明同步沿用当前依赖约束与历史约定，仅做文档补充，不引入新的运行时 provider、模型或 Base URL 行为变更。

---

## 快速导航：你应该看哪一节？

1. **【新手小白】** "我只想赶紧把系统跑起来，越简单越好！" -> [指路【方式一：极简单模型配置】](#方式一极简单模型配置适合新手)
2. **【进阶用户】** "我有好几个 Key，想配置备用模型，还要改自定义网址(Base URL)。" -> [指路【方式二：渠道(Channels)模式配置】](#方式二渠道channels模式配置适合进阶多模型)
3. **【高玩老手】** "我要做复杂的负载均衡、请求路由、甚至多异构平台高可用！" -> [指路【方式三：YAML 高级配置】](#方式三yaml高级配置适合老手自定义)
4. **【本地模型】** "我想用 Ollama 本地模型！" -> [指路【示例 4：使用 Ollama 本地模型】](#示例-4使用-ollama-本地模型)
5. **【视觉模型】** "我想用图片识别股票代码！" -> [指路【扩展功能：看图模型(Vision)配置】](#扩展功能看图模型vision配置)

---

## Generation Backend（Phase 4）

Generation backend 是普通分析、大盘复盘和 `generate_text()` 的外层运行时选择。默认仍是 `litellm`，零配置路径与历史行为保持一致；`codex_cli` / `claude_code_cli` / `opencode_cli` 是显式 opt-in 的本地 CLI backend，当前标记为 **experimental/limited**。

```env
GENERATION_BACKEND=litellm
GENERATION_FALLBACK_BACKEND=litellm
GENERATION_BACKEND_TIMEOUT_SECONDS=300
GENERATION_BACKEND_MAX_OUTPUT_BYTES=1048576
GENERATION_BACKEND_MAX_CONCURRENCY=1
LOCAL_CLI_BACKEND_MAX_CONCURRENCY=1
# 可选：留空时使用本机 OpenCode 默认模型；配置时作为 --model 覆盖值传给 OpenCode。
# OPENCODE_CLI_MODEL=provider/model
AGENT_GENERATION_BACKEND=auto
```

- `GENERATION_BACKEND=litellm|codex_cli|claude_code_cli|opencode_cli`。本地 CLI backend 是 generation backend，不是 LiteLLM provider；不要写 `LITELLM_MODEL=codex_cli/...`、`LITELLM_MODEL=claude_code_cli/...` 或 `LITELLM_MODEL=opencode_cli/...`。
- `GENERATION_BACKEND=opencode_cli` 时默认不传 `--model`，由本机 OpenCode 使用自身默认模型配置；`OPENCODE_CLI_MODEL` 只是可选覆盖值，配置时才作为单个 `--model` 参数传给 OpenCode。provider 认证、账号和模型可用性由本机 OpenCode 自身配置负责；DSA 不接管这些配置。
- `GENERATION_FALLBACK_BACKEND` 未配置时默认 `litellm`；本地 `.env` 显式空值 `GENERATION_FALLBACK_BACKEND=` 表示禁用 backend-level fallback；primary 与 fallback 相同时解析为 no-op。仓库自带 GitHub Actions workflow 未配置该变量时会显式导出 `litellm`，如果要在 Actions 中禁用 backend fallback，请把 fallback 设为 primary backend，例如 `GENERATION_BACKEND=codex_cli` + `GENERATION_FALLBACK_BACKEND=codex_cli`。
- `GENERATION_BACKEND=codex_cli|claude_code_cli` 且没有 Gemini/OpenAI/Anthropic/DeepSeek API Key 时，普通分析和大盘复盘仍会尝试本地 CLI backend；如果对应 executable 不存在，会返回结构化 `command_not_found`，不会报“API Key 未配置”。
- 当前 `codex_cli` preset 使用 `codex exec --output-last-message <temp-file> -` 读取最终响应；Codex CLI 仍会把同一最终响应打印到 stdout，DSA 会从 stdout 诊断预览和输出大小统计中剔除这份重复内容，不参与主分析 JSON 解析。官方依据见 [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive) 与 [Codex CLI command line options](https://developers.openai.com/codex/cli/reference)。本仓库当前只验证 `codex-cli 0.142.0`，不声明更宽最低版本；如果 CLI 版本不支持 preset 参数，DSA 会返回结构化 `capability_unsupported` / `cli_contract_unsupported` 诊断，并在配置 backend fallback 时回退到 `litellm`。
- 当前 `claude_code_cli` preset 使用 `claude --safe-mode --tools "" --disallowedTools "mcp__*" --strict-mcp-config --no-session-persistence --output-format json -p <static instruction>`，完整 DSA prompt 通过 stdin 传入。DSA 只从 Claude JSON envelope 的 `result/success` 最终字段提取文本；如果后续启用 `--json-schema`，schema mode 必须提取 `structured_output`，并且仍会继续经过 DSA 现有 JSON validator、minimal parser contract、`_parse_response()`、integrity retry、placeholder fill 和 usage telemetry。参数依据见 [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)；本 PR smoke 验证版本为 `claude 2.1.177 (Claude Code)`，不声明更宽最低版本。
- 当前 `opencode_cli` preset 使用 `opencode --pure run --format json [--model <OPENCODE_CLI_MODEL>] <static instruction> --file <temp prompt file>`；只有显式配置 `OPENCODE_CLI_MODEL` 时才追加 `--model`，完整 DSA prompt 写入权限受控的临时文件，不进入 argv。DSA 只解析 OpenCode JSON event 输出中无工具事件的 `text` 内容，并要求正常 `step_finish`；出现 `tool_use`、`error`、`question`、`permission` 等事件会结构化失败。参数依据见 [OpenCode CLI reference](https://opencode.ai/docs/cli)，项目配置合并语义见 [OpenCode config reference](https://opencode.ai/docs/config)；本 PR smoke 验证版本为 `opencode 1.17.11`，不声明更宽最低版本。
- 本地 CLI backend 不支持 streaming。请求 stream 时会自动降级为 non-stream，不会因此返回 `capability_unsupported`。
- 本地 CLI usage 通常不可用，系统不会写入 fake 0 token、fake cost 或 fake cache telemetry。
- 本地 CLI 执行上限有硬边界：`GENERATION_BACKEND_TIMEOUT_SECONDS` 最大 `3600`，`GENERATION_BACKEND_MAX_OUTPUT_BYTES` 最大 `33554432`，`GENERATION_BACKEND_MAX_CONCURRENCY` 最大 `16`，`LOCAL_CLI_BACKEND_MAX_CONCURRENCY` 最大 `4`。诊断 stdout/stderr 与最终响应合计超过输出上限时会返回结构化 `output_too_large`；对 `--output-last-message` preset，stdout 中重复打印的最终响应不会重复计入，也不会作为 `stdout_preview` 暴露。
- 本地 CLI 默认并发为 1；有效并发为 `min(LOCAL_CLI_BACKEND_MAX_CONCURRENCY, GENERATION_BACKEND_MAX_CONCURRENCY)`，不继承 `MAX_WORKERS`。
- `AGENT_GENERATION_BACKEND=auto` 不会继承 `GENERATION_BACKEND` 的 local CLI 值；Agent 工具调用继续使用 LiteLLM。Web 设置页仅暴露 `auto|litellm`；手写 `AGENT_GENERATION_BACKEND=codex_cli|claude_code_cli|opencode_cli` 不实现 text-only Agent mode，会返回明确 unsupported tool-calling 诊断。
- Web 设置页的生成后端快速检查只读取已保存的 `.env`、运行时兜底值和未保存草稿；它不会写配置、重载运行时，也不会发起真实模型请求。`available` 只表示当前配置具备尝试运行的条件。JSON 冒烟测试是单独的显式操作，会使用服务端固定的 JSON 提示词和 schema 发起一次真实的生成后端请求，用于验证提取器、JSON 契约、超时、输出限制和 usage-unavailable 语义。
- `GET /api/v1/system/config/generation-backends/status` 只读取已保存配置；未保存草稿需调用 `POST /api/v1/system/config/generation-backends/status/preview` 或 `POST /api/v1/system/config/generation-backends/smoke-test`。被遮罩的密钥字段会继续沿用已保存值。`health_status` 与 `last_error_code/message` 只代表本次计算结果，不是历史持久健康状态。

### Local CLI 本地 backend 隐私与边界

- 本地 CLI Backend 不等于离线模型；Codex / Claude Code / OpenCode 背后的服务可能处理股票代码、新闻、持仓上下文、分析 prompt、报告草稿等内容。
- Docker、云服务器、CI 不天然拥有你本机的 CLI 登录态。
- GitHub Actions 只负责透传配置值，不安装或登录本地 CLI；如果在 Actions 中 opt-in local CLI backend，runner 上缺少可执行文件或登录态时应看到结构化失败。
- DSA 不读取 Codex/Claude/OpenCode credential 文件，但子进程可能读取 CLI 自身登录态。
- macOS 从 Finder/Dock 启动桌面端时不继承 shell PATH；打包桌面端会在启动后端时补入常见 Homebrew 路径（如 `/opt/homebrew/bin`、`/usr/local/bin`）。如果设置检查仍提示找不到 CLI 可执行文件，请完全退出并重开 DSA；打开 CLI 交互窗口不会改变已运行后端的 PATH。
- DSA 默认只继承最小运行环境，并拒绝通配继承 `CLAUDE_*`、`ANTHROPIC_*`、`OPENCODE_*`、`OPENAI_*`、`GOOGLE_*`、`GEMINI_*`、`AWS_*`、`AZURE_*`、`VERTEX_*`、`*_API_KEY`、`*_AUTH_TOKEN`、`*_ACCESS_TOKEN`、`*_SECRET`、`*_PASSWORD`，降低 DSA API keys、provider tokens 和 webhook tokens 泄漏风险。`CODEX_HOME` 是为兼容既有 Codex CLI 登录目录保留的精确例外；不会恢复 `CODEX_CLI_*` 通配。
- `opencode_cli` 会在临时 cwd 写入最小项目 `opencode.json` 以关闭分享、自动更新、快照和常见工具权限，但 OpenCode resolved config 仍可能包含用户本机全局配置；运行时安全边界同时依赖 `--pure`、env denylist、prompt file 权限和 event extractor fail-closed。
- Web 设置页只暴露安全 preset，不允许提交任意 command / argv / shell string。
- `codex_cli` / `claude_code_cli` / `opencode_cli` 仍标记为 experimental/limited；如果你的 CLI 版本不支持本仓库已验证的非交互输出契约，DSA 会返回结构化 `capability_unsupported`、`cli_contract_unsupported`、`invalid_json`、`schema_validation_failed` 或对应 backend error，并在配置 backend fallback 时回退到 `litellm`。无法接受该版本漂移风险时，请保持 `GENERATION_BACKEND=litellm`。
- `opencode_cli` 不支持 OpenCode serve / web / ACP / MCP / attach / `--dangerously-skip-permissions`；DSA 不把 OpenCode final text 当成 Agent tool success。

## 方式一：极简单模型配置（适合新手）

**目标：** 只要记得填入 API Key 和对应的模型名就能立刻用。不需要折腾复杂概念。

如果你只打算用一种模型，这是最快捷的办法。打开项目根目录下的 `.env` 文件（如果没有，复制一份 `.env.example` 并重命名为 `.env`）。

### Anspire Open 示例：

> 💡 **推荐 [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC)**：支持中文优化的联网搜索与 OpenAI-compatible 路径一体化体验，适合只准备一个 Key 的用户。
> - 以下为配置示例，模型与网关可用性以账号权限和 Anspire 控制台为准；文档示例不替代实际连通性验证。
> - 建议在 Web 设置页点击“测试连接”进行实际鉴权与模型可用性检查，避免以文档默认值直接当作可用性承诺。

```env
# Anspire Open API Keys（支持多个，逗号分隔）
# 获取: https://open.anspire.cn/?share_code=QFBC0FYC
# 满足默认优先级条件时，系统会复用该 Key 处理搜索与 LLM（仅限示例兜底路径）。
# 示例模型：Doubao-Seed-2.0-lite；示例网关：https://open-gateway.anspire.cn/v6
ANSPIRE_API_KEYS=sk-xxxxxxxxxxxxxxxx
# 可选：按控制台可用性切换模型或网关
# ANSPIRE_LLM_MODEL=Doubao-Seed-2.0-pro
# ANSPIRE_LLM_BASE_URL=https://open-gateway.anspire.ai/v6
```

### 示例 1：使用通用第三方平台（兼容 OpenAI 格式，推荐）

现在市面上绝大多数第三方聚合平台（例如硅基流动、AIHubmix、阿里百炼、智谱等）都兼容 OpenAI 的接口格式。只要平台提供了 API Key 和 Base URL，你都可以按照以下格式无脑配置：

```env
# 填入平台提供给你的 API Key
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
# 填入平台的接口地址 (非常重要：结尾通常必须带有 /v1)
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
# 填入该平台上具体的模型名称（非常重要：注意前面必须加上 openai/ 前缀帮系统识别）
LITELLM_MODEL=openai/deepseek-ai/DeepSeek-V3 
```

### 示例 2：使用 DeepSeek 官方接口
```env
# 填入你在 DeepSeek 官方平台申请的 API Key
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```
*兼容提示：仅填这一行时，系统仍会默认使用 `deepseek/deepseek-chat` 并在日志提示迁移。*
`deepseek-chat` / `deepseek-reasoner` 仍可用于兼容旧配置，但 DeepSeek 官方已标记为 2026/07/24 后废弃；新配置建议通过 Web 快速渠道或显式 `LITELLM_MODEL=deepseek/deepseek-v4-flash` 迁移到 `deepseek-v4-flash` / `deepseek-v4-pro`。

### 示例 3：使用 Gemini 免费 API
```env
# 填入你获取的 Google Gemini Key
GEMINI_API_KEY=AIzac...
```

### 示例 4：使用 Ollama 本地模型
```env
# Ollama 无需 API Key，本地运行 ollama serve 后即可使用
OLLAMA_API_BASE=http://localhost:11434
LITELLM_MODEL=ollama/qwen3:8b
```

> **重要**：Ollama 必须使用 `OLLAMA_API_BASE` 配置，**不要**使用 `OPENAI_BASE_URL`，否则系统会错误拼接 URL（如 404、`api/generate/api/show`）。远程 Ollama 时，将 `OLLAMA_API_BASE` 设为实际地址（如 `http://192.168.1.100:11434`）。当前依赖约束为 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`（与 requirements.txt 一致）。

> **恭喜！小白读到这里就可以去运行程序了！**
> 想测测看通没通？在主目录打开命令行输入：`python scripts/check_env.py --llm`

---

## 方式二：渠道(Channels)模式配置（适合进阶/多模型）

**目标：** 我有多个不同平台的 Key 想要混着用，如果主模型卡了/网络挂了，我希望它能自动切换到备用模型。

**网页端可以直接配：** 你可以启动程序后，在 **Web UI 的“系统设置 -> AI 模型 -> AI 模型接入”** 中非常直观地进行可视化配置！

> **新版编辑体验补充**：对于 DeepSeek、阿里百炼（DashScope）以及其他兼容 OpenAI `/v1/models` 的渠道，设置页现在支持直接点击“获取模型”，从 `{base_url}/models` 拉取可用模型并多选；底层仍会保存为原来的 `LLM_{CHANNEL}_MODELS=model1,model2` 逗号格式。若渠道不支持该接口、鉴权失败或暂时不可达，仍可继续手动填写模型列表，不影响保存。

### 首次启动配置状态

后端提供只读状态接口 `GET /api/v1/system/config/setup/status`，用于判断首次启动闭环中最基础的几类配置是否已经就绪：LLM 主渠道、Agent 渠道、自选股、通知渠道和本地存储。这个接口只读取已保存的 `.env` 与当前进程环境变量，不会重载运行时配置、写入 `.env`、测试真实模型或创建数据库文件；前端向导和后续 smoke run 可以基于该接口逐步接入。

### Web 渠道编辑器的兼容性 / 迁移 / 回退规则

- 预设里的 provider / Base URL / 示例模型只用于**初始化表单**；真正落盘时仍是你当前输入的 `LLM_{CHANNEL}_PROTOCOL`、`LLM_{CHANNEL}_BASE_URL`、`LLM_{CHANNEL}_MODELS`、`LLM_{CHANNEL}_API_KEY(S)`，不会在后台偷偷改成别的 provider 名或 URL。
- 设置页的“获取模型”只对 `OpenAI Compatible` / `DeepSeek` 渠道调用 `{base_url}/models`；“测试连接”默认只对模型列表首项发起一次最小聊天请求，并在结果中展示后端规范化后的 `resolved_model`。若返回 `details.reason=model_access_denied`（例如 Issue #1208 中已观测到的 SiliconFlow / OpenAI Compatible 经 LiteLLM 返回 `Model disabled`），请把它视为基于 provider 文案的 best-effort 模型可用性诊断，优先确认该模型是否已在当前账号/key 下开通，必要时调整模型顺序或移除不可用模型后重试；未覆盖或语义不同的 provider 文案会继续走兜底诊断。可选的“运行时能力检测”必须由用户显式选择后触发，会额外发起 JSON / tools / stream / vision smoke 请求，结果仅代表当前账号、模型和 endpoint 的一次 best-effort 检测。上述检测返回的 `stage / error_code / details / latency_ms / capability_results` 仅用于结构化诊断提示，**不会写回** `.env`，也不会阻止保存。
- 若返回 `details.reason=provider_blocked`，表示服务商或中转网关明确拦截了本次请求；它区别于本地网络 / TLS 异常和 `model_access_denied`，应优先检查账号风控、地域或请求来源限制、模型权限、代理商网关策略和内容安全策略。
- 运行时能力检测会产生真实 LLM 请求，可能带来 token / 图像输入费用、RPM/TPM 限流、余额不足或超时。检测失败可能来自账号权限、模型未开通、endpoint 区域、余额、服务商兼容层或 LiteLLM 转换路径，不等于该 provider 全局不支持对应能力。P3 未对所有真实 provider 做在线 smoke；兼容依据来自当前依赖约束 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` 下的 LiteLLM `completion()` / OpenAI I/O format / streaming / exception mapping，以及 OpenAI Chat Completions 的 JSON mode、tool calling、streaming 和 vision input 形状。
- 相关外部来源：LiteLLM Python SDK / OpenAI I/O format / streaming / exception mapping：<https://docs.litellm.ai/>；LiteLLM OpenAI-compatible 路由：<https://docs.litellm.ai/docs/providers/openai_compatible>；OpenAI Chat Completions：<https://platform.openai.com/docs/api-reference/chat/create>；JSON mode：<https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat>；tool calling：<https://platform.openai.com/docs/guides/function-calling?api-mode=chat>；streaming：<https://platform.openai.com/docs/guides/streaming-responses?api-mode=chat>；vision input：<https://platform.openai.com/docs/guides/images-vision?api-mode=chat>。
- 保存渠道时，只会更新这次提交的 key；不会因为切换渠道模式而静默迁移整个旧配置。唯一会被**同步清理**的是运行时模型引用：如果 `LITELLM_MODEL`、`AGENT_LITELLM_MODEL`、`VISION_MODEL` 或 `LITELLM_FALLBACK_MODELS` 指向了当前已启用渠道里已经不存在的模型，设置页会在保存前把这些失效引用清空/移除，避免运行时继续指向无效模型；即使当前启用渠道没有任何可选模型，也会清理缺少 legacy Key 支撑的托管 provider 旧值。`cohere/*`、`google/*`、`xai/*` 这类直连模型仅用于说明历史 `direct-env` 兼容保留语义，不等于可用性承诺，是否可用请按各厂商官方模型/API 文档再做实际验证。
- 后端一致性依据：配置校验链路在 `SystemConfigService._validate_llm_runtime_selection`（`src/services/system_config_service.py`）中通过 `_uses_direct_env_provider`（`src/config.py`）判断运行时来源；当前仅 `gemini`、`vertex_ai`、`anthropic`、`openai`、`deepseek` 属于托管 key provider，`cohere`、`google`、`xai` 不在该白名单中，因此会保留为直连模型。
- 回退方式也保持最小：把对应渠道模型列表改回去后重新选择主模型 / fallback，或直接用桌面端导出备份 / 手动 `.env` 还原之前的 `LLM_*`、`LITELLM_MODEL`、`AGENT_LITELLM_MODEL`、`VISION_MODEL`、`LLM_TEMPERATURE`、`LLM_USAGE_HMAC_*` 即可，不需要额外跑迁移脚本。Web 端如需恢复配置，也可在启用管理员鉴权（`ADMIN_AUTH_ENABLED=true`）后通过 `POST /api/v1/system/config/import` 回滚。
- 当前仓库对此链路的依赖约束是 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`（见 `requirements.txt`）；回归覆盖包括 `tests/test_system_config_service.py`、`tests/test_system_config_api.py` 和 `apps/dsa-web/src/components/settings/__tests__/LLMChannelEditor.test.tsx`。

> **外部 provider 示例模型说明**：`cohere/*`、`google/*`、`xai/*` 等 provider 前缀值仅用于说明当前保存清理语义，**不代表该依赖约束内的逐型号可用性保证**。文档或测试中的具体模型名都是配置保留行为样例，不是生产推荐；实际可用性请以对应官方模型文档为准，并结合仓库依赖约束 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` 复核。

### 回退与兼容性证据

- 依赖约束与静默清理范围：在 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` 下，保存仅清理失效的 runtime 模型引用（`LITELLM_MODEL`、`AGENT_LITELLM_MODEL`、`VISION_MODEL`、`LITELLM_FALLBACK_MODELS`），`cohere/*`、`google/*`、`xai/*` 等非渠道直连模型会被保留。
- 回退方式：可直接用桌面端导出备份后通过 `POST /api/v1/system/config/import` 恢复；也可手动把 `.env` 中历史 `LITELLM_* / AGENT_LITELLM_MODEL / VISION_MODEL / LLM_TEMPERATURE / LLM_USAGE_HMAC_*` 回填后重启生效。Web 端执行导入前请先开启管理员鉴权（`ADMIN_AUTH_ENABLED=true`）。
- 回退回归证据：`tests/test_system_config_service.py::test_import_desktop_env_restores_runtime_models_after_cleanup` 覆盖“清理后用桌面导出备份恢复 runtime 引用”。
- 直连 provider 回归证据：`tests/test_system_config_service.py::SystemConfigServiceTestCase::test_validate_accepts_minimax_model_as_direct_env_provider`、`test_validate_accepts_cohere_model_as_direct_env_provider`、`test_validate_accepts_google_model_as_direct_env_provider`、`test_validate_accepts_xai_model_as_direct_env_provider` 覆盖直连 provider 保留语义。
- 前端回归命令：`cd apps/dsa-web && npm run lint && npm run build && npm run test -- src/components/settings/__tests__/LLMChannelEditor.test.tsx`。
- 建议回退操作链路（含设置页刷新）：先导出桌面备份，`POST /api/v1/system/config/import` 导入后，再通过 `GET /api/v1/system/config` 刷新页面配置，再确认 `LITELLM_MODEL / AGENT_LITELLM_MODEL / VISION_MODEL / LLM_TEMPERATURE / LLM_USAGE_HMAC_*` 与模型列表一致后再继续使用。

### 常用官方文档来源（用于核对预设 provider / Base URL / 模型命名）

- OpenAI Compatible 规范（LiteLLM）：<https://docs.litellm.ai/docs/providers/openai_compatible>
- OpenAI 官方：<https://platform.openai.com/docs/api-reference/chat>
- DeepSeek 官方：<https://api-docs.deepseek.com/>
- Anspire Open：<https://open.anspire.cn/?share_code=QFBC0FYC>
- 阿里百炼 DashScope 兼容模式：<https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- Moonshot / Kimi 官方：<https://platform.moonshot.ai/docs/guide/compatibility>
- Anthropic 官方：<https://docs.anthropic.com/en/api/messages>
- Gemini 官方：<https://ai.google.dev/gemini-api/docs/openai>
- Cohere 官方：<https://docs.cohere.com/>
- Cohere API 参考：<https://docs.cohere.com/reference/>
- Cohere LiteLLM Provider：<https://docs.litellm.ai/docs/providers/cohere>
- Google Gemini API 与模型：<https://ai.google.dev/gemini-api/docs/openai>、<https://ai.google.dev/gemini-api/docs/models>
- Google LiteLLM Provider：<https://docs.litellm.ai/docs/providers/gemini>
- xAI 官方：<https://docs.x.ai/docs>
- xAI LiteLLM Provider：<https://docs.litellm.ai/docs/providers/xai>
- Ollama 官方：<https://github.com/ollama/ollama/blob/main/docs/api.md>

如果不方便用网页版，在 `.env` 文件中配置也非常丝滑，它能让你同时管理多个第三方平台。规则如下：

1. **先声明你有几个渠道**：`LLM_CHANNELS=渠道名称1,渠道名称2`
2. **给每个渠道分别填写配置**（注意全大写）：`LLM_{渠道名}_XXX`

### 示例：同时配置 DeepSeek 和某中转平台，并设置备用切换
```env
# 1. 开启渠道模式，声明这里有两个渠道：deepseek 和 aihubmix
LLM_CHANNELS=deepseek,aihubmix

# 2. 渠道一：配置 DeepSeek 官方
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_DEEPSEEK_API_KEY=sk-1111111111111
LLM_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro

# 3. 渠道二：配置一个常用的聚合中转 API
LLM_AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1
LLM_AIHUBMIX_API_KEY=sk-2222222222222
LLM_AIHUBMIX_MODELS=gpt-5.5,claude-sonnet-4-6

# 4. 【关键】指定主模型和备用模型列表
# 平时首选用 deepseek 这款模型：
LITELLM_MODEL=deepseek/deepseek-v4-flash
# 可选：Agent 问股单独指定主模型（留空则继承主模型）
AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro
# 主模型崩了立刻挨个尝试下面这俩备用模型：
LITELLM_FALLBACK_MODELS=openai/gpt-5.4-mini,anthropic/claude-sonnet-4-6
```

### 示例：Ollama 渠道模式（本地模型，无需 API Key）
```env
# 1. 开启渠道模式，声明 ollama 渠道
LLM_CHANNELS=ollama

# 2. 配置 Ollama 地址（本地默认 11434 端口）
LLM_OLLAMA_BASE_URL=http://localhost:11434
LLM_OLLAMA_MODELS=qwen3:8b,llama3.2

# 3. 指定主模型
LITELLM_MODEL=ollama/qwen3:8b
```

### 示例：Hermes 本地 HTTP Generation（Phase 3）
```env
LLM_CHANNELS=hermes
LLM_HERMES_PROTOCOL=openai
LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1
LLM_HERMES_API_KEY=sk-local-hermes
LLM_HERMES_MODELS=hermes-agent
LITELLM_MODEL=openai/hermes-agent
```

Hermes 是保留渠道名，只支持本机 loopback `/v1` OpenAI-compatible generation。Phase 3 只验证普通分析与 JSON 输出；不支持 Stream/SSE、Tools、Vision、Agent tools、远程 Hermes 或进程生命周期管理。Hermes API Key 只能使用单个 `LLM_HERMES_API_KEY`，不要配置 `LLM_HERMES_API_KEYS` 或 `LLM_HERMES_EXTRA_HEADERS`。如果 Hermes 配置非法，系统会阻止 legacy provider silent fallback，避免错误地改用外部模型。Web 设置页保存 reserved Hermes 渠道时，会显式清空旧的 `LLM_HERMES_API_KEYS` / `LLM_HERMES_EXTRA_HEADERS` 并返回 warning；如需恢复旧值，请从 `.env` 备份、Git 历史或桌面端导出备份手动还原，但 Phase 3 仍会拒绝非空的多 Key / Extra Headers 配置。

### MiniMax 渠道模型填写说明

- 如果你通过 OpenAI Compatible 渠道接 MiniMax，请在渠道模型里直接填写 `minimax/<模型名>`，例如 `minimax/MiniMax-M1`。
- Web 设置页里的主模型、Agent 主模型、Fallback、Vision 下拉会保留这个值原样展示，不会再错误改写成 `openai/minimax/<模型名>`。

### 问股 Agent / LiteLLM 配置兼容说明

- 问股 Agent 运行时沿用与普通分析相同的三层优先级：`LITELLM_CONFIG`（LiteLLM YAML）> `LLM_CHANNELS` > legacy provider keys。只要上层配置有效生效，下层配置就不会再参与本次请求。
- YAML 模式下，Agent 直接复用 LiteLLM `model_list` / `model_name` 路由语义；渠道模式下，优先读取 `AGENT_LITELLM_MODEL`，留空时继承 `LITELLM_MODEL`，再按 `LITELLM_FALLBACK_MODELS` 继续 fallback。
- 如果你没有启用 YAML / Channels，且 `AGENT_LITELLM_MODEL` 也留空，但本地仍保留 legacy 环境变量，问股 Agent 依然会继承旧配置：`GEMINI_API_KEY + GEMINI_MODEL` -> `gemini/<model>`，`OPENAI_API_KEY + OPENAI_MODEL` -> `openai/<model>`，`ANTHROPIC_API_KEY + ANTHROPIC_MODEL` -> `anthropic/<model>`。
- 该兼容逻辑只增强“失败时保留后端真实错误原因”和“未配置 LLM 时给出更具体诊断”，**不会**静默删除、清空、迁移或改写你现有的 `GEMINI_*` / `OPENAI_*` / `ANTHROPIC_*` / `LITELLM_*` 配置。
- 如果当前环境没有任何有效 Agent 模型链路，问股页面会继续按失败语义返回，并直接展示后端真实配置诊断；补齐任一有效模型来源后即可恢复，无需额外执行配置迁移脚本。
- 推荐的新配置方式仍然是显式设置 `LITELLM_MODEL` / `AGENT_LITELLM_MODEL` 或使用 `LLM_CHANNELS`；legacy provider keys 目前保留为兼容回退路径，方便旧 `.env`、本地 macOS 开发环境和历史部署平滑继续运行。

### 问股可见对话上下文压缩

默认情况下，问股仍按历史行为只注入最近 20 条可见对话。需要长会话省 token 时，可开启：

```env
AGENT_CONTEXT_COMPRESSION_ENABLED=true
AGENT_CONTEXT_COMPRESSION_PROFILE=balanced
# 留空则跟随 profile preset
AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS=
AGENT_CONTEXT_PROTECTED_TURNS=
```

压缩只处理 `session_id` 下用户可见的 `user` / `assistant` 文本历史，不处理 provider trace、thinking blocks、tool calls 或 tool results，也不会改变同轮工具调用透传。三档 preset 分别是 `cost`（6000 tokens / 保护 2 轮）、`balanced`（12000 / 4）和 `long_context_raw_first`（24000 / 6）；trigger / protected 留空时跟随当前 profile，显式填写时覆盖 profile。

问股 single-agent 路径会额外维护一条 provider-aware trace 分轨，用于 DeepSeek V4 thinking + tool-call 的跨轮协议回放：只有同一轮同时出现 `tool_calls` 与 `reasoning_content` 时才会按当前 `session_id + provider + model` 保存最近 3 条最小协议材料，并在下一轮按原始时序插回对应可见 assistant 回复之前。该 trace 只能原样保留或整段丢弃，不参与摘要、不写入 Web 会话消息、不新增 `.env` 配置；model/provider 不匹配、锚点已被 summary 覆盖或预算不足时会整段跳过。Claude extended thinking 本轮只覆盖 adapter/storage 级 opaque `thinking` / `redacted_thinking` / `signature` blocks plumbing 与离线 fixture，不声明生产端到端支持；multi-agent trace 注入仍是 follow-up。外部协议依据包括 DeepSeek thinking mode 文档（<https://api-docs.deepseek.com/guides/thinking_mode>）和 Anthropic Claude extended thinking 文档（<https://platform.claude.com/docs/en/docs/build-with-claude/extended-thinking>），LiteLLM 兼容窗口仍以 `requirements.txt` 的 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` 为准。

### 严格 temperature 模型兼容说明

- Moonshot 官方说明 Kimi API 兼容 OpenAI 接口，Base URL 使用 `https://api.moonshot.ai/v1`：<https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart>
- LiteLLM 官方要求 OpenAI Compatible 渠道模型名使用 `openai/` 前缀：<https://docs.litellm.ai/docs/providers/openai_compatible>
- Moonshot 官方兼容性文档区分两种固定值：**thinking 模式固定 `1.0`，non-thinking 模式固定 `0.6`**；传其它值会被接口拒绝：<https://platform.moonshot.ai/docs/guide/compatibility#parameters-differences-in-request-body>
- OpenAI Chat Completions 规范中 `temperature` 是可选参数；对 GPT-5 / o 系列等只接受默认温度的模型，本项目会在请求层省略 `temperature`，让服务端使用默认值，而不是改写你的 `LLM_TEMPERATURE`：<https://platform.openai.com/docs/api-reference/chat/create>
- 当前仓库的运行时依赖约束是 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`（见 `requirements.txt`）；本次兼容逻辑按该约束回归验证了主分析、大盘复盘、Agent 直连 LiteLLM，以及系统设置页的渠道连通性测试。
- 因此本项目会在请求发出前按**实际请求模式**归一化 `kimi-k2.6` 及其 `kimi-k2.6-*` 变体：默认 / thinking 路径使用 `temperature=1.0`；如果你的 LiteLLM YAML 路由别名里显式写了 `litellm_params.extra_body.thinking.type: disabled`（或等价 non-thinking 配置），则自动切到 `temperature=0.6`。你在 `.env` 或 Web 设置里保存的 `LLM_TEMPERATURE` 不会被改写。
- 如果兼容平台对未收录的新模型返回明确的参数错误（例如 `temperature` 不支持、只能使用默认 `1.0`、`top_p` 不支持），运行时会对**当前请求**做一次参数修正并重试；只有重试成功后才把该策略缓存在当前进程内。该缓存不会写回 `.env`，服务重启后会重新按配置与适配规则判断。
- 对已经产生部分内容的流式响应，系统不会在半截输出后切换参数；仍沿用原有“同模型非流式重试 / fallback 模型”的稳定路径，避免拼接出不一致的回答。
- `SystemConfigService` 在 Web 设置保存 / 桌面端 `.env` 导入时只更新你提交的 key，不会因为切到严格 temperature 模型静默清空、迁移或重写已有 `LLM_TEMPERATURE`；渠道测试请求里的临时参数策略也不会回写到配置文件。
- 非严格主模型、非严格 fallback 以及切回普通模型后的请求，仍继续使用你配置的温度；也就是说旧配置无需迁移，切换模型即可自动恢复原行为。
- 本仓库兼容性回归覆盖见：`tests/test_llm_channel_config.py`、`tests/test_market_analyzer_generate_text.py`、`tests/test_agent_pipeline.py`、`tests/test_system_config_service.py`。
- 最小回滚方式：直接回退本次 LLM 参数适配相关改动，无需单独迁移已有 `LLM_TEMPERATURE` 配置。

### 兼容性与回退复核清单（按 PR 审核口径）

- 运行时依赖约束：`litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`（与 `requirements.txt` 一致）。
- 回归验证入口：
  - 渠道模型发现与连接：`tests/test_llm_channel_config.py`
  - 运行时源清理与恢复（含桌面导出备份链路）：`tests/test_system_config_service.py`
  - 接口校验与问题面向字段：`tests/test_system_config_api.py`
  - 设置页交互与保存后提示：`apps/dsa-web/src/components/settings/__tests__/LLMChannelEditor.test.tsx`
- 旧配置回退路径：`桌面端导出备份 -> /api/v1/system/config/import`，或手动恢复 `LLM_* / LITELLM_* / AGENT_LITELLM_MODEL / VISION_MODEL / LLM_TEMPERATURE / LLM_USAGE_HMAC_*`；Web 导入备份前同样要求 `ADMIN_AUTH_ENABLED=true`，否则会返回 403。

> **致命避坑说明**：如果你启用了 `LLM_CHANNELS`，那么你直接写在外面的 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 将**全部失效（系统一律无视）**！二者**选其一即可**，千万不要既写了新手模式又写了渠道模式结果产生冲突。
> **Docker 注意**：如果你在 `docker compose environment:` 或 `docker run -e` 中显式传入 `LITELLM_MODEL`、`LLM_CHANNELS`、`LLM_DEEPSEEK_MODELS` 等变量，容器重启后这些环境变量会覆盖 Web 设置页写入的 `.env`，需要同步修改部署配置。

### 兼容依据与回退审计说明（本次 PR 适配说明）

- 官方与运行时兼容依据采用两层：第一层为官方接口语义（LiteLLM OpenAI-compatible 路由、OpenAI Chat Completions、Moonshot/Kimi 文档与官方模型说明）；第二层为本仓库当前运行时语义（`litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`）下的实际错误归类。
- 本次兼容恢复只使用“本地运行时错误归类 + 单请求修正重试 + 进程内缓存”策略，不写入 `.env`、不做配置迁移，仅在执行路径上动态规避不支持参数（`temperature`、`top_p`、`presence_penalty`、`frequency_penalty`、`seed`）。若要回退，不需要额外迁移命令，恢复旧值即可。
- 回归与证据：`tests/test_llm_param_recovery.py`、`tests/test_system_config_service.py`、`tests/test_llm_channel_config.py`、`tests/test_system_config_api.py`、`tests/test_market_analyzer_generate_text.py`、`tests/test_agent_pipeline.py`；桌面导入与运行时清理回退另有 `test_import_desktop_env_restores_runtime_models_after_cleanup` 直接覆盖。

---

### LLM usage HMAC 遥测

P0a usage telemetry 会为实际发送的 message 生成 HMAC-SHA256 指纹，用于后续判断相同 prompt/message 前缀是否稳定。该能力只写入本地 `llm_usage` 记录，不改变 prompt、provider 参数、cache hint、模型输出或 fallback 顺序。

Usage 来源按三层读取：

- 优先读取 provider / LiteLLM 公开响应字段 `usage`。
- 其次读取 LiteLLM 公开响应字段 `usage_metadata`。
- 最后才读取 `_hidden_params["usage"]`，这是 LiteLLM private/internal 的 best-effort fallback，不是稳定公共契约；缺失时只代表 usage/cache telemetry 可能不完整，不代表模型请求失败。

Cache token 归一化只做 allowlisted best-effort normalization。外部字段依据和运行时边界如下，避免把官方稳定契约、LiteLLM 当前归一化行为和本仓库兼容 allowlist 混为一谈：

| Provider / 来源 | 读取字段 | 依据与边界 | 覆盖情况 |
| --- | --- | --- | --- |
| OpenAI | `usage.prompt_tokens_details.cached_tokens` | 官方 Prompt Caching 文档说明 1024 tokens 以下也会返回 `cached_tokens=0`：<https://developers.openai.com/api/docs/guides/prompt-caching> | unit/mock 覆盖；本 PR 未做 OpenAI live smoke |
| Anthropic | `cache_creation_input_tokens` / `cache_read_input_tokens` / `input_tokens` | 官方 Prompt Caching 文档定义 `total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens`：<https://platform.claude.com/docs/en/build-with-claude/prompt-caching> | unit/mock 覆盖；本 PR 未做 Anthropic live smoke |
| Gemini / Vertex AI | 官方字段为 `UsageMetadata.cachedContentTokenCount`；运行时消费 LiteLLM 暴露的 snake_case / normalized 字段，如 `cached_content_token_count`、`cache_read_input_tokens` 或 `prompt_tokens_details.cached_tokens` | Gemini `UsageMetadata` 官方字段见 <https://ai.google.dev/api/generate-content#UsageMetadata>；本仓库不新增 native camelCase runtime fallback，运行时边界以 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` 为准 | unit/mock 覆盖；本 PR 未做 Gemini / Vertex live smoke |
| DeepSeek | `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` | DeepSeek Chat Completion 文档说明 `prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens`：<https://api-docs.deepseek.com/api/create-chat-completion> | unit/mock 覆盖；本 PR 只做一次脱敏 DeepSeek smoke，不保存完整响应 |
| GLM / OpenAI-compatible / StepFun 等兼容平台 | 已建模 token/cache count allowlist 中能映射到统一字段的值 | 不声明官方稳定 cache telemetry contract；仅表示在当前 LiteLLM / OpenAI-compatible shape 下做 best-effort normalization，未建模 metadata 不持久化 | unit/fixture/mock 覆盖；本 PR 未做这些 provider 的 live smoke |
| LiteLLM public response shape | `usage` / `usage_metadata` | 按当前依赖窗口 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` 的 response / `Usage` object shape 消费；不作为 LiteLLM 2.x 兼容承诺 | Analyzer / Agent / usage tests 覆盖 |
| LiteLLM private fallback | `_hidden_params["usage"]` | private/internal best-effort fallback，不是 LiteLLM 稳定公共契约；仅在 public usage zero-only/no-signal 等窄场景补足 streaming usage，不改变 provider 请求参数 | unit/mock 覆盖；缺失时只影响 telemetry 完整性，不代表模型请求失败 |

```env
LLM_USAGE_HMAC_SECRET=
LLM_USAGE_HMAC_KEY_VERSION=local-v1
```

- `LLM_USAGE_HMAC_SECRET` 留空时，系统会在数据目录生成 `.llm_usage_hmac_secret`，适合单部署本地比较。
- 只有需要跨部署比较 HMAC 时，才显式配置同一个高熵随机密钥；建议使用 `openssl rand -hex 32` 生成。
- `.llm_usage_hmac_secret` 是本地 secret artifact，已在 `.gitignore` 中按文件名忽略。
- 轮换密钥时同步更新 `LLM_USAGE_HMAC_KEY_VERSION`，避免不同密钥生成的 HMAC 被误比较。
- 不要复用登录 session secret，也不要把真实密钥提交到版本控制或暴露在 issue、日志、截图中。

### Provider prompt cache 配置（P1 / P1.5）

Prompt cache 配置只控制本项目是否记录 cache usage / diagnostics，以及主分析路径是否主动发送已验证的 provider-specific hint；它不控制 OpenAI、Gemini、DeepSeek 等 provider 的 implicit / provider-managed cache。

```env
LLM_PROMPT_CACHE_TELEMETRY_ENABLED=true
LLM_PROMPT_CACHE_HINTS_ENABLED=false
LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL=off
```

- `LLM_PROMPT_CACHE_TELEMETRY_ENABLED=false` 时，不持久化 provider raw usage JSON、normalized cache fields 和 cache decision diagnostics；基础 token usage 记录保持兼容。
- `LLM_PROMPT_CACHE_HINTS_ENABLED=true` 只允许主分析 / analyzer LiteLLM 路径向 registry 中已验证或 smoke-tested 的 provider / route 发送 `prompt_cache_key`、`cache_control`、`user_id` 等 hint。问股 Agent 路径当前只记录 capability / usage diagnostics，不主动发送 provider-specific hints。未知 OpenAI-compatible gateway 默认 telemetry only。
- `LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL=basic` 只在 debug 日志和测试可观察对象中提供 provider、api surface、verification status、hint applied / disabled reason 等非敏感枚举。`debug` 在同一范围内额外提供 HMAC-derived route/cache diagnostics 和 matched caps id，但仍禁止 raw prompt、request body、message content、股票/用户原文、webhook 或 API key；这些诊断不是公开 Usage API 或普通设置页输出。
- Provider Cache Capability Registry 是 `src/llm/provider_cache.py` 中的 code-level 手工能力表。条目带 `doc_sources`、`last_verified_at` 和 `verification_status`；新增 provider 或升级 LiteLLM 后应同步更新条目与测试。
- Prompt cache key、route key 和 DeepSeek session isolation 复用 `LLM_USAGE_HMAC_SECRET` / `.llm_usage_hmac_secret` 做 domain-separated HMAC，不新增 prompt-cache 专用 secret。

### Legacy message stability audit（P0.5a）

P0.5a 在普通个股分析路径为 legacy `[system, user]` message 追加内部稳定性审计字段，继续写入本地 `llm_usage`。它复用上面的 message HMAC，不修改 prompt 内容、message 顺序、provider 请求参数、cache hint、模型输出、fallback 顺序，也不扩展公开 Usage API 或 Web 页面。

新增字段只用于维护者诊断：

- `language`、`market_group`、`analysis_mode`、`legacy_prompt_mode`、`provider`、`transport`、`message_count` 描述本次普通个股分析调用的低敏路由上下文。
- `skill_config_hmac` 是基于已解析 skill prompt 片段、默认 skill 策略和 legacy prompt 模式生成的 HMAC-SHA256，用于判断 system message 是否随 skill configuration 变化；不会保存 skill 原文。
- `known_dynamic_marker_positions` 是 JSON string，只记录 `marker_name`、`message_role`、`char_offset`；不会保存股票代码、股票名称、日期、新闻正文、行情值、headers、response text 或 prompt 片段。
- `estimated_total_prompt_tokens`、`approx_common_prefix_chars`、`approx_common_prefix_tokens` 基于项目内稳定 canonical render 估算：按 message 顺序拼接 `role + "\n" + content`，并用固定分隔符连接。该口径不声称等同 provider 真实 wire bytes。
- `char_offset` 是 marker 在对应 message `content` 内的位置；`approx_common_prefix_chars` 是 canonical render 起点到第一个已知动态 marker 之前的字符数。没有 marker 时 common-prefix 字段为 `NULL`。
- token 估算使用 `ceil(chars / 3)`，只作 diagnostics，不替代 provider usage，也不参与 cache threshold 判定；中文场景可能偏低。

P0.5a 不引入 PromptBlock IR、`block_id`、`stability_class`、`static_prefix_hash` 或 `dynamic_context_hash`。Agent、research 与 market review 路径暂不接入该审计。

---

## 方式三：YAML 高级配置（适合老手自定义）

**目标：** 我不在乎学习门槛，我要最高控制权，我要用原生规则做企业级高可用！

这一层会直接映射到底层 LiteLLM 路由能力，支持高并发、自动重试、按 RPM/TPM 负载均衡等操作。

### 本地运行 / Docker 部署模式配置说明

1. 在 `.env` 中只保留一行指向声明：
   ```env
   LITELLM_CONFIG=./litellm_config.yaml
   ```
2. 在项目根目录创建一个 `litellm_config.yaml`（可以参考自带的 `docs/examples/litellm_config.example.yaml`）。

示例 `litellm_config.yaml`：
```yaml
model_list:
  - model_name: my-smart-model
    litellm_params:
      model: deepseek/deepseek-v4-flash
      api_base: https://api.deepseek.com
      api_key: "os.environ/MY_CUSTOM_SECRET_KEY"  # 从环境变量读取 Key，安全防泄漏

  # Ollama 本地模型（无需 api_key）
  - model_name: ollama/qwen3:8b
    litellm_params:
      model: ollama/qwen3:8b
      api_base: http://localhost:11434
```

### GitHub Actions配置说明

1. `Settings` → `Secrets and variables` → `Actions`。非敏感配置（如模型名、开关、Base URL）可以放在 `Secret` 或 `Variables`；凡是 `*_API_KEY` / `*_API_KEYS` 以及 `LLM_<NAME>_API_KEY` / `LLM_<NAME>_API_KEYS` 这类密钥字段，请统一放在 `Secret` 标签页的 `New repository secret`

2. 按下表配置，只有全部必填配置正确配置，YAML 高级配置模式才可以生效，YAML配置文件的写法，可以参考自带的 `docs/examples/litellm_config.example.yaml`

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `LITELLM_CONFIG` | 高级模型路由配置文件路径，通常配置 `./litellm_config.yaml` | 必填 |
| `LITELLM_MODEL` | 默认主模型名称或路由别名 | 必填 |
| `LITELLM_CONFIG_YAML` | 存放 YAML 配置文件内容，可不在仓库中提交实体文件 | 可选 |
| `LITELLM_API_KEY` | 用于存储API Key，可在配置文件中引用（环境变量引用方式）。由于GitHub Actions必须要指定导入的环境变量，因此你不能像本地运行模式那样自由命名环境变量 | 可选，必须配置到repository secret中 |
| `ANTHROPIC_API_KEY` | 如果要多个API Key，这个变量名称也能拿来用 | 可选，必须配置到repository secret中 |
| `OPENAI_API_KEY` | 同上，可以用来存储API Key | 可选，必须配置到repository secret中 |

渠道模式无需上传 YAML 文件。仓库自带 `00-daily-analysis.yml` 已显式透传以下常用字段：

- 运行时选择：`GENERATION_BACKEND`、`GENERATION_FALLBACK_BACKEND`、`GENERATION_BACKEND_TIMEOUT_SECONDS`、`GENERATION_BACKEND_MAX_OUTPUT_BYTES`、`GENERATION_BACKEND_MAX_CONCURRENCY`、`LOCAL_CLI_BACKEND_MAX_CONCURRENCY`、`AGENT_GENERATION_BACKEND`、`LLM_CHANNELS`、`LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`AGENT_LITELLM_MODEL`、`VISION_MODEL`、`VISION_PROVIDER_PRIORITY`、`LLM_TEMPERATURE`、`LLM_USAGE_HMAC_SECRET`、`LLM_USAGE_HMAC_KEY_VERSION`、`LLM_PROMPT_CACHE_TELEMETRY_ENABLED`、`LLM_PROMPT_CACHE_HINTS_ENABLED`、`LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL`
- 多 Key：`GEMINI_API_KEYS`、`ANTHROPIC_API_KEYS`、`OPENAI_API_KEYS`、`DEEPSEEK_API_KEYS`（当前 workflow 仅从 repository secrets 导入，不会读取同名 Variables）
- 常用渠道名：`primary`、`secondary`、`aihubmix`、`deepseek`、`dashscope`、`zhipu`、`moonshot`、`minimax`、`volcengine`、`siliconflow`、`openrouter`、`gemini`、`anthropic`、`openai`、`ollama`

例如在 GitHub Actions 中配置 `LLM_CHANNELS=primary,deepseek` 时，需同步配置 `LLM_PRIMARY_*` / `LLM_DEEPSEEK_*`。其中 `LLM_<NAME>_API_KEY` / `LLM_<NAME>_API_KEYS` 当前也仅从 repository secrets 导入；如果你把这些值放在 Variables，运行时不会生效。若使用自定义渠道名（如 `my_proxy`），GitHub Actions 还必须在 workflow `env:` 中显式新增对应的 `LLM_MY_PROXY_*` 映射；本地 `.env` 和 Docker 不受这个限制。


> **三层配置互斥准则**：YAML 优先级最高！只要配置了 YAML，**渠道模式** 和 **新手极简模式** 统统被忽略。系统优先级为：`YAML配置 > 渠道模式 > 极简单模型`。

---

## 扩展功能：看图模型 (Vision) 配置

系统中有些特定功能（比如上传股票软件截图，让 AI 提取出截图里的股票代码并放入自选股池）必须用到具备“视觉能力”的模型。你需在 `.env` 单独给它指派一个懂图片的模型。

```env
# 指定你看图专用的模型名
VISION_MODEL=openai/gpt-5.5
# 别忘了填写它对应提供商的 API KEY，如果是 OpenAI 兼容渠道就提供 OPENAI_API_KEY：
# OPENAI_API_KEY=xxx
```

**备用看图机制：** 为了防止偶尔罢工，系统内置了切换策略。如果主视觉模型调用失败，它会按照下方的顺位尝试寻找是否有其他看图模型的 Key：
```env
# 默认的备用顺序：
VISION_PROVIDER_PRIORITY=gemini,anthropic,openai
```

---

## 检测与排错 (Troubleshooting)

配好了之后心惊胆战不知道对不对？在命令行（Terminal）里敲入下面代码帮你挂号问诊：

- `python scripts/check_env.py --config` ：纯检测 `.env` 配置文件里的逻辑写得对不对，是不是少写了什么。（秒出结果，不调用网络，纯检查本地文本拼写）
- `python scripts/check_env.py --llm` ：系统会真的发一句问候语给大模型，让你亲眼看到他的回答。这能彻底测出你的**网络通不通、账号有没有欠费**。

### 常见踩坑答疑台

| 遇到了什么诡异报错？ | 罪魁祸首可能是啥？ | 该怎么收拾它？ |
|----------------------|----------------------|------------------|
| **界面提示主模型未配置** | 系统不知道你到底想用哪家的哪个模型 | 在 `.env` 中写上一句明白话：`LITELLM_MODEL=provider/你的模型名`。比如 `openai/gpt-5.5` |
| **我写了好几家的Key，为什么死活只有一个生效？修改还没用？** | 你把 **极简模式** 和 **渠道模式** 混着写了！ | 想好一条路走到黑——只要简单就删掉 `LLM_CHANNELS` 开头的；想要丰富备用切换就要全部转投到 `LLM_CHANNELS` 下的编制里。 |
| **错误码报 400 或 401 或 Invalid API Key** | API Key 填错、少复制了一截、账号充值没到账、或者模型名字敲错（极度常见）。 | 1. 检查复制的 Key 前后是否有误填空格。<br> 2. 检查 Base URL 最后是不是少了一个 `/v1`。<br> 3. 检查模型名是否少写了 `openai/` 之类的前缀！ |
| **Kimi K2.6 报 `invalid temperature`（可能提示只允许 `1.0` 或 `0.6`）** | 该模型按 thinking / non-thinking 模式要求不同固定 temperature；旧配置或调用入口可能还在传 `0.7`。 | 升级后系统会对 `kimi-k2.6` 默认 / thinking 请求自动使用 `temperature=1.0`；如果你在 LiteLLM YAML 路由里显式关闭 thinking，则自动改用 `0.6`。模型名建议写成 `openai/kimi-k2.6` 并配合 Moonshot / 聚合平台的 OpenAI 兼容 Base URL 与 API Key。非 Kimi fallback 仍会继续使用你配置的 `LLM_TEMPERATURE`。 |
| **GPT-5 / o 系列报 `temperature` 不支持或只允许默认值** | 这类模型只接受服务端默认采样参数，但旧调用入口会显式传 `0.7`。 | 升级后请求层会省略 `temperature`，让服务端使用默认值；`.env` / Web 设置中的 `LLM_TEMPERATURE` 不会被改写，切回普通模型后仍按原值发送。 |
| **转圈转不停，最后报 Timeout / ConnectionRefused 等** | 1. 在国内使用国外原版（像 Google、OpenAI），没开代理被墙了。<br>2. 你买的云服务器压根不能出境。 | 非常推荐使用**国内官方**（如DeepSeek、阿里）或者各种**兼容 OpenAI 的聚合中转接口**。因为中转站把网络问题帮你解决好了。 |
| **Ollama 报 404、`Could not get model info` 或 `api/generate/api/show`** | 误用 `OPENAI_BASE_URL` 配置 Ollama，系统会错误拼接 URL | 改用 `OLLAMA_API_BASE=http://localhost:11434` 或渠道模式（`LLM_CHANNELS=ollama` + `LLM_OLLAMA_BASE_URL`） |

*进阶老手的叮嘱：如果你开启了 **Agent (深度思考网络搜索问股) 模式**，这里有个经验之谈，推荐选用如 `deepseek-v4-pro` 这种逻辑推导能力更强的大模型。如果为了省钱用小微模型跑 Agent，它逻辑能力大概率跟不上，不仅达不到预期，还会白跑一堆空流程。*
