<div align="center">

# 📈 Tägliche Aktienanalyse

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

<p align="center">
  <img src="https://trendshift.io/api/badge/trendshift/repositories/18527/daily?language=Python" alt="#1 Python Repository Of The Day | Trendshift" width="250" height="55"/>&nbsp;<a href="https://hellogithub.com/repository/ZhuLinsen/daily_stock_analysis" target="_blank"><img src="https://api.hellogithub.com/v1/widgets/recommend.svg?rid=6daa16e405ce46ed97b4a57706aeb29f&claim_uid=pfiJMqhR9uvDGlT&theme=neutral" alt="Featured｜HelloGitHub" width="230" /></a>
</p>

> 🤖 KI-gestütztes Analysesystem für deine Watchlist aus A-Aktien, Hongkong, USA, Japan, Korea und Taiwan — analysiert täglich automatisch und schickt ein „Entscheidungs-Dashboard" an WeCom/Feishu/DingTalk/Telegram/Discord/Slack/E-Mail

[**Vorschau**](#-vorschau) · [**Funktionen**](#-funktionen) · [**Schnellstart**](#-schnellstart) · [**Beispielausgabe**](#-beispielausgabe) · [**Doku-Übersicht**](docs/INDEX.md) · [**Vollständige Anleitung**](docs/full-guide.md)

Deutsch | [简体中文](docs/README_ZH.md) | [English](docs/README_EN.md) | [繁體中文](docs/README_CHT.md)

</div>

## 💖 Sponsoren

<div align="center">
  <p align="center">
    <a href="https://open.anspire.cn/dsa?share_code=QFBC0FYC" target="_blank"><img src="./docs/assets/anspire.png" alt="Anspire Open — Modelle und Suche aus einer Hand" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a>
    <a href="https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis" target="_blank"><img src="./docs/assets/serpapi_banner_en.png" alt="Finanznachrichten in Echtzeit aus Suchmaschinen abgreifen - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a>
  </p>
</div>

## 🖥️ Vorschau

<p align="center">
  <img src="docs/assets/readme_workspace_tour_20260510.gif" alt="Demo des DSA-Web-Arbeitsbereichs" width="720">
</p>

## ✨ Funktionen

| Fähigkeit | Umfang |
|------|------|
| KI-Entscheidungsberichte | Kernaussage, Score, Trend, Ein- und Ausstiegsmarken, Risikowarnungen, Katalysatoren, Handlungs-Checkliste |
| Multi-Markt-Datenaggregation | A-Aktien, Hongkong, USA, Japan, Korea, Taiwan und ETFs — mit Kursen, Kerzencharts, technischen Indikatoren, Nachrichten, Meldungen, Fundamentaldaten und Zusatzdaten für Berichte; Datenquellen und Grenzen je Markt siehe [Marktabdeckung](docs/market-support.md) |
| Web-/Desktop-Arbeitsbereich | Manuelle Analyse, Aufgabenfortschritt, Berichtshistorie, vollständiges Markdown, Backtest, Portfolio, Konfiguration, helles/dunkles Design |
| Agent-Strategieabfragen | Mehrstufige Rückfragen mit 15 eingebauten Strategien (u. a. gleitende Durchschnitte, Chan-Theorie, Elliott-Wellen, Trend, Themen, Ereignisse, Wachstum, Neubewertung) — über Web/Bot/API |
| Intelligenter Import & Autovervollständigung | Import aus Bild, CSV/Excel und Zwischenablage; Vervollständigung von Kürzel, Name, Pinyin und Alias |
| Automatisierung & Benachrichtigungen | GitHub Actions, Docker, lokale Zeitsteuerung, FastAPI-Dienst sowie Versand an WeCom/Feishu/DingTalk/Telegram/Discord/Slack/E-Mail |

> Details zu Funktionen, Feldverträgen, P0-Timeout-Semantik bei Fundamentaldaten, Handelsdisziplin, Priorität der Datenquellen und Web-/API-Verhalten stehen in der [vollständigen Konfigurations- und Deployment-Anleitung](docs/full-guide.md).

### Technik und Datenquellen

| Kategorie | Unterstützt |
|------|------|
| KI-Modelle | [Anspire](https://open.anspire.cn/dsa?share_code=QFBC0FYC), [AIHubMix](https://aihubmix.com/?aff=CfMq), Gemini, OpenAI-kompatible Anbieter, DeepSeek, Qwen, Claude, Ollama (lokal) u. a. |
| Kursdaten | [TickFlow](https://tickflow.org/auth/register?ref=WDSGSPS5XC), AkShare, Tushare, Pytdx, Baostock, YFinance, Longbridge |
| Nachrichtensuche | [Anspire](https://open.anspire.cn/dsa/?share_code=QFBC0FYC), [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis), [Tavily](https://tavily.com/), [Bocha](https://open.bocha.cn/), [Brave](https://brave.com/search/api/), [MiniMax](https://platform.minimaxi.com/), SearXNG |
| Soziale Stimmung | [Stock Sentiment API](https://api.adanos.org/docs) (Reddit / X / Polymarket, nur US-Aktien, optional) |

> Das Projekt bringt mit AkShare, Baostock und YFinance kostenlose Kursquellen mit und läuft ohne jede Konfiguration. Kostenlose Quellen unterliegen jedoch Rate-Limits, Schnittstellenänderungen und Netzschwankungen — Stabilität ist nicht garantiert. Für dauerhafte Zeitpläne, Massenanalysen oder verlässlichere Kurse empfehlen sich Token-basierte Quellen wie TickFlow, Tushare oder Longbridge; passende Märkte, Actions-Zuordnung und Fallback-Regeln siehe [Datenquellen-Konfiguration](docs/full-guide.md#数据源配置).

## 🚀 Schnellstart

### Variante 1: GitHub Actions (empfohlen)

> In 5 Minuten eingerichtet, kostenlos, kein Server nötig.

#### 1. Repository forken

Oben rechts auf `Fork` klicken (und gern auch einen Star⭐ dalassen).

#### 2. Secrets hinterlegen

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

**KI-Modell (mindestens eines erforderlich)**

Wähle zunächst einen Anbieter und trage dessen API-Key ein. Für mehrere Modelle, Bilderkennung, lokale Modelle oder fortgeschrittenes Routing siehe den [LLM-Konfigurationsleitfaden](docs/LLM_CONFIG_GUIDE.md).

| Secret | Beschreibung | Pflicht |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/dsa?share_code=QFBC0FYC) API-Key — ein Key für gängige große Modelle und Websuche zugleich; für neue Nutzer dieses Projekts gibt es ein Freikontingent im Gegenwert von 35 CNY | **empfohlen** |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API-Key — ein Key für die gesamte Modellpalette, für dieses Projekt mit 10 % Rabatt | **empfohlen** |
| `GEMINI_API_KEY` | Google Gemini API-Key | optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API-Key | optional |
| `OPENAI_API_KEY` | OpenAI-kompatibler API-Key (u. a. DeepSeek, Qwen) | optional |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | nur bei OpenAI-kompatiblen Diensten nötig | optional |

> Ollama eignet sich eher für lokalen Betrieb oder Docker; für GitHub Actions ist eine Cloud-API die bessere Wahl.

**Benachrichtigungskanäle (mindestens einer erforderlich)**

| Secret | Beschreibung |
|------------|------|
| `WECHAT_WEBHOOK_URL` | WeCom-Bot (WeChat Work) |
| `FEISHU_WEBHOOK_URL` | Feishu-Bot |
| `DINGTALK_WEBHOOK_URL` | DingTalk-Gruppenbot (bei aktivierter Signatur zusätzlich `DINGTALK_SECRET`) |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram |
| `DISCORD_WEBHOOK_URL` | Discord-Webhook |
| `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | Slack-Bot |
| `EMAIL_SENDER` + `EMAIL_PASSWORD` | E-Mail-Versand |

Weitere Kanäle, Signaturprüfung, Sammelmails und Markdown-zu-Bild-Optionen siehe [Konfiguration der Benachrichtigungskanäle](docs/full-guide.md#通知渠道详细配置).

**Watchlist (Pflicht)**

| Secret | Beschreibung | Pflicht |
|------------|------|:----:|
| `STOCK_LIST` | Kürzel der beobachteten Titel, z. B. `600519,hk00700,AAPL,7203.T,005930.KS,2330.TW` | ✅ |

**Nachrichtenquellen (empfohlen)**

Die Nachrichtenquelle beeinflusst Stimmungsbild, Meldungen, Ereignisse und Katalysatoren erheblich — mindestens ein Suchdienst ist ratsam.

| Secret | Beschreibung | Pflicht |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://open.anspire.cn/dsa?share_code=QFBC0FYC): bündelt weltweite Stimmungsdaten, passend für Nachrichten- und Sentiment-Recherche zu A-Aktien, US- und HK-Titeln; derselbe Key lässt sich für die Modelle mitnutzen | **empfohlen** |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis): ergänzt Suchmaschinenergebnisse, gut für Finanznachrichten in Echtzeit | **empfohlen** |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/): allgemeine Nachrichtensuch-API | optional |
| `BOCHA_API_KEYS` | [Bocha-Suche](https://open.bocha.cn/): auf Chinesisch optimiert, mit KI-Zusammenfassung | optional |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/): datenschutzfreundlich, ergänzt US-Aktiennachrichten | optional |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimaxi.com/): strukturierte Suchergebnisse | optional |
| `SEARXNG_BASE_URLS` | Eigene SearXNG-Instanz: Rückfalloption ohne Kontingent, gut für private Deployments | optional |

Weitere Suchquellen, soziale Stimmungsdaten und Degradationsregeln siehe [Konfiguration der Suchdienste](docs/full-guide.md#搜索服务配置).

**Kursdatenquellen (optional)**

> Standardmäßig kommen die kostenlosen Quellen AkShare, Baostock und YFinance zum Einsatz; „nicht konfiguriert"-Hinweise im Log beeinträchtigen den Betrieb nicht.
> Für verlässlichere Kurse lassen sich je Markt folgende Secrets setzen:

| Secret | Markt | Beschreibung |
|------------|:--------:|------|
| `TUSHARE_TOKEN` | A-Aktien | stabilere historische Kursdaten |
| `LONGBRIDGE_OAUTH_CLIENT_ID` + `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` | Hongkong/USA | ergänzt Felder wie Volumenverhältnis, Umschlagshäufigkeit und KGV |

> Details siehe [Datenquellen-Konfiguration](docs/full-guide.md#数据源配置).

#### 3. Actions aktivieren

Reiter `Actions` → `I understand my workflows, go ahead and enable them`

#### 4. Manuell testen

`Actions` → `每日股票分析` (Tägliche Aktienanalyse) → `Run workflow` → `Run workflow`

#### Fertig

Standardmäßig läuft die Analyse **werktags um 18:00 Uhr (Pekinger Zeit)** automatisch und lässt sich zusätzlich manuell auslösen. An handelsfreien Tagen (inkl. Feiertagen in China, Hongkong und den USA) läuft sie nicht. Regeln zu erzwungenen Läufen, Handelstagsprüfung und Wiederaufnahme siehe [vollständige Anleitung](docs/full-guide.md#定时任务配置).

### Variante 2: Lokaler Betrieb / Docker

```bash
# Projekt klonen
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis

# Abhängigkeiten installieren
pip install -r requirements.txt

# Umgebungsvariablen konfigurieren
cp .env.example .env && vim .env

# Analyse starten
python main.py
```

Häufige Befehle:

```bash
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL,2330.TW
python main.py --market-review
python main.py --schedule
python main.py --serve-only
```

> Docker-Deployment, Zeitsteuerung und Zugriff über einen Cloud-Server sind in der [vollständigen Anleitung](docs/full-guide.md) beschrieben; das Packaging des Desktop-Clients in den [Hinweisen zum Desktop-Paket](docs/desktop-package.md).

## 📱 Beispielausgabe

### Entscheidungs-Dashboard

```
🎯 2026-02-08 决策仪表盘
共分析3只股票 | 🟢买入:0 🟡观望:2 🔴卖出:1

📊 分析结果摘要
⚪ 中钨高新(000657): 观望 | 评分 65 | 看多
⚪ 永鼎股份(600105): 观望 | 评分 48 | 震荡
🟡 新莱应材(300260): 卖出 | 评分 35 | 看空

⚪ 中钨高新 (000657)
📰 重要信息速览
💭 舆情情绪: 市场关注其AI属性与业绩高增长，情绪偏积极，但需消化短期获利盘和主力流出压力。
📊 业绩预期: 基于舆情信息，公司2025年前三季度业绩同比大幅增长，基本面强劲，为股价提供支撑。

🚨 风险警报:

风险点1：2月5日主力资金大幅净卖出3.63亿元，需警惕短期抛压。
风险点2：筹码集中度高达35.15%，表明筹码分散，拉升阻力可能较大。
风险点3：舆情中提及公司历史违规记录及重组相关风险提示，需保持关注。
✨ 利好催化:

利好1：公司被市场定位为AI服务器HDI核心供应商，受益于AI产业发展。
利好2：2025年前三季度扣非净利润同比暴涨407.52%，业绩表现强劲。
📢 最新动态: 【最新消息】舆情显示公司是AI PCB微钻领域龙头，深度绑定全球头部PCB/载板厂。2月5日主力资金净卖出3.63亿元，需关注后续资金流向。

---
生成时间: 18:00
```

### Marktrückblick

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

> Die Berichtssprache richtet sich nach der Konfiguration; die Beispiele oben zeigen die Standardausgabe auf Chinesisch.

## ⚙️ Konfiguration

Sämtliche Umgebungsvariablen, Modellkanäle, Benachrichtigungskanäle, die Priorisierung der Datenquellen, Handelsdisziplin, die P0-Semantik bei Fundamentaldaten und Deployment-Hinweise stehen in der [vollständigen Konfigurationsanleitung](docs/full-guide.md).

## 🖥️ Web-Oberfläche

Der Web-Arbeitsbereich bietet Konfigurationsverwaltung, Aufgabenüberwachung, manuelle Analyse, Berichtshistorie, vollständige Markdown-Berichte, Agent-Strategieabfragen, Backtests, Portfolioverwaltung, intelligenten Import sowie helles und dunkles Design. Start:

```bash
python main.py --serve
python main.py --serve-only
```

> `--webui` / `--webui-only` sind kompatible Aliase und entsprechen `--serve` / `--serve-only`.

Danach ist die Oberfläche unter `http://127.0.0.1:8000` erreichbar. Details zu Authentifizierung, intelligentem Import, Suchvervollständigung, Kopieren aus der Berichtshistorie und Zugriff über einen Cloud-Server siehe [lokale WebUI-Verwaltungsoberfläche](docs/full-guide.md#本地-webui-管理界面).

## 🤖 Agent-Strategieabfragen

Sobald ein beliebiger nutzbarer KI-API-Key hinterlegt ist, stehen die Strategieabfragen auf der Web-Seite `/chat` bereit; abschalten lässt sich das mit `AGENT_MODE=false`.

- Eingebaute Strategien u. a. für Goldene Kreuze gleitender Durchschnitte, Chan-Theorie, Elliott-Wellen, Aufwärtstrends, Themenschwerpunkte, ereignisgetriebene Ansätze, Wachstumsqualität und Neubewertung
- Zugriff auf Echtzeitkurse, Kerzencharts, technische Indikatoren, Nachrichten und Risikohinweise
- Mehrstufige Rückfragen, Export von Sitzungen, Versand an Benachrichtigungskanäle und Ausführung im Hintergrund
- Eigene Strategiedateien und Multi-Agent-Orchestrierung (experimentell)

> Konkrete Agent-Parameter, Kompatibilität der `skill`-Benennung, Multi-Agent-Modus und Budgetgrenzen siehe [vollständige Anleitung](docs/full-guide.md#本地-webui-管理界面) und [LLM-Konfigurationsleitfaden](docs/LLM_CONFIG_GUIDE.md).

## 🧩 Verwandte Projekte

> DSA konzentriert sich auf tägliche Analyseberichte. Die beiden folgenden Projekte derselben Reihe decken Titelauswahl, Strategieprüfung und Strategieentwicklung ab und lassen sich bei Bedarf ergänzend einsetzen. Sie werden derzeit eigenständig gepflegt; künftig sollen vorrangig Kandidatenimport, Backtest-Validierung und Berichtsverknüpfung mit DSA erschlossen werden.

| Projekt | Zweck |
|------|------|
| [AlphaSift](https://github.com/ZhuLinsen/alphasift) | Multifaktor-Titelauswahl und marktweites Screening zur Ermittlung von Kandidaten aus einem Aktienpool |
| [AlphaEvo](https://github.com/ZhuLinsen/alphaevo) | Strategie-Backtesting und Selbstentwicklung zur Validierung von Regeln sowie iterativen Erkundung von Parametern und Kombinationen |

## 📬 Kontakt und Zusammenarbeit

<table>
  <tr>
    <td width="120" valign="top"><strong>Kontakt-E-Mail</strong></td>
    <td valign="top">
      <a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a><br>
      Projektfragen, Deployment-Unterstützung und Funktionserweiterungen
    </td>
    <td align="center" rowspan="3" valign="middle" width="148">
      <a href="http://xhslink.com/m/tU520DWCKT" target="_blank"><img src="./docs/assets/xiaohongshu_tick.jpg" width="112" alt="Xiaohongshu-QR-Code"></a><br>
      <sub>QR-Code für Xiaohongshu scannen</sub>
    </td>
  </tr>
  <tr>
    <td width="120" valign="top"><strong>Xiaohongshu</strong></td>
    <td valign="top"><a href="http://xhslink.com/m/tU520DWCKT">Auf Xiaohongshu folgen</a></td>
  </tr>
  <tr>
    <td width="120" valign="top"><strong>Fehler melden</strong></td>
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">Issue erstellen</a></td>
  </tr>
</table>

## 📄 Lizenz

[MIT License](LICENSE) © 2026 ZhuLinsen

Bei Weiterentwicklung oder Verwendung freuen wir uns über einen Hinweis auf dieses Repository — danke für die Unterstützung der weiteren Pflege.

## ⚠️ Haftungsausschluss

Dieses Projekt dient ausschließlich zu Lern- und Forschungszwecken und stellt keine Anlageberatung dar. Aktienmärkte bergen Risiken — investiere mit Bedacht. Der Autor haftet nicht für Verluste, die aus der Nutzung dieses Projekts entstehen.

---
