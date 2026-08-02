<div align="center">

# 📈 Intelligentes Aktienanalyse-System

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![CI](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/daily_stock_analysis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

<p align="center">
  <img src="https://trendshift.io/api/badge/trendshift/repositories/18527/daily?language=Python" alt="#1 Python Repository Of The Day | Trendshift" width="250" height="55"/>&nbsp;<a href="https://hellogithub.com/repository/ZhuLinsen/daily_stock_analysis" target="_blank"><img src="https://api.hellogithub.com/v1/widgets/recommend.svg?rid=6daa16e405ce46ed97b4a57706aeb29f&claim_uid=pfiJMqhR9uvDGlT&theme=neutral" alt="Featured｜HelloGitHub" width="230" /></a>
</p>

> 🤖 Intelligentes Watchlist-Analysesystem für A-Aktien / Hongkong-Aktien / US-Aktien / japanische Aktien / koreanische Aktien / Taiwan-Aktien auf Basis großer KI-Modelle. Es analysiert täglich automatisch und pusht das „Entscheidungs-Dashboard" an WeCom / Feishu / Telegram / Discord / Slack / E-Mail

[**Produktvorschau**](#-produktvorschau) · [**Funktionsübersicht**](#-funktionsübersicht) · [**Schnellstart**](#-schnellstart) · [**Push-Beispiele**](#-push-beispiele) · [**Dokumentationszentrum**](docs/INDEX.md) · [**Vollständiger Leitfaden**](docs/full-guide.md)

Chinesisch | [Englisch](docs/README_EN.md) | [Traditionelles Chinesisch](docs/README_CHT.md)

</div>

## 💖 Sponsoren (Sponsors)
<div align="center">
  <p align="center">
    <a href="https://open.anspire.cn/dsa?share_code=QFBC0FYC" target="_blank"><img src="./docs/assets/anspire.png" alt="Anspire Open – einheitlicher Modell- und Suchdienst" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a>
    <a href="https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis" target="_blank"><img src="./docs/assets/serpapi_banner_zh.png" alt="Einfach Echtzeit-Finanznachrichten aus Suchmaschinen abrufen - SerpApi" width="300" height="141" style="width: 300px; height: 141px; object-fit: contain;"></a>
  </p>
</div>


## 🖥️ Produktvorschau

<p align="center">
  <img src="docs/assets/readme_workspace_tour_20260510.gif" alt="DSA Web-Workbench-Demo" width="720">
</p>

## ✨ Funktionsübersicht

| Fähigkeit | Abgedeckte Inhalte |
|------|------|
| KI-Entscheidungsbericht | Kernaussage, Score/Bewertung, Trend, Kauf-/Verkaufspunkte, Risikoalarme, Katalysatoren, Handlungs-Checkliste |
| Aggregation mehrerer Märkte | Abdeckung von A-Aktien, Hongkong-Aktien, US-Aktien, japanischen Aktien, koreanischen Aktien, Taiwan-Aktien und ETFs; Unterstützt Kursdaten, K-Linien, technische Indikatoren, Nachrichten, Unternehmensmeldungen, Fundamentaldaten und Berichtshilfsdaten; Datenquellen und Fähigkeitsgrenzen der verschiedenen Märkte siehe [Marktunterstützungsgrenzen](docs/market-support.md) |
| Web / Desktop-Workbench | Manuelle Analyse, Aufgabenfortschritt, Verlaufsberichte, vollständiges Markdown, Backtest, Positionen, Konfigurationsverwaltung, helles / dunkles Design |
| Agent-Strategie-Fragen zum Aktienmarkt | Mehrere Nachfragerunden; unterstützt 15 integrierte Strategien wie Gleitender Mittelwert (MA), Chan-Theorie, Wellentheorie, Trend, Hotspots, Ereignisse, Wachstum, Erwartungen usw.; Abdeckung von Web/Bot/API |
| Intelligenter Import und Vervollständigung | Import per Bild, CSV/Excel, Zwischenablage; Vervollständigung von Aktiencode/-name/Pinyin/Alias |
| Automatisierung und Push | GitHub Actions, Docker, lokale geplante Tasks, FastAPI-Service sowie Push über WeCom / Feishu / Telegram / Discord / Slack / E-Mail |

> Funktionale Details, Feldverträge, Grundlagen-P0-Timeoutsemantik, Trading-Disziplin, Datenquellen-Priorität sowie Web/API-Verhalten findest du im [Vollständigen Konfigurations- und Bereitstellungsleitfaden](docs/full-guide.md).

### Technologie-Stack und Datenquellen

| Typ | Unterstützung |
|------|------|
| KI-Modelle | [Anspire](https://open.anspire.cn/dsa?share_code=QFBC0FYC)、[AIHubMix](https://aihubmix.com/?aff=CfMq)、Gemini、OpenAI-kompatibel、DeepSeek、Qwen、Claude、Ollama-Lokalmodelle usw. |
| Kursdaten | [TickFlow](https://tickflow.org/auth/register?ref=WDSGSPS5XC)、AkShare、Tushare、Pytdx、Baostock、YFinance、Longbridge |
| Nachrichtensuche | [Anspire](https://open.anspire.cn/dsa/?share_code=QFBC0FYC)、[SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis)、[Tavily](https://tavily.com/)、[Bocha](https://open.bocha.cn/)、[Brave](https://brave.com/search/api/)、[MiniMax](https://platform.minimaxi.com/)、SearXNG |
| Soziale Stimmungsdaten | [Stock Sentiment API](https://api.adanos.org/docs)（Reddit / X / Polymarket, nur US-Aktien, optional） |

> Das Projekt enthält standardmäßig kostenlose Kursquellen wie AkShare, Baostock, YFinance usw. und kann ohne Konfiguration laufen. Kostenlose Quellen unterliegen Upstream-Rate-Limits, Schnittstellenänderungen und Netzwerkschwankungen – die Stabilität ist nicht garantiert. Für langfristige geplante Ausführungen, Batch-Analysen oder stabilere Kursdaten wird die Konfiguration token-basierter Datenquellen wie TickFlow, Tushare, Longbridge empfohlen. Geeignete Märkte, Actions-Zuordnung und Fallback-Regeln siehe [Datenquellen-Konfiguration](docs/full-guide.md#datenquellen-konfiguration).

## 🚀 Schnellstart

### Methode 1: [GitHub Actions (empfohlen)](https://www.bilibili.com/video/BV11FEb66EXG/)

> Deployment in 5 Minuten, kostenlos, ohne Server.


#### 1. Fork dieses Repositories

Klicke oben rechts auf den `Fork`-Button (und gib uns dabei gern einen Star⭐).

#### 2. Secrets konfigurieren

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

**KI-Modell-Konfiguration (mindestens eine konfigurieren)**

Wähle zunächst einen Modellanbieter und trage den API Key ein. Für mehrere Modelle, Bilderkennung, lokale Modelle oder erweitertes Routing siehe [LLM-Konfigurationsleitfaden](docs/LLM_CONFIG_GUIDE.md).

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/dsa?share_code=QFBC0FYC) API Key; ein Key aktiviert gleichzeitig populäre weltweite große Modelle und Websuche. Für neue Nutzer dieses Projekts gibt es kostenloses Guthaben im Gegenwert von 30 Yuan (GLM5.2, GPT und andere Modelle im Sonderangebot) | **Empfohlen** |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API Key; ein Key zum Umschalten auf die gesamte Modellpalette, ohne VPN; für dieses Projekt gibt es 10% Rabatt | **Empfohlen** |
| `GEMINI_API_KEY` | Google Gemini API Key | Optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | Optional |
| `OPENAI_API_KEY` | OpenAI-kompatibler API Key (unterstützt DeepSeek, Qwen usw.) | Optional |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | Auszufüllen, wenn ein OpenAI-kompatibler Dienst verwendet wird | Optional |

> Ollama eignet sich besser für lokale / Docker-Bereitstellung; für GitHub Actions wird die Cloud-API empfohlen.

**Benachrichtigungskanal-Konfiguration (mindestens einen konfigurieren)**

| Secret-Name | Beschreibung |
|------------|------|
| `WECHAT_WEBHOOK_URL` | WeCom-Roboter |
| `FEISHU_WEBHOOK_URL` | Feishu-Roboter |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram |
| `DISCORD_WEBHOOK_URL` | Discord Webhook |
| `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | Slack Bot |
| `EMAIL_SENDER` + `EMAIL_PASSWORD` | E-Mail-Push |

Weitere Kanäle, Signaturprüfung, Gruppene-Mails, Markdown-zu-Bild-Konvertierung usw. siehe [Detaillierte Benachrichtigungskanal-Konfiguration](docs/full-guide.md#benachrichtigungskanal-detaillierte-konfiguration).

**Watchlist-Konfiguration (Pflicht)**

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `STOCK_LIST` | Watchlist-Codes, z. B. `600519,hk00700,AAPL,7203.T,005930.KS,2330.TW` | ✅ |

**Nachrichtenquellen-Konfiguration (empfohlen)**

Nachrichtenquellen beeinflussen die Qualität von Stimmungsdaten, Unternehmensmeldungen, Ereignissen und Katalysatoren erheblich. Es wird empfohlen, mindestens einen Suchdienst zu konfigurieren.

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://open.anspire.cn/dsa?share_code=QFBC0FYC)：Bündelt globale Stimmungsinformationen; geeignet für Nachrichten- und Stimmungsrecherche zu A-Aktien, US-Aktien, Hongkong-Aktien usw.; derselbe Key kann auch für den Modellservice wiederverwendet werden; neue Nutzer dieses Projekts erhalten kostenloses Guthaben im Gegenwert von 30 Yuan | **Empfohlen** |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis)：Ergänzung der Suchmaschinenergebnisse, geeignet für Echtzeit-Finanznachrichten | **Empfohlen** |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/)：Allgemeine Nachrichtensuch-API | Optional |
| `BOCHA_API_KEYS` | [Bocha-Suche](https://open.bocha.cn/)：Optimiert für chinesische Suche, unterstützt KI-Zusammenfassungen | Optional |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/)：Datenschutzorientiert, Ergänzung für US-Aktien-Nachrichten | Optional |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimaxi.com/)：Strukturierte Suchergebnisse | Optional |
| `SEARXNG_BASE_URLS` | Self-hostete SearXNG-Instanz：Quotierungsfreie Fallback-Option, geeignet für private Bereitstellung | Optional |

Weitere Suchquellen, soziale Stimmungsdaten und Degradierungsregeln siehe [Suchdienst-Konfiguration](docs/full-guide.md#suchdienst-konfiguration).

**Kursdatenquellen-Konfiguration (optional)**

> Standardmäßig werden kostenlose Datenquellen wie AkShare, Baostock, YFinance verwendet. Der Hinweis „nicht konfiguriert" im Log beeinträchtigt den Betrieb nicht.
> Für stabilere Kursdaten können je nach Markt folgende Secrets konfiguriert werden:

| Secret-Name | Geeignete Märkte | Beschreibung |
|------------|:--------:|------|
| `TUSHARE_TOKEN` | A-Aktien | Verbessert die Stabilität historischer Kursdaten |
| `LONGBRIDGE_OAUTH_CLIENT_ID` + `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` | Hongkong-/US-Aktien | Ergänzt Felder wie Volumenverhältnis, Umsatzquote, KGV usw. |

> Details siehe [Datenquellen-Konfiguration](docs/full-guide.md#datenquellen-konfiguration).

#### 3. Actions aktivieren

`Actions`-Tab → `I understand my workflows, go ahead and enable them`

#### 4. Manueller Test

`Actions` → `Tägliche Aktienanalyse` → `Run workflow` → `Run workflow`

#### Fertig

Standardmäßig wird automatisch an jedem **Werktag um 18:00 Uhr (Pekinger Zeit)** ausgeführt; ein manueller Trigger ist ebenfalls möglich. Standardmäßig wird an Nicht-Handelstagen (einschließlich A/H/US-Feiertagen) nicht ausgeführt. Regeln für erzwungene Ausführung, Handelstagsprüfung und unterbrechungsfreie Fortsetzung siehe [Vollständiger Leitfaden](docs/full-guide.md#geplanter-task-konfiguration).

### Methode 2: [Client-Konfigurations-Tutorial](https://www.bilibili.com/video/BV11FEb66Eyr/) / lokale Ausführung / Docker-Bereitstellung

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

> Docker-Bereitstellung, geplante Tasks und Zugriff über Cloud-Server siehe [Vollständiger Leitfaden](docs/full-guide.md); das Verpacken des Desktop-Clients siehe [Desktop-Paketierung](docs/desktop-package.md).

## 📱 Push-Beispiele

### Entscheidungs-Dashboard
```
🎯 2026-02-08 Entscheidungs-Dashboard
Insgesamt 3 Aktien analysiert | 🟢Kauf:0 🟡Abwarten:2 🔴Verkauf:1

📊 Zusammenfassung der Analyseergebnisse
⚪ Zhongwu High-Tech (000657): Abwarten | Score 65 | Bullisch
⚪ Yongding Shares (600105): Abwarten | Score 48 | Seitwärts
🟡 Xinlai Yingcai (300260): Verkauf | Score 35 | Bärisch

⚪ Zhongwu High-Tech (000657)
📰 Wichtige Informationen im Überblick
💭 Stimmung: Der Markt beachtet seine KI-Attribute und das hohe Gewinnwachstum; die Stimmung ist eher positiv, allerdings müssen kurzfristige Gewinnmitnahmen und Abflüsse von Hauptakteuren erst verdaut werden.
📊 Gewinnerwartung: Basierend auf Stimmungsinformationen ist das Betriebsergebnis des Unternehmens in den ersten drei Quartalen 2025 im Jahresvergleich stark gestiegen; die Fundamentaldaten sind robust und stützen den Aktienkurs.

🚨 Risikoalarme:

Risiko 1: Am 5. Februar verkauften Hauptakteure netto deutlich 363 Millionen Yuan; kurzfristiger Verkaufsdruck sollte beachtet werden.
Risiko 2: Der Konzentrationsgrad der Chip-Verteilung liegt bei 35,15%, was auf eine breite Streuung hinweist und den Aufwärtswiderstand erhöhen könnte.
Risiko 3: In der Stimmungslage werden historische Verstöße des Unternehmens sowie Risikohinweise im Zusammenhang mit Restrukturierungen erwähnt; dies sollte im Auge behalten werden.
✨ Positive Katalysatoren:

Katalysator 1: Das Unternehmen wird vom Markt als Kernlieferant von HDI für KI-Server positioniert und profitiert von der Entwicklung der KI-Branche.
Katalysator 2: Der Nettogewinn ohne nicht wiederkehrende Posten stieg in den ersten drei Quartalen 2025 im Jahresvergleich um 407,52%, eine starke Performance.
📢 Aktuellste Entwicklung: 【Neueste Meldung】Stimmungslage zufolge ist das Unternehmen führend im Bereich KI-PCB-Mikrobohrer und eng mit global führenden PCB-/Substrat-Herstellern verbunden. Am 5. Februar verkauften Hauptakteure netto 363 Millionen Yuan; die weitere Kapitalflussentwicklung sollte beobachtet werden.

---
Erstellt um: 18:00
```

### Marktrückblick
```
🎯 2026-01-10 Marktrückblick

📊 Hauptindizes
- Shanghai Composite: 3250.12 (🟢+0.85%)
- Shenzhen Component: 10521.36 (🟢+1.02%)
- ChiNext Index: 2156.78 (🟢+1.35%)

📈 Marktüberblick
Gestiegen: 3920 | Gefallen: 1349 | Kurslimit up: 155 | Kurslimit down: 3

🔥 Sektorperformance
Führend: Internetdienste, Kulturmedien, Kleinmetalle
Nachgebend: Versicherungen, Flughäfen, Photovoltaik-Ausrüstung
```

## ⚙️ Konfigurationshinweise

Vollständige Umgebungsvariablen, Modellkanäle, Benachrichtigungskanäle, Datenquellen-Priorität, Trading-Disziplin, Grundlagen-P0-Semantik und Bereitstellungshinweise siehe [Vollständiger Konfigurationsleitfaden](docs/full-guide.md).

## 🖥️ Web-Oberfläche

Die Web-Workbench bietet Konfigurationsverwaltung, Aufgabenüberwachung, manuelle Analyse, Verlaufsberichte, vollständige Markdown-Berichte, Agent-Fragen, Backtest, Positionsverwaltung, intelligenten Import sowie helles / dunkles Design. Start:

```bash
python main.py --webui
python main.py --webui-only
```

Zugriff über `http://127.0.0.1:8000`. Details zu Authentifizierung, intelligentem Import, Suchvervollständigung, Kopieren von Verlaufsberichten und Zugriff über Cloud-Server siehe [Lokale WebUI-Verwaltungsoberfläche](docs/full-guide.md#lokale-webui-verwaltungsoberfläche).

## 🤖 Agent-Strategie-Fragen zum Aktienmarkt

Nach der Konfiguration eines verfügbaren AI-API-Keys kannst du auf der Web-Seite `/chat` Strategiefragen nutzen; zum expliziten Deaktivieren kann `AGENT_MODE=false` gesetzt werden.

- Unterstützt integrierte Strategien wie Gleitender Mittelwert (MA) Golden Cross, Chan-Theorie, Wellentheorie, Aufwärtstrend, heiße Themen, Event-Drive, Wachstumsqualität, Neubewertung von Erwartungen usw.
- Unterstützt Aufrufe von Echtzeit-Kursdaten, K-Linien, technischen Indikatoren, Nachrichten und Risikoinformationen
- Unterstützt mehrere Nachfragerunden, Sitzungsexport, Versand an Benachrichtigungskanäle und Hintergrundausführung
- Unterstützt benutzerdefinierte Strategiedateien und Multi-Agent-Orchestrierung (experimentell)

> Agent-spezifische Parameter, `skill`-Namenskompatibilität, Multi-Agent-Modus und Budget-Schutzschranken siehe [Vollständiger Leitfaden](docs/full-guide.md#lokale-webui-verwaltungsoberfläche) und [LLM-Konfigurationsleitfaden](docs/LLM_CONFIG_GUIDE.md).

## 🧩 Verwandte Projekte (Related Projects)

> DSA fokussiert sich auf tägliche Analyseberichte; die integrierte Aktienauswahl orientiert sich an AlphaSift, AlphaEvo dient der Strategievalidierung und -evolution.

| Projekt | Positionierung |
|------|------|
| [AlphaSift](https://github.com/ZhuLinsen/alphasift) | Referenzprojekt für den integrierten Aktienauswahl-Engine von DSA |
| [AlphaEvo](https://github.com/ZhuLinsen/alphaevo) | Strategie-Backtest und Selbst-Evolution; dient der Validierung von Strategieregeln und der iterativen Erkundung von Strategieparametern und -kombinationen |

## 📬 Kontakt und Kooperation

<table>
  <tr>
    <td width="92" valign="top"><strong>Kooperations-E-Mail</strong></td>
    <td valign="top">
      <a href="mailto:zhuls345@gmail.com">zhuls345@gmail.com</a><br>
      Projektanfragen, Bereitstellungsunterstützung und Funktionserweiterungen
    </td>
    <td align="center" rowspan="3" valign="middle" width="148">
      <a href="http://xhslink.com/m/tU520DWCKT" target="_blank"><img src="./docs/assets/xiaohongshu_tick.jpg" width="112" alt="Xiaohongshu-QR-Code"></a><br>
      <sub>Scannen und Xiaohongshu folgen</sub>
    </td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>Xiaohongshu</strong></td>
    <td valign="top"><a href="http://xhslink.com/m/tU520DWCKT">Willkommen, folge uns auf Xiaohongshu</a></td>
  </tr>
  <tr>
    <td width="92" valign="top"><strong>Problemfeedback</strong></td>
    <td valign="top"><a href="https://github.com/ZhuLinsen/daily_stock_analysis/issues">Issue einreichen</a></td>
  </tr>
</table>

## 📄 Lizenz

[MIT License](LICENSE) © 2026 ZhuLinsen

Wir freuen uns, wenn bei Weiterentwicklungen oder Verweisen die Quelle dieses Repositories angegeben wird. Danke für deine Unterstützung der kontinuierlichen Pflege des Projekts.

## ⚠️ Haftungsausschluss

Dieses Projekt dient ausschließlich Lern- und Forschungszwecken und stellt keine Anlageberatung dar. Der Aktienmarkt birgt Risiken; Investitionen erfordern Vorsicht. Der Autor übernimmt keine Haftung für Verluste, die durch die Verwendung dieses Projekts entstehen.

---
