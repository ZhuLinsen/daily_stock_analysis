<!-- i18n-source: README.md | synced-commit: 38023206 | synced-date: 2026-11-28 -->
<div align="center">

# 📈 AI 株式分析システム (Daily Stock Analysis)

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

**日本株（`.T`）・米国株・香港株・A株・韓国株・台湾株に対応した LLM ベースの自動株式分析＆通知システム**

ウォッチリストを毎日自動分析 → 売買判断ダッシュボードを生成 → Telegram / Discord / Slack / Email / 飛書 / 企業微信へ配信

日本語 | [English](README_EN.md) | [简体中文](../README.md) | [繁體中文](README_CHT.md) | [한국어](README_KO.md)

</div>

> [!NOTE]
> **対応言語・データ範囲について（導入前にご確認ください）**
> - **Web UI・AI レポート出力**：現在 **English / 中文**（および韓国語レポート）に対応しています。日本語レポート（`REPORT_LANGUAGE=ja`）は未対応のため、設定時は **`REPORT_LANGUAGE=en`** の指定を推奨します。
> - **日本株（例: `7203.T`, `9984.T`）**：Yahoo Finance ベースで株価・日足 K 線・市場概況（`^N225` / `^TOPX`）に対応します。市場別のデータ範囲・制限事項は [Multi-Market Support & Boundaries](./market-support_EN.md) をご覧ください。
> - **最新ドキュメント正本**：本ページは日本語向けクイック入口です。最新の詳細仕様は [English Docs](./INDEX_EN.md) / [Official Docs Site (EN)](https://dsa.zhulinsen.tech/en/) / [简体中文 README](../README.md) をご参照ください。

## 🖥️ 画面プレビュー

<p align="center">
  <a href="assets/readme_workspace_tour_20260510.gif"><img src="assets/readme_workspace_preview.gif" alt="DSA Web workspace demo" width="640"></a><br>
  <sub>クリックしてフルデモを表示</sub>
</p>

## ✨ 主な機能

| 機能 | 概要 |
|---|---|
| **AI 意思決定レポート** | 総合判断・スコア・トレンド・エントリー/損切り/利確目安・リスク警告・カタリスト・チェックリストを自動生成 |
| **マルチマーケット対応** | 日本株（`7203.T` 等）、米国株（`AAPL`）、香港株（`hk00700`）、A株（`600519`）、韓国株（`005930.KS`）、台湾株（`2330.TW`）、ETF に対応 |
| **Web / デスクトップ UI** | 手動分析、進捗監視、履歴閲覧、バックテスト、ポートフォリオ管理、アラート設定、ダーク/ライトテーマ |
| **Agent 戦略チャット** | 20 種のビルトイン戦略＋カスタム YAML スキルで個別銘柄を対話的に深掘り |
| **ゼロサーバー自動配信** | GitHub Actions / Docker / ローカル常駐 / FastAPI に対応し、Telegram・Discord・Slack・Email 等へ定期配信 |

## 🚀 5 分クイックスタート

### 方法 1：GitHub Actions（無料・サーバー不要）

1. 本リポジトリを **Fork** します。
2. Fork 先の `Settings` → `Secrets and variables` → `Actions` で最小構成の Secrets を設定します：

| Secret 名 | 設定例 / 説明 | 必須 |
|---|---|:---:|
| `STOCK_LIST` | `7203.T,9984.T,AAPL,NVDA`（カンマ区切り） | ✅ |
| `REPORT_LANGUAGE` | `en`（英語レポート出力を推奨） | 推奨 |
| AI API Key（いずれか 1 つ） | `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` 等 | ✅ |
| 通知チャネル（任意） | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`、`DISCORD_WEBHOOK_URL`、`SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID`、`EMAIL_SENDER` + `EMAIL_PASSWORD` 等 | 任意 |
| ニュース検索（推奨） | `SERPAPI_API_KEYS` / `TAVILY_API_KEYS` / `BRAVE_API_KEYS` | 推奨 |

3. `Actions` タブでワークフローを有効化し、`每日股票分析` → `Run workflow` で手動テストを実行します。

### 方法 2：ローカル / WebUI / デスクトップアプリ

```bash
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis
pip install -r requirements.txt
cp .env.example .env   # STOCK_LIST=7203.T,9984.T,AAPL と REPORT_LANGUAGE=en、AI Key を設定

# 指定銘柄を 1 回分析
python main.py --stocks 7203.T,9984.T,AAPL --no-market-review

# Web UI を起動 (http://127.0.0.1:8000)
python main.py --serve-only
```

> ノーコードで始めたい場合は [Beginner Desktop Setup Guide (EN)](./beginner-client-setup_EN.md) をご覧ください。

## 📚 詳細ドキュメント（English / 中文）

| ドキュメント | 内容 |
|---|---|
| [Full English README](./README_EN.md) | 英語版の全体概要・スポンサー・CLI・プラグイン導入 |
| [Documentation Index (EN)](./INDEX_EN.md) | 全ドキュメントの目次と中国市場用語集 |
| [Official Docs Site (EN)](https://dsa.zhulinsen.tech/en/) | 検索対応の公式ドキュメントサイト |
| [Multi-Market Support & Boundaries](./market-support_EN.md) | 日本株・米国株など各市場のデータソースと制限事項 |
| [LLM Config Guide (EN)](./LLM_CONFIG_GUIDE_EN.md) | Gemini / OpenAI / Claude / DeepSeek / Ollama / LiteLLM ルーティング設定 |
| [Notification Channels (EN)](./notifications_EN.md) | Telegram / Discord / Slack / Email / Webhook 通知設定 |
| [Deploy Guide (EN)](./DEPLOY_EN.md) / [FAQ (EN)](./FAQ_EN.md) | Docker・サーバー運用とよくある質問 |

## 📄 ライセンス・免責事項

- **ライセンス**：[MIT License](../LICENSE) © 2026 ZhuLinsen
- **免責事項**：本プロジェクトは情報提供および学習目的のみであり、投資助言を構成するものではありません。投資判断はご自身の責任で行ってください。
