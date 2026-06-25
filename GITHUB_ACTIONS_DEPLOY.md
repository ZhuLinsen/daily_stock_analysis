# GitHub Actions 部署指南

> 零服务器成本，每天自动运行股票分析，推送结果到你的手机/电脑

## 📋 目录

- [功能概览](#功能概览)
- [部署步骤](#部署步骤)
- [配置 Secrets](#配置-secrets)
- [配置自选股](#配置自选股)
- [手动运行](#手动运行)
- [查看报告](#查看报告)
- [常见问题](#常见问题)

---

## ✨ 功能概览

### 🎯 核心功能

| 功能 | 说明 |
|------|------|
| 📊 **实时行情** | 获取沪深两市实时股票价格、涨跌幅、成交量等 |
| 📈 **K线分析** | MA、MACD、RSI、乖离率等技术指标计算 |
| 🎯 **智能荐股** | 基于技术面的买入信号评估和风险提示 |
| 🌐 **大盘复盘** | 上证指数、深证成指、创业板指等大盘分析 |
| 🤖 **AI 解读** | 大模型生成专业分析报告 |
| 📱 **多渠道推送** | 飞书、企业微信、Telegram、邮件等 |
| ⏰ **定时运行** | 每个交易日收盘后自动执行 |

### 💰 成本

- **GitHub Actions**：免费（每月 2000 分钟额度，足够每天运行）
- **金融数据**：免费（腾讯财经、东方财富等公开数据源）
- **AI 模型**：免费（智谱 GLM-4.7-Flash 永久免费）

**总费用：0 元/月**

---

## 🚀 部署步骤

### 第一步：Fork 本仓库

1. 点击页面右上角的 **Fork** 按钮
2. 选择你的 GitHub 账号
3. 等待 Fork 完成

### 第二步：配置 Secrets

进入你的仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

#### 必选配置（AI 分析）

推荐使用**智谱 GLM-4.7-Flash**（永久免费）：

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `LLM_ZHIPU_API_KEY` | 你的智谱 API Key | 从 [open.bigmodel.cn](https://open.bigmodel.cn) 获取 |
| `LITELLM_MODEL` | `zhipu/glm-4.7-flash` | 默认使用的模型 |

> 💡 详细免费模型配置请参考 [FREE_LLM_SETUP.md](./FREE_LLM_SETUP.md)

#### 必选配置（自选股）

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `STOCK_LIST` | `600519,300750,002594` | 你关注的股票代码，逗号分隔 |

#### 可选配置（通知推送）

**飞书机器人（推荐）：**

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `FEISHU_WEBHOOK_URL` | 飞书机器人 Webhook 地址 | 飞书群 → 设置 → 群机器人 |
| `FEISHU_WEBHOOK_SECRET` | 飞书机器人签名密钥 | 可选，开启签名验证时需要 |

**企业微信：**

| Secret 名称 | 值 |
|------------|-----|
| `WECOM_WEBHOOK_URL` | 企业微信机器人 Webhook |

**Telegram：**

| Secret 名称 | 值 |
|------------|-----|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 接收消息的 Chat ID |

### 第三步：启用 Actions

1. 进入你的仓库 → **Actions** 标签页
2. 点击 **I understand my workflows, go ahead and enable them**
3. 找到 **每日股票分析** 工作流

### 第四步：手动测试运行

1. 在 Actions 页面点击 **每日股票分析**
2. 点击 **Run workflow** 按钮
3. 选择运行模式：
   - `full`：完整分析（股票 + 大盘）
   - `market-only`：仅大盘复盘
   - `stocks-only`：仅股票分析
4. 点击 **Run workflow**

🎉 恭喜！部署完成！

---

## ⚙️ 配置详解

### 运行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| `full` | `python main.py` | 完整分析：股票技术分析 + 大盘复盘 |
| `market-only` | `python main.py --market-review` | 仅大盘复盘 |
| `stocks-only` | `python main.py --no-market-review` | 仅股票分析 |

### 定时时间

- **默认**：每个交易日北京时间 18:00（UTC 10:00）
- **修改方式**：编辑 `.github/workflows/00-daily-analysis.yml` 中的 cron 表达式

```yaml
schedule:
  - cron: '0 10 * * 1-5'  # 周一到周五，UTC 10:00 = 北京时间 18:00
```

### 环境变量完整列表

#### AI 模型配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LITELLM_MODEL` | 默认使用的模型 | - |
| `LITELLM_FALLBACK_MODELS` | 降级模型列表 | - |
| `LLM_CHANNELS` | 启用的 LLM 渠道 | - |
| `LLM_ZHIPU_API_KEY` | 智谱 AI API Key | - |
| `LLM_VOLCENGINE_API_KEY` | 火山方舟 API Key | - |
| `LLM_SILICONFLOW_API_KEY` | 硅基流动 API Key | - |
| `LLM_DEEPSEEK_API_KEY` | DeepSeek API Key | - |

#### 股票配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `STOCK_LIST` | 自选股列表（逗号分隔） | `600519,300750,002594` |
| `MARKET_SCOPE` | 市场范围 | `cn` |

#### 通知配置

| 变量 | 说明 |
|------|------|
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook |
| `FEISHU_WEBHOOK_SECRET` | 飞书签名密钥 |
| `WECOM_WEBHOOK_URL` | 企业微信 Webhook |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID |
| `SMTP_HOST` / `SMTP_PORT` | 邮件 SMTP 配置 |
| `SMTP_USER` / `SMTP_PASSWORD` | 邮件账号密码 |
| `EMAIL_TO` | 收件人地址 |

---

## 📱 手动运行

### 方式一：网页操作

1. 进入仓库 → **Actions** → **每日股票分析**
2. 点击 **Run workflow**
3. 选择模式，点击运行

### 方式二：API 调用

可以通过 GitHub API 触发工作流，适合集成到其他系统。

---

## 📄 查看报告

### 方式一：Actions 日志

1. 进入 **Actions** → 点击某次运行
2. 点击 **analyze** job
3. 展开 **执行股票分析** 步骤
4. 可以看到完整的分析过程和结果

### 方式二：Artifacts 下载

1. 进入某次运行详情页
2. 在 **Artifacts** 部分找到 `analysis-reports-xxx`
3. 点击下载，包含完整的报告文件和日志

### 方式三：推送通知

如果配置了飞书/企业微信/Telegram 等推送渠道，报告会直接推送到对应平台。

---

## 🔧 常见问题

### Q: 为什么运行失败了？

A: 检查以下几点：
1. Secrets 是否配置正确
2. API Key 是否有效
3. 股票代码格式是否正确（6位数字）
4. 查看 Actions 日志中的具体错误信息

### Q: 数据是实时的吗？

A: 是的，数据来自腾讯财经、东方财富等公开数据源，是实时行情数据。但 GitHub Actions 定时运行，建议在收盘后运行。

### Q: 可以分析港股/美股吗？

A: 可以，项目支持港股和美股，需要配置对应的数据源。

### Q: 每天运行会消耗多少 Actions 额度？

A: 每次运行约 2-5 分钟，每月 2000 分钟免费额度，完全够用。

### Q: 可以自定义分析时间吗？

A: 可以，修改工作流中的 cron 表达式即可。注意使用 UTC 时间。

### Q: 如何添加更多股票？

A: 修改 `STOCK_LIST` 这个 Secret，添加更多股票代码，用逗号分隔。

### Q: AI 分析需要付费吗？

A: 不需要，使用智谱 GLM-4.7-Flash 等免费模型即可，永久免费。

---

## 📚 相关文档

- [FREE_LLM_SETUP.md](./FREE_LLM_SETUP.md) - 免费大模型配置指南
- [QUICKSTART_CN.md](./QUICKSTART_CN.md) - 国内用户快速开始
- [.env.example](./.env.example) - 完整环境变量配置模板

---

## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。
