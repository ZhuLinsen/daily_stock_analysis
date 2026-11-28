# Native 4-Protocol HTTPX + SSE Transport & `LLM_TRANSPORT_MODE`

`daily_stock_analysis` decouples stock analysis, Ask-Stock Agent, stock screening, Vision extraction, and Channel Test from direct `litellm` SDK imports through the unified boundary in `src/llm/transport.py`. Phase 2 adds a native `httpx` + SSE transport engine (`NativeUnifiedTransport` / `NativeUnifiedRouter`) behind an **env-only** rollout switch while keeping `LLM_TRANSPORT_MODE=litellm` as the default.

## Runtime Switch (`LLM_TRANSPORT_MODE`, Env-Only)

Configure `LLM_TRANSPORT_MODE` in `.env`, process environment variables, or GitHub Actions Variables/Secrets (it is intentionally not exposed in Web Settings during Phase 2 soak):

| Value | Behavior | LiteLLM Import |
| --- | --- | --- |
| `litellm` *(default)* | Uses `LiteLLMTransport`, preserving legacy `litellm` SDK routing and test-patch hooks. | On demand |
| `auto` | Routes **OpenAI Chat Completions**, **OpenAI Responses API**, **Anthropic Messages**, and **Google Gemini REST** through native `httpx` + SSE. Decisions happen **per alias group**: any alias backed by a cloud-IAM provider (`azure*`, `bedrock*`, `vertex_ai*`, `sagemaker*`, `cohere*`) or a missing-base custom provider is delegated to `LiteLLMTransport` without downgrading sibling native aliases. | Fallback alias only |
| `native` | Strictly enforces native HTTPX + SSE (`fallback_to_litellm=False`) with **zero** `litellm` import at startup or inference time. Fails closed (`NativeConfigError`) before any network I/O on unsupported providers or missing `api_base`. | Never imported |

Recognized aliases:
- `""`, `"litellm"` → `"litellm"`
- `"auto"`, `"native_httpx"`, `"hybrid"` → `"auto"`
- `"native"`, `"native_only"`, `"httpx"` → `"native"`
- Any unrecognized value logs an English warning and safely falls back to `"litellm"`.

## Deterministic Protocol Precedence (R1) & Opaque Wire Models (R4)

`src/llm/native_resolve.py` (`resolve_deployment()`) is the single shared resolver used by analyzer, Agent, Vision, screening, and Test Channel:

1. **Cloud-IAM fallback check first**: `azure`, `azure_ai`, `azure_text`, `bedrock`, `bedrock_mantle`, `vertex_ai`, `vertex_ai_beta`, `sagemaker*`, `cohere*` → `Unsupported` (even if `wire_protocol` is also set).
2. **Explicit `wire_protocol`**: `openai_chat`, `openai_responses`, `anthropic`, `gemini`.
3. **Explicit surface**: `model_info.dsa_api_surface` / `api_surface` (`chat_completions` → `openai_chat`; `responses` → `openai_responses`).
4. **Responses encoding or path**: `responses/<model>`, `openai/responses/<model>`, or `api_base` path ending in `/responses` → `openai_responses`.
5. **Explicit `custom_llm_provider`**: canonical native wire provider.
6. **Canonical wire provider prefix**: strips **at most one** leading canonical wire prefix (`openai/`, `anthropic/`, `gemini/`, `deepseek/`, `openrouter/`, `ollama/`, `groq/`, `xai/`, `together_ai/`, `fireworks_ai/`, `mistral/`, `perplexity/`, `moonshot/`, `dashscope/`, `minimax/`, `volcengine/`, `zai/`). Organization/vendor namespaces (`Qwen/...`, `deepseek-ai/...`, `anthropic/...` behind an OpenAI relay) are **never** stripped.
7. **`api_base` host/path rules**: `/v1beta/openai` or `/openai` → `openai_chat`; `api.anthropic.com` or `.../messages` → `anthropic`; `generativelanguage.googleapis.com` or `:generateContent` → `gemini`; any other custom URL → `openai_chat`.
8. **No model-name Responses auto-hijack**: `gpt-5`, `o3`, `o4`, and `codex` models default to `openai_chat` unless `responses` is explicitly selected via surface, encoding, or `/responses` URL.

Fail-closed endpoint & origin-bound credential guarantees:
- Non-`openai` providers without a verified default base URL (`custom`, `openai_compatible`, `vllm`, `hosted_vllm`, `lm_studio`, unknown prefixes) fail closed with **zero HTTP requests** instead of defaulting to `api.openai.com`.
- `os.environ/VAR` references in `api_key`, `api_base`, `base_url`, and `extra_headers` are expanded centrally; unset endpoint env vars fail closed.
- Provider env keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY`, `MISTRAL_API_KEY`, `TOGETHERAI_API_KEY`, `FIREWORKS_AI_API_KEY`, `PERPLEXITYAI_API_KEY`, `DEEPSEEK_API_KEY`, etc.) and `extra_headers` stay strictly origin-bound (`scheme + host + port`).

## Three Third-Party Relay Modes

Arbitrary third-party relays, aggregators, reverse proxies, and self-hosted servers work without vendor lock-in:

1. **OpenAI-Compatible Relay (`openai_chat` / `openai_responses`)**
   - Works with One-API, New-API, OpenRouter, AIHubmix, Modelflare, x6.ai, SiliconFlow, Requesty, Cloudflare/Vercel AI Gateway, Ollama (`http://127.0.0.1:11434` auto-normalizes to `/v1/chat/completions`), vLLM, LM Studio, and Hermes no-proxy loopback.
   - Preserves custom paths (`/v1`, `/api/v3`, `/api/paas/v4`, `/v6`, `/compatible-mode/v1`) and query strings, passes opaque model IDs (`claude-sonnet-4-6`, `gpt-5`, `Qwen/Qwen3-235B`, `anthropic/claude-sonnet-4`) verbatim, maps `max_tokens` → `max_completion_tokens` for `o1`/`o3`/`o4`/`gpt-5+` (with one-shot HTTP 400 recovery), and sends `stream_options` only when explicitly requested or targeting official `api.openai.com`.
