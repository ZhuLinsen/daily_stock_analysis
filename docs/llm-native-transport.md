# Native HTTPX LLM Transport & `LLM_TRANSPORT_MODE`

`daily_stock_analysis` decouples core analysis, Ask-Stock Agent, stock screening, Vision extraction, and Web channel verification from direct `litellm` SDK imports through the unified boundary in `src/llm/transport.py`.

## Runtime Switch (`LLM_TRANSPORT_MODE`)

Configure `LLM_TRANSPORT_MODE` in `.env` or environment variables:

| Value | Behavior | LiteLLM Import |
| --- | --- | --- |
| `litellm` *(default)* | Uses `LiteLLMTransport`, preserving legacy `litellm` SDK routing and test-patch hooks (`litellm.completion` / `Router`). | On demand |
| `auto` | Routes **OpenAI Chat Completions**, **OpenAI Responses API**, **Anthropic Messages**, and **Google Gemini REST** through native `httpx` (`NativeUnifiedTransport`); delegates non-native cloud IAM targets (`bedrock/`, `vertex_ai/`, `azure/`) to `LiteLLMTransport`. | Fallback only |
| `native` | Strictly enforces `NativeUnifiedTransport` (`fallback_to_litellm=False`) across all 4 native HTTPX protocols with **zero** `litellm` import at startup or inference time. Fails fast (`NativeBadRequestError`) on `bedrock/` / `vertex_ai/` / `azure/`. | Never imported |

Aliases recognized by `resolve_llm_transport_mode()`:
- `""`, `"litellm"` → `"litellm"`
- `"auto"`, `"native_httpx"`, `"hybrid"` → `"auto"`
- `"native"`, `"native_only"`, `"httpx"` → `"native"`
- Any unrecognized value logs an English warning and safely falls back to `"litellm"`.

## Supported Native Protocols

- **`openai_chat`**: OpenAI, DeepSeek, Moonshot, DashScope/Qwen, Zhipu/GLM, MiniMax, SiliconFlow, OpenRouter, Ollama, Groq, xAI, Mistral, Perplexity, and custom OpenAI-compatible gateways (`/chat/completions`).
- **`openai_responses`**: Selected when `LLM_<CHANNEL>_API_SURFACE=responses` (`openai/responses/<model>` wire encoding and `model_info.dsa_api_surface`), bare `responses/<model>`, explicit `wire_protocol="openai_responses"` / `api_surface="responses"`, an `api_base` ending in `/responses`, or default OpenAI reasoning/GPT-5 families (`gpt-5` excluding `chat-latest`, `o3`, `o4`, `codex`) targeting `/responses`. Setting `api_surface="chat_completions"` or `wire_protocol="openai_chat"` forces `/chat/completions` over heuristic inference. Decodes `openai/responses/<model>` to wire `model=<model>` before HTTP serialization and translates `tool_choice` and `response_format` (`json_object` / `json_schema` -> `text.format`).
- **`anthropic`**: Anthropic Messages API (`/v1/messages`) with `x-api-key` + `anthropic-version: 2023-06-01`, `system` + `cache_control`, Vision base64/URL, strict role alternation merging, `thinking` / `redacted_thinking` preservation, and SSE streaming.
- **`gemini`**: Google Gemini REST (`/v1beta/models/{model}:generateContent` & `:streamGenerateContent?alt=sse`) using header auth (`x-goog-api-key`, never URL query strings), `systemInstruction`, Vision `inlineData`, `thoughtSignature` round-trip preservation, and `usageMetadata` cache reporting.

## Official Protocol Specifications & Wire Mapping

The 4 native HTTPX protocol adapters track the vendor REST/SSE specifications and LiteLLM compatibility contracts below (see [LLM Providers Reference](llm-providers.md) for per-provider presets):

