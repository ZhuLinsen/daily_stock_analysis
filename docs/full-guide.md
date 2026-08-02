# 📖 Vollständiger Konfigurations- und Bereitstellungsleitfaden

Dieses Dokument enthält die vollständige Konfigurationsanleitung für das intelligente A-Aktien-Analysesystem und richtet sich an Nutzer, die erweiterte Funktionen oder spezielle Bereitstellungsmethoden benötigen.

> 💡 Für den Schnellstart siehe [README.md](../README.md); dieses Dokument behandelt die erweiterte Konfiguration.

## 📁 Projektstruktur

```
daily_stock_analysis/
├── main.py              # Haupteinstiegspunkt
├── src/                 # Kern-Geschäftslogik
│   ├── analyzer.py      # KI-Analysator
│   ├── config.py        # Konfigurationsverwaltung
│   ├── notification.py  # Nachrichten-Push
│   └── ...
├── data_provider/       # Mehrfach-Datenquellen-Adapter
├── bot/                 # Bot-Interaktionsmodul
├── api/                 # FastAPI-Backend-Dienst
├── apps/dsa-web/        # React-Frontend
├── docker/              # Docker-Konfiguration
├── docs/                # Projektdokumentation
└── .github/workflows/   # GitHub Actions
```

## 📑 Inhaltsverzeichnis

