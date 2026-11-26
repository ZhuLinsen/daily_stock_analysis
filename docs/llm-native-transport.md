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
- **`openai_responses`**: OpenAI `gpt-5` (non-`chat-latest`), `o3`, `o4`, `codex`, or channels configured with `/responses` (`/responses`).
- **`anthropic`**: Anthropic Messages API (`/v1/messages`) with `x-api-key` + `anthropic-version: 2023-06-01`, `system` + `cache_control`, Vision base64/URL, strict role alternation merging, `thinking` / `redacted_thinking` preservation, and SSE streaming.
- **`gemini`**: Google Gemini REST (`/v1beta/models/{model}:generateContent` & `:streamGenerateContent?alt=sse`) using header auth (`x-goog-api-key`, never URL query strings), `systemInstruction`, Vision `inlineData`, `thoughtSignature` round-trip preservation, and `usageMetadata` cache reporting.

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
