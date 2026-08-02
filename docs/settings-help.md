# Wartungshinweise zur Konfigurationshilfe der Einstellungsseite

Die Konfigurationshilfe der Einstellungsseite dient dazu, die wichtigsten Erläuterungen der Konfigurationspunkte in die WebUI zu integrieren, damit der Benutzer weniger zwischen Einstellungsseite und Dokumenten hin- und herwechseln muss. Auf der Seite bleibt weiterhin eine kurze Beschreibung; die ausführliche Erläuterung wird über das Hilfe-Symbol neben dem Konfigurationspunkt geöffnet.

Dieser Text erläutert nur die Wartungsregeln des Hilfesystems und ersetzt nicht die vollständige Konfigurationsdokumentation. Konfigurationssemantik, Standardwerte, Laufzeitpriorität und Troubleshooting-Details richten sich weiterhin nach `.env.example`, `docs/full-guide.md` sowie den jeweiligen Fachdokumenten als Tatsachenquellen.

## Datenstruktur

Das Backend-Konfigurationsregister fügt in `src/core/config_registry.py` Hilfs-Metadaten für die Felder hinzu:

- `help_key`: Der stabile Key für die mehrsprachigen Hilfetexte des Frontends.
- `examples`: Direkt anzeigbare Konfigurationsbeispiele. Sensible Felder dürfen nur Platzhalter verwenden, z. B. `sk-xxxx`, `your_token`.
- `docs`: Zugehörige Dokumentationslinks, bevorzugt auf bereits vorhandene Fachdokumente oder den vollständigen Leitfaden im Repository verweisend.
- `warning_codes`: Stabile Hinweis-Codes für das Frontend oder spätere Validierungserweiterungen.

Die langen Frontend-Texte werden in `apps/dsa-web/src/locales/settingsHelp.ts` gepflegt:

- Standardmäßig werden chinesische Texte angezeigt.
- Die englischen Texte behalten dieselbe Struktur bei, um spätere Spracherweiterungen zu erleichtern.
- Die Texte sollen Zweck, Wertangaben, Auswirkungsbereich, Hinweise und zugehörige Dokumentation erklären, aber nicht die vollständigen Fachdokumente kopieren.

## Hinweise zur WebUI-Sprache (kein Konfigurationspunkt)

Dieses Projekt fügt eine separate WebUI-Oberflächensprachfunktion (`zh` / `en`) hinzu, die für statische Seitentexte, Navigation und allgemeine Steuerelement-Texte verwendet wird. Dieser Status ist von `REPORT_LANGUAGE` entkoppelt und ändert nicht die Semantik der Berichtssprache.

- Status-Key: `dsa.uiLanguage` (`localStorage`, browserseitig persistiert).
- Initialisierungspriorität: `localStorage`-Wert bevorzugt, dann die Browsersprache erkennen (`zh-*` / `en-*`), zuletzt Fallback auf `zh`.
- Dieser Sprachschalter gehört nicht zu den `.env`-Konfigurationsfeldern und erscheint nicht in der konfigurierbaren Feldliste von `system/config`.
- Der Oberflächenwechsel synchronisiert `document.documentElement.lang` (`zh-CN` oder `en`), um Barrierefreiheit und Accessibility-Semantik zu unterstützen.

## Abdeckungsumfang

PR1 deckt die Infrastruktur und die ersten repräsentativen Konfigurationspunkte ab:

- `STOCK_LIST`
- `LITELLM_MODEL`
- `LLM_CHANNELS`
- `FEISHU_WEBHOOK_URL`
- `WEBUI_HOST`

PR2 deckt weiterhin häufige, fehleranfällige Konfigurationspunkte ab:

- AI-Modell-Laufzeit: Agent-Hauptmodell, Fallback-Modell, erweiterte YAML-Routing, temperature, Provider-API-Key, OpenAI-kompatible Base-URL.
- Interne Felder des LLM-Channels-Editors: Kanalname, Protokoll, Base-URL, API-Key, Modellliste, Laufzeit-Fähigkeitsprüfung, Hauptmodell, Agent-Hauptmodell, Fallback, Vision und temperature.
- Datensources und Suche: Tushare, Fernaktualisierungsschalter der Aktienindizes, Priorität der Echtzeitkurse, Echtzeit-Technikindikatoren, Such-API-Key, SearXNG, Chip-Verteilung, Nachrichtenfenster.
- Benachrichtigungen: Webhook, Telegram, E-Mail, Discord/Slack und andere Chat-Plattformen, Berichtsausgabe, Webhook-SSL-Validierung.
- WebUI / auth / schedule / proxy: Host, Port, Login-Schutz, vertrauenswürdiger Reverse-Proxy, geplante Tasks, Handelstagsprüfung, Netzwerk-Proxy.

PR3 registered-field slice / schrittweise Ergänzung: Fokussiert auf die Hilfe-Ergänzung der tatsächlich angezeigten/konfigurierbaren Felder der Web-Einstellungsseite, einschließlich der derzeit sichtbaren Felder der allgemeinen Konfigurationskarte und der bedingt sichtbaren AI-legacy-Felder:

