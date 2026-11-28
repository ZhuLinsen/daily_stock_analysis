# Beginner Desktop Client Installation & Setup Guide

This guide is written for non-technical users who want to download the desktop app and start right away. The goal is simple: download the desktop client, add one AI model API key, enter your stock codes, and generate your first analysis report.

> Reports produced by this project are decision-support aids and do not constitute investment advice. Always exercise independent judgment in real trading.

## Prerequisites

1. A Windows or macOS computer.
2. One AI model API key from your preferred provider:
   - [Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis) / [x6.ai](https://console.x6pro.io/register?code=zJ2qSdns): aggregator platforms suited for switching among major global models from one account.
   - DeepSeek, Gemini, OpenAI, Anthropic, AIHubMix, or Anspire Open are also supported—pick whichever fits your needs.
3. The stock codes you want to analyze, such as `600519,hk00700,AAPL`.

## 1. Download the Desktop Client

Open the releases page:

<https://github.com/ZhuLinsen/daily_stock_analysis/releases/latest>

Under `Assets` at the bottom of the page, download the package matching your system:

| System | Package to Download |
| --- | --- |
| Windows | `daily-stock-analysis-windows-installer-<version>.exe` |
| Windows Portable (no install) | `daily-stock-analysis-windows-noinstall-<version>.zip` |
| macOS Apple Silicon | `daily-stock-analysis-macos-arm64-<version>.dmg` |
| macOS Intel | `daily-stock-analysis-macos-x64-<version>.dmg` |

You do not need `latest.yml` or `*.blockmap`; they are update metadata files, not installers.

If you are unsure which Mac chip you have, click the Apple menu in the top-left corner -> **About This Mac**. Choose `arm64` if you see M1/M2/M3/M4, or `x64` if you see Intel.

## 2. Install & Launch

- **Windows Installer**: Double-click `.exe`, follow the wizard, and keep the default installation folder.
- **Windows Portable**: Extract the `.zip` archive and double-click `Daily Stock Analysis.exe`.
- **macOS**: Double-click `.dmg` and drag the app into `Applications`. Current DMGs are not signed or notarized with an Apple Developer ID, so macOS Gatekeeper may block launch initially. Only allow opening via **Privacy & Security** for official GitHub Releases downloads; see `docs/desktop-package.md` for full details and troubleshooting.

macOS users should export a configuration backup inside Settings before upgrading versions.

## 3. Configure an AI Model

Open the desktop client and go to:

`Settings -> AI Models`

Configure only one of the options below.

> Important: After editing any setting, click **Save** on the page and wait for the save-success toast before switching tabs or returning to Home.

### Option A: Modelflare (or x6.ai and similar aggregators)

1. Register / log in at your chosen platform (such as [Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis) or [x6.ai](https://console.x6pro.io/register?code=zJ2qSdns)) and create an API key.
2. Back in the desktop client, choose the matching preset template in Quick Add Channel (e.g., `Modelflare` or `x6.ai`).
3. Paste your API key.
4. Select an enabled model from your account (or click **Fetch Models**); if unsure, pick a recommended model shown in the platform console.
5. Click **Save**, and once saved successfully, click **Test Connection**.

### Optional Alternatives: AIHubMix / Anspire Open

1. [AIHubMix](https://inferera.com/?aff=CfMq): choose `AIHubmix` in Quick Add Channel, paste your API key, pick an enabled model, save, and test connection.
2. [Anspire Open](https://open.anspire.cn/dsa?share_code=QFBC0FYC): choose `Anspire Open` in Quick Add Channel, paste your API key, pick an enabled model, save, and test connection.

Once the connection test passes, proceed to the next step.

## 4. Add Your Watchlist

Go to:

`Settings -> Basic`

Find **Watchlist (`STOCK_LIST`)** and enter:

`600519,hk00700,AAPL`

Separate multiple tickers with ASCII commas. Common symbol formats:

- A-shares: `600519`, `300750`, `000001`
- Hong Kong: `hk00700`, `hk09988`
- US: `AAPL`, `TSLA`, `NVDA`

Click **Save**, confirm the success prompt, then return to Home.

## 5. Recommended: Configure News Search

A news source is optional, but strongly recommended. It powers recent news, announcements, event catalysts, theme context, and risk alerts.

Go to:

`Settings -> Data Sources`

Pick according to your setup:

1. Standard setups: obtain an API key from [SerpAPI](https://serpapi.com/github-daily-stock-analysis) or [Tavily](https://tavily.com/), paste it into `SerpAPI API Keys` or `Tavily API Keys`, and click **Save**.
2. If you use Anspire: you can also fill `Anspire API Keys` as a search source.

If you just want a quick trial, you can skip news search for now—the client still generates baseline technical and market analysis.

## 6. Start Analyzing

Return to Home:

1. Enter a stock code such as `600519`.
2. Click **Analyze**.
3. Wait while the task moves through queued -> running -> completed.
4. Open the report in History.

## Frequently Asked Questions

### There are many files on the Releases page—which one do I download?

Most Windows users should download the `.exe` installer. Skip `latest.yml` and `*.blockmap`.

### Why doesn't my API key work after entering it?

Check these items:

1. Make sure the full key was copied without extra leading or trailing spaces.
2. Verify your provider account has remaining credit or quota.
3. Confirm the selected model is enabled on your account.
4. Inspect the **Test Connection** error message for invalid model ID, permission denied, or insufficient balance.

### What if my configuration gets messed up?

Export a configuration backup in Settings whenever things work smoothly. If anything breaks later, import your previous backup or reconfigure only the three essentials: AI Model, Watchlist, and News Source.
