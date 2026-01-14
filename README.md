# 📈 A股智能分析系统

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)

> 🤖 基于 AI 大模型的 A 股自选股智能分析系统，每日自动分析并推送「决策仪表盘」到企业微信/飞书/Telegram/邮箱

![运行效果演示](./sources/all_2026-01-13_221547.gif)

## ✨ 功能特性

### 🎯 核心功能
- **AI 决策仪表盘** - 一句话核心结论 + 精确买卖点位 + 检查清单
- **多维度分析** - 技术面 + 筹码分布 + 舆情情报 + 实时行情
- **大盘复盘** - 每日市场概览、板块涨跌、北向资金
- **多渠道推送** - 支持企业微信、飞书、Telegram、邮件（自动识别）
- **零成本部署** - GitHub Actions 免费运行，无需服务器
- **💰 白嫖 Gemini API** - Google AI Studio 提供免费额度，个人使用完全够用
- **🔄 多模型支持** - 支持 OpenAI 兼容 API（DeepSeek、通义千问等）作为备选

### 📊 数据来源
- **行情数据**: AkShare（免费）、Tushare、Baostock、YFinance
- **新闻搜索**: Tavily、SerpAPI
- **AI 分析**: 
  - 主力：Google Gemini（gemini-3-flash-preview）—— [免费获取](https://aistudio.google.com/)
  - 备选：应大家要求，也支持了OpenAI 兼容 API（DeepSeek、通义千问、Moonshot 等）

### 🛡️ 交易理念内置
- ❌ **严禁追高** - 乖离率 > 5% 自动标记「危险」
- ✅ **趋势交易** - MA5 > MA10 > MA20 多头排列
- 📍 **精确点位** - 买入价、止损价、目标价
- 📋 **检查清单** - 每项条件用 ✅⚠️❌ 标记

## 🚀 快速开始

### 方式一：GitHub Actions（推荐，零成本）

**无需服务器，每天自动运行！**

#### 1. Fork 本仓库

点击右上角 `Fork` 按钮

#### 2. 配置 Secrets

进入你 Fork 的仓库 → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

**AI 模型配置（二选一）**

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) 获取免费 Key | ✅* |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（支持 DeepSeek、通义千问等） | 可选 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址（如 `https://api.deepseek.com/v1`） | 可选 |
| `OPENAI_MODEL` | 模型名称（如 `deepseek-chat`） | 可选 |
| `OPENAI_RESERVE_PROVIDERS` | OpenAI 兼容备用 Provider 池（JSON 数组，base_url/api_key/model 缺一不可） | 可选 |

> *注：`GEMINI_API_KEY` 和 `OPENAI_API_KEY` 至少配置一个

**通知渠道配置（可同时配置多个，全部推送）**

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `WECHAT_WEBHOOK_URL` | 企业微信 Webhook URL | 可选 |
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook URL | 可选 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（@BotFather 获取） | 可选 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可选 |
| `EMAIL_SENDER` | 发件人邮箱（如 `xxx@qq.com`） | 可选 |
| `EMAIL_PASSWORD` | 邮箱授权码（非登录密码） | 可选 |
| `EMAIL_RECEIVERS` | 收件人邮箱（多个用逗号分隔，留空则发给自己） | 可选 |
| `CUSTOM_WEBHOOK_URLS` | 自定义 Webhook（多个用逗号分隔） | 可选 |                                                                                                            | 可选 |
| `FEISHU_APP_ID` | 飞书应用ID，需要去（[开发者后台](https://open.feishu.cn/app)创建应用，步骤参考[这里](https://blog.csdn.net/qq_38423105/article/details/149316776)） | 可选 |
| `FEISHU_APP_SECRET` | 飞书应用APP_SECRET                                                                                                            | 可选 |
| `FEISHU_FOLDER_TOKEN` | 飞书文档云盘文件夹Key(地址栏 folder 后面参数)  | 可选 |  

> *注：至少配置一个渠道，配置多个则同时推送到所有渠道
> 
> 自定义 Webhook 支持：钉钉、Discord、Slack、Bark、自建服务等任意支持 POST JSON 的 Webhook
> 

> 通过飞书应用创建的飞书文档，里面的内容不会出现已截断的情况。应用创建好后需要执行以下操作：
> 
> 1.Github 配置对应 Secret
> 
> 2.创建群组，在群组设置->群机器人，将创建的应用添加到群组内，算上飞书 Webhook，此时群组应该会有两个机器人 
> 
> 3.点击飞书云盘文件夹的“...”,将群组添加为协作者，权限设置为可管理

**其他配置**

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `STOCK_LIST` | 自选股代码，如 `600519,300750,002594` | ✅ |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) 搜索 API（新闻搜索） | 推荐 |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/) 备用搜索 | 可选 |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/) Token | 可选 |

#### 3. 启用 Actions

进入 `Actions` 标签 → 点击 `I understand my workflows, go ahead and enable them`

#### 4. 手动测试

`Actions` → `每日股票分析` → `Run workflow` → 选择模式 → `Run workflow`

#### 5. 完成！

默认每个工作日 **18:00（北京时间）** 自动执行

### 方式二：本地运行

