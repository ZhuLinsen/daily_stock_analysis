# English Documentation Index

This is the entry point for project documentation. The README covers the project overview and quick start; detailed setup, configuration, deployment, feature usage, and troubleshooting docs are linked below.

> For Chinese documentation, see [docs/INDEX.md](INDEX.md).

## Choose By Goal

| I want to | Start with | Then read |
| --- | --- | --- |
| Understand what the project does | [README (EN)](README_EN.md) | [Full Guide (EN)](full-guide_EN.md) |
| Run the project for the first time | [README (EN)](README_EN.md) | [Full Guide (EN)](full-guide_EN.md) |
| Configure model providers | [LLM Config Guide (EN)](LLM_CONFIG_GUIDE_EN.md) | [Provider Configuration Guide](llm-providers.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) |
| Configure notifications | [Notification Baseline](notifications.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | [Full Guide (EN)](full-guide_EN.md) |
| Deploy to a server or cloud platform | [Deploy Guide (EN)](DEPLOY_EN.md) | [Cloud WebUI Deployment](deploy-webui-cloud.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only), [Zeabur Deployment](docker/zeabur-deployment.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) |
| Use Bot / IM integrations | [Bot Commands (EN)](bot-command_EN.md) | [Bot Platform Docs](bot/) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) |
| Troubleshoot runtime issues | [FAQ (EN)](FAQ_EN.md) | [Changelog](CHANGELOG.md) |
| Contribute code or docs | [Contributing Guide (EN)](CONTRIBUTING_EN.md) | [API Spec](architecture/api_spec.json) |

## Getting Started

| Document | Contents |
| --- | --- |
| [README (EN)](README_EN.md) | Project overview, key features, quick start, sample output |
| [Full Guide (EN)](full-guide_EN.md) | Environment setup, run modes, configuration, deployment paths, and common issues |
| [FAQ (EN)](FAQ_EN.md) | Common configuration, model, notification, deployment, and runtime issues |
| [Changelog](CHANGELOG.md) | Release notes, capability changes, and migration notes |

## Configuration

| Document | Contents |
| --- | --- |
| [LLM Config Guide (EN)](LLM_CONFIG_GUIDE_EN.md) | Model providers, three-tier configuration, Web settings, and common model setup |
| [Provider Configuration Guide](llm-providers.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Provider presets, GitHub Actions mapping, error categories, and diagnostics |
| [LiteLLM YAML Example](examples/litellm_config.example.yaml) | Example LiteLLM multi-provider configuration |
| [Notification Baseline](notifications.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | WeChat Work, Feishu, Telegram, Discord, Slack, Email, and other notification channels |
| [Tushare Stock List Guide](TUSHARE_STOCK_LIST_GUIDE.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Tushare stock-list configuration and usage notes |

## Usage Topics

| Document | Contents |
| --- | --- |
| [Bot Commands (EN)](bot-command_EN.md) | Bot commands, webhooks, platform integration, and callback behavior |
| [Bot Platform Docs](bot/) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Feishu, DingTalk, Discord, and related Bot configuration screenshots and notes |
| [Image Extraction Prompt](image-extract-prompt.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Prompt and boundaries for extracting stock information from images |
| [OpenClaw Skill Integration](openclaw-skill-integration.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | OpenClaw / Skill external integration notes |

## Deployment And Packaging

| Document | Contents |
| --- | --- |
| [Deploy Guide (EN)](DEPLOY_EN.md) | Server deployment, Docker, systemd, Supervisor, and related options |
| [Cloud WebUI Deployment](deploy-webui-cloud.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Cloud server WebUI access and deployment notes |
| [Zeabur Deployment](docker/zeabur-deployment.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Zeabur platform deployment |
| [Desktop Packaging](desktop-package.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Electron desktop app and Web artifact packaging |

## Reference And Development

| Document | Contents |
| --- | --- |
| [API Spec](architecture/api_spec.json) | FastAPI OpenAPI artifact |
| [Contributing Guide (EN)](CONTRIBUTING_EN.md) | Issues, pull requests, tests, documentation sync, and collaboration expectations |

## Languages

| Document | Contents |
| --- | --- |
| [Chinese Documentation Index](INDEX.md) | Chinese documentation entry point |
| [Traditional Chinese README](README_CHT.md) | Traditional Chinese project overview and quick start |

## China-Market Glossary

| Term | Meaning |
| --- | --- |
| **A-shares** | Stocks listed on the Shanghai or Shenzhen stock exchanges, denominated in CNY |
| **Northbound capital flow** | Net buy/sell flow from foreign investors through Stock Connect programs |
| **Dragon-Tiger List** | Daily SSE/SZSE disclosure of heavily traded stocks and top trading seats |
| **Chip distribution** | Cost-basis distribution of outstanding shares, often used to estimate support and resistance |
| **Tushare** | Chinese financial data API that requires a token |
| **AkShare** | Open-source Python market data library |
| **Baostock** | Free Python SDK for historical A-share data |
| **WeChat Work** | Tencent enterprise messaging platform with webhook notifications |
| **Feishu** | ByteDance enterprise collaboration platform with webhook notifications |
| **PushPlus / ServerChan** | Chinese mobile push notification services |
