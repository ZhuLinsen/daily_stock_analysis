<div align="center">

# 📈 股票智能分析系统 (DSA)

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![arXiv](https://img.shields.io/badge/arXiv-2608.26990-b31b1b.svg)](https://arxiv.org/abs/2608.26990)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

<p align="center">
  <a href="https://trendshift.io/repositories/18527?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-18527" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/18527" alt="ZhuLinsen%2Fdaily_stock_analysis | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://www.star-history.com/zhulinsen/daily_stock_analysis">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=ZhuLinsen/daily_stock_analysis&amp;type=rank&amp;theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=ZhuLinsen/daily_stock_analysis&amp;type=rank" />
      <img alt="Star History Rank" src="https://api.star-history.com/badge?repo=ZhuLinsen/daily_stock_analysis&amp;type=rank" height="55" />
    </picture>
  </a>
</p>

> 🤖 覆盖 **A股 / 港股 / 美股 / 日股 / 韩股 / 台股** 的全链路 AI 投研工作台：集多源行情聚合、技术/情报分析、Agent 策略问股、决策信号回测验证、持仓风控与多渠道推送于一体

[**产品预览**](#-产品预览) · [**功能特性**](#-功能特性) · [**快速开始**](#-快速开始) · [**推送效果**](#-推送效果) · [**文档中心**](docs/INDEX.md) · [**完整指南**](docs/full-guide.md)

**[下载桌面客户端](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [5 分钟 GitHub Actions](#方式一github-actions推荐) · [Docker / 本地 WebUI](#方式二客户端配置教程--本地运行--docker-部署)**

简体中文 | [English](docs/README_EN.md) | [繁體中文](docs/README_CHT.md)

</div>

<details open>
<summary><strong>💖 赞助商 (Sponsors)</strong></summary>
<table>
  <tr><td align="center"><a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis"><img src="./docs/assets/modelflare_banner_zh.png" alt="Modelflare" width="720"></a><br>感谢 <strong>Modelflare</strong> 赞助本项目！由美国 Havenbyte LLC 运营，满血稳定不掺水，低成本接入 GPT、Claude、Gemini、Grok 及 40+ 图片/视频模型，支持大陆正规商务合作。指定 OpenAI 分组提供 <strong>65% / 75% / 85% 每日缓存命中率保障</strong>；单笔充值 <strong>US$20 解锁 GPT 0.015x</strong>，<strong>US$50 解锁 Claude 0.03x</strong>。<a href="https://modelflare.dev/sign-up?utm_source=github&amp;utm_campaign=daily_stock_analysis">专属链接注册</a></td></tr>
  <tr><td align="center"><a href="https://console.x6pro.io/register?code=zJ2qSdns"><img src="./docs/assets/x6ai_banner.png" alt="x6.ai" width="720" height="187"></a><br>100+ 模型 $5 包月，Claude 1.9 折、GPT 0.9 折、DeepSeek 5.8 折，首充立减 20%。<a href="https://console.x6pro.io/register?code=zJ2qSdns">专属链接注册</a></td></tr>
  <tr><td align="center"><a href="https://serpapi.com/github-daily-stock-analysis" target="_blank"><img src="./docs/assets/serpapi_banner_zh.png" alt="轻松抓取搜索引擎上的实时金融新闻数据 - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a></td></tr>
</table>
</details>

## 💻 产品预览

<p align="center">
  <a href="docs/assets/readme_workspace_tour_20260510.gif"><img src="docs/assets/readme_workspace_preview.gif" alt="DSA Web 工作台演示" width="640"></a><br>
  <sub>点击动图查看完整工作台演示（涵盖个股分析、智能选股、决策信号、持仓风控、回测与 Agent 问股）</sub>
</p>

> [!TIP]
> 🚀 **作者配套开源项目**：[AlphaSift · 智能选股](https://github.com/ZhuLinsen/alphasift) ｜ [AlphaEvo · 策略回测与进化](https://github.com/ZhuLinsen/alphaevo)

## ✨ 功能特性

| 阶段 | 核心能力与 Web 工作台模块 | 专题文档 |
|------|------|------|
| **发现** | 多因子与自然语言智能选股（`/screening`）、市场热点雷达、规则化 ETF 双动量轮动（`--etf-rotation`） | [选股引擎](docs/screening-engine.md) · [ETF 轮动](docs/etf-rotation.md) |
| **分析** | 6 市场「决策仪表盘」报告（`/`）、大盘复盘、15 种内置策略的多轮 Agent 策略问股（`/chat`） | [完整指南](docs/full-guide.md) · [市场边界](docs/market-support.md) |
| **验证** | 决策信号池（`/decision-signals`）、历史胜率与方向回测（`/backtest`）、运行诊断可观测与数据源健康体检 | [决策信号](docs/decision-signals.md) · [数据中心](docs/data-center-diagnostics.md) |
| **跟踪** | 持仓账本与风险暴露看板（`/portfolio`、富途同步）、实时异动告警（`/alerts`）、Token 统计（`/usage`） | [组合风控](docs/portfolio-risk-exposure-dashboard.md) · [告警中心](docs/alerts.md) |
| **触达** | GitHub Actions 零服务器定时任务、Electron 桌面端、企业微信 / 飞书 / Telegram / Discord / Slack / 邮件推送 | [通知配置](docs/notifications.md) · [Bot 接入](docs/bot-command.md) |

### 技术栈与数据来源

| 类型 | 支持 |
|------|------|
| **AI 模型** | [Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis)、[x6.ai](https://console.x6pro.io/register?code=zJ2qSdns)、AIHubMix、Gemini、OpenAI 兼容、DeepSeek、通义千问、Claude、Ollama 本地模型等 |
| **行情数据** | [TickPlus（推荐）](http://www.tickplus.org/register?reg=5433cf922395)、AkShare、Tushare、Pytdx、Baostock、YFinance、Longbridge（内置免费源零配置可跑，批量/稳定建议配合 Token 源） |
| **新闻与舆情** | [SerpAPI](https://serpapi.com/github-daily-stock-analysis)、Anspire、Tavily、Bocha、Brave、MiniMax、SearXNG；美股可选 Stock Sentiment API（Reddit / X / Polymarket） |

## 🚀 快速开始

| 上手方式 | 适合人群 | 所需前置 | 入口 |
|------|------|------|------|
| **桌面客户端** | 不想折腾命令行的个人投资者 | 1 个 AI API Key | [Releases 下载](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [小白教程](docs/beginner-client-setup.md) |
| **GitHub Actions** | 零服务器每日自动分析（推荐） | **仅 1 个 AI 模型 Secret** | [下方 4 步配置](#方式一github-actions推荐) |
| **Docker / 本地 WebUI** | 私有部署、持仓管理与 Agent 问股 | Docker 或 Python 3.10+ | [下方部署命令](#方式二客户端配置教程--本地运行--docker-部署) · [部署指南](docs/DEPLOY.md) |

### 方式一：[GitHub Actions（推荐）](https://www.bilibili.com/video/BV11FEb66EXG/)

> 5 分钟部署，无需自备服务器（AI 模型调用费用由你选择的 API 渠道计费）；首次跑通**只需配置 1 个 AI 模型 Secret**，`STOCK_LIST` 默认兜底 `600519`，通知渠道可选。

1. **Fork 本仓库**：点击右上角 `Fork`（顺便点个 Star ⭐ 支持一下）。
2. **配置至少 1 个 AI 模型 Secret**（`Settings` → `Secrets and variables` → `Actions` → `New repository secret`）：
   - **单 Secret 推荐**：`MODELFLARE_KEY`（[Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis)，自动补齐默认地址与模型）、`AIHUBMIX_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY` 或官方 `OPENAI_API_KEY`
   - **多变量渠道 / 兼容接入**：使用 [x6.ai](https://console.x6pro.io/register?code=zJ2qSdns) 需配置 `LLM_CHANNELS=x6ai`、`LLM_X6AI_BASE_URL`、`LLM_X6AI_API_KEY` 与 `LLM_X6AI_MODELS`（见 [x6.ai 渠道示例](docs/llm-providers.md#x6ai-聚合平台)）；使用 OpenAI 兼容 DeepSeek/通义千问需同时配置 `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `OPENAI_MODEL`
   - **可选增强**：`STOCK_LIST`（如 `600519,hk00700,AAPL,7203.T,005930.KS,2330.TW`，规则见 [指数自选股配置](docs/full-guide.md#指数自选股配置)）、`SERPAPI_API_KEYS`（新闻补强）、`TICKPLUS_API_KEY` / `TUSHARE_TOKEN` / `LONGBRIDGE_OAUTH_CLIENT_ID`（稳定行情）、通知渠道（`WECHAT_WEBHOOK_URL` / `FEISHU_WEBHOOK_URL` / `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID` / `DISCORD_WEBHOOK_URL` / `SLACK_BOT_TOKEN`+`SLACK_CHANNEL_ID` / `EMAIL_SENDER`+`EMAIL_PASSWORD`，详见 [完整指南](docs/full-guide.md)）。
3. **启用 Actions**：进入 Fork 仓库的 `Actions` 标签 → 点击 `I understand my workflows, go ahead and enable them`。
4. **手动测试与查看结果**：`Actions` → `每日股票分析` → `Run workflow`，运行结束后可在推送通知渠道查看结果或下载 `analysis-reports-*` Artifact；之后每个工作日 **18:00（北京时间）** 自动执行（非交易日跳过及断点续传规则见 [定时任务配置](docs/full-guide.md#定时任务配置)）。

### 方式二：[客户端配置教程](https://www.bilibili.com/video/BV11FEb66Eyr/) / 本地运行 / Docker 部署

```bash
# 1. 浅克隆项目（跳过历史提交，下载更快）
git clone --depth 1 https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis

# 2. 安装依赖并启动 Web 工作台（推荐直接在网页设置页配置模型、自选股与通知）
pip install -r requirements.txt
python main.py --webui-only
```

启动后访问 `http://127.0.0.1:8000`（支持图片/CSV/剪贴板智能导入与 `/chat` Agent 问股）。如使用 `.env` 命令行模式：

```bash
cp .env.example .env && vim .env
python main.py                              # 全量分析（个股 + 大盘复盘）
python main.py --stocks 600519,hk00700,AAPL # 一次性分析指定标的
python main.py --market-review              # 仅运行大盘复盘
python main.py --schedule                   # 本地定时调度
python main.py --serve-only                 # 仅启动 FastAPI + WebUI 服务
```

> Docker 部署、云服务器访问与 `--etf-rotation` 请看 [完整配置与部署指南](docs/full-guide.md)；桌面端打包请看 [桌面端打包说明](docs/desktop-package.md)；多模型路由与 Agent 参数请看 [LLM 配置指南](docs/LLM_CONFIG_GUIDE.md)。

## 📱 推送效果

<details>
<summary>点击展开推送示例（决策仪表盘 &amp; 大盘复盘）</summary>

```markdown
🎯 2026-02-08 决策仪表盘
共分析3只股票 | 🟢买入:0 🟡观望:2 🔴卖出:1

📊 分析结果摘要
🟡 中钨高新(000657): 观望 | 评分 65 | 看多
🟡 永鼎股份(600105): 观望 | 评分 48 | 震荡
🔴 新莱应材(300260): 卖出 | 评分 35 | 看空

🚨 风险警报:
- 主力资金大幅净卖出，需警惕短期抛压；筹码偏分散，拉升阻力较大。
✨ 利好催化:
- 受益于 AI 服务器产业链，业绩同比高增长提供基本面支撑。

🎯 2026-01-10 大盘复盘
📊 主要指数: 上证指数 3250.12 (🟢+0.85%) | 深证成指 10521.36 (🟢+1.02%) | 创业板指 2156.78 (🟢+1.35%)
📈 市场概况: 上涨 3920 | 下跌 1349 | 涨停 155 | 跌停 3
```

</details>

## 🛠️ 排障与保持更新

- **Fork 保持更新**：定期在 GitHub 点击 `Sync fork` 同步数据源与模型修复；通过 Secrets/Variables 配参数，避免改动 workflow 引发冲突。
- **60 天定时停用**：GitHub 会在仓库 **60 天无仓库活动** 后自动暂停 `schedule` 定时任务，可在 `Actions` 页重新启用或定期 `Sync fork`，详见 [FAQ](docs/FAQ.md)。

## 📬 联系与合作

<table>
  <tr>
    <td width="92" valign="top"><strong>合作邮箱</strong></td>
    <td valign="top"><a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a>（项目咨询、部署支持与功能扩展）</td>
    <td align="center" rowspan="3" valign="middle" width="148">
      <a href="http://xhslink.com/m/tU520DWCKT" target="_blank"><img src="./docs/assets/xiaohongshu_tick.jpg" width="112" alt="小红书二维码"></a><br>
      <sub>扫码关注小红书</sub>
    </td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>小红书</strong></td>
    <td valign="top"><a href="http://xhslink.com/m/tU520DWCKT">欢迎关注小红书</a></td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>问题反馈</strong></td>
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">提交 Issue</a> · <a href="docs/INDEX.md">文档中心</a></td>
  </tr>
</table>

## 📄 License & ⚠️ 免责声明

[MIT License](LICENSE) © 2026 ZhuLinsen — 欢迎在二次开发或引用时注明本仓库来源。本项目仅供学习和研究使用，不构成任何投资建议；股市有风险，投资需谨慎。
