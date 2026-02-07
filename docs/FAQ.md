# ❓ 常见问题解答 (FAQ)

本文档整理了用户在使用过程中遇到的常见问题及解决方案。

---

## 📊 数据相关

### Q1: 美股代码（如 AMD, AAPL）分析时价格显示不正确？

**现象**：输入美股代码后，显示的价格明显不对（如 AMD 显示 7.33 元），或被误识别为 A 股。

**原因**：早期版本代码匹配逻辑优先尝试国内 A 股规则，导致代码冲突。

**解决方案**：
1. 已在 v2.3.0 修复，系统现在支持美股代码自动识别
2. 如仍有问题，可在 `.env` 中设置：
   ```bash
   YFINANCE_PRIORITY=0
   ```
   这将优先使用 Yahoo Finance 数据源获取美股数据

> 📌 相关 Issue: [#153](https://github.com/ZhuLinsen/daily_stock_analysis/issues/153)

---

### Q2: 报告中"量比"字段显示为空或 N/A？

**现象**：分析报告中量比数据缺失，影响 AI 对缩放量的判断。

**原因**：默认的某些实时行情源（如新浪接口）不提供量比字段。

**解决方案**：
1. 已在 v2.3.0 修复，腾讯接口现已支持量比解析
2. 推荐配置实时行情源优先级：
   ```bash
   REALTIME_SOURCE_PRIORITY=tencent,akshare_sina,efinance,akshare_em
   ```
3. 系统已内置 5 日均量计算作为兜底逻辑

> 📌 相关 Issue: [#155](https://github.com/ZhuLinsen/daily_stock_analysis/issues/155)

---

### Q3: Tushare 获取数据失败，提示 Token 不对？

**现象**：日志显示 `Tushare 获取数据失败: 您的token不对，请确认`

**解决方案**：
1. **无 Tushare 账号**：无需配置 `TUSHARE_TOKEN`，系统会自动使用免费数据源（AkShare、Efinance）
2. **有 Tushare 账号**：确认 Token 是否正确，可在 [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) 个人中心查看
3. 本项目所有核心功能均可在无 Tushare 的情况下正常运行

---

### Q4: 数据获取被限流或返回为空？

**现象**：日志显示 `熔断器触发` 或数据返回 `None`

**原因**：免费数据源（东方财富、新浪等）有反爬机制，短时间大量请求会被限流。

**解决方案**：
1. 系统已内置多数据源自动切换和熔断保护
2. 减少自选股数量，或增加请求间隔
3. 避免频繁手动触发分析

---

## ⚙️ 配置相关

### Q5: GitHub Actions 运行失败，提示找不到环境变量？

**现象**：Actions 日志显示 `GEMINI_API_KEY` 或 `STOCK_LIST` 未定义

**原因**：GitHub 区分 `Secrets`（加密）和 `Variables`（普通变量），配置位置不对会导致读取失败。

**解决方案**：
1. 进入仓库 `Settings` → `Secrets and variables` → `Actions`
2. **Secrets**（点击 `New repository secret`）：存放敏感信息
   - `GEMINI_API_KEY`
   - `OPENAI_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - 各类 Webhook URL
3. **Variables**（点击 `Variables` 标签）：存放非敏感配置
   - `STOCK_LIST`
   - `GEMINI_MODEL`
   - `REPORT_TYPE`

---

### Q6: 修改 .env 文件后配置没有生效？

**解决方案**：
1. 确保 `.env` 文件位于项目根目录
2. **Docker 部署**：修改后需重启容器
   ```bash
   docker-compose down && docker-compose up -d
   ```
3. **GitHub Actions**：`.env` 文件不生效，必须在 Secrets/Variables 中配置
4. 检查是否有多个 `.env` 文件（如 `.env.local`）导致覆盖

---

### Q7: 如何配置代理访问 Gemini/OpenAI API？

**解决方案**：

在 `.env` 中配置：
```bash
USE_PROXY=true
PROXY_HOST=127.0.0.1
PROXY_PORT=10809
```

> ⚠️ 注意：代理配置仅对本地运行生效，GitHub Actions 环境无需配置代理。

---

## 📱 推送相关

### Q8: 机器人推送失败，提示消息过长？

**现象**：分析成功但未收到推送，日志显示 400 错误或 `Message too long`

**原因**：不同平台消息长度限制不同：
- 企业微信：4KB
- 飞书：20KB
- 钉钉：20KB

**解决方案**：
1. **自动分块**：最新版本已实现长消息自动切割
2. **单股推送模式**：设置 `SINGLE_STOCK_NOTIFY=true`，每分析完一只股票立即推送
3. **精简报告**：设置 `REPORT_TYPE=simple` 使用精简格式

---

### Q9: Telegram 推送收不到消息？

**解决方案**：
1. 确认 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 都已配置
2. 获取 Chat ID 方法：
   - 给 Bot 发送任意消息
   - 访问 `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - 在返回的 JSON 中找到 `chat.id`
3. 确保 Bot 已被添加到目标群组（如果是群聊）
4. 本地运行时需要能访问 Telegram API（可能需要代理）

---

### Q10: 企业微信 Markdown 格式显示不正常？

**解决方案**：
1. 企业微信对 Markdown 支持有限，可尝试设置：
   ```bash
   WECHAT_MSG_TYPE=text
   ```
2. 这将发送纯文本格式的消息

---

## 🤖 AI 模型相关

### Q11: Gemini API 返回 429 错误（请求过多）？

**现象**：日志显示 `Resource has been exhausted` 或 `429 Too Many Requests`

**解决方案**：
1. Gemini 免费版有速率限制（约 15 RPM）
2. 减少同时分析的股票数量
3. 增加请求延迟：
   ```bash
   GEMINI_REQUEST_DELAY=5
   ANALYSIS_DELAY=10
   ```
4. 或切换到 OpenAI 兼容 API 作为备选

---

### Q12: 如何使用 DeepSeek 等国产模型？

**配置方法**：

```bash
# 不需要配置 GEMINI_API_KEY
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
```

支持的模型服务：
- DeepSeek: `https://api.deepseek.com/v1`
- 通义千问: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Moonshot: `https://api.moonshot.cn/v1`

---

## 🐳 Docker 相关

### Q13: Docker 容器启动后立即退出？

**解决方案**：
1. 查看容器日志：
   ```bash
   docker logs <container_id>
   ```
2. 常见原因：
   - 环境变量未正确配置
   - `.env` 文件格式错误（如有多余空格）
   - 依赖包版本冲突

---

### Q14: Docker 中 WebUI 无法访问？

**解决方案**：
1. 确保 `WEBUI_HOST=0.0.0.0`（不能是 127.0.0.1）
2. 检查端口映射是否正确：
   ```yaml
   ports:
     - "8000:8000"
   ```

---

## 🔧 其他问题

### Q15: 如何只运行大盘复盘，不分析个股？

**方法**：
```bash
# 本地运行
python main.py --market-only

# GitHub Actions
# 手动触发时选择 mode: market-only
```

---

### Q16: 分析结果中买入/观望/卖出数量统计不对？

**原因**：早期版本使用正则匹配统计，可能与实际建议不一致。

**解决方案**：已在最新版本中修复，AI 模型现在会直接输出 `decision_type` 字段用于准确统计。

---

## 💬 还有问题？

如果以上内容没有解决你的问题，欢迎：
1. 查看 [完整配置指南](full-guide.md)
2. 搜索或提交 [GitHub Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
3. 查看 [更新日志](CHANGELOG.md) 了解最新修复

---

*最后更新：2026-02-01*
