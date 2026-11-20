# English Documentation Index

> [!TIP]
> Pick a setup in the [3-minute quickstart (Chinese)](QUICKSTART.md) or follow the [English quickstart](README_EN.md#-quick-start).

> For Chinese documentation, see [docs/INDEX.md](INDEX.md).

---

<a name="choose-by-goal"></a>

## Getting Started

| Goal | Start with | Notes |
| --- | --- | --- |
| Run your first analysis | [Quickstart (Chinese)](QUICKSTART.md) · [Quickstart (English)](README_EN.md#-quick-start) | Choose desktop, GitHub Actions, local, or Docker setup |
| Explore DSA | [README (EN)](README_EN.md) | Project overview, features, sample outputs |
| Desktop client beginner walkthrough | [Beginner Client Setup](beginner-client-setup.md) (Chinese-only) | Installer download, API key setup, FAQ |
| Troubleshooting & diagnostics | [FAQ (EN)](FAQ_EN.md) | Common configuration, data-source & runtime FAQs |

---

<a name="configuration"></a>

## Daily Runs and Notifications

| Goal | Start with | Then read |
| --- | --- | --- |
| Configure AI model providers | [LLM Config Guide (EN)](LLM_CONFIG_GUIDE_EN.md) | [Provider Configuration Guide (Chinese)](llm-providers.md) · [LiteLLM YAML Example](examples/litellm_config.example.yaml) |
| Configure push notifications | [Notification Baseline](notifications.md) (Chinese-only) | [Full Guide (EN)](full-guide_EN.md) |
| Schedule analyses | [GitHub Actions Configuration](full-guide_EN.md#github-actions-configuration) | [Scheduled Tasks](full-guide_EN.md#scheduled-task-configuration) |
| Market support & data sources | [Market Support And Boundaries](market-support.md) (Chinese-only) | [Data-source stability diagrams](data-source-stability.md) · [Data Center](data-center-diagnostics.md) |
| Specific data / macro adapters | [FXMacroData Integration](FXMACRODATA_EN.md) | [TickPlus Integration](tickplus.md) · [Tushare Stock List Guide](TUSHARE_STOCK_LIST_GUIDE.md) |

---

<a name="usage-topics"></a>

## Advanced Research

| Topic | Document | Contents |
| --- | --- | --- |
| **Portfolio & Watchlist Signals** | [Portfolio Risk & Exposure](portfolio-risk-exposure-dashboard.md) · [Watchlist Next Action](watchlist-next-action.md) (Chinese-only) | Portfolio risk, market and currency exposure, and watchlist signals |
| **Screening & ETF Rotation** | [Screening Engine](screening-engine.md) · [ETF Rotation](etf-rotation.md) (Chinese-only) | Multi-factor/NL screening & rule-based `--etf-rotation` |
| **AI Signals & Real-Time Alerts** | [DecisionSignal Topic](decision-signals.md) · [Real-Time Alert Center](alerts.md) (Chinese-only) | AI recommendations, price/thesis watch triggers, notification attempts |
| **News & Report Sharing** | [Intelligence Sources](intelligence-sources.md) · [Share Images](share-images.md) (Chinese-only) | News feeds, reports, and share images |

---

<a name="deployment-and-packaging"></a>

## Deployment and Operations

- [Full Guide (EN)](full-guide_EN.md)
- [Deploy Guide (EN)](DEPLOY_EN.md) · [Cloud WebUI](deploy-webui-cloud.md) (Chinese) · [Zeabur](docker/zeabur-deployment.md) (Chinese)
- [Desktop Packaging](desktop-package.md) (Chinese)

---

<a name="reference-and-development"></a>

## Integrations and Reference

- [Bot Commands (EN)](bot-command_EN.md) · [Bot Platform Docs](bot/) (Chinese)
- [Grok Bot Integration](grok-bot-integration.md) · [Grok Bot Skill](examples/grok_bot/README.md) · [OpenClaw Integration](openclaw-skill-integration.md) (Chinese)

<details>
<summary>Expand P0–P7 internal contracts, the API spec, and the contributing guide</summary>

| Document | Contents |
| --- | --- |
| [Contributing Guide (EN)](CONTRIBUTING_EN.md) | Issues, pull requests, tests, and collaboration expectations |
| [API Spec](architecture/api_spec.json) | FastAPI OpenAPI artifact |
| [Stock Profile API](stock-profile-api.md) (Chinese-only) | Single stock-profile contract and quality states |
| [ResearchArtifact Contract](research-artifact.md) (Chinese-only) | Structured thesis, evidence, and invalidation boundaries |
| [Screening Explanation Contract](screening-explanations.md) (Chinese-only) | Deterministic Why Selected / Why Now provenance |
| [Analysis Context Pack Contract, Runtime Consumption, And Visibility](analysis-context-pack.md) <sub><sub>![P6 Badge](https://img.shields.io/badge/P6-orange?style=flat)</sub></sub> (Chinese-only) | P1/P2 internal contracts, P3 prompt-summary consumption, P4 history/API/Web low-sensitivity visibility, P5 data-quality scoring, and P6 migration/rollback notes. Also covers #1386 market-phase analysis, migration, and rollback entry points |
| [Agent Stream Events & Trajectory Eval](agent-stream-events.md) (Chinese-only) | [Multi-Strategy Contract](multi-strategy-contract.md) · [Trajectory Eval](agent-trajectory-eval.md) |
| [Run Diagnostics Specs](run-diagnostics-p0.md) (Chinese-only) | [P0](run-diagnostics-p0.md) · [P1](run-diagnostics-p1.md) · [P2](run-diagnostics-p2.md) · [P3](run-diagnostics-p3.md) |
| [Web Settings Draft Protection](settings-draft-protection.md) (Chinese-only) | Draft protection and [settings help maintenance](settings-help.md) |
| [Image Extraction Prompt](image-extract-prompt.md) (Chinese-only) | Vision prompt for portfolio/watchlist screenshot extraction |

</details>

[Changelog](CHANGELOG.md)

---

<a name="languages"></a>

## 🌐 Languages

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
