# English Documentation Index

> All English-language documentation for the AI Stock Analysis System.
> 
> For Chinese docs, see the [main README](../README.md).

---

## 🚀 Getting Started

| Document | Description |
|----------|-------------|
| [README (EN)](README_EN.md) | Project overview, quick start, features, sample output |
| [Full Guide (EN)](full-guide_EN.md) | Complete setup and usage walkthrough |
| [Deploy Guide (EN)](DEPLOY_EN.md) | Server deployment (Docker, systemd, Supervisor) |
| [LLM Config Guide (EN)](LLM_CONFIG_GUIDE_EN.md) | AI model configuration (Gemini, OpenAI-compatible, DeepSeek, Ollama, etc.) |

## ❓ Help & Troubleshooting

| Document | Description |
|----------|-------------|
| [FAQ (EN)](FAQ_EN.md) | Frequently asked questions and common errors |

## 🤖 Bot Integration

| Document | Description |
|----------|-------------|
| [Bot Commands (EN)](bot-command_EN.md) | Bot architecture, commands, webhook routes, Feishu / DingTalk integration |

## 🤝 Contributing

| Document | Description |
|----------|-------------|
| [Contributing Guide (EN)](CONTRIBUTING_EN.md) | How to report bugs, request features, and submit pull requests |

## 📋 Reference

| Document | Description |
|----------|-------------|
| [Changelog](CHANGELOG.md) | Version history and release notes (maintained in Chinese with English summaries) |

---

## Glossary of China-market Terms

Some terms in this project are specific to Chinese financial markets. Here is a quick reference:

| Term | Meaning |
|------|---------|
| **A-shares** | Stocks listed on the Shanghai (SSE) or Shenzhen (SZSE) stock exchanges, denominated in CNY |
| **Northbound capital flow** (北向资金) | Net buy/sell flow from foreign investors via the Stock Connect programs (Shanghai/Shenzhen–Hong Kong Connect) |
| **Dragon-Tiger List** (龙虎榜) | Daily SSE/SZSE disclosure of the top 5 institutional seats by turnover for heavily traded stocks |
| **Chip distribution** (筹码分布) | Cost-basis distribution of all outstanding shares, used to estimate support/resistance levels |
| **三板块涨跌榜** (boards / sectors) | Intraday sector rotation ranking published by SSE/SZSE |
| **Tushare** | A popular Chinese financial data API; requires a token (free tier available) |
| **AkShare** | An open-source Python library for Chinese/HK/US market data; no key required for most endpoints |
| **Baostock** | A free Python SDK for historical A-share data |
| **WeChat Work** (企业微信) | Tencent's enterprise messaging platform; supports webhook-based notifications |
| **Feishu** (飞书) | ByteDance's enterprise collaboration platform (similar to Slack); also supports webhooks |
| **PushPlus / ServerChan** | Chinese mobile push notification services |

---

*Last updated: see [CHANGELOG.md](CHANGELOG.md)*
