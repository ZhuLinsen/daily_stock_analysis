# Frequently Asked Questions (FAQ)

This document compiles common issues encountered by users and their solutions.

---

## Data Related

### Q1: US stock codes (e.g., AMD, AAPL) show incorrect prices during analysis?

**Symptom**: After entering US stock codes, displayed prices are clearly wrong (e.g., AMD showing 7.33 yuan), or being misidentified as A-shares.

**Cause**: Earlier version code matching logic prioritized A-share rules, causing code conflicts.

**Solution**:
1. Fixed in v2.3.0, system now supports automatic US stock code recognition
2. If issues persist, set in `.env`:
   ```bash
   YFINANCE_PRIORITY=0
   ```
   This prioritizes Yahoo Finance data source for US stock data

> Related Issue: [#153](https://github.com/ZhuLinsen/daily_stock_analysis/issues/153)

---

### Q2: "Volume Ratio" field shows empty or N/A in reports?

**Symptom**: Volume ratio data missing in analysis reports, affecting AI's judgment on volume changes.

**Cause**: Some default real-time quote sources (e.g., Sina interface) don't provide volume ratio field.

**Solution**:
1. Fixed in v2.3.0, Tencent interface now supports volume ratio parsing
2. Recommended real-time quote source priority:
   ```bash
   REALTIME_SOURCE_PRIORITY=tencent,akshare_sina,efinance,akshare_em
   ```
3. System has built-in 5-day average volume calculation as fallback

> Related Issue: [#155](https://github.com/ZhuLinsen/daily_stock_analysis/issues/155)

---

### Q3: Tushare data fetch failed, showing Token error?

**Symptom**: Log shows `Tushare data fetch failed: Your token is incorrect, please verify`

**Solution**:
1. **No Tushare account**: No need to configure `TUSHARE_TOKEN`, system will automatically use free data sources (AkShare, Efinance)
2. **Have Tushare account**: Verify Token is correct, check in [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638) personal center
3. All core features of this project work normally without Tushare

---

### Q4: Data fetch rate-limited or returning empty?

**Symptom**: Log shows `Circuit breaker triggered` or data returns `None`

**Cause**: Free data sources (Eastmoney, Sina, etc.) have anti-scraping mechanisms, high-frequency requests get rate-limited.

**Solution**:
1. System has built-in multi-source auto-switching and circuit breaker protection
2. Reduce watchlist size, or increase request intervals
3. Avoid frequently manually triggering analysis

---

## Configuration Related

### Q5: GitHub Actions run failed, showing environment variable not found?

**Symptom**: Actions log shows `GEMINI_API_KEY` or `STOCK_LIST` undefined

**Cause**: GitHub distinguishes `Secrets` (encrypted) and `Variables` (regular variables), wrong configuration location causes read failure.

**Solution**:
1. Go to repo `Settings` → `Secrets and variables` → `Actions`
2. **Secrets** (click `New repository secret`): Store sensitive information
   - `GEMINI_API_KEY`
   - `OPENAI_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - Various Webhook URLs
3. **Variables** (click `Variables` tab): Store non-sensitive configuration
   - `STOCK_LIST`
   - `GEMINI_MODEL`
   - `REPORT_TYPE`

---

### Q6: Configuration not taking effect after modifying .env file?

**Solution**:
1. Ensure `.env` file is in project root directory
2. **Docker deployment**: Restart container after modification
   ```bash
   docker-compose down && docker-compose up -d
   ```
3. **GitHub Actions**: `.env` file doesn't work, must configure in Secrets/Variables
4. Check if there are multiple `.env` files (e.g., `.env.local`) causing override

---

### Q7: How to configure proxy to access Gemini/OpenAI API?

**Solution**:

Configure in `.env`:
```bash
USE_PROXY=true
PROXY_HOST=127.0.0.1
PROXY_PORT=10809
```

> Note: Proxy configuration only works for local runs, GitHub Actions environment doesn't need proxy.

---

### LLM Configuration

> Full details: [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md).

**Q: Configured both GEMINI_API_KEY and LLM_CHANNELS, why does it only use channels?**

The system uses exactly one mode by priority: `LITELLM_CONFIG` (YAML) > `LLM_CHANNELS` > legacy keys. Once channels or YAML are configured, the legacy section (`GEMINI_API_KEY`, etc.) is not used.

**Q: test_env outputs ✗ No LLM configured, what to do?**

Configure `LITELLM_CONFIG` / `LLM_CHANNELS` or at least one `*_API_KEY` (e.g. `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `AIHUBMIX_KEY`). Run `python test_env.py --config` to validate config, `python test_env.py --llm` to actually call the API.

**Q: How to use multiple models at once (e.g. AIHubmix + DeepSeek + Gemini)?**

Use channel mode: set `LLM_CHANNELS=aihubmix,deepseek,gemini` and configure each channel's `LLM_{NAME}_BASE_URL`, `LLM_{NAME}_API_KEY`, `LLM_{NAME}_MODELS`. You can also configure visually in Web Settings → AI Model → Channel Editor.

---

## Push Notification Related

### Q8: Bot push failed, showing message too long?

**Symptom**: Analysis succeeded but no notification received, log shows 400 error or `Message too long`

**Cause**: Different platforms have different message length limits:
- WeChat Work: 4KB
- Feishu: 20KB
- DingTalk: 20KB

**Solution**:
1. **Auto-chunking**: Latest version implements automatic long message splitting
2. **Single stock push mode**: Set `SINGLE_STOCK_NOTIFY=true`, push immediately after each stock analysis
3. **Brief report**: Set `REPORT_TYPE=simple` for simplified format

---

### Q9: Not receiving Telegram push messages?

**Solution**:
1. Confirm both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured
2. How to get Chat ID:
   - Send any message to the Bot
   - Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find `chat.id` in the returned JSON
3. Ensure Bot has been added to target group (if group chat)
4. When running locally, need to be able to access Telegram API (may need proxy)

---

### Q10: WeChat Work Markdown format not displaying correctly?

**Solution**:
1. WeChat Work has limited Markdown support, try setting:
   ```bash
   WECHAT_MSG_TYPE=text
   ```
2. This will send plain text format messages

---

## AI Model Related

### Q11: Gemini API returns 429 error (too many requests)?

**Symptom**: Log shows `Resource has been exhausted` or `429 Too Many Requests`

**Solution**:
1. Gemini free tier has rate limits (about 15 RPM)
2. Reduce number of stocks analyzed simultaneously
3. Increase request delay:
   ```bash
   GEMINI_REQUEST_DELAY=5
   ANALYSIS_DELAY=10
   ```
4. Or switch to OpenAI-compatible API as backup

---

### Q12: How to use DeepSeek and other Chinese models?

**Configuration method**:

```bash
# No need to configure GEMINI_API_KEY
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
# Thinking mode: deepseek-reasoner, deepseek-r1, qwq auto-detected; deepseek-chat enabled by model name
```

Supported model services:
- DeepSeek: `https://api.deepseek.com/v1`
- Qwen (Tongyi Qianwen): `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Moonshot: `https://api.moonshot.cn/v1`

---

### Q12b: How to use Ollama local models?

**Configuration**: Use `OLLAMA_API_BASE` + `LITELLM_MODEL`, or channel mode (`LLM_CHANNELS=ollama` + `LLM_OLLAMA_BASE_URL` + `LLM_OLLAMA_MODELS`).

**Pitfall**: Do not use `OPENAI_BASE_URL` for Ollama, or LiteLLM will incorrectly concatenate URLs (e.g. 404, `api/generate/api/show`). See [LLM Config Guide](LLM_CONFIG_GUIDE_EN.md) Example 4 and channel examples.

---

## Docker Related

### Q13: Docker container exits immediately after starting?

**Solution**:
1. View container logs:
   ```bash
   docker logs <container_id>
   ```
2. Common causes:
   - Environment variables not correctly configured
   - `.env` file format error (e.g., extra spaces)
   - Dependency package version conflicts

---

### Q14: API service inaccessible in Docker?

**Solution**:
1. Ensure startup command includes `--host 0.0.0.0` (cannot be 127.0.0.1)
2. Check port mapping is correct:
   ```yaml
   ports:
     - "8000:8000"
   ```

---

## Other Issues

### Q15: How to run only market review, without stock analysis?

**Method**:
```bash
# Local run
python main.py --market-only

# GitHub Actions
# Select mode: market-only when manually triggering
```

---

### Q16: Buy/Hold/Sell counts in analysis results are incorrect?

**Cause**: Earlier versions used regex matching for statistics, may not match actual recommendations.

**Solution**: Fixed in latest version, AI model now directly outputs `decision_type` field for accurate statistics.

---

## Still Have Questions?

If the above content doesn't solve your issue, welcome to:
1. Check [Complete Configuration Guide](full-guide_EN.md)
2. Search or submit [GitHub Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
3. Check [Changelog](CHANGELOG.md) for latest fixes

---

*Last updated: 2026-02-01*