- Agent-Konfiguration (22 Felder): Ask-Stock-Generierungsmethode, Agent-Modus, maximale Reasoning-Schritte, Strategieliste, Strategieverzeichnis, natürliche Sprachrouting, Architektur, Orchestrator-Modus, Timeout, Risiko-Veto, Deep-Research-Budget/Timeout, Memory, Strategie-Autogewichte, Strategie-Routing, Komprimierung des sichtbaren Ask-Stock-Konversationskontexts, Event-Monitoring-Schalter/Intervall, Alarmregel-JSON. Normale Benutzer sehen nur den neuen `AGENT_BACKEND`-Auswahlschalter; das alte `AGENT_GENERATION_BACKEND` bleibt nur für die Konfigurationskompatibilität erhalten.
- Backtest-Konfiguration (5 Felder): Backtest-Schalter, Bewertungsfenster, minimale Datensatzalter, Engine-Version, neutrales Renditeband.
- Berichtskonfiguration (9 Felder): Nur Zusammenfassung pushen, Modellnamen anzeigen, Template-Verzeichnis, Rendering-Engine, Integritätsprüfung/Retry, Vergleich historischer Signale, Einzelaktien-Push, zusammengeführte E-Mails.
- Benachrichtigungsrouting-Konfiguration (9 Felder): Kanalrouting für Berichte/Alarme/Systemfehler, Deduplizierung/Cooldown, Ruhezeiten/Zeitzone, Mindeststufe, Tageszusammenfassung (reserviert).
- Systemlaufzeit (7 Felder): Log-Level, Debug-Modus, maximale Nebenläufigkeit, Analyseintervall, Marktanalyse-Schalter/Markt/Farbschema.
- AI-legacy- und Anspire-Konfiguration: Provider-spezifische Mehrfach-Keys, Modellname, Temperatur, Vision-Modell, max tokens und Anspire-LLM-Gateway-Felder.
- Datensources und Suche: TickFlow, SerpAPI, Brave, Bocha, MiniMax, SearXNG-Public-Instances, BIAS-Schwellenwert und Pytdx-Serverfelder.
- Erweiterte Benachrichtigungsfelder: Feishu-Erweiterte-Sicherheits-/App-Felder, Telegram-Topic, Discord/Slack-Erweiterte-Felder, Pushover, ntfy, Gotify, PushPlus, ServerChan3, AstrBot und benutzerdefinierte Webhook-Erweiterte-Template-/Auth-Felder.

Nach dem Abschluss von Issue #1512 zeigt die Web-Einstellungsseite nur noch die formalen Felder aus dem Backend-Konfigurationsregister. Nicht registrierte `.env`-Keys werden nicht mehr als normale bearbeitbare Einstellungselemente angezeigt, um zu vermeiden, dass raw-Keys, `Auto-inferred field metadata.` und Konfigurationspunkte ohne Hilfe-Button in die chinesische Oberfläche gelangen; diese Keys können weiterhin über die `.env`-Datei oder die Import-/Export-Funktion erhalten und gepflegt werden.

Ausnahme: Die dynamischen Kanal-Detail-Keys, die von `LLM_CHANNELS` deklariert werden (z. B. `LLM_DEEPSEEK_API_KEY`, `LLM_MY_PROXY_MODELS`), bleiben in der Rückgabe des Konfigurationsendpunkts erhalten, damit der „AI-Modell-Anbindung"-Editor sie lesen und speichern kann; sie werden nicht als normale Konfigurationskarten angezeigt und übernehmen auch nicht die betriebliche Ausblendungssemantik von `WEB_SETTINGS_HIDDEN_FROM_UI`.

Niederfrequente/betriebliche `.env`-Variablen, die vorerst nicht in die Web-Einstellungsseite aufgenommen werden, umfassen `DATABASE_PATH`, `SQLITE_*`, `USE_PROXY`, `PROXY_HOST`, `PROXY_PORT` usw. Wenn diese Felder später in der Web-Oberfläche bearbeitet werden sollen, sollten sie zunächst in `src/core/config_registry.py` formal registriert und mit Hilfe-Metadaten ergänzt werden, statt sich auf automatische Ableitung zu verlassen.

### Abdeckungsgrenzen

- Die Reihe `settings.llm_channel.*` in `settingsHelp.ts` sind Feldbeschreibungen im Inneren des LLM-Kanaleditors, dienen nur der Frontend-Renderung und entsprechen keinem separaten Konfigurationspunkt in `.env`; dies ist ein bewusstes „eingebautes Erweiterungs"-Design in PR2, um die Bedienbarkeit des Editors zu verbessern.
- Alle anderen Hilfe-Texte sollten sich über den `help_key` eines Feldes in `src/core/config_registry.py` auf die Backend-Registriermetadaten abbilden lassen, um eine einheitliche Wartung mit den Dokumentquellen und `warning_codes` zu ermöglichen.