- [Projektstruktur](#projektstruktur)
- [Detaillierte GitHub-Actions-Konfiguration](#detaillierte-github-actions-konfiguration)
- [Vollständige Liste der Umgebungsvariablen](#vollständige-liste-der-umgebungsvariablen)
- [Docker-Bereitstellung](#docker-bereitstellung)
- [Detaillierte lokale Ausführungskonfiguration](#detaillierte-lokale-ausführungskonfiguration)
- [Konfiguration geplanter Tasks](#konfiguration-geplanter-tasks)
- [Detaillierte Konfiguration der Benachrichtigungskanäle](#detaillierte-konfiguration-der-benachrichtigungskanäle)
- [Datenquellen-Konfiguration](#datenquellen-konfiguration)
- [Erweiterte Funktionen](#erweiterte-funktionen)
- [Backtest-Funktion](#backtest-funktion)
- [Lokale WebUI-Verwaltungsoberfläche](#lokale-webui-verwaltungsoberfläche)

---

## Detaillierte GitHub-Actions-Konfiguration

### 1. Forke dieses Repository

Klicke oben rechts auf den Button `Fork`

### 2. Konfiguriere die Secrets

Rufe dein geforktes Repository auf → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

<div align="center">
  <img src="assets/secret_config.png" alt="Schematische Darstellung der GitHub-Secrets-Konfiguration" width="600">
</div>

#### KI-Modell-Konfiguration (mindestens eines konfigurieren)

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC) API-Key: Ein Key aktiviert zugleich das große Sprachmodell und die für Chinesisch optimierte Websuche, inklusive kostenlosem Kontingent für dieses Projekt | Empfohlen |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API-Key: Ein Key für die gesamte Modellfamilie; für dieses Projekt 10 % Rabatt möglich | Empfohlen |
| `GEMINI_API_KEY` | Kostenloser Key von [Google AI Studio](https://aistudio.google.com/) | Optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API-Key | Optional |
| `OPENAI_API_KEY` | OpenAI-kompatibler API-Key (unterstützt DeepSeek, Tongyi Qianwen usw.) | Optional |
| `OPENAI_BASE_URL` | OpenAI-kompatible API-Adresse (z. B. `https://api.deepseek.com`) | Optional |
| `OPENAI_MODEL` | Modellname (z. B. `gemini-3.1-pro-preview`, `deepseek-v4-flash`, `gpt-5.5`) | Optional |

> *Hinweis: Mindestens einer der oben genannten Modell-Keys/Kanäle muss konfiguriert sein; empfohlen wird, mit einem Multi-Modell-Dienst wie Anspire oder AIHubMix zu beginnen. Beim Start gibt die Konfigurationsprüfung eine eindeutige Fehlermeldung aus, wenn ein KI-Modell-Key oder ein Modellkanal fehlt.

#### Konfiguration der Benachrichtigungskanäle (mehrere gleichzeitig möglich, alle pushen)

> Die Detail-Ebenen von Benachrichtigungskanälen, minimal/advanced Keys, Actions-Zuordnung, `--check-notify`-Diagnose, Web-Ein-Klick-Test sowie die Szenarien lokal / Docker / GitHub Actions / Desktop siehe [Benachrichtigungs-Dokument](notifications.md).

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `WECHAT_WEBHOOK_URL` | WeCom-Webhook-URL | Optional |
| `FEISHU_WEBHOOK_URL` | Feishu-Webhook-URL | Optional |
| `FEISHU_WEBHOOK_SECRET` | Feishu-Webhook-Signaturschlüssel (erforderlich, wenn „Signaturprüfung“ aktiviert ist) | Optional |
| `FEISHU_WEBHOOK_KEYWORD` | Feishu-Webhook-Keyword (erforderlich, wenn „Keyword“ aktiviert ist) | Optional |
| `DINGTALK_WEBHOOK_URL` | DingTalk-Gruppenroboter-Webhook-URL | Optional |
| `DINGTALK_SECRET` | DingTalk-Gruppenroboter-Signaturschlüssel (beginnt mit SEC) | Optional |
| `TELEGRAM_BOT_TOKEN` | Telegram-Bot-Token (von @BotFather erhalten) | Optional |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | Optional |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram-Topic-ID (zum Senden in Unterthemen) | Optional |
| `DISCORD_WEBHOOK_URL` | Discord-Webhook-URL ([Erstellungsmethode](https://support.discord.com/hc/en-us/articles/228383668)) | Optional |
| `DISCORD_BOT_TOKEN` | Discord-Bot-Token (entweder Bot oder Webhook) | Optional |
| `DISCORD_MAIN_CHANNEL_ID` | Discord-Kanal-ID (bei Verwendung des Bots erforderlich) | Optional |
| `DISCORD_INTERACTIONS_PUBLIC_KEY` | Discord-Public-Key (nur zur Signaturprüfung eingehender Interaction/Webhook-Callbacks erforderlich) | Optional |
| `SLACK_BOT_TOKEN` | Slack-Bot-Token (empfohlen, unterstützt Bild-Upload; hat Vorrang vor dem Webhook, wenn beides konfiguriert ist) | Optional |
| `SLACK_CHANNEL_ID` | Slack-Kanal-ID (bei Verwendung des Bots erforderlich) | Optional |
| `SLACK_WEBHOOK_URL` | Slack-Incoming-Webhook-URL (nur Text, keine Bilder) | Optional |
| `EMAIL_SENDER` | Absender-E-Mail (z. B. `xxx@qq.com`) | Optional |
| `EMAIL_PASSWORD` | E-Mail-Autorisierungscode (nicht das Anmeldepasswort) | Optional |
| `EMAIL_RECEIVERS` | Empfänger-E-Mail (mehrere per Komma getrennt; leer = an sich selbst senden) | Optional |
| `EMAIL_SENDER_NAME` | Anzeigename des Absenders (Standard: daily_stock_analysis-Aktienanalyseassistent) | Optional |
| `PUSHPLUS_TOKEN` | PushPlus-Token ([Bezugsadresse](https://www.pushplus.plus), inländischer Push-Dienst) | Optional |
| `SERVERCHAN3_SENDKEY` | ServerChan³-Sendkey ([Bezugsadresse](https://sc3.ft07.com/), Push-Dienst für mobile Apps) | Optional |
| `ASTRBOT_URL` | AstrBot-Webhook-URL | Optional |
| `ASTRBOT_TOKEN` | AstrBot-Bearer-Token (optional) | Optional |
| `NTFY_URL` | ntfy vollständiger Topic-Endpoint, muss den Topic-Pfad enthalten, z. B. `https://ntfy.sh/my-topic` | Optional |
| `NTFY_TOKEN` | ntfy-Bearer-Token (optional) | Optional |
| `GOTIFY_URL` | Gotify-Server-Basis-URL, ohne `/message`; das System fügt `/message` automatisch an | Optional |
| `GOTIFY_TOKEN` | Gotify-Anwendungstoken, wird über den `X-Gotify-Key`-Header gesendet | Optional |
| `CUSTOM_WEBHOOK_URLS` | Benutzerdefinierte Webhooks (unterstützt DingTalk usw., mehrere per Komma getrennt) | Optional |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | Bearer-Token für benutzerdefinierte Webhooks (für Webhooks, die eine Authentifizierung benötigen) | Optional |
| `CUSTOM_WEBHOOK_BODY_TEMPLATE` | JSON-Body-Vorlage für benutzerdefinierte Webhooks, für spezielle Payloads wie AstrBot, NapCat, selbst gehostete Dienste usw. | Optional |
| `WEBHOOK_VERIFY_SSL` | Zertifikatsprüfung für webhook-artige HTTPS-Benachrichtigungsanfragen, die diese Konfiguration lesen (Standard true). Mit false werden selbstsignierte Zertifikate unterstützt. Warnung: Das Deaktivieren birgt ernste Sicherheitsrisiken (MITM), nur in vertrauenswürdigen internen Netzen | Optional |

> *Hinweis: Mindestens einen Kanal konfigurieren; sind mehrere konfiguriert, wird in alle gepusht. Die Konfigurationsprüfung beim Start weist auf fehlende zusammengehörige Telegram-/E-Mail-Felder hin sowie darauf, dass gängige Webhook-URLs nicht mit `http://` oder `https://` beginnen.
>
> Der aktuelle Standard-Workflow `00-daily-analysis.yml` mappt nur feste Secret-/Variable-Namen und importiert beliebig nummerierte Variablen wie `STOCK_GROUP_1`, `EMAIL_GROUP_1` nicht automatisch in die Laufzeitumgebung; auch neu hinzugefügte optionale Schalter wie `NEWS_INTEL_AUTO_FETCH_ENABLED` werden nicht automatisch importiert. Die Gruppen-E-Mail-Funktion und die lokale Nachrichten-Autovervollständigung sind daher derzeit nicht für den mitgelieferten Standard-GitHub-Actions-Workflow geeignet; sie gelten für lokale `.env`, Docker oder Laufzeitumgebungen, in denen die `env:`-Zuordnung selbst explizit erweitert wurde. Die Actions haben bereits `CUSTOM_WEBHOOK_BODY_TEMPLATE`, `WEBHOOK_VERIFY_SSL`, `FEISHU_WEBHOOK_SECRET`, `FEISHU_WEBHOOK_KEYWORD`, `PUSHPLUS_TOPIC`, `NTFY_URL`, `NTFY_TOKEN`, `GOTIFY_URL`, `GOTIFY_TOKEN`, die P3-Benachrichtigungs-Routingkeys sowie die P4-Entrauschungskey für Benachrichtigungen explizit gemappt; `MARKDOWN_TO_IMAGE_CHANNELS` und `MERGE_EMAIL_NOTIFICATION` bleiben als Verhaltensschalter bestehen und werden im Standard-Workflow nicht automatisch gemappt.

#### Konfiguration des Push-Verhaltens

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `SINGLE_STOCK_NOTIFY` | Einzelaktien-Push-Modus: mit `true` wird nach jeder analysierten Aktie sofort gepusht | Optional |
| `REPORT_TYPE` | Berichtstyp: `simple` (kompakt), `full` (vollständig), `brief` (3-5-Sätze-Zusammenfassung); in Docker-Umgebungen wird `full` empfohlen | Optional |
| `REPORT_LANGUAGE` | Standardausgabesprache für Berichte und Agent Chat: `zh` (Standard: Chinesisch) / `en` (Englisch) / `ko` (Koreanisch); wirkt sich auch auf Prompts, Vorlagen, Benachrichtigungs-Fallbacks, feste Texte der Web-Berichtsseite und Aktienfragen-Antworten ohne explizit übergebenes `context.report_language` aus. `ko` nutzt das englische Strukturgerüst und weist das Modell über die Ausgabesprach-Anweisung an, auf Koreanisch auszugeben; Benachrichtigungen rendern lokalisierte Labels nach Berichtssprache. Das mitgelieferte `00-daily-analysis.yml` hat diese Variable bereits explizit gemappt; direkt in den Actions Secrets/Variables konfigurieren, um sie zu aktivieren | Optional |
| `REPORT_SUMMARY_ONLY` | Nur Analyse-Zusammenfassung: mit `true` wird nur die Zusammenfassung gepusht, ohne Einzelaktien-Details; bei mehreren Aktien für einen schnellen Überblick geeignet (Standard false, Issue #262) | Optional |
| `REPORT_SHOW_LLM_MODEL` | Ob am Ende des Benachrichtigungsberichts der Name des in dieser Analyse verwendeten LLM-Modells angezeigt wird, Standard `true`; mit `false` werden Laufzeit-Modellinformationen ausgeblendet. Diese Variable beeinflusst nur die Anzeige, nicht die Semantik von provider/model/Base URL, LiteLLM-Routing oder das Speichern/Migrieren/Bereinigen von Laufzeitmodellen. | Optional |
| `REPORT_TEMPLATES_DIR` | Jinja2-Vorlagenverzeichnis (relativ zum Projektstamm, Standard `templates`) | Optional |
| `REPORT_RENDERER_ENABLED` | Jinja2-Vorlagen-Rendering aktivieren (Standard `false`, gewährleistet null Regression) | Optional |
| `REPORT_INTEGRITY_ENABLED` | Integritätsprüfung des Berichts aktivieren; bei fehlenden Pflichtfeldern wird erneut versucht oder mit Platzhaltern ergänzt (Standard `true`) | Optional |
| `REPORT_INTEGRITY_RETRY` | Anzahl der Wiederholungen der Integritätsprüfung (Standard `1`, `0` bedeutet nur Platzhalter ohne Wiederholung) | Optional |
| `REPORT_HISTORY_COMPARE_N` | Anzahl vergleichbarer historischer Signale; `0` deaktiviert (Standard), `>0` aktiviert | Optional |
| `ANALYSIS_DELAY` | Verzögerung (Sekunden) zwischen Einzelaktien- und Marktanalyse, um API-Limits zu vermeiden, z. B. `10` | Optional |
| `SAVE_CONTEXT_SNAPSHOT` | Ob der Analyseverlauf `context_snapshot` gespeichert wird, Standard `true`; mit `false` oder `--no-context-snapshot` wird keine vollständige Kontext-Snapshot persistiert | Optional |
| `MERGE_EMAIL_NOTIFICATION` | Zusammengeführter Push von Einzelaktien- und Markt-Rückblick (Standard false), reduziert die Anzahl der E-Mails und das Spam-Risiko; schließt sich mit `SINGLE_STOCK_NOTIFY` gegenseitig aus (in Einzelaktien-Modus greift die Zusammenführung nicht) | Optional |
| `MARKDOWN_TO_IMAGE_CHANNELS` | Kanäle, die Markdown in Bilder umwandeln und senden (per Komma getrennt): telegram,wechat,custom,email,slack; für Einzelaktien-Push müssen zudem die Bildkonvertierungswerkzeuge installiert sein | Optional |
| `NOTIFICATION_REPORT_CHANNELS` | report-Routing-Kanäle (Einzelaktien-Push, aggregierter Tagesbericht, Markt-Rückblick, zusammengeführte Pushs usw.); leer bedeutet alle konfigurierten Kanäle | Optional |
| `NOTIFICATION_ALERT_CHANNELS` | alert-Routing-Kanäle (EventMonitor-Warnungen); leer bedeutet alle konfigurierten Kanäle | Optional |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | reservierte system_error-Routing-Kanäle; derzeit werden keine automatischen Systemfehler-Produzenten hinzugefügt, leer bedeutet alle konfigurierten Kanäle | Optional |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | TTL-Sekunden für die Benachrichtigungs-Deduplizierung, `0` deaktiviert; derselbe stabile Dedup-Key wird innerhalb der TTL nur einmal gesendet | Optional |
| `NOTIFICATION_COOLDOWN_SECONDS` | Benachrichtigungs-Cooldown in Sekunden, `0` deaktiviert; derselbe Cooldown-Key wird innerhalb des Fensters gedrosselt | Optional |
| `NOTIFICATION_QUIET_HOURS` | Stillezeitraum für Benachrichtigungen, Format `HH:MM-HH:MM`, unterstützt über Mitternacht; leer deaktiviert | Optional |
| `NOTIFICATION_TIMEZONE` | IANA-Zeitzone für den Stillezeitraum, z. B. `Asia/Shanghai`; leer folgt `TZ` oder der System-Zeitzone | Optional |
| `NOTIFICATION_MIN_SEVERITY` | Mindest-Schweregrad der Benachrichtigung: `info`, `warning`, `error`, `critical`; leer behält den aktuellen Zustand | Optional |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | reservierter Schalter für die tägliche Zusammenfassung; derzeit werden keine Zusammenfassungen gesendet oder Inhalte persistiert | Optional |
| `MARKDOWN_TO_IMAGE_MAX_CHARS` | Über dieser Länge wird nicht in Bilder umgewandelt, um übergroße Bilder zu vermeiden (Standard 15000) | Optional |
| `MD2IMG_ENGINE` | Bildkonvertierungs-Engine: `wkhtmltoimage` (Standard, benötigt wkhtmltopdf) oder `markdown-to-file` (bessere Emoji-Darstellung, benötigt `npm i -g markdown-to-file`) | Optional |
| `PREFETCH_REALTIME_QUOTES` | Mit `false` kann der Echtzeit-Kursabruf deaktiviert werden, um efinance/akshare_em-Gesamtmarkt-Abrufe zu vermeiden (Standard true) | Optional |

> Kompatibilitätshinweis: `REPORT_SHOW_LLM_MODEL` behält die ursprüngliche Anzeigesemantik mit Standard `true`; wenn deaktiviert, betrifft das nur die Modelltextzeile am Ende. Diese Konfiguration ändert nicht die Semantik von provider/model/Base URL, LiteLLM-Routing, Modellspeicherung, -migration oder -bereinigung; als Rückfall gilt, die Variable wiederherzustellen oder zu entfernen und auf `true` zu setzen.

> Hinweis: `REPORT_LANGUAGE` beeinflusst Berichtstexte, feste Texte der Web-Berichtsseite und Agent-Chat-Antworten ohne explizit angegebene Sprache; die WebUI-Seitensprache (Navigation, Login-Seite, Seitenleiste, Einstellungsseite, allgemeine Steuerelemente) verwendet einen unabhängigen Zustand und ist nicht damit verknüpft.
> Der WebUI-Sprachzustand wird im Browser-`localStorage` unter `dsa.uiLanguage` gespeichert; die Startreihenfolge ist:
> 1) Explizite Auswahl (`localStorage.dsa.uiLanguage`, nur `zh`/`en` unterstützt)
> 2) Browser-Spracherkennung (`navigator.languages` / `navigator.language`, `zh-*` oder `en-*`)
> 3) Standard-Rückfall `zh`.

#### Weitere Konfiguration

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `STOCK_LIST` | Watchlist-Codes, z. B. `600519,300750,002594,7203.T,005930.KS`; englische Kommas werden empfohlen; chinesische Kommas, Aufzählungszeichen, Semikolons, Leerzeichen und Zeilenumbrüche werden erkannt und zu englischen Kommas normalisiert | ✅ |
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/) ist für chinesische Inhalte besonders optimiert; derselbe Key kann als Fallback-Beispiel für Suche und Anspire-Großmodell-Gateway dienen (die Verfügbarkeit richtet sich nach Konsole und Kontoberechtigungen) | Empfohlen |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) Verstärkung der Suchmaschinenergebnisse, geeignet für Echtzeit-Finanznachrichten | Empfohlen |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/)-Such-API (Nachrichtensuche) | Optional |
| `BOCHA_API_KEYS` | [Bocha Search](https://open.bocha.cn/) Web-Search-API (für Chinesisch optimiert, unterstützt KI-Zusammenfassungen, mehrere Keys per Komma getrennt) | Optional |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/)-API (datenschutzorientiert, für US-Aktien optimiert, mehrere Keys per Komma getrennt) | Optional |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimax.io/) Coding Plan Web Search (strukturierte Suchergebnisse) | Optional |
| `SEARXNG_BASE_URLS` | Selbst gehostete SearXNG-Instanz (ohne Quoten-Fallback, erfordert `format: json` in settings.yml); leer erkennt automatisch öffentliche Instanzen | Optional |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Ob bei leerem `SEARXNG_BASE_URLS` automatisch öffentliche Instanzen von `searx.space` bezogen werden (Standard `true`) | Optional |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) Token | Optional |
| `TUSHARE_HTTP_URL` | Tushare-Pro-HTTP-Adresse; leer (oder nicht gesetzt/blank) wird der offizielle Endpoint `http://api.tushare.pro` verwendet; nur bei Firmen-Proxy, grenzüberschreitendem Netzwerk oder eigenem Mirror eine vollständige `http://`- oder `https://`-Adresse angeben | Optional |
| `TICKFLOW_API_KEY` | [TickFlow](https://tickflow.org)-API-Key; optional für A-Aktien-Tages-K, Echtzeit-Kurse, Aktienlisten/-namen und Markt-Rückblick-Erweiterung; bei Fehlern oder fehlenden Berechtigungen automatischer Rückfall. | Optional |
| `LONGBRIDGE_OAUTH_CLIENT_ID` | [Longbridge OpenAPI](https://open.longbridge.com/) OAuth client_id; leer und ohne Legacy-Access-Token wird kompatibel `LONGBRIDGE_APP_KEY` verwendet | Optional |
| `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` | Base64-Inhalt der OAuth-Token-Cache-Datei, um den SDK-Token-Cache in headless Umgebungen wie GitHub Actions / Docker wiederherzustellen | Optional |
| `LONGBRIDGE_APP_KEY` | Longbridge Legacy App Key; ohne `LONGBRIDGE_ACCESS_TOKEN` auch als kompatibles Alias für OAuth client_id nutzbar | Optional |
| `LONGBRIDGE_APP_SECRET` | Longbridge App Secret | Optional |
| `LONGBRIDGE_ACCESS_TOKEN` | Longbridge Legacy Access Token (kein OAuth-Access-Token) | Optional |
| `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` | Sekunden für den prozessinternen Cache von Longbridge `static_info` (Standard 86400, 0 = kein Cache) | Optional |
| `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` | Cooldown-Sekunden nach Longbridge-Verbindungsfehlern (Standard 15; während des Cooldowns wird Longbridge vorübergehend übersprungen, um häufige Neuverbindungen zu vermeiden) | Optional |
| `LONGBRIDGE_HTTP_URL` | HTTP-API-Adresse (Standard `https://openapi.longbridge.com`) | Optional |
| `LONGBRIDGE_QUOTE_WS_URL` | Kurs-WebSocket-Adresse (Standard `wss://openapi-quote.longbridge.com/v2`) | Optional |
| `LONGBRIDGE_TRADE_WS_URL` | Handels-WebSocket-Adresse (Standard `wss://openapi-trade.longbridge.com/v2`) | Optional |
| `LONGBRIDGE_REGION` | Überschreibt den Zugangspunkt; das SDK wählt automatisch je nach Netzwerk, Standard `hk`, bei falscher Erkennung einstellbar (z. B. `cn`, `hk`) | Optional |
| `LONGBRIDGE_ENABLE_OVERNIGHT` | Ob der Nachthandels-Kursverlauf `true`/`false` aktiviert ist, Standard `false` | Optional |
| `LONGBRIDGE_PUSH_CANDLESTICK_MODE` | K-Linien-Push-Modus: `realtime` oder `confirmed` (Standard `realtime`) | Optional |
| `LONGBRIDGE_PRINT_QUOTE_PACKAGES` | Ob beim Verbinden Kurs-Pakete ausgegeben werden (Standard `false`, wenn nicht gesetzt; mit `1`/`true`/`yes` aktivieren) | Optional |
| `ENABLE_CHIP_DISTRIBUTION` | Chip-Verteilung aktivieren (Actions Standard false; bei Bedarf in den Variables auf true setzen, die Schnittstelle kann instabil sein) | Optional |

> **GitHub Actions:** Das mitgelieferte `00-daily-analysis.yml` hat `TUSHARE_TOKEN`, `TICKFLOW_API_KEY` / `TICKFLOW_*` sowie die `LONGBRIDGE_*`-Einträge der obigen Tabelle bereits auf die Task-Umgebung gemappt. Der API-Key von TickFlow sollte in den **Secrets** liegen; Priorität, Rechte und Batch-Schalter können in den **Variables** oder **Secrets** liegen. Die Longbridge-OAuth-Methode benötigt eine client_id (bevorzugt `LONGBRIDGE_OAUTH_CLIENT_ID`; leer und ohne Legacy-Access-Token wird kompatibel `LONGBRIDGE_APP_KEY` verwendet) und die lokale Datei `~/.longbridge/openapi/tokens/<client_id>` muss base64-kodiert als Secret `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` gespeichert werden; die Legacy-Methode kann weiterhin `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN` konfigurieren. Optionale Zugangspunktvariablen (z. B. `LONGBRIDGE_REGION`) können in den **Variables** oder **Secrets** liegen.

> **TUSHARE_HTTP_URL-Zuordnung im täglichen Workflow:** `00-daily-analysis.yml` hat `TUSHARE_HTTP_URL` bereits explizit gemappt (mit `vars.TUSHARE_HTTP_URL || secrets.TUSHARE_HTTP_URL`-Priorität, identisch zur Wertungsstrategie bestehender nicht-sensitiver Konfigurationen wie `TICKFLOW_PRIORITY`). Diese Adresse ist eine „Zugangsadresse“-Konfiguration und keine Anmeldedaten; es wird empfohlen, sie in den **Variables** zu platzieren, damit das Team sie reviewen und versionieren kann. Beachte: Die tatsächliche Priorität lautet „ein nicht leerer vars-Wert gewinnt“; **gleichnamige Variablen in den Secrets können nicht-leere Variables nicht überschreiben**. Nur wenn vars leer ist, werden secrets verwendet — modelliere deine Sicherheit nach dieser tatsächlichen Semantik. GitHub gestaltet Variables und Secrets als zwei unabhängige Schreibberechtigungsmodelle: Jede Person oder Automatisierung mit Schreibberechtigung für die Repository-Variables kann ohne Lesen oder Ändern der Secrets durch Setzen einer nicht-leeren Variable den Laufzeit-Endpoint umschreiben (einschließlich der Umleitung von `TUSHARE_TOKEN` und des vollständigen Request-Bodys auf eine von Angreifern kontrollierte Adresse); Secrets schützen nur die Vertraulichkeit der Werte und bieten automatisch weder „Endpoint-Integrität“ noch „Prioritäts-Override“. Wenn tatsächlich eine stärkere Zugriffskontrolle für Endpoints nötig ist, nutze GitHub Environment protection rules, CODEOWNERS, branch protection oder einen separaten Deployment-Genehmigungsprozess — **behandle „nur Secrets, Variables leer“ nicht als Schutzschild gegen Änderungen**. Ohne Setzung oder bei leerem Wert verwendet der Fetcher weiterhin den offiziellen `http://api.tushare.pro`-Endpoint und meldet keinen Fehler wegen fehlender Variable.

> **Longbridge-Laufzeitverhalten:** Ohne konfigurierte Anmeldedaten wird dieser optionale Fetcher nicht instanziiert; treten zur Laufzeit Verbindungsfehler wie `client is closed`, `context closed`, `connection closed` auf, wird ein Cooldown gestartet (Standard 15 Sekunden, über `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` einstellbar). Während des Cooldowns werden Echtzeit- und Tagesanfragen für US-/Hongkong-Aktien automatisch Longbridge überspringen und auf Fallback-Pfade wie YFinance / AkShare zurückgreifen.

> Ergänzende Hinweise
- Bei `TUSHARE_TOKEN`: Wenn dieser Parameter konfiguriert ist, aber keine Berechtigung für die Hongkong-Aktien-Tagesdaten-Schnittstelle besteht, können Hongkong-Aktien-Daten nicht abgefragt werden oder es treten Fehler auf — derselbe Effekt wie die alte Version, die Hongkong-Aktien als nicht unterstützt meldet

#### ✅ Minimales Konfigurationsbeispiel

Für einen schnellen Start müssen mindestens die folgenden Punkte konfiguriert werden:

1. **KI-Modell**: `ANSPIRE_API_KEYS` (ein Key aktiviert zugleich Modell und Suche), `AIHUBMIX_KEY` ([AIHubmix](https://aihubmix.com/?aff=CfMq), ein Key für mehrere Modelle), `GEMINI_API_KEY` oder `OPENAI_API_KEY`
2. **Benachrichtigungskanal**: mindestens einen konfigurieren, z. B. `WECHAT_WEBHOOK_URL` oder `EMAIL_SENDER` + `EMAIL_PASSWORD`
3. **Aktienliste**: `STOCK_LIST` (Pflicht)
4. **Such-API**: `ANSPIRE_API_KEYS` oder `SERPAPI_API_KEYS` (empfohlen für Nachrichten- und Stimmungsabruf)

> 💡 Nach der Konfiguration der oben genannten 4 Punkte kann es losgehen!

### 3. Actions aktivieren

1. Rufe das geforkte Repository auf
2. Klicke oben auf den Tab `Actions`
3. Wenn ein Hinweis erscheint, klicke auf `I understand my workflows, go ahead and enable them`

### 4. Manueller Test

1. Öffne den Tab `Actions`
2. Wähle links den Workflow `Tägliche Aktienanalyse`
3. Klicke rechts auf die Schaltfläche `Run workflow`
4. Wähle den Ausführungsmodus
5. Klicke zur Bestätigung auf das grüne `Run workflow`

### 5. Fertig!

Standardmäßig wird automatisch an jedem Werktag um **18:00 Uhr (Pekinger Zeit)** ausgeführt.

---

## Vollständige Liste der Umgebungsvariablen

### KI-Modell-Konfiguration

> Vollständige Erläuterungen siehe [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md) (Drei-Ebenen-Konfiguration, Kanalmodus, Vision, Agent, Fehlerbehebung); gängige Provider-Presets, Actions-Variablen-Vergleich und Fehlerbehebung siehe [LLM-Provider-Konfigurationsleitfaden](llm-providers.md).
> Kompatibilitätshinweis (Issue #1306/#1391, bestätigt zusätzlich #1381): Die Änderungen dieses Abschnitts nutzen nur die vorhandene Verlaufsschreibkette zur Darstellung der Markt-Rückblick-Ergebnisse; es werden keine API/API-Parameter hinzugefügt, keine unabhängige Anzeige der Web-Phasenergebnisse, keine strukturierte Persistenz des vierstufigen Tagesberichts und keine Status-Tabelle des Tagesberichts eingeführt; das Laufzeit-Routing von `provider`/`model`/`base_url` und das Standardmodellverhalten bleiben unverändert. #1381 ist ebenfalls nur eine Backend-Runtime-Wiederverwendung ohne neue Konfigurations-Migrations-/Bereinigungs-/Rückschreibzweige. Falls die strukturierte API/Web/Tagesbericht-Abnahme von Issue #1381 nicht zeitgleich umgesetzt wird, sollte dieser PR nicht als vollständige Auslieferung gelten, sondern in einem Folge-PR weiter ausgeliefert werden. Der Rückfallweg ist ein Release-Rollback (direkt den aktuellen Commit reverten oder der bestehenden Konfigurations-Rollback-Kette folgen). Die Kompatibilitätsprüfung nutzt hauptsächlich die bestehenden Constraint-Checks (`requirements.txt`: `litellm`-Versionsbeschränkung) und bestehende Konfigurations-Regressionstests: `tests/test_system_config_service.py`, `tests/test_system_config_api.py`, `tests/test_llm_channel_config.py`, `tests/test_market_review_runtime.py`; offizielle Quellen: [LiteLLM OpenAI-compatible](https://docs.litellm.ai/docs/providers/openai_compatible), [OpenAI Chat Completion API](https://platform.openai.com/docs/api-reference/chat).
> Das Strukturprüfungsrisiko von #1391 Phase 2 stammt aus den int-Sicherheitsfallbacks `agent_max_steps`/`agent_orchestrator_timeout_s` in `src/agent/factory.py`; es ist eine typkompatible Verstärkung auf der Konfigurationsleseseite und ändert nicht den Routing-Zustand von `litellm_model`, `agent_litellm_model`, `openai_base_url` oder `LLM_*`. Für die Regression siehe `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_does_not_mutate_llm_route_config` und `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_multi_arch_does_not_mutate_llm_route_config`. Bei ungültigen Konfigurationswerten (z. B. nicht numerisch) protokolliert `src.agent.factory` eine Warning und fällt auf den Standardwert zurück, um die Fehlersuche zu erleichtern und fälschlich als aktiv interpretierte Konfigurationen zu vermeiden.
> Kompatibilitätsgrenzen von #1815 Phase 3: In dieser Runde werden nur die Servicegrenzen von JP/KR und Market Light konsolidiert; es wird keine LLM provider/model/base_url-Migrationslogik hinzugefügt und die Persistenzsemantik des `.env`-Hauptroutingsmodells bleibt unverändert. `MarketSymbol`, die Warnungs-Enums und die Anpassungen an `data_quality/limitations` der Snapshot werden gemäß der bestehenden atomaren `.env`-Upsert-Semantik in die gespeicherte Konfiguration geschrieben; nicht explizit übermittelte Schlüssel werden nicht geleert.
> Dieser Abschnitt synchronisiert nur die Modell-/Kanal-Konfigurationsliste und führt keine neuen Kompatibilitätskonventionen für externe Provider / Base URLs ein; die Kompatibilitätssemantik richtet sich nach den Abhängigkeitsbeschränkungen in `requirements.txt` und den zugehörigen Tests; historische Rückfallpfade siehe die Abschnitte „Rückfall/Wiederherstellung“ in den beiden oben genannten Dokumenten.

| Variable | Beschreibung | Standardwert | Pflicht |
|--------|------|--------|:----:|
| `GENERATION_BACKEND` | Backend für die normale Analysegenerierung; unterstützt `litellm` oder explizit opt-in `codex_cli`/`claude_code_cli`/`opencode_cli` (experimental/limited) | `litellm` | Nein |
| `OPENCODE_CLI_MODEL` | Optionale Modell-Überschreibung für OpenCode `--model`, wenn `GENERATION_BACKEND=opencode_cli`; leer verwendet das lokale OpenCode-Standardmodell, Authentifizierung und Modellverfügbarkeit übernimmt die lokale OpenCode-Konfiguration | leer | Nein |
| `GENERATION_FALLBACK_BACKEND` | Backend-Fallback; nicht konfiguriert ist Standard `litellm`, leerer Wert deaktiviert, Self-Fallback wird als No-op aufgelöst | `litellm` | Nein |
| `GENERATION_BACKEND_TIMEOUT_SECONDS` | Timeout in Sekunden für einen einzelnen Generation-Backend-Aufruf, hauptsächlich für lokale CLI-Backends; Bereich `1-3600` | `300` | Nein |
| `GENERATION_BACKEND_MAX_OUTPUT_BYTES` | Obergrenze für die Erfassung von stdout/stderr-Diagnose und endgültiger Antwort eines einzelnen lokalen CLI-Backend-Aufrufs; die durch `--output-last-message` wiederholt auf stdout gedruckte endgültige Antwort wird nicht erneut angerechnet; Bereich `1-33554432` | `1048576` | Nein |
| `GENERATION_BACKEND_MAX_CONCURRENCY` | Globale Obergrenze für Generation-Backend-Nebenläufigkeit; Bereich `1-16`, ändert nicht das Verhalten von LiteLLM Router / `MAX_WORKERS` | `1` | Nein |
| `LOCAL_CLI_BACKEND_MAX_CONCURRENCY` | Nebenläufigkeitsgrenze für lokale CLI-Backends; Bereich `1-4`, die effektive Nebenläufigkeit ist der kleinere Wert aus ihr und `GENERATION_BACKEND_MAX_CONCURRENCY` | `1` | Nein |
| `AGENT_BACKEND` | Ausführungsmodus des bestehenden Aktienfragen-Chats: `auto` (empfohlen, behält das Standardmodell), `litellm` oder `codex_app_server` (experimentell, nur Single-Agent-Chat) | `auto` | Nein |
| `AGENT_GENERATION_BACKEND` | Generation-Backend für Agent-Chat; die Web-Einstellungsseite legt nur `auto|litellm` offen, ein manuell eingetragenes lokales CLI-Backend liefert eine Diagnose für nicht unterstütztes Tool-Calling | `auto` | Nein |
| `AGENT_SKILL_CONCURRENCY` | Nebenläufigkeitsgrenze für Strategie-Experten-Worker im `specialist`-Modus, Bereich `1-4`; höchstens 4 Strategien wählbar, standardmäßig 3 parallel, die 4. geht in die nächste Charge und teilt das Gesamt-Timeout-Budget | `3` | Nein |
| `LITELLM_MODEL` | Hauptmodell, Format `provider/model` (z. B. `gemini/gemini-3.1-pro-preview`), vorzugsweise verwenden | - | Nein |
| `AGENT_LITELLM_MODEL` | Hauptmodell für den Aktienfragen-Chat mit „Standardmodell“ (optional); leer erbt das Hauptmodell, ohne Provider-Präfix wird als `openai/<model>` aufgelöst; Codex verwendet diesen Eintrag nicht | - | Nein |
| `AGENT_CONTEXT_COMPRESSION_ENABLED` | Schalter für die LLM-Kompression des sichtbaren Verlaufs im Aktienfragen-Chat mit „Standardmodell“; Codex verwendet die letzten 20 sichtbaren Konversationen und behält diese Konfiguration | `false` | Nein |
| `AGENT_CONTEXT_COMPRESSION_PROFILE` | Kompressionsstrategie für den Aktienfragen-Kontext: `cost` / `balanced` / `long_context_raw_first` | `balanced` | Nein |
| `AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS` | Kompression wird ausgelöst, wenn die geschätzte Verlaufstoken-Zahl diesen Wert überschreitet; leer folgt dem Profile-Preset | - | Nein |
| `AGENT_CONTEXT_PROTECTED_TURNS` | Bei der Kompression bleiben die letzten N Benutzerrunden und deren Antworten im Original erhalten; leer folgt dem Profile-Preset | - | Nein |
| `LITELLM_FALLBACK_MODELS` | Ersatzmodelle, per Komma getrennt | - | Nein |
| `LLM_CHANNELS` | Liste der Kanalnamen (per Komma getrennt), zusammen mit `LLM_{NAME}_*` zu verwenden, siehe [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md) | - | Nein |
| `LLM_HERMES_API_KEY` | Einzelner API-Key für die reservierte lokale HTTP-Generierung von Hermes; nur aus `.env`, Laufzeitkonfiguration oder Secrets | - | Pflicht bei Hermes-Verwendung |
| `LLM_HERMES_BASE_URL` | Lokale Loopback-`/v1`-Adresse von Hermes; Standard `http://127.0.0.1:8642/v1`, Remote-Adressen werden nicht unterstützt | `http://127.0.0.1:8642/v1` | Nein |
| `LLM_HERMES_MODELS` | Liste der Rohmodelle von Hermes; Phase-3-Standard `hermes-agent`, Laufzeit-Route `openai/hermes-agent`, keine Unterstützung für Vision / Stream / Tools / Agent-Tools | `hermes-agent` | Nein |
| `LITELLM_CONFIG` | Pfad zur YAML-Konfigurationsdatei für erweitertes Modell-Routing (erweitert) | - | Nein |
| `LLM_PROMPT_CACHE_TELEMETRY_ENABLED` | Telemetrie für Provider-Prompt-Cache-Nutzung/-Diagnosen; steuert nicht den impliziten Provider-Cache | `true` | Nein |
| `LLM_PROMPT_CACHE_HINTS_ENABLED` | Ob der Hauptanalysepfad aktiv verifizierte providerspezifische Prompt-Cache-Hints sendet; der Agent-Pfad protokolliert derzeit nur Diagnosen und sendet keine Hints; standardmäßig deaktiviert | `false` | Nein |
| `LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL` | Diagnosegrad für den Prompt-Cache: `off` / `basic` / `debug`; basic/debug liefern nur in Debug-Logs und testobservablen Objekten entschärfte Diagnosen, nicht als öffentliche Usage-API oder reguläre Einstellungsseitenausgabe | `off` | Nein |
| `LLM_USAGE_HMAC_SECRET` | HMAC-Schlüssel für Nachrichten der LLM-Nutzungstelemetrie; leer wird automatisch die lokale Schlüsseldatei im Datenverzeichnis verwendet | - | Nein |
| `LLM_USAGE_HMAC_KEY_VERSION` | Versionslabel für den HMAC-Schlüssel der LLM-Nutzungstelemetrie, bei Schlüsselrotation mit aktualisieren | `local-v1` | Nein |
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC)-API-Key: Ein Key aktiviert zugleich Großmodell-Gateway und Suche | - | Optional |
| `AIHUBMIX_KEY` | [AIHubmix](https://aihubmix.com/?aff=CfMq)-API-Key: Ein Key für die gesamte Modellfamilie, keine zusätzliche Base-URL-Konfiguration nötig | - | Optional |
| `GEMINI_API_KEY` | Google Gemini API-Key | - | Optional |
| `GEMINI_MODEL` | Name des Hauptmodells (legacy, `LITELLM_MODEL` hat Vorrang) | `gemini-3.1-pro-preview` | Nein |
| `GEMINI_MODEL_FALLBACK` | Ersatzmodell (legacy) | `gemini-3-flash-preview` | Nein |
| `OPENAI_API_KEY` | OpenAI-kompatibler API-Key | - | Optional |
| `OPENAI_BASE_URL` | OpenAI-kompatible API-Adresse | - | Optional |
| `OLLAMA_API_BASE` | Adresse des lokalen Ollama-Dienstes (z. B. `http://localhost:11434`), siehe [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md) | - | Optional |
| `OPENAI_MODEL` | OpenAI-Modellname (legacy, AIHubmix-Nutzer können z. B. `gemini-3.1-pro-preview`, `gpt-5.5` eintragen) | `gpt-5.5` | Optional |
| `ANTHROPIC_API_KEY` | Anthropic Claude API-Key | - | Optional |
| `ANTHROPIC_MODEL` | Claude-Modellname | `claude-sonnet-4-6` | Optional |
| `ANTHROPIC_TEMPERATURE` | Claude-Temperaturparameter (0.0-1.0) | `0.7` | Optional |
| `ANTHROPIC_MAX_TOKENS` | Maximale Token-Anzahl für Claude-Antworten | `8192` | Optional |

> GitHub-Actions-Hinweis: Das mitgelieferte `00-daily-analysis.yml` verwendet explizit `litellm`, wenn `GENERATION_FALLBACK_BACKEND` nicht konfiguriert ist, damit nicht gesetzte Secrets/Variables nicht als leere Werte exportiert werden und den Backend-Fallback versehentlich deaktivieren. Wenn der Backend-Fallback in Actions deaktiviert werden soll, setze den Fallback auf das primäre Backend, sodass der Resolver den Self-No-op-Weg nimmt.

> Hinweis zum Generierungs-Backend-Status: Die Schnellprüfung der Web-Einstellungsseite liest nur die gespeicherte Konfiguration und ungespeicherte Entwürfe und prüft, ob die lokalen CLI-Ausführungsdateien sichtbar sind; sie löst keine echten Modellanfragen aus. Der JSON-Smoke-Test ist eine separate explizite Aktion und sendet eine echte Anfrage mit den serverseitig festgelegten JSON-Prompts und dem Schema. `health_status` und `last_error_code/message` stehen nur für das Ergebnis dieser Statusberechnung oder dieses Smoke-Tests, nicht für einen dauerhaft gesunden Zustand.

> *Hinweis: Mindestens einer von `ANSPIRE_API_KEYS`, `AIHUBMIX_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` oder `OLLAMA_API_BASE` muss konfiguriert sein. Für `ANSPIRE_API_KEYS` und `AIHUBMIX_KEY` ist keine `OPENAI_BASE_URL` nötig; das System passt sich automatisch an.

> Der Single-Agent-Pfad des Aktienfragen-Chats speichert im Hintergrund die letzten 3 Provider-Traces für DeepSeek V4 thinking + tool-call und spielt `reasoning_content`/Tool-Ergebnisse in der ursprünglichen Reihenfolge ab; diese Fähigkeit fügt keine Konfigurationsoptionen hinzu und geht nicht in die Web-Verlaufs-API ein; Claude Extended Thinking deckt nur die Offline-Plumbing ab, die Multi-Agent-Trace-Injektion bleibt eine spätere Erweiterung.

> `AGENT_BACKEND=codex_app_server` ist ein experimenteller Einstieg, der nur den bestehenden Aktienfragen-Chat betrifft: Codex muss auf dem Gerät installiert und angemeldet sein, auf dem DSA läuft; der Web-Pfad ist „Einstellungen → Agent-Einstellungen → Generierungsmethode für Aktienfragen“, nach der Auswahl `AGENT_ARCH=single` beibehalten und ein Gesamtzeitlimit größer 0 setzen. Die Einstellungsseite prüft nur, ob Konfiguration, Codex-Befehl und benötigte Protokolle einen Versuch zulassen; sie loggt sich nicht ein, ruft keine Modelle auf und liest keine Aktiendaten. Nach dem Speichern kann direkt gefragt werden; die erste Frage ist die erste echte Ausführung. Codex kann derzeit nur gespeicherte Analysekontexte und Backtest-Zusammenfassungen lesen; für Echtzeit-Kurse, Nachrichten, Markt-Hotspots, Neuberechnung technischer Indikatoren, individuelle Backtest-Details und Positionswerkzeuge bitte das „Standardmodell“ verwenden. Nach Klick auf Stopp zeigt die Seite „Wird gestoppt“; erst wenn sowohl Codex als auch die Tool-Aufgaben dieser Runde beendet sind, erscheint das endgültige „Gestoppt“. Es unterstützt derzeit macOS, Linux und DSA-Backends, die vollständig in WSL laufen; natives Windows wird vorerst nicht unterstützt; die `codex_cli`-Generierungsfähigkeit von Phase 2 bleibt unberührt. Es unterstützt weder Codex Multi Agent noch Codex Deep Research und ändert auch nicht die bestehenden LiteLLM Multi Agent-, Deep-Research-, normalen Bericht- oder geplanten Task-Funktionen. Codex ist kein Offline-Modell; Aktienfragen und entschärfte Tool-Ergebnisse können von den in Codex konfigurierten Diensten verarbeitet werden; DSA liest oder speichert keine Codex-Anmeldedaten. Docker, Remote-Server und Desktop müssen jeweils sicherstellen, dass Codex im PATH ihres Backend-Prozesses sichtbar ist. Siehe [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md#codex-local-agent-phase-6-experimental-prototyp).

### Konfiguration der Benachrichtigungskanäle

Weitere Basiswerte, Diagnosen und Bereitstellungsszenarien für Benachrichtigungen siehe [Benachrichtigungs-Dokument](notifications.md).

| Variable | Beschreibung | Pflicht |
|--------|------|:----:|
| `WECHAT_WEBHOOK_URL` | WeCom-Roboter-Webhook-URL | Optional |
| `FEISHU_WEBHOOK_URL` | Feishu-Roboter-Webhook-URL | Optional |
| `FEISHU_WEBHOOK_SECRET` | Feishu-Roboter-Signaturschlüssel (nur ausfüllen, wenn in den Roboter-Sicherheitseinstellungen „Signaturprüfung“ aktiviert ist) | Optional |
| `FEISHU_WEBHOOK_KEYWORD` | Feishu-Roboter-Keyword (nur ausfüllen, wenn in den Roboter-Sicherheitseinstellungen „Keyword“ aktiviert ist) | Optional |
| `TELEGRAM_BOT_TOKEN` | Telegram-Bot-Token | Optional |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | Optional |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram-Topic-ID | Optional |
| `DISCORD_WEBHOOK_URL` | Discord-Webhook-URL | Optional |
| `DISCORD_BOT_TOKEN` | Discord-Bot-Token (entweder Bot oder Webhook) | Optional |
| `DISCORD_MAIN_CHANNEL_ID` | Discord-Kanal-ID (bei Verwendung des Bots erforderlich) | Optional |
| `DISCORD_INTERACTIONS_PUBLIC_KEY` | Discord-Public-Key (nur zur Signaturprüfung eingehender Interaction/Webhook-Callbacks erforderlich) | Optional |
| `DISCORD_MAX_WORDS` | Obergrenze für den Content einer einzelnen Discord-Nachricht (Standard 2000; zur Laufzeit wird die Discord-Grenze von 2000 Zeichen nicht überschritten, lange Berichte werden automatisch aufgeteilt und 429-Limits mit begrenzten Wiederholungen behandelt) | Optional |
| `SLACK_BOT_TOKEN` | Slack-Bot-Token (empfohlen, unterstützt Bild-Upload; hat Vorrang vor dem Webhook, wenn beides konfiguriert ist) | Optional |
| `SLACK_CHANNEL_ID` | Slack-Kanal-ID (bei Verwendung des Bots erforderlich) | Optional |
| `SLACK_WEBHOOK_URL` | Slack-Incoming-Webhook-URL (nur Text, keine Bilder) | Optional |
| `EMAIL_SENDER` | Absender-E-Mail | Optional |
| `EMAIL_PASSWORD` | E-Mail-Autorisierungscode (nicht das Anmeldepasswort) | Optional |
| `EMAIL_RECEIVERS` | Empfänger-E-Mail (per Komma getrennt; leer an sich selbst) | Optional |
| `EMAIL_SENDER_NAME` | Anzeigename des Absenders | Optional |
| `STOCK_GROUP_N` / `EMAIL_GROUP_N` | E-Mail-Gruppenrouting (Issue #268): `STOCK_GROUP_N` sollte eine Teilmenge von `STOCK_LIST` sein, betrifft nur die E-Mail-Empfänger, ändert nicht den Analyseumfang oder andere Benachrichtigungskanäle | Optional |
| `CUSTOM_WEBHOOK_URLS` | Benutzerdefinierte Webhooks (per Komma getrennt) | Optional |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | Bearer-Token für benutzerdefinierten Webhook | Optional |
| `WEBHOOK_VERIFY_SSL` | Zertifikatsprüfung für webhook-artige HTTPS-Benachrichtigungsanfragen, die diese Konfiguration lesen (Standard true). Mit false werden selbstsignierte Zertifikate unterstützt. Warnung: Das Deaktivieren birgt ernste Sicherheitsrisiken | Optional |
| `PUSHOVER_USER_KEY` | Pushover-Benutzerschlüssel | Optional |
| `PUSHOVER_API_TOKEN` | Pushover-API-Token | Optional |
| `NTFY_URL` | ntfy vollständiger Topic-Endpoint, muss den Topic-Pfad enthalten, z. B. `https://ntfy.sh/my-topic` | Optional |
| `NTFY_TOKEN` | ntfy-Bearer-Token (optional) | Optional |
| `GOTIFY_URL` | Gotify-Server-Basis-URL, ohne `/message` | Optional |
| `GOTIFY_TOKEN` | Gotify-Anwendungstoken, wird über den `X-Gotify-Key`-Header gesendet | Optional |
| `PUSHPLUS_TOKEN` | PushPlus-Token (inländischer Push-Dienst) | Optional |
| `SERVERCHAN3_SENDKEY` | ServerChan³-Sendkey | Optional |
| `ASTRBOT_URL` | AstrBot-Webhook-URL | Optional |
| `ASTRBOT_TOKEN` | AstrBot-Bearer-Token (optional) | Optional |
| `NOTIFICATION_REPORT_CHANNELS` | report-Routing-Kanäle, per Komma getrennt; erlaubte Werte: wechat,feishu,telegram,email,pushover,ntfy,gotify,pushplus,serverchan3,custom,discord,slack,astrbot | Optional |
| `NOTIFICATION_ALERT_CHANNELS` | alert-Routing-Kanäle, per Komma getrennt; leer behält alle Kanäle | Optional |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | reservierte system_error-Routing-Kanäle, per Komma getrennt; leer behält alle Kanäle | Optional |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | TTL-Sekunden für die Benachrichtigungs-Deduplizierung, `0` deaktiviert | Optional |
| `NOTIFICATION_COOLDOWN_SECONDS` | Benachrichtigungs-Cooldown in Sekunden, `0` deaktiviert | Optional |
| `NOTIFICATION_QUIET_HOURS` | Stillezeitraum, Format `HH:MM-HH:MM`, unterstützt über Mitternacht | Optional |
| `NOTIFICATION_TIMEZONE` | Zeitzone für den Stillezeitraum, z. B. `Asia/Shanghai`; leer folgt `TZ` oder der System-Zeitzone | Optional |
| `NOTIFICATION_MIN_SEVERITY` | Mindest-Schweregrad der Benachrichtigung: info, warning, error, critical; leer behält den aktuellen Zustand | Optional |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | reservierter Schalter für die tägliche Zusammenfassung; derzeit wird keine Zusammenfassung gesendet | Optional |

> Hinweis: Der standardmäßige GitHub-Actions-Workflow `00-daily-analysis.yml` mappt nur feste Variablennamen und importiert beliebig nummerierte `STOCK_GROUP_N`/`EMAIL_GROUP_N` nicht automatisch. Daher funktioniert die Gruppen-E-Mail derzeit nur in lokalen `.env`, Docker oder anderen Laufzeitumgebungen, in denen diese Umgebungsvariablen explizit injiziert wurden; wenn du sie in deinen eigenen GitHub Actions verwenden willst, musst du sie im Job `env:` des Workflows pro Gruppe explizit mappen.

#### Feishu-Cloud-Dokument-Konfiguration (optional, behebt das Problem abgeschnittener Nachrichten)

| Variable | Beschreibung | Pflicht |
|--------|------|:----:|
| `FEISHU_APP_ID` | Feishu-App-ID | Optional |
| `FEISHU_APP_SECRET` | Feishu-App-Secret | Optional |
| `FEISHU_FOLDER_TOKEN` | Feishu-Cloud-Disk-Ordner-Token | Optional |
| `FEISHU_SEND_AS_FILE` | Feishu-App-Bot sendet Berichte als Datei (Standard `false`) | Optional |

> Schritte zur Feishu-Cloud-Dokument-Konfiguration:
> 1. Erstelle eine App im [Feishu-Entwicklerportal](https://open.feishu.cn/app)
> 2. Konfiguriere die GitHub-Secrets
> 3. Erstelle eine Gruppe und füge den App-Bot hinzu
> 4. Füge die Gruppe im Cloud-Disk-Ordner als Mitwirkende hinzu (mit Verwaltungsberechtigung)
>
> Hinweis: `FEISHU_APP_ID`/`FEISHU_APP_SECRET` werden für die Feishu-App, Cloud-Dokumente oder den Stream-Bot-Modus verwendet und aktivieren nicht direkt den Gruppen-Webhook-Push. Wenn du einfach nur Gruppenbenachrichtigungen erhalten möchtest, konfiguriere zuerst `FEISHU_WEBHOOK_URL`.
>
> Ergänzung: Wenn `FEISHU_APP_ID`, `FEISHU_APP_SECRET` und `FEISHU_CHAT_ID` zusammen konfiguriert sind, kann der aktive Benachrichtigungskanal des Feishu-App-Bots aktiviert werden, der ohne Webhook aktiv an einen bestimmten Chat oder Benutzer pusht; `FEISHU_RECEIVE_ID_TYPE` ist standardmäßig `chat_id`, für private Chats auf `open_id` ändern. Diese Methode läuft über die OpenAPI-Bot-Sitzung von Feishu und ist ein vom Gruppen-Webhook unabhängiger Pfad.

### Konfiguration des Suchdienstes

| Variable | Beschreibung | Pflicht |
|--------|------|:----:|
| `ANSPIRE_API_KEYS` | Anspire-Open-API-Key (Konfigurationsbeispiel für Szenarien mit geteilter Suche und Großmodell-Gateway; die Verfügbarkeit hängt von Kontoberechtigungen und Gateway-Sichtbarkeit ab, kann die A-Aktien-Analyse wirkungsvoll verbessern) | Empfohlen |
| `SERPAPI_API_KEYS` | Verstärkung der Suchmaschinenergebnisse über SerpAPI, geeignet für Echtzeit-Finanznachrichten | Empfohlen |
| `TAVILY_API_KEYS` | Tavily-Such-API-Key | Optional |
| `BOCHA_API_KEYS` | Bocha-Search-API-Key (für Chinesisch optimiert) | Optional |
| `BRAVE_API_KEYS` | Brave-Search-API-Key (für US-Aktien optimiert) | Optional |
| `MINIMAX_API_KEYS` | MiniMax Coding Plan Web Search (strukturierte Suchergebnisse) | Optional |
| `SOCIAL_SENTIMENT_API_KEY` | Stock-Sentiment-API-Key (Reddit / X / Polymarket, optional) | Optional |
| `SOCIAL_SENTIMENT_API_URL` | Stock-Sentiment-API-Adresse (Standard `https://api.adanos.org`) | Optional |
| `SEARXNG_BASE_URLS` | Selbst gehostete SearXNG-Instanz (ohne Quoten-Fallback, erfordert `format: json` in settings.yml); leer erkennt automatisch öffentliche Instanzen | Optional |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Ob bei leerem `SEARXNG_BASE_URLS` automatisch öffentliche Instanzen von `searx.space` bezogen werden (Standard `true`) | Optional |
| `NEWS_STRATEGY_PROFILE` | Nachrichtenstrategie-Fensterstufe: `ultra_short` (1 Tag)/`short` (3 Tage)/`medium` (7 Tage)/`long` (30 Tage); das tatsächliche Fenster ist der kleinere Wert mit `NEWS_MAX_AGE_DAYS` | Standard `short` |
| `NEWS_MAX_AGE_DAYS` | Maximale Nachrichtenaktualität (Tage), begrenzt die Suchergebnisse auf den jüngsten Zeitraum | Standard `3` |
| `BIAS_THRESHOLD` | Abweichungsschwelle (%), darüber wird vor dem Nachkaufen gewarnt; bei starken Trendaktien automatisch auf das 1,5-fache erweitert | Standard `5.0` |

> Verhaltenshinweis: Der Suchdienst und der Social-Reputationsdienst sind optionale Erweiterungspfade. Schlägt die Initialisierung eines Dienstes fehl, protokolliert das System eine Warning und überspringt diesen Dienst; das betrifft nur den jeweiligen Teil und blockiert weder den Hauptpfad der technischen Analyse noch den Hauptaufgabenfluss.

### Erklärbare Sortierung der Nachrichtenrecherche (Issue #1356)

Für jede Kandidaten-Nachricht berechnet `search_stock_news` eine „erklärbare Relevanz“ und ordnet sie einer von 3 Label-Klassen zu:

- `direct_company_news`: Treffer auf Zielcode, Firmennamen (einschließlich Gewichtung offizieller/Börsenquellen);
- `sector_related_news`: Treffer auf die Semantik des Branchensektors;
- `macro_market_news`: makroökonomische/Marktkontext-Nachrichten, wenn kein Zielsubjekt getroffen wurde.

Die Sortierstrategie lautet: zuerst nach Kategoriepriorität (direct > sector > macro), dann nach Sprachpräferenz (Chinesisch zuerst) und dann nach Punktzahl. Daher werden Nachrichten, die im selben Zeitfenster ein eindeutiges Ziel treffen, zuerst angezeigt.

Nach der Sortierung wird zusätzlich eine domänenunabhängige Zulassungsfilterung ausgeführt: offensichtliche Download-/Installationspaket-/App-Bewertungsseiten sowie Spam-Seiten für Erwachsenendienste werden entfernt. Wenn in derselben Charge bereits ein direktes Ziel oder bewertete Branchen-/Marktkandidaten existieren, gelangen `score=0`-Hintergrundauffüller nicht in `news_context`, die Tool-Ausgabe des Agents oder den historischen Intelligenz-Cache. Diese Regel enthält keine feste Website-Blacklist, um die Wartung über Domänen-Enumeration zu vermeiden.

Debug-Einstieg:

- Jede Rückgabe behält die Metadaten `relevance_score`/`relevance_category`/`relevance_reasons`; das finale `to_text()` und der Intelligenzkontext enthalten die entsprechende „Relevanz“-Erläuterung;
- Das Suchpfad-Log gibt `[Nachrichtenrelevanz]`-Statistiken aus, um nachvollziehen zu können, warum diese Charge die direct/sector/macro-Schichtung ausgelöst hat.

Kompatibilitäts- und Rückfallhinweis: Diese Änderung fügt keine Modelle, Provider, Base URLs, LiteLLM-Routen, Konfigurationsbereinigungen oder Rückschreiblogik hinzu oder ändert sie; bei Anomalien kann das alte Sortierverhalten nur durch ein Rollback dieses Commits wiederhergestellt werden; eine Migration historischer Konfigurationen ist nicht betroffen.

### Konfiguration des Futu-Positionsimports

| Variable | Beschreibung | Standardwert | Pflicht |
|--------|------|--------|:----:|
| `FUTU_OPEND_HOST` | OpenD-Adresse; das gesperrte `futu-api==10.8.6808` unterstützt nur IPv4-Adressen oder Hostnamen, die zu IPv4 auflösen. Hostübergreifende Verbindungen sollten nur über vertrauenswürdige Netzwerke oder lokalen Port-Forwarding erfolgen. | `127.0.0.1` | Optional |
| `FUTU_OPEND_PORT` | OpenD-Port, gültiger Bereich `1-65535`. | `11111` | Optional |
| `FUTU_SECURITY_FIRM` | Name des Futu-`SecurityFirm`-Enums; `NONE` bedeutet, dass die offizielle Auto-Erkennung des SDK einmalig verwendet wird, ein Broker kann auch explizit angegeben werden. | `NONE` | Optional |
| `FUTU_ACC_ID` | Gibt eine passende REAL-Konto-ID an; leer werden alle `NORMAL`- (normal) und `MASTER`- (Haupt) Wertpapierkonten mit Status `ACTIVE` zusammengeführt. Die Konto-ID ist als sensible Konfiguration zu behandeln und darf nicht ins Repository committet werden. | leer | Optional |

`MASTER` steht nur für die Hauptkontenrolle von Futu und bedeutet keine Nur-Lese-Eigenschaft des Kontos. Die Nur-Lese-Grenze dieser Integration rührt daher, dass sie nur Abfrage-Schnittstellen für Konto, Positionen und Wertpapierinformationen aufruft, nicht aber Schnittstellen für Handelsfreischaltung, Auftragserteilung, -änderung oder -stornierung.

### Datenquellen-Konfiguration

| Variable | Beschreibung | Standardwert | Pflicht |
|--------|------|--------|:----:|
| `TUSHARE_TOKEN` | Tushare Pro Token | - | Optional |
| `TUSHARE_HTTP_URL` | Tushare-Pro-HTTP-Adresse; leer wird der offizielle Endpoint `http://api.tushare.pro` verwendet; nur bei Firmen-Proxy, grenzüberschreitendem Netzwerk oder eigenem Mirror eine vollständige `http://`- oder `https://`-Adresse angeben | `http://api.tushare.pro` | Optional |
| `TICKFLOW_API_KEY` | TickFlow-API-Key; optional für A-Aktien-Tages-K, Echtzeit-Kurse, Aktienlisten/-namen und Markt-Rückblick-Erweiterung; bei Fehlern oder fehlenden Berechtigungen automatischer Rückfall. | - | Optional |
| `TICKFLOW_PRIORITY` | Priorität der TickFlow-Tages-K-Datenquelle; je kleiner die Zahl, desto früher wird sie versucht, Standard `2`; ohne konfigurierten API-Key nicht aktiv; betrifft nicht die Echtzeit-Kurse, deren Reihenfolge `REALTIME_SOURCE_PRIORITY` steuert. | `2` | Optional |
| `TENCENT_PRIORITY` | Priorität der Tencent-Direktverbindungs-A-Aktien-Tages-K-Datenquelle; je kleiner die Zahl, desto früher wird sie versucht, Standard `5`, als endgültiger Fallback nach Efinance, AkShare, Tushare, TickFlow, PyTDX, Baostock und YFinance; betrifft nicht die Echtzeit-Kurse. | `5` | Optional |
| `TICKFLOW_KLINE_ADJUST` | Bereinigungsmodus der TickFlow-Tages-K: `none`, `forward`, `backward`, `forward_additive`, `backward_additive`. | `none` | Optional |
| `TICKFLOW_BATCH_DAILY_ENABLED` | Ob der TickFlow-Batch-Tages-K-Vorabruf aktiviert ist; bei fehlenden Berechtigungen wird der Fehlerstatus kurz gecacht und der reguläre Fallback fortgesetzt. | `true` | Optional |
| `TICKFLOW_BATCH_SIZE` | Maximale Anzahl von Zielen pro Charge für TickFlow-Tages-K- und Echtzeit-Batchanfragen. | `100` | Optional |
| `LONGBRIDGE_OAUTH_CLIENT_ID` | Longbridge OAuth client_id; leer und ohne Legacy-Access-Token wird kompatibel `LONGBRIDGE_APP_KEY` verwendet | - | Optional |
| `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` | Base64-Inhalt der OAuth-Token-Cache-Datei, für headless Umgebungen wie GitHub Actions / Docker | - | Optional |
| `LONGBRIDGE_APP_KEY` | Longbridge Legacy App Key; ohne `LONGBRIDGE_ACCESS_TOKEN` auch als kompatibles Alias für OAuth client_id nutzbar | - | Optional |
| `LONGBRIDGE_APP_SECRET` | Longbridge App Secret | - | Optional |
| `LONGBRIDGE_ACCESS_TOKEN` | Longbridge Legacy Access Token (kein OAuth-Access-Token) | - | Optional |
| `LONGBRIDGE_*` (optional) | siehe offizielle [Umgebungsvariablen](https://open.longbridge.com/zh-CN/docs/getting-started#环境变量); zusätzlich `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` und `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` | - | Optional |
| `ENABLE_REALTIME_QUOTE` | Echtzeit-Kurse aktivieren (bei Deaktivierung wird mit historischen Schlusskursen analysiert) | `true` | Optional |
| `ENABLE_REALTIME_TECHNICAL_INDICATORS` | Echtzeit-Technik während der Handelszeit: aktiviert werden MA5/MA10/MA20 und die Bullenordnung mit Echtzeitpreisen berechnet (Issue #234); deaktiviert wird der gestrige Schlusskurs verwendet | `true` | Optional |
| `ENABLE_CHIP_DISTRIBUTION` | Chip-Verteilungsanalyse aktivieren (diese Schnittstelle ist instabil, für Cloud-Deployments empfohlen zu deaktivieren). GitHub-Actions-Nutzer müssen `ENABLE_CHIP_DISTRIBUTION=true` in den Repository Variables setzen, um sie zu aktivieren; der Workflow ist standardmäßig deaktiviert. | `true` | Optional |
| `ENABLE_EASTMONEY_PATCH` | East-Money-Schnittstellen-Patch: Bei häufigen Fehlern der East-Money-Schnittstelle (z. B. RemoteDisconnected, Verbindung geschlossen) wird empfohlen, auf `true` zu setzen; ein NID-Token und ein zufälliger User-Agent werden injiziert, um die Wahrscheinlichkeit von Rate-Limits zu verringern | `false` | Optional |
| `REALTIME_SOURCE_PRIORITY` | Priorität der Echtzeit-Kursquellen, per Komma getrennt, z. B. `tencent,akshare_sina,efinance,akshare_em`; `tickflow` muss explizit enthalten sein, damit TickFlow-Echtzeit-Kurse verwendet werden. | siehe `.env.example` | Optional |
| `ENABLE_FUNDAMENTAL_PIPELINE` | Hauptschalter für die Fundamentaldaten-Aggregation; deaktiviert wird nur der `not_supported`-Block zurückgegeben, ohne die ursprüngliche Analyse-Pipeline zu ändern | `true` | Optional |
| `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS` | Gesamt-Timeout-Budget der Fundamentaldaten-Phase (Sekunden) | `8.0` | Optional |
| `FUNDAMENTAL_FETCH_TIMEOUT_SECONDS` | Timeout für einzelne Fähigkeitsquellen-Aufrufe (Sekunden); die Branchen-/Konzept-Rankings der Marktstruktur nutzen ebenfalls dieses Budget | `8.0` | Optional |
| `FUNDAMENTAL_RETRY_MAX` | Anzahl der Wiederholungen der Fundamentaldaten-Fähigkeiten (einschließlich des ersten Versuchs) | `1` | Optional |
| `FUNDAMENTAL_CACHE_TTL_SECONDS` | TTL des Fundamentaldaten-Aggregationscaches (Sekunden), kurzer Cache verringert wiederholte Abrufe | `120` | Optional |
| `FUNDAMENTAL_CACHE_MAX_ENTRIES` | Maximale Anzahl der Einträge im Fundamentaldaten-Cache (innerhalb der TTL zeitbasiert ausgeschieden) | `256` | Optional |

> Verhaltenshinweise:
> - A-Aktien: liefert die aggregierten Fähigkeiten `valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards`;
> - ETF: gibt die verfügbaren Einträge zurück, fehlende Fähigkeiten werden als `not_supported` markiert, ohne den ursprünglichen Ablauf zu beeinflussen;
> - US-/Hongkong-Aktien: liefert über den yfinance-Adapter `valuation/growth/earnings/belong_boards` (Quellen `info.sector`/`industry`); `institution/capital_flow/dragon_tiger/boards` haben derzeit keine entsprechende Datenquelle und bleiben `not_supported`; wenn yfinance nicht verfügbar ist oder Felder fehlen, wird insgesamt auf `not_supported` herabgestuft, weiterhin fail-open;
> - japanische/koreanische Aktien: nutzen derzeit nur den Yfinance-Basispfad für Tageslinien und Echtzeit-Kurse; Fähigkeiten wie `institution`, `capital_flow`, `dragon_tiger`, `boards`, die auf A-Aktien-spezifischen Quellen/der vollständigen Offshore-Version beruhen, werden auf `not_supported` herabgestuft (siehe [Marktunterstützung und Grenzen](market-support.md));
> - Taiwan-Aktien: Zusätzlich zum Offshore-Basispfad für US-/Hongkong-Aktien zeigt der `institution`-Block die Netto-Kauf-/Verkaufsbeträge der drei großen Institutionen (TWSE T86 / TPEx, standardmäßig aktiviert, fail-open, bleibt `not_supported`, wenn keine Daten verfügbar sind); `capital_flow`, `dragon_tiger`, `boards` bleiben `not_supported`;
> - Jede Anomalie nutzt fail-open, Fehler werden nur protokolliert und beeinflussen nicht den Hauptpfad von Technik/Nachrichten/Chips.
> - Nach der Konfiguration von `TICKFLOW_API_KEY` wird TickFlow als optionale A-Aktien-Tages-K-Datenquelle und Markt-Rückblick-Erweiterungsquelle instanziiert; `TICKFLOW_PRIORITY` betrifft nur die Tages-K-/Allgemein-Datenquellen-Fallback-Kette. Die Echtzeit-Kurspriorität wird separat von `REALTIME_SOURCE_PRIORITY` gesteuert; nur bei explizitem `tickflow` werden TickFlow-Echtzeit-Kurse verwendet. Datenquellen vor `tickflow` in `REALTIME_SOURCE_PRIORITY` werden zuerst versucht.
> - TickFlow-Tages-K Standard `TICKFLOW_KLINE_ADJUST=none`; das Tages-`volume` wird einheitlich von Händen in Aktien umgerechnet, `amount` bleibt in Yuan (CNY).
> - TickFlow-Tages-K-Bereichsanfragen übergeben explizit `start_time`/`end_time`/`count`; der offizielle Quickstart stellt klar, dass Zeitbereichsabfragen weiterhin durch `count` begrenzt sind. Wenn die Rückgabe nicht leer ist, aber die Zeilenzahl `count` voll ausschöpft und der erste zurückgegebene Handelstag später liegt als der angeforderte Start-Handelstag, stuft das System dies als vermutete Kürzung ein, schreibt nicht in den Cache und lässt den Manager weiter zurückfallen.
> - Bei Batch-Analysen wärmt `prefetch_daily_klines()` den Prozess-Cache vor den einzelnen `get_daily_data()`-Aufrufen auf, ohne den externen Aufrufpfad zu ändern.
> - TickFlow-Fähigkeiten sind nach Paketberechtigungen gestaffelt: Pakete mit begrenzten Berechtigungen können weiterhin Hauptindexabfragen nutzen; nur Pakete, die Abfragen des Zielpools `CN_Equity_A` unterstützen, aktivieren TickFlow-Marktstatistiken.
> - TickFlow kann über den Shenwan-Erstbranchen-Zielpool und alle A-Aktien-Kurse Branchen-Auf-/Ab-Rankings erzeugen und nimmt bevorzugt am Fallback der Branchenhauptlinie der Marktstruktur teil; die Konzept-/Themen-Rankings werden weiterhin von der bestehenden AkShare-/Tushare-/Efinance-Kette geliefert.
> - Der offizielle TickFlow-Quickstart zeigt die Verwendung von `quotes.get(universes=["CN_Equity_A"])`, aber nicht jeder API-Key hat die entsprechende Berechtigung; Batch-Tages-K, Tiefe und Finanz-Fähigkeiten sind ebenfalls berechtigungsabhängig fail-open.
> - Die von TickFlow tatsächlich zurückgegebenen `change_pct`/`amplitude` sind Verhältniswerte; das System hat sie bereits in der Anbindungsschicht einheitlich in Prozentwerte umgerechnet, um die Semantik der bestehenden Datenquellenfelder zu gewährleisten.
> - Der A-Aktien-Markt-Rückblickbericht verwendet eine Workbench-artige Struktur nach Börsenschluss: fest enthalten sind Markt-Signale, Index-Details, Sektor-Top-Tabelle, Markthinweise der letzten drei Tage, Handelsplan für morgen und Risikohinweise; Markt-Signale werden als reiner Text-Score wie `66/100（leicht bullish, Angriff möglich）` ausgedrückt, um uneinheitliche Darstellungen von Farbverlaufsbalken auf verschiedenen Terminals zu vermeiden; die Markthinweise der letzten drei Tage listen nur Titel, Quelle und Link, ohne Such-Snippets; wenn einige Datenquellen fehlen, bleiben die verfügbaren Blöcke erhalten und werden an den entsprechenden Stellen degradiert angezeigt.
> - Feldkontrakt:
>   - `fundamental_context.belong_boards` = Liste der zugehörigen Sektoren einer Aktie; bei A-Aktien aus der AkShare-Sektorliste, bei US-/Hongkong-Aktien aus yfinance `info.sector`/`info.industry`, bei fehlenden Daten `[]`;
>   - `fundamental_context.boards.data` = `sector_rankings` (Sektor-Auf-/Ab-Ranking, Struktur `{top, bottom}`, derzeit nicht für HK/US verfügbar);
>   - `fundamental_context.concept_boards.data` = `concept_rankings` (Konzept-/Themen-Auf-/Ab-Ranking, Struktur `{top, bottom}`, derzeit nur für A-Aktien verfügbar; bei Nichtverfügbarkeit fail-open leer oder fehlend);
>   - `fundamental_context.earnings.data.financial_report` = Finanzbericht-Zusammenfassung (Berichtszeitraum, Umsatz, Nettoergebnis der Muttergesellschaft, operativer Cashflow, ROE, sowie `currency` aus `info.financialCurrency`, bei HK ADR üblich CNY);
>   - `fundamental_context.earnings.data.dividend` = Dividenden-Kennzahlen (nur Bar-Dividende vor Steuern, inkl. `events`, `ttm_cash_dividend_per_share`, `ttm_dividend_yield_pct`, `currency`). `currency` wird unabhängig aus `info.currency` gelesen und kann sich von `financial_report.currency` unterscheiden (HK ADR: Finanzbericht CNY, Dividende HKD); der TTM-Yield wird standardmäßig als `ttm_cash / latest_price * 100` (gleiche Währung) sofort neu berechnet, nur wenn TTM cash oder latest price fehlen, wird auf yfinance `trailingAnnualDividendYield` oder `dividendYield` zurückgegriffen;
>   - `get_stock_info.belong_boards` = Liste der Sektoren, zu denen die Aktie gehört;
>   - `get_stock_info.boards` ist ein Kompatibilitäts-Alias mit demselben Wert wie `belong_boards` (eine Entfernung wird künftig nur in einer Hauptversion erwogen);
>   - `get_stock_info.sector_rankings` bleibt konsistent mit `fundamental_context.boards.data`.
>   - `AnalysisReport.details.belong_boards` = Liste der zugehörigen Sektoren in den Details des strukturierten Berichts;
>   - `AnalysisReport.details.sector_rankings` = Sektor-Auf-/Ab-Ranking in den Details des strukturierten Berichts (für die verknüpfte Sektor-Anzeige im Frontend).
>   - `AnalysisReport.details.concept_rankings` = Konzept-/Themen-Auf-/Ab-Ranking in den Details des strukturierten Berichts (für die Signalanpassung verknüpfter Sektoren im Frontend sowie die Unterscheidung von Branchen/Konzepten nach Typ in der Benachrichtigungstabelle).
> - Das Sektor-Auf-/Ab-Ranking verwendet die Datenquellenreihenfolge: identisch zur globalen Priorität.
> - Die Timeout-Steuerung ist ein `best-effort`-weiches Timeout: Die Phase degradiert gemäß Budget schnell und führt fort, ohne einen harten Abbruch der zugrunde liegenden Drittanbieter-Aufrufe zu garantieren.
> - `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS=8.0` stellt das Zielbudget der neuen Fundamentaldaten-Phase dar, keine strikte harte SLA; unter Windows, Docker oder bei gedrosselten kostenlosen Datenquellen kann weiter auf `12-15s` erhöht werden.
> - Für eine harte SLA bitte in späteren Versionen auf subprozess-isolierte Ausführung umstellen und nach dem Timeout gewaltsam beenden.

### Weitere Konfiguration

| Variable | Beschreibung | Standardwert |
|--------|------|--------|
| `STOCK_LIST` | Watchlist-Codes (per Komma getrennt) | - |
| `ADMIN_AUTH_ENABLED` | Web-Login: mit `true` wird der Passwortschutz aktiviert; beim ersten Zugriff wird das anfängliche Passwort im Web festgelegt, änderbar unter „Systemeinstellungen > Passwort ändern“; bei vergessenem Passwort `python -m src.auth reset_password` ausführen. Der Import/Export von `.env`-Backups im Web ist nur bei aktiviertem Schalter verfügbar (Desktop ist davon nicht betroffen). | `false` |
| `TRUST_X_FORWARDED_FOR` | Bei einer einstufigen vertrauenswürdigen Reverse-Proxy-Bereitstellung auf `true` setzen; der äußerste rechte Wert von `X-Forwarded-For` wird als echte Client-IP verwendet (z. B. für Login-Rate-Limits); bei direktem öffentlichem Netz `false` beibehalten, um Fälschungen zu verhindern. In mehrstufigen Proxy-/CDN-Szenarien kann der Limit-Key auf die Edge-Proxy-IP abfallen, zusätzliche Bewertung nötig | `false` |
| `MAX_WORKERS` | Anzahl der parallelen Threads | `3` |
| `MARKET_REVIEW_ENABLED` | Markt-Rückblick aktivieren | `true` |
| `DAILY_MARKET_CONTEXT_ENABLED` | Injiziert die Tagesmarkt-Umgebungszusammenfassung in den Einzelaktien-Analyse-Prompt und mildert aggressive Kaufsempfehlungen in Hochrisiko-/Rückgangsumgebungen; standardmäßig aktiviert, mit `false` kann der Markt-Rückblick weiterhin ausgeführt werden | `true` |
| `MARKET_REVIEW_REGION` | Marktregion des Markt-Rückblicks: cn (A-Aktien), hk (Hongkong-Aktien), us (US-Aktien), jp (japanische Aktien), kr (koreanische Aktien), both (fünf Märkte); us/jp/kr eignen sich für Nutzer mit Fokus auf eine einzige Region | `cn` |
| `MARKET_REVIEW_COLOR_SCHEME` | Farben der Index-Auf-/Ab-Bewegung im Markt-Rückblick: `green_up` = Grün steigt/Rot fällt (Standard), `red_up` = Rot steigt/Grün fällt | `green_up` |
| `TRADING_DAY_CHECK_ENABLED` | Handelstagsprüfung: Standard `true`, an Nicht-Handelstagen wird die Ausführung übersprungen; mit `false` oder `--force-run` kann die Ausführung erzwungen werden (Issue #373) | `true` |
| `SCHEDULE_ENABLED` | Geplante Tasks aktivieren | `false` |
| `SCHEDULE_TIME` | Zeitpunkt der geplanten Ausführung | `18:00` |
| `SCHEDULE_TIMES` | Mehrere Zeitpunkte der geplanten Ausführung, per Komma getrennt; leer wird `SCHEDULE_TIME` verwendet | leer |
| `LOG_DIR` | Log-Verzeichnis | `./logs` |
| `SAVE_CONTEXT_SNAPSHOT` | Analyseverlauf `context_snapshot` speichern; bei `false` speichert neuer Verlauf kein enhanced_context, market_phase_summary, AnalysisContextPack-Overview oder Diagnose-Snapshot, deaktiviert aber nicht die entschärfte Zusammenfassung des jeweiligen Prompts | `true` |

---

## Docker-Bereitstellung

Das Dockerfile verwendet einen mehrstufigen Build; das Frontend wird beim Erstellen des Images automatisch gebündelt und in `static/` eingebettet.
Zum Überschreiben der statischen Ressourcen kann das lokale `static/` auf `/app/static` im Container gemountet werden.
Der laufende `server`-Container nutzt standardmäßig direkt die vorgebauten Artefakte in `/app/static`; weder muss das Quellverzeichnis `apps/dsa-web` im Container verbleiben noch `npm` zur Laufzeit installiert sein. Wenn die WebUI nicht geöffnet werden kann, prüfe zuerst, ob `/app/static/index.html` existiert.

Aktuelle Veröffentlichungsadressen der offiziellen Images:

- GHCR: `ghcr.io/zhulinsen/daily_stock_analysis:<tag>`
- Docker Hub: `<DOCKERHUB_USERNAME>/daily_stock_analysis:<tag>` (wird durch das `DOCKERHUB_USERNAME`-Secret des Veröffentlichers bestimmt, offiziell veröffentlicht als `zhulinsen/daily_stock_analysis`)

### Schnellstart

```bash
# 1. Repository klonen
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis

# 2. Umgebungsvariablen konfigurieren
cp .env.example .env
vim .env  # API-Key und Konfiguration eintragen

# 3. Container starten
docker-compose -f ./docker/docker-compose.yml up -d server     # Web-Dienstmodus (empfohlen, bietet API und WebUI)
docker-compose -f ./docker/docker-compose.yml up -d analyzer   # Modus für geplante Tasks
docker-compose -f ./docker/docker-compose.yml up -d            # Beide Modi gleichzeitig starten

# 4. WebUI aufrufen
# http://localhost:8000

# 5. Logs ansehen
docker-compose -f ./docker/docker-compose.yml logs -f server
```

Standardmäßig setzt Compose für jeden Dienst `limits.memory: 1G` und `reservations.memory: 512M`. `512M` wird nur für leichte Web-/API-, Einzelaktien- und niedrige Nebenläufigkeitsszenarien empfohlen, mit `MAX_WORKERS=1`; für reguläre vollständige Analysen wird `1G` empfohlen, bei gleichzeitigem Start von `server + analyzer`, mehreren Aktien, Markt-Rückblick, Nachrichten-Erweiterung, Bildberichten oder integrierter Aktienauswahl werden `2G+` empfohlen. Wenn nur `512M` verfügbar ist, vermeide das gleichzeitige Starten beider Dienste und reduziere schwergewichtige Funktionen.

### Offizielles Image direkt ziehen und ausführen

Wenn du den Quellcode nicht auf der Zielmaschine behalten möchtest, kannst du das offizielle Image direkt ziehen:

```bash
# Web-/API-Modus
docker pull zhulinsen/daily_stock_analysis:latest
docker run -d \
  --name dsa-server \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  zhulinsen/daily_stock_analysis:latest \
  python main.py --serve-only --host 0.0.0.0 --port 8000

# Modus für geplante Tasks
docker run -d \
  --name dsa-analyzer \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  zhulinsen/daily_stock_analysis:latest
```

Für eine feste Version oder einfache Rollbacks ersetze `latest` durch einen konkreten Versionstag, z. B. `v3.13.0`.

### Erläuterung der Ausführungsmodi

| Befehl | Beschreibung | Port |
|------|------|------|
| `docker-compose -f ./docker/docker-compose.yml up -d server` | Web-Dienstmodus, bietet API und WebUI | 8000 |
| `docker-compose -f ./docker/docker-compose.yml up -d analyzer` | Modus für geplante Tasks, tägliche automatische Ausführung | - |
| `docker-compose -f ./docker/docker-compose.yml up -d` | Startet beide Modi gleichzeitig | 8000 |

### Docker-Compose-Konfiguration

`docker-compose.yml` nutzt YAML-Anker zur Konfigurationswiederverwendung:

```yaml
version: '3.8'

x-common: &common
  build:
    context: ..
    dockerfile: docker/Dockerfile
  restart: unless-stopped
  env_file:
    - ../.env
  environment:
    - TZ=Asia/Shanghai
  volumes:
    - ../data:/app/data
    - ../logs:/app/logs
    - ../reports:/app/reports
    - ../strategies:/app/strategies:ro
  deploy:
    resources:
      limits:
        memory: 1G
      reservations:
        memory: 512M

services:
  # Modus für geplante Tasks
  analyzer:
    <<: *common
    container_name: stock-analyzer

  # FastAPI-Modus
  server:
    <<: *common
    container_name: stock-server
    command: ["python", "main.py", "--serve-only", "--host", "0.0.0.0", "--port", "${API_PORT:-8000}"]
    ports:
      - "${API_PORT:-8000}:${API_PORT:-8000}"
```

### Hinweise zur `.env`- und Datenverzeichnis-Zuordnung

Egal ob du `docker run` oder Compose verwendest, du musst zwischen der Injektion von Start-Umgebungsvariablen und dem Dateischreiben zur Laufzeit unterscheiden:

- Umgebungsvariablen-Injektion: `--env-file .env` oder Compose `env_file`
  Wirkung: Die Schlüssel-Wert-Paare aus `.env` werden als Umgebungsvariablen beim Containerstart in den Python-Prozess übergeben.
- Schreiben der Laufzeitkonfiguration: Mounte das Host-`.env` nicht als Single-File-Bind-Mount über den `.env`-Pfad im Container. Docker behandelt das Single-File-Mountziel als Mount-Point; die atomare Aktualisierung mit `os.replace()` beim Speichern der Konfiguration kann fehlschlagen und `Device or resource busy` melden; auch das Rückfall-Schreiben kann durch Berechtigungen eingeschränkt sein.

Die Standard-Compose- und `docker run`-Beispiele nutzen nur `env_file`/`--env-file` zur Injektion der Startkonfiguration und mounten das Host-`.env` nicht mehr als Single-File in den Container. Die WebUI-Einstellungsseite zeigt bei fehlenden Schlüsseln in der aktuell aktiven `.env`-Datei die gleichnamigen, beim Start injizierten Umgebungsvariablen als Fallback an, damit Docker-Nutzer nicht fälschlich glauben, die Konfiguration sei gar nicht gelesen worden; „`.env` exportieren“ exportiert jedoch weiterhin nur den Inhalt der aktuell aktiven Konfigurationsdatei.

Die in der WebUI gespeicherte Laufzeitkonfiguration wird standardmäßig in die Konfigurationsdatei im Container geschrieben und entspricht nicht einem Rückschreiben auf das Host-`.env`; nach dem Löschen oder Neuerstellen des Containers gilt weiterhin die beim Start injizierte `.env`. Für die Persistenz der Laufzeitkonfiguration platziere das Schreibziel in einem beschreibbaren Datenvolumen (z. B. über `ENV_FILE=/app/data/runtime.env` auf eine Datei im `data`-Volume zeigen), verwende keinen Single-File-Bind-Mount für `.env`. Achtung: Wenn beim Start in `env_file`, `--env-file`, `docker run -e` oder Compose `environment:` noch gleichnamige alte Werte stehen, können diese Prozess-Umgebungsvariablen beim Container-Neustart die gespeicherten Werte in der Laufzeitdatei weiterhin überschreiben; um die in der WebUI gespeicherten Werte durchzusetzen, aktualisiere oder entferne die gleichnamigen Überschreibungen in der Startumgebung.

Es wird empfohlen, diese Verzeichnisse parallel zu mappen:

- `./data:/app/data`: Datenbank, Cache und Laufzeitdaten
- `./logs:/app/logs`: Log-Ausgabe
- `./reports:/app/reports`: erzeugte Analyseberichte
- `./strategies:/app/strategies:ro`: benutzerdefinierte Strategie-YAML (schreibgeschützt gemountet)

Beim Start des offiziellen Docker-Images werden die Mount-Verzeichnisberechtigungen von `/app/data`, `/app/logs` und `/app/reports` automatisch erstellt und repariert; anschließend wird die Anwendung als nicht-root Nutzer `dsa` (UID/GID `1000:1000`) im Container ausgeführt. Normale Docker-/Compose-Bereitstellungen benötigen kein manuelles `chown` oder `chmod` auf den Host-Verzeichnissen.

Wenn du über `--user` oder Compose `user:` einen anderen Ausführungsbenutzer angibst oder eine `chown` einschränkende Speicherumgebung wie Schreibschutz-Mounts, rootless Docker oder NFS verwendest, kann die automatische Reparatur nicht greifen. Stelle dann sicher, dass der tatsächliche Ausführungsbenutzer Schreibrechte auf `data`, `logs` und `reports` hat, oder verwende beschreibbare Volumes.

Wenn du die eingebauten statischen Ressourcen überschreiben möchtest, kannst du zusätzlich mounten:

- `./static:/app/static:ro`

### Häufige Befehle

```bash
# Laufzeitstatus anzeigen
docker-compose -f ./docker/docker-compose.yml ps

# Logs anzeigen
docker-compose -f ./docker/docker-compose.yml logs -f server

# Dienst stoppen
docker-compose -f ./docker/docker-compose.yml down

# Image neu erstellen (nach Code-Updates)
docker-compose -f ./docker/docker-compose.yml build --no-cache
docker-compose -f ./docker/docker-compose.yml up -d server
```

### Image manuell erstellen

```bash
docker build -f docker/Dockerfile -t stock-analysis .
docker run -d \
  --name dsa-server-local \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  stock-analysis \
  python main.py --serve-only --host 0.0.0.0 --port 8000
```

---

## Detaillierte lokale Ausführungskonfiguration

### Abhängigkeiten installieren

```bash
# Python 3.10+ empfohlen
pip install -r requirements.txt

# oder conda verwenden
conda create -n stock python=3.10
conda activate stock
pip install -r requirements.txt
```

Wenn Windows PowerShell noch die systemseitige Standard-Codepage verwendet, wird empfohlen, vor der ersten Installation der Abhängigkeiten oder der Umgebungsprüfung UTF-8 zu aktivieren, damit Drittanbieter-Tools oder Terminalausgaben nicht an chinesischen Zeichen scheitern:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -m pip install -r requirements.txt
python scripts/check_env.py --config
```

**Abhängigkeiten für den Smart-Import**: `pypinyin` (Namens→Code-Pinyin-Abgleich) und `openpyxl` (Excel-.xlsx-Parsing) sind bereits in `requirements.txt` enthalten und werden bei der obigen `pip install -r requirements.txt` automatisch installiert. Bei Verwendung der Smart-Import-Funktion (Bild/CSV/Excel/Zwischenablage) stelle sicher, dass die Abhängigkeiten korrekt installiert sind; fehlen sie, kann ein `ModuleNotFoundError` auftreten.

### Befehlszeilenargumente

```bash
python main.py                        # Vollständige Analyse (Einzelaktien + Markt-Rückblick)
python main.py --market-review        # Nur Markt-Rückblick
python main.py --no-market-review     # Nur Einzelaktienanalyse
python main.py --stocks 600519,300750 # Bestimmte Aktien angeben
python main.py --portfolio futu       # Futu echte LONG-Aktienpositionen verwenden (überschreibt --stocks/STOCK_LIST)
python main.py --dry-run              # Nur Daten abrufen, keine KI-Analyse
python main.py --no-notify            # Keine Push-Benachrichtigungen senden
python main.py --schedule             # Modus für geplante Tasks
python main.py --force-run            # Auch an Nicht-Handelstagen erzwungen ausführen (Issue #373)
python main.py --debug                # Debug-Modus (detaillierte Logs)
python main.py --workers 5            # Anzahl der parallelen Tasks angeben
```

### Futu echte Positionen als Analyse-Liste

Standard-Quellinstallation (`pip install -r requirements.txt`), offizielle Docker-Images und das Windows/macOS-Desktop-Backend enthalten bereits standardmäßig das gesperrte `futu-api==10.8.6808`. Nur bei Verwendung einer abgespeckten benutzerdefinierten Python-Umgebung muss gemäß [Futu-OpenAPI-SDK-Installationsanleitung](https://openapi.futunn.com/futu-api-doc/en/intro/intro.html) manuell nachinstalliert werden. Starte und logge dich in Futu OpenD ein und führe dann aus:

```bash
# Nur die abgespeckte benutzerdefinierte Umgebung benötigt die nächste Zeile
pip install "futu-api==10.8.6808"
# Alle Standard-Installationen können direkt ausgeführt werden
python main.py --portfolio futu
```

`--portfolio futu` liest fest die realen `REAL`-Wertpapierkonten mit eindeutigem Status `ACTIVE` und aktualisiert die Positionen vor jeder Analyse mit `refresh_cache=True`; Konten mit fehlendem Status, `N/A`, unbekanntem oder `DISABLED`-Status werden abgelehnt. Ohne `FUTU_ACC_ID` werden alle verfügbaren `NORMAL`- (normal) und `MASTER`- (Haupt) Wertpapierkonten zusammengeführt und nach Code dedupliziert; mit Setzung wird nur die angegebene positive ganzzahlige Konto-ID gelesen. Laut [Futu `get_acc_list`-Kontenrollen-Definition](https://openapi.futunn.com/futu-api-doc/trade/get-acc-list.html) steht `MASTER` für das Hauptkonto und nicht für eine Nur-Lese-Eigenschaft; malaysische `IPO`-Konten gehören nicht zu den Positionsquellen dieser Funktion und werden übersprungen. Die Nur-Lese-Grenze dieser Integration rührt daher, dass sie nur Abfrage-Schnittstellen aufruft.

Nur Aktienpositionen mit eindeutiger Richtung `LONG`, statischem Futu-Typ `STOCK` und von Null verschiedener Menge fließen in die Analyse ein; `SHORT`, unbekannte Richtungen, Optionen, ETFs, Warrants, Futures usw. werden ausgeschlossen. Die Futu-Positionscode-Konvertierung unterstützt nur A-Aktien der Börsen Shanghai/Shenzhen, Hongkong-Aktien und US-Aktien; Positionen in Shanghai/Shenzhen-B-Aktien, japanischen und anderen Futu-Märkten werden im Log mit ihrem Code aufgeführt und übersprungen, ohne die bestehende Marktunterstützungsgrenze der manuellen Aktienliste zu ändern. Wenn die verfügbare Konto-ID ungültig ist, die `LONG`-Positionsmenge ungültig ist, ein von Null verschiedener `LONG`-Positionscode ungültig ist, der statische Typ fehlt/unbekannt ist oder ein bestätigter Aktiencode nicht in das aktuelle Analyseformat konvertiert werden kann, schlägt der gesamte Positionsimport explizit fehl und liefert keine stillschweigend gekürzten Teilergebnisse zurück.

Die OpenD-Standardadresse ist `127.0.0.1:11111` und kann über `FUTU_OPEND_HOST`/`FUTU_OPEND_PORT` überschrieben werden. Die Netzwerkschicht des gesperrten `futu-api==10.8.6808` verwendet IPv4-Sockets, daher sollte `FUTU_OPEND_HOST` eine IPv4-Adresse oder einen zu IPv4 auflösbaren Hostnamen enthalten; IPv6-Adressen wie `::1` werden nicht unterstützt. In einem Docker-Container zeigt `127.0.0.1` auf den Container selbst; wenn OpenD auf dem Host läuft, kann unter macOS/Windows `FUTU_OPEND_HOST=host.docker.internal` gesetzt werden; unter Linux muss zuerst die Zuordnung `host.docker.internal:host-gateway` für den Container ergänzt werden, bevor dieser Hostname verwendet wird. Hostübergreifende Verbindungen übertragen echte Konto- und Positionsinformationen; [Futu empfiehlt für Live-Verbindungen die Konfiguration der Protokollverschlüsselung](https://openapi.futunn.com/futu-api-doc/en/ftapi/protocol.html). Diese Funktion ändert nicht die prozessweite SDK-Verschlüsselungskonfiguration; es wird empfohlen, OpenD bevorzugt auf derselben Maschine wie dieses Programm laufen zu lassen oder vertrauenswürdige Netzwerke / lokalen Port-Forwarding zu verwenden. Ohne `FUTU_SECURITY_FIRM` wird nur die offizielle `SecurityFirm.NONE`-Automatik des Futu-SDK einmalig verwendet; es werden keine mehreren Broker enumeriert oder bei teilweise fehlgeschlagener Erkennung stillschweigend Ergebnisse verknüpft; für einen festen Broker kann die Variable explizit konfiguriert werden.

Wenn zugleich `--stocks` übergeben wird, haben Futu-Positionen Vorrang; der geplante Modus liest vor jeder Runde erneut die echten Positionen, statt die Snapshot vom Start wiederzuverwenden. Gibt es keine passenden Futu-Positionen, überspringt diese Runde die Einzelaktienanalyse und fällt nicht auf `STOCK_LIST` zurück; der aktivierte Markt-Rückblick wird weiterhin gemäß ursprünglicher Konfiguration ausgeführt; wenn auch kein Markt-Rückblick angefordert wird, werden Aktienindex und Analyse-Pipeline nicht aktualisiert bzw. aufgebaut, der aktivierte automatische Backtest wird weiterhin als unabhängiger Schritt ausgeführt. Eine einzelne CLI-Ausführung gibt nur dann einen von Null verschiedenen Exit-Code zurück, wenn Positions-Resolution-Grenzen wie SDK, OpenD, Kontoerkennung, Positionslesung oder Wertpapierklassifizierung fehlschlagen; nach erfolgreicher Positionsauflösung folgen Handelstagskalender-, Analyse-Pipeline- und Berichtsanomalien weiterhin der Protokollierungs- und Fehlertoleranz-Semantik des ursprünglichen Analyseablaufs. Bereits gestartete Dienste und geplante Schedules protokollieren Positionsimportfehler und laufen weiter. Diese Fähigkeit liest nur Konten und Positionen und führt keine Auftragserteilung, -änderung, -stornierung oder Handelsfreischaltung aus. Bestehende Analyse-Logs protokollieren die Aktiencodes dieser Runde, aber keine Konto-ID, Positionsmenge, Kosten oder Mittel; vor dem Teilen von Laufzeit-Logs bitte nach Bedarf entschärfen.

---

## Konfiguration geplanter Tasks

### Zeitplanung über GitHub Actions

Bearbeite `.github/workflows/00-daily-analysis.yml`:

```yaml
schedule:
  # UTC-Zeit, Pekinger Zeit = UTC + 8
  - cron: '0 10 * * 1-5'   # Montag bis Freitag 18:00 (Pekinger Zeit)
```

Gängige Zeitumrechnung:

| Pekinger Zeit | UTC-Cron-Ausdruck |
|---------|----------------|
| 09:30 | `'30 1 * * 1-5'` |
| 12:00 | `'0 4 * * 1-5'` |
| 15:00 | `'0 7 * * 1-5'` |
| 18:00 | `'0 10 * * 1-5'` |
| 21:00 | `'0 13 * * 1-5'` |

#### Manuelle Ausführung an Nicht-Handelstagen über GitHub Actions (Issue #461 / #466)

`00-daily-analysis.yml` unterstützt zwei Steuerungsmöglichkeiten:

- `TRADING_DAY_CHECK_ENABLED`: Repository-weite Konfiguration (`Settings → Secrets and variables → Actions`), Standard `true`
- `workflow_dispatch.force_run`: Einmalschalter bei manueller Auslösung, Standard `false`

Empfohlene Prioritäts-Sichtweise:

| Konfigurationskombination | Verhalten an Nicht-Handelstagen |
|---------|-------------|
| `TRADING_DAY_CHECK_ENABLED=true` + `force_run=false` | Ausführung überspringen (Standardverhalten) |
| `TRADING_DAY_CHECK_ENABLED=true` + `force_run=true` | Diese Ausführung erzwingen |
| `TRADING_DAY_CHECK_ENABLED=false` + `force_run=false` | Immer ausführen (weder geplant noch manuell wird der Handelstag geprüft) |
| `TRADING_DAY_CHECK_ENABLED=false` + `force_run=true` | Immer ausführen |

Schritte zur manuellen Auslösung:

1. Öffne `Actions → Tägliche Aktienanalyse → Run workflow`
2. Wähle `mode` (`full` / `market-only` / `stocks-only`)
3. Wenn heute ein Nicht-Handelstag ist und die Ausführung dennoch gewünscht wird, setze `force_run` auf `true`
4. Klicke auf `Run workflow`

### Lokale geplante Tasks

Der eingebaute Scheduler für geplante Tasks unterstützt die Ausführung der Analyse täglich zur angegebenen Zeit (Standard 18:00).

#### Über die Befehlszeile

```bash
# Geplanten Modus starten (einmalige sofortige Ausführung beim Start, danach täglich um 18:00)
python main.py --schedule

# Geplanten Modus starten (keine Ausführung beim Start, wartet nur auf die nächste geplante Auslösung)
python main.py --schedule --no-run-immediately
```

> Hinweis: Der geplante Modus liest vor jeder Auslösung erneut die aktuell gespeicherte `STOCK_LIST`. Wenn zugleich `--stocks` übergeben wird, sperrt dieser Parameter die künftige geplante Aktienliste nicht; für temporäre Ausführungen nur bestimmter Aktien verwende bitte den nicht geplanten Einmal-Befehl.
>
> Nach dem Start über `python main.py --schedule` oder einen gleichwertigen reinen CLI-Schedulermodus werden neue in der WebUI gespeicherte `SCHEDULE_TIME`/`SCHEDULE_TIMES` innerhalb der nächsten Schedule-Prüfung automatisch neu an die Daily-Jobs gebunden, ohne einen Prozess-Neustart; alte Ausführungszeiten bleiben nicht erhalten. `python main.py --serve --schedule` übernimmt die geplanten Tasks über den Web-/API-Runtime-Scheduler; nachdem langlaufende WebUI/API/Desktop-Prozesse `SCHEDULE_ENABLED`, `SCHEDULE_TIME` oder `SCHEDULE_TIMES` speichern, wird der Runtime-Scheduler gemäß der aktuellen Konfiguration gestartet, gestoppt oder neu aufgebaut.
>
> Der Sofort-Ausführungs-Einstieg des Web-/API-Runtime-Schedulers akzeptiert Anfragen nur, wenn gerade keine Analyse läuft; läuft bereits eine Analyse, wird ein Beschäftigt-Status zurückgegeben, statt vorzutäuschen, die Warteschlange hätte Erfolg.

#### Über Umgebungsvariablen

Du kannst das Zeitverhalten auch über Umgebungsvariablen konfigurieren (geeignet für Docker oder .env):

| Variable | Beschreibung | Standardwert | Beispiel |
|--------|------|:-------:|:-----:|
| `SCHEDULE_ENABLED` | Ob geplante Tasks aktiviert sind | `false` | `true` |
| `SCHEDULE_TIME` | Tägliche Ausführungszeit (HH:MM) | `18:00` | `09:30` |
| `SCHEDULE_TIMES` | Mehrere tägliche Ausführungszeiten, durch Kommas getrennt; wenn leer, wird `SCHEDULE_TIME` verwendet | leer | `09:20,12:30,15:10,18:00` |
| `SCHEDULE_RUN_IMMEDIATELY` | Ob im Zeitplanmodus beim Start sofort einmal ausgeführt wird; wenn nicht explizit gesetzt, wird die Laufzeit-Override-Semantik von `RUN_IMMEDIATELY` übernommen | `true` | `false` |
| `RUN_IMMEDIATELY` | Ob im Nicht-Zeitplanmodus beim Start sofort einmal ausgeführt wird; dient zugleich als Legacy-Fallback, wenn `SCHEDULE_RUN_IMMEDIATELY` nicht explizit gesetzt ist | `true` | `false` |
| `TRADING_DAY_CHECK_ENABLED` | Handelstag-Prüfung: An Nicht-Handeltagen wird die Ausführung übersprungen; mit `false` kann eine Ausführung erzwungen werden | `true` | `false` |

Zum Beispiel in Docker konfigurieren:

```bash
# Start ohne sofortige Analyse konfigurieren
docker run -e SCHEDULE_ENABLED=true -e SCHEDULE_RUN_IMMEDIATELY=false ...
```

> Kompatibilitätshinweis: Wenn zur Laufzeit explizit `RUN_IMMEDIATELY` übergeben wird, aber kein separates `SCHEDULE_RUN_IMMEDIATELY`, übernimmt der eingebaute Zeitplanmodus weiterhin Ersteren, damit nicht ein in `.env` persistierter alter Wert von `SCHEDULE_RUN_IMMEDIATELY` überschreibend zurückwirkt.

> Kompatibilitätshinweis (Issue #1815): `MARKET_REVIEW_REGION=cn|hk|us|jp|kr|both` erweitert nur die Eingabemenge des Markt-Rückblicks; JP/KR dienen ausschließlich als Kontext für den Rückblick und aktivieren keine Market-Light-Alarme.
> - Die Änderungen in `src/config.py`, `src/core/config_registry.py` und `src/services/system_config_service.py` sind lediglich semantische Konfigurationserweiterungen; sie verändern weder das Laufzeit-Routing von `provider`/`model`/`base_url` noch lösen sie eine Migration oder Bereinigung von provider/model/base URL aus.
> - Kontrollierte Konfigurationselemente dieser Runde: `MARKET_REVIEW_REGION`, `MARKET_REVIEW_COLOR_SCHEME`; alte Werte wie `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `VISION_MODEL`, `OPENAI_BASE_URL` behalten die atomare Upsert-Semantik und werden beim Aktualisieren anderer Felder nicht stillschweigend geleert oder überschrieben.
> - Zusammenfassung der verifizierbaren Belege: Offizielle provider / Base URL / Modellnamen-Quellen folgen dem [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md#häufig-verwendete-offizielle-dokumentquellen-zur-überprüfung-von-preset-provider--base-url--modellnamen); das aktuelle Laufzeit-Abhängigkeitsfenster folgt `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` in `requirements.txt`; diese Runde fügt kein Konfigurations-Migrationsskript und keinen Bereinigungspfad hinzu, Speichern/Importieren schreibt weiterhin nur die Schlüssel dieses Commits. `tests/test_system_config_service.py::SystemConfigServiceTestCase::test_update_market_review_region_does_not_trigger_runtime_model_cleanup` deckt ab, dass beim nur-Speichern von `MARKET_REVIEW_REGION` alte Konfigurationen wie `LITELLM_CONFIG`, `LLM_CHANNELS`, `LLM_OPENAI_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `VISION_MODEL`, `OPENAI_*` weder geleert noch umgeschrieben werden.
> - Rückfallstrategie für alte Werte: Durch Wiederherstellung des Backups von `MARKET_REVIEW_REGION` und der Konfigurationsdatei kehrt man zur alten Grenze zurück; nicht übertragene Modell-/Routing-Schlüssel behalten ihre ursprünglichen Werte; bei Bedarf den PR `revert` und gemäß `.env`-Backup den Rückfall durchführen.
> - Rollback-Pfad: Vor dem Commit gesicherte `MARKET_REVIEW_REGION` und zugehörige Laufzeitvariablen aus `.env` / Konfigurations-Backups wiederherstellen oder direkt diesen PR revertieren.

#### Handelstag-Erkennung (Issue #373)

Standardmäßig wird anhand der Watchlist-Märkte (A-Aktien / Hongkong-Aktien / US-Aktien / japanische Aktien / koreanische Aktien) und `MARKET_REVIEW_REGION` bestimmt, ob es sich um einen Handelstag handelt:
- `exchange-calendars` wird verwendet, um die jeweiligen Handelskalender (inkl. Feiertage) von A-Aktien / Hongkong-Aktien / US-Aktien / japanischen Aktien / koreanischen Aktien zu unterscheiden
- Bei gemischten Positionen wird jede Aktie nur an Marktöffnungstagen ihres Marktes analysiert; Aktien ruhender Märkte werden an diesem Tag übersprungen
- Sind alle relevanten Märkte Nicht-Handelstage, wird die Ausführung insgesamt übersprungen (keine Pipeline, keine Push-Benachrichtigung)
- Die "Daten bereits vorhanden"-Prüfung von Fortsetzungsunterstützung und `--dry-run` nutzt dieselbe Logik zur Auflösung des "zuletzt wiederverwendbaren Handelstags" und verwendet nicht mehr direkt den Server-Kalendertag
- Der `zuletzt wiederverwendbare Handelstag` wird in der lokalen Zeitzone des jeweiligen Aktienmarktes aufgelöst: A-Aktien verwenden `Asia/Shanghai`, Hongkong-Aktien `Asia/Hong_Kong`, US-Aktien `America/New_York`, japanische Aktien `Asia/Tokyo`, koreanische Aktien `Asia/Seoul`
- Bei Ausführung an Nicht-Handelstagen (Wochenende / Feiertage) wird auf den zuletzt abgeschlossenen Handelstag für die lokale Datenprüfung zurückgegriffen; sind die Daten dieses Handelstags bereits vorhanden, wird das erneute Abrufen übersprungen, andernfalls wird nachgeladen
- Bei Ausführung während der Handelszeit oder vor Handelsschluss wird der zuletzt abgeschlossene Handelstag als Wiederverwendungsziel verwendet; bei Ausführung nach Handelsschluss werden die Daten des Tages direkt übersprungen, wenn sie bereits vorhanden sind, andernfalls wird abgerufen
- Überschreiben: `TRADING_DAY_CHECK_ENABLED=false` oder Kommandozeilen-Flag `--force-run`

#### Marktphasen-Baseline (Issue #1386 P0)

P0 fügt lediglich eine interne Baseline zur Marktphasen-Erkennung hinzu und verändert nicht das Standardverhalten des bestehenden täglichen Abschlussberichts, des Handelstag-Skippings, der Fortsetzungsunterstützung, der API, des Web, des Bots, des Agents oder der GitHub Actions. Die Phasen-Erkennung dient der Vorbereitung des Kontextvertrags für spätere P1+; wenn `exchange-calendars` nicht installiert ist oder der Kalender fehlerhaft ist, gibt die Phase `unknown` zurück, während die bestehende Handelstag-Erkennung und die Logik des zuletzt wiederverwendbaren Handelstags weiterhin ihr bisheriges fail-open-Verhalten behalten.

Die Phasen-Enumeration basiert auf der Semantik der regulären Sitzung:

| Phase | Bedeutung |
| --- | --- |
| `premarket` | Vor Beginn der regulären Handelszeit; bedeutet nicht, dass bereits erweiterte vorbörsliche Kursdaten abgerufen wurden |
| `intraday` | Innerhalb der regulären Handelszeit und nicht in der Mittagspause oder im Fenster kurz vor Handelsschluss |
| `lunch_break` | Vom Marktkalender bereitgestelltes Mittagspausen-Fenster; Märkte ohne Mittagspause treten nicht in diese Phase ein |
| `closing_auction` | Heuristik-Fenster kurz vor Handelsschluss: A-Aktien 3 Minuten, Hongkong-Aktien 10 Minuten, US-Aktien 5 Minuten, taiwanische Aktien 5 Minuten (13:25–13:30); stellt nicht das vollständige Börsenauktionssystem dar |
| `postmarket` | Nach Schluss der regulären Handelszeit; bedeutet nicht, dass bereits erweiterte nachbörsliche Kursdaten abgerufen wurden |
| `non_trading` | Das lokale Datum des aktuellen Marktes ist kein Handelstag |
| `unknown` | Unbekannter Markt, Kalender nicht verfügbar oder Kalenderfehler; die Phase kann nicht zuverlässig bestimmt werden |

Aktueller Stand der Einstiegspunkte:

- Gewöhnliche Einzelaktienanalyse, Agent-Analyse, manuelle Web-Analyse, Bot `/analyze` / `/ask`, Schedule und GitHub Actions verwenden weiterhin die bisherigen Analysepfade und die Rückblick-Ausrichtung nach Handelsschluss; durch die P0-Phasen-Baseline wird kein Prompt oder Ausgabestruktur automatisch umgestellt.
- Der Markt-Rückblick läuft weiterhin gemäß `MARKET_REVIEW_REGION` und der Filterung auf Handelstage und konsumiert keine Marktphasen-Labels.
- Bei gemischten Märkten in der Watchlist sollte die Phase pro Symbol nach dessen eigenem Markt bestimmt werden; die Anzeige von "inkonsistente Marktphasen" in aggregierten Berichten bleibt P1+ überlassen.

Bekannte Problem-Baseline:

- Bei Auslösung während der Handelszeit könnte der Bericht die noch nicht abgeschlossenen Intraday-Kurse weiterhin als vollständigen Handelstags-Rückblick darstellen.
- Die Ausgabe neigt weiterhin zu "Rückblick des heutigen Verlaufs / Fokus auf morgen" statt "nächste Beobachtung des aktuellen Intraday-Verlaufs".
- Echtzeit-Kurszeitstempel, Datenquellen, Cache und Stale-Status sind noch nicht einheitlich in den Phasenkontext eingegangen.
- Szenarien wie Mittagspause, kurz vor Handelsschluss und erzwungene Ausführung an Nicht-Handelstagen sind noch nicht explizit durch Prompt und Berichtsstruktur ausgedrückt.

P0 macht nicht: keine Anbindung an Pipeline / Agent / API / Web / Bot, keine Änderung des Report-Schemas, keine Änderung der partial-bar-Bewertung von Technical-Indicator-Alarmen und keine neuen Konfigurationsoptionen.

#### Laufzeit-Marktphasenkontext (Issue #1386 P1a)

P1a konstruiert und übergibt einen internen `market_phase_context` in der gewöhnlichen Einzelaktienanalyse-Pipeline, im Legacy-Agent-Kontext und in `ctx.meta` des Multi-Agent-Systems. Dieser Kontext enthält Markt, Phase, lokales Marktdatum, zuletzt wiederverwendbares Tagesdaten-Datum, die dreistufigen Markierungen Handelstag / Markt geöffnet / partial bar, eine best-effort-Schätzung der Minuten bis Eröffnung/Schluss sowie Degradierungs-Warncodes wie `unknown_market`, `calendar_unavailable` und `calendar_error`.

P1a selbst ändert keine Prompt-Texte, API/Web/Bot-Parameter, Reportstrukturen, stabile Metadaten von history/task status oder die Semantik von quote freshness/data quality; der History-Snapshot der gewöhnlichen Analyse und der Agent-History-Snapshot entfernen dieses Laufzeitfeld. Später definiert P1b den Vertrag für persistierbare Metadaten und die Anzeige des Task-Status.

#### Marktphasen-Metadaten mit niedriger Sensibilität (Issue #1386 P1b)

P1b projiziert den Laufzeit-`market_phase_context` von P1a auf eine stabile, niedrigsensible, öffentlich verfügbare `market_phase_summary` und schreibt sie auf die oberste Ebene von `analysis_history.context_snapshot`. Historie-Details, synchrone Analyseantworten und abgeschlossene `/api/v1/analysis/status/{task_id}` geben dieselbe Marktphasen-Metainformation über `report.meta.market_phase_summary` zurück; der abgeschlossene Task-Status erhält kein neues Feld auf `TaskStatus`-Top-Level, sondern legt es nur indirekt über `status.result.report.meta.market_phase_summary` offen.

`market_phase_summary` enthält nur Markt, Phase, lokale Marktzeit, session date, effective daily-bar date, die Markierungen Handelstag / Markt geöffnet / partial-bar, Minuten bis Eröffnung/Schluss, Auslösequelle, Analyseabsicht und Warncodes. Es legt weder den vollständigen `market_phase_context` offen noch fügt es Felder wie quote freshness, fallback, stale oder data_quality scoring hinzu. `report.details.analysis_context_pack_overview` beschreibt weiterhin die Qualitätszusammenfassung der Eingabedatenblöcke aus #1389; das von der API zurückgegebene `details.context_snapshot` entfernt die Top-Level-Felder `market_phase_summary` und `analysis_context_pack_overview`, damit der Roh-Snapshot diese stabilen öffentlichen Felder nicht doppelt anzeigt. Bei `SAVE_CONTEXT_SNAPSHOT=false` wird nicht die gesamte `analysis_history.context_snapshot` persistiert; fehlt der Summary bei alten History-Einträgen, ist das Feld leer, und der Bericht wird weiterhin normal zurückgegeben.

P1b ändert keine Prompts, fügt keinen `analysis_phase`-Anfrageparameter hinzu, macht keine Web-Phasenlabels oder Seitenanzeigen und überschreibt weder das TaskPanel für pending/processing noch laufende SSE-Ereignisse, den Bot, Benachrichtigungen, `market_review` oder die Intraday-Datenqualitätsfelder aus P3.

#### Marktphasen-Prompt-Injektion (Issue #1386 P2-min)

P2-min beginnt damit, in Analysepfaden, die bereits `market_phase_context` erhalten haben, die Laufzeit-Marktphase als LLM-lesbaren Prompt-Block zu rendern. Gewöhnliche Analyse, single Agent und multi-agent sehen im Prompt die aktuelle Phase, die lokale Marktzeit, das zuletzt wiederverwendbare vollständige Tagesdaten-Datum sowie die minimalen Phaseneinschränkungen: Vorbörslich darf "der heutige Verlauf ist bereits erfolgt" nicht beschrieben werden; während der Handelszeit / Mittagspause / kurz vor Schluss muss angegeben werden, dass die letzte Tageskerze möglicherweise unvollständig ist; nach Börsenschluss bleibt die vollständige Handelstags-Rückblick-Semantik erhalten; bei Nicht-Handelstagen oder unbekannter Phase wird konservativ formuliert.

P2-min fügt weiterhin keine API/Web/Bot-Parameter hinzu, schreibt nichts in history/task status/report metadata, ändert das JSON-Schema des Berichts nicht und führt keinen vollständigen Vertrag für quote freshness, fallback, stale oder data_quality ein. Bot/API-Direktverbindungen zum Agent, die `market_phase_context` nicht über die P1a-Pipeline aufbauen, behalten das alte Verhalten; Durchreichen und sichtbare Anzeige der Einstiegspunkte bleiben späteren P4+ vorbehalten.

#### Intraday-Datenpaket und Echtzeit-Qualitätskontrolle (Issue #1386 P3)

P3 ergänzt die Qualitätsmetadaten für Echtzeitkurse, die der Hauptpfad der gewöhnlichen Analyse verwendet, fügt aber weiterhin keinen `analysis_phase`-Parameter hinzu, ändert keine API/Web/Bot-Phaseneinstiegspunkte, verändert das JSON-Schema des Berichts nicht und macht keine Datenqualitätsbewertung oder Modellkonfidenzbeschränkung aus #1389 P5. Echtzeit-Quote trägt `fetched_at`, `provider_timestamp`, `is_stale`, `stale_seconds` und `fallback_from`; `fetched_at` ist die Systemabrufzeit, `provider_timestamp` wird nur ausgefüllt, wenn der Provider tatsächlich eine Kurszeit liefert. Fehlt die Providerzeit, wird keine falsche Frische vorgetäuscht, und `stale_seconds` und `is_stale` bleiben leer.

Die Semantik des gesamten Quellen-Fallbacks ist festgelegt: `source` behält das Token der tatsächlich erfolgreichen Datenquelle, `fallback_from` zeichnet das Token der höchstpriorisierten gesamten Quelle auf, die in dieser Runde fehlgeschlagen ist; wenn nach erfolgreicher bevorzugter Quelle nur Felder aus nachfolgenden Quellen ergänzt werden, wird `fallback_from` nicht geschrieben. `AnalysisContextBuilder` mappt nur diese Upstream-Artefakte, ruft keine Daten erneut ab und macht keine Qualitätsbewertung; der Status des Quote-Blocks wird nach `STALE > FALLBACK > AVAILABLE` zusammengeführt. Wenn Intraday-Echtzeitkurse `today` überschreiben, werden `is_partial_bar`, `is_estimated`, `estimated_fields`, `realtime_source` und die Quote-Metadaten markiert; der `daily_bars`-Block repräsentiert weiterhin das vollständige Tagesdatenfenster im Storage, partial/estimated fließen nur in den technical-Block ein. Freshness-Scoring, gestufte Intraday-Cache-TTLs, Wiederverwendung auf Agent-Tool-Ebene und API/Web-Anzeige bleiben späteren Phasen überlassen.

#### Analysephasen-Einstieg und Task-Queue-Durchreichung (Issue #1386 P4a)

P4a fügt den Anfrageparameter `analysis_phase=auto|premarket|intraday|postmarket` hinzu, Standard `auto`, mit dem API-Aufrufer die Analysephase dieser Ausführung explizit überschreiben können. Der Parameter wird derzeit an `POST /api/v1/analysis/analyze`, die asynchrone Task-Queue, `AnalysisService`, die gewöhnliche Analyse-Pipeline und den Marktphasenkontext angebunden; Web-Frontend-Typen und API-Mapper haben das Feld übernommen, fügen aber keinen Seiten-Selector hinzu; Bot, Schedule, GitHub Actions und DB-Migration sind in dieser Phase nicht enthalten.

`analysis_phase` ist der Anforderungswert; die endgültige Berichtsphase richtet sich weiterhin nach `report.meta.market_phase_summary.phase`. Die asynchrone accepted-Antwort, der In-Memory-Task-Status, die Task-Liste und die SSE-Payload spiegeln die angeforderte Phase wider; der History-DB-Fallback fügt kein persistiertes Feld hinzu, alte Einträge können weiterhin leer sein. Derselbe Befehl mit unterschiedlichen Phasen wird weiterhin über denselben Aktien-Task dedupliziert, um parallele doppelte Analysen zu vermeiden.

Der interne Phasenkontext bleibt mit dem alten Parameter `analysis_intent` kompatibel: Nur wenn `analysis_phase` auf `auto` bleibt, wird ein nicht-`auto`-`analysis_intent` zur Phase dieser Anfrage normalisiert; externe Aufrufer sollten bevorzugt `analysis_phase` verwenden.

`auto` behält die bestehende Kalender-Erkennung des Handelstags bei; nicht-`auto` überschreibt nur die Phase und berechnet `is_trading_day`, `is_market_open_now`, `is_partial_bar`, `minutes_to_open` und `minutes_to_close` neu. Das Überschreiben verändert weder die echte `market_local_time` noch `effective_daily_bar_date`; wenn das aktuelle Datum kein Handelstag ist oder der Kalender die entsprechende Sitzung nicht unterstützt, können die Minutenfelder leer sein.

#### Web-Phasenlabel-Anzeige (Issue #1386 P4b)

P4b ergänzt im Web die Sichtbarkeit der Phase, fügt aber keinen Phasen-Override-Selector hinzu. Das TaskPanel für laufende Aufgaben zeigt nur die von P4a zurückgespiegelte angeforderte Phase `analysis_phase` an, wobei `auto` klar als "Automatische Phase" angezeigt wird und nicht als endgültige ermittelte Phase getarnt wird. Die endgültige Berichtsseite zeigt die tatsächliche Marktphasenlabel über `report.meta.market_phase_summary.phase` und weist bei `is_partial_bar=true` auf "Tageskerze unvollständig" hin.

Die Datenqualitätszusammenfassung verwendet weiterhin `report.details.analysis_context_pack_overview.data_quality` und die bestehende `AnalysisContextSummary`; das Web zeigt auf derselben Berichtsdetailseite das Phasenlabel an und verwendet weiterhin die niedrigsensible Datenqualitätszusammenfassung, ohne das vollständige `AnalysisContextPack`, die Prompt-Zusammenfassung, rohe Payloads oder bereits entfernte Snapshot-interne Felder offenzulegen. Historienliste, Bot, Schedule, GitHub Actions, Desktop, Benachrichtigungszusammenfassungen und erweiterte Phasen-Override-Einstiege bleiben spätere Arbeiten.

#### AnalysisContextPack-Prompt-Zusammenfassung (Issue #1389 P3)

P3 bindet die niedrigsensible Zusammenfassung `AnalysisContextPack` in den gewöhnlichen Analyse- und Agent-Initialkontext ein. Die Pipeline setzt das Pack aus bereits abgerufenen Kursen, Tagesdaten, Trends, Chips, Fundamentaldaten, Nachrichten und Marktphasen-Artefakten zusammen und fügt `analysis_context_pack_summary` in den Prompt ein; in diesem neuen Pack-Zusammenfassungsblock sieht die LLM nur subject, Version, Status/Quelle/Warnung/fehlenden Grund der einzelnen Datenblöcke und die Anzahl der Nachrichtenergebnisse und sieht über diesen Block weder vollständiges `news.content`, `trend_result`, Chip- noch Fundamentaldaten-Rohpayloads. Die bestehenden Kanäle `news_context`, Agent pre-fetched JSON und `enhanced_context` für Rohdaten behalten ihr Verhalten vor P3 und werden weder durch diese Zusammenfassung ersetzt noch entschärft.

P3 fügte damals keine API/Web/Bot-Parameter hinzu, schrieb nichts in history/task status/report metadata, veränderte das JSON-Schema des Berichts nicht und legte das vollständige Pack weder in History noch in Benachrichtigungen noch im Web offen. Wiederverwendung von Pack-Daten auf Agent-Tool-Ebene und das Datenqualitäts-Scoring aus P5 bleiben späteren Phasen überlassen.

#### Eingabezusammenfassung für Multi-Agent-Meinungsdivergenzen (Issue #1904 P1 plumbing)

Multi-Agent konstruiert vor dem Eintritt in `DecisionAgent` eine interne niedrigsensible `agent_disagreement_summary`, um Richtungsdivergenzen früherer Agent-Meinungen, Nachweise für Risiko-Overrides, ob Risiko-Overrides durch die aktuelle `AGENT_RISK_OVERRIDE`-Konfiguration aktiviert sind, sowie Degradierungsinformationen nicht kritischer Phasen hinzuweisen. Diese Zusammenfassung enthält nur Agentname, Signal, Konfidenz, Konflikttyp, Hinweis auf den Entscheidungspfad, den niedrigsensiblen Risikokontrollstatus und den Marker für degradierte Phasen, nicht jedoch reasoning, raw_data, ursprüngliche Fehlertexte, Token oder private Payloads.

Diese Fähigkeit ist derzeit nur eine interne Prompt-Eingabepipeline von `DecisionAgent`: Die Zusammenfassung wird in das Laufzeit-`ctx.meta` geschrieben, geht nicht in pre-fetched Daten des Agents ein und fügt keine öffentlichen APIs, Web/Desktop-Anzeigen, history/task status/report metadata, Dashboard-Schemas oder endgültige Erklärungsfelder hinzu. `risk_level=high` dient nur als Risikobeleg und löst allein keinen Override aus; die Zusammenfassung und das endgültige `_apply_risk_override()` verwenden denselben Override-Mechanismus und respektieren `AGENT_RISK_OVERRIDE=false`. Nicht kritische Degradierungsphasen folgen den Degradierungsverträgen des Orchestrators für `intel`, `risk` und specialist/skill-Agents, um eine einseitige Meinung nicht fälschlich als Multi-Agent-Konsens darzustellen. Die benutzersichtbare endgültige Erklärungsausgabe von #1904 gehört weiterhin zu einer späteren Phase.

`AgentResult.runtime_facts` ist ein internes optionales Feld zum Speichern der in dieser Orchestrator-Ausführung bereits gesammelten Basis-Agent-Meinungen, Degradierungsereignisse, Pipeline-Terminierung und tatsächlichen Risikoanwendung. Degradierungsereignisse verwenden `DURING_STAGE`, um ein eigenes Scheitern der Stufe zu unterscheiden, und `BEFORE_STAGE`, um anzuzeigen, dass die Stufe wegen Pipeline-Deadline oder Budget-Guard nicht gestartet wurde. Wird die Deadline-Prüfung ausgelöst, nachdem eine Stufe bereits abgeschlossen ist, wird diese Stufe nicht als Timeout-Degradierung aufgezeichnet; `pipeline_termination.last_completed_stage` wird aus dem letzten echten `COMPLETED`-Ergebnis von `AgentRunStats.stage_results` bezogen und kann auch leer sein.

Das strukturierte Orchestrator-Dashboard wird in der Reihenfolge Input-Vorbereitung, einzelne Risikoanwendung und post-risk-Finalisierung verarbeitet. Die post-risk-Finalisierung aktualisiert Top-Level-Entscheidungs-/Handlungsempfehlung, Kernsignal-/Positionsempfehlung, battle-plan-Positionsstrategie sowie das Signal/canonical-Payload von `DecisionAgent`. Diese Phase behandelt keine richtungsweisenden Formulierungen in anderem Freitext des Dashboards; runtime facts und post-risk-Agent-Dashboard stellen auch keine endgültige Pipeline-Entscheidung dar und erzeugen keine öffentlichen explanation-Felder.

Nachdem Multi-Agent-Ergebnisse in `StockAnalysisPipeline` eingehen, werden Struktur und Kapitalfluss, Marktphase und daily-market context vervollständigt. Das System aktualisiert nach jedem Schritt, der öffentliche Aktionen verändern könnte, über denselben Parse-Einstieg wie den DecisionSignal-Builder die Acht-Zustands-Aktion und zeichnet die tatsächlichen `from_action`/`to_action`-Übergänge in Ausführungsreihenfolge auf. Nur wenn Start der Anpassungskette, jede Zwischenaktion und die endgültige Aktion eindeutig durch die gemeinsame Regel auflösbar sind, erzeugt das System basierend auf `AgentResult.runtime_facts` deterministisch das optionale `dashboard.agent_disagreement_explanation`. Dieses Feld verwendet `pipeline_start_action` als Startpunkt der Anpassungskette und `final_action` als einzige autoritative endgültige Schlussfolgerung; `final_action` stimmt mit der Berichts-`action`, der History-Aktion und der `DecisionSignal.action` überein. Der dreistufige `decision_type` dient nicht mehr als endgültige Schlussfolgerung der Erklärung; `risk_control.post_risk_signal` bleibt nur als statistischer Hintergrundfakt der Agent-Risikokontrollphase.

Top-Level- oder verschachtelte gleichnamige Erklärungen, die vom Modell zurückgegeben werden, werden an der Parse-Grenze des gemeinsamen Agent-Dashboards entfernt, und das endgültige Feld wird ausschließlich von der Pipeline konstruiert. Unzulässige Agent-Signale werden gemäß der bestehenden Gültigkeitsregel für Strategiemeinungen aus runtime facts und öffentlichen Divergenzstatistiken ausgeschlossen und nicht stillschweigend in `hold` umgewandelt. Wenn Freitext nicht eindeutig in eine Acht-Zustands-Aktion auflösbar ist, bleibt der gemeinsame Resolver fail-closed: Der Bericht und die Historie behalten `action=None`, erzeugen keine Erklärung und auch keinen DecisionSignal; die Pipeline füllt keine Werte privat über `decision_type` nach. Das Feld wird bei vorhandener kanonischer Aktion zusammen mit dem Dashboard persistiert und vor der DecisionSignal-Extraktion abgeschlossen. Alte Berichte, single Agent/Nicht-Agent-Pfade und kompatible Aufrufe ohne `runtime_facts` müssen das Feld nicht enthalten; diese Phase fügt keine Web/Desktop-spezifische Anzeige, keine vollständigen Traces und keine Gewichtungs- und Audit-Fähigkeiten aus P2-P4 hinzu.

#### Niedrigsensible Sichtbarkeit von AnalysisContextPack (Issue #1389 P4)

P4 fügt `report.details.analysis_context_pack_overview` hinzu; Historie-Details und abgeschlossene `/api/v1/analysis/status/{task_id}` geben dieselbe niedrigsensible Übersicht aus dem bereits persistierten `context_snapshot` zurück; auch synchrone Analyseantworten lesen die bereits gespeicherte `analysis_history.context_snapshot` dieser Ausführung, um die Übersicht zu extrahieren, sodass bei `SAVE_CONTEXT_SNAPSHOT=false` neue Einträge nicht garantiert dieses Feld zurückgeben. Die Web-Berichtsseite zeigt nach "Strategiepunkten" und "Informationen" eine standardmäßig eingeklappte Datenblock-Zusammenfassung; der eingeklappte Kopf zeigt verfügbare Anzahl, fehlende Anzahl, Zählungen anderer Nicht-Null-Status und Auslösequelle, und nach dem Aufklappen werden Datenblock-Status, Quelle, Warnung, fehlender Grund, Statuszählungen und Anzahl der Nachrichtenergebnisse angezeigt. Das von der API zurückgegebene `details.context_snapshot` entfernt das Top-Level-`analysis_context_pack_overview`, damit das Transparenzpanel den Roh-Snapshot nicht doppelt anzeigt.

Diese Übersicht enthält weder das vollständige Pack, den Prompt-String `analysis_context_pack_summary`, `items.value`, den Nachrichtentext, `trend_result`, Chip- noch Fundamentaldaten-Rohpayloads. Bei `SAVE_CONTEXT_SNAPSHOT=false` wird nicht die gesamte `analysis_history.context_snapshot` persistiert, daher wird die Übersicht auch nicht aus neuen History-Einträgen gelesen; fehlt die Übersicht bei alten History-Einträgen, ist das Feld leer, und der Bericht wird weiterhin normal zurückgegeben. Diese Phase überschreibt weder das TaskPanel für pending/processing, laufende SSE-Ereignisse, Benachrichtigungszusammenfassungen, Bot/Desktop-spezifische Anzeigen, die `market_review`-Übersicht noch das Datenqualitäts-Scoring.

#### Datenqualitäts-Scoring von AnalysisContextPack und Prompt-Datenbegrenzung (Issue #1389 P5)

P5 fügt, ohne `PACK_VERSION = "1.0"` zu ändern, ohne neue Datenquellen und ohne das JSON-Schema des Berichts zu verändern, eine leichte Datenqualitätsbewertung und einen modelllesbaren Block zur Datenbegrenzung für `AnalysisContextPack` hinzu. `ContextFieldStatus` erhält `fetch_failed`, das nur bedeutet, dass der Abruf des Felds oder Datenblocks in dieser Ausführung eindeutig fehlgeschlagen ist; die erste Version mappt nur `fundamental_context.status == "failed"` auf `fetch_failed`; leere Nachrichten, nicht konfigurierte Suche, kein Echtzeit-Quote oder fehlende Chips werden weiterhin gemäß dem bestehenden `missing`/`not_supported` behandelt.

`DataQuality` enthält jetzt `overall_score`, `level`, `block_scores` und `limitations` und behält die alten `warnings`/`metadata` bei. Die Bewertung deckt fest die sechs Blöcke `quote`, `daily_bars`, `technical`, `news`, `fundamentals` und `chip` ab und wird bei fehlenden Hilfsblöcken nicht neu normalisiert; Degradierung von Kernblöcken verlangt im Prompt-Block "Datenbegrenzung", dass das Modell keine hohe Konfidenz ausgibt, während fehlende Hilfsblöcke nur den jeweiligen Analyseabschnitt begrenzen und nicht als bullisch oder bärisch interpretiert werden sollten. Dieser Prompt-Block wird einheitlich von `format_analysis_context_pack_prompt_section()` erzeugt; gewöhnliche Analyse, single Agent und multi-agent verwenden dieselbe niedrigsensible Zusammenfassung, ohne Rohpayloads, Nachrichtentexte, Trendrohwerte, Secrets, Token oder Webhooks offenzulegen.

Historie-Details, synchrone Analyseantworten und abgeschlossene Task-Zustände legen weiterhin nur niedrigsensible Felder über `report.details.analysis_context_pack_overview` offen; P5 fügt unter dieser Übersicht nur `data_quality` mit score, level, block_scores und limitations hinzu und wiederholt nicht öffentlich `warnings`. Die Web-Berichtsseite zeigt die Datenblock-Zusammenfassung weiterhin standardmäßig eingeklappt; der eingeklappte Kopf zeigt Qualitätspunktzahl/Stufe, nach dem Aufklappen werden Begrenzungshinweise und der `fetch_failed`-Status angezeigt; `details.context_snapshot` entfernt weiterhin das Top-Level-`analysis_context_pack_overview`.

#### AnalysisContextPack-Dokumentation, Migration und Rollback (Issue #1389 P6)

P6 macht nur Dokumentations- und Konfigurationssichtbarkeitsabschluss, fügt kein Pack-Runtime, kein Enable/Disable-Feature-Flag für das Pack, keine Änderung von `PACK_VERSION = "1.0"`, keine API-Parameter, keine Änderung des JSON-Schemas des Berichts und keine Datenbankmigration hinzu. Vollständiger Vertrag, Feldstatus, Sichtbarkeit der niedrigsensiblen Zusammenfassung, Entschärfungsgrenzen, Migration und Rollback-Hinweise finden sich im [AnalysisContextPack-Themendokument](analysis-context-pack.md).

`SAVE_CONTEXT_SNAPSHOT` ist eine bestehende Umgebungsvariable; P6 synchronisiert sie nur in `.env.example`, das Konfigurationsregister und die Web-Einstellungshilfe. Standard `true`; bei `false` oder mit CLI `--no-context-snapshot` wird für neue History-Einträge nicht mehr die gesamte `analysis_history.context_snapshot` persistiert, einschließlich `enhanced_context`, `market_phase_summary`, `analysis_context_pack_overview`, Diagnose-Snapshots und Roh-Snapshot-Felder. Diese Einstellung deaktiviert weder die `AnalysisContextPack`-Konstruktion dieser Ausführung, entfernt nicht die niedrigsensible `analysis_context_pack_summary` aus dem Prompt und verändert weder das JSON-Schema der Analyseergebnisse noch die API-Anfrageparameter.

Derzeit gibt es keinen Laufzeit-Gesamtschalter für das Pack; um die Pack-Prompt-Zusammenfassung, die Übersicht oder die Datenqualitätsanbindung von P3-P5 zu deaktivieren, kann dies nur über Release- oder Code-Rollback erfolgen. Alte History-Einträge ohne `analysis_context_pack_overview`/`data_quality` geben weiterhin leere Felder zurück, und das Berichtslesen bleibt kompatibel.

#### Marktstruktur-Kontext (Issue #1909)

Die Einzelaktienanalyse erhält jetzt einen niedrigsensiblen `market_structure_context` und legt ihn über `AnalysisReport.details.market_structure` für Historie-Details, synchrone Analyseantworten und abgeschlossene Task-Zustände offen. Das Feld verwendet eine zweistufige Struktur: `market_theme_context` repräsentiert die Markt-/Themenebene und enthält Branchen-/Konzeptrankings der A-Aktien, aktive Themen, führende Branchen/Konzepte, Themenbreite und Datenqualität; `stock_market_position` repräsentiert die Einzelaktien-Positionsebene und enthält den Sektor der Aktie, das primär assoziierte Thema, die Themenphase, die Aktienposition, Risikolabel und fehlende Belege.

Die erste Marktstrukturversion wird von einem nativen DSA-Dienst auf Basis von `DataFetcherManager.get_sector_rankings()`, `get_concept_rankings()` und `fundamental_context.belong_boards` erzeugt und ruft die eingebaute Aktienauswahl-Engine nicht auf. Hotspot-Details, Gärungsrouten, Bestandteile und Leader-Stocks der eingebauten Aktienauswahl, die auf AlphaSift-Implementierung verweisen, können als spätere optionale Datenquellen dienen, werden aber derzeit nicht implizit von der gewöhnlichen Einzelaktienanalyse aufgerufen. Fehlen Belege für Bestandteile oder Leader, bleibt `stock_role` standardmäßig `follower/edge/unknown` und markiert in `missing_fields` die Werte `hotspot_constituents` und `leader_stocks`, um gewöhnliche assoziierte Aktien nicht fälschlich als Themenführer zu beschreiben.

Kompatibilitätsgrenze: Die provider/model-Snapshot-Felder in `market_structure_context` (einschließlich `model_used`, `market_structure_context.*.source.provider` usw.) dienen nur der historischen Nachverfolgung und Seitenanzeige und stellen keinen Eingang für LLM-provider-Routing, `base URL` oder `provider/model`-Laufzeitkonfiguration dar; sie lösen weder eine Bereinigung, ein Zurückschreiben, eine Migration noch eine stillschweigende Änderung der `.env`-Konfiguration aus.

Gewöhnliche LLM-, single-Agent- und multi-agent-Prompts erhalten die niedrigsensible Marktstruktur-Zusammenfassung injiziert; die automatische DecisionSignal-Extraktion schreibt `primary_theme`, `theme_phase`, `stock_role`, Versionsnummer und Risikolabel in die Metadaten, ohne Hauptfelder, Deduplizierungsschlüssel oder Lebenszyklusregeln zu verändern. Die Web-Berichtsseite zeigt nach der Übersicht eine Karte "Marktposition" mit getrennten Anzeigen für die Markt-/Themenebene und die Einzelaktien-Positionsebene; alte History-Einträge ohne dieses Feld zeigen sie nicht an. Nicht-A-Aktien-Märkte geben in der ersten Version `not_supported` zurück, ohne den bestehenden Bericht zu beeinflussen.

#### Intraday-Entscheidungs-Schutzmaßnahmen und Qualitätsprüfung (Issue #1386 P5)

P5 fügt im `dashboard.phase_decision` des Einzelaktienanalyse-Berichts stufenweise Entscheidungsfelder hinzu: `phase_context`, `action_window`, `immediate_action`, `watch_conditions`, `next_check_time`, `confidence_reason` und `data_limitations`. Dieses Feld geht nur als rückwärtskompatible Erweiterung des Berichts-JSON in das rohe `raw_result` der Historie ein; es fügt keinen `analysis_phase`-API-Parameter hinzu, verändert keine Web-Phaseneinstiegspunkte, fügt keine Konfigurationsoptionen hinzu und beeinflusst das Standardverhalten des täglichen Abschluss-Rückblicks nicht.

Gewöhnliche Analyse und Agent-Analyse führen vor dem Speichern der Historie mithilfe der diesmaligen `market_phase_summary` und `analysis_context_pack_overview.data_quality` leichte Schutzmaßnahmen durch: Bei stale, fallback, missing, fetch_failed, partial oder estimated der Kernquote-/daily_bars-/technical-Daten sind keine hochkonfidenziellen Schlussfolgerungen zulässig; vor Börsenbeginn, an Nicht-Handelstagen oder bei unbekannter Phase dürfen keine hochkonfidenziellen Intraday-Kauf-/Verkaufsempfehlungen ausgegeben werden; während der Handelszeit, in der Mittagspause und kurz vor Schluss wird der Abschluss-Rückblick-Ton in der Hauptschlussfolgerung geprüft und Formulierungen wie "der Rückblick nach heutigem Schluss zeigt" oder "morgen besonders beobachten" in phasensichere Beobachtungs-/Wartende-Formulierungen umgewandelt. Die Schutzmaßnahmen ergänzen nur niedrigsensibles `phase_context` und Datenbegrenzungen und erfinden keine Beobachtungsbedingungen oder nächsten Prüfzeiten; die Anbindung an Benachrichtigungszusammenfassungen, Alarme, Positionen und Backtests bleibt späterem P6 überlassen.

#### Signalattributionsanalyse (Issue #1742)

Issue #1742 fügt im `dashboard.signal_attribution` des Einzelaktienanalyse-Berichts ein Feld zur Signalattributionsanalyse hinzu: `technical_indicators`, `news_sentiment`, `fundamentals`, `market_conditions` (vier Beitragsanteile; gültige, von Null verschiedene Beitragsanteile werden auf 100 normalisiert; alle Null bedeuten keine gültigen Signale), `strongest_bullish_signal` und `strongest_bearish_signal`. Dieses Feld erklärt die Zusammensetzung der Empfehlungsbegründung und hilft dem Benutzer, die Attributionsgewichte der KI-Entscheidung zu verstehen.

Die Signalattributionsanalyse wird synchron auf allen Berichts-Rendering-Pfaden angezeigt:
- `generate_dashboard_report()` (Standard-Benachrichtigungsbericht)
- `generate_single_stock_report()` (Einzelaktien-Push-Bericht)
- `templates/report_markdown.j2` (Jinja2-Vorlage)
- `HistoryService._generate_single_stock_markdown()` (Web-History-Schublade)

Die Normalisierungsfunktion wird in `_parse_response()` und `parse_dashboard_json()` explizit aufgerufen und stellt sicher:
- String-Prozente werden in int umgewandelt (z. B. `"35%"` → `35`)
- Negative Werte werden auf 0 gesetzt
- Wenn die Summe ≠ 100 ist, wird auf Summe = 100 normalisiert
- Werte werden auf den Bereich [0, 100] begrenzt

`signal_attribution` ist ein optionales Anzeigefeld (nicht erforderlich). Fehlt es, schlägt die Integritätsprüfung nicht fehl, es wird nicht in die `missing`-Liste geschrieben und kein Auffüll-Prompt ausgelöst; wenn vorhanden, wird es normalisiert und auf den unterstützten Berichtspfaden angezeigt.

#### Anbindung an Alarme, Positionen und Historie (Issue #1386 P6)

P6 verwendet die bestehenden `market_phase_summary` und `analysis_context_pack_overview` in den Ketten für Alarme, Positionen, Historie, Backtests und Benachrichtigungen wieder, ohne neue phase/pack-Protokolle und ohne Datenbankmigration. Alarmauslöseaufzeichnungen verwenden weiterhin das bestehende Textfeld `diagnostics`; wenn diagnostics JSON-ifizierbar sind, schreibt der Worker in `status=triggered`-Einträgen zusätzlich `analysis_visibility.market_phase_summary`, `analysis_visibility.analysis_context_pack_overview` und `analysis_visibility.source` zusammen. Alte reine Text-diagnostics bleiben im Originaltext erhalten; die abgeleiteten Felder der Alert API sind leer und `analysis_visibility_source=legacy_text`.

Die Alarm-Phasenzusammenfassung stammt aus dem Kontext zum Auslösezeitpunkt: symbol-Ziele werden nach Aktienmarkt bestimmt, `target_scope=market` verwendet direkt die Marktregion `cn|hk|us|jp|kr`, und wenn die Kontoebene nicht eindeutig lokalisiert werden kann, darf auf `unknown` zurückgefallen werden. Die Pack-Übersicht stammt nur aus der niedrigsensiblen Übersicht, die der Evaluator bereits hat, oder aus History-Snapshots der letzten 30 Tage; fehlt sie, wird `null` zurückgegeben, es wird kein Pack vorgetäuscht und keine leichte LLM-Analyse automatisch ausgelöst. Öffentliche source-Werte sind `alert_trigger_market_context`, `analysis_history_snapshot`, `evaluator_snapshot`, `legacy_text` oder `null`.

Die Positionsseite erhält einen neuen manuellen Einstieg für Einzelaktienanalysen, entsprechend `POST /api/v1/portfolio/positions/{symbol}/analysis`. Anforderungsfelder sind `account_id`, `analysis_phase=auto|premarket|intraday|postmarket` und `force`; nur Positionen ungleich Null in der aktuellen Positions-Snapshot können übermittelt werden, ohne Position wird 404 zurückgegeben, bei mehreren Konten mit derselben Aktie ohne `account_id` wird `400 ambiguous_position_account` zurückgegeben. Dieser Einstieg folgt den bestehenden asynchronen accepted/duplicate-Semantiken; `force` beeinflusst nur die Analyse-Aktualisierung und umgeht nicht das in-flight-duplicate. Das Backend übergibt nur den niedrigsensiblen `portfolio_context` an die interne Pipeline und den optionalen `portfolio`-Block des Context-Packs; dieser Block nimmt nicht an der bestehenden Gesamtpunktzahl der sechs Datenblöcke teil und erscheint weder in der Task-Liste noch im SSE-Payload.

Historienliste, Einzelaktien-Historie, StockBar und Details extrahieren `market_phase_summary` aus dem `context_snapshot`; alte Einträge, fehlende Snapshots oder Parse-Fehler geben `null` zurück. Backtest-Ergebniseinträge erhalten `market_phase` und `market_phase_summary`; Ergebnislisten und performance/summary-Abfragen unterstützen `analysis_phase=premarket|intraday|postmarket|unknown`; die Statistik fasst `intraday`, `lunch_break` und `closing_auction` unter intraday zusammen und ordnet `non_trading`, fehlende und ungültige Werte unter unknown ein. Backtest-Abfragen mit Phasenfilter lesen Ergebnisse und Snapshots auf Repository-Ebene in Batches gemäß SQL-Bedingung, bucket dann und paginieren und geben in den Summary-diagnostics `phase_breakdown` und `raw_phase_counts` zurück.

Benachrichtigungszusammenfassungen verwenden einen einheitlichen öffentlichen Formatierungs-Helper und geben nur Phasenlabel, Auslösequelle, partial-bar-Warnung, Datenqualitätsstufe und die ersten beiden limitations aus; sie geben keine rohen Context-Packs, Prompts, Nachrichtentexte oder sensible Positionsdetails aus. Web-Alarmhistorie, Positionen, Historienliste, StockBar und Backtest-Seiten zeigen synchron Phasen-Badges, Qualitätszusammenfassungen, Phasenfilter und Breakdown an.

#### Dokumentation, Konfiguration und Migrationshinweise (Issue #1386 P7)

P7 schließt nur die benutzersichtbaren Erklärungen zur Vor-/Intraday-/Nachbörsen-Analyse ab, ohne neue Laufzeitfähigkeiten, Konfigurationsoptionen, API-Parameter, Datenbankmigrationen, Web-Phasen-Override-Selectoren, Bot-Phasenparameter oder GitHub-Actions-Intraday-Workflows. Die standardmäßige tägliche Abschlussanalyse, die standardmäßigen GitHub Actions und das bestehende Schedule-Verhalten bleiben unverändert.

Empfohlene Verwendung:

| Szenario | Empfohlene Verwendung | Hinweis |
| --- | --- | --- |
| Vorbörslich | Eröffnungsplan und Beobachtungsbedingungen erzeugen | Der noch nicht erfolgte heutige Verlauf darf nicht als Tatsache beschrieben werden; Fokus auf den letzten vollständigen Handelstag, Nachrichten über Nacht und Eröffnungsauslösebedingungen. |
| Während der Handelszeit / Mittagspause / kurz vor Schluss | Echtzeit-Statusbewertung, Risiko- und Chancenhinweise | Aktueller Kurs, Frische der Echtzeitkurse, partial bar, Datenbegrenzungen und nächste Beobachtungsbedingungen beachten; ersetzt nicht den vollständigen Rückblick nach Börsenschluss. |
| Nach Börsenschluss | Vollständigen Rückblick und Plan für den nächsten Tag beibehalten | Verwendet die vollständige Handelstagssemantik; das Szenario, das der standardmäßigen täglichen Analyse am nächsten kommt. |

Einstiegspunkte und Sichtbarkeit:

| Einstieg | Phasenverhalten |
| --- | --- |
| `POST /api/v1/analysis/analyze` | Unterstützt `analysis_phase=auto|premarket|intraday|postmarket`; ohne Angabe Standard `auto`. |
| Web-Hauptanalyse / Reanalyse / manuelle Positionsanalyse | Derzeit kein Phasen-Override-Selector; der Frontend-Aufruf übergibt standardmäßig `auto`. Das TaskPanel für laufende Aufgaben zeigt die angeforderte Phase, die endgültige Berichtsseite zeigt das endgültige Phasenlabel. |
| Bot / CLI / Schedule / Standard-GitHub-Actions | Übergibt kein `analysis_phase` und verwendet weiterhin die `auto`-Erkennung; das Standardverhalten der Abschlussanalyse bleibt unverändert. |
| Historie / Backtest / Benachrichtigungen / Alarme | Konsumiert nur öffentliche `market_phase_summary` und niedrigsensibles `analysis_context_pack_overview`; legt kein vollständiges Pack, keine Prompt-Zusammenfassung, keine Nachrichtentexte und keine sensiblen Positionsdetails offen. |

`analysis_phase` ist der Anforderungswert; die endgültige Berichtsphase richtet sich weiterhin nach `report.meta.market_phase_summary.phase`. Alte Aufrufe ohne `analysis_phase` bleiben kompatibel; alte History-Einträge ohne `market_phase_summary` oder `analysis_context_pack_overview` geben leere Felder zurück und beeinflussen das Berichtslesen nicht. Backtest-Abfragen unterstützen den Filter `analysis_phase=premarket|intraday|postmarket|unknown` und ordnen Mittagspause und kurz vor Schluss gemäß P6-Regeln unter intraday ein.

`SAVE_CONTEXT_SNAPSHOT=false` oder CLI `--no-context-snapshot` stoppt nur die Persistierung der gesamten `context_snapshot` für neue History-Einträge, sodass neue History-Einträge keine persistierten Zusammenfassungen wie phase summary / pack overview / diagnostics snapshot mehr öffentlich machen; es deaktiviert weder die `AnalysisContextPack`-Konstruktion dieser Ausführung, entfernt nicht die niedrigsensible `analysis_context_pack_summary` aus dem Prompt und verändert das JSON-Schema des Berichts nicht. Aufrufer können, um vorübergehend zu einer Ausgabe näher am alten Nachbörsen-Duktus zurückzukehren, fest `analysis_phase=postmarket` übergeben; um die phase/pack-Runtime-Anbindung von P0-P6 vollständig zu entfernen, sind Release- oder Code-Rollback erforderlich.

#### Crontab verwenden

Wenn kein Dauerprozess gewünscht ist, kann auch der System-Cron verwendet werden:

```bash
crontab -e
# Hinzufügen: 0 18 * * 1-5 cd /path/to/project && python main.py
```

---

## Detaillierte Konfiguration der Benachrichtigungskanäle

Die Benachrichtigungskanal-Matrix, die minimal/advanced-Key-Ebenen, das Diagnoseformat von `--check-notify` und szenariobasierte Konfigurationshinweise finden sich im [Benachrichtigungs-Themendokument](notifications.md).

### WeCom

1. In einem WeCom-Gruppenchat einen "Gruppenbot" hinzufügen
2. Die Webhook-URL kopieren
3. `WECHAT_WEBHOOK_URL` setzen

### Feishu

> ⚠️ **Wichtige Unterscheidung**: `FEISHU_WEBHOOK_SECRET` (Webhook-Signaturgeheimnis) und `FEISHU_APP_SECRET` (Feishu-App-Secret) sind zwei völlig verschiedene Konfigurationen und dürfen nicht verwechselt werden.

**Minimale verfügbare Konfiguration (ohne Sicherheitseinschränkungen):**

```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your_hook_token
```

**Vollständige Schritte:**

1. **Im Feishu-Gruppenchat einen Custom-Bot erstellen**:
   - Ziel-Gruppenchat öffnen → oben rechts «Gruppeneinstellungen» → «Gruppenbots» → «Bot hinzufügen» → «Custom-Bot»
   - Bot-Namen ausfüllen, die generierte **Webhook-URL** kopieren (Format: `https://open.feishu.cn/open-apis/bot/v2/hook/...`)
2. `FEISHU_WEBHOOK_URL` setzen (also die im vorherigen Schritt kopierte URL).
3. Die **Sicherheitseinstellungen** des Bots ansehen und je nach aktivierten Sicherheitselementen entscheiden, ob zusätzliche Konfigurationen nötig sind:
   - **Keine zusätzlichen Sicherheitseinstellungen**: Nur `FEISHU_WEBHOOK_URL` ausfüllen.
   - **«Signaturprüfung» aktiviert**: Das von Feishu angezeigte Secret in `FEISHU_WEBHOOK_SECRET` eintragen. Beide Seiten müssen gleichzeitig aktiviert oder gleichzeitig leer sein, sonst gibt Feishu einen Fehler bei der Signaturprüfung zurück.
   - **«Schlüsselwort» aktiviert**: Dasselbe Schlüsselwort in `FEISHU_WEBHOOK_KEYWORD` eintragen; das System fügt es automatisch vor jeder Nachricht ein, ohne die Berichtsvorlage manuell ändern zu müssen.
   - **IP-Whitelist aktiviert**: Sicherstellen, dass die Ausgangs-IP der aktuellen Laufzeitumgebung in der Whitelist steht (Ausgangs-IPs von lokal/Docker/GitHub Actions unterscheiden sich jeweils).
4. `FEISHU_APP_ID`/`FEISHU_APP_SECRET` sind speziell für die Feishu-App-/Stream-Bot-/Cloud-Dokumentmodi gedacht und lösen keinen Gruppen-Webhook-Push aus; sie sollten nicht allein als Ersatz für `FEISHU_WEBHOOK_URL` verwendet werden.
5. Wenn `FEISHU_APP_ID`/`FEISHU_APP_SECRET` konfiguriert sind und zusätzlich `FEISHU_CHAT_ID` konfiguriert wird, kann über den Feishu-App-Bot direkt an die angegebene Gruppe oder den Benutzer gepusht werden, ohne auf den Gruppen-Webhook angewiesen zu sein; `FEISHU_RECEIVE_ID_TYPE` ist standardmäßig `chat_id`, bei Direktnachrichten auf `open_id` ändern. Dieser Weg nutzt die Feishu-OpenAPI-Bot-Sitzung und ist ein unabhängiger Kanal vom Gruppen-Webhook.
6. Der App-Bot-Sendepfad verwendet das bereits in `requirements.txt` enthaltene `lark-oapi>=1.0.0`; Standard-Quellcode-Installation, Docker, der tägliche GitHub-Actions-Workflow und die Desktop-Build-Kette installieren es über `pip install -r requirements.txt`, ohne eine neue Bibliothek separat installieren zu müssen. Referenz: [Feishu message create OpenAPI](https://open.feishu.cn/document/server-docs/im-v1/message/create), [lark-oapi PyPI](https://pypi.org/project/lark-oapi/), [SDK repo](https://github.com/larksuite/oapi-sdk-python).

**Häufige Fehlerursachen:**
- Nur `FEISHU_APP_ID`/`FEISHU_APP_SECRET` ausgefüllt, aber weder `FEISHU_WEBHOOK_URL` noch das für den aktiven App-Bot-Push benötigte `FEISHU_CHAT_ID` konfiguriert
- Feishu-Bot hat «Signaturprüfung» aktiviert, aber `FEISHU_WEBHOOK_SECRET` ist nicht konfiguriert (oder fälschlich als `FEISHU_APP_SECRET` eingetragen)
- Feishu-Bot hat «Schlüsselwort» aktiviert, aber lokal ist `FEISHU_WEBHOOK_KEYWORD` nicht synchron konfiguriert
- Der Bot wurde nicht in die Zielgruppe aufgenommen, oder Gruppenadministratoren haben die Bot-Berechtigung zum Schreiben eingeschränkt
- Auf Feishu-Seite zusätzlich eine IP-Whitelist konfiguriert, aber die IP der aktuellen Laufzeitumgebung ist nicht in der Whitelist
- Nachrichteninhalt zu lang: Feishu hat eine Längenbegrenzung pro Nachricht; das System sendet automatisch in Segmenten; für den vollständigen Inhalt in einem Dokument kann die Feishu-Cloud-Dokumentfunktion konfiguriert werden (`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_FOLDER_TOKEN`)

Vollständigere Fehlersuche mit Bildern findest du in [docs/bot/feishu-bot-config.md](bot/feishu-bot-config.md).

### Telegram

1. Ein Bot über den Dialog mit @BotFather erstellen
2. Bot-Token abrufen
3. Chat-ID abrufen (z. B. über @userinfobot)
4. `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID` setzen
5. (Optional) Für das Senden an ein Topic `TELEGRAM_MESSAGE_THREAD_ID` setzen (vom Ende des Topic-Links abrufen)

### E-Mail

1. Den SMTP-Dienst des E-Mail-Postfachs aktivieren
2. Den Autorisierungscode abrufen (nicht das Anmelde-Passwort)
3. `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` setzen

Unterstützte E-Mail-Anbieter:
- QQ Mail: smtp.qq.com:465
- 163 Mail: smtp.163.com:465
- Gmail: smtp.gmail.com:587

**Verschiedene Aktiengruppen an verschiedene E-Mails senden** (Issue #268, optional):
Mit `STOCK_GROUP_N` und `EMAIL_GROUP_N` können Berichte verschiedener Aktiengruppen an verschiedene E-Mail-Adressen gesendet werden, z. B. um bei gemeinsam genutzten Analysen mehrere Personen nicht zu stören. `STOCK_LIST` bestimmt weiterhin die tatsächlich in dieser Ausführung analysierte Aktienmenge; `STOCK_GROUP_N` sollte als Teilmenge von `STOCK_LIST` geschrieben werden; es beeinflusst nur die E-Mail-Empfänger und verändert nicht die vollständigen Berichte, die über andere Kanäle wie Telegram, WeCom oder Webhook empfangen werden. Der Markt-Rückblick wird an alle konfigurierten E-Mail-Adressen gesendet.

> GitHub-Actions-Einschränkung: Stand 2026-03-29 importiert der im Repository enthaltene `00-daily-analysis.yml` keine beliebig nummerierten `STOCK_GROUP_N`/`EMAIL_GROUP_N` automatisch. Wenn du diese Variablen also nur in den Repository-Secrets/Variables anlegst, ohne den Workflow explizit zu mappen, gelangen sie nicht in den laufenden Prozess und es wirkt, als ob die "Gruppenkonfiguration nicht wirksam" wäre.

```bash
STOCK_LIST=600519,300750,002594,AAPL
STOCK_GROUP_1=600519,300750
EMAIL_GROUP_1=user1@example.com
STOCK_GROUP_2=002594,AAPL
EMAIL_GROUP_2=user2@example.com
```

### Custom-Webhook

Unterstützt jeden Webhook, der POST-JSON empfängt, darunter:
- DingTalk-Bot
- Discord-Webhook
- Slack-Webhook
- Bark (iOS-Push)
- Selbst gehosteter Dienst

`CUSTOM_WEBHOOK_URLS` setzen, mehrere mit Kommas trennen.

Für spezielle Bodies von AstrBot, NapCat oder selbst gehosteten Diensten kann `CUSTOM_WEBHOOK_BODY_TEMPLATE` gesetzt werden. Dies ist eine globale Vorlage, die vor der automatischen Payload-Erkennung über die URL von Bark, Slack, Discord usw. wirkt; wenn das gerenderte Ergebnis kein JSON-Objekt ist, fällt das System auf das Standard-Payload zurück. Empfohlen wird `$content_json`/`$title_json`, um Zeilenumbrüche und Anführungszeichen zu vermeiden, die das JSON brechen würden:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"msg_type":"text","content":$content_json}
```

Verfügbare Platzhalter: `$content_json`, `$content`, `$title_json`, `$title`. Dabei sind `$content`/`$title` nackte Strings ohne JSON-Escape; bei doppelten Anführungszeichen oder Zeilenumbrüchen im Text kann der Fallback ausgelöst werden.

In einer Docker-Compose-Bereitstellung werden diese Anwendungsplatzhalter beim Speichern über die Web-Einstellungsseite als `$$content_json`/`$$title_json` usw. geschrieben, damit Compose sie bei erneuter Bereitstellung nicht zu leer expandiert; beim Anwendungsstart werden sie wieder zu einem einzelnen `$` reduziert. Wenn die von Docker verwendete `.env` manuell bearbeitet wird, bitte ebenfalls die Schreibweise `$$content_json` verwenden.

Bark muss bei Verwendung der globalen Vorlage den Bark-Body explizit ausschreiben:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"body":$content_json,"group":"stock"}
```

Das NapCat-/OneBot-Beispiel muss an den tatsächlichen endpoint, `user_id` oder `group_id` angepasst werden:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"user_id":123456,"message":$content_json}
```

### ntfy / Gotify

ntfy und Gotify sind erstklassige Benachrichtigungskanäle; sie senden nur Text/JSON und beteiligen sich nicht an der Markdown-zu-Bild-Konvertierung.

ntfy verwendet den vollständigen Topic-Endpoint; das letzte Path-Segment wird als Topic verwendet:

```env
NTFY_URL=https://ntfy.sh/my-topic
NTFY_TOKEN=
```

Gotify verwendet die Server-Base-URL; das System fügt automatisch die feste `/message`-API an und sendet das Application-Token über den `X-Gotify-Key`-Header. `GOTIFY_URL` kann ein Reverse-Proxy-Path-Präfix enthalten, aber kein `/message`:

```env
GOTIFY_URL=https://gotify.example
GOTIFY_TOKEN=app-token
```

```env
# Die tatsächliche Anfrage wird an https://example.com/gotify/message gesendet
GOTIFY_URL=https://example.com/gotify
GOTIFY_TOKEN=app-token
```

Der unterschiedliche semantische Umfang von `NTFY_URL` und `GOTIFY_URL` ist eine bewusste Wahl aufgrund unterschiedlicher API-Designs der beiden Dienste: Bei ntfy bildet der Benutzer-Topic den Endpoint, bei Gotify ist `/message` eine feste Dienst-API.

### Discord

Discord unterstützt zwei Push-Wege:

Lange Berichte werden automatisch gemäß dem 2000-Zeichen-Limit pro Discord-Content segmentiert gesendet; wenn ein Segment eine 429-Rate-Limitierung erhält, wiederholt der Sender begrenzt gemäß dem von Discord zurückgegebenen `retry_after` oder `Retry-After` und versucht weiter die folgenden Segmente. `DISCORD_MAX_WORDS` kann die Länge einzelner Segmente verringern, aber zur Laufzeit ist mehr als 2000 nicht zulässig.

**Weg 1: Webhook (empfohlen, einfach)**

1. In den Discord-Kanaleinstellungen einen Webhook erstellen
2. Die Webhook-URL kopieren
3. Umgebungsvariablen konfigurieren:

```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

**Weg 2: Bot-API (benötigt mehr Berechtigungen)**

1. Im [Discord Developer Portal](https://discord.com/developers/applications) eine Anwendung erstellen
2. Einen Bot erstellen und das Token abrufen
3. Den Bot zum Server einladen
4. Die Kanal-ID abrufen (im Entwicklermodus per Rechtsklick auf den Kanal kopieren)
5. Umgebungsvariablen konfigurieren:

```bash
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_MAIN_CHANNEL_ID=your_channel_id
```

Wenn du Discord-Slash-Command-/Interaction-Rückrufe empfangen möchtest und nicht nur Nachrichten an Discord pushen willst, musst du zusätzlich im Discord Developer Portal unter `General Information -> Public Key` den öffentlichen Schlüssel kopieren und konfigurieren:

```bash
DISCORD_INTERACTIONS_PUBLIC_KEY=your_public_key
```

Ohne diesen öffentlichen Schlüssel lehnt das System alle eingehenden Discord-Webhook-Anfragen ab.

### Slack

Slack unterstützt zwei Push-Wege; sind beide konfiguriert, wird bevorzugt die Bot API verwendet, damit Text und Bilder an denselben Kanal gesendet werden:

**Weg 1: Bot API (empfohlen, unterstützt Bild-Upload)**

1. Slack-App erstellen: https://api.slack.com/apps → Create New App
2. Bot-Token-Scopes hinzufügen: `chat:write`, `files:write`
3. Im Workspace installieren und Bot-Token (xoxb-...) abrufen
4. Kanal-ID abrufen: Kanaldetails → unten Kanal-ID kopieren
5. Umgebungsvariablen konfigurieren:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C01234567
```

**Weg 2: Incoming Webhook (einfache Konfiguration, nur Text)**

1. Im Slack-App-Verwaltungsbereich einen Incoming Webhook erstellen
2. Die Webhook-URL kopieren
3. Umgebungsvariablen konfigurieren:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```

### Pushover (iOS/Android-Push)

[Pushover](https://pushover.net/) ist ein plattformübergreifender Push-Dienst mit Unterstützung für iOS und Android.

1. Pushover-Konto registrieren und App herunterladen
2. Im [Pushover Dashboard](https://pushover.net/) den User Key abrufen
3. Eine Application erstellen und den API-Token abrufen
4. Umgebungsvariablen konfigurieren:

```bash
PUSHOVER_USER_KEY=your_user_key
PUSHOVER_API_TOKEN=your_api_token
```

Eigenschaften:
- Unterstützt iOS/Android auf beiden Plattformen
- Unterstützt Benachrichtigungsprioritäten und Sound-Einstellungen
- Das kostenlose Kontingent reicht für den privaten Gebrauch (10.000 Nachrichten pro Monat)
- Nachrichten können 7 Tage aufbewahrt werden

### Markdown zu Bild (optional)

Mit `MARKDOWN_TO_IMAGE_CHANNELS` können Berichte als Bild an Kanäle gesendet werden, die kein Markdown unterstützen (telegram, wechat, custom, email, slack).

**Abhängigkeitsinstallation**:

1. **imgkit**: Bereits in `requirements.txt` enthalten; wird bei `pip install -r requirements.txt` automatisch installiert
2. **wkhtmltopdf** (Standard-Engine): Systemabhängigkeit, muss manuell installiert werden:
   - **macOS**: `brew install wkhtmltopdf`
   - **Debian/Ubuntu**: `apt install wkhtmltopdf`
3. **markdown-to-file** (optional, bessere Emoji-Unterstützung): `npm i -g markdown-to-file` und `MD2IMG_ENGINE=markdown-to-file` setzen

Ist das Tool nicht installiert oder die Installation fehlgeschlagen, wird automatisch auf das Senden als Markdown-Text zurückgegriffen.

**Einzelaktien-Push + Bildversand** (Issue #455):

Im Einzelaktien-Push-Modus (`SINGLE_STOCK_NOTIFY=true`) muss für Bild-Push über Kanäle wie Telegram zusätzlich `MARKDOWN_TO_IMAGE_CHANNELS=telegram` konfiguriert und das Konvertierungstool (wkhtmltopdf oder markdown-to-file) installiert werden. Auch die Tageszusammenfassung einzelner Aktien unterstützt die Bildkonvertierung ohne zusätzliche Konfiguration.

**Fehlerbehebung**: Falls im Log «Markdown-zu-Bild-Konvertierung fehlgeschlagen, Fallback auf Textversand» erscheint, bitte die `MARKDOWN_TO_IMAGE_CHANNELS`-Konfiguration prüfen und ob das Konvertierungstool korrekt installiert ist (`which wkhtmltoimage` oder `which m2f`).

---

## Datenquellen-Konfiguration

Das System verwendet standardmäßig AkShare (kostenlos) und unterstützt auch andere Datenquellen:

### AkShare (Standard)
- Kostenlos, keine Konfiguration nötig
- Datenquelle: Eastmoney-Crawler

### Tushare Pro
- Registrierung zum Abruf des Tokens erforderlich
- Stabiler, vollständigere Daten
- `TUSHARE_TOKEN` setzen

### Baostock
- Kostenlos, keine Konfiguration nötig
- Als Ersatz-Datenquelle

### YFinance
- Kostenlos, keine Konfiguration nötig
- Unterstützt US-/Hongkong-Aktiendaten
- Historische Daten und Echtzeitkurse für US-Aktien verwenden einheitlich YFinance, um durch Replikationsanomalien von akshare bei US-Aktien verursachte Fehler bei Technischen Indikatoren zu vermeiden

### Longbridge (Changqiao)
- Fallback für US-/Hongkong-Aktiendaten, ergänzt von YFinance fehlende Felder wie Volume-Verhältnis, Turnover-Rate und PE
- Für Neuanschluss wird das offizielle Longbridge-OAuth-2.0 empfohlen: client_id bevorzugt `LONGBRIDGE_OAUTH_CLIENT_ID` verwenden; wenn leer und kein Legacy-Access-Token vorhanden ist, kompatibel `LONGBRIDGE_APP_KEY` verwenden; zuerst in einer interaktiven Umgebung `python scripts/generate_longbridge_oauth_token.py --client-id <client_id>` ausführen, um den SDK-Token-Cache zu generieren
- Headless-Umgebungen wie GitHub Actions / Docker können im Analysetask nicht auf Browser-Autorisierung warten; die Datei `~/.longbridge/openapi/tokens/<client_id>` des lokalen Rechners kann base64-kodiert als `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` konfiguriert werden
- OAuth setzt zur Laufzeit voraus, dass das SDK `OAuthBuilder` / `Config.from_oauth` bereitstellt; kann in der aktuellen Linux/Docker-Umgebung nur eine alte SDK-Version installiert werden, wird dies im Log klar gemeldet und Longbridge automatisch übersprungen, ohne den YFinance-/AkShare-Fallback zu beeinträchtigen
- Legacy-API-Key bleibt kompatibel: `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN` setzen; der Access Token ist eine Legacy-API-Key-Anmeldedaten und kein OAuth-Access-Token
- Optional `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` für die Cool-down-Sekunden nach Verbindungsschluss-Ausnahmen (Standard 15)
- Zugangspunkte konfigurierbar über `LONGBRIDGE_HTTP_URL`, `LONGBRIDGE_QUOTE_WS_URL`, `LONGBRIDGE_TRADE_WS_URL`, `LONGBRIDGE_REGION`
- Weitere optionale Parameter siehe offizielle [Umgebungsvariablen-Dokumentation](https://open.longbridge.com/zh-CN/docs/getting-started#环境变量)
- Wird nur automatisch ausgelöst, wenn YFinance (US-Aktien) oder AkShare (Hongkong-Aktien) unvollständige Daten zurückliefert; die A-Aktien-Kette bleibt unberührt
- Ohne konfigurierte Anmeldedaten wird diese optionale Datenquelle nicht instanziiert; tritt zur Laufzeit eine Verbindungsschluss-Ausnahme auf, wird Longbridge innerhalb der Cool-down-Periode vorübergehend übersprungen, um häufige Neuverbindungen auf Anfrageebene zu vermeiden

### Umgang mit häufigen Eastmoney-Schnittstellenfehlern

Erscheinen im Log `RemoteDisconnected`, geschlossene `push2his.eastmoney.com`-Verbindungen usw., liegt meist eine Eastmoney-Rate-Limitierung vor. Empfohlen:

1. In `.env` `ENABLE_EASTMONEY_PATCH=true` setzen
2. Mit `MAX_WORKERS=1` die Parallelität reduzieren
3. Ist Tushare konfiguriert, kann bevorzugt die Tushare-Datenquelle verwendet werden

---

## Erweiterte Funktionen

### Hongkong-Aktien-Unterstützung

Mit dem Präfix `hk` werden Hongkong-Aktiencodes angegeben:

```bash
STOCK_LIST=600519,hk00700,hk01810
```

Hongkong-Tagesdaten überspringen Datenquellen, die keine Hongkong-Tagesdaten unterstützen (efinance, pytdx, baostock usw.), damit Hongkong-Codes nicht fälschlich einem Nicht-Hongkong-Markt zugeordnet werden; standardmäßig greifen die Hongkong-Pfade von AkShare/Tushare/YFinance/Longbridge usw. weiter als Fallback ein.

### ETF- und Indexanalyse

Für indexnachbildende ETFs und US-Indizes (z. B. VOO, QQQ, SPY, 510050, SPX, DJI, IXIC) konzentriert sich die Analyse nur auf **Indexverlauf, Tracking-Error und Marktliquidität** und bezieht keine Unternehmensrisiken auf Fondsmanager-/Emittentenebene ein (Rechtsstreitigkeiten, Ruf, Führungswechsel usw.). Risikoalarme und Leistungserwartungen basieren auf der Gesamtperformance der Indexbestandteile, um zu vermeiden, dass Fondsgesellschaftsnachrichten fälschlich als Nachteil des Ziels selbst interpretiert werden. Details siehe Issue #274.

### Modellwechsel bei mehreren Modellen

Mehrere Modelle konfigurieren, das System wechselt automatisch:

```bash
# Gemini (Hauptmodell)
GEMINI_API_KEY=xxx
GEMINI_MODEL=gemini-3.1-pro-preview

# OpenAI-kompatibel (Alternative)
OPENAI_API_KEY=xxx
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
# deepseek-chat / deepseek-reasoner bleiben kompatibel, sind aber offiziell nach 2026/07/24 als veraltet markiert
```

### Erweitertes Modell-Routing (basiert auf LiteLLM)

Details siehe [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md). Für die Standardnutzung genügt es, Hauptmodell, Ersatzmodell und Modellkanäle zu verstehen; wenn du diesen Abschnitt erreicht hast, möchtest du direkt die zugrunde liegenden [LiteLLM](https://github.com/BerriAI/litellm)-Routingfähigkeiten nutzen, ohne einen separaten Proxy-Dienst starten zu müssen.

**Zweistufiger Mechanismus**: Key-Rotation bei mehreren Keys desselben Modells (Router) und modellübergreifendes Degrading (Fallback) sind getrennte Ebenen und stören sich nicht gegenseitig.

**Beispiel für Multi-Key + modellübergreifendes Degrading**:

```env
# Hauptmodell: 3 Gemini-Keys rotieren, bei jedem 429 wechselt der Router automatisch zum nächsten Key
GEMINI_API_KEYS=key1,key2,key3
LITELLM_MODEL=gemini/gemini-3.1-pro-preview

# Modellübergreifendes Degrading: Scheitern alle Keys des Hauptmodells, wird der Reihe nach Claude → GPT versucht
# Entsprechende API-Keys erforderlich: ANTHROPIC_API_KEY、OPENAI_API_KEY
LITELLM_FALLBACK_MODELS=anthropic/claude-sonnet-4-6,openai/gpt-5.4-mini
```

**Erwartetes Verhalten**: Der erste Request verwendet `key1`; bei 429 verwendet der Router beim nächsten Mal `key2`; sind alle 3 Keys nicht verfügbar, wird zu Claude gewechselt, und bei erneutem Fehlschlag zu GPT.

> ⚠️ `LITELLM_MODEL` muss ein provider-Präfix enthalten (z. B. `gemini/`、`anthropic/`、`openai/`),
> sonst kann das System nicht erkennen, welche API-Key-Gruppe verwendet werden soll. Das alte Format `GEMINI_MODEL` (ohne Präfix) wird nur zur automatischen Ableitung verwendet, wenn `LITELLM_MODEL` nicht konfiguriert ist.

**Abhängigkeitshinweis**: `requirements.txt` behält `openai>=1.0.0`, da LiteLLM intern das OpenAI-SDK als einheitliche Schnittstelle verwendet; die explizite Beibehaltung stellt die Versionskompatibilität sicher, ohne dass der Benutzer separat konfigurieren muss.

**Vision-Modell (Aktiencodes aus Bildern extrahieren)**: Details siehe [LLM-Konfigurationsleitfaden - Vision](LLM_CONFIG_GUIDE.md#41-vision-modelle-bilder-erkennen-von-aktiencodes).

Das Extrahieren von Aktiencodes aus Bildern (z. B. `/api/v1/stocks/extract-from-image`) nutzt eine einheitliche Vision-Modellanbindung, basiert auf LiteLLM Vision und dem OpenAI-`image_url`-Format und unterstützt Vision-fähige Modelle wie Gemini, Claude, OpenAI und DeepSeek. Zurückgegeben werden `items` (code, name, confidence) sowie ein kompatibles `codes`-Array.

> Kompatibilitätshinweis: Die Antwort von `/api/v1/stocks/extract-from-image` fügt zum ursprünglichen `codes` das Feld `items` hinzu. Verwenden Downstream-Clients ein striktes JSON-Schema und akzeptieren keine unbekannten Felder, bitte das Schema synchron aktualisieren.

**Intelligenter Import**: Neben Bildern werden auch CSV-/Excel-Dateien und Clipboard-Einfügen unterstützt (`/api/v1/stocks/parse-import`), mit automatischer Erkennung der Code-/Namensspalten; die Namens→Code-Auflösung unterstützt lokale Zuordnungen, Pinyin-Matching und AkShare-Online-Fallback. Abhängig von `pypinyin` (Pinyin-Matching) und `openpyxl` (Excel-Parsing), bereits in `requirements.txt` enthalten.

- **AkShare-Namensauflösungs-Cache**: Wird beim Namens→Code-Parsing der AkShare-Online-Fallback verwendet, werden Ergebnisse 1 Stunde (TTL) gecacht, um häufige Anfragen zu vermeiden; nach dem ersten Aufruf oder bei Cache-Ablauf wird automatisch aktualisiert.
- **CSV-/Excel-Spaltennamen**: Unterstützt `code`, `股票代码`, `代码`, `name`, `股票名称`, `名称` usw. (unabhängig von Groß-/Kleinschreibung); ohne Kopfzeile gelten standardmäßig Spalte 1 als Code und Spalte 2 als Name.
- **Häufige Parsing-Fehler**: Bei zu großer Datei (>2MB), Nicht-UTF-8/GBK-Kodierung, leerem oder beschädigtem Excel-Arbeitsblatt oder inkonsistenten CSV-Trennzeichen/Spaltenanzahl gibt die API eine konkrete Fehlermeldung zurück.

- **Modellpriorität**: `VISION_MODEL` > `LITELLM_MODEL` > Ableitung aus vorhandenem API-Key (`OPENAI_VISION_MODEL` ist veraltet, bitte `VISION_MODEL` verwenden)
- **Provider-Fallback**: Schlägt das Hauptmodell fehl, wird gemäß `VISION_PROVIDER_PRIORITY` (Standard `gemini,anthropic,openai`) automatisch zum nächsten verfügbaren Provider gewechselt
- **Wenn das Hauptmodell kein Vision unterstützt**: Ist das Hauptmodell ein Nicht-Vision-Modell wie DeepSeek, kann für die Bilderkennung explizit `VISION_MODEL=openai/gpt-5.5` oder `gemini/gemini-3.1-pro-preview` konfiguriert werden
- **Konfigurationsvalidierung**: Ist `VISION_MODEL` konfiguriert, aber der API-Key des entsprechenden Providers fehlt, wird beim Start eine warning ausgegeben und die Bilderkennung ist nicht verfügbar

### Debug-Modus

```bash
python main.py --debug
```

Logdatei-Pfade:
- Normales Log: `logs/stock_analysis_YYYYMMDD.log`
- Debug-Log: `logs/stock_analysis_debug_YYYYMMDD.log`

Das Debug-Log behält standardmäßig die DEBUG-Informationen des Projekts selbst bei, senkt aber interne LiteLLM-Logs auf `WARNING`, um beim Streaming pro Token große Mengen an Drittanbieter-Debug-Logs zu vermeiden; zum Untersuchen interner LiteLLM-Details kann in `.env` vorübergehend `LITELLM_LOG_LEVEL=DEBUG` gesetzt werden.

### Stabile SQLite-Schreibkonfiguration

Die Standard-Datei-SQLite aktiviert beim Verbindungsaufbau `WAL` und setzt `busy_timeout`; `save_daily_data()` wurde außerdem auf einen atomaren Batch-Upsert nach `(code, date)` umgestellt, um Lock-Konkurrenz bei Batch-Aktualisierungen und parallelen Rückschreibvorgängen zu verringern.

Für Anpassungen können in `.env` gesetzt werden:

| Variable | Standardwert | Beschreibung |
|------|-------|------|
| `SQLITE_WAL_ENABLED` | `true` | Ob die Datei-SQLite `journal_mode=WAL` aktiviert |
| `SQLITE_BUSY_TIMEOUT_MS` | `5000` | SQLite-Lock-Warte-Timeout (Millisekunden) |
| `SQLITE_WRITE_RETRY_MAX` | `3` | Maximale Wiederholungen bei `database is locked` / `database table is locked` |
| `SQLITE_WRITE_RETRY_BASE_DELAY` | `0.1` | Basis-Backoff-Zeit für Schreibwiederholungen (Sekunden, exponentiell steigend) |

---

## Analyse-Entscheidungs-Opersationalität

Die Handlungsempfehlung im Einzelaktienbericht wird unter Berücksichtigung von Unterstützung, Widerstand, Volumen/Chips, Hauptkapitalfluss und Risikoereignissen kalibriert, um heftige Wechsel zwischen "Kauf/Verkauf" allein aufgrund eines einzelnen Tagesgewinns/-verlusts oder eines Score-Grenzübertritts zu vermeiden. Liegt der Preis zwischen Unterstützung und Widerstand und ist der Kapitalfluss unklar, gibt der Bericht bevorzugt neutrale umsetzbare Empfehlungen wie "Halten, Seitwärtsbeobachtung, Washout-Beobachtung"; nur bei bestätigter Unterstützung, gültigem Ausbruch über den Widerstand und passendem Volumen-Preis/Kapitalfluss wird zum Kauf geraten, und bei Bruch einer entscheidenden Unterstützung oder anhaltendem Hauptkapitalabfluss zum Verkauf/Positionsabbau.
Diese Anpassung beeinflusst die Laufzeitpersistierung umsetzbarer Entscheidungen und die Prompt-Einschränkungskette, verändert aber nicht das LLM-Modell, das LiteLLM-Routing, Provider/Key und deren Kompatibilitätsgrenzen und beeinflusst weder die Speicher-/Bereinigungssemantik der Konfiguration.
Kompatibilitätsverifizierungsergebnis: Abgesehen von der Konfigurations- und Modellseitensemantik deckt diese Entscheidungsstabilitätskette das Laufzeitverhalten von `src/analyzer.py`, `src/core/pipeline.py`, `src/core/backtest_engine.py`, `src/report_language.py` und den Entscheidungspfaden von `src/agent` ab; empfohlen wird, die Zuordnung des Berichtsentscheidungstyps und die Verknüpfung mit dem Backtest-Einstieg zu prüfen.
Verifizierungspfad: Die zugehörige Logik greift in den obigen Laufzeitpfaden und den entsprechenden Tests (`tests/test_backtest_engine.py`, `tests/test_analyzer_news_prompt.py`, `tests/test_decision_stability.py`, `tests/test_agent_pipeline.py` usw.); in `src/config.py`, `src/report.py` und der Speicher-/Persistenzkette wurden keine Konfigurationsfelder oder Bereinigungslogik hinzugefügt.

### Handlungsempfehlungs-Taxonomie (#1390 P0)

Der Einzelaktienbericht behält den Freitext `operation_advice` bei und fügt zusätzlich optionale Felder `action`/`action_label` als strukturierte Anzeigehilfe für Web-Historienliste, Aktienhistorie, StockBar und Backtest-Ergebniszeilen hinzu. `decision_type` behält weiterhin die alte dreistufige Statistikbasis `buy|hold|sell`; ist `action` leer, wird die bestehende `decision_type`-Ableitungskette nicht umgeschrieben.

| `action` | Häufige Quelltexte | `decision_type`-Brücke |
| --- | --- | --- |
| `buy` | `strong_buy`, `强烈买入`, `买入`, `布局`, `建仓` | `buy` |
| `add` | `add`, `加仓`, `增持`, `accumulate` | `buy` |
| `hold` | `hold`, `持有`, `持有观察`, `洗盘观察` | `hold` |
| `watch` | `watch`, `观望`, `等待`, `wait` | `hold` |
| `reduce` | `reduce`, `减仓`, `trim` | `sell` |
| `sell` | `sell`, `卖出`, `清仓`, `strong_sell`, `强烈卖出` | `sell` |
| `avoid` | `avoid`, `回避`, `规避`, `不建议买入`, `避免买入`, `do not buy` | `hold` |
| `alert` | `alert`, `风险预警`, `警惕`, `触发告警`, `risk alert` | `hold` |

Die `decision_type`-Brücke in der obigen Tabelle beschreibt nur die Kompatibilitätsbeziehung zwischen den Acht-Zustands-Aktionen und der alten dreistufigen Statistikbasis; #1390 P0 schreibt `action` nicht automatisch zurück in das bestehende `decision_type`. Sind ein explizites `action` des Upstream und `decision_type` gleichzeitig vorhanden, aber semantisch inkonsistent, gelten für die dreistufige Statistik, den Backtest und die alten Berichtsformate weiterhin `decision_type`/die ursprüngliche Ableitungskette; `action/action_label` übernehmen nur die strukturierte Anzeigehilfe.

Unbekannte oder mehrdeutige Empfehlungen fallen nicht auf `watch` oder `hold` zurück, sondern liefern ein leeres `action/action_label`. Web-Historienkarten, StockBar, die Aktienhistorie-Schublade und Backtest-Ergebniszeilen greifen bei alten Einträgen ohne `action/action_label` auf Anzeigeebene aus `operation_advice` zurück; dieser Fallback betrifft nur das Frontend-Label und entspricht nicht einer stabilen API-Aktion oder einem späteren Signalwert. Die Web-Anzeigeebene generiert, wenn gleichzeitig `action` und `action_label` empfangen werden, das Label bevorzugt nach der aktuellen Oberflächensprache aus `action`; `action_label` in der API wird weiterhin nach der Berichtssprache erzeugt und dient Nicht-Web-Clients oder der kompatiblen Anzeige ohne `action`. Der Markt-Rückblick und andere Nicht-Einzelaktienberichte erzeugen keine Handels-`action`, sondern behalten nur den `operation_advice`-Text. `dashboard.phase_decision.immediate_action` gehört zum Berichtsfeld der Marktphasen-Schutzmaßnahmen und nimmt nicht an der Acht-Zustands-Aktionsableitung von #1390 P0 teil; die endgültige Marktphase stammt weiterhin aus `report.meta.market_phase_summary.phase`.

#1390 P0 flacht nachfolgende Signalwertfelder nicht auf die bestehenden Summary-, Historienlisten-, StockBar- oder Backtest-Antworten aus. Ab #1390 P1 wird über die eigenständige `DecisionSignal`-Ressource die Übernahme feingranularer Planungsfelder wie `horizon`, `plan_quality` und `status` übernommen, ohne den bestehenden Hauptvertrag der Berichte zu ändern, ohne Historien zurückzufüllen und ohne neue Konfigurationsoptionen.

### Entscheidungssignal-Assets (#1390 P1/P2/P3/P4/P5)

`DecisionSignal` ist eine eigenständige Backend-Ressource, um KI-Empfehlungen als abfragbare, deduplizierbare und statusaktualisierbare Signal-Assets zu verfestigen. Es ersetzt `operation_advice` nicht und erweitert nicht `decision_type=buy|hold|sell`. Ab #1390 P2 extrahieren die gewöhnliche Einzelaktienanalyse und die Agent-Einzelaktienanalyse nach erfolgreichem Speichern der Analysehistorie best-effort eine Signalquelle mit `source_type=analysis` aus dem endgültigen `AnalysisResult`; explizite API- oder Serviceaufrufe bleiben erhalten.

Die automatische Extraktion konsumiert nur strukturierte Felder aus dem bereits erzeugten Bericht, parst kein Markdown erneut, füllt keine alte Historie zurück, fügt keine Konfigurationsoptionen hinzu und verändert den Hauptvertrag der Berichte nicht. Bei Extraktionsfehler, unbekannter oder mehrdeutiger Handlungsempfehlung, Nicht-Einzelaktienbericht oder nicht erkennbarem Markt wird das Schreiben übersprungen, ohne das Speichern des Analyseberichts zu beeinflussen. `source_report_id` verwendet die gerade gespeicherte `AnalysisHistory.id`; `trace_id` bevorzugt die Laufzeit-Diagnose-Trace, bei Fehlen Rückfall auf die Pipeline-Trace oder `query_id`; `stock_name` stammt aus `AnalysisResult.name`; `trigger_source` stammt vom Ausführungseinstieg, bei Fehlen `system`.

Die Marktphase der P2-Automatikextraktion liest bevorzugt `market_phase_summary.phase` aus dem gespeicherten Snapshot, danach `AnalysisResult.market_phase_summary.phase`; die Datenqualität liest bevorzugt `analysis_context_pack_overview.data_quality` aus dem gespeicherten Snapshot, danach `AnalysisResult.analysis_context_pack_overview.data_quality`. Der Preisplan nutzt die beim Speichern der Historie verwendeten Regeln zur Auflösung von Scharfschützenpunkten wieder und mappt `dashboard.battle_plan.sniper_points.ideal_buy/secondary_buy/stop_loss/take_profit` auf `entry_low/entry_high/stop_loss/target_price`; nur bei `ideal_buy` wird `entry_low` geschrieben, nur bei `secondary_buy` wird `entry_high` geschrieben, und bei gleichzeitigem Vorhandensein werden die gültigen Preise so sortiert, dass `entry_low <= entry_high` gilt. Ein fehlender Stop-Loss oder Zielpreis senkt nur die vom Service automatisch berechnete `plan_quality`, erfindet aber keine Felder. `watch_conditions` liest bevorzugt `dashboard.phase_decision.watch_conditions`, nur wenn diese fehlen, `dashboard.battle_plan.action_checklist`; `catalyst_summary` wird nur geschrieben, wenn `dashboard.intelligence.positive_catalysts` vorhanden und eine Liste ist. `confidence` wird konservativ aus der Berichtskonfidenzstufe gemappt: `高/high=0.8`, `中/medium/mid=0.6`, `低/low=0.4`; die ursprüngliche Konfidenzstufe bleibt in `metadata` erhalten.

Ab P3 vervollständigt `DecisionSignalService` den Lebenszyklus einheitlich: Explizit übergebene `horizon`/`expires_at` haben immer Vorrang; bei nicht übergebenem `horizon` gilt für `alert` oder `premarket/intraday/lunch_break/closing_auction` Standard `intraday`, für `postmarket/non_trading/unknown` oder ohne Phasenkontext Standard `3d`; bei nicht übergebenem `expires_at` liest `intraday` bevorzugt `metadata.market_phase_summary.minutes_to_close/minutes_to_open`, ohne Kontext wird ein deterministischer TTL-Fallback verwendet (A-Aktien 4h, Hongkong-Aktien 5.5h, US-Aktien 6.5h, unbekannt 4h), `1d/3d/5d/10d` nach Kalendertagen, `swing/long` laufen nicht automatisch ab. Die Fallback-TTL ist nur eine Degradierungsstrategie ohne Handelskalender-Kontext und entspricht nicht der realen Börsenschlusszeit. Die Automatikextraktion schreibt nur `market_phase_summary.phase/session_date/minutes_to_open/minutes_to_close` als niedrigsensible Hinweise in `metadata.market_phase_summary`; die endgültigen `horizon/expires_at` werden weiterhin vom Service berechnet.

Zu den Kernfeldern gehören `stock_code`, `stock_name`, `market`, `source_type`, `source_agent`, `source_report_id`, `trace_id`, `decision_profile`, `market_phase`, `trigger_source`, `action`, `action_label`, `confidence`, `score`, `horizon`, `entry_low`, `entry_high`, `stop_loss`, `target_price`, `invalidation`, `watch_conditions`, `reason`, `risk_summary`, `catalyst_summary`, `evidence`, `data_quality_summary`, `plan_quality`, `status`, `expires_at`, `created_at`, `updated_at` und `metadata`. `action` nutzt die Acht-Zustands-Handlungsempfehlungen wieder; `decision_profile` unterstützt `conservative|balanced|aggressive`, `NULL` in der Datenbank bedeutet nur legacy/unknown; `market_phase` nutzt die Marktphasen-Enumeration wieder; `source_type` unterstützt `analysis|agent|alert|market_review|manual`; `status` unterstützt `active|expired|invalidated|closed|archived`; `horizon` unterstützt `intraday|1d|3d|5d|10d|swing|long`.

`confidence` liegt bei `0.0-1.0`, `score` bei `0-100` und ist vom `sentiment_score` des historischen Berichts entkoppelt. Die Preisplan-Felder `entry_low`, `entry_high`, `stop_loss` und `target_price` müssen endliche positive Zahlen sein, und bei gleichzeitiger Übergabe von `entry_low` und `entry_high` gilt `entry_low <= entry_high`. `plan_quality` unterstützt `complete|partial|minimal|unknown`: Bei explizit übergebenem gültigen Wert wird direkt gespeichert; wird keiner übergeben, berechnet es der Service, wobei der Einstiegsbereich (`entry_low` oder `entry_high` mit Wert) als 1 Element zählt, `stop_loss`, `target_price`, `invalidation` und `watch_conditions` jeweils als 1 Element; ab 2 Elementen `partial`, ab 4 Elementen `complete`, nur mit action/reason `minimal`.

Neue APIs:

- `POST /api/v1/decision-signals`: Erstellt oder dedupliziert nach gleichartigem Quellschlüssel, gibt `{ item, created }` mit HTTP 200 zurück. Neue Einträge können `decision_profile` weglassen und standardmäßig `balanced` annehmen oder einen gültigen Wert `conservative|balanced|aggressive` übergeben; explizites Top-Level-`null`, leere oder ungültige Werte werden abgelehnt. Nur bei fehlendem Top-Level-Wert wird auf gültiges `metadata.decision_profile` zurückgegriffen; vor dem Schreiben wird `metadata.decision_profile` mit dem formellen Feldwert synchronisiert; weggelassenes oder explizit `null` gesetztes metadata wird als kein metadata behandelt, object wird flach kopiert, Nicht-object wird abgelehnt. Der exakte Deduplizierungsschlüssel ist `(source_report_id, source_type, market, stock_code, decision_profile, action, horizon, market_phase)`; ohne report aber mit `trace_id` wird `(trace_id, source_type, market, stock_code, decision_profile, action, horizon, market_phase)` verwendet; ohne beides keine Deduplizierung. Exakte Übereinstimmung, relaxed fallback, horizon/phase fill, expired refresh, active invalidation und stale backfill invalidation folgen alle der same-profile-Semantik: `NULL` matcht nur `NULL`, ein nicht-leeres profile matcht nur dasselbe profile; die Refresh-Duplizierung abgelaufener Signale überschreibt `decision_profile` nicht. Schlägt die exakte Übereinstimmung fehl, wird ein enger relaxed fallback nach gleichartiger Quelle + `source_type/market/stock_code/decision_profile/action` versucht, der nur leere `horizon/market_phase` alter Einträge auffüllt, wobei `horizon` nur aufgefüllt werden darf, wenn der neue Wert vom Service standardmäßig erzeugt wurde; explizit unterschiedliche Laufzeiten, bereits vorhandene unterschiedliche Phasen oder unterschiedliche profile behalten mehrere Einträge. Wird ein gleichartiges abgelaufenes Signal mit gleichem profile getroffen und die neue Anfrage ist active mit zukünftigem `expires_at`, wird dieser Eintrag an Ort und Stelle aktualisiert und `created=false` zurückgegeben; diese Verlängerung wird als neues active-Aktivierungsereignis behandelt. Nach der aktiven Neuerstellung oder abgelaufenen Verlängerung markiert ein bullishes Signal (`buy/add`) frühere active defensive Signale (`reduce/sell/avoid`) mit gleichem profile als `invalidated`, und umgekehrt; unterschiedliche nicht-leere profile können koexistieren, selbst wenn die Aktionen entgegengesetzt sind. Auch ein active duplicate retry führt die Invalidierungsreparatur des gleichen profiles erneut aus, um ein partielles create wiederherzustellen, bei dem die letzte Erstellung erfolgreich war, aber die Invalidierungsschreibung fehlschlug; normale alte duplicates/replays gelten nicht als neue Aktivierungsereignisse. `hold/watch/alert` lösen keine automatische Invalidierung aus. Refresh oder Duplikat-Treffer geben nach außen `created=false` zurück; diese Funktion bietet keine Garantie für parallele Eindeutigkeit.
- `GET /api/v1/decision-signals`: Paginierte Abfrage, unterstützt `market`, `stock_code`, `action`, `market_phase`, `decision_profile`, `source_type`, `source_report_id`, `trace_id`, `trigger_source`, `status`, Zeitbereich, `holding_only` und `account_id`. Weggelassenes oder leeres `decision_profile` fügt keine profile-Bedingung hinzu und gibt alle profiles zurück; `decision_profile=unknown` fragt Legacy-`NULL`-Zeilen ab; gültige profiles werden exakt gematcht.
- `GET /api/v1/decision-signals/{signal_id}`: Fragt einen einzelnen Eintrag ab; 404 wenn nicht vorhanden.
- `PATCH /api/v1/decision-signals/{signal_id}/status`: Aktualisiert den gültigen Status und optionales `metadata`; bei weggelassenem metadata bleiben die ursprünglichen Werte erhalten, bei explizitem `null` werden sie auf SQL-`NULL` geleert, bei object wird das gesamte Paket ersetzt. Ein nicht-`NULL`-`decision_profile` im formellen Feld überschreibt konfliktierende profiles im metadata; ist das formelle Feld Legacy-`NULL`, wird der profile-Key aus dem Anfrage-object entfernt und das formelle Feld nicht angehoben. Terminalzustände wie `expired/invalidated/closed/archived` können nicht direkt per PATCH zu `active` zurückgeführt werden; eine Verlängerung abgelaufener Signale ist weiterhin nur über ein erneutes `POST` active + zukünftiges `expires_at` möglich.
- `GET /api/v1/decision-signals/latest/{stock_code}`: Fragt das neueste aktive Signal pro Aktie ab, Standard `limit=1`.

Lesende Einstiege führen eine Lazy-Ablaufprüfung durch: Vor Listen-, Detail- und latest-Abfragen werden active Signale, deren `expires_at` erreicht ist, als expired markiert; bei der Erstellung bereits abgelaufene active Signale werden direkt als expired gespeichert; gleichartige abgelaufene Signale können nur durch ein erneutes `POST` active + zukünftiges `expires_at` verlängert werden, `PATCH /status` akzeptiert kein `expires_at`. `expired|invalidated|closed|archived` werden per PATCH nicht direkt wiederbelebt, und `closed|invalidated|archived` werden auch über den create-Pfad nicht wiederbelebt. Die automatische Invalidierung durch entgegengesetzte Signale schreibt zusätzlich in das metadata des alten Signals: `invalidated_by_signal_id`, `invalidated_reason`, `invalidated_at`, `previous_status`; bei nicht-`NULL`-formellem profile wird das metadata-profile synchronisiert, bei Legacy-`NULL`-formellem profile bleibt das ursprüngliche metadata-profile erhalten und das formelle Feld wird nicht angehoben. Ist das alte metadata-JSON beschädigt oder kein object, wird es durch die Invalidierungs-metadata ersetzt und ein entsprechender replacement marker geschrieben, ohne die Erstellung neuer Signale zu blockieren. Zeitfelder werden nach UTC als zeitzonenlose `datetime` gespeichert und verglichen; zeitzonenbehaftete Eingaben werden zuerst nach UTC umgewandelt und verlieren dann das `tzinfo`, zeitzonenlose Eingaben werden als UTC behandelt, und die API-Antwort gibt weiterhin ISO-Strings ohne Zeitzonen-Suffix zurück. Aktiencodes werden beim Schreiben und Abfragen deterministisch nach `market` normalisiert: A-Aktien wie `600519`, `SH600519`, `600519.SH` usw. werden als derselbe Code gematcht; Hongkong-Aktien wie `00700`, `HK00700`, `00700.HK` werden als `HK00700` gematcht; US-Ticker werden einheitlich großgeschrieben. `holding_only=true` liest nur die gecachten Positionen mit `quantity > 0` aus `portfolio_positions` unter aktiven Konten und matcht Signale nach Positionen `(market, stock_code)`, optional mit aktivem `account_id`; diese Abfrage ruft keinen kombinerten Snapshot-Replay auf und liefert ohne Cache leere Ergebnisse; der Cache muss zuerst über die Portfolio-Snapshot-API aktualisiert werden.

`source_report_id` darf leer sein und erzwingt keine Prüfung auf vorhandene Historie; beim Löschen von Historie-Einträgen werden nur historiengebundene Signale mit `source_type=analysis` und `source_report_id`, die die tatsächlich gelöschte ID treffen, explizit bereinigt; Schwach-Referenz-Signale wie `manual/agent/alert/market_review` werden nicht allein wegen ID-Kollisionen gelöscht; die Listen-Schnittstelle unterstützt typed filters nach `source_report_id` und `trace_id`. Folgeverknüpfungsfelder wie `task_id` und `alert_trigger_id` werden zunächst in `metadata` abgelegt; P1 fügt keine separaten Spalten und keine typed filters hinzu, und spätere Verknüpfungsphasen heben sie zu eigenständigen Verträgen an. JSON-Felder, lange Textfelder und anzeigeorientierte Kurztextfelder (`stock_name/source_agent/trigger_source/action_label`) werden vor dem Schreiben einer signal-spezifischen Entschärfung unterzogen, die sensible Keys, Bearer-, Authorization-/Cookie-Header oder -Zuweisungen, token-ähnliche Strings, andere sensible Zuweisungen, Webhook-URLs, URL-Userinfo sowie URLs mit sensiblen query-/fragment-Parametern abdeckt; gewöhnliche Beleg-URLs bleiben erhalten, damit Quellen nachvollziehbar bleiben, und lange Texte unterliegen nicht der 300-Zeichen-Kürzung für Diagnosetexte. `trace_id` ist das Identitätsfeld der gleichartigen Deduplizierung; enthält es sensible Anmeldedaten, die entschärft würden, lehnt die API die Anfrage ab, anstatt einen verlustbehafteten redacted Wert zu speichern.

Diese Schnittstellen erben die bestehende Admin-Authentifizierung von `/api/v1/*`: Bei `ADMIN_AUTH_ENABLED=true` muss ein gültiges Admin-Sitzungs-Cookie mitgeführt werden; diese Funktion fügt keine eigenständige Authentifizierungsmethode hinzu.

#1390 P4 bindet im Web die bestehende `DecisionSignal`-API an. Ab #1756 ist der Einstieg "KI-Empfehlungen" in der Seitenleiste `/decision-signals` der zentrale Abfrageeinstieg für strukturierte Entscheidungssignale; standardmäßig werden Signale mit `status=active` angezeigt, und es gibt Filter nach Markt, Aktiencode, Aktion, Marktphase, Quelle, Quellbericht-ID und Status; der Zeitlinienbereich erhält einen profile filter, der die Server-seitige `decision_profile`-Abfrage der List-API wiederverwendet, wobei `unknown` nur zum Filtern und Anzeigen von Legacy-`NULL`-Zeilen dient und die normale erweiterte Liste keinen profile filter erhält. Die Seite bietet außerdem einen Einstieg zur Abfrage des neuesten aktiven Signals nach Aktiencode. Karten, Details und Zeitlinie lesen bevorzugt das formelle `decision_profile`-Feld und greifen nur bei fehlendem Feld auf Legacy-metadata zurück; explizites `null`, in der Historie fehlende oder ungültige profiles werden als unknown angezeigt. Die Signaldetails zeigen Aktion, Stil, Konfidenz/Score, horizon, plan_quality, market_phase, Preisplan, Risiko, Beobachtungsbedingungen, Quellbericht und Datenqualität; das Web erlaubt es nur, Signale als `closed`, `invalidated` oder `archived` zu markieren, und bietet keine Wiederherstellung von Terminalzuständen zu active an.

#1390 P5 fügt Signal-Feedback, Ex-post-Bewertung und einen Statistik-sidecar hinzu, ohne die Haupttabelle `decision_signals` zu erweitern und ohne an `analysis_history_id` gebundene `BacktestResult` wiederzuverwenden. `decision_signal_feedback` speichert nach `signal_id` das neueste `useful|not_useful`-Feedback, optionalen Grund/Bemerkung und Quelle; `decision_signal_outcomes` speichert idempotent nach `(signal_id, horizon, engine_version)` die Ex-post-Ergebnisse, aktuell `engine_version=decision-signal-v1`. Das Outcome friert bei der Bewertung statistische Dimensionen wie `action/market/market_phase/source_type/source_agent/plan_quality/data_quality_level/holding_state` ein; die historische Statistik hängt nicht von späteren live-joins ab. Beim Löschen historischer Berichte werden zuerst Signale mit `source_type=analysis`, die an die gelöschte Historie-ID gebunden sind, gefunden und dann die zugehörigen feedback/outcome-Untertabellen bereinigt.

Die P5-Ex-post-Bewertung unterstützt nur die tagesdatenverifizierbaren `1d/3d/5d/10d`; die Fenstersemantik sind 1/3/5/10 `StockDaily`-Handelsbars nach dem Anker und verwendet nicht die Kalendertage-Ablaufsemantik von `DecisionSignalService._horizon_days()` wieder. `anchor_date` liest bevorzugt `metadata.market_phase_summary.session_date`, sonst `created_at.date()`; am Ankertag muss ein `StockDaily.close` vorhanden sein, es wird nicht auf den vorherigen Handelstag zurückgegriffen. Aktionszuordnung: `buy/add -> up`, `hold -> not_down`, `reduce/sell/avoid -> not_up`; `watch/alert`, `intraday/swing/long`, fehlender Ankerpreis, unzureichende forward bars usw. schreiben `eval_status=unable` und einen eindeutigen `unable_reason`. Fehlender Ankerpreis, ungültiger Ankerpreis, unzureichende forward bars und fehlende/ungültige Fensterschlusskurse sind wiederherstellbare unable-Zustände; spätere Standard-Neuläufe bewerten nach Datenvervollständigung erneut; Nicht-Richtungsaktionen, nicht unterstützte horizons und fehlendes Ankerdatum sind terminale unable-Zustände und bleiben standardmäßig idempotent übersprungen. Der Laufzeit der Automatikextraktion kann zusätzlich `portfolio_context.quantity` übergeben werden; nur der niedrigsensible `holding_state=holding|empty|unknown` wird für die Ex-post-Snapshot in das metadata geschrieben, keine Menge, kein Konto und keine Kosten.

P5 zeigt auf der Web-`/decision-signals`-Seite unter dem Filterbereich die Gesamtstatistikkarte des aktuellen outcome-engines; das Detail-Schubladen lädt bei Bedarf die outcomes dieses Signals und kann useful/not useful-Feedback übermitteln. Die Seite fügt keine Navigationsseite hinzu, geht nicht in die BacktestPage ein und fügt keine Hintergrund-Planungsaufgaben hinzu; die Ex-post-Berechnung wird explizit über `POST /api/v1/decision-signals/outcomes/run` ausgelöst. Der Batch-Lauf priorisiert standardmäßig Signale mit fehlendem outcome, wiederholt dann wiederherstellbare unable und lässt neueste Signale mit abgeschlossenem oder terminalem unable den `limit` nicht dauerhaft belegen.

#1758 fügt in derselben `GET /api/v1/decision-signals/outcomes/stats`-Antwort `profile_calibration` hinzu, das strukturierte Gruppen nach decision profile, profile + action, profile + horizon, profile + market phase, profile + eingefrorene data quality und profile source zurückgibt. Jede Gruppe verlangt unabhängig `completed >= 30`; bei Unterschreitung werden nur counts behalten und die fünf deskriptiven Kennzahlen einheitlich `null` zurückgegeben; das Web zeigt nur die Stichprobengröße und "Stichprobe zu klein, nur zur Beobachtung." an, ohne zu ranken oder Stile zu empfehlen. Der Nenner der Hit-/Miss-Rate ist `hit + miss`, der Nenner der nicht bewertbaren Rate ist total; der maximale nachteilige Ausschlag wird nur aus den bereits gespeicherten `start_price/min_low/max_high` des outcomes berechnet und löst kein Kurslesen aus. `decision_profile` und das metadata-gestützte `profile_source` sind die aktuelle Attribution des Signals zum Abfragezeitpunkt; action, horizon, market phase und data quality verwenden weiterhin die eingefrorenen outcome-Werte. Die data quality neuer outcomes greift nur dann auf das normalisierte metadata-level zurück, wenn das summary kein explizites level hat; bestehende outcomes werden nicht stillschweigend überschrieben. Das Web verwendet die ursprüngliche Statistik-Anfrage und Card wieder und bietet nur die zwei Benutzeransichten konservativ/ausgewogen/aggressiv und nach Aktion/Periode; wenn dem alten Backend das neue Feld fehlt, bleibt die ursprüngliche Statistik weiterhin verfügbar. Der vollständige Maßstab findet sich im [DecisionSignal-Themendokument](decision-signals.md).

Die Positionsseite lädt KI-Empfehlungen asynchron als nicht blockierende Verbesserung: Zuerst werden Kombinations-Snapshot und Risikomodul nach der ursprünglichen Logik gerendert, danach wird für jede eindeutige Position im aktuellen Snapshot `GET /api/v1/decision-signals/latest/{stock_code}?market=<market>&limit=1` zur Abfrage des neuesten aktiven Signals aufgerufen; es gibt kein paginiertes Scannen der allgemeinen Liste über `holding_only=true` und keinen festen Seitenzahl-Abschnitt. Schlägt die latest-Abfrage einer einzelnen Position fehl, behält die Seite die anderen bereits geladenen Signale und zeigt einen sichtbaren Degradierungshinweis; ohne passendes Signal zeigt die Positionszeile einen leeren Platzhalter. Die Matching-Logik verwendet die Äquivalenzregeln für Aktiencodes im Web wieder und deckt A-Aktien `600519/SH600519/600519.SH`, Hongkong-Aktien `00700/HK00700/00700.HK` und US-Ticker mit Groß-/Kleinschreibung ab.

#1390 P6 verwendet `DecisionSignal` in Alarmen, Benachrichtigungen und Kombinationsrisiko wieder, ohne Tabellen, Migrationen oder Konfiguration. Echte Aktienalarmauslösungen verknüpfen bevorzugt das neueste aktive Signal desselben Ziels und schreiben den niedrigsensiblen `decision_signal_summary` in `alert_triggers.diagnostics`; ohne aktives Signal erstellt der worker nur ein minimales Signal mit `source_type=alert`, `action=alert`, wobei `trace_id=alert-rule-<hash>` nur der best-effort-Idempotenzdeduplizierung gleichartiger Wiederholungen dient, das aktive Signal selbst nicht überschreibt und kein `market_phase` schreibt, um phasenübergreifende Duplikate zu vermeiden. Alarmbenachrichtigungen und Analysebenachrichtigungen verweisen nur auf öffentliche Felder der Zusammenfassung wie `action/horizon/reason/watch_conditions/risk_summary/source_report_id`; ein Benachrichtigungsfehler beeinflusst weder das Trigger noch das Signal-Schreiben. `GET /api/v1/portfolio/risk` fügt einen Aggregationsblock `decision_signal_risk` hinzu, der nur aktive `sell/reduce/alert`-Signale der aktuellen Positionen zählt und `avoid/buy/add/hold/watch` explizit ausschließt; bei fehlgeschlagener Signalanfrage bleibt die Risiko-Schnittstelle fail-open, und der Web-Risikobereich zeigt einen Degradierungsstatus.

Die Abschlussdokumentation von #1390 P7 findet sich im [DecisionSignal-Themendokument](decision-signals.md). #1756 fügt keine `DECISION_SIGNAL_*`-Konfiguration oder Laufzeitschalter hinzu, fügt aber `decision_signals` ein nullable `decision_profile`-Feld, API-Anfrage-/Antwortfelder und einen profile-bewussten Index hinzu; bestehende SQLite führt nur bei fehlender Spalte `ALTER TABLE ADD COLUMN` aus, droppt/rebuild nicht die Tabelle und löscht keine alten Indizes. Die Migration erstellt idempotent den profile-bewussten Index und parst `metadata_json` defensiv zeilenweise; nur gültiges `metadata.decision_profile` wird zurückbefüllt, invalid JSON, Nicht-object oder ungültige profiles bleiben `NULL`. Aktueller Rollback-Weg ist das Revertieren des entsprechenden Codes. Nach dem Rollback stoppen Signalextraktion und -schreiben; die bestehenden Hauptflüsse für Berichtsspeicherung, Alarmauslösung, Benachrichtigungssendung und Kombinationsrisiko laufen weiter, ohne auf den Signalpool angewiesen zu sein; historische Signal-, Feedback- und Outcome-Daten werden nicht automatisch bereinigt.

Die Detailseite gewöhnlicher Einzelaktien-Historieberichte bindet das aus diesem Bericht extrahierte Signal mit `source_type=analysis` nicht mehr inline ein und initiiert beim Öffnen der Berichtsdetails auch keine Signalabfrage mit `source_report_id=<recordId>`; für das Ansehen strukturierter KI-Empfehlungen geht man einheitlich auf die `/decision-signals`-Seite, filtert nach Quellbericht-ID, öffnet den deep link `/decision-signals?sourceReportId=<recordId>` oder fragt nach Aktie. Beim Ausfüllen der Quellbericht-ID oder der Verwendung dieses URL-Parameters initiiert das Web eine präzise Abfrage mit `source_type=analysis + source_report_id=<recordId>`, ohne weitere Listenfilter wie den Standard `status=active` zu überlagern, um die best-effort-Lazy-Rückbefüllungssemantik alter Berichte beizubehalten.

## Backtest-Funktion

Das Backtest-Modul verifiziert automatisch historische KI-Analyseaufzeichnungen nachträglich und bewertet die Genauigkeit der Analyseempfehlungen.

### Funktionsweise

1. `AnalysisHistory`-Einträge auswählen, deren Cool-down-Periode (Standard 14 Tage) abgelaufen ist
2. Tagesdaten nach dem Analysedatum abrufen (Forward-K-Linien)
3. Aus der Handlungsempfehlung die erwartete Richtung ableiten und mit dem tatsächlichen Verlauf vergleichen
4. Treffen von Take-Profit/Stop-Loss bewerten und simulierten Ertrag berechnen
5. Als Performance-Kennzahlen auf Gesamt- und Einzelaktienebene zusammenfassen

### Zuordnung der Handlungsempfehlungen

| Handlungsempfehlung | Positionsgrößen-Ableitung | Erwartete Richtung | Siegbedingung |
|---------|---------|---------|---------|
| Kauf/Aufstocken/strong buy | long | up | Anstieg ≥ neutrale Bandbreite |
| Verkauf/Positionsabbau/strong sell | cash | down | Rückgang ≥ neutrale Bandbreite |
| Halten/Halten-Beobachtung/Seitwärtsbeobachtung/Washout-Beobachtung/hold/hold and watch/range-bound watch/shakeout watch | long | not_down | Kein signifikanter Rückgang |
| Beobachten/Warten/wait | cash | flat | Preis innerhalb der neutralen Bandbreite |

### Konfiguration

Folgende Variablen in `.env` setzen (alle haben Standardwerte, optional):

| Variable | Standardwert | Beschreibung |
|------|-------|------|
| `BACKTEST_ENABLED` | `true` | Ob nach der täglichen Analyse automatisch ein Backtest ausgeführt wird |
| `BACKTEST_EVAL_WINDOW_DAYS` | `10` | Bewertungsfenster (Anzahl Handelstage) |
| `BACKTEST_MIN_AGE_DAYS` | `14` | Nur Einträge N Tage zurück testen, um unvollständige Daten zu vermeiden |
| `BACKTEST_ENGINE_VERSION` | `v1` | Engine-Versionsnummer, zur Unterscheidung der Ergebnisse beim Upgrade der Logik |
| `BACKTEST_NEUTRAL_BAND_PCT` | `2.0` | Schwellwert der neutralen Zone (%), ±2 % gilt als Seitwärtsbewegung |

### Automatische Ausführung

Der Backtest wird automatisch nach Abschluss des täglichen Analyseablaufs ausgelöst (nicht blockierend; ein Fehler beeinflusst den Benachrichtigungspush nicht). Er kann auch über die API manuell ausgelöst werden.

### Bewertungskennzahlen

| Kennzahl | Beschreibung |
|------|------|
| `direction_accuracy_pct` | Genauigkeit der Richtungsvorhersage (erwartete Richtung stimmt mit der tatsächlichen überein) |
| `win_rate_pct` | Gewinnrate (Gewinne / (Gewinne+Verluste), ohne neutrale) |
| `avg_stock_return_pct` | Durchschnittliche Aktienrendite |
| `avg_simulated_return_pct` | Durchschnittlicher simulierter Ausführungsertrag (inkl. Take-Profit-/Stop-Loss-Ausstiege) |
| `stop_loss_trigger_rate` | Stop-Loss-Auslöserate (nur Einträge mit konfiguriertem Stop-Loss) |
| `take_profit_trigger_rate` | Take-Profit-Auslöserate (nur Einträge mit konfiguriertem Take-Profit) |

---

## Lokales WebUI-Verwaltungsinterface

Die WebUI teilt sich denselben Serviceprozess mit der FastAPI-API; nach dem Start können im Browser Konfigurationsverwaltung, manuelle Analyse, Task-Fortschrittsanzeige, Historienberichte, Backtest, Positionsverwaltung und intelligenter Import ausgeführt werden. Authentifizierung, Cloud-Server-Zugriff und API-Aufrufdetails siehe die Hinweise unten.

### FastAPI-API-Dienst

FastAPI stellt einen RESTful-API-Dienst bereit und unterstützt Konfigurationsverwaltung und Analyseauslösung.

### Startmöglichkeiten

| Befehl | Beschreibung |
|------|------|
| `python main.py --serve` | API-Dienst starten + eine vollständige Analyse ausführen |
| `python main.py --serve-only` | Nur den API-Dienst starten, Analyse manuell auslösen |

### Funktionseigenschaften

- 📝 **Konfigurationsverwaltung** - Watchlist ansehen/ändern
- 🗂️ **Startseite mit drei Ansichten** - Startseite hat einen neuen Arbeitsbereich «Historie / Watchlist / Heute», standardmäßig wird die Historienansicht geöffnet; die Watchlist-Seite unterstützt die Batch-Übermittlung aller oder nur der "heute noch nicht analysierten" Aktien
- 🧭 **Sprachumschaltung der Oberfläche** - Sowohl im angemeldeten als auch im abgemeldeten Zustand ist eine schnelle Sprachumschaltung der Oberfläche (`zh` / `en`) möglich, unabhängig von `REPORT_LANGUAGE`, für statische UI-Texte und Navigationsgerüst
- 🚀 **Schnellanalyse** - Auslösung der Einzelaktienanalyse über die API-Schnittstelle; die Startseite bietet außerdem eine Schaltfläche "Markt-Rückblick" und einen Einzelmarkt-Selector, um im Docker-/Servermodus einen Rückblick im Hintergrund nach den Server-Standardeinstellungen oder einem vorübergehend ausgewählten einzelnen/mehreren Markt auszulösen
- 🎯 **Strategieauswahl** - Die Startseite unterstützt die explizite Auswahl der Analysestrategie-skill; ohne `skills` wird mit der Systemstandardstrategie ausgeführt, um die Kompatibilität mit dem bisherigen Verhalten zu wahren
- 🧪 **Heute-Status/Task-Refresh-Entprellung** - Startseite «Heute» und «Watchlist» führen über zeitzonenbewusste Historiebereiche die Beurteilung durch und initiieren paginierte Historieabfragen; nach Task-Abschluss wird die Fehleranzeige erst durch einen erfolgreichen Refresh der letzten Stockbar gelöscht, um zu vermeiden, dass alte Anfragen den neuen Status ungeordnet überschreiben und doppelte Übermittlungen verursachen
- 🧭 **Erstkonfigurationshinweis** - Die Startseite liest den schreibgeschützten Konfigurationsstatus und weist bei fehlenden Basiselementen wie LLM-Hauptkanal oder Watchlist auf die Lücke hin und führt in die Systemeinstellungen
- 📊 **Echtzeit-Fortschritt** - Analysetask-Status wird in Echtzeit aktualisiert, parallele Tasks werden unterstützt; die gewöhnliche Analyse-Kette versucht nach Eintritt in die LLM-Phase bevorzugt LiteLLM-Streaming-Generierung und speist über Task-SSE feinere `message/progress` zurück
- 🧪 **Wiederherstellbarer eingebauter Aktienauswahl-Task** - Die Aktienauswahlimplementierung verweist auf AlphaSift; nach dem Absenden des Hintergrundtasks auf der Seite wird der Status abgefragt, beim Seitenwechsel und Zurückkehren werden der aktuelle Task-Fortschritt oder das Endergebnis wiederhergestellt
- 🗂️ **Sichtbarkeit des Markt-Rückblick-Tasks** - Nach dem Auslösen des Markt-Rückblicks auf der Startseite wird `task_id` zurückgegeben und `GET /api/v1/analysis/status/{task_id}` abgefragt; in den Szenarien laufend/abgeschlossen/fehlgeschlagen wird sichtbares Feedback gegeben, bei Fehlschlag wird der Fehlerinhalt direkt durchgereicht
- 🗂️ **Separater Einstieg für die Markt-Rückblick-Historie** - Die Markt-Rückblick-Historie wird über einen speziellen Eintrag von der gewöhnlichen Einzelaktienhistorie isoliert; empfohlen wird die direkte Abfrage und Wiedergabe der Markt-Rückblick-Einträge über `stock_code=MARKET` + `report_type=market_review`
- 🧾 **Wiederverwendbare Markt-Rückblick-Historie** - Markt-Rückblick-Tasks werden in der Analysehistorie persistiert, `report_type` ist `market_review`; das entsprechende Markdown oder die Detailseite kann direkt über die Historienliste/Details geöffnet werden, ohne eine erneute Analyseberechnung auszulösen
- 🧭 **Marktpositionskarte** - Der gewöhnliche A-Aktien-Analysebericht zeigt die Markt-/Themenebene und die Einzelaktien-Positionsebene und unterscheidet Markthauptlinie, primär assoziiertes Thema, Themenphase, Aktienposition und fehlende Belege
- 🧩 **Sichtbare Eingabedatenblöcke** - Der gewöhnliche Analysebericht gibt in Historie-Details, synchronen Antworten und abgeschlossenen Task-Zuständen den niedrigsensiblen `AnalysisContextPack`-overview zurück; die Web-Berichtsseite zeigt nach Strategiepunkten und Informationen standardmäßig eingeklappt Datenblock-Status, Quelle, fehlenden Grund und Degradierungszusammenfassung
- 💬 **Fragen-zur-Aktie-Folgekontext** - Nach dem Wechsel von einem Historienbericht zum Fragen-zur-Aktie trägt die Folgeanfrage dauerhaft das aktuelle `stock_code/stock_name`; beim Wechsel zurück oder Neuladen einer bestehenden Fragen-zur-Aktie-Sitzung wird der Basiszielwert aus den bereits geladenen historischen Benutzernachrichten wiederhergestellt; nur wenn der Benutzer das Ziel explizit wechselt, wird der Kontext gewechselt; Anfragen mit eindeutiger Vergleichsabsicht (vergleichen/vergleich/gegenüber/Unterschied/im Vergleich zu) oder mehreren nicht-aktuellen, expliziten Aktiencodes verschmutzen das aktuelle Ziel nicht
- 📈 **Backtest-Verifizierung** - Genauigkeit der historischen Analyse bewerten, Richtungs-Gewinnrate und simulierten Ertrag abfragen
- 🔗 **API-Dokumentation** - Auf `/docs` die Swagger-UI ansehen

### Mit dieser Änderung verbundene Produktverhalten

- Der Web-Sprachstatus verwendet einen zweistufigen Mechanismus: `dsa.uiLanguage` (im Browser persistiert) und `REPORT_LANGUAGE` (Standardausgabe von Berichten und Fragen-zur-Aktie) sind entkoppelt.
  - `dsa.uiLanguage` bestimmt nur die WebUI-Texte und die Navigationssprache (`zh` / `en`); die Wertpriorität ist lokaler persistierter Wert -> Browsersprache -> Standard `zh`.
  - `REPORT_LANGUAGE` steuert Berichtstexte, Lokalisierung von Aktienkurzbezeichnungen, feste Texte der Berichtsseite sowie Agent-Chat-Antworten ohne `context.report_language` (`zh` / `en` / `ko`).
- Die Sprachumschaltung der Seite ist eine Verbesserung des Benutzererlebnisses und gehört nicht zum Nachweisumfang der Regressionsverifizierung; Screenshots und Befehle bitte gemäß PR-Ablauf separat in der PR-Beschreibung pflegen.
- Diese Änderung fügt nur einen anfrageebenen Berichtssprach-Override-Parameter hinzu und verändert die Migrations- und Bereinigungslogik von `provider`/`model`/`base_url` nicht.

### API-Schnittstellen

| Schnittstelle | Methode | Beschreibung |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | Aktienanalyse auslösen |
| `/api/v1/analysis/market-review` | POST | Markt-Rückblick im Hintergrund auslösen; der Request-Body kann `{"send_notification": true, "region": "cn,us"}` übergeben; `region` überschreibt nur diese Anfrage und nutzt mit `main.py --market-review` und `bot` dieselbe `GeminiAnalyzer/SearchService/NotificationService`-Assemblierungssemantik |
| `/api/v1/analysis/tasks` | GET | Task-Liste abfragen |
| `/api/v1/analysis/tasks/stream` | GET (SSE) | Echtzeit-Statusstream der Tasks abonnieren; `task_progress` kann optional inkrementelle `flow_event`-Laufzeitablaufereignisse mitführen |
| `/api/v1/analysis/tasks/{task_id}/flow` | GET | Laufzeitablauf-Snapshot eines aktiven Tasks abfragen |
| `/api/v1/analysis/status/{task_id}` | GET | Task-Status abfragen |
| `/api/v1/screening/screen/tasks` | POST | Eingebauten Aktienauswahl-Task im Hintergrund absenden (zuerst `SCREENING_ENABLED` aktivieren) |
| `/api/v1/screening/screen/tasks/{task_id}` | GET | Status und Abschlussergebnis des eingebauten Aktienauswahl-Tasks abfragen |
| `/api/v1/history` | GET | Analysehistorie abfragen |
| `/api/v1/history/{record_id}/diagnostics` | GET | Laufzeit-Diagnosezusammenfassung und entschärften Kopiertext des Historienberichts abfragen |
| `/api/v1/history/{record_id}/flow` | GET | Laufzeitablauf-Snapshot des Historienberichts abfragen; gewöhnliche Einzelaktien und `MARKET/market_review`-Markt-Rückblick nutzen denselben Vertrag |
| `/api/v1/decision-signals` | POST | Entscheidungssignale explizit erstellen oder nach gleichartigem Quellschlüssel deduplizieren, gibt `{ item, created }` zurück |
| `/api/v1/decision-signals` | GET | Entscheidungssignale paginiert abfragen; unterstützt Filter nach Aktie, Markt, Aktion, Phase, Stil, Quelle, Status, Zeitbereich und cache-only-Positionen |
| `/api/v1/decision-signals/outcomes/run` | POST | Ex-post-Bewertung von Signalen explizit auslösen; standardmäßig completed/terminale unable überspringen, wiederherstellbare unable neu berechnen, `force=true` erzwingt Neuberechnung |
| `/api/v1/decision-signals/outcomes` | GET | Ex-post-Ergebnisse von Signalen paginiert abfragen |
| `/api/v1/decision-signals/outcomes/stats` | GET | Statistik des aktuellen Ex-post-Engines abfragen, standardmäßig archived-Signale ausschließen |
| `/api/v1/decision-signals/{signal_id}/outcomes` | GET | Ergebnisse eines einzelnen Signals unter dem aktuellen Ex-post-Engine abfragen |
| `/api/v1/decision-signals/{signal_id}/feedback` | GET | Benutzerfeedback eines einzelnen Signals abfragen; ohne Feedback wird `feedback_value=null` zurückgegeben |
| `/api/v1/decision-signals/{signal_id}/feedback` | PUT | `useful|not_useful`-Feedback eines einzelnen Signals schreiben oder aktualisieren |
| `/api/v1/decision-signals/{signal_id}` | GET | Ein einzelnes Entscheidungssignal abfragen, vor dem Lesen Lazy-Ablauf ausführen |
| `/api/v1/decision-signals/{signal_id}/status` | PATCH | Status und optionales metadata eines Entscheidungssignals aktualisieren |
| `/api/v1/decision-signals/latest/{stock_code}` | GET | Neuestes aktives Entscheidungssignal der angegebenen Aktie abfragen |
| `/api/v1/usage/summary?period=today|month|all` | GET | LLM-Aufrufzahlen und Token-Verbrauch nach Aufruftyp und Modell aggregieren |
| `/api/v1/usage/dashboard?period=today|month|all&limit=50` | GET | Token-Verbrauchs-Dashboard-Daten zurückgeben: Gesamtmenge, Prompt/Completion-Aufschlüsselung, Modellverbrauch, Aufruftypverteilung und letzte Aufrufdetails; Web-Einstieg über die linke Navigation "Verbrauch" |
| `/api/v1/backtest/run` | POST | Backtest auslösen |
| `/api/v1/backtest/results` | GET | Backtest-Ergebnisse abfragen (paginiert) |
| `/api/v1/backtest/performance` | GET | Gesamte Backtest-Performance abrufen |
| `/api/v1/backtest/performance/{code}` | GET | Backtest-Performance einer einzelnen Aktie abrufen |
| `/api/v1/stocks/extract-from-image` | POST | Aktiencodes aus einem Bild extrahieren (multipart, Timeout 60s) |
| `/api/v1/stocks/parse-import` | POST | CSV/Excel/Clipboard parsen (multipart-Datei oder JSON `{"text":"..."}`, Datei ≤2MB, Text ≤100KB) |
| `/api/health` | GET | Health-Check |
| `/docs` | GET | API-Swagger-Dokumentation |

> Hinweis: `POST /api/v1/analysis/analyze` unterstützt bei `async_mode=false` nur eine einzelne Aktie; für eine Batch von `stock_codes` muss `async_mode=true` verwendet werden. Die asynchrone `202`-Antwort gibt bei einer einzelnen Aktie `task_id` zurück, bei einer Batch die Aggregatstruktur `accepted` / `duplicates`.
> Hinweis: `POST /api/v1/analysis/analyze` unterstützt die Übergabe einer Liste von Strategie-Skill-IDs über `skills`; ohne Übergabe wird nach der Server-Standardstrategie ausgeführt. Für die Kompatibilität historischer Aufrufe bleibt das Feld `strategies` als kompatibles Alias erhalten.
> Hinweis: `POST /api/v1/analysis/analyze` unterstützt `analysis_phase=auto|premarket|intraday|postmarket`, Standard `auto`. Nicht-`auto` überschreibt nur die Analysephase dieser Ausführung und die abgeleiteten Phasenmarkierungen, ohne die echten Handelskalenderzeiten zu verändern; die accepted-Antwort, der In-Memory-Task-Status, die Task-Liste und das SSE spiegeln die angeforderte Phase wider, die endgültige Berichtsphase richtet sich nach `report.meta.market_phase_summary.phase`.
> Hinweis: `POST /api/v1/analysis/analyze` unterstützt `report_language=zh|en|ko` und akzeptiert kompatibel `reportLanguage` als Alias; ohne Übergabe wird auf das globale `REPORT_LANGUAGE` (oder `Config.report_language` aus der Umgebung) zurückgegriffen. Dieses Feld betrifft nur den Berichtstext dieser Ausführung, `report.meta.report_language` und die persistierte Anzeige und wird nicht als Laufzeitkonfiguration persistiert.
> Hinweis: Das Strategie-Dropdown auf der Web-Startseite ist ein explizit wählbarer Strategieeinstieg. Hat der Benutzer nicht manuell gewählt, wird kein `skills` mitgeführt, konsistent mit dem Verhalten historischer Clients; nach der Auswahl einer Strategie wird sie an diese Schnittstelle durchgereicht und im Task-Status sowie im Historie-Snapshot aufbewahrt.
> Hinweis: `POST /api/v1/analysis/market-review` verwendet einen mit CLI/Bot gemeinsamen Konfigurationspfad (`GeminiAnalyzer(config=...)` und dieselben Such-/Prompt-Konstruktions-Einstiege). Die Provider-kompatible Route erkennt und verwendet bevorzugt `litellm_model`, `llm_model_list`; ohne Konfiguration greift sie auf Legacy-Schlüssel `GEMINI_*`, `OPENAI_*`, `ANTHROPIC_*`, `DEEPSEEK_*` zurück; es werden keine provider-, Base-URL- oder LiteLLM-Routingsemantiken hinzugefügt/angepasst.
> Hinweis: `POST /api/v1/analysis/market-review` unterstützt zusätzlich `report_language=zh|en|ko` (Alias `reportLanguage` unterstützt). Ohne Übergabe wird ebenfalls auf das globale `REPORT_LANGUAGE` zurückgegriffen. Dieser Parameter betrifft nur den Text des Rückblick-Berichts dieser Ausführung und die sprachbezogenen Inhalte in den strukturierten Rückgabefeldern; von Bot, Schedule, CLI oder Schaltfläche ausgelöstes `main.py --market-review` verwendet weiterhin die globale Konfiguration, ohne neue anfrageebene Überschreibungsfähigkeit.
> Hinweis: `POST /api/v1/analysis/market-review` kann optional das String-Feld `region` mit einer Länge von 1–64 übergeben, unterstützt `cn`, `hk`, `us`, `jp`, `kr`, `both` oder ein durch Kommas getrennter gültiger, nicht leerer Teilmenge (z. B. `cn,us`). Die Anfrageebene normalisiert Groß-/Kleinschreibung, Leerzeichen, Duplikate und Marktreihenfolge; leere Strings, leere Tokens, unbekannte Tokens oder `both` gemischt mit anderen Märkten geben insgesamt 4xx zurück, ohne Teilausführung oder Fallback. Bei weggelassenem Feld wird weiterhin das globale `MARKET_REVIEW_REGION` gelesen.
> Hinweis: Der Markt-Selector auf der Startseite überschreibt nur diese Web-Auslösung, ruft keine Konfigurations-Lese-/Speicher-Schnittstellen auf und schreibt nicht in LocalStorage; bei Auswahl von "Server-Standard" lässt die Anfrage `region` weg, und die UI errät den tatsächlichen Laufzeitmarkt nicht aus den saved/display-Werten der Web-Einstellungen. Das Backend löst an der Task-Einreichungsgrenze den einzigen kanonischen tatsächlich ausgeführten Wert auf; die accepted-Antwort, die Zustände pending/processing/completed, die Task-Liste, `task_created`/`task_started`/`task_progress`/`task_completed`-SSE, das strukturierte Payload des Abschlusszustands sowie `region` und `context_snapshot.market_review_region` der History-Listeneinträge verwenden diesen Wert wieder. Die langfristige `MARKET_REVIEW_REGION`-Konfiguration behält ihre historische lockere Filter-/Fallback-Semantik; CLI, Bot, Schedule und die Standard-`cn`-Semantik bleiben unverändert.
> Hinweis: `POST /api/v1/analysis/market-review` ist der manuelle Auslöseeinstieg von Web/Desktop; nach dem Klick wird der Markt-Rückblick-Task direkt eingereicht und nicht wegen `TRADING_DAY_CHECK_ENABLED=true` oder an dem Tag ruhender relevanter Märkte kurzgeschlossen übersprungen; geplante Tasks, manuelle GitHub-Actions-Ausführung und der CLI-Standardeinstieg folgen weiterhin der Handelstag-Prüfung und können mit `--force-run` oder dem Workflow-`force_run` überschrieben werden.
> Audit-Grundlage: Die Prioritäts- und Fallbacksemantik richtet sich nach `Config._load_from_env()` in `src/config.py` (`LITELLM_CONFIG` > `LLM_CHANNELS` > legacy). Begleitende Regressionen siehe `tests/test_llm_channel_config.py` (Konfigurationsquellen-Parsing) und `tests/test_market_review_runtime.py` (gemeinsamer Assemblierungspfad). Diese Schnittstelle bietet derzeit nur Fähigkeit gegen Duplikate auf Einzelprozess-/Einzelmaschinenebene; für Mehrinstanz-Bereitstellungen muss die globale Idempotenz über externe Task-Queues oder verteilte Locks ergänzt werden.
> Hinweis: Nach Auslösung von `POST /api/v1/analysis/market-review` wird der Bericht mit `report_type=market_review` in die Historie geschrieben; du kannst direkt `/api/v1/history` oder `/api/v1/history/{record_id}` abfragen, um das historische Markdown zu erhalten, und so eine erneute Analyseberechnung vermeiden.
> Hinweis: Die Historienliste erhält den neuen Abfrageparameter `report_type`; über `stock_code=MARKET&report_type=market_review` kann die Markt-Rückblick-Historiensammlung separat gelesen werden, vollständig isoliert von der gewöhnlichen Einzelaktien-Historie-Logik.
> Hinweis: Task-Status und Historie-Persistierung von `POST /api/v1/analysis/market-review` enthalten beide `market_review_payload`: `region` ist der kanonische Marktstring der diesmal tatsächlichen Ausführung, außerdem enthält er strukturierte Felder wie `market_scope`, `sections`, `sectors`, `concepts`, `news`, `market_light`, `indices`. Die Web-Markdown-Renderung und die Historie-Details verwenden diese strukturierten Felder wieder; sind die strukturierten Felder leer, wird auf das ursprüngliche Markdown zurückgegriffen.
> Hinweis: Die Laufzeitablauf-Snapshot-Schnittstelle gibt den einheitlichen Vertrag `lanes/nodes/edges/events/summary` zurück. Fehlen beim aktiven Task diagnostics, wird ein skeleton flow zurückgegeben; hat die Task-SSE bereits ein echtes `flow_event` empfangen, enthält der Snapshot die letzten inkrementellen Ereignisse. Die completed-Historie bevorzugt `context_snapshot.diagnostics` und `analysis_context_pack_overview` für die Konstruktion der vollständigen Topologie. `cancel_requested/cancelled` sind gültige Zustände und werden nicht als failed gemappt.
> Hinweis: `breadth` im `market_review_payload` wird nur ausgeliefert, wenn Marktbreitendaten tatsächlich verfügbar sind; bei US-/Hongkong-Aktien oder wenn die Schnittstelle vorübergehend nicht verfügbar ist, wird das Feld nicht ausgeliefert. Die Frontend-Anzeigeschicht muss bei "Feld fehlt" auf "Keine Daten" degradieren und nicht 0 anzeigen.
> Hinweis: Gibt der Endpunkt ein `task_id` zurück, fragt die WebUI per Polling `GET /api/v1/analysis/status/{task_id}` ab, um den Status anzuzeigen. Bei Status `completed` wird ein Abschlusshinweis gegeben (Bericht erzeugt und gemäß Konfiguration gepusht), bei Status `failed` wird der `error`-Grund im Frontend-Fehlerbereich angezeigt.
> Hinweis: `GET /api/v1/history/{record_id}/diagnostics` unterstützt die Primärschlüssel-ID oder `query_id` von Historie-Einträgen und gibt die Zusammenfassung `normal/degraded/failed/unknown`, Schlüsselkettenkomponenten und den kopierbaren entschärften `copy_text` zurück; alte Berichte ohne Diagnose-Snapshot geben `unknown` zurück, ohne das Berichtslesen zu beeinflussen.
> Hinweis: Die Listenzusammenfassung von `GET /api/v1/history` kann die Historie derselben Aktie paginiert nach `stock_code` abfragen und gibt optionale Felder wie Trendbeurteilung, Analysezusammenfassung, Modellname und Preis/Änderung zum Analysezeitpunkt zurück; alte Einträge ohne Snapshot-Felder geben leere Werte zurück. `created_at` und `last_analysis_time` von `/api/v1/history/stocks` verwenden ISO-8601-Zeitstempel mit Serverzeitzonen-Offset; die Datumsfilterung wird weiterhin nach dem lokalen Serverdatum interpretiert. Die Schublade "Historischer Trend" der Web-Berichtsseite verwendet diese Schnittstelle zum Laden derselben Aktienhistorie wieder.
> Hinweis: `GET /api/v1/usage/dashboard` verwendet die Audit-Tabelle `llm_usage` wieder und fügt weder Konfigurationsoptionen noch Datenbankmigrationen hinzu. Die Schnittstelle gibt nur bereits persistierte Aufrufzahlen, Prompt/Completion/Total-Token-Aggregate, modellbezogenen Verbrauch und letzte Aufrufaufzeichnungen zurück, ohne Modellkontextfenster oder Provider-Metadaten abzuleiten.
> Hinweis (Issue #1520): Das in der Liste angezeigte Modellnamensfeld stammt nur aus `model_used` im Historie-Snapshot und dient nur der historischen Nachverfolgungsanzeige; es beeinflusst nicht das Laufzeit-Modellrouting (`litellm_model`, `llm_model_list`), den Provider, die Base-URL und die Konfigurationsmigrations-/Bereinigungssemantik. Der Fallback-Weg ist das Revertieren dieses Commits; die Kompatibilität der Bestands-Historieabfrage/-Schublade/-Schnittstellen bleibt unverändert.
> Hinweis: Historie-Details, synchrone Analyseantworten und abgeschlossene Task-Zustände geben in `report.details.analysis_context_pack_overview` die niedrigsensible Eingabedatenblock-Übersicht zurück; dabei hängen synchrone Analyseantworten von der diesmal bereits persistierten `analysis_history.context_snapshot` ab, und bei `SAVE_CONTEXT_SNAPSHOT=false` ist die Übersicht in neuen Einträgen nicht garantiert. `details.context_snapshot` entfernt dieses Top-Level-Feld und gibt weder das vollständige `AnalysisContextPack` noch eine Prompt-Zusammenfassung zurück.
> Hinweis: `POST /api/v1/agent/chat` und `POST /api/v1/agent/chat/stream` verwenden das vom Frontend übergebene `context.stock_code` als Basiszielwert für Fragen-zur-Aktie und verwenden bei fehlendem `context.report_language` das globale `REPORT_LANGUAGE`; ein vom Aufrufer explizit angegebenes `context.report_language` bleibt bevorzugt. Der Server beurteilt zuerst den stock scope neu. Das Frontend sendet nach dem Wechsel von einem Historienbericht zu Fragen-zur-Aktie kontinuierlich den aktiven stock context; beim Wechsel zurück oder Neuladen einer bestehenden Sitzung wird basierend auf den bereits geladenen historischen Benutzernachrichten das Basis-`{stock_code, stock_name: null}` wiederhergestellt. Der Server beurteilt in jeder Nachrichtenrunde erneut `maintain`/`switch`/`compare`: ohne expliziten Wechsel kann der Aktien-Tool-Aufruf mit `stock_code` nur das aktuelle Ziel abrufen; explizites Umschalten bereinigt die alten Ziel-Historiezusammenfassungen und vorab geladenen Daten; Fragen mit eindeutiger Vergleichsabsicht (vergleichen/vergleich/gegenüber/Unterschied/im Vergleich zu) oder mehreren nicht-aktuellen, expliziten Aktiencodes erlauben die diesmal eindeutig auftretenden Codes, ohne das aktuelle Ziel umzuschreiben. Wenn das Modell Finanzabkürzungen wie TTM, PE, MACD, KDJ, das `MA`-Indikatorwort im Gleitende-Mittel-Kontext oder Börsensegmente wie SH/SZ/BJ/HK/SS fälschlich als Aktiencode für einen Tool-Aufruf behandelt, gibt das Backend ein nicht wiederholbares `stock_scope_violation`-Toolergebnis zurück, ohne das entsprechende Aktien-Tool auszuführen. Toolnamen lösen nur exakte Namen im Register auf; keine provider-Namespaces oder Suffixe werden auf vorhandene Tools geroutet.
> Hinweis: `POST /api/v1/backtest/run` erhält neue Anfrageparameter `analysis_date_from` / `analysis_date_to` (`YYYY-MM-DD`) zum Filtern der Kandidaten nach historischem Analysedatum; ist `analysis_date_from > analysis_date_to`, gibt die Schnittstelle 400 `invalid_params` zurück.
> Hinweis: Läuft der Backtest erfolgreich, aber ohne neue Datenbankeinträge, gibt `BacktestRunResponse.message` eine lesbare Diagnosebeschreibung zurück und `diagnostics` den Fehlersuchkontext (Beispiel: `empty_reason`, `analysis_date_from`, `analysis_date_to`, `eval_window_days`, `min_age_days`, `limit`).
> Hinweis: `GET /api/v1/backtest/results`, `GET /api/v1/backtest/performance` und `GET /api/v1/backtest/performance/{code}` unterstützen synchron `analysis_date_from`, `analysis_date_to`; ohne Übergabe bleibt das historische Verhalten.

> Kompatibilitäts-Audit-Belege:
> - Offizielle Quellen: LiteLLM OpenAI-compatible provider Dokumentation <https://docs.litellm.ai/docs/providers/openai_compatible>; OpenAI Chat-API-Dokumentation <https://platform.openai.com/docs/api-reference/chat/create>; DeepSeek-API-Dokumentation <https://api-docs.deepseek.com/>.
> - Abhängigkeitsversion: Das Projekt begrenzt auf `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (siehe `requirements.txt`); die oben genannten Kompatibilitätssemantik-Regressionstests wurden innerhalb dieses Versionsfensters ausgeführt.
> - Nachprüfbare Tests:
>   - `tests/test_llm_channel_config.py` (Priorität der Konfigurationsquellen und provider/base-url-Zuordnung)
>   - `tests/test_market_review_runtime.py` (Wiederverwendung des Assemblierungspfads von `build_market_review_runtime`)
>   - `tests/test_analysis_api_contract.py` (Vertrag von `/api/v1/analysis/market-review` und Task-Statushauptkette)
> - Rollback/Rückfall: Hat der neue Pfad Probleme, können zunächst historische `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS` und Legacy-`GEMINI_*` / `OPENAI_*` / `ANTHROPIC_*` / `DEEPSEEK_*` wiederhergestellt werden, oder über Desktop-Backup bzw. das mit Admin-Authentifizierung aktivierte Web `POST /api/v1/system/config/import` zurückgerollt und neu gestartet werden; auf Laufzeitebene können `LITELLM_CONFIG` / `LLM_CHANNELS` vorübergehend geleert werden, um den Legacy-Fallback auszulösen.

> Fortschrittsstream-Hinweis: `GET /api/v1/analysis/tasks/stream` erhält zusätzlich zu `task_created / task_started / task_completed / task_failed` das Ereignis `task_progress`. Die gewöhnliche Analyse-Kette aktualisiert in Phasen wie "Kursvorbereitung / Nachrichtenabruf / Kontextaufbereitung / LLM-Generierung / Berichtsspeicherung" kontinuierlich `progress` und `message`. LiteLLM-Streaming-Rückgaben werden serverseitig nur bis zum vollständigen Text akkumuliert; erst nach erfolgreichem finalen JSON-Parsing wird der Historienbericht persistiert; ist Streaming vor dem ersten chunk nicht verfügbar, wird automatisch auf den ursprünglichen Nicht-Streaming-Aufruf zurückgegriffen; schlägt es nach bereits erzeugten Teil-chunks fehl, versucht das System zuerst einen Nicht-Streaming-Retry desselben Modells, danach gemäß der bestehenden Reihenfolge Hauptmodell -> Ersatzmodell weiter.
> Schlägt der Task-Fortschritts-Callback fehl, wird die Hauptkette nicht unterbrochen; das System hebt den Alarm auf warning-Ebene an und gibt die vollständige Ausnahme im Server-Log aus, um die Fehlersuche bei SSE-Push-Unterbrechungen zu erleichtern.
>
> Hinweis: Diese Funktion gehört zu den Laufzeit-SSE- und Fallback-Ketten-Details; sie wird bevorzugt im vollständigen Leitfaden (`full-guide*.md`) dokumentiert und in `README.md` nicht in detaillierte Verhaltensverzweigungen ausgeführt.

**Aufrufbeispiele**:
```bash
# Health-Check
curl http://127.0.0.1:8000/api/health

# Analyse auslösen (A-Aktien)
curl -X POST http://127.0.0.1:8000/api/v1/analysis/analyze \
  -H 'Content-Type: application/json' \
  -d '{"stock_code": "600519"}'

# Strategie durchreichen (optional)
curl -X POST http://127.0.0.1:8000/api/v1/analysis/analyze \
  -H 'Content-Type: application/json' \
  -d '{"stock_code": "600519", "skills": ["bull_trend", "growth_quality"]}'

# Task-Status abfragen
curl http://127.0.0.1:8000/api/v1/analysis/status/<task_id>

# Heutigen LLM-Verbrauch abfragen
curl "http://127.0.0.1:8000/api/v1/usage/summary?period=today"

# Heutiges LLM-Verbrauchs-Dashboard abfragen
curl "http://127.0.0.1:8000/api/v1/usage/dashboard?period=today&limit=50"

# Backtest auslösen (alle Aktien)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'

# Backtest auslösen (bestimmte Aktie)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"code": "600519", "force": false}'

# Backtest auslösen (nach Analysedatumsbereich)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"analysis_date_from": "2026-05-01", "analysis_date_to": "2026-05-31", "limit": 100}'

# Backtest auslösen (bestimmte Aktie + Datumsbereich + erzwungener Neulauf)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"code": "600519", "force": true, "analysis_date_from": "2026-05-01", "analysis_date_to": "2026-05-31"}'

# Gesamte Backtest-Performance abfragen
curl http://127.0.0.1:8000/api/v1/backtest/performance

# Backtest-Performance einer einzelnen Aktie abfragen
curl http://127.0.0.1:8000/api/v1/backtest/performance/600519

# Backtest-Ergebnisse paginiert abfragen
curl "http://127.0.0.1:8000/api/v1/backtest/results?page=1&limit=20"
```

### Benutzerdefinierte Konfiguration

Standardport ändern oder LAN-Zugriff erlauben:

```bash
python main.py --serve-only --host 0.0.0.0 --port 8888
```

### Unterstützte Aktiencode-Formate

| Typ | Format | Beispiel |
|------|------|------|
| A-Aktien | 6-stellige Zahl | `600519`, `000001`, `300750` |
| Börse Peking | 6-stellig beginnend mit 8/4/92, unterstützt `BJ`-Präfix oder `.BJ`-Suffix | `920748`, `BJ920493`, `920493.BJ` |
| Hongkong-Aktien | hk + 5-stellige Zahl | `hk00700`, `hk09988` |
| US-Aktien | 1-5 Buchstaben (optionales .X-Suffix) | `AAPL`, `TSLA`, `BRK.B` |
| japanische Aktien | Yahoo-Suffix `.T` | `7203.T`, `6758.T` |
| koreanische Aktien | Yahoo-Suffix `.KS` / `.KQ` | `005930.KS`, `035720.KQ` |
| US-Indizes | SPX/DJI/IXIC usw. | `SPX`, `DJI`, `NASDAQ`, `VIX` |

### Hinweise

- Browserzugriff: `http://127.0.0.1:8000` (oder der von dir konfigurierte Port)
- Nach der Bereitstellung auf einem Cloud-Server nicht sicher, welche Adresse im Browser einzugeben ist? Siehe [Anleitung zum Web-Interface-Zugriff auf Cloud-Server](deploy-webui-cloud.md)
- Nach Abschluss der Analyse werden automatisch Benachrichtigungen an die konfigurierten Kanäle gepusht
- Diese Funktion wird in der GitHub-Actions-Umgebung automatisch deaktiviert
- Siehe auch [openclaw-Skill-Integrationsleitfaden](openclaw-skill-integration.md)

---

## Häufige Fragen

### Q: Push-Nachrichten werden abgeschnitten?
A: WeCom/Feishu haben eine Nachrichtenlängenbegrenzung; das System sendet bereits automatisch in Segmenten. Für vollständige Inhalte kann die Feishu-Cloud-Dokumentfunktion konfiguriert werden.

### Q: Datenabruf fehlgeschlagen?
A: AkShare verwendet einen Crawler-Mechanismus und kann vorübergehend rate-limitiert werden. Das System hat einen Retry-Mechanismus konfiguriert; in der Regel genügt es, ein paar Minuten zu warten und erneut zu versuchen.

### Q: Wie füge ich Watchlist-Aktien hinzu?
A: Die Umgebungsvariable `STOCK_LIST` ändern, mehrere Codes empfohlen mit englischen Kommas trennen. Das System erkennt auch chinesische Kommas, Pausenpunkte, Semikolons, Leerzeichen und Zeilenumbrüche und normalisiert sie nach dem Speichern auf der Web-Einstellungsseite oder dem Hinzufügen/Entfernen der Watchlist auf englische Kommas.

### Q: GitHub Actions wird nicht ausgeführt?
A: Prüfen, ob Actions aktiviert sind und ob der cron-Ausdruck korrekt ist (beachte, dass es UTC-Zeit ist).

---

Weitere Fragen bitte als [Issue einreichen](https://github.com/ZhuLinsen/daily_stock_analysis/issues)

## Agent-Tool-Datencache und -Persistierung

- `get_daily_history` versucht zuerst, den lokalen `stock_daily`-Tagesdaten-Cache wiederzuverwenden; wenn der Cache frisch ist und mindestens die standardmäßigen 30 Einträge der Startseite abdeckt, werden externe Datenquellen nicht erneut angefragt.
- Fordert der Agent mehr Tage an als im lokalen Cache vorhanden sind, gibt das Tool die tatsächlich verfügbaren Einträge zurück und kennzeichnet über `partial_cache=true`, `requested_days`, `actual_records`, dass es sich um einen partiellen Cache-Treffer handelt.
- Bei fehlendem oder abgelaufenem Cache ruft das Tool die Tagesdaten weiterhin nach der ursprünglichen Logik aus der Datenquelle ab; nach erfolgreichem Abruf wird best-effort in `stock_daily` zurückgeschrieben; ein Speicherfehler blockiert die Agent-Antwort nicht.
- `search_stock_news` und `search_comprehensive_intel` schreiben nach erfolgreicher Rückgabe best-effort in `news_intel` und verwenden die bestehende URL-/Fallback-Key-Deduplizierungslogik.
- `get_realtime_quote` verwendet `stock_daily` nicht als Echtzeitkurs-Cache und schreibt Intraday-Echtzeitkurse auch nicht in die Tagesdatentabelle; für einen Echtzeitkurs-Cache sollte separat eine Echtzeitkurs-Speicherung entworfen werden.

## Agent-Ereignis-Alarmüberwachung

Nach `AGENT_EVENT_MONITOR_ENABLED=true` führt der Schedule-Modus den Alarm-worker gemäß `AGENT_EVENT_MONITOR_INTERVAL_MINUTES` aus. Der worker liest pro Runde die über die Alert-API erstellten und aktivierten persistenten Regeln und bleibt gleichzeitig mit Legacy-Regeln in `AGENT_EVENT_ALERT_RULES_JSON` kompatibel; nach der Auslösung wird weiterhin an die bestehenden Benachrichtigungskanäle gesendet. Die persistenten Regeln von Alert-API/Web unterstützen Echtzeitpreis, Änderungsrate, Handelsvolumen, Tagesdaten-Technische Indikatoren, `watchlist`, `portfolio_holdings`, `portfolio_account` sowie das `market`-Ziel der Markt-Ampel; das Legacy-JSON unterstützt weiterhin nur drei grundlegende Regeltypen.

> Kompatibilitäts- und Migrationshinweis: Dieser Abschnitt dokumentiert das Laufzeitverhalten der aktuellen Ereignis-Alarmregeln (inkl. `price_change_percent`), ohne die Semantik externer Modell-/API-Konfigurationen wie Modellname, provider, Base-URL, LiteLLM, `OPENAI_*`, `DEEPSEEK_*`, `GEMINI_*` zu verändern. Das Legacy-JSON wird nicht automatisch migriert, gelöscht oder umgeschrieben; für einen Rückfall genügt das Löschen oder Deaktivieren von `AGENT_EVENT_MONITOR_ENABLED`, um den Hintergrund-Alarm-worker zu stoppen.

| `alert_type` | Richtungsfeld | Schwellwertfeld | Beschreibung |
| --- | --- | --- | --- |
| `price_cross` | `above` / `below` | `price` | Aktueller Preis durchbricht den angegebenen Preis nach oben oder unten |
| `price_change_percent` | `up` / `down` | `change_pct` | Änderungsrate erreicht den angegebenen Prozentsatz |
| `volume_spike` | - | `multiplier` | Neuestes Handelsvolumen überschreitet das angegebene Vielfache des Durchschnittsvolumens der letzten 20 Tage |
| `ma_price_cross` | `above` / `below` | `window` | Tagesdaten-close kreuzt den Rand von MA(window) nach oben oder unten |
| `rsi_threshold` | `above` / `below` | `period`, `threshold` | RSI kreuzt den Schwellwertrand nach oben oder unten |
| `macd_cross` | `bullish_cross` / `bearish_cross` | `fast_period`, `slow_period`, `signal_period` | Goldener Kreuz oder Todeskreuz an der DIF/DEA-Kante |
| `kdj_cross` | `bullish_cross` / `bearish_cross` | `period`, `k_period`, `d_period` | Goldener Kreuz oder Todeskreuz an der K/D-Kante |
| `cci_threshold` | `above` / `below` | `period`, `threshold` | CCI kreuzt den Schwellwertrand nach oben oder unten |
| `portfolio_stop_loss` | `mode=near|breach` | - | Kontoebener Stop-Loss nahe oder ausgelöst |
| `portfolio_concentration` | - | - | Kontoebene symbol-Konzentration |
| `portfolio_drawdown` | - | - | Kontoebener maximaler Drawdown-Alarm |
| `portfolio_price_stale` | - | - | Positionspreis stale oder missing |
| `market_light_status` | - | `statuses` | Aktueller Markt-Ampelstatus trifft die `red/yellow`-Liste |
| `market_light_score_drop` | - | `min_drop` | Market-Light-Score sinkt gegenüber dem vorherigen Handelstag um den Schwellwert |

Beispiel:

```env
AGENT_EVENT_MONITOR_ENABLED=true
AGENT_EVENT_MONITOR_INTERVAL_MINUTES=5
AGENT_EVENT_ALERT_RULES_JSON=[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":3.0},{"stock_code":"000858","alert_type":"volume_spike","multiplier":2.5}]
```

Der worker schreibt `triggered`, `skipped`, `degraded` und `failed` als Bewertungshistorie in `alert_triggers`; normale, nicht ausgelöste Ereignisse schreiben keine Historie. Für die `triggered`-Historie persistenter Regeln wird nach `rule_id + target + data_source + data_timestamp` best-effort auf denselben Datenpunkt dedupliziert; bei erneutem Treffer wird der früheste Auslöse-Eintrag wiederverwendet, und bei fehlendem `data_timestamp` wird nicht dedupliziert. Nach einem echten Auslösen wird der attempt jedes Benachrichtigungskanals in `alert_notifications` geschrieben und für persistente, über die Alert-API erstellte Regeln der Geschäfts-Cool-down-Zustand in `alert_cooldowns`; schlägt das Lesen des persistenten Cool-downs fehl, verwendet der worker vorübergehend einen In-Process-Fingerprint, um doppelte Pushs während eines DB-Fehlers zu vermeiden. Legacy-`AGENT_EVENT_ALERT_RULES_JSON`-Regeln verwenden weiterhin die In-Process-Fingerprint-Unterdrückung und schreiben keinen persistenten Cool-down; die Rauschunterdrückung `notification_noise.py` der Benachrichtigungsinfrastruktur wirkt weiterhin unabhängig. Die Web-Regelliste verwendet das vom Backend zurückgegebene `cooldown_active` zur Beurteilung des Cool-down-Zustands, damit die Zeitzonenauflösung des Browsers die Anzeige nicht beeinflusst.

Regeln für Technische Indikatoren verwenden nur die Randauslösung des Tagesdaten-close; die partial-bar-Behandlung ist eine Heuristik mit Server-Lokalzeit + 16:00, ohne präzise Marktkalender-Beurteilung. `watchlist` wird nach jeder Runde anhand von `STOCK_LIST` expandiert, `portfolio_holdings` wird aus den Nicht-Null-Positionen des Positions-Snapshots nach symbol dedupliziert expandiert, `portfolio_account` verwendet den Positionsrisiko-Dienst für die kontoebene Aggregatbewertung. Das target der `market`-Regel unterstützt nur `cn|hk|us|jp|kr` und verwendet das strukturierte `MarketLightSnapshot`; `trade_date` stammt aus der jeweiligen Market-Übersicht, `data_quality=unavailable` überspringt die Auslösung, Nicht-Handelstage werden vom Handelstags-Gate übersprungen, und `market_light_score_drop` vergleicht nur den Score über Handelstage hinweg. Die "Alarm"-Seite der WebUI kann persistente Regeln verwalten, einmalige dry-run-Tests ausführen und die Auslösehistorie, Benachrichtigungsversuche und den schreibgeschützten Cool-down-Zustand ansehen; der Listen-Cool-down-Zustand von Batch-Regeln ist die Zusammenfassung der Elternregel, und der Cool-down von Unterzielen richtet sich nach der Auslösehistorie. Detaillierte Grenzen siehe [Echtzeit-Alarmzentrum](alerts.md).

## Positionsverwaltungshinweise

### Was die Seite `/portfolio` kann

- Vollständige Positionen ansehen oder in die Einzelkonten-Perspektive wechseln.
- Zwischen den zwei Kostenmethoden `fifo` / `avg` umschalten, Snapshot-KPI, Risikozusammenfassung und das Top-Positions-Konzentrationsdiagramm ansehen.
- Direkt auf der Web-Seite Konten anlegen, versehentlich erstellte Konten löschen oder Ereignisse wie Trades, Cash-Flows und Unternehmensmaßnahmen erfassen.
- Positionsaufzeichnungen per CSV importieren; zuerst `dry_run`-Vorschau, dann entscheiden, ob formal geschrieben wird.
- In der Ereignisliste nach Konto, Datum, Richtung, Code usw. filtern und Einzelkonto-Ereignisse mit Löschkorrektur bearbeiten.

### Zugehörige Schnittstellen

| Schnittstelle | Methode | Beschreibung |
|------|------|------|
| `/api/v1/portfolio/snapshot` | GET | Positions-Snapshot abfragen |
| `/api/v1/portfolio/risk` | GET | Risikozusammenfassung abfragen |
| `/api/v1/portfolio/trades` | GET | Trade-Aufzeichnungen paginiert abfragen |
| `/api/v1/portfolio/cash-ledger` | GET | Cash-Flows paginiert abfragen |
| `/api/v1/portfolio/corporate-actions` | GET | Unternehmensmaßnahmen paginiert abfragen |
| `/api/v1/portfolio/imports/csv/brokers` | GET | Eingebaute CSV-Broker-Parser abfragen |
| `/api/v1/portfolio/fx/refresh` | POST | Wechselkurs-Cache manuell aktualisieren |
| `/api/v1/portfolio/accounts/{account_id}` | DELETE | Positionskonto löschen/archivieren |
| `/api/v1/portfolio/trades/{trade_id}` | DELETE | Trade-Aufzeichnung löschen |
| `/api/v1/portfolio/cash-ledger/{entry_id}` | DELETE | Cash-Flow löschen |
| `/api/v1/portfolio/corporate-actions/{action_id}` | DELETE | Unternehmensmaßnahme löschen |

> Abfrage-Schnittstellen unterstützen einheitlich gängige Filterparameter wie `account_id`, `date_from`, `date_to`, `page`, `page_size`; Ereignislisten geben die einheitliche Struktur `items`, `total`, `page`, `page_size` zurück.

### Nutzungsverhaltenshinweise

- Der CSV-Import enthält eingebaute Parser für `huatai`, `citic`, `cmb`; schlägt die Broker-Listen-Schnittstelle fehl, greift die Web-Seite automatisch auf diese eingebauten Optionen zurück.
- Der Importablauf parst das CSV zuerst in normalisierte Einträge und übermittelt sie dann einzeln an das Positions-Hauptbuch; blockierte Zeilen werden in `failed_count` gezählt, ohne dass ein einzelner Zeilenkonflikt den gesamten Batch-Anfragestatus zum Fehlschlag bringt.
- Das Löschen von Konten verwendet eine Soft-Delete-Semantik: Standard-Kontenliste, Snapshot, Risiko, Erfassungseinstieg und Ereignisliste zeigen das Konto nicht mehr an, aber Trades, Cash-Flows und Unternehmensmaßnahmen werden nicht physisch bereinigt; zur Korrektur einer einzelnen Buchung muss vor der Kontoarchivierung der Löschkorrektur-Einstieg in der Ereignisliste verwendet werden.
- Trade-Deduplizierung bevorzugt die kontounique `trade_uid`; bei Fehlen wird auf einen deterministischen Hash basierend auf Datum, Code, Richtung, Menge, Preis, Gebühren, Steuern und Währung zurückgegriffen.
- Verkäufe validieren zuerst die verfügbare Menge; Überverkauf gibt `409 portfolio_oversell` zurück; bei parallelen Schreibkonflikten kann `409 portfolio_busy` zurückgegeben werden.
- `positions[]` im Positions-Snapshot gibt Preis-Metainformationen wie `price_source`, `price_date`, `price_stale` und `price_available` zurück; der Snapshot des Tages versucht standardmäßig zuerst den Echtzeitkurs, greift bei nicht verfügbarem oder nicht positivem Echtzeitkurs auf den historischen Schlusskurs von `as_of` oder den zuletzt davor liegenden zurück; mit `include_realtime=false` wird der Echtzeitkurs übersprungen und direkt der lokale historische Schlusskurs-Rückfallpfad verwendet, und die Web-Positionsseite verwendet diesen Modus, um die Positionsliste priorisiert zu rendern und so zu vermeiden, dass langsame externe Echtzeitquellen den ersten Screen blockieren. Historische `as_of`-Snapshots ziehen keine Echtzeitkurse ab und behandeln den Kostenpreis auch nicht stillschweigend als aktuellen Preis; Positionen ohne Preis werden mit `price_available=false` markiert und von der Marktwert- und Unrealized-Gewinn/Verlust-Aggregation ausgeschlossen.
- Der Wechselkurs-Refresh versucht zuerst Online-Quellen; schlägt der Online-Abruf fehl, wird auf den letzten Cache zurückgegriffen und `is_stale=true` markiert, um die Gesamtverfügbarkeit von Snapshot und Risikoseite zu erhalten.
- Bei `PORTFOLIO_FX_UPDATE_ENABLED=false` gibt die manuelle Refresh-Schnittstelle eindeutig "Online-Refresh deaktiviert" zurück; die Seite führt nicht in die Irre mit "Derzeit keine aktualisierbaren Währungspaare".
- Die Risikozusammenfassung enthält Informationen wie Konzentration, Drawdown und Stop-Loss-Nähe; `sector_concentration` versucht bevorzugt, nach Sektor zu klassifizieren, und degradiert bei Fehlschlag auf `UNCLASSIFIED`, ohne die Rückgabe des Risikoergebnisses zu blockieren.

### Agent liest Positionen

- Der Agent kann über `get_portfolio_snapshot` eine kontoorientierte kompakte Positionszusammenfassung abrufen, die standardmäßig einen reduzierten Risikoblock enthält und sich zur Kontrolle des Token-Verbrauchs eignet.
- Optionale Parameter umfassen `account_id`, `cost_method`, `as_of`, `include_positions` und `include_risk`.
- Schlägt die Erstellung des Risikoblocks fehl, wird der Snapshot weiterhin zurückgegeben; ist das Positionsmodul in der aktuellen Umgebung nicht aktiviert, gibt das Tool strukturiert `not_supported` zurück.