```bash
# 克隆仓库
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
vim .env  # 填入你的 API Key

# 运行
python main.py                    # 完整分析
python main.py --market-review    # 仅大盘复盘
python main.py --schedule         # 定时任务模式
```

### 方式三：Docker 部署

```bash
# 配置环境变量
cp .env.example .env
vim .env

# 一键启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 📱 推送效果

### 决策仪表盘
```
📊 2026-01-10 决策仪表盘
3只股票 | 🟢买入:1 🟡观望:2 🔴卖出:0

🟢 买入 | 贵州茅台(600519)
📌 缩量回踩MA5支撑，乖离率1.2%处于最佳买点
💰 狙击: 买入1800 | 止损1750 | 目标1900
✅多头排列 ✅乖离安全 ✅量能配合

🟡 观望 | 宁德时代(300750)
📌 乖离率7.8%超过5%警戒线，严禁追高
⚠️ 等待回调至MA5附近再考虑

---
生成时间: 18:00
```

### 大盘复盘

![大盘复盘推送效果](./sources/dapan_2026-01-13_22-14-52.png)

```
🎯 2026-01-10 大盘复盘

📊 主要指数
- 上证指数: 3250.12 (🟢+0.85%)
- 深证成指: 10521.36 (🟢+1.02%)
- 创业板指: 2156.78 (🟢+1.35%)

📈 市场概况
上涨: 3920 | 下跌: 1349 | 涨停: 155 | 跌停: 3

🔥 板块表现
领涨: 互联网服务、文化传媒、小金属
领跌: 保险、航空机场、光伏设备
```

## ⚙️ 配置说明

### 环境变量

```bash
# === 必填 ===
GEMINI_API_KEY=your_gemini_key          # Gemini AI
WECHAT_WEBHOOK_URL=https://qyapi...     # 企业微信机器人
STOCK_LIST=600519,300750,002594         # 自选股列表

# === 推荐 ===
TAVILY_API_KEYS=your_tavily_key         # 新闻搜索
GEMINI_MODEL=gemini-3-flash-preview     # 主模型
GEMINI_MODEL_FALLBACK=gemini-2.5-flash  # 备选模型

# === 可选 ===
TUSHARE_TOKEN=your_token                # Tushare数据源
SERPAPI_API_KEYS=your_serpapi_key       # 备用搜索
```

### 定时配置（GitHub Actions）

编辑 `.github/workflows/daily_analysis.yml`:

```yaml
schedule:
  # UTC 时间，北京时间 = UTC + 8
  - cron: '0 10 * * 1-5'   # 周一到周五 18:00（北京时间）
```

| 北京时间 | UTC cron |
|---------|----------|
| 09:30 | `'30 1 * * 1-5'` |
| 15:00 | `'0 7 * * 1-5'` |
| 18:00 | `'0 10 * * 1-5'` |

## 📁 项目结构

```
daily_stock_analysis/
├── main.py              # 主程序入口
├── analyzer.py          # AI 分析器（Gemini）
├── market_analyzer.py   # 大盘复盘分析
├── search_service.py    # 新闻搜索服务
├── notification.py      # 消息推送
├── scheduler.py         # 定时任务
├── storage.py           # 数据存储
├── config.py            # 配置管理
├── data_provider/       # 数据源适配器
│   ├── akshare_fetcher.py
│   ├── tushare_fetcher.py
│   ├── baostock_fetcher.py
│   └── yfinance_fetcher.py
├── .github/workflows/   # GitHub Actions
├── Dockerfile           # Docker 镜像
└── docker-compose.yml   # Docker 编排
```

## 🗺️ Roadmap

> 📢 以下功能将视后续情况逐步完成，如果你有好的想法或建议，欢迎 [提交 Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues) 讨论！

### 🔔 通知渠道扩展
- [x] 企业微信机器人
- [x] 飞书机器人
- [x] Telegram Bot
- [x] 邮件通知（SMTP）
- [x] 自定义 Webhook（支持钉钉、Discord、Slack、Bark 等）
- [ ] iOS/Android 推送（Pushover）

### 🤖 AI 模型支持
- [x] Google Gemini（主力，免费额度）
- [x] OpenAI 兼容 API（支持以下模型）
  - [x] OpenAI GPT-4/4o
  - [x] DeepSeek
  - [x] 通义千问
  - [x] Moonshot（月之暗面）
  - [x] 智谱 GLM
- [ ] Claude
- [ ] 文心一言
- [x] 本地模型（Ollama）

### 📊 数据源扩展
- [x] AkShare（免费）
- [x] Tushare Pro
- [x] Baostock
- [x] YFinance
- [ ] 东方财富 API
- [ ] 同花顺 API
- [ ] 新浪财经

### 🎯 功能增强
- [x] 决策仪表盘
- [x] 大盘复盘
- [x] 定时推送
- [x] GitHub Actions
- [ ] Web 管理界面
- [ ] 自选股动态管理 API
- [ ] 历史分析回测
- [ ] 多策略支持
- [ ] 港股/美股支持

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

详见 [贡献指南](CONTRIBUTING.md)

## 📄 License

[MIT License](LICENSE) © 2026 ZhuLinsen

## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。作者不对使用本项目产生的任何损失负责。

---

**如果觉得有用，请给个 ⭐ Star 支持一下！**