| Native Protocol | Endpoint & Auth Wire Contract | Authoritative Official Sources |
| --- | --- | --- |
| `openai_chat` | `POST /chat/completions`; `Authorization: Bearer <key>`; JSON + `stream_options.include_usage` + `choices[].delta` SSE | [OpenAI Chat Completions Create](https://platform.openai.com/docs/api-reference/chat/create), [OpenAI Chat Streaming](https://platform.openai.com/docs/api-reference/chat-streaming), [OpenAI Authentication](https://platform.openai.com/docs/api-reference/authentication), [LiteLLM OpenAI-Compatible](https://docs.litellm.ai/docs/providers/openai_compatible) |
| `openai_responses` | `POST /responses`; `Authorization: Bearer <key>`; `instructions` + `input` items, flattened `tools`/`tool_choice`, `max_output_tokens`, `text.format`, `response.output_text.delta` / `response.function_call_arguments.delta` / `response.completed` SSE | [OpenAI Responses Create](https://platform.openai.com/docs/api-reference/responses/create), [OpenAI Responses Streaming](https://platform.openai.com/docs/api-reference/responses-streaming), [Migrate to Responses](https://platform.openai.com/docs/guides/migrate-to-responses) |
| `anthropic` | `POST /v1/messages`; `x-api-key` + `anthropic-version: 2023-06-01`; `system`, alternating `user`/`assistant` content blocks, `thinking`/`redacted_thinking`, `cache_control`, `message_start` / `content_block_*` / `message_delta` SSE | [Anthropic Messages](https://docs.anthropic.com/en/api/messages), [Anthropic Messages Streaming](https://docs.anthropic.com/en/api/messages-streaming), [API Versioning](https://docs.anthropic.com/en/api/versioning), [Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching), [Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking) |
| `gemini` | `POST /v1beta/models/{model}:generateContent` / `:streamGenerateContent?alt=sse`; `x-goog-api-key` header; `systemInstruction`, `contents`, `tools[].functionDeclarations`, `toolConfig`, `inlineData`, `thoughtSignature` | [Gemini generateContent](https://ai.google.dev/api/generate-content), [Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling), [Gemini Thinking](https://ai.google.dev/gemini-api/docs/thinking), [Gemini API Keys](https://ai.google.dev/gemini-api/docs/api-key) |

## Verification Scope & Opt-In Rollout Boundaries

- **Default safety**: `LLM_TRANSPORT_MODE` defaults to `"litellm"`, leaving existing production routing completely unchanged unless `auto` or `native` is explicitly configured.
- **Offline CI coverage**: Automated verification covers wire-model/surface decoding (`openai/responses/<model>` and `model_info.dsa_api_surface`), request/response/SSE schema normalization across all 4 protocols, all runtime call sites (`Config`, `GeminiAnalyzer`, `LLMToolAdapter`, `image_stock_extractor`, `screening/ranker`, `SystemConfigService`), and real local TCP loopback HTTP/1.1 + `Transfer-Encoding: chunked` SSE transport execution (`ThreadingHTTPServer` + real `httpx.Client`) in `tests/test_llm_native_all_protocols.py` and `tests/test_llm_native_cutover_e2e.py`.
- **Live vendor boundary**: Automated CI runs offline without live vendor API keys and therefore does not hit third-party SaaS endpoints directly. Before switching a deployment to `LLM_TRANSPORT_MODE=auto` or `native`, run **Settings -> Test Channel** (which exercises `test_llm_channel` through the active transport) and `python main.py --doctor` / `--dry-run`, or revert immediately to `LLM_TRANSPORT_MODE=litellm`.

## Pooled Failover, Retry Semantics, Hermes No-Proxy, and Secret Redaction

- **Thread-safe `DeploymentPool`**: Priority tiers + round-robin selection with `Retry-After`-aware exponential cooldown on `429`/`401`/`403`/`5xx`/transport failures.
- **Transient Retry (`num_retries`) & Bad-Key Exclusion**: Requests passing `num_retries > 0` retry across remaining healthy candidates only on transient failures (`429`, `5xx`, timeout, transport error, invalid JSON); deterministic client errors (`400`/`413`/`422`) fail fast, `401`/`403` credentials are excluded via `bad_auth_ids` for subsequent rounds, and `raise_if_stock_cancelled` aborts retries cleanly on cancellation.
- **SSE Pre-First-Chunk Safety**: Failover and transient retries occur only before the first chunk is yielded; transport failures or mid-stream aborts after streaming begins raise immediately without duplicating partial output.
- **Protocol Kwarg Filtering**: Non-protocol orchestrator kwargs (`num_retries`, `fallbacks`, `metadata`, `caching`) are consumed or stripped before HTTP JSON serialization.
- **Hybrid `auto` Exception Matching**: `resolve_exception_types(...)` returns unified catchable exception tuples covering both native exceptions (`NativeRateLimitError`, `NativeContextWindowError`, etc.) and any already-loaded `litellm.*` fallback exception classes without eagerly importing `litellm` in `native` mode.
- **Programmatic Config Helpers**: `resolve_llm_transport_mode_for_config(config)` and `get_transport_for_config(config)` honor `os.getenv("LLM_TRANSPORT_MODE")` first and fall back cleanly to programmatic `config.llm_transport_mode`.
- **Hermes No-Proxy Clients**: Local Hermes channels passing `open_hermes_no_proxy_client(...)` preserve the injected no-proxy `httpx.Client` without closing it prematurely or serializing `client` into request JSON.
- **Secret Redaction**: `x-api-key`, `x-goog-api-key`, `Authorization: Bearer ...`, `?key=...`, and `sk-*` tokens are scrubbed from raised exceptions and warning logs.

## Diagnostics & Web Settings

- **CLI / Doctor**: `python main.py --doctor` (`run_doctor_diagnostics`) reports the effective transport mode in `checks["llm"]["llm_transport_mode"]` and prints `transport=<mode>` on the `[llm]` summary line.
- **Web Settings UI**: `LLM_TRANSPORT_MODE` is registered in `src/core/config_registry.py` under `ai_model` (`litellm`, `auto`, `native`) with full `zh`/`en` localization and help tooltips.

## Rollback

To restore legacy SDK behavior immediately, unset `LLM_TRANSPORT_MODE` or set:

```env
LLM_TRANSPORT_MODE=litellm
```
