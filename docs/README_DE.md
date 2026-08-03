<div align="center">

# README (Deutsch) — Intelligentes Aktienanalysesystem

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

<p align="center">
  <img src="https://trendshift.io/api/badge/trendshift/repositories/18527/daily?language=Python" alt="#1 Python Repository Of The Day | Trendshift" width="250" height="55"/>&nbsp;<a href="https://hellogithub.com/repository/ZhuLinsen/daily_stock_analysis" target="_blank"><img src="https://api.hellogithub.com/v1/widgets/recommend.svg?rid=6daa16e405ce46ed97b4a57706aeb29f&claim_uid=pfiJMqhR9uvDGlT&theme=neutral" alt="Featured｜HelloGitHub" width="230" /></a>
</p>

**Intelligentes Analysesystem für A-/Hongkong-/US-/japanische-/koreanische-/taiwanische-Aktien-Watchlisten auf Basis großer AI-Modelle**

Analysiert die Watchlist täglich automatisch -> erzeugt das Entscheidungs-Dashboard -> pusht an Telegram / Discord / Slack / E-Mail / WeCom / Feishu.

[**Produktvorschau**](#-produktvorschau) · [**Funktionen**](#-funktionen) · [**Schnellstart**](#-schnellstart) · [**Push-Wirkung**](#-push-wirkung) · [**Dokumentationszentrum**](./INDEX.md) · [**Vollständiger Leitfaden**](./full-guide.md)

Deutsch | [English](README_EN.md) | [Chinesisch (vereinfacht)](../README.md)

</div>

## 💖 Sponsoren (Sponsors)

<div align="center">
  <p align="center">
    <a href="https://open.anspire.cn/?share_code=QFBC0FYC" target="_blank"><img src="assets/anspire.png" alt="Anspire Open — Modell- und Suchdienst aus einer Hand" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a>
    <a href="https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis" target="_blank"><img src="assets/serpapi_banner_zh.png" alt="Schnelles Abrufen von Echtzeit-Finanznachrichten aus Suchmaschinen - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a>
  </p>
</div>

## 🖥️ Produktvorschau

<p align="center">
  <img src="assets/readme_workspace_tour_20260510.gif" alt="Demo der DSA-Web-Arbeitsumgebung" width="720">
</p>

## ✨ Funktionen

| Funktion | Abgedeckter Inhalt |
|------|------|
| AI-Entscheidungsbericht | Kernschlussfolgerung, Score, Trend, Kauf-/Verkaufspunkte, Risikoalarme, Katalysatoren, Handlungs-Checkliste |
| Aggregation mehrerer Märkte | Abdeckung von A-, Hongkong-, US-, japanischen, koreanischen und taiwanischen Aktien sowie ETF; Unterstützung von Kursdaten, K-Linien, technischen Indikatoren, Nachrichten, Unternehmensmeldungen, Fundamentaldaten und Bericht-Hilfsdaten; die Datenquellen und Fähigkeitsgrenzen der einzelnen Märkte siehe [Markt-Support-Grenzen](market-support.md) |
| Web-/Desktop-Arbeitsumgebung | Manuelle Analyse, Aufgabenfortschritt, historische Berichte, vollständiges Markdown, Backtest, Positionen, Konfigurationsverwaltung, helles/dunkles Thema |
| Agent-Strategieaktienabfrage | Mehrrundige Nachfragen, Unterstützung von 15 integrierten Strategien wie MA, Chan-Theorie, Wellentheorie, Trend, Hotspot, Ereignis, Wachstum, Erwartung usw.; Abdeckung von Web/Bot/API |
| Intelligenter Import und Vervollständigung | Bild-, CSV/Excel- und Zwischenablage-Import; Vervollständigung von Aktiencode/-name/-pinyin/-alias |
| Automatisierung und Push | GitHub Actions, Docker, lokale geplante Tasks, FastAPI-Dienst sowie WeCom/Feishu/Telegram/Discord/Slack/E-Mail-Push |

> Funktionsdetails, Feldverträge, die P0-Timeout-Semantik für Fundamentaldaten, Handelsdisziplin, Datenquellen-Priorität und Web/API-Verhalten siehe [Vollständiger Konfigurations- und Bereitstellungsleitfaden](./full-guide.md).

### Technologie-Stack und Datenquellen

| Typ | Unterstützung |
|------|------|
| AI-Modelle | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC), [AIHubMix](https://aihubmix.com/?aff=CfMq), Gemini, OpenAI-kompatibel, DeepSeek, Qwen, Claude, lokale Ollama-Modelle usw. |
| Kursdaten | [TickFlow](https://tickflow.org/auth/register?ref=WDSGSPS5XC), AkShare, Tushare, Pytdx, Baostock, YFinance, Longbridge |
| Nachrichtensuche | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC), [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis), [Tavily](https://tavily.com/), [Bocha](https://open.bocha.cn/), [Brave](https://brave.com/search/api/), [MiniMax](https://platform.minimaxi.com/), SearXNG |
| Social-Stimmung | [Stock Sentiment API](https://api.adanos.org/docs) (Reddit / X / Polymarket, nur US-Aktien, optional) |

> Das Projekt enthält standardmäßig kostenlose Kursquellen wie AkShare, Baostock und YFinance und kann ohne Konfiguration ausgeführt werden; kostenlose Quellen unterliegen dem Rate-Limit der vorgelagerten Anbieter, Schnittstellenänderungen und Netzwerkschwankungen, die Stabilität ist nicht garantiert. Für langfristig geplante Aufgaben, Batch-Analysen oder stabilere Kursdaten wird empfohlen, Token-basierte Datenquellen wie TickFlow, Tushare und Longbridge zu konfigurieren; die geltenden Märkte, die Actions-Zuordnung und die Fallback-Regeln siehe [Datenquellen-Konfiguration](./full-guide.md#-datenquellen-konfiguration).

## 🚀 Schnellstart

### Variante 1: [GitHub Actions (empfohlen)](https://www.bilibili.com/video/BV11FEb66EXG/)

> In 5 Minuten bereitgestellt, null Kosten, kein Server erforderlich.

#### 1. Dieses Repository forken

Auf den `Fork`-Button oben rechts klicken (und gern auch ein Star zur Unterstützung).

#### 2. Secrets konfigurieren

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

**AI-Modellkonfiguration (mindestens eines konfigurieren)**

Standardmäßig zuerst einen Modellanbieter auswählen und den API Key eintragen; wenn mehrere Modelle, Bilderkennung, lokale Modelle oder erweitertes Routing benötigt werden, siehe [LLM-Konfigurationsleitfaden](./LLM_CONFIG_GUIDE.md).

| Secret-Name | Erläuterung | Erforderlich |
|-------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC) API Key; ein Key aktiviert gleichzeitig beliebte globale große Modelle und Websuche, inklusive kostenlosem Kontingent für dieses Projekt | **Empfohlen** |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API Key; ein Key für die Nutzung der gesamten Modellfamilie, für dieses Projekt 10 % Rabatt | **Empfohlen** |
| `GEMINI_API_KEY` | Google Gemini API Key | Optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | Optional |
| `OPENAI_API_KEY` | OpenAI-kompatibler API Key (unterstützt DeepSeek, Qwen usw.) | Optional |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | Auszufüllen bei Verwendung eines OpenAI-kompatiblen Dienstes | Optional |

> Ollama eignet sich besser für lokale/Docker-Bereitstellung; für GitHub Actions werden Cloud-APIs empfohlen.

**Konfiguration der Benachrichtigungskanäle (mindestens einen konfigurieren)**

| Secret-Name | Erläuterung |
|-------------|------|
| `WECHAT_WEBHOOK_URL` | WeCom-Roboter |
| `FEISHU_WEBHOOK_URL` | Feishu-Roboter |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram |
| `DISCORD_WEBHOOK_URL` | Discord Webhook |
| `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | Slack Bot |
| `EMAIL_SENDER` + `EMAIL_PASSWORD` | E-Mail-Push |

Weitere Kanäle, Signaturprüfung, Gruppen-E-Mails, Markdown-zu-Bild usw. siehe [Detaillierte Konfiguration der Benachrichtigungskanäle](./full-guide.md#-detaillierte-konfiguration-der-benachrichtigungskan%C3%A4le).

**Watchlist-Konfiguration (erforderlich)**

| Secret-Name | Erläuterung | Erforderlich |
|-------------|------|:----:|
| `STOCK_LIST` | Watchlist-Codes, z. B. `600519,hk00700,AAPL,7203.T,005930.KS,2330.TW` | ✅ |

**Konfiguration der Nachrichtenquellen (empfohlen)**

Die Nachrichtenquellen beeinflussen die Qualität von Stimmungslage, Unternehmensmeldungen, Ereignissen und Katalysatoren erheblich; es wird empfohlen, mindestens einen Suchdienst zu konfigurieren.

| Secret-Name | Erläuterung | Erforderlich |
|-------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/): für chinesische Inhalte besonders optimiert, kann die A-Aktien-Analyse verbessern; derselbe Key dient auch als Beispiel für den Anspire-Großmodell-Gateway-Fallback | **Empfohlen** |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis): Verstärkung der Suchmaschinen-Ergebnisse, geeignet für Echtzeit-Finanznachrichten | **Empfohlen** |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/): allgemeine Nachrichtensuch-API | Optional |
| `BOCHA_API_KEYS` | [Bocha Search](https://open.bocha.cn/): für die chinesische Suche optimiert, unterstützt AI-Zusammenfassung | Optional |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/): datenschutzorientiert, Verstärkung der US-Aktien-Informationen | Optional |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimaxi.com/): strukturierte Suchergebnisse | Optional |
| `SEARXNG_BASE_URLS` | SearXNG-Selbsthost-Instanz: quotenloser Fallback, geeignet für private Bereitstellung | Optional |

Weitere Suchquellen, Social-Stimmung und Degradierungsregeln siehe [Suchdienst-Konfiguration](./full-guide.md#-suchdienst-konfiguration).

**Konfiguration der Kursdatenquellen (optional)**

> Standardmäßig werden kostenlose Datenquellen wie AkShare, Baostock und YFinance verwendet; Hinweise auf „nicht konfiguriert“ in den Logs beeinträchtigen die Ausführung nicht.
> Für stabilere Kursdaten können je nach Markt die folgenden Secrets konfiguriert werden:

| Secret-Name | Geltende Märkte | Erläuterung |
|-------------|:--------:|------|
| `TUSHARE_TOKEN` | A-Aktien | Verbessert die Stabilität historischer Kursdaten |
| `LONGBRIDGE_OAUTH_CLIENT_ID` + `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` | Hongkong-/US-Aktien | Ergänzt Felder wie Volumenverhältnis, Umschlagshäufigkeit, PE usw. |

> Siehe [Datenquellen-Konfiguration](./full-guide.md#-datenquellen-konfiguration).

#### 3. Actions aktivieren

Auf dem Tab `Actions` -> `I understand my workflows, go ahead and enable them`

#### 4. Manueller Test

`Actions` -> `Tägliche Aktienanalyse` -> `Run workflow` -> `Run workflow`

#### Fertig

Standardmäßig wird an jedem Werktag um 18:00 (Pekinger Zeit) automatisch ausgeführt; eine manuelle Auslösung ist ebenfalls möglich. Standardmäßig wird an Nicht-Handelstagen (einschließlich A/H/US-Feiertagen) nicht ausgeführt; Regeln für erzwungene Ausführung, Handelstagsprüfung und Fortsetzung nach Unterbrechung siehe [Vollständiger Leitfaden](./full-guide.md#-konfiguration-geplanter-tasks).

### Variante 2: [Client-Konfigurations-Tutorial](https://www.bilibili.com/video/BV11FEb66Eyr/) / Lokale Ausführung / Docker-Bereitstellung

```bash
# Projekt klonen
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis

# Abhängigkeiten installieren
pip install -r requirements.txt

# Umgebungsvariablen konfigurieren
cp .env.example .env && vim .env

# Analyse ausführen
python main.py
```

Häufig verwendete Befehle:

```bash
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL,2330.TW
python main.py --market-review
python main.py --schedule
python main.py --serve-only
```

> Docker-Bereitstellung, geplante Tasks und Cloud-Server-Zugriff siehe [Vollständiger Leitfaden](./full-guide.md); das Packen des Desktop-Clients siehe [Hinweise zum Packen der Desktop-Version](./desktop-package.md).

## 📱 Push-Wirkung

### Entscheidungs-Dashboard

```markdown
🎯 2026-02-08 Entscheidungs-Dashboard
Insgesamt 3 Aktien analysiert | 🟢 Kauf:0 🟡 Abwarten:2 🔴 Verkauf:1

📊 Zusammenfassung der Analyseergebnisse
🟡 Zhongwu Gaoxin (000657): Abwarten | Score 65 | bullish
🟡 Yongding (600105): Abwarten | Score 48 | seitwärts
🔴 Xinlai Yingcai (300260): Verkauf | Score 35 | bearish

🚨 Risikoalarm:
Risikopunkt 1: Bei den Hauptmitteln ist ein deutlicher Abfluss zu beobachten; kurzfristiger Verkaufsdruck ist zu beachten.
Risikopunkt 2: Die Chip-Konzentration ist recht hoch; die Widerstände für einen Anstieg können größer sein.

✨ Positive Katalysatoren:
Katalysator 1: Das Unternehmen wird vom Markt als Kernziel der AI-Lieferkette positioniert.
Katalysator 2: Das jüngste Gewinnwachstum bietet den Aktienkursen fundamentale Unterstützung.
```

### Markt-Nachbetrachtung

```markdown
🎯 2026-01-10 Markt-Nachbetrachtung

📊 Hauptindizes
- Shanghai Composite: 3250.12 (+0.85%)
- Shenzhen Component: 10521.36 (+1.02%)
- ChiNext: 2156.78 (+1.35%)

📈 Marktüberblick
Gestiegen: 3920 | Gefallen: 1349 | Limit-up: 155 | Limit-down: 3
```

## ⚙️ Konfigurationshinweise

Vollständige Umgebungsvariablen, Modellkanäle, Benachrichtigungskanäle, Datenquellen-Priorität, Handelsdisziplin, P0-Semantik für Fundamentaldaten und Bereitstellungshinweise siehe [Vollständiger Konfigurationsleitfaden](./full-guide.md).

## 🖥️ Web-Oberfläche

Die Web-Arbeitsumgebung bietet Konfigurationsverwaltung, Aufgabenüberwachung, manuelle Analyse, historische Berichte, vollständige Markdown-Berichte, Agent-Aktienabfrage, Backtest, Positionsverwaltung, intelligenten Import sowie helles/dunkles Thema. Starten mit:

```bash
python main.py --webui
python main.py --webui-only
```

Nach dem Zugriff auf `http://127.0.0.1:8000` ist es einsatzbereit. Details zu Authentifizierung, intelligentem Import, Suchvervollständigung, Kopieren historischer Berichte und Cloud-Server-Zugriff siehe [Lokale WebUI-Verwaltungsoberfläche](./full-guide.md#-lokale-webui-verwaltungsoberfl%C3%A4che).

## 🤖 Agent-Strategieaktienabfrage

Nach dem Konfigurieren eines beliebigen verfügbaren AI-API-Keys kann die Strategieaktienabfrage auf der Web-Seite `/chat` verwendet werden; zum expliziten Deaktivieren kann `AGENT_MODE=false` gesetzt werden.

- Unterstützt integrierte Strategien wie MA-Golden-Cross, Chan-Theorie, Wellentheorie, bullische Trends, heiße Themen, ereignisgetrieben, Wachstumsqualität, Erwartungs-Neubewertung usw.
- Unterstützt den Abruf von Echtzeit-Kursdaten, K-Linien, technischen Indikatoren, Nachrichten und Risikoinformationen
- Unterstützt mehrrundige Nachfragen, Sitzungsexport, Senden an Benachrichtigungskanäle und Hintergrundausführung
- Unterstützt benutzerdefinierte Strategiedateien und Multi-Agent-Orchestrierung (experimentell)

> Konkrete Agent-Parameter, `skill`-Namenskompatibilität, Multi-Agent-Modus und Budget-Guardrails siehe [Vollständiger Leitfaden](./full-guide.md#-lokale-webui-verwaltungsoberfl%C3%A4che) und [LLM-Konfigurationsleitfaden](./LLM_CONFIG_GUIDE.md).

## 🧩 Verwandte Projekte (Related Projects)

> DSA fokussiert auf tägliche Analyseberichte; die integrierte Aktienauswahl orientiert sich an AlphaSift, AlphaEvo dient der Strategievalidierung und -evolution.

| Projekt | Positionierung |
|------|------|
| [AlphaSift](https://github.com/ZhuLinsen/alphasift) | Referenzprojekt für die integrierte Aktienauswahl-Engine von DSA |
| [AlphaEvo](https://github.com/ZhuLinsen/alphaevo) | Strategie-Backtest und Selbst-Evolution; dient der Validierung von Strategieregeln und erkundet über Iterationen Strategieparameter und -kombinationen |

## 📬 Kontakt und Zusammenarbeit

<table>
  <tr>
    <td width="92" valign="top"><strong>Kooperations-E-Mail</strong></td>
    <td valign="top">
      <a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a><br>
      Projektberatung, Bereitstellungs-Support und Funktionserweiterung
    </td>
    <td align="center" rowspan="3" valign="middle" width="148">
      <a href="http://xhslink.com/m/tU520DWCKT" target="_blank"><img src="assets/xiaohongshu_tick.jpg" width="112" alt="Xiaohongshu-QR-Code"></a><br>
      <sub>QR-Code scannen, um Xiaohongshu zu folgen</sub>
    </td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>Xiaohongshu</strong></td>
    <td valign="top"><a href="http://xhslink.com/m/tU520DWCKT">Willkommen bei Xiaohongshu</a></td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>Problem-Feedback</strong></td>
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">Issue einreichen</a></td>
  </tr>
</table>

## 📄 License

[MIT License](../LICENSE) © 2026 ZhuLinsen

Wenn du dieses Projekt verwendest oder als Grundlage für eine Weiterentwicklung nutzt, ist eine Quellenangabe im README oder in der Dokumentation mit Link zu diesem Repository sehr willkommen.

## ⚠️ Haftungsausschluss

Dieses Projekt dient nur zu Lern- und Forschungszwecken und stellt keine Anlageberatung dar. Aktienmärkte bergen Risiken; investiere mit Bedacht. Der Autor übernimmt keine Haftung für Verluste, die durch die Nutzung dieses Projekts entstehen.