2. **Anthropic Messages Proxy (`anthropic`)**
   - Set `PROTOCOL=anthropic` with any custom `BASE_URL` (with or without `/v1`; normalized cleanly to `/v1/messages` or `/messages` without duplicating `/v1`).
   - Sends `x-api-key` + `anthropic-version: 2023-06-01` (overrideable to `Authorization: Bearer ...` via `EXTRA_HEADERS`), preserves ordered `provider_blocks` (`thinking` + visible `text`) across multi-turn tool replay, keeps list-form system `cache_control`, and maps `reasoning_effort` to `thinking.budget_tokens`.
3. **Gemini REST Proxy (`gemini`)**
   - Set `PROTOCOL=gemini` with any custom `BASE_URL` (auto-appends `/v1beta` for both official Google endpoints and custom reverse proxies lacking `/v1`/`/v1beta`/`/v1alpha`/`/models/`, and merges `alt=sse` query-safely via `parse_qsl`/`urlencode` while preserving existing `?key=` params).
   - Uses `x-goog-api-key` header auth (unless `?key=` or `Authorization` is explicitly supplied), preserves/echoes `functionCall.id` and `thoughtSignature` on all parts, raises on `promptFeedback.blockReason`, and sanitizes tool JSON schemas to LiteLLM parity.

## Official Protocol Specifications

| Native Protocol | Wire Contract | Authoritative Official Sources |
| --- | --- | --- |
| `openai_chat` | `POST /chat/completions`; `Authorization: Bearer <key>`; JSON + SSE ending with `[DONE]` | [OpenAI Chat Completions Create](https://platform.openai.com/docs/api-reference/chat/create), [OpenAI Chat Streaming](https://platform.openai.com/docs/api-reference/chat-streaming), [LiteLLM OpenAI-Compatible](https://docs.litellm.ai/docs/providers/openai_compatible) |
| `openai_responses` | `POST /responses`; `Authorization: Bearer <key>`; `store=false` default + `include: ["reasoning.encrypted_content"]`; SSE ending with `response.completed` / `response.incomplete` | [OpenAI Responses Create](https://platform.openai.com/docs/api-reference/responses/create), [OpenAI Responses Streaming](https://platform.openai.com/docs/api-reference/responses-streaming), [Migrate to Responses](https://platform.openai.com/docs/guides/migrate-to-responses) |
| `anthropic` | `POST /v1/messages`; `x-api-key` + `anthropic-version: 2023-06-01`; ordered `thinking` + `text` + `tool_use` blocks; SSE ending with `message_stop` | [Anthropic Messages](https://docs.anthropic.com/en/api/messages), [Anthropic Messages Streaming](https://docs.anthropic.com/en/api/messages-streaming), [Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching), [Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking) |
| `gemini` | `POST /v1beta/models/{model}:generateContent` / `:streamGenerateContent?alt=sse`; `x-goog-api-key`; `systemInstruction`, `contents`, `inlineData`, `thoughtSignature`; SSE ending with `finishReason` | [Gemini generateContent](https://ai.google.dev/api/generate-content), [Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling), [Gemini Thinking](https://ai.google.dev/gemini-api/docs/thinking), [Gemini API Keys](https://ai.google.dev/gemini-api/docs/api-key) |

## Pool, SSE, Diagnostics & Rollback

- **Pool & Attempt Budget (`src/llm/native_pool.py`, `src/llm/native_engine.py`)**: exact alias matching, equal-priority round-robin rotation (`priority=0` default), cooldown skip honoring both numeric and HTTP-date `Retry-After`, total attempts capped at `1 + num_retries`, fail-fast on HTTP 400/413/422/404 and HTTP 200 HTML, and WAF/model-disabled HTTP 403 classified separately from bad API keys.
- **Deadline & Stream Ownership**: single monotonic deadline per logical call (respecting stock cancellation), cancellation checks inside the SSE chunk loop, closeable `NativeStreamWrapper` even when never iterated, BOM stripping, rejection of truncated EOF frames and missing terminal markers, and pooled `httpx.Client` cleanup on `reset_transport_cache()`.
- **Diagnostics**: `python main.py --doctor` reports `checks["llm"]["llm_transport_mode"]` and prints `transport=<mode>` on the `[llm]` line; usage audit records report the actual execution engine (`native` vs `litellm`).
- **Verification Boundary**: offline CI validates all 4 protocols, SSE fuzzing, pool properties, redaction, real-TCP loopback + proxy stub, and a LiteLLM-vs-native parity harness; live SaaS vendor endpoints require opt-in verification via **Test Channel** or soak runs before promoting defaults.
- **Instant Rollback**: unset `LLM_TRANSPORT_MODE` or set `LLM_TRANSPORT_MODE=litellm`.
