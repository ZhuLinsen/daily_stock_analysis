# Basis der Benachrichtigungsfunktionen

Dieses Dokument hält den Endzustand der Benachrichtigungsfunktionen P0–P7 fest: Kanäle, Konfigurationsschlüssel, GitHub-Actions-Zuordnung, Web-Einstellungsmetadaten, CLI-Diagnosekriterien, Web-Ein-Klick-Test, Semantik der benutzerdefinierten Webhook-Body-Vorlage, Benachrichtigungs-Routing-Strategie, Rauschunterdrückungsmechanismus, Fehlerisolierung von Sammelberichten, ntfy-/Gotify-First-Class-Kanäle, WebPush-/Apprise-Bewertung sowie die kontextbezogenen Konfigurationshinweise für lokal / Docker / GitHub Actions / Desktop. P0 legt nur die Basislinie und eine reine Lese-Diagnose fest; P1 ergänzt den echten Web-Test je Kanal; P2 produktiviert die bestehende Body-Vorlage; P3 ergänzt das Routing für report / alert / system_error; P4 ergänzt die prozessinterne Rauschunterdrückung; P5 stärkt die Testdiagnose und die kanalweise Fehlerisolierung von Sammelberichten; P6-A führt ntfy ein; P6-C führt Gotify ein; P6-D bewertet nur WebPush / Apprise; P7 schließt die Dokumentation und die Automatisierung der Actions-env-Zuordnungstabelle ab, ohne neue Laufzeitabhängigkeiten, Konfigurationszugänge, per-URL-Vorlagen, kanalübergreifende Persistenz, echte tägliche Zusammenfassungen oder Wiederholungsschleifen hinzuzufügen.

## Kanal-Basislinie

