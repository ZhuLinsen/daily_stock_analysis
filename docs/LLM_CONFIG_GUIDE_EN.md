# LLM Configuration Guide

Welcome! Whether you are a beginner newly exposed to AI or a veteran skilled with various APIs, this guide will help you set up Large Language Models (LLMs) quickly.

This project exposes a unified AI model access flow that supports official APIs, OpenAI-compatible platforms, and local models. Under the hood it is powered by [LiteLLM](https://docs.litellm.ai/), but most users only need to think in terms of picking a provider, adding an API key, and optionally choosing a primary model or channels. To cater to different experience levels, we provide a three-tier configuration hierarchy. Choose the method that fits you best.

If you are choosing a concrete provider, setting up GitHub Actions Secrets / Variables, troubleshooting a `details.reason` error, or rolling back an LLM configuration, start with the [Provider Configuration Guide](./llm-providers.md). It is the maintained reference for provider presets, Actions variable mapping, runtime capability-check boundaries, and common error handling.

---

## Quick Navigation: Which section should you read?

1. **[Beginners]** "I just want to get the system running ASAP, keep it as simple as possible!" -> [Go to Method 1: Simple Model Config](#method-1-simple-model-config-for-beginners)
2. **[Advanced Users]** "I have several Keys, want to configure fallback models, and define custom Base URLs." -> [Go to Method 2: Channels Mode Config](#method-2-channels-mode-config-advancedmulti-model)
3. **[Veterans]** "I want complex load balancing, request routing, and enterprise-level high availability!" -> [Go to Method 3: Advanced YAML Config](#method-3-advanced-yaml-config-expert-setup)
4. **[Local Models]** "I want to use Ollama local models!" -> [Go to Example 4: Using Ollama Local Models](#example-4-using-ollama-local-models)
5. **[Vision Models]** "I want to extract stock codes from images!" -> [Go to Vision Model Config](#advanced-feature-vision-model-config)

---

## Generation Backend (Phase 4)

The generation backend is the outer runtime selector for regular stock analysis, market review, and `generate_text()`. The default remains `litellm` with zero regression. `codex_cli` / `claude_code_cli` / `opencode_cli` are explicit opt-in local CLI backends and are currently **experimental/limited**.

```env
GENERATION_BACKEND=litellm
GENERATION_FALLBACK_BACKEND=litellm
GENERATION_BACKEND_TIMEOUT_SECONDS=300
GENERATION_BACKEND_MAX_OUTPUT_BYTES=1048576
GENERATION_BACKEND_MAX_CONCURRENCY=1
LOCAL_CLI_BACKEND_MAX_CONCURRENCY=1
# Optional: leave empty to use the local OpenCode default model; set it only to pass a --model override.
# OPENCODE_CLI_MODEL=provider/model
AGENT_BACKEND=auto
AGENT_GENERATION_BACKEND=auto
```

- `GENERATION_BACKEND=litellm|codex_cli|claude_code_cli|opencode_cli`. Local CLI backends are generation backends, not LiteLLM providers; do not set `LITELLM_MODEL=codex_cli/...`, `LITELLM_MODEL=claude_code_cli/...`, or `LITELLM_MODEL=opencode_cli/...`.
- With `GENERATION_BACKEND=opencode_cli`, DSA does not pass `--model` by default and lets local OpenCode use its own default model configuration. `OPENCODE_CLI_MODEL` is only an optional override; when set, DSA passes it as one OpenCode `--model` argument. Provider authentication, account state, and model availability are handled by your local OpenCode setup.
- If `GENERATION_FALLBACK_BACKEND` is unset, it defaults to `litellm`. In local `.env`, an explicit empty value disables backend-level fallback. A fallback equal to the primary backend is treated as no-op. The bundled GitHub Actions workflow explicitly exports `litellm` when this variable is not configured; to disable backend fallback there, set the fallback to the primary backend, for example `GENERATION_BACKEND=codex_cli` + `GENERATION_FALLBACK_BACKEND=codex_cli`.
- With `GENERATION_BACKEND=codex_cli|claude_code_cli`, regular analysis and market review do not require Gemini/OpenAI/Anthropic/DeepSeek API keys. If the corresponding executable is missing, DSA returns structured `command_not_found` instead of “API key not configured”.
- The current `codex_cli` preset uses `codex --ask-for-approval never exec --sandbox read-only --output-last-message <temp-file> -`. Regular analysis is unattended generation, so `never` prevents a non-interactive run from stopping for human approval while `read-only` retains the filesystem boundary. DSA reads the final response from the temporary file; the duplicate response printed to stdout is removed from diagnostics previews and output-size accounting and is never used for main-analysis JSON parsing. Official references: [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive) and [Codex CLI command line options](https://developers.openai.com/codex/cli/reference). This repository has live-verified `codex-cli 0.144.3` and does not claim a wider minimum version range; if the installed CLI does not support a preset argument, DSA returns structured `capability_unsupported` / `cli_contract_unsupported` diagnostics and falls back to `litellm` when backend fallback is configured.
- The current `claude_code_cli` preset uses `claude --safe-mode --tools "" --disallowedTools "mcp__*" --strict-mcp-config --no-session-persistence --output-format json -p <static instruction>`, with the full DSA prompt passed through stdin. DSA only extracts the final text from Claude's `result/success` JSON envelope. If `--json-schema` is enabled later, schema mode must extract `structured_output`, and the output still goes through DSA's existing JSON validator, minimal parser contract, `_parse_response()`, integrity retry, placeholder fill, and usage telemetry. The CLI flags are based on the [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference). This PR smoke-tested `claude 2.1.177 (Claude Code)` and does not claim a wider minimum version range.
- The current `opencode_cli` preset uses `opencode --pure run --format json [--model <OPENCODE_CLI_MODEL>] <static instruction> --file <temp prompt file>`. DSA only appends `--model` when `OPENCODE_CLI_MODEL` is explicitly set. The full DSA prompt is written to a permission-restricted temporary file and is not placed in argv. DSA only extracts text from OpenCode JSON event output that has no tool events and ends with a normal `step_finish`; `tool_use`, `error`, `question`, or `permission` events fail structurally. The CLI flags are based on the [OpenCode CLI reference](https://opencode.ai/docs/cli), and project config merge semantics are documented in the [OpenCode config reference](https://opencode.ai/docs/config). This PR smoke-tested `opencode 1.17.11` and does not claim a wider minimum version range.
- Local CLI backends do not support streaming. Stream requests degrade to non-stream and do not return `capability_unsupported`.
- Local CLI usage is normally unavailable. DSA does not persist fake 0-token, fake cost, or fake cache telemetry.
- Local CLI execution has hard caps: `GENERATION_BACKEND_TIMEOUT_SECONDS` max `3600`, `GENERATION_BACKEND_MAX_OUTPUT_BYTES` max `33554432`, `GENERATION_BACKEND_MAX_CONCURRENCY` max `16`, and `LOCAL_CLI_BACKEND_MAX_CONCURRENCY` max `4`. Diagnostic stdout/stderr plus the final response are counted together; for `--output-last-message` presets, the final response duplicated to stdout is not counted twice and is not exposed in `stdout_preview`.
- Local CLI default concurrency is 1. Effective local CLI concurrency is `min(LOCAL_CLI_BACKEND_MAX_CONCURRENCY, GENERATION_BACKEND_MAX_CONCURRENCY)` and does not inherit `MAX_WORKERS`.
- `AGENT_GENERATION_BACKEND=auto` does not inherit local CLI values from `GENERATION_BACKEND`; Agent tool calling remains on LiteLLM. The Web settings page only exposes `auto|litellm`; a hand-written `AGENT_GENERATION_BACKEND=codex_cli|claude_code_cli|opencode_cli` does not enable Agent text-only mode and returns an explicit unsupported tool-calling diagnostic.
- The Phase 6a DSA Tool Surface remains the only tool-schema, permission, scope-guard, structured-error, audit, and redaction boundary. The Phase 6 Codex AgentBackend can execute tools only through this surface. `codex_cli` / `claude_code_cli` / `opencode_cli` remain generation-only and are never Agent tool fallbacks.
- The Web settings generation-backend quick check only reads saved `.env`, runtime defaults, and unsaved drafts. It does not write config, reload runtime, or send a real model request; `available` only means the current config can be attempted. JSON smoke test is a separate explicit button that sends one real generation-backend request with a server-owned fixed JSON prompt/schema to verify extractor behavior, JSON contract, timeout, output limits, and usage-unavailable semantics.
- `GET /api/v1/system/config/generation-backends/status` only reads saved config. Unsaved drafts use `POST /api/v1/system/config/generation-backends/status/preview` or `POST /api/v1/system/config/generation-backends/smoke-test`; masked secrets preserve saved values. `health_status` and `last_error_code/message` describe only the current computation, not persisted historical health.

### Codex Local Agent (Phase 6 Experimental Prototype)

`AGENT_BACKEND` selects only the runtime for the existing ask-stock Chat. It does not change regular reports, scheduled analysis, market review, the regular Agent analysis pipeline, LiteLLM Multi Agent, or Deep Research:

```env
# Auto (recommended) never enables experimental Codex; auto and litellm keep the existing route.
AGENT_BACKEND=auto
# Explicit opt-in:
# AGENT_BACKEND=codex_app_server
# AGENT_ARCH=single
```

Web setup: open **Settings → Agent → Ask-stock method**, choose **Codex local Agent (experimental)**, keep **Single Agent**, set the overall Agent timeout to a value greater than 0, and save. Settings checks only whether the current configuration, local Codex command, and required App Server protocol allow an attempt; it does not sign in, call a model, or read stock data. Return to Chat and ask directly after saving. The first question is the first real execution. To restore the original behavior, select **Auto (recommended)** and save.

- Codex must be installed and signed in on the device running the DSA backend. DSA does not read or store Codex credentials; the App Server process uses Codex's own sign-in state. Docker, remote servers, and Desktop have separate PATH and sign-in environments. A Desktop backend launched from Finder/Dock only sees the PATH constructed for that process; install Codex CLI where that PATH can find it and fully restart DSA.
- The Phase 6 Codex App Server Agent currently supports macOS, Linux, and environments where the complete DSA backend runs inside WSL. Native Windows backends are rejected before status probing or transport startup. This does not change the existing Windows generation support for Phase 2 `GENERATION_BACKEND=codex_cli`.
- Codex currently exposes read-only access only to saved analysis context, overall backtest summaries, and strategy backtest summaries. This phase validates and promises the independent-process, stop, timeout, and cleanup lifecycle only for those three tools. Live quotes, news, market hotspots, technical-indicator recalculation, per-stock backtest details, and portfolio tools were not validated in this phase and are therefore omitted from the Codex tool list; choose **Default model** when you need them. An explicit symbol or one uniquely selected Web stock only establishes the stock scope for the exposed historical-analysis-context tool; DSA does not guess across ambiguous listings.
- This is not an offline model. Services configured in Codex may process stock symbols, questions, news, position context, and redacted tool results.
- Only single-agent Chat is supported. Codex Multi Agent and Codex Deep Research are not supported. Existing LiteLLM Multi Agent and Deep Research remain unchanged.
- Each Chat request creates a new ephemeral App Server thread. DSA retains the existing visible session history and injects it into the next request, but it does not inject LiteLLM provider traces. Web clients do not receive chain-of-thought, raw JSON-RPC, stderr, or complete tool arguments/results; Codex receives only the redacted tool results needed for that turn.
- When the user stops ask-stock Chat, the page first shows **Stopping**. DSA interrupts the Codex turn and terminates and reaps the independently running tool process for that turn. The original Chat request reports **Stopped** only after both Codex and the tool process have exited. Timeouts and client disconnects use the same cleanup boundary, so a turn is never reported as finished while its background work is still running. This contract applies only to Codex and does not change the default LiteLLM Agent execution path.
- Codex requires `AGENT_ORCHESTRATOR_TIMEOUT_S` greater than 0 so success, failure, timeout, and stop all reach a bounded end. The existing `0`-disables-timeout behavior remains available only to the default LiteLLM path. Codex rejects 0 during configuration and before execution instead of silently replacing it with 600 seconds.
- Cheap status checks configuration, executable visibility, version, and the App Server schema capabilities required by the production path without a model request. It does not prove that Codex is signed in, a model is available, or tools can complete. The status says only **Can try**; command, protocol, sign-in, model, and tool failures are classified when the user sends a question. Chat checks status once when loaded and retries only when the user asks it to check again.
- The server selects the actual backend for each Chat request. It prepares context and persists the user question before emitting the single SSE `accepted` event, and only then starts model execution. Web preserves the input, stock scope, follow-up context, and skill selection until `accepted`, preventing ghost messages when preparation fails. The actual backend in `accepted` determines how Stop works.
- One bounded turn budget covers cumulative App Server output and event counts. Tool calls use the existing `AGENT_MAX_STEPS` budget, and per-turn state is removed at completion. Tool-process IPC measures raw UTF-8 result bytes rather than JSON-escaped size. A limit breach returns a structured error and reclaims the turn without retrying or switching backends.
- The integration follows the [Codex App Server v2 documentation](https://developers.openai.com/codex/app-server/) for JSONL stdio, ephemeral `thread/start`, `turn/start` / `turn/interrupt`, and experimental dynamic tools. Local acceptance on 2026-07-15 used `codex-cli 0.144.3`; DSA does not infer a universal minimum version from that observation. Settings decides only whether an attempt is allowed; the user's real question determines final availability.

### Local CLI Privacy And Boundaries

- A local CLI backend is not an offline model. The service behind Codex / Claude Code / OpenCode may process stock symbols, news, position context, analysis prompts, and report drafts.
- Docker, cloud servers, and CI do not automatically have your local CLI login state.
- GitHub Actions only passes configuration values through; it does not install or log in local CLIs. If you opt into a local CLI backend in Actions, a runner without the executable or login state should return a structured failure.
- DSA does not read Codex/Claude/OpenCode credential files, but the subprocess may use the CLI's own login state.
- On macOS, desktop apps launched from Finder/Dock do not inherit the shell PATH. The packaged desktop app adds common Homebrew directories such as `/opt/homebrew/bin` and `/usr/local/bin` when starting the backend. If setup checks still cannot find the CLI executable, fully quit and reopen DSA; opening an interactive CLI window does not change the already-running backend PATH.
- DSA only inherits a minimal child environment and denies wildcard inheritance of `CLAUDE_*`, `ANTHROPIC_*`, `OPENCODE_*`, `OPENAI_*`, `GOOGLE_*`, `GEMINI_*`, `AWS_*`, `AZURE_*`, `VERTEX_*`, `*_API_KEY`, `*_AUTH_TOKEN`, `*_ACCESS_TOKEN`, `*_SECRET`, and `*_PASSWORD`, reducing the risk of leaking DSA API keys, provider tokens, or webhook tokens. `CODEX_HOME` is the exact-name exception retained for existing Codex CLI login-directory compatibility; `CODEX_CLI_*` wildcard inheritance is not restored.
- `opencode_cli` writes a minimal project `opencode.json` in the temporary cwd to disable sharing, autoupdate, snapshots, and common tool permissions, but OpenCode's resolved config may still include local global settings. Runtime safety also relies on `--pure`, the env denylist, prompt-file permissions, and the event extractor failing closed.
- The Web settings page only exposes safe presets; it does not accept arbitrary command, argv, or shell strings.
- `codex_cli` / `claude_code_cli` / `opencode_cli` remain experimental/limited. If your CLI version does not support the non-interactive output contract verified by this repository, DSA returns structured `capability_unsupported`, `cli_contract_unsupported`, `invalid_json`, `schema_validation_failed`, or the corresponding backend error, and falls back to `litellm` when backend fallback is configured. If that version-drift risk is unacceptable, keep `GENERATION_BACKEND=litellm`.
- `opencode_cli` does not support OpenCode serve / web / ACP / MCP / attach / `--dangerously-skip-permissions`, and DSA never treats OpenCode final text as Agent tool success.

## Method 1: Simple Model Config (For Beginners)

**Goal:** Just paste your API Key and the model name to start using it immediately. No need to mess with complex concepts.

If you only plan to use one single model, this is the fastest way. Open the `.env` file in the project's root directory (if it doesn't exist, copy `.env.example` and rename it to `.env`).

### Anspire Open Example:

> 💡 **[Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC)**: supports Chinese-optimized search and OpenAI-compatible model access using a shared key.
> - The following values are configuration examples only; model availability depends on your account and Anspire console.
> - Documentation examples do not replace connectivity validation; please validate with the Web "Test connection" flow before relying on production traffic.

```env
# Anspire Open API keys (multiple keys supported, separated by commas)
# Get your key at: https://open.anspire.cn/?share_code=QFBC0FYC
# When no higher-priority OpenAI-compatible source is set, this key is reused for Anspire search + LLM path (example fallback behavior only).
# Example model: Doubao-Seed-2.0-lite; example gateway: https://open-gateway.anspire.cn/v6
ANSPIRE_API_KEYS=sk-xxxxxxxxxxxxxxxx
# Optional: switch example model or gateway according to your Anspire account and official docs.
# ANSPIRE_LLM_MODEL=Doubao-Seed-2.0-pro
# ANSPIRE_LLM_BASE_URL=https://open-gateway.anspire.ai/v6
```

### Example 1: Using a Third-party OpenAI-Compatible Platform (Highly Recommended)

Most third-party relay platforms and local API providers support the OpenAI interface format. As long as the platform provides an API Key and a Base URL, you can configure it easily using the following pattern:

```env
# Fill in the API Key provided by your platform
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
# Fill in the platform's API Base URL (Very Important: Usually must end with /v1)
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
# Fill in the specific model name (Very Important: You must add the "openai/" prefix so the system recognizes it)
LITELLM_MODEL=openai/deepseek-ai/DeepSeek-V3 
```

### Example 2: Using the Official DeepSeek API
```env
# Fill in the API Key requested from the official DeepSeek platform
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```
*Compatibility note: with only this line, the system still defaults to `deepseek/deepseek-chat` and logs a migration warning.*
`deepseek-chat` / `deepseek-reasoner` still work for compatibility with old configs, but DeepSeek marks them deprecated after 2026/07/24. New configs should migrate through the Web quick channel or explicitly set `LITELLM_MODEL=deepseek/deepseek-v4-flash` for `deepseek-v4-flash` / `deepseek-v4-pro`.

### Example 3: Using the Free Gemini API
```env
# Fill in your Google Gemini Key
GEMINI_API_KEY=AIzac...
```

### Example 4: Using Ollama Local Models
```env
# Ollama requires no API Key; works after running ollama serve locally
OLLAMA_API_BASE=http://localhost:11434
LITELLM_MODEL=ollama/qwen3:8b
```

> **Important**: Ollama must be configured with `OLLAMA_API_BASE`. **Do not** use `OPENAI_BASE_URL`, or the system will concatenate URLs incorrectly (e.g. 404, `api/generate/api/show`). For remote Ollama, set `OLLAMA_API_BASE` to the actual address (e.g. `http://192.168.1.100:11434`). Current dependency constraint is `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (matches requirements.txt).

> **Congratulations! If you're a beginner, you can stop reading here and run the program!**
> Want to test the connection? Open your terminal in the root directory and run: `python scripts/check_env.py --llm`

---

## Method 2: Channels Mode Config (Advanced/Multi-model)

**Goal:** I have Keys from multiple different platforms and want to use them together. If my primary model fails or the network drops, I want it to automatically switch to fallback models.

**Configure via Web UI directly:** After starting the application, you can do this visually under **System Settings -> AI Model -> AI Model Access** in the Web UI.

> **New editor behavior**: For DeepSeek, DashScope, and other OpenAI-compatible providers that expose `/v1/models`, the settings page can now fetch models directly from `{base_url}/models` and let you select multiple entries visually. The underlying storage format is still the existing comma-separated `LLM_{CHANNEL}_MODELS=model1,model2` value. If a provider does not support `/models`, authentication fails, or the endpoint is temporarily unavailable, you can still type the model list manually and save normally.

### First-run Setup Status

The backend exposes a read-only status endpoint at `GET /api/v1/system/config/setup/status`. It reports whether the minimum first-run pieces are present: primary LLM, Agent model inheritance/configuration, stock list, optional notification channel, and local storage. The endpoint only reads the saved `.env` plus the current process environment; it does not reload runtime config, write `.env`, test a real model, or create a database file. Frontend onboarding and later smoke-run flows can build on this endpoint incrementally.

### Web channel editor: compatibility, migration, and rollback rules

- The preset provider / Base URL / sample models are **form defaults only**. What gets persisted is still exactly what you submit in `LLM_{CHANNEL}_PROTOCOL`, `LLM_{CHANNEL}_BASE_URL`, `LLM_{CHANNEL}_MODELS`, and `LLM_{CHANNEL}_API_KEY(S)`; the editor does not silently rewrite them to a different provider name or URL.
- "Discover models" only calls `{base_url}/models` for `OpenAI Compatible` / `DeepSeek` channels, and the default "Test connection" action sends one minimal chat completion request against the first model in the list and shows the backend-normalized `resolved_model` in the result. If the response includes `details.reason=model_access_denied` (for example, the observed Issue #1208 SiliconFlow / OpenAI Compatible sample returned `Model disabled` through LiteLLM), treat it as a best-effort model availability diagnostic based on provider wording: first confirm that the tested model is enabled for the current account/key, then adjust the model order or remove unavailable models before retrying. Provider messages not covered by this conservative rule, or provider messages with different semantics, continue to use the fallback diagnostic path. Optional runtime capability checks must be explicitly selected by the user and send additional JSON / tools / stream / vision smoke requests; the result only represents a best-effort check for the current account, model, and endpoint at that moment. The returned `stage / error_code / details / latency_ms / capability_results` fields are for structured diagnostics only, are **never persisted** back into `.env`, and do not block saving.
- If the response includes `details.reason=provider_blocked`, the provider or relay gateway explicitly blocked this request. This is distinct from local network / TLS failures and `model_access_denied`; first check account risk controls, region or request-source restrictions, model entitlement, relay gateway policy, and content-safety policy.
- Runtime capability checks send real LLM requests and may incur token / image-input cost, RPM/TPM rate limiting, insufficient balance errors, or timeouts. A failed check may come from account permissions, model entitlement, endpoint region, balance, provider compatibility layers, or LiteLLM translation behavior; it does not prove that the provider globally lacks that capability. P3 does not include online smoke coverage for every real provider. Its compatibility basis is the repository dependency constraint `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`, LiteLLM `completion()` / OpenAI I/O format / streaming / exception mapping, and the OpenAI Chat Completions shapes for JSON mode, tool calling, streaming, and vision input.
- External references: LiteLLM Python SDK / OpenAI I/O format / streaming / exception mapping: <https://docs.litellm.ai/>; LiteLLM OpenAI-compatible routing: <https://docs.litellm.ai/docs/providers/openai_compatible>; OpenAI Chat Completions: <https://platform.openai.com/docs/api-reference/chat/create>; JSON mode: <https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat>; tool calling: <https://platform.openai.com/docs/guides/function-calling?api-mode=chat>; streaming: <https://platform.openai.com/docs/guides/streaming-responses?api-mode=chat>; vision input: <https://platform.openai.com/docs/guides/images-vision?api-mode=chat>.
- Saving channels only updates the keys submitted in that save operation; there is no whole-config silent migration when you switch channel settings. The one deliberate cleanup is runtime model references: if `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, or `LITELLM_FALLBACK_MODELS` point to models that no longer exist in the currently enabled channels, the editor clears/removes those stale references before saving so runtime calls do not keep targeting invalid models. Even when enabled channels expose no selectable models, stale managed-provider values without a matching legacy key are cleaned. `cohere/*`, `google/*`, and `xai/*` are kept as explicit direct-env compatibility examples for legacy retention behavior only, and are not a runtime availability guarantee.
- Backend consistency basis: runtime validation in `SystemConfigService._validate_llm_runtime_selection` (`src/services/system_config_service.py`) relies on `_uses_direct_env_provider` (`src/config.py`). Only `gemini`, `vertex_ai`, `anthropic`, `openai`, and `deepseek` are treated as managed key-backed providers; `cohere`, `google`, and `xai` are not in that allowlist, so they remain valid direct provider runtime entries.
- Rollback stays minimal: restore the previous channel model list and re-select the runtime models, or restore the previous `LLM_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `LLM_TEMPERATURE`, and `LLM_USAGE_HMAC_*` values from your desktop export / manual `.env` backup. No extra migration script is required.
- The current dependency constraint for this flow in the repository is `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (see `requirements.txt`). Regression coverage for it lives in `tests/test_system_config_service.py`, `tests/test_system_config_api.py`, and `apps/dsa-web/src/components/settings/__tests__/LLMChannelEditor.test.tsx`.

> **External provider model examples notice**: `cohere/*`, `google/*`, and `xai/*` provider-prefixed values are included here only to describe current runtime retention behavior and are **not** a global availability guarantee. Specific model names in docs or tests are configuration-retention examples, not production recommendations. Check the provider's official model/API docs and validate against the repository dependency constraint `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` before production use.

### Rollback & compatibility evidence

- Scope and cleanup behavior under `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`: only runtime references (`LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `LITELLM_FALLBACK_MODELS`) are sanitized during save; non-channel direct providers such as `cohere/*`, `google/*`, and `xai/*` are preserved.
- Rollback path: export desktop config, then restore the backup through `POST /api/v1/system/config/import`; or manually restore historical `.env` entries (`LITELLM_*`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `LLM_TEMPERATURE`, `LLM_USAGE_HMAC_*`) and restart.
- Rollback evidence: `tests/test_system_config_service.py::test_import_desktop_env_restores_runtime_models_after_cleanup` covers restore from exported desktop backup after runtime cleanup.
- Direct-provider evidence: `tests/test_system_config_service.py::SystemConfigServiceTestCase::test_validate_accepts_minimax_model_as_direct_env_provider`, `test_validate_accepts_cohere_model_as_direct_env_provider`, `test_validate_accepts_google_model_as_direct_env_provider`, and `test_validate_accepts_xai_model_as_direct_env_provider` cover the preserved direct-provider behavior.
- Frontend regression commands: `cd apps/dsa-web && npm run lint && npm run build && npm run test -- src/components/settings/__tests__/LLMChannelEditor.test.tsx`.
- Recommended rollback sequence (including UI reload): export desktop backup, restore via `POST /api/v1/system/config/import`, then call `GET /api/v1/system/config` to refresh the settings page and verify `LITELLM_MODEL` / `AGENT_LITELLM_MODEL` / `VISION_MODEL` / `LLM_TEMPERATURE` before continuing.

### Official references for provider presets / Base URLs / model naming

- OpenAI-compatible routing in LiteLLM: <https://docs.litellm.ai/docs/providers/openai_compatible>
- OpenAI official API docs: <https://platform.openai.com/docs/api-reference/chat>
- DeepSeek official API docs: <https://api-docs.deepseek.com/>
- Anspire Open: <https://open.anspire.cn/?share_code=QFBC0FYC>
- DashScope OpenAI-compatible mode: <https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- Moonshot / Kimi official compatibility docs: <https://platform.moonshot.ai/docs/guide/compatibility>
- Anthropic official Messages API: <https://docs.anthropic.com/en/api/messages>
- Gemini official OpenAI compatibility docs: <https://ai.google.dev/gemini-api/docs/openai>
- Cohere official: <https://docs.cohere.com/>
- Cohere API reference: <https://docs.cohere.com/reference/>
- Cohere LiteLLM provider page: <https://docs.litellm.ai/docs/providers/cohere>
- Google Gemini API and model list: <https://ai.google.dev/gemini-api/docs/openai>, <https://ai.google.dev/gemini-api/docs/models>
- Google LiteLLM provider page: <https://docs.litellm.ai/docs/providers/gemini>
- xAI official: <https://docs.x.ai/docs>
- xAI LiteLLM provider page: <https://docs.litellm.ai/docs/providers/xai>
- Ollama API docs: <https://github.com/ollama/ollama/blob/main/docs/api.md>

If you prefer modifying files, configuring this in the `.env` file is also very smooth. It allows you to manage multiple platforms simultaneously. The rules are:

1. **Declare your channels first**: `LLM_CHANNELS=channel_name_1,channel_name_2`
2. **Provide configurations for each channel** (Note the uppercase): `LLM_{CHANNEL_NAME}_XXX`

### Example: Configuring DeepSeek and a Third-party Relay with Fallbacks
```env
# 1. Enable channel mode, declare two channels here: deepseek and aihubmix
LLM_CHANNELS=deepseek,aihubmix

# 2. Channel 1: Configure Official DeepSeek
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_DEEPSEEK_API_KEY=sk-1111111111111
LLM_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro

# 3. Channel 2: Configure a common relay/proxy API
LLM_AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1
LLM_AIHUBMIX_API_KEY=sk-2222222222222
LLM_AIHUBMIX_MODELS=gpt-5.5,claude-sonnet-4-6

# 4. [Key Step] Specify the primary model and fallback list
# Set your primary model:
LITELLM_MODEL=deepseek/deepseek-v4-flash
# Optional: set an Agent-only primary model (empty = inherit the primary model)
AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro
# If the primary model crashes, try these fallbacks sequentially:
LITELLM_FALLBACK_MODELS=openai/gpt-5.4-mini,anthropic/claude-sonnet-4-6
```

### Example: Ollama Channel Mode (Local Models, No API Key)
```env
# 1. Enable channel mode, declare ollama channel
LLM_CHANNELS=ollama

# 2. Configure Ollama address (default local port 11434)
LLM_OLLAMA_BASE_URL=http://localhost:11434
LLM_OLLAMA_MODELS=qwen3:8b,llama3.2

# 3. Specify primary model
LITELLM_MODEL=ollama/qwen3:8b
```

### Example: Hermes Local HTTP Generation (Phase 3)
```env
LLM_CHANNELS=hermes
LLM_HERMES_PROTOCOL=openai
LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1
LLM_HERMES_API_KEY=sk-local-hermes
LLM_HERMES_MODELS=hermes-agent
LITELLM_MODEL=openai/hermes-agent
```

`hermes` is a reserved channel name for local loopback `/v1` OpenAI-compatible generation. Phase 3 only verifies regular analysis and JSON output. It does not support Stream/SSE, tools, Vision, Agent tools, remote Hermes, or process lifecycle management. Use exactly one `LLM_HERMES_API_KEY`; do not configure `LLM_HERMES_API_KEYS` or `LLM_HERMES_EXTRA_HEADERS`. If enabled Hermes config is invalid, DSA blocks legacy provider silent fallback so requests do not unexpectedly switch to an external model. When the Web settings page saves the reserved Hermes channel, it explicitly clears stale `LLM_HERMES_API_KEYS` / `LLM_HERMES_EXTRA_HEADERS` values and returns a warning. To recover previous values, restore them from a `.env` backup, Git history, or a desktop export backup, but Phase 3 will still reject non-empty multi-key or extra-header Hermes settings.

### MiniMax Model Naming in Channel Mode

- If you access MiniMax through an OpenAI-compatible channel, enter the model as `minimax/<model-name>` in the channel model list, for example `minimax/MiniMax-M1`.
- The Web settings page now keeps that value unchanged in Primary, Agent Primary, Fallback, and Vision selectors instead of rewriting it to `openai/minimax/<model-name>`.

### Default-Model Ask-Stock / LiteLLM Compatibility Notes

- With `AGENT_BACKEND=auto|litellm`, ask-stock follows the same three-tier runtime priority as the regular analyzer: `LITELLM_CONFIG` (LiteLLM YAML) > `LLM_CHANNELS` > legacy provider keys. Once an upper tier is valid and active, lower tiers are ignored for that request; Codex does not use this model route.
- In YAML mode, the Agent reuses LiteLLM `model_list` / `model_name` routing semantics directly. In channel mode, it first reads `AGENT_LITELLM_MODEL`; when that is empty it inherits `LITELLM_MODEL`, then continues through `LITELLM_FALLBACK_MODELS`.
- If you do not use YAML or Channels, leave `AGENT_LITELLM_MODEL` empty, and still rely on legacy provider env vars, the ask-stock Agent continues to inherit them: `GEMINI_API_KEY + GEMINI_MODEL` -> `gemini/<model>`, `OPENAI_API_KEY + OPENAI_MODEL` -> `openai/<model>`, and `ANTHROPIC_API_KEY + ANTHROPIC_MODEL` -> `anthropic/<model>`.
- This fix only improves two things: preserving the backend's real failure reason and returning a more specific diagnostic when no usable Agent LLM is configured. It does **not** silently delete, clear, migrate, or rewrite your existing `GEMINI_*`, `OPENAI_*`, `ANTHROPIC_*`, or `LITELLM_*` settings.
- If the current environment has no valid Agent model path at all, the ask-stock page still returns a failure and now surfaces the backend's real configuration diagnosis. As soon as you restore any valid model source, the flow recovers without running any migration step.
- The recommended forward path is still to configure `LITELLM_MODEL` / `AGENT_LITELLM_MODEL` explicitly or move to `LLM_CHANNELS`; legacy provider keys remain a compatibility fallback for older `.env` files, local macOS development, and existing deployments.

### Ask-Stock Visible Chat Context Compression

By default, ask-stock injects only the 20 most recent visible messages. The following LLM compression applies only to **Default model** ask-stock: Codex Agent always uses the 20 most recent user-visible messages and never calls `AGENT_LITELLM_MODEL` to summarize history. Switching to Codex does not clear the saved compression setting; it takes effect again after switching back to **Default model**.

```env
AGENT_CONTEXT_COMPRESSION_ENABLED=true
AGENT_CONTEXT_COMPRESSION_PROFILE=balanced
# Blank values follow the selected profile preset
AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS=
AGENT_CONTEXT_PROTECTED_TURNS=
```

Compression processes only visible `user` / `assistant` text under the same `session_id`. It does not process provider traces, thinking blocks, tool calls, or tool results, and it does not change same-turn tool passthrough. The presets are `cost` (6000 tokens / 2 protected turns), `balanced` (12000 / 4), and `long_context_raw_first` (24000 / 6). Blank trigger/protected values follow the selected profile; explicit values override it.

For the single-agent ask-stock path, the backend also keeps a provider-aware trace track for DeepSeek V4 thinking + tool-call roundtrip. A trace is persisted only when the same run has both `tool_calls` and `reasoning_content`; the last 3 minimal protocol slices per `session_id + provider + model` are spliced back into the next request before the anchored visible assistant reply. Provider trace is either preserved exactly or dropped as a whole; it is never summarized, never returned by Web session-history APIs, and adds no `.env` setting. Model/provider mismatch, summarized anchors, or insufficient budget drop the whole trace. Claude extended thinking is limited in this PR to adapter/storage-level opaque `thinking` / `redacted_thinking` / `signature` block plumbing with offline fixtures; production end-to-end Claude and multi-agent trace injection remain follow-ups. Protocol references: DeepSeek thinking mode (<https://api-docs.deepseek.com/guides/thinking_mode>) and Anthropic Claude extended thinking (<https://platform.claude.com/docs/en/docs/build-with-claude/extended-thinking>). The LiteLLM compatibility window remains `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` from `requirements.txt`.

### Strict Temperature Model Compatibility Notes

- Moonshot officially documents Kimi as an OpenAI-compatible API, with `https://api.moonshot.ai/v1` as the base URL: <https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart>
- LiteLLM officially requires the `openai/` prefix for OpenAI-compatible model routing: <https://docs.litellm.ai/docs/providers/openai_compatible>
- Moonshot's compatibility docs distinguish two fixed values: **thinking mode must use `1.0`, while non-thinking mode must use `0.6`**; other values are rejected by the API: <https://platform.moonshot.ai/docs/guide/compatibility#parameters-differences-in-request-body>
- The OpenAI Chat Completions API treats `temperature` as optional. For GPT-5 / o-series style models that only accept the provider default temperature, this project omits `temperature` at request time instead of rewriting your saved `LLM_TEMPERATURE`: <https://platform.openai.com/docs/api-reference/chat/create>
- The current runtime dependency constraint in this repository is `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (see `requirements.txt`); this compatibility fix is regression-covered under that constraint across the main analyzer, market review, direct Agent LiteLLM calls, and the system-settings channel connectivity test path.
- This repository therefore normalizes `kimi-k2.6` and `kimi-k2.6-*` right before dispatch based on the **actual request mode**: default / thinking requests use `temperature=1.0`; if your LiteLLM YAML route alias explicitly sets `litellm_params.extra_body.thinking.type: disabled` (or an equivalent non-thinking override), it automatically switches to `temperature=0.6`. Your saved `LLM_TEMPERATURE` value in `.env` or the Web settings is not rewritten.
- If a compatible platform returns an explicit parameter error for a not-yet-profiled model, such as unsupported `temperature`, default-only `1.0`, or unsupported `top_p`, the runtime repairs the **current request** and retries once. The strategy is cached only in the current process after the retry succeeds; it is never written back to `.env`, and a service restart re-evaluates the configured rules normally.
- For streaming responses that already produced partial content, the runtime does not switch parameters mid-output. It keeps the existing same-model non-stream retry / fallback-model path to avoid stitching inconsistent answers together.
- `SystemConfigService` only updates keys that you actually submit when saving from the Web settings page or importing a desktop `.env`; switching to a strict-temperature model does not silently clear, migrate, or rewrite an existing `LLM_TEMPERATURE`. Temporary request-time parameter strategies are not persisted back into the config file.
- Non-strict primary models, non-strict fallbacks, and any request after switching back to a regular model still use your configured temperature. Existing configs do not need migration; changing the model restores the original behavior automatically.
- Repository-side compatibility coverage lives in `tests/test_llm_channel_config.py`, `tests/test_market_analyzer_generate_text.py`, `tests/test_agent_pipeline.py`, and `tests/test_system_config_service.py`.
- Minimal rollback: revert only the LLM generation-parameter adaptation change set; no separate `LLM_TEMPERATURE` migration is required.

> **Critical Warning**: If you enable `LLM_CHANNELS`, any standard `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` declared independently will be **completely ignored**. **Use only one mode** to prevent configuration conflicts.
> **Docker note**: If `LITELLM_MODEL`, `LLM_CHANNELS`, `LLM_DEEPSEEK_MODELS`, or related variables are explicitly passed through `docker compose environment:` or `docker run -e`, they will override the `.env` written by the Web settings page after a container restart. Update the deployment environment at the same time.

### Compatibility evidence and rollback audit notes (for this recovery change)

- Compatibility is validated in two layers: first-party provider/API contract references (LiteLLM OpenAI-compatible routing, OpenAI Chat Completions, Moonshot/Kimi docs and model notes), and second the current runtime implementation in this repository under `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`.
- This recovery path is runtime-only and intentionally local: exception classification + one in-request repair retry + in-process cache. It does not rewrite `.env`, migrate saved config keys, or alter legacy values; it only omits/adjusts request parameters (`temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`) for the current call. Rolling back requires no migration; restore previous settings and model/provider selection.
- Regression evidence for this path is in `tests/test_llm_param_recovery.py`, `tests/test_system_config_service.py`, `tests/test_llm_channel_config.py`, `tests/test_system_config_api.py`, `tests/test_market_analyzer_generate_text.py`, `tests/test_agent_pipeline.py`; desktop backup import restore is directly covered by `test_import_desktop_env_restores_runtime_models_after_cleanup`.

---

## Method 3: Advanced YAML Config (Expert Setup)

**Goal:** I want maximum control and origin-level routing rules for enterprise-grade high availability.

This layer maps directly to the underlying LiteLLM routing capabilities, including high concurrency, automatic retries, and TPM/RPM-based load balancing.

1. Keep only one declaration line in your `.env`:
   ```env
   LITELLM_CONFIG=./litellm_config.yaml
   ```
2. Create a `litellm_config.yaml` in the project root directory (you can refer to `docs/examples/litellm_config.example.yaml`).

Example `litellm_config.yaml`:
```yaml
model_list:
  - model_name: my-smart-model
    litellm_params:
      model: deepseek/deepseek-v4-flash
      api_base: https://api.deepseek.com
      api_key: "os.environ/MY_CUSTOM_SECRET_KEY"  # Fetch from environment vars for security

  # Ollama local model (no api_key needed)
  - model_name: ollama/qwen3:8b
    litellm_params:
      model: ollama/qwen3:8b
      api_base: http://localhost:11434
```

> **Priority Rule**: YAML is king! If YAML is configured, both **Channels Mode** and **Simple Mode** are entirely ignored. Hierarchy: `YAML > Channels > Simple`.

### LLM usage HMAC telemetry

P0a usage telemetry creates HMAC-SHA256 fingerprints for the actual messages sent to the model. This only writes local `llm_usage` telemetry. It does not change prompts, provider parameters, cache hints, model output, or fallback order.

Usage is read in three tiers:

- Prefer the provider / LiteLLM public `usage` response field.
- Then read the LiteLLM public `usage_metadata` response field.
- Only then read `_hidden_params["usage"]`, which is a LiteLLM private/internal best-effort fallback rather than a stable public contract. If it is absent, usage/cache telemetry may be incomplete; the model request itself has not failed for that reason.

Cache-token normalization is allowlisted best-effort normalization only. The external field evidence and runtime boundaries are separated below so provider contracts, current LiteLLM normalization behavior, and repository-specific compatibility allowlists are not treated as the same thing:

| Provider / source | Fields read | Evidence and boundary | Coverage |
| --- | --- | --- | --- |
| OpenAI | `usage.prompt_tokens_details.cached_tokens` | The official Prompt Caching docs state that requests below 1024 tokens still expose `cached_tokens=0`: <https://developers.openai.com/api/docs/guides/prompt-caching> | Covered by unit/mock tests; this PR does not include OpenAI live smoke |
| Anthropic | `cache_creation_input_tokens` / `cache_read_input_tokens` / `input_tokens` | The official Prompt Caching docs define `total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens`: <https://platform.claude.com/docs/en/build-with-claude/prompt-caching> | Covered by unit/mock tests; this PR does not include Anthropic live smoke |
| Gemini / Vertex AI | Official source field: `UsageMetadata.cachedContentTokenCount`; runtime consumes LiteLLM-exposed snake_case / normalized fields such as `cached_content_token_count`, `cache_read_input_tokens`, or `prompt_tokens_details.cached_tokens` | Gemini `UsageMetadata` official field: <https://ai.google.dev/api/generate-content#UsageMetadata>. This repository does not add native camelCase runtime fallback; runtime compatibility is bounded to `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` | Covered by unit/mock tests; this PR does not include Gemini / Vertex live smoke |
| DeepSeek | `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` | DeepSeek Chat Completion docs state that `prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens`: <https://api-docs.deepseek.com/api/create-chat-completion> | Covered by unit/mock tests; this PR includes one redacted DeepSeek smoke only and does not store the full response |
| GLM / OpenAI-compatible / StepFun and similar compatible platforms | Values from the modeled token/cache count allowlist that can be normalized to common fields | No stable official cache telemetry contract is claimed here; this is best-effort normalization under the current LiteLLM / OpenAI-compatible shape. Unmodeled metadata is not persisted | Covered by unit/fixture/mock tests; this PR does not include live smoke for these providers |
| LiteLLM public response shape | `usage` / `usage_metadata` | Consumed according to the response / `Usage` object shape in the current dependency window `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`; this is not a LiteLLM 2.x compatibility guarantee | Covered by Analyzer / Agent / usage tests |
| LiteLLM private fallback | `_hidden_params["usage"]` | Private/internal best-effort fallback, not a stable LiteLLM public contract. It only fills narrow streaming telemetry gaps such as public zero-only/no-signal usage and does not change provider request parameters | Covered by unit/mock tests; absence only affects telemetry completeness, not model request success |

```env
LLM_USAGE_HMAC_SECRET=
LLM_USAGE_HMAC_KEY_VERSION=local-v1
```

- When `LLM_USAGE_HMAC_SECRET` is empty, the backend creates `.llm_usage_hmac_secret` in the data directory for local deployment-scoped comparisons.
- Set the same high-entropy random secret only when multiple deployments intentionally need comparable HMACs; generate one with `openssl rand -hex 32`.
- `.llm_usage_hmac_secret` is a local secret artifact and is ignored by filename in `.gitignore`.
- When rotating the secret, update `LLM_USAGE_HMAC_KEY_VERSION` so old and new fingerprints are not compared as if they used the same key.
- Do not reuse the login session secret and do not commit or expose the real secret in version control, issues, logs, or screenshots.

### Provider prompt cache configuration (P1 / P1.5)

Prompt-cache settings only control whether this project records cache usage / diagnostics and whether the main analysis path actively sends verified provider-specific hints. They do not control implicit or provider-managed cache behavior in OpenAI, Gemini, DeepSeek, or other providers.

```env
LLM_PROMPT_CACHE_TELEMETRY_ENABLED=true
LLM_PROMPT_CACHE_HINTS_ENABLED=false
LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL=off
```

- When `LLM_PROMPT_CACHE_TELEMETRY_ENABLED=false`, provider raw usage JSON, normalized cache fields, and cache-decision diagnostics are not persisted. Basic token usage remains compatible.
- `LLM_PROMPT_CACHE_HINTS_ENABLED=true` only allows the main analysis / analyzer LiteLLM path to send `prompt_cache_key`, `cache_control`, `user_id`, and similar hints for provider / route entries that are verified or smoke-tested in the registry. The ask-stock Agent path currently records capability / usage diagnostics only and does not actively send provider-specific hints. Unknown OpenAI-compatible gateways stay telemetry-only.
- `LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL=basic` provides non-sensitive enum decisions such as provider, API surface, verification status, hint applied, and disabled reason only through debug logs and test-observable objects. `debug` adds HMAC-derived route/cache diagnostics and matched caps id on the same surfaces, but still must not include raw prompts, request bodies, message content, raw stock/user values, webhooks, or API keys. These diagnostics are not public Usage API or ordinary settings-page output.
- The Provider Cache Capability Registry is a code-level manual registry in `src/llm/provider_cache.py`. Entries include `doc_sources`, `last_verified_at`, and `verification_status`; update them with tests when adding providers or upgrading LiteLLM.
- Prompt cache keys, route keys, and DeepSeek session isolation reuse `LLM_USAGE_HMAC_SECRET` / `.llm_usage_hmac_secret` with domain-separated HMACs. No prompt-cache-specific secret is introduced.

### Legacy message stability audit (P0.5a)

P0.5a adds internal stability-audit fields for the ordinary stock-analysis legacy `[system, user]` message path. The fields are written only to local `llm_usage` records. They reuse the message HMAC pipeline above and do not change prompt text, message order, provider request parameters, cache hints, model output, fallback order, the public Usage API, or Web pages.

The added fields are for maintainer diagnostics only:

- `language`, `market_group`, `analysis_mode`, `legacy_prompt_mode`, `provider`, `transport`, and `message_count` describe low-sensitivity routing context for the stock-analysis call.
- `skill_config_hmac` is an HMAC-SHA256 over the resolved skill prompt fragments, default skill policy, and legacy prompt mode. It lets maintainers tell whether the system message changes with skill configuration without storing raw skill text.
- `known_dynamic_marker_positions` is a JSON string. Each entry stores only `marker_name`, `message_role`, and `char_offset`; it does not store stock codes, stock names, dates, news body text, quote values, headers, response text, or prompt snippets.
- `estimated_total_prompt_tokens`, `approx_common_prefix_chars`, and `approx_common_prefix_tokens` use the repository's stable canonical render: messages are concatenated in order as `role + "\n" + content` with a fixed separator. This is not claimed to match provider wire bytes.
- `char_offset` is measured inside the matching message `content`. `approx_common_prefix_chars` is the character count from canonical-render start to the first known dynamic marker. When no marker is found, common-prefix fields stay `NULL`.
- Token estimates use `ceil(chars / 3)`. They are diagnostics only, do not replace provider usage, and are not used for cache-threshold decisions; Chinese text can be underestimated.

P0.5a does not introduce PromptBlock IR, `block_id`, `stability_class`, `static_prefix_hash`, or `dynamic_context_hash`. Agent, research, and market-review paths are not wired into this audit yet.

### GitHub Actions Notes

The bundled `00-daily-analysis.yml` explicitly passes the common LLM runtime fields to the job environment:

- Runtime selection: `GENERATION_BACKEND`, `GENERATION_FALLBACK_BACKEND`, `GENERATION_BACKEND_TIMEOUT_SECONDS`, `GENERATION_BACKEND_MAX_OUTPUT_BYTES`, `GENERATION_BACKEND_MAX_CONCURRENCY`, `LOCAL_CLI_BACKEND_MAX_CONCURRENCY`, `AGENT_GENERATION_BACKEND`, `LLM_CHANNELS`, `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `VISION_PROVIDER_PRIORITY`, `LLM_TEMPERATURE`, `LLM_USAGE_HMAC_SECRET`, `LLM_USAGE_HMAC_KEY_VERSION`, `LLM_PROMPT_CACHE_TELEMETRY_ENABLED`, `LLM_PROMPT_CACHE_HINTS_ENABLED`, `LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL`
- Multiple keys: `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`, `DEEPSEEK_API_KEYS` (the current workflow imports these from repository Secrets only, not from same-named Variables)
- Common channel names: `primary`, `secondary`, `aihubmix`, `deepseek`, `dashscope`, `zhipu`, `moonshot`, `minimax`, `volcengine`, `siliconflow`, `openrouter`, `gemini`, `anthropic`, `openai`, `ollama`

For example, if you set `LLM_CHANNELS=primary,deepseek` in GitHub Actions, also configure the corresponding `LLM_PRIMARY_*` and `LLM_DEEPSEEK_*` entries. The `LLM_<NAME>_API_KEY` / `LLM_<NAME>_API_KEYS` fields are also imported from repository Secrets only right now, so storing them in Variables will not work at runtime. If you use a custom channel name such as `my_proxy`, GitHub Actions must explicitly add matching `LLM_MY_PROXY_*` mappings in the workflow `env:` block. Local `.env` and Docker runs do not have this limitation.

---

## Advanced Feature: Vision Model Config

Certain specific features in our system (like uploading a stock chart screenshot to extract the stock code) require models capable of computer vision. You need to assign a dedicated vision model in your `.env`.

```env
# Specify your dedicated vision model name
VISION_MODEL=openai/gpt-5.5
# Make sure to provide its corresponding provider API KEY (e.g., OPENAI_API_KEY):
# OPENAI_API_KEY=xxx
```

**Vision Fallback Mechanism:** To prevent unexpected failures, the system has a built-in fallback strategy. If the primary vision model fails, it will attempt to use alternative vision-capable provider keys in the following order:
```env
# Default fallback sequence:
VISION_PROVIDER_PRIORITY=gemini,anthropic,openai
```

---

## Troubleshooting

Afraid you got the config wrong? Type the following commands in your terminal to diagnose:

- `python scripts/check_env.py --config`: Only verifies if the logic in your `.env` is structurally correct. (Provides instant results, no network calls, strictly checks for syntax omissions).
- `python scripts/check_env.py --llm`: Sends a real greeting to the LLM to test the actual endpoint. This thoroughly verifies if your **network is working** and if your **account has sufficient balance**.

### Common Pitfalls

| Weird Error You Got? | Likely Culprit | How to Fix It? |
|----------------------|----------------|----------------|
| **The UI says the primary model is not configured** | The system doesn't know which provider/model you want to use. | Add a clear instruction in `.env`: `LITELLM_MODEL=provider/your_model_name`. Example: `openai/gpt-5.5`. |
| **I added multiple provider Keys, why is only one working?** | You mixed the **Simple Mode** and **Channels Mode**! | Choose one path. For simple setups, delete anything starting with `LLM_CHANNELS`. To use multi-model fallbacks, migrate all your Keys into the `LLM_CHANNELS` setup. |
| **Returns 400, 401, or Invalid API Key** | The API Key is wrong, copied incompletely, account lacks credits, or you mistyped the model name (extremely common). | 1. Ensure there are no spaces at the start/end of your Key.<br> 2. Ensure your Base URL ends with `/v1`.<br> 3. Check if you forgot the `openai/` prefix on the model name! |
| **Kimi K2.6 returns `invalid temperature` (it may say only `1.0` or `0.6` is allowed)** | The model requires different fixed temperatures for thinking vs non-thinking mode, while older config or call paths may still pass `0.7`. | After this fix, default / thinking `kimi-k2.6` requests automatically use `temperature=1.0`; if you explicitly disable thinking in a LiteLLM YAML route, the request automatically uses `0.6` instead. Prefer `openai/kimi-k2.6` with your Moonshot or relay OpenAI-compatible Base URL and API key. Non-Kimi fallbacks still keep your configured `LLM_TEMPERATURE`. |
| **GPT-5 / o-series returns that `temperature` is unsupported or only the default is allowed** | These models only accept the provider default sampling parameters, while older call paths may still send `0.7`. | The request layer now omits `temperature` so the provider default is used. Your `.env` / Web `LLM_TEMPERATURE` is not rewritten, and regular models keep using it after you switch back. |
| **Spins endlessly, eventually hits Timeout/ConnectionRefused** | You are using restricted APIs (like Google/OpenAI) in a blocked region without a proxy, or your cloud server lacks external internet access. | Highly recommend using **official regional APIs** (like DeepSeek) or **OpenAI-compatible relay platforms**. Third-party platforms bypass these network constraints. |
| **Ollama returns 404, `Could not get model info`, or `api/generate/api/show`** | Using `OPENAI_BASE_URL` for Ollama makes the system concatenate URLs incorrectly | Use `OLLAMA_API_BASE=http://localhost:11434` or channel mode (`LLM_CHANNELS=ollama` + `LLM_OLLAMA_BASE_URL`) instead |

*Veteran's Tip: If you enable **Agent Mode (Deep-thinking & web-search)**, experience shows you should use a stronger model like `deepseek-v4-pro`. Trying to save money by using weak mini-models for agents will likely result in infinite loops or missed objectives.*
