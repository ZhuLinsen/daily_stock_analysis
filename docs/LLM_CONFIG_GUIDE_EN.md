# LLM Configuration Guide

Welcome! Whether you are a beginner newly exposed to AI or a veteran skilled with various APIs, this guide will help you set up Large Language Models (LLMs) quickly.

Our LLM integration is powered by the robust and universal [LiteLLM](https://docs.litellm.ai/), which means we support almost all mainstream models on the market (both official APIs and third-party relay services). To cater to users at different experience levels, we have designed a "three-tier priority" configuration. Simply choose the method that suits you best.

---

## Quick Navigation: Which section should you read?

1. **[Beginners]** "I just want to get the system running ASAP, keep it as simple as possible!" -> [Go to Method 1: Simple Model Config](#method-1-simple-model-config-for-beginners)
2. **[Advanced Users]** "I have several Keys, want to configure fallback models, and define custom Base URLs." -> [Go to Method 2: Channels Mode Config](#method-2-channels-mode-config-advancedmulti-model)
3. **[Veterans]** "I want complex load balancing, request routing, and enterprise-level high availability!" -> [Go to Method 3: Advanced YAML Config](#method-3-advanced-yaml-config-expert-setup)
4. **[Vision Models]** "I want to extract stock codes from images!" -> [Go to Vision Model Config](#advanced-feature-vision-model-config)

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
*Note: Only this single line is needed. The system will automatically detect and default to the DeepSeek model.*

### Example 3: Using the Free Gemini API
```env
# Fill in your Google Gemini Key
GEMINI_API_KEY=AIzac...
```

> **Congratulations! If you're a beginner, you can stop reading here and run the program!**
> Want to test the connection? Open your terminal in the root directory and run: `python test_env.py --llm`

---

## Method 2: Channels Mode Config (Advanced/Multi-model)

**Goal:** I have Keys from multiple different platforms and want to use them together. If my primary model fails or the network drops, I want it to automatically switch to fallback models.

**Configure via Web UI directly:** After starting the application, you can do this visually under **System Settings -> AI Models -> Channel Editor** in the Web UI!

If you prefer modifying files, configuring this in the `.env` file is also very smooth. It allows you to manage multiple platforms simultaneously. The rules are:

1. **Declare your channels first**: `LLM_CHANNELS=channel_name_1,channel_name_2`
2. **Provide configurations for each channel** (Note the uppercase): `LLM_{CHANNEL_NAME}_XXX`

### Example: Configuring DeepSeek and a Third-party Relay with Fallbacks
```env
# 1. Enable channel mode, declare two channels here: deepseek and aihubmix
LLM_CHANNELS=deepseek,aihubmix

# 2. Channel 1: Configure Official DeepSeek
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
LLM_DEEPSEEK_API_KEY=sk-1111111111111
LLM_DEEPSEEK_MODELS=deepseek-chat,deepseek-reasoner

# 3. Channel 2: Configure a common relay/proxy API
LLM_AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1
LLM_AIHUBMIX_API_KEY=sk-2222222222222
LLM_AIHUBMIX_MODELS=gpt-4o-mini,claude-3-5-sonnet

# 4. [Key Step] Specify the primary model and fallback list
# Set your primary model:
LITELLM_MODEL=deepseek/deepseek-chat
# If the primary model crashes, try these fallbacks sequentially:
LITELLM_FALLBACK_MODELS=openai/gpt-4o-mini,anthropic/claude-3-5-sonnet
```

> **Critical Warning**: If you enable `LLM_CHANNELS`, any standard `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` declared independently will be **completely ignored**. **Use only one mode** to prevent configuration conflicts.

---

## Method 3: Advanced YAML Config (Expert Setup)

**Goal:** I want maximum control and origin-level routing rules for enterprise-grade high availability.

This project completely unlocks LiteLLM's native capabilities, supporting high concurrency, automatic retries, and TPM/RPM based load balancing.

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
      model: openai/deepseek-chat
      api_base: https://api.deepseek.com/v1
      api_key: "os.environ/MY_CUSTOM_SECRET_KEY"  # Fetch from environment vars for security
```

> **Priority Rule**: YAML is king! If YAML is configured, both **Channels Mode** and **Simple Mode** are entirely ignored. Hierarchy: `YAML > Channels > Simple`.

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
| **"LLM_MODEL is not configured" pops up** | The system doesn't know which brand's model you want to use. | Add a clear instruction in `.env`: `LITELLM_MODEL=provider/your_model_name`. Example: `openai/gpt-4o-mini`. |
| **I added multiple provider Keys, why is only one working?** | You mixed the **Simple Mode** and **Channels Mode**! | Choose one path. For simple setups, delete anything starting with `LLM_CHANNELS`. To use multi-model fallbacks, migrate all your Keys into the `LLM_CHANNELS` setup. |
| **Returns 400, 401, or Invalid API Key** | The API Key is wrong, copied incompletely, account lacks credits, or you mistyped the model name (extremely common). | 1. Ensure there are no spaces at the start/end of your Key.<br> 2. Ensure your Base URL ends with `/v1`.<br> 3. Check if you forgot the `openai/` prefix on the model name! |
| **Spins endlessly, eventually hits Timeout/ConnectionRefused** | You are using restricted APIs (like Google/OpenAI) in a blocked region without a proxy, or your cloud server lacks external internet access. | Highly recommend using **official regional APIs** (like DeepSeek) or **OpenAI-compatible relay platforms**. Third-party platforms bypass these network constraints. |

*Veteran's Tip: If you enable **Agent Mode (Deep-thinking & web-search)**, experience shows you should use an advanced reasoning model like `deepseek-reasoner`. Trying to save money by using weak mini-models for agents will likely result in infinite loops or missed objectives.*
