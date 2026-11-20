# English Documentation Index

> [!TIP]
> **New users:** Start with the [3-Minute Quickstart (ZH)](QUICKSTART.md) or [README (EN)](README_EN.md). You only need **1 AI API Key** and a watchlist (`STOCK_LIST`) — free market data sources work out of the box.

> For Chinese documentation, see [docs/INDEX.md](INDEX.md).

---

## 🚀 Step 1: 3-Minute Quickstart

| Goal | Start with | Notes |
| --- | --- | --- |
| Understand DSA in 2 minutes | [README (EN)](README_EN.md) | Project overview, features, sample outputs |
| Desktop client beginner walkthrough | [Beginner Client Setup](beginner-client-setup.md) (Chinese-only) | Installer download, API key setup, FAQ |
| Troubleshooting & diagnostics | [FAQ (EN)](FAQ_EN.md) | Common configuration, data-source & runtime FAQs |

---

## ⚙️ Step 2: Configuration & Deployment

| Goal | Start with | Then read |
| --- | --- | --- |
| Configure AI model providers | [LLM Config Guide (EN)](LLM_CONFIG_GUIDE_EN.md) | [Provider Configuration Guide](llm-providers.md) (Chinese-only) |
| Configure push notifications | [Notification Baseline](notifications.md) (Chinese-only) | [Full Guide (EN)](full-guide_EN.md) |
| Deploy to server / Docker / cloud | [Deploy Guide (EN)](DEPLOY_EN.md) | [Cloud WebUI](deploy-webui-cloud.md) · [Zeabur](docker/zeabur-deployment.md) (Chinese-only) |
| Market support & data sources | [Market Support And Boundaries](market-support.md) (Chinese-only) | [Data-source stability diagrams](data-source-stability.md) · [Data Center](data-center-diagnostics.md) |
| Specific data / macro adapters | [FXMacroData Integration](FXMACRODATA_EN.md) | [TickPlus Integration](tickplus.md) · [Tushare Stock List Guide](TUSHARE_STOCK_LIST_GUIDE.md) |

---

## 📈 Step 3: Portfolio, Screening, Bots & Verifiable Arena

| Topic | Document | Contents |
| --- | --- | --- |
| **Portfolio & Watchlist Signals** | [Portfolio Risk & Exposure](portfolio-risk-exposure-dashboard.md) · [Watchlist Next Action](watchlist-next-action.md) (Chinese-only) | Concentration/correlation stress-test and home watchlist status signals |
| **Screening & ETF Rotation** | [Screening Engine](screening-engine.md) · [ETF Rotation](etf-rotation.md) (Chinese-only) | Multi-factor/NL screening & rule-based `--etf-rotation` |
| **AI Signals & Real-Time Alerts** | [DecisionSignal Topic](decision-signals.md) · [Real-Time Alert Center](alerts.md) (Chinese-only) | AI recommendations, price/thesis watch triggers, notification attempts |
| **Bot / IM Integrations** | [Bot Commands (EN)](bot-command_EN.md) | [Bot Platform Docs](bot/) · [Grok Bot Integration](grok-bot-integration.md) · [OpenClaw Integration](openclaw-skill-integration.md) · [Grok Bot Skill](examples/grok_bot/README.md) |
| **Full Reference & Packaging** | [Full Guide (EN)](full-guide_EN.md) | [Share Images](share-images.md) · [Intelligence Sources](intelligence-sources.md) · [Desktop Packaging](desktop-package.md) · [Web Settings Help](settings-help.md) |

---

## 🛠️ Developer Reference & Internal Contracts

<details>
<summary>Expand developer specs, P0–P7 internal contracts, OpenAPI spec & changelog</summary>

| Document | Contents |
| --- | --- |
| [Contributing Guide (EN)](CONTRIBUTING_EN.md) | Issues, pull requests, tests, and collaboration expectations |
| [API Spec](architecture/api_spec.json) | FastAPI OpenAPI artifact |
| [Changelog](CHANGELOG.md) | Release notes and migration notes |
| [LiteLLM YAML Example](examples/litellm_config.example.yaml) | Multi-provider LiteLLM config template |
| [Stock Profile API](stock-profile-api.md) (Chinese-only) | Single stock-profile contract and quality states |
| [ResearchArtifact Contract](research-artifact.md) (Chinese-only) | Structured thesis, evidence, and invalidation boundaries |
| [Screening Explanation Contract](screening-explanations.md) (Chinese-only) | Deterministic Why Selected / Why Now provenance |
| [Analysis Context Pack](analysis-context-pack.md) (Chinese-only) | P1–P6 internal context contracts, quality scoring, rollback anchors |
| [Agent Stream Events & Trajectory Eval](agent-stream-events.md) (Chinese-only) | [Multi-Strategy Contract](multi-strategy-contract.md) · [Trajectory Eval](agent-trajectory-eval.md) |
| [Run Diagnostics Specs](run-diagnostics-p0.md) (Chinese-only) | [P0](run-diagnostics-p0.md) · [P1](run-diagnostics-p1.md) · [P2](run-diagnostics-p2.md) · [P3](run-diagnostics-p3.md) |
| [Web Settings Draft Protection](settings-draft-protection.md) (Chinese-only) | Unsaved settings draft guard mechanics |
| [Image Extraction Prompt](image-extract-prompt.md) (Chinese-only) | Vision prompt for portfolio/watchlist screenshot extraction |

</details>

---

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