## Priorität der Tatsachenquellen

Beim Hinzufügen oder Ändern von Hilfe-Texten bevorzugt an folgenden Stellen gegenprüfen:

1. `.env.example`: Konfigurations-Key-Namen, Standardwerte, Beispielformate und sensible Platzhalter.
2. `docs/full-guide.md`: Hauptkonfigurationshinweise, Ausführungseinträge und Bereitstellungskontext.
3. `docs/LLM_CONFIG_GUIDE.md`, `docs/llm-providers.md`: LLM-Priorität, Channels, provider/model, Kompatibilitätsgrenzen und Troubleshooting.
4. Fachdokumente: z. B. `docs/bot/feishu-bot-config.md`, `docs/deploy-webui-cloud.md`, `docs/desktop-package.md`.
5. Code-Implementierung und Tests: Wenn Dokument und Code inkonsistent sind, gilt zuerst die ausführbare Implementierung, und die Dokumente werden synchron korrigiert.

## Wartungsgrenzen

- Hilfe-Texte dürfen die Konfigurationsspeicherung, Validierung, Laufzeitpriorität, `.env`-Rückgabe oder Umgebungsvariablen-Override-Semantik nicht ändern.
- Keine echten Schlüssel, Konten, Tokens, vollständige Webhook-Werte oder lokale absolute Pfade anzeigen.
- Wenn LLM-bezogene Beispiele konkrete Provider-Präfixe, Modellnamen oder Base-URLs enthalten, müssen sie auf die aktuellen Repository-Dokumente oder offiziellen Quellen zurückführbar sein; sonst Platzhalter verwenden oder auf die Tatsachenquelle verlinken.
- Die Verfügbarkeit von Drittanbieter-Modellen/APIs, das LiteLLM-Kompatibilitätsfenster oder die Provider-Fallback-Regeln werden in den Einstellungshilfen nicht separat zugesichert; bei Änderungen müssen die Fachdokumente und die PR-Kompatibilitätshinweise synchron aktualisiert werden.
- Chinesische und englische Texte sollten denselben semantischen Umfang bewahren. Wenn nur eine Sprache aktualisiert wird, muss der Grund in der Übergabeerläuterung angegeben werden.
- Die kurze Beschreibung im ersten Bildschirm bleibt prägnant; die ausführliche Erläuterung liegt im Hilfe-Dialog, um Wiederholungen zwischen Hover-Tooltip und ständig angezeigter Kurzbeschreibung zu vermeiden.

## Neustart-Semantik

Das Speichern der Einstellungsseite schreibt normalerweise nur in `.env` und löst eine zur Laufzeit nachladbare Konfigurationsaktualisierung aus. Hilfe-Texte und `warning_codes` müssen die folgenden Fälle explizit unterscheiden:

- `WEBUI_HOST`, `WEBUI_PORT`: Lauschadresse und Port werden nur beim Prozessstart gebunden; nach dem Speichern muss der aktuelle Prozess, Docker-Container oder Dienstmanager neu gestartet werden, damit sie wirksam werden.
- `RUN_IMMEDIATELY`: Einmalige Laufkonfiguration beim Start im Nicht-Schedule-Modus; nach dem Speichern wird kein bereits laufender WebUI/API-Prozess sofort eine Analyse auslösen.
- Die Web-Einstellungsseite legt interne Keys wie `SCHEDULE_TIME` / `SCHEDULE_TIMES` / `SCHEDULE_RUN_IMMEDIATELY` nicht direkt offen; der Benutzer pflegt über die Karte „Geplante Tasks" den Aktivierungsstatus, mehrere Ausführungszeiten und eine Sofortausführung.
- `SCHEDULE_ENABLED`: WebUI/API/Desktop-Langzeitprozesse (einschließlich `python main.py --serve --schedule`) starten oder stoppen nach dem Speichern den Runtime-Scheduler nach dem neuen Wert; der reine CLI-Schedule-Modus (`python main.py --schedule`) läuft weiterhin nach den Startparametern und der Konfiguration.
- `SCHEDULE_TIME`, `SCHEDULE_TIMES`: Kein Neustart erforderlich. Wenn `SCHEDULE_TIMES` leer ist, wird `SCHEDULE_TIME` verwendet; der bereits laufende Scheduler baut die Daily Jobs nach der neuen Zeit neu auf.
- `SCHEDULE_RUN_IMMEDIATELY`: Startverhalten im Schedule-Modus; nach dem Speichern führt der aktuelle Prozess nicht sofort eine Analyse aus; für die manuelle Ausführung die run-now-API des Runtime-Schedulers verwenden.
- Die run-now-API des Runtime-Schedulers akzeptiert Anfragen nur, wenn keine Analysenaufgabe läuft; wenn bereits eine Analyse ausgeführt wird, wird ein belegter Status zurückgegeben und die Web-Einstellungsseite weist darauf hin, es später erneut zu versuchen.
