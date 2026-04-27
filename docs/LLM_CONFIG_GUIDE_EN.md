# LLM Configuration Guide

Welcome! Whether you are a beginner newly exposed to AI or a veteran skilled with various APIs, this guide will help you set up Large Language Models (LLMs) quickly.

This project exposes a unified AI model access flow that supports official APIs, OpenAI-compatible platforms, and local models. Under the hood it is powered by [LiteLLM](https://docs.litellm.ai/), but most users only need to think in terms of picking a provider, adding an API key, and optionally choosing a primary model or channels. To cater to different experience levels, we provide a three-tier configuration hierarchy. Choose the method that fits you best.

---

## Quick Navigation: Which section should you read?

1. **[Beginners]** "I just want to get the system running ASAP, keep it as simple as possible!" -> [Go to Method 1: Simple Model Config](#method-1-simple-model-config-for-beginners)
2. **[Advanced Users]** "I have several Keys, want to configure fallback models, and define custom Base URLs." -> [Go to Method 2: Channels Mode Config](#method-2-channels-mode-config-advancedmulti-model)
3. **[Veterans]** "I want complex load balancing, request routing, and enterprise-level high availability!" -> [Go to Method 3: Advanced YAML Config](#method-3-advanced-yaml-config-expert-setup)
4. **[Local Models]** "I want to use Ollama local models!" -> [Go to Example 4: Using Ollama Local Models](#example-4-using-ollama-local-models)
5. **[Vision Models]** "I want to extract stock codes from images!" -> [Go to Vision Model Config](#advanced-feature-vision-model-config)

---

## Method 1: Simple Model Config (For Beginners)

**Goal:** Just paste your API Key and the model name to start using it immediately. No need to mess with complex concepts.

If you only plan to use one single model, this is the fastest way. Open the `.env` file in the project's root directory (if it doesn't exist, copy `.env.example` and rename it to `.env`).

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

> **Important**: Ollama must be configured with `OLLAMA_API_BASE`. **Do not** use `OPENAI_BASE_URL`, or the system will concatenate URLs incorrectly (e.g. 404, `api/generate/api/show`). For remote Ollama, set `OLLAMA_API_BASE` to the actual address (e.g. `http://192.168.1.100:11434`). Current dependency requirement is LiteLLM ≥1.80.10 (matches requirements.txt).

> **Congratulations! If you're a beginner, you can stop reading here and run the program!**
> Want to test the connection? Open your terminal in the root directory and run: `python test_env.py --llm`

---

## Method 2: Channels Mode Config (Advanced/Multi-model)

**Goal:** I have Keys from multiple different platforms and want to use them together. If my primary model fails or the network drops, I want it to automatically switch to fallback models.

**Configure via Web UI directly:** After starting the application, you can do this visually under **System Settings -> AI Model -> AI Model Access** in the Web UI.

> **New editor behavior**: For DeepSeek, DashScope, and other OpenAI-compatible providers that expose `/v1/models`, the settings page can now fetch models directly from `{base_url}/models` and let you select multiple entries visually. The underlying storage format is still the existing comma-separated `LLM_{CHANNEL}_MODELS=model1,model2` value. If a provider does not support `/models`, authentication fails, or the endpoint is temporarily unavailable, you can still type the model list manually and save normally.

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
LLM_AIHUBMIX_MODELS=gpt-4o-mini,claude-3-5-sonnet

# 4. [Key Step] Specify the primary model and fallback list
# Set your primary model:
LITELLM_MODEL=deepseek/deepseek-v4-flash
# Optional: set an Agent-only primary model (empty = inherit the primary model)
AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro
# If the primary model crashes, try these fallbacks sequentially:
LITELLM_FALLBACK_MODELS=openai/gpt-4o-mini,anthropic/claude-3-5-sonnet
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

### MiniMax Model Naming in Channel Mode

- If you access MiniMax through an OpenAI-compatible channel, enter the model as `minimax/<model-name>` in the channel model list, for example `minimax/MiniMax-M1`.
- The Web settings page now keeps that value unchanged in Primary, Agent Primary, Fallback, and Vision selectors instead of rewriting it to `openai/minimax/<model-name>`.

### Kimi K2.6 Fixed-Temperature Compatibility Notes

- Moonshot officially documents Kimi as an OpenAI-compatible API, with `https://api.moonshot.ai/v1` as the base URL: <https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart>
- LiteLLM officially requires the `openai/` prefix for OpenAI-compatible model routing: <https://docs.litellm.ai/docs/providers/openai_compatible>
- Moonshot's compatibility docs distinguish two fixed values: **thinking mode must use `1.0`, while non-thinking mode must use `0.6`**; other values are rejected by the API: <https://platform.moonshot.ai/docs/guide/compatibility#parameters-differences-in-request-body>
- The current runtime dependency window in this repository is `litellm>=1.80.10,<1.82.7` (see `requirements.txt`); this compatibility fix is regression-covered in that range across the main analyzer, market review, direct Agent LiteLLM calls, and the system-settings channel connectivity test path.
- This repository therefore normalizes `kimi-k2.6` and `kimi-k2.6-*` right before dispatch based on the **actual request mode**: default / thinking requests use `temperature=1.0`; if your LiteLLM YAML route alias explicitly sets `litellm_params.extra_body.thinking.type: disabled` (or an equivalent non-thinking override), it automatically switches to `temperature=0.6`. Your saved `LLM_TEMPERATURE` value in `.env` or the Web settings is not rewritten.
- `SystemConfigService` only updates keys that you actually submit when saving from the Web settings page or importing a desktop `.env`; switching to Kimi does not silently clear, migrate, or rewrite an existing `LLM_TEMPERATURE`. The temporary `1.0/0.6` used for Kimi channel tests is request-scoped and is not persisted back into the config file.
- Non-Kimi primary models, non-Kimi fallbacks, and any request after switching away from Kimi still use your configured temperature. Existing configs do not need migration; changing the model restores the original behavior automatically.
- Repository-side compatibility coverage lives in `tests/test_llm_channel_config.py`, `tests/test_market_analyzer_generate_text.py`, `tests/test_agent_pipeline.py`, and `tests/test_system_config_service.py`.
- Minimal rollback: revert only the Kimi fixed-temperature change set; no separate `LLM_TEMPERATURE` migration is required.

> **Critical Warning**: If you enable `LLM_CHANNELS`, any standard `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` declared independently will be **completely ignored**. **Use only one mode** to prevent configuration conflicts.
> **Docker note**: If `LITELLM_MODEL`, `LLM_CHANNELS`, `LLM_DEEPSEEK_MODELS`, or related variables are explicitly passed through `docker compose environment:` or `docker run -e`, they will override the `.env` written by the Web settings page after a container restart. Update the deployment environment at the same time.

---

## Method 3: Advanced YAML Config (Expert Setup)

**Goal:** I want maximum control and origin-level routing rules for enterprise-grade high availability.

This layer maps directly to the underlying LiteLLM routing capabilities, including high concurrency, automatic retries, and TPM/RPM-based load balancing.

1. Keep only one declaration line in your `.env`:
   ```env
   LITELLM_CONFIG=./litellm_config.yaml
   ```
2. Create a `litellm_config.yaml` in the project root directory (you can refer to `litellm_config.example.yaml`).

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

### GitHub Actions Notes

The bundled `daily_analysis.yml` explicitly passes the common LLM runtime fields to the job environment:

- Runtime selection: `LLM_CHANNELS`, `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `VISION_PROVIDER_PRIORITY`, `LLM_TEMPERATURE`
- Multiple keys: `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`, `DEEPSEEK_API_KEYS` (the current workflow imports these from repository Secrets only, not from same-named Variables)
- Common channel names: `primary`, `secondary`, `gemini`, `deepseek`, `aihubmix`, `openai`, `anthropic`, `moonshot`, `ollama`

For example, if you set `LLM_CHANNELS=primary,deepseek` in GitHub Actions, also configure the corresponding `LLM_PRIMARY_*` and `LLM_DEEPSEEK_*` entries. The `LLM_<NAME>_API_KEY` / `LLM_<NAME>_API_KEYS` fields are also imported from repository Secrets only right now, so storing them in Variables will not work at runtime. If you use a custom channel name such as `my_proxy`, GitHub Actions must explicitly add matching `LLM_MY_PROXY_*` mappings in the workflow `env:` block. Local `.env` and Docker runs do not have this limitation.

---

## Advanced Feature: Vision Model Config

Certain specific features in our system (like uploading a stock chart screenshot to extract the stock code) require models capable of computer vision. You need to assign a dedicated vision model in your `.env`.

```env
# Specify your dedicated vision model name
VISION_MODEL=gemini/gemini-2.5-flash
# Make sure to provide its corresponding provider API KEY (e.g., GEMINI_API_KEY):
# GEMINI_API_KEY=xxx
```

**Vision Fallback Mechanism:** To prevent unexpected failures, the system has a built-in fallback strategy. If the primary vision model fails, it will attempt to use alternative vision-capable provider keys in the following order:
```env
# Default fallback sequence:
VISION_PROVIDER_PRIORITY=gemini,anthropic,openai
```

---

## Troubleshooting

Afraid you got the config wrong? Type the following commands in your terminal to diagnose:

- `python test_env.py --config`: Only verifies if the logic in your `.env` is structurally correct. (Provides instant results, no network calls, strictly checks for syntax omissions).
- `python test_env.py --llm`: Sends a real greeting to the LLM to test the actual endpoint. This thoroughly verifies if your **network is working** and if your **account has sufficient balance**.

### Common Pitfalls

| Weird Error You Got? | Likely Culprit | How to Fix It? |
|----------------------|----------------|----------------|
| **The UI says the primary model is not configured** | The system doesn't know which provider/model you want to use. | Add a clear instruction in `.env`: `LITELLM_MODEL=provider/your_model_name`. Example: `openai/gpt-4o-mini`. |
| **I added multiple provider Keys, why is only one working?** | You mixed the **Simple Mode** and **Channels Mode**! | Choose one path. For simple setups, delete anything starting with `LLM_CHANNELS`. To use multi-model fallbacks, migrate all your Keys into the `LLM_CHANNELS` setup. |
| **Returns 400, 401, or Invalid API Key** | The API Key is wrong, copied incompletely, account lacks credits, or you mistyped the model name (extremely common). | 1. Ensure there are no spaces at the start/end of your Key.<br> 2. Ensure your Base URL ends with `/v1`.<br> 3. Check if you forgot the `openai/` prefix on the model name! |
| **Kimi K2.6 returns `invalid temperature` (it may say only `1.0` or `0.6` is allowed)** | The model requires different fixed temperatures for thinking vs non-thinking mode, while older config or call paths may still pass `0.7`. | After this fix, default / thinking `kimi-k2.6` requests automatically use `temperature=1.0`; if you explicitly disable thinking in a LiteLLM YAML route, the request automatically uses `0.6` instead. Prefer `openai/kimi-k2.6` with your Moonshot or relay OpenAI-compatible Base URL and API key. Non-Kimi fallbacks still keep your configured `LLM_TEMPERATURE`. |
| **Spins endlessly, eventually hits Timeout/ConnectionRefused** | You are using restricted APIs (like Google/OpenAI) in a blocked region without a proxy, or your cloud server lacks external internet access. | Highly recommend using **official regional APIs** (like DeepSeek) or **OpenAI-compatible relay platforms**. Third-party platforms bypass these network constraints. |
| **Ollama returns 404, `Could not get model info`, or `api/generate/api/show`** | Using `OPENAI_BASE_URL` for Ollama makes the system concatenate URLs incorrectly | Use `OLLAMA_API_BASE=http://localhost:11434` or channel mode (`LLM_CHANNELS=ollama` + `LLM_OLLAMA_BASE_URL`) instead |

*Veteran's Tip: If you enable **Agent Mode (Deep-thinking & web-search)**, experience shows you should use a stronger model like `deepseek-v4-pro`. Trying to save money by using weak mini-models for agents will likely result in infinite loops or missed objectives.*