| Kanal | Typ | Minimal key | Advanced key | Beschreibung |
| --- | --- | --- | --- | --- |
| DingTalk Webhook | Statische Konfiguration | `DINGTALK_WEBHOOK_URL` | `DINGTALK_SECRET` | Unterstützt die signierte Sicherheitsmethode; in die Web-UI-Einstellungsseite und den Ein-Kanal-Test integriert. |
| WeCom | Statische Konfiguration | `WECHAT_WEBHOOK_URL` | `WECHAT_MSG_TYPE` | Nimmt nach der Konfiguration an der Batch-Benachrichtigung teil |
| Feishu Webhook / App Bot | Statische Konfiguration | `FEISHU_WEBHOOK_URL` oder `FEISHU_APP_ID` + `FEISHU_APP_SECRET` + `FEISHU_CHAT_ID` | `FEISHU_WEBHOOK_SECRET`, `FEISHU_WEBHOOK_KEYWORD`, `FEISHU_RECEIVE_ID_TYPE`, `FEISHU_DOMAIN` | Webhook-URL hat Vorrang; wenn kein Webhook konfiguriert ist, kann das App-Bot-Triple aktiv an eine bestimmte Gruppe / einen bestimmten Nutzer senden. `FEISHU_STREAM_ENABLED` steht nur für Event-Abo / Stream Bot und fließt nicht in die Beurteilung der Konfigurationsvollständigkeit für aktive Benachrichtigungen ein |
| Telegram | Statische Konfiguration | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `TELEGRAM_MESSAGE_THREAD_ID` | Token und Chat-ID müssen gemeinsam vorhanden sein |
| E-Mail | Statische Konfiguration | `EMAIL_SENDER`, `EMAIL_PASSWORD` | `EMAIL_RECEIVERS`, `EMAIL_SENDER_NAME` | Wenn `EMAIL_RECEIVERS` leer ist, wird an sich selbst gesendet |
| Pushover | Statische Konfiguration | `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN` | - | Die beiden Keys müssen gemeinsam vorhanden sein |
| ntfy | Statische Konfiguration | `NTFY_URL` | `NTFY_TOKEN`, `WEBHOOK_VERIFY_SSL` | `NTFY_URL` muss den Topic-Pfad enthalten, z. B. `https://ntfy.sh/my-topic` |
| Gotify | Statische Konfiguration | `GOTIFY_URL`, `GOTIFY_TOKEN` | `WEBHOOK_VERIFY_SSL` | `GOTIFY_URL` ist die Server-Basis-URL und enthält kein `/message`; das Token wird über den `X-Gotify-Key`-Header gesendet |
| PushPlus | Statische Konfiguration | `PUSHPLUS_TOKEN` | `PUSHPLUS_TOPIC` | `PUSHPLUS_TOPIC` wirkt nur, wenn ein Token vorhanden ist |
| Server酱3 | Statische Konfiguration | `SERVERCHAN3_SENDKEY` | - | Push an die Mobile App |
| Benutzerdefinierter Webhook | Statische Konfiguration | `CUSTOM_WEBHOOK_URLS` | `CUSTOM_WEBHOOK_BEARER_TOKEN`, `CUSTOM_WEBHOOK_BODY_TEMPLATE`, `WEBHOOK_VERIFY_SSL` | Unterstützt mehrere URLs, durch Kommas getrennt |
| Discord | Statische Konfiguration | `DISCORD_WEBHOOK_URL` oder `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` | `DISCORD_INTERACTIONS_PUBLIC_KEY` | Webhook und Bot können beide das Senden aktivieren |
| Slack | Statische Konfiguration | `SLACK_WEBHOOK_URL` oder `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | - | Der Bot wird bevorzugt zum Senden von Text und Bildern im selben Kanal verwendet |
| AstrBot | Statische Konfiguration | `ASTRBOT_URL` | `ASTRBOT_TOKEN`, `WEBHOOK_VERIFY_SSL` | `ASTRBOT_TOKEN` optional |
| `UNKNOWN` | Fallback-Enum | - | - | Nur als Fallback für unbekannte Kanäle; wird nicht durch statische Umgebungsvariablen aktiviert |
| DingTalk-Sitzung | Laufzeit-Kontext | - | - | Wird aus dem Kontext der Quellnachricht extrahiert; kann nicht allein über `.env` statisch bestimmt werden |
| Feishu-Sitzung | Laufzeit-Kontext | - | - | Wird aus dem Kontext der Quellnachricht extrahiert; Ergebnisse interaktiver Befehle gehen nur an die Quellsitzung zurück |
| Telegram-Sitzung | Laufzeit-Kontext | - | - | Wird aus dem Kontext der Quellnachricht extrahiert; Ergebnisse interaktiver Befehle gehen nur an die Quellsitzung zurück |

Das Senden langer Discord-Berichte nutzt die bestehende Fragmentierungskette: Eine einzelne `content`-Nachricht überschreitet zur Laufzeit nicht das Discord-Limit von 2000 Zeichen; sowohl Webhook als auch Bot API senden stückweise und warten kurz zwischen den Teilen; bei einem 429 wird gemäß dem von Discord zurückgegebenen `retry_after` bzw. `Retry-After` begrenzt wiederholt, damit nach einer zwischenzeitlichen Ratenbegrenzung nicht nur der erste Teil des Berichts ankommt.

## Aufteilung in Minimal / Advanced

- Minimal key: Mindestkonfiguration, die ausreicht, um einen Benachrichtigungskanal zu aktivieren.
- Advanced key: beeinflusst nur Authentifizierung, Sicherheit, Format, Threads, Gruppen, Zertifikatsprüfung oder Darstellung; kann einen Kanal nicht allein aktivieren.
- Die `NOTIFICATION_*_CHANNELS` aus P3 gehören zu den Advanced keys: Sie schränken nur bereits aktivierte Kanäle ein und aktivieren keinen Kanal für sich.
- Die `NOTIFICATION_DEDUP_TTL_SECONDS`, `NOTIFICATION_COOLDOWN_SECONDS`, `NOTIFICATION_QUIET_HOURS`, `NOTIFICATION_TIMEZONE`, `NOTIFICATION_MIN_SEVERITY`, `NOTIFICATION_DAILY_DIGEST_ENABLED` aus P4 gehören zu den Advanced keys: Sie beeinflussen nur die Sende-Strategie bereits aktivierter statischer Kanäle und aktivieren keinen Kanal für sich.
- `REPORT_SHOW_LLM_MODEL` ist ein Schalter für die Berichtsanzeige: Bei Standardwert `true` wird am Ende des Benachrichtigungsberichts das für diese Analyse verwendete LLM-Modell angezeigt, bei `false` ausgeblendet. Der Parameter beeinflusst nur die Berichtsdarstellung; er ändert nicht die Laufzeit-Provider-/Modell-/Basis-URL, das LiteLLM-Routing oder die Logik zum Speichern, Migrieren oder Bereinigen von Modellen. Als Rückfall wird der Wert wieder auf `true` gesetzt oder die Variable entfernt.
- `WEBHOOK_VERIFY_SSL` ist der gemeinsame Schalter zur Zertifikatsprüfung für Webhook-artige HTTPS-Benachrichtigungsanfragen, die diese Konfiguration lesen.
- WebPush, Apprise, feineres Routing, kanalübergreifende Rauschunterdrückung und echte tägliche Zusammenfassungen gehen vorerst nicht in die Laufzeitimplementierung ein; falls solche Konfigurationen künftig eingeführt werden, sollten zuerst dieses Dokument, `.env.example`, die Web-Metadaten und die Regressionstests aktualisiert werden.
- Bark bleibt bei der Custom-Webhook-Basislinie; es werden keine erstklassigen `BARK_*`-Konfigurationen ergänzt.
- Der Sendepfad des Feishu App Bot nutzt das bereits in `requirements.txt` vorhandene `lark-oapi>=1.0.0` wieder und ist keine neue Abhängigkeit; die Standard-Quellinstallation, Docker, der tägliche GitHub-Actions-Workflow und die Desktop-Build-Kette installieren alle über `pip install -r requirements.txt`. Offizielle Grundlage: [Feishu message create OpenAPI](https://open.feishu.cn/document/server-docs/im-v1/message/create), [lark-oapi PyPI](https://pypi.org/project/lark-oapi/), [SDK repo](https://github.com/larksuite/oapi-sdk-python). Der Datei-Upload des App Bot hängt von der `im.v1.file.create`-API desselben SDKs ab, offizielle Dokumentation: [Feishu file create OpenAPI](https://open.feishu.cn/document/server-docs/im-v1/file/create).

## Berichtsdarstellung und Fragmentierung

Der Einstiegspunkt, die Inhaltsquelle und das Gesamtlayout der aktuell standardmäßig gepushten Berichte bleiben unverändert. In dieser Phase wird nur der technische Pfad der Benachrichtigungsdarstellung vereinheitlicht: Es werden Kanal-Fähigkeitsprofile, die Nachrichtenstruktur vor dem Versand und eine strukturbewusste Fragmentierungsfähigkeit etabliert, damit beim späteren Ausbau einzelner Kanäle keine parallele Logik weiter in den jeweiligen Sendern aufgetürmt wird.

Der Standard-Sendepfad übernimmt das bestehende Verhalten der Sender, ohne den neuen Renderer anzubinden: Feishu und Telegram verwenden weiterhin die bisherige Kompatibilitätskonvertierung, WeCom und Slack die bisherige Fragmentierungslogik, um die online sichtbare Berichtsdarstellung nicht zu verändern. Die neu hinzugefügten Kanal-Fähigkeitsprofile, PreparedMessage, Renderer-Presets und die strukturbewusste Fragmentierung dienen nur als Grundlage für spätere Erweiterungen; sollen kanalspezifische Renderer für WeCom, Feishu, Telegram, Slack usw. aktiviert werden, ist das schrittweise über explizite Konfiguration, echte Sendeverifikation und Regressionstests zu tun.

Kompatibilitäts-Ausnahmen:
- In dieser Runde werden die Sendepfade von `src/notification_sender/wechat_sender.py`, `src/notification_sender/slack_sender.py` und `src/notification_sender/telegram_sender.py` nicht verändert; in `src/notification_sender/feishu_sender.py` wird der Datei-Sendepfad `send_feishu_file()` ergänzt, im Webhook-Modus wird auf das Senden des Dateiinhalts als Text zurückgefallen, der App-Bot-Textsendepfad (`send_to_feishu` → `_send_via_app_bot`) bleibt unverändert.
- `model_used` wird nur am Ende der Berichtsdarstellung angezeigt und nimmt nicht an der Laufzeitauswahl, Speicherung, Bereinigung oder Migration von provider/model/base_url teil. Falls ein CI-Scan nach Schlüsselwörtern wie „provider/API-Kompatibilitätsmigration“ sucht, sollte der Trefferbereich zuerst auf die `model_used`-Beispiele in den Test-Fixtures und die Berichts-Snapshot-Fixtures (`tests/fixtures/notification_reports/*.md`) sowie die reine Anzeige-Schalterlogik von `report_show_llm_model` in `src/notification.py` zurückgeführt werden.
- `REPORT_SHOW_LLM_MODEL` und `report_renderer_enabled` sind beides Anzeige-/Downgrade-Strategieschalter: Das Deaktivieren beeinflusst nur die sichtbare Struktur des Berichts und löst keine Konfigurationsmigration oder ein Zurückfallen der Laufzeitparameter aus; als Rückfall werden `true` wiederhergestellt (bzw. der Eintrag entfernt) oder die Standardkonfiguration wiederhergestellt.

Die Darstellung der verwandten Sektoren erfolgt weiterhin in der Erzeugungsphase des Berichtstexts: Wenn keine Signale für die Gewinner-/Verliererrangliste von Branchen/Konzepten vorliegen, verwendet der Push-Bericht weiterhin die bisherige einzeilige Darstellung, z. B. `Kommunikationskabel und Zubehör / Kommunikationsgeräte / Kommunikation / Jiangsu-Sektor / Technologiestil`, ohne eine zusätzliche Spalte „Typ“ zu zeigen. Nur wenn führende/fallende Signale über `fundamental_context.boards.data` / `sector_rankings` oder `fundamental_context.concept_boards.data` / `concept_rankings` erkannt werden, wird eine Tabelle mit „Sektor / Typ / Sektorperformance / Sektorveränderung in %“ verwendet, wobei die Spalte „Typ“ „Industriesektor“ oder „Konzeptsektor“ kennzeichnet. Diese Logik betrifft nur die Berichtsanzeige; sie ändert nicht provider/model/Base URL, das LiteLLM-Routing oder die Logik zum Speichern, Migrieren oder Bereinigen von Modellen.

## GitHub-Actions-Zuordnung

Der mitgelieferte `.github/workflows/00-daily-analysis.yml` importiert nur explizit feste Variablennamen. P0/P3/P4/P6 haben die Body-Vorlage, Sicherheitseinträge, PushPlus-Topic, Routing, Rauschunterdrückung sowie ntfy- und Gotify-Benachrichtigungsschlüssel in den Standard-Workflow aufgenommen. Die folgende Tabelle wird von `scripts/generate_notification_actions_env_table.py` aus der workflow `env:` und den Benachrichtigungs-Diagnosemetadaten erzeugt, damit handgeschriebene Referenztabellen und die echte Actions-Zuordnung nicht weiter auseinanderdriften.

<!-- notification-actions-env-table:start -->

| Key | Tier | Channel / feature | Actions source | Default |
| --- | --- | --- | --- | --- |
| `WECHAT_WEBHOOK_URL` | minimal | wechat | Secret | - |
| `WECHAT_MSG_TYPE` | advanced | wechat | Variable or Secret | `markdown` |
| `FEISHU_WEBHOOK_URL` | minimal | feishu | Secret | - |
| `FEISHU_WEBHOOK_SECRET` | advanced | feishu | Secret | - |
| `FEISHU_WEBHOOK_KEYWORD` | advanced | feishu | Variable or Secret | - |
| `DINGTALK_WEBHOOK_URL` | minimal | dingtalk | Secret | - |
| `DINGTALK_SECRET` | advanced | dingtalk | Secret | - |
| `TELEGRAM_BOT_TOKEN` | minimal | telegram | Secret | - |
| `TELEGRAM_CHAT_ID` | minimal | telegram | Secret | - |
| `TELEGRAM_MESSAGE_THREAD_ID` | advanced | telegram | Secret | - |
| `EMAIL_SENDER` | minimal | email | Variable or Secret | - |
| `EMAIL_PASSWORD` | minimal | email | Secret | - |
| `EMAIL_RECEIVERS` | advanced | email | Variable or Secret | - |
| `EMAIL_SENDER_NAME` | advanced | email | Variable or Secret | `daily_stock_analysis Aktienanalyse-Assistent` |
| `PUSHOVER_USER_KEY` | minimal | pushover | Secret | - |
| `PUSHOVER_API_TOKEN` | minimal | pushover | Secret | - |
| `NTFY_URL` | minimal | ntfy | Secret | - |
| `NTFY_TOKEN` | advanced | ntfy | Secret | - |
| `GOTIFY_URL` | minimal | gotify | Secret | - |
| `GOTIFY_TOKEN` | minimal | gotify | Secret | - |
| `PUSHPLUS_TOKEN` | minimal | pushplus | Secret | - |
| `PUSHPLUS_TOPIC` | advanced | pushplus | Variable or Secret | - |
| `CUSTOM_WEBHOOK_URLS` | minimal | custom | Secret | - |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | advanced | custom | Secret | - |
| `CUSTOM_WEBHOOK_BODY_TEMPLATE` | advanced | custom | Variable or Secret | - |
| `WEBHOOK_VERIFY_SSL` | advanced | ntfy, gotify, custom, astrbot | Variable or Secret | `true` |
| `DISCORD_WEBHOOK_URL` | minimal | discord | Secret | - |
| `DISCORD_BOT_TOKEN` | minimal | discord | Secret | - |
| `DISCORD_MAIN_CHANNEL_ID` | minimal | discord | Secret | - |
| `FEISHU_APP_ID` | minimal | feishu | Secret | - |
| `FEISHU_APP_SECRET` | minimal | feishu | Secret | - |
| `FEISHU_CHAT_ID` | minimal | feishu | Variable or Secret | - |
| `FEISHU_RECEIVE_ID_TYPE` | advanced | feishu | Variable or Secret | - |
| `FEISHU_DOMAIN` | advanced | feishu | Variable or Secret | - |
| `FEISHU_SEND_AS_FILE` | advanced | feishu | Variable or Secret | - |
| `ASTRBOT_URL` | minimal | astrbot | Secret | - |
| `ASTRBOT_TOKEN` | advanced | astrbot | Secret | - |
| `SERVERCHAN3_SENDKEY` | minimal | serverchan3 | Secret | - |
| `SLACK_WEBHOOK_URL` | minimal | slack | Secret | - |
| `SLACK_BOT_TOKEN` | minimal | slack | Secret | - |
| `SLACK_CHANNEL_ID` | minimal | slack | Secret | - |
| `NOTIFICATION_REPORT_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_ALERT_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | advanced | noise | Variable or Secret | `0` |
| `NOTIFICATION_COOLDOWN_SECONDS` | advanced | noise | Variable or Secret | `0` |
| `NOTIFICATION_QUIET_HOURS` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_TIMEZONE` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_MIN_SEVERITY` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | advanced | noise | Variable or Secret | `false` |

<!-- notification-actions-env-table:end -->

Der Standard-Workflow bildet `MARKDOWN_TO_IMAGE_CHANNELS` und `MERGE_EMAIL_NOTIFICATION` weiterhin nicht ab. Sie sind Schalter für die Sendeform bzw. das Aggregationsverhalten und keine Kanal-Anmeldeinformationen; ein automatisches Einlesen gleichnamiger Secrets/Variablen in Actions würde zusätzliche Verhaltensänderungen einführen.

## Bildbericht-Share-Template

Nach der Konfiguration von `MARKDOWN_TO_IMAGE_CHANNELS` nutzen Einzelaktien-Analyse, Aggregatberichte und Marktrückblick den bestehenden Benachrichtigungs-Routing und verwenden in der Bildumwandlungsphase die 1080 px breite Marken-Share-Vorlage. Für eine einzelne Aktie wird eine Entscheidungskarte nach „Schlussfolgerung — Punkte — Technik — Risiko — Position" generiert, für den Gesamtmarkt eine Rückblick-Karte nach „Signale — Indizes — Breite — Starke/Schwache-Sektoren — Kapitalbeobachtung — Wichtige Nachverfolgung — Strategie — Risiko"; Mehr-Aktien-Berichte behalten das Aggregat-Layout. Am unteren Rand werden die GitHub-Repository-Adresse, ein optionaler Bereich für den Xiaohongshu-Account und der Risikohinweis „Nur zu Forschungs- und Austauschzwecken, keine Anlageberatung" angezeigt.

- Die Xiaohongshu-URL, der Account, die ID und der QR-Code-Pfad werden über `SHARE_IMAGE_XIAOHONGSHU_*` konfiguriert; wenn alle leer sind, wird dieser Bereich nicht angezeigt. Der QR-Code wird beim Umwandeln als HTML eingebettet und hängt nicht von externen Bilddiensten oder dem Laufzeit-Netz ab.
- Die Vorlage zeigt nur die vorhandenen 0–100-Scores, Acht-Zustands-Aktionen und `battle_plan.sniper_points`-Punkte des Berichts; ideale/suboptimale Kaufpunkte, Stop-Loss und Zielwerte verwenden eine eigene hochkontrastreiche Handelskarte; es werden keine zusätzlichen Scores oder Long/Short-Anteile erzeugt.
- Strukturierte Felder, Verhalten bei fehlenden Werten, Einzelaktien-/Gesamtmarkt-Zuordnung und lokale Vorschau-Beispiele siehe [Vorlage für geteilte Bildberichte und Datenbefüllung](share-images.md#vorlage-für-geteilte-bildberichte-und-datenbefüllung).
- `wkhtmltoimage`, `markdown-to-file` und `playwright` verwenden dasselbe Poster-HTML; die bestehenden `MD2IMG_ENGINE`, `MARKDOWN_TO_IMAGE_MAX_CHARS` und das Verhalten des Text-Fallbacks bei Umwandlungsfehlern bleiben unverändert. Im Playwright-Modus müssen zuerst die Web-Abhängigkeiten installiert und `npx playwright install chromium` ausgeführt werden.
- Die Vorlage erzeugt ein langes Bild entsprechend der Länge des Haupttexts und schneidet den Bericht nicht an ein festes Seitenverhältnis an. Wenn der Inhalt `MARKDOWN_TO_IMAGE_MAX_CHARS` überschreitet, wird die Bildumwandlung weiterhin übersprungen.
- GitHub Actions ordnet `MARKDOWN_TO_IMAGE_CHANNELS` standardmäßig weiterhin nicht zu; um es in einem Fork-Workflow zu aktivieren, sollte die Umgebungsvariablen-Zuordnung explizit ergänzt und das gewählte Umwandlungstool installiert werden.

## CLI-Diagnose

```bash
python main.py --check-notify
```

Dieser Befehl liest nur die Konfiguration, sendet keine Benachrichtigungen und schreibt nichts in `.env`. Er wird unmittelbar nach dem Laden der Konfiguration und der Log-Initialisierung ausgeführt und beendet sich danach direkt, ohne in den Web-, Zeitplan-, Markt-Rückblick- oder Standard-Analyseablauf zu gehen.

- Rückgabecode `0`: keine Diagnosen auf Fehlerebene.
- Rückgabecode `1`: es liegen Fehler vor, z. B. 0 konfigurierte statische Benachrichtigungskanäle oder nur die Hälfte eines Schlüsselpaars ist konfiguriert.

## Web-Ein-Klick-Test

Die Kategorie „Benachrichtigungskanäle“ der Web-Einstellungsseite bietet einen Einstieg zum Ein-Kanal-Test. Der Test erstellt mit den aktuellen Entwurfswerten der Seite eine temporäre Konfiguration und sendet eine echte Testbenachrichtigung, speichert aber `.env` nicht und ändert auch nicht die globale Laufzeitkonfiguration.

- Testumfang: 14 statische Benachrichtigungskanäle, ohne `UNKNOWN` und Laufzeit-Kontextkanäle.
- Normale Kanäle: liefern das Einzel-Sendeergebnis, die benötigte Zeit und einen allgemeinen Fehlercode zurück.
- Benutzerdefinierter Webhook: gibt `attempts` in URL-Reihenfolge zurück und zeigt für jede URL Erfolg/Fehler, HTTP-Status, benötigte Zeit und Fehlercode; bei teilweisem Erfolg mehrerer URLs kennzeichnet die oberste `message` die Anzahl Erfolge / Gesamtzahl.
- Die Ergebnisse maskieren `token`, `secret`, `password`, `Bearer`, die vollständige Webhook-Query und vermutete Pfad-Tokens.
- Bei fehlender Konfiguration oder Sendefehler wird `success=false` zurückgegeben; das beeinflusst weder gespeicherte Konfigurationen noch den Standard-Analyseablauf.

## Benutzerdefinierte Webhook-Body-Vorlage

`CUSTOM_WEBHOOK_BODY_TEMPLATE` ist die globale JSON-Body-Vorlage für benutzerdefinierte Webhooks. Nach der Konfiguration greift sie vor der automatischen URL-Erkennung und überschreibt damit die automatischen Payloads von Bark, Slack, Discord, DingTalk usw. Ohne Konfiguration wird weiterhin die bisherige automatische URL-Erkennung verwendet; wenn das Ergebnis nach dem Rendern kein gültiges JSON-Objekt ist, wird ein Fehler protokolliert und auf den Standard-Payload zurückgefallen, ohne den Haupt-Benachrichtigungsablauf zu unterbrechen.

Verfügbare Platzhalter:

- `$content_json`: der JSON-escapte Benachrichtigungstext, als Standard empfohlen.
- `$title_json`: der JSON-escapte Benachrichtigungstitel, als Standard empfohlen.
- `$content` / `$title`: Roh-Strings ohne JSON-Escaping. Enthält der Text doppelte Anführungszeichen, Backslashes oder Zeilenumbrüche, kann das JSON ungültig werden und einen Fallback auslösen.

Bei Docker-Compose-Bereitstellungen schreibt die Web-Einstellungsseite beim Speichern der Vorlage in `.env` die Anwendungsplatzhalter automatisch als `$$content_json`, `$$title_json`, `$$content`, `$$title`, damit Compose sie nicht als leere Host-Umgebungsvariablen expandiert; zur Laufzeit setzt die Anwendung sie wieder auf einzelne `$`-Platzhalter zurück. Wenn du die von Docker verwendete `.env` von Hand bearbeitest, speichere sie ebenfalls in der Form `$$content_json`.

Diese Funktion betrifft nur die Darstellung des Benachrichtigungstexts und nicht die Speicher-, Migrations- oder Bereinigungssemantik von LLM `provider` / `model` / `base URL` / LiteLLM-Routing; falls bei einer strukturierten Suche ein Treffer zur provider/API-Kompatibilitätssemantik auftritt, sollte der Trefferbereich auf die Erläuterung zur Trennung von Berichtsmodell-Darstellung und Benachrichtigungskonfiguration in diesem Dokument zurückgeführt werden und nicht auf die Webhook-Reparaturkette selbst.

Allgemeines Webhook-Beispiel:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"content":$content_json}
```

Wenn Bark über einen Custom-Webhook verwendet wird, setzt du den Bark-Endpoint direkt in `CUSTOM_WEBHOOK_URLS`; es ist keine zusätzliche `BARK_*`-Konfiguration nötig. Ohne globale Vorlage erzeugt das System `title` / `body` / `group` automatisch gemäß `api.day.app`; wenn eine globale Vorlage konfiguriert ist, musst du den Bark-Body selbst angeben:

```env
CUSTOM_WEBHOOK_URLS=https://api.day.app/YOUR_BARK_KEY
```

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"body":$content_json,"group":"stock"}
```

AstrBot ist bereits ein First-Class-Benachrichtigungskanal; bevorzugt werden `ASTRBOT_URL` und das optionale `ASTRBOT_TOKEN` verwendet. Nur wenn ein AstrBot-kompatibler Endpoint in `CUSTOM_WEBHOOK_URLS` aufgenommen werden muss, wird die Custom-Webhook-Vorlage verwendet, z. B.:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$content_json}
```

ntfy ist bereits ein First-Class-Benachrichtigungskanal; bevorzugt werden `NTFY_URL` und das optionale `NTFY_TOKEN` verwendet. `NTFY_URL` bezeichnet den vollständigen Topic-Endpoint, z. B. `https://ntfy.sh/my-topic` oder `https://self-hosted:port/my-topic`; das System parst das letzte Pfadsegment als Topic und sendet einen JSON-Publish an die Server-Wurzel:

```env
NTFY_URL=https://ntfy.sh/my-topic
NTFY_TOKEN=
```

Gotify ist bereits ein First-Class-Benachrichtigungskanal; bevorzugt werden `GOTIFY_URL` und `GOTIFY_TOKEN` verwendet. `GOTIFY_URL` bezeichnet die Basis-URL des Gotify-Servers, kann ein Reverse-Proxy-Pfadpräfix enthalten, aber kein `/message`; beim Senden hängt das System die feste `/message`-API an und übermittelt das Application-Token über den `X-Gotify-Key`-Header. `NTFY_URL` ist der vollständige Topic-Endpoint, während `GOTIFY_URL` die Server-Basis-URL ist — eine bewusste Entscheidung aufgrund der unterschiedlichen API-Designs der beiden Dienste:

```env
GOTIFY_URL=https://gotify.example
GOTIFY_TOKEN=app-token
```

```env
# 反向代理 path prefix 示例；实际请求会发送到 https://example.com/gotify/message
GOTIFY_URL=https://example.com/gotify
GOTIFY_TOKEN=app-token
```

Die NapCat-/OneBot-HTTP-API muss an den tatsächlichen Endpoint und den Zieltyp angepasst werden. Im Folgenden sind nur Beispiele für häufige Body-Formen; `user_id`, `group_id`, URL-Pfade und die Authentifizierungsmethode richten sich stets nach deiner NapCat-Konfiguration:

```env
# 私聊：CUSTOM_WEBHOOK_URLS=http://127.0.0.1:3000/send_private_msg
CUSTOM_WEBHOOK_BODY_TEMPLATE={"user_id":123456,"message":$content_json}
```

```env
# 群聊：CUSTOM_WEBHOOK_URLS=http://127.0.0.1:3000/send_group_msg
CUSTOM_WEBHOOK_BODY_TEMPLATE={"group_id":123456789,"message":$content_json}
```

## Benachrichtigungs-Routing-Strategie

P3 ergänzt drei Arten von Benachrichtigungs-Routingkonfigurationen:

| Routentyp | Konfigurationskey | Aktuelle Erzeuger |
| --- | --- | --- |
| `report` | `NOTIFICATION_REPORT_CHANNELS` | Einzelaktien-Push, aggregierter Tagesbericht, Markt-Rückblick, zusammengeführte Pushs, Erfolgslinks für Feishu-Dokumente |
| `alert` | `NOTIFICATION_ALERT_CHANNELS` | Über EventMonitor ausgelöste Benachrichtigungen |
| `system_error` | `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | Reservefähigkeit; derzeit werden keine automatischen Systemfehler-Erzeuger hinzugefügt |

Der Konfigurationswert ist eine durch Kommas getrennte Kanalaufzählung: `wechat,dingtalk,feishu,telegram,email,pushover,ntfy,gotify,pushplus,serverchan3,custom,discord,slack,astrbot`.

- Leer oder nicht konfiguriert: das alte Verhalten bleibt erhalten, es wird an alle konfigurierten statischen Kanäle gesendet.
- Nicht leer: es wird nur an die Schnittmenge aus Routingliste und konfigurierten Kanälen gesendet; bei leerer Schnittmenge gibt es keinen Fallback auf alle Kanäle.
- `send_to_context()` unterliegt keiner Routing-Beschränkung; der Bot-Sitzungskontext erhält weiterhin die Antwort auf die auslösende Aufgabe.
- Interaktive Befehle (DingTalk-Sitzung, Feishu-Sitzung, Telegram) überspringen statische Benachrichtigungskanäle wie `FEISHU_WEBHOOK_URL`, wenn ein Quellkontext vorhanden ist; Aufgaben von `SCHEDULE`, CLI, API oder ohne Quellkontext werden weiterhin über das `report`-Routing gesendet.
- Die Routenfilterung erfolgt vor der Umwandlung von Markdown in Bilder; `MARKDOWN_TO_IMAGE_CHANNELS` wirkt nur auf die Teilmenge der Kanäle nach dem Routing.
- `MERGE_EMAIL_NOTIFICATION` benötigt keine zusätzliche Konfiguration; solange `email` weiterhin in den Kanälen nach dem `report`-Routing enthalten ist, bleibt das bestehende Verhalten beim Zusammenführen von E-Mails erhalten.
- `--check-notify` meldet unbekannte Kanalwerte als `error` und gültige, aber nicht aktivierte Routing-Ziele als `warning`.

## Fehlerisolierung von Sammelberichten

P5 verstärkt die Fehlergrenzen des Benachrichtigungspfads für Sammelberichte: `_send_notifications()` sendet nach der `report`-Routenfilterung für jeden statischen Benachrichtigungskanal separat. Eine Ausnahme in einem Kanal wird protokolliert und als Fehler dieses Kanals gewertet, überspringt aber weder nachfolgende Kanäle noch unterbricht sie den Haupt-Analyseablauf.

- E-Mails werden je Empfängergruppe isoliert; schlägt eine Empfängergruppe fehl, senden nachfolgende Gruppen weiter.
- Wenn ein statischer Kanal erfolgreich sendet, wird die P4-Rauschunterdrückungs-Reservierung in den offiziellen Datensatz geschrieben; wenn alle statischen Kanäle fehlschlagen oder Ausnahmen werfen, wird die Reservierung freigegeben.
- `send_to_context()` bleibt unabhängig von den statischen Kanalrouten und den Rauschunterdrückungsaufzeichnungen und dient dazu, dem Bot-Sitzungskontext der auslösenden Aufgabe zu antworten.

Die Zusammenfassung der Entscheidungssignale aus #1390 P6 übernimmt dieselbe Fehlerisolierungsgrenze: Analysebericht-Benachrichtigungen und Alarmbenachrichtigungen hängen nur die wenig sensible `decision_signal_summary` an (Aktion, Zeitraum, Begründung, Beobachtungsbedingungen, Risiko und Quellbericht) und geben weder `signal` `metadata`, `evidence`, Raw-Diagnosen noch webhook/token aus. Wenn das Senden von Alarmbenachrichtigungen fehlschlägt, wird nur der Benachrichtigungsversuch oder der Dispatch-Fallback protokolliert; bereits geschriebene Trigger oder DecisionSignals werden nicht zurückgerollt.

Zu den Benachrichtigungs-Zusammenfassungsfeldern der DecisionSignals, der Grenze sensibler Informationen sowie zu Migration und Rollback siehe [DecisionSignal-Sonderthema](decision-signals.md).

## Rauschunterdrückung von Benachrichtigungen

P4 ergänzt die prozessinterne Rauschunterdrückung; sie betrifft nur statisch konfigurierte Kanäle und nicht den Bot-ausgelösten Sitzungsbeleg von `send_to_context()`. Standardmäßig sind alle Konfigurationen deaktiviert; ohne Einstellung bleibt das alte Verhalten erhalten.

| Konfigurationskey | Standardwert | Beschreibung |
| --- | --- | --- |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | `0` | Sendet denselben stabilen Dedup-Key innerhalb der TTL nur einmal; `0` deaktiviert |
| `NOTIFICATION_COOLDOWN_SECONDS` | `0` | Begrenzt denselben Cooldown-Key innerhalb des Fensters; `0` deaktiviert |
| `NOTIFICATION_QUIET_HOURS` | leer | Ruhezeitraum, Format `HH:MM-HH:MM`, unterstützt Zeiträume über Mitternacht hinaus |
| `NOTIFICATION_TIMEZONE` | leer | Zeitzone für den Ruhezeitraum, z. B. `Asia/Shanghai`; leer verwendet die lokale Zeitzone der Python-Laufzeit (normalerweise durch die Prozessvariable `TZ` oder die Systemzeitzone bestimmt) |
| `NOTIFICATION_MIN_SEVERITY` | leer | `info`, `warning`, `error`, `critical`; leer filtert nicht |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | `false` | Reservekonfiguration; es werden derzeit keine täglichen Zusammenfassungen gesendet oder Zusammenfassungsinhalte persistiert |

Standardwerte der Schweregrade:

- `report`: `info`
- `alert`: `warning`
- `system_error`: `error`
- Unbekanntes oder nicht gesetztes Routing: `info`

Implementierungsgrenzen:

- Der Dedup-/Cooldown-Zustand ist ein Dict innerhalb des aktuellen Python-Prozesses und gilt für den `main.py`-Einzelprozess und den `--serve`-Einzelworker.
- Bei `uvicorn --workers N`, mehreren Containern oder mehreren Maschinen wird der Zustand nicht geteilt; die Rauschunterdrückung greift dann nur näherungsweise pro Worker.
- Der Einzelaktien- und Sammelberichtspfad der Pipeline verwendet stabile Keys, damit sich ändernde Erzeugungszeiten im Bericht die Deduplizierung nicht unterlaufen; andere `report`-Benachrichtigungen ohne expliziten `dedup_key` werden über einen Inhalts-Hash dedupliziert.
- Aufrufe ohne expliziten `cooldown_key` teilen sich einen Standard-Cooldown-Slot nach Routing und Schweregrad, z. B. teilen sich normale Benachrichtigungen mit `report`/`info` denselben Slot.
- Parallele Sendungen mit demselben Key im selben Prozess belegen zuerst einen kurzlebigen In-Flight-Slot, um plötzliche Doppelsendungen zu vermeiden; schlagen alle statischen Kanäle fehl, wird der Slot freigegeben, ohne in den offiziellen Dedup-/Cooldown-Zustand zu schreiben.
- Bei einer Ausnahme in der Rauschunterdrückungsprüfung gilt fail-open: Es wird protokolliert und die statischen Kanäle werden weiterhin gesendet.
- Wenn `NOTIFICATION_TIMEZONE` leer ist, wird die über `datetime.now().astimezone()` ermittelte lokale Laufzeitzone verwendet; für Actions-/Docker-Szenarien wird empfohlen, `NOTIFICATION_TIMEZONE` explizit zu konfigurieren, um Zeitzonen-Mehrdeutigkeiten zu vermeiden.

## Bewertung von WebPush / Apprise

P6-D macht nur eine Designbewertung und fügt weder Abhängigkeiten noch `.env`-Konfiguration noch Laufzeit-Benachrichtigungspfade hinzu. Fazit: Beide eignen sich nicht dafür, in dieser Runde direkt in den Kanal-Implementierungs-PR gemischt zu werden.

Soll WebPush später umgesetzt werden, müssen zuerst der Abonnement-Lebenszyklus und die Sicherheitsgrenzen separat entworfen werden:

- Die Web-Frontend muss einen Service Worker registrieren; Service Worker / `PushManager.subscribe()` erfordern einen sicheren Kontext, in der Produktion ist normalerweise HTTPS nötig, für die lokale Entwicklung kann `localhost` verwendet werden.
- VAPID-öffentlicher/-privater Schlüssel sind nötig; beim Abonnieren wird der `public key` ausgeliefert, beim Senden muss der Server den `private key` besitzen und eine sichere Schlüsselrotation gewährleisten.
- Eine Browser-Berechtigungsinteraktion ist nötig; das Abonnieren muss durch eine Nutzergeste ausgelöst werden und darf nicht still im Hintergrund erfolgen.
- `PushSubscription` enthält `endpoint` und einen Verschlüsselungsschlüssel; der `endpoint` ist eine Capability-URL, sollte wie ein `secret` behandelt und maskiert angezeigt werden.
- Abonnements müssen persistiert sowie Ungültigwerden und Geräteabmeldung behandelt werden; das aktuelle `.env`-/Einzelprozess-Konfigurationsmodell eignet sich nicht dafür, mehrere Nutzer-/Geräteabonnements direkt hineinzupacken.
- Die APIs zum Anlegen, Löschen und Aktualisieren von Abonnements benötigen Authentifizierung und CSRF-Schutz und dürfen sich nicht nur auf das Verstecken des Einstiegs im Frontend verlassen.

Soll Apprise später eingeführt werden, sollte es zuerst als optionale Abhängigkeit bewertet werden, nicht als Standardabhängigkeit:

- Apprise ist eine universelle Benachrichtigungsbibliothek mit breiter Abdeckung, überschneidet sich aber mit den bereits vorhandenen First-Class-Kanälen wie WeChat, Telegram, Discord, Slack, ntfy, Gotify, Pushover usw.
- Abhängigkeitsgröße, Installationsfehlerpfade, Aufblähen von Docker-Images, der GitHub-Actions-Abhängigkeitscache und die Strategie für optionale Extras müssen bewertet werden.
- Die `secret`-Übergabe darf die vollständige Apprise-URL nicht direkt offenlegen; einheitliches Maskieren, Abdecken der Web-Testziele und Filterung der Fehlerprotokolle sind nötig.
- Sendefehler sollten innerhalb des Apprise-Kanals isoliert bleiben und dürfen die Fehlerisolierungssemantik der bestehenden Kanäle nicht beeinträchtigen.
- Wenn Apprise übernommen wird, wird empfohlen, zuerst einen separaten experimentellen Kanal oder einen CLI-only-Spike hinzuzufügen, bevor entschieden wird, ob es in die Web-Einstellungsseite und die Actions-env aufgenommen wird.

## Lokale Konfiguration

Für den lokalen Betrieb wird bevorzugt die `.env` im Projektstammverzeichnis verwendet. Kopiere `.env.example` und fülle mindestens einen minimal key aus, um den entsprechenden statischen Benachrichtigungskanal zu aktivieren; advanced keys ändern nur Authentifizierung, Sicherheit, Format, Routing oder Rauschunterdrückung und aktivieren keinen Kanal für sich.

```bash
python main.py --check-notify
```

`--check-notify` ist eine reine Lese-Diagnose: keine Benachrichtigungen senden, keine `.env` schreiben, kein Eintritt in den Analyseablauf. Nach der Konfiguration der WebUI kannst du über den Ein-Kanal-Test auf der Systemeinstellungsseite auch echte Testnachrichten senden; dieser Test verwendet nur die temporäre Entwurfskonfiguration der Seite und speichert keine `.env`.

## Docker

In Docker-Szenarien können Benachrichtigungs-Umgebungsvariablen über `--env-file .env` / Compose `env_file` injiziert werden. Binde die Host-`.env` nicht als Einzeldatei-Bind-Mount über `/app/.env` im Container, sonst können beim Speichern der Konfiguration über die Web-Einstellungsseite atomare Ersetzungen oder Berechtigungsprobleme durch Docker-Mount-Point-Beschränkungen auftreten. Die neue Web-Einstellungsseite zeigt beim Fehlen bestimmter Schlüssel in der aktiven `.env` die beim Start injizierten gleichnamigen Umgebungsvariablen als Fallback an; wenn nach einem Container-Neubau die von der WebUI gespeicherten Benachrichtigungskonfigurationen erhalten bleiben sollen, setze `ENV_FILE` auf eine beschreibbare Daten-Volume-Datei wie `/app/data/runtime.env` und aktualisiere oder entferne gleichzeitig die gleichnamigen alten Werte in der Startumgebung, damit sie nach einem Neustart nicht überschrieben werden.

Für den Rauschunterdrückungs-Ruhezeitraum wird empfohlen, `NOTIFICATION_TIMEZONE` explizit zu konfigurieren, damit die Standardzeitzone des Containers nicht von der Erwartung abweicht. Für selbstsignierte Intranet-Webhooks kann vorübergehend `WEBHOOK_VERIFY_SSL=false` verwendet werden, aber die Zertifikatsprüfung sollte in öffentlichen Verbindungen nicht deaktiviert werden.

## GitHub Actions

Die Standard-`00-daily-analysis.yml` liest nur die in der Tabelle explizit zugeordneten Secrets/Variablen. Nach dem Hinzufügen eines Repository-Secrets oder einer Variable gelangt nur der Wert in den Laufprozess, wenn der Variablenname bereits in der workflow `env:` erscheint; willkürlich nummerierte Variablen wie `STOCK_GROUP_N` / `EMAIL_GROUP_N` werden nicht automatisch importiert.

Secrets eignen sich für sensible Einträge wie `token`, `password`, webhook URL; Variables eignen sich für nicht-sensible Verhaltenskonfigurationen wie `WECHAT_MSG_TYPE`, `EMAIL_SENDER_NAME`, Routing, Rauschunterdrückungsfenster und Zeitzone. `MARKDOWN_TO_IMAGE_CHANNELS` und `MERGE_EMAIL_NOTIFICATION` werden standardmäßig nicht zugeordnet; wenn du sie in deinem eigenen Fork verwenden möchtest, ändere den Workflow explizit und ergänze entsprechende Tests.

## Desktop

Der Desktop übernimmt die Benachrichtigungskonfiguration und den Ein-Kanal-Test-Einstieg der Web-Einstellungsseite. Der Benachrichtigungstest sendet eine echte Testnachricht, verwendet aber nur die Entwurfswerte der aktuellen Seite und speichert nicht automatisch; für die Persistenz muss weiterhin „Konfiguration speichern“ geklickt werden.

Der Desktop kann die `.env` über Export/Import der Konfiguration wiederherstellen. Beim Zurücksetzen eines Benachrichtigungskanals reicht es, den minimal key des Kanals zu leeren und zu speichern; verbleibende advanced keys aktivieren keinen Kanal für sich, sollten aber zur Reduzierung des Fehlersuchen-Aufwands gleichzeitig bereinigt werden.

## Rollback-Methoden

- Lokal / Docker: die alte `.env` wiederherstellen oder den minimal key des entsprechenden Kanals löschen und den Prozess neu starten.
- GitHub Actions: das entsprechende Secret/die Variable leeren oder löschen; nicht zugeordnete keys gelangen nicht in den Laufprozess des Workflows.
- Desktop: die alte `.env` über ein Konfigurationsbackup importieren oder die Konfiguration des entsprechenden Kanals auf der Einstellungsseite leeren und speichern.
- Versions-Rollback: die in P6/P7 neu hinzugefügten `NTFY_*`, `GOTIFY_*`, Routing- und Rauschunterdrückungs-Keys werden in älteren Versionen ignoriert; um Irreführung zu vermeiden, sollten sie gleichzeitig aus `.env` oder der Actions-Konfiguration entfernt werden.
