# Echtzeit-Alarmzentrum

Dieses Dokument beschreibt die Laufzeit-Baseline, den Datenvertrag, die phasenweise umgesetzten Umfänge und die Kompatibilitätsgrenzen des Alarmzentrums aus Issue #1202.

## Aktuelle Baseline

Die aktuellen Laufzeit-Alarme werden einheitlich durch den Hintergrund-worker in `src/services/alert_worker.py` geplant; die Regelbewertung darunter nutzt das EventMonitor-Regelmodell aus `src/services/alert_service.py` und `src/agent/events.py` wieder.

- Konfigurationseinstieg: `AGENT_EVENT_MONITOR_ENABLED`, `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, `AGENT_EVENT_ALERT_RULES_JSON`.
- Laufzeiteinstieg: `main.py` registriert in der schedule-Mode den Hintergrund-Task `agent_event_monitor`; der Hintergrund-worker liest pro Runde die persistierten active rules und bleibt kompatibel mit dem legacy-`AGENT_EVENT_ALERT_RULES_JSON`.
- Benachrichtigungszustellung: Nach Auslösung wird `NotificationService.send(..., route_type="alert")` wiederverwendet und weiterhin die alert-Routingskonfiguration des Benachrichtigungs-Gateways eingehalten.
- Web/System-Konfigurationsvalidierung: `src/services/system_config_service.py` validiert `AGENT_EVENT_ALERT_RULES_JSON` hinsichtlich JSON und Regelsemantik.

Das aktuelle runtime unterstützt drei Regeltypen:

| `alert_type` | Richtungsfeld | Schwellenfeld | Aktuelle Semantik |
| --- | --- | --- | --- |
| `price_cross` | `direction`: `above` / `below` | `price` | Echtzeitpreis durchbricht einen festen Preis nach oben oder unten |
| `price_change_percent` | `direction`: `up` / `down` | `change_pct` | Echtzeit-Kursänderung erreicht einen bestimmten Prozentsatz |
| `volume_spike` | - | `multiplier` | Das neueste Volumen übersteigt das angegebene Vielfache des durchschnittlichen Volumens der letzten 20 Tage |

Typen wie `sentiment_shift`, `risk_flag`, `custom` dienen nur als Platzhalter für zukünftige Erweiterungen; das aktuelle runtime akzeptiert diese Typen nicht als ausführbare Regeln.

## Legacy-Konfigurationskompatibilität

`AGENT_EVENT_ALERT_RULES_JSON` bleibt als Quelle für legacy-Laufzeitregeln erhalten; bestehende `.env`- / Web-Konfigurationen des Benutzers werden nicht automatisch migriert, gelöscht, überschrieben oder umgeschrieben.

- Eine leere Zeichenkette oder ein leeres Array bedeutet: keine legacy-Regeln konfiguriert; die schedule-Mode registriert den Hintergrund-worker trotzdem, damit später über die API erstellte persistierte active rules ohne Neustart bewertet werden können.
- Beim Speichern der Web/System-Konfiguration wird eine strenge Validierung durchgeführt; ungültiges JSON, fehlende Felder, ungültige Richtung, ungültige Schwelle oder unsupported rule type müssen einen Konfigurationsfehler zurückgeben.
- Beim Laden zur Laufzeit darf eine einzelne ungültige Regel übersprungen werden; die übrigen gültigen Regeln arbeiten weiter, damit eine einzelne Konfiguration nicht den gesamten schedule-Prozess zerstört.
- Der aktuelle worker verwendet einen in-process-fingerprint, um wiederholte Pushs bei dauerhaft erfüllten Bedingungen zu vermeiden; dies ist kein Kühlungsmodell des Alarmzentrums und bietet auch keinen cross-prozessualen oder nach dem Neustart erhaltenen Kühlungszustand.

## Datenvertrag

Die folgenden Verträge dienen der Ausrichtung der nachgelagerten P1+-API-, worker-, Web- und Speicherimplementierung. P0 definiert nur Felder und Semantikgrenzen; das bedeutet nicht, dass diese persistierten Entitäten derzeit bereits existieren.

### `alert_rule`

Eine verwaltbare Alarmregel.

| Feld | Beschreibung |
| --- | --- |
| `id` | Regel-ID; legacy-JSON-Regeln haben in P0 keine persistierte ID |
| `name` | Benutzerlesbarer Name; kann bei Nichtangabe aus Regeltyp und Ziel erzeugt werden |
| `target_scope` | Zielumfang, z. B. single symbol, watchlist, portfolio, market |
| `target` | Zielwert oder Zielreferenz, z. B. Aktiencode, watchlist-ID, portfolio-ID |
| `alert_type` | Regeltyp; P1 erlaubt zunächst nur `price_cross`, `price_change_percent`, `volume_spike` |
| `parameters` | Regelparameter, z. B. `direction`, `price`, `change_pct`, `multiplier` |
| `severity` | Alarmstufe, z. B. info, warning, critical |
| `enabled` | Ob aktiviert |
| `cooldown_policy` | Kühlungsrichtlinie; P0 definiert nur das Feld, P4 implementiert die Ausführungssemantik |
| `notification_policy` | Benachrichtigungsrichtlinie; Standardmäßig wird die alert-Route von `NotificationService` wiederverwendet |
| `source` | Erstellungsquelle, z. B. legacy_env, web, api, import |
| `created_at` / `updated_at` | Erstellungs- und Aktualisierungszeit |

### `alert_trigger`

Eine reale oder protokollierbare Regelauslösung.

| Feld | Beschreibung |
| --- | --- |
| `id` | Auslösungsdatensatz-ID |
| `rule_id` | Zugehörige Regel-ID; legacy-env-Regeln können einen temporären Verweis protokollieren |
| `target` | Tatsächliches Auslöseziel |
| `observed_value` | Beobachtungswert, z. B. aktueller Preis, Kursänderungsprozentsatz, Volumenvielfaches |
| `threshold` | Auslöseschwelle |
| `reason` | Lesbarer Auslösegrund |
| `data_source` | Datenquelle oder provider |
| `data_timestamp` | Datenzeit; bei fehlender Zeit darf nicht die aktuelle Zeit vorgetäuscht werden |
| `triggered_at` | Auslösezeit |
| `status` | Auslösestatus, z. B. triggered, skipped, degraded, failed |
| `diagnostics` | Redigierte Diagnoseinformationen |

### `alert_notification`

Ein Benachrichtigungsversuch zu einer Auslösung.

| Feld | Beschreibung |
| --- | --- |
| `id` | Benachrichtigungsversuchs-ID |
| `trigger_id` | Zugehöriger Auslösungsdatensatz-ID |
| `channel` | Benachrichtigungskanal |
| `attempt` | Wie vielter Versuch |
| `success` | Ob erfolgreich |
| `error_code` | Strukturierter Fehlercode |
| `retryable` | Ob ein Retry empfohlen wird |
| `latency_ms` | Benötigte Zeit |
| `diagnostics` | Redigierte Sende-Diagnose; darf kein token, keine vollständige webhook-URL, kein E-Mail-Passwort und kein bot secret enthalten |
| `created_at` | Versuchszeit |

### `alert_cooldown`

Kühlungszustand auf Regel- oder Zieldimension.

| Feld | Beschreibung |
| --- | --- |
| `rule_id` | Zugehörige Regel-ID |
| `target` | Kühlungsziel |
| `severity` | Optionale Stufen-Dimension |
| `last_triggered_at` | Letzte Auslösezeit |
| `cooldown_until` | Kühlungsendezeitpunkt |
| `reason` | Kühlungsgrund |
| `state` | Aktueller Zustand, z. B. active, expired |
| `updated_at` | Aktualisierungszeit |

## Bewertung der Speicherlösung

Das aktuelle Repository hat bereits eine SQLite-Speicherschicht und eine repository/service-Schichtung:

- `src/storage.py` verwaltet die SQLite-Verbindung, SQLAlchemy-ORM-Modelle und den `DatabaseManager`.
- `src/repositories/` enthält die Datenzugriffsschicht, z. B. `PortfolioRepository`.
- `src/services/` enthält die Geschäftsserviceschicht, z. B. `PortfolioService`, `PortfolioRiskService`.
- Der Standard-Datenbankpfad folgt der bestehenden Konfiguration und liegt üblicherweise unter `data/stock_analysis.db`.

Bei der Implementierung der Alarm-Persistenz in P1/P2 wird empfohlen, die obigen Muster bevorzugt wiederzuverwenden: alert-ORM-Modelle in der Speicherschicht definieren, CRUD und Abfragen in der repository-Schicht kapseln und in der service-Schicht Regelvalidierung, Bewertungsstatus, Benachrichtigungsergebnisse und Kühlungssemantik verarbeiten. P0 erstellt keine neuen Tabellen und ändert die bestehende Datenbank nicht.

Wenn ein späterer PR eine Schema-Änderung benötigt, müssen zugleich geliefert werden:

- Idempotente Initialisierung: Wiederholte Starts oder wiederholte Initialisierungen dürfen bestehende Daten nicht zerstören.
- Rückwärtskompatibilität: Ohne konfiguriertes Alarmzentrum bleiben Tagesanalyse, Fragen zur Aktie, Benachrichtigungen, Marktübersicht und Positionsfunktionen unbeeinflusst.
- Rollback-Erläuterung: Der minimale Rollback-Weg umfasst mindestens den Revert des PR; wurden neue Tabellen oder Indexe erstellt, muss erläutert werden, ob die Daten erhalten bleiben und wie manuell bereinigt wird.
- Datenmigrationsgrenze: `AGENT_EVENT_ALERT_RULES_JSON` darf nicht automatisch migriert, gelöscht oder überschrieben werden, es sei denn, der Benutzer führt explizit eine Importaktion aus.

## P1 Alert API MVP

P1 fügt die Backend-Alert-API und das Schema hinzu, fixiert den minimalen API-Vertrag des Alarmzentrums und bindet weder eine Web-Seite noch den Hintergrund-worker an.

- Neue API-Datei: `api/v1/endpoints/alerts.py`.
- Neue Schema-Datei: `api/v1/schemas/alerts.py`.
- API-Umfang:
  - `GET /api/v1/alerts/rules`
  - `POST /api/v1/alerts/rules`
  - `GET /api/v1/alerts/rules/{rule_id}`
  - `PATCH /api/v1/alerts/rules/{rule_id}`
  - `DELETE /api/v1/alerts/rules/{rule_id}`
  - `POST /api/v1/alerts/rules/{rule_id}/enable`
  - `POST /api/v1/alerts/rules/{rule_id}/disable`
  - `POST /api/v1/alerts/rules/{rule_id}/test`
  - `GET /api/v1/alerts/triggers`
  - `GET /api/v1/alerts/notifications`
- Die Erstversion der Regeln unterstützt weiterhin nur `price_cross`, `price_change_percent`, `volume_spike`; zukünftige Typen wie `sentiment_shift`, `risk_flag`, `custom` geben einen strukturierten unsupported-Fehler zurück.
- Die `test`-Schnittstelle führt nur eine einmalige dry-run-Bewertung aus, sendet keine Benachrichtigung und schreibt keine echten Auslöse- oder Benachrichtigungsversuchsdatensätze.
- `cooldown_policy` / `notification_policy` sind in P1 nur reservierte Felder: Die API kann diese opaque-Konfigurationen speichern und zurückgeben, führt aber keine Kühlungs- oder benutzerdefinierte Benachrichtigungssemantik aus.
- API-Antworten müssen redigiert werden; token, vollständige webhook-URL, E-Mail-Passwort, cookie und bot secret werden nicht zurückgespiegelt.
- `AGENT_EVENT_ALERT_RULES_JSON` bleibt als legacy-Konfigurationseinstieg erhalten; P1 migriert, löscht, überschreibt oder schreibt die legacy-Konfiguration nicht automatisch um.

P1 macht nicht:

- Fügt keine Web-Alarmzentrum-Seite, keine Route und keinen Seitenleisten-Einstieg hinzu.
- Lässt den schedule-worker keine persistierten active rules laden und implementiert auch keine Zusammenführung/Dedupe persistierter Regeln mit legacy-JSON.
- Implementiert kein echtes Schreiben von `alert_trigger` / `alert_notification`; P1 bietet nur Abfrage-Schnittstellen und Tabellenstrukturen.
- Implementiert keine `alert_cooldown`-Ausführungssemantik.
- Implementiert keine MACD-, KDJ-, CCI-, RSI-, Positionsrisiko- oder Market-Light-Alarmregeln.

## P2 Alarmbewertungs-Worker

P2 stellt das schedule-runtime von einem einmalig beim Start erzeugten legacy-`EventMonitor` auf die Bewertung persistierter active rules und legacy-JSON-Regeln durch den Hintergrund-worker pro Runde um.

- `AGENT_EVENT_MONITOR_ENABLED` bleibt der Hauptschalter; der Hintergrund-Taskname bleibt `agent_event_monitor`.
- Der worker liest pro Runde die `alert_rules` mit `enabled=true` aus der DB und parst `AGENT_EVENT_ALERT_RULES_JSON` erneut; neue API-Regeln erfordern keinen Neustart des schedule-Prozesses.
- DB-Regeln und legacy-Regeln werden nach `target_scope + target + alert_type + canonical(parameters)` dedupliziert; bei Konflikten haben DB-Regeln Vorrang; die legacy-Konfiguration wird nicht automatisch migriert, gelöscht oder umgeschrieben.
- Jede Regel wird unabhängig bewertet; ein Einzelausfall schreibt nur den Bewertungsstatus `failed` und beeinflusst weder andere Regeln derselben Runde noch den Hauptanalyseablauf.
- `alert_triggers` werden in P2 zum Protokollieren einer minimalen Bewertungshistorie verwendet: `triggered`, `skipped`, `degraded`, `failed`; normales `not_triggered` wird nicht protokolliert, um ein Auffüllen der Tabelle durch Polling zu vermeiden.
- Fehlende Echtzeitkurse, fehlende Felder oder nicht bewertbare Szenarien werden als `skipped` protokolliert; nicht verfügbare oder strukturell unvollständige Tagesdaten werden als `degraded` protokolliert; Diagnoseinformationen werden redigiert.
- Nach Auslösung wird weiterhin `NotificationService.send(..., route_type="alert")` aufgerufen; der in-process-fingerprint vermeidet nur wiederholte Pushs bei dauerhaft erfüllten Bedingungen und führt keine `cooldown_policy` aus.

P2 macht nicht:

- Fügt keine Web-Alarmzentrum-Seite, keine Route und keinen Seitenleisten-Einstieg hinzu.
- Schreibt keine `alert_notifications` und protokolliert keine per-channel-Benachrichtigungsversuche.
- Implementiert keine Ausführungssemantik von `alert_cooldown`, `cooldown_policy` oder `notification_policy`.
- Implementiert keine MACD-, KDJ-, CCI-, RSI-, Positionsrisiko- oder Market-Light-Alarmregeln.

## P3 Web-Alarmzentrum MVP

P3 fügt in der WebUI den Einstieg `/alerts` zum Alarmzentrum hinzu, damit der Benutzer die aktuellen drei Laufzeitregeln verwalten kann, ohne legacy-JSON direkt bearbeiten zu müssen.

- In der Seitenleiste wird der Einstieg „Alarme" hinzugefügt; die Seite unterstützt Regel-Lists, Pagination, Aktivierungsfilter und Regeltypen-Filter.
- Das Formular zur Regel-Erstellung unterstützt nur den Zielumfang `single_symbol` und die drei aktuell ausführbaren Regeltypen:
  - `price_cross`: `direction` ist `above` / `below`, und `price` wird ausgefüllt.
  - `price_change_percent`: `direction` ist `up` / `down`, und `change_pct` wird ausgefüllt.
  - `volume_spike`: `multiplier` wird ausgefüllt.
- Regelaktionen unterstützen Aktivieren, Deaktivieren, Löschen und einen einmaligen dry-run-Test.
- Der dry-run-Test zeigt nur die deklarierten Felder von `AlertRuleTestResponse`: Regel-ID, Status, ob ausgelöst, Beobachtungswert und Nachricht; erweiterte Diagnosefelder wie `threshold`, `data_source`, `data_timestamp` werden erst angezeigt, wenn das Backend-Schema sie explizit freigibt.
- Die Auslösungshistorie zeigt die vom P2-worker geschriebenen `triggered`, `skipped`, `degraded`, `failed`-Datensätze; normales `not_triggered` wird weiterhin nicht in die Historie geschrieben.
- Der Bereich der Benachrichtigungsversuche fragt nur die bestehende `GET /api/v1/alerts/notifications` ab; da das P2-runtime keine per-channel-Benachrichtigungsversuche schreibt, zeigt der Bereich aktuell üblicherweise den Leerzustand „Keine Benachrichtigungsversuche" und leitet den Auslösestatus nicht als Benachrichtigungszustellungsergebnis ab.
- Die Web-Seite setzt keinen Bearbeitungseinstieg für `AGENT_EVENT_ALERT_RULES_JSON` aus und migriert, löscht oder schreibt die legacy-Konfiguration nicht automatisch um.

P3 macht nicht:

- Fügt kein Backend-API-, schema-, storage- oder worker-Verhalten hinzu bzw. ändert es.
- Implementiert keine Regelbearbeitung, keine erweiterte Ziel-/Quellenfilterung, keine watchlist/portfolio-Ziele, keine technischen Indikatorregeln und keine Market-Light-Kopplung.
- Führt `cooldown_policy` / `notification_policy` nicht aus und schreibt keine `alert_notifications`.

## P4 Benachrichtigungsergebnisse und persistierte Kühlung

P4 verleiht echten Alarmauslösungen fehlerdiagnostizierbare Benachrichtigungsergebnisse und verleiht über die Alert-API erstellten persistierten Regeln einen über Neustarts erhaltenen Geschäftskühlungszustand.

- Die `triggered`-Historie DB-persistierter Regeln wird nach `rule_id + target + data_source + data_timestamp` für denselben Datenpunkt dedupliziert: Dasselbe Auslöseereignis behält nur den frühesten `alert_triggers`-Datensatz; wiederholte Polling-Treffer verwenden den bestehenden Auslöse-Datensatz wieder; bei fehlendem `data_timestamp` wird nicht dedupliziert, um Datenpunkte ohne nachweisbare Same-Source nicht fälschlich zusammenzuführen. Auch wenn spätere Kühlung oder Benachrichtigungs-Rauschunterdrückung sie unterdrückt, werden über `alert_notifications` die zugehörigen Benachrichtigungsversuche oder synthetischen Unterdrückungszustände protokolliert.
- `alert_notifications` protokollieren echte per-channel-Benachrichtigungsversuche, einschließlich `channel`, `success`, `error_code`, `retryable`, `latency_ms` und redigierter `diagnostics`.
- Nicht-Kanal-Sendezustände werden über synthetische Kanäle protokolliert:
  - `__cooldown__`: Geschäftskühlung des Alarms unterdrückt, `error_code="cooldown_active"`.
  - `__cooldown_read_failed__`: Nach fehlgeschlagenem Lesen des persistierten Kühlungszustands wird durch einen temporären Fallback im worker-Prozess unterdrückt, `error_code="cooldown_read_failed"`.
  - `__noise_suppressed__`: Rauschunterdrückung der Benachrichtigungsinfrastruktur, `error_code="noise_suppressed"`.
  - `__no_channel__`: Die alert-Route trifft keinen verfügbaren Benachrichtigungskanal.
  - `__dispatch__`: Fallback oder Ausnahme auf Benachrichtigungs-Dispositionsebene.
- Kühlungsschichtung:
  - Der normale Pfad DB-persistierter Regeln verwendet `alert_cooldowns` als Geschäftskühlung des Alarms; der in-process-fingerprint des workers entscheidet nicht mehr darüber; nur wenn das Lesen des persistierten Kühlungszustands fehlschlägt, wird der in-process-fingerprint vorübergehend verwendet, um wiederholte Pushs derselben Regel pro Runde während einer DB-Ausnahme zu verhindern.
  - legacy-`AGENT_EVENT_ALERT_RULES_JSON`-Regeln verwenden weiterhin den in-process-fingerprint des workers und schreiben kein `alert_cooldowns`.
  - `notification_noise.py` bleibt der globale Sicherheitsnetz auf der Ebene der Benachrichtigungsinfrastruktur; es ist kein Geschäft-cooldown des Alarms, und wenn es unterdrückt, werden `alert_cooldowns` weder geschrieben noch verlängert.
- `cooldown_policy.cooldown_seconds` DB-basierter Regeln wird auf eine nicht-negative Ganzzahl normalisiert; bei fehlendem Wert gilt standardmäßig 24 Stunden Geschäftskühlung, `0` bedeutet, dass die DB-Geschäftskühlung deaktiviert ist.
- `GET /api/v1/alerts/rules` gibt die schreibgeschützte Zusammenfassung `last_triggered_at` / `cooldown_until` / `cooldown_active` zurück; `cooldown_active` wird vom Backend nach derselben Kühlzeit-Semantik berechnet; die Web-Seite analysiert naive-ISO-Zeichenketten nicht lokal im Browser, um den Zustand abzuleiten.
- Das Web-Alarmzentrum zeigt Kühlungszustand und Benachrichtigungsergebnisse nur lesend an und bietet kein Bearbeitungsformular für die cooldown-policy.

P4 macht nicht:

- Fügt keine technischen Indikator-, Positions-, Watchlist-, portfolio-, watchlist- oder Market-Light-Alarmregeln hinzu.
- Implementiert keine target-level-übergreifende zusammengeführte Kühlung von Regeln; die Zusammenführung auf Ziel-Ebene bleibt der Positions-/Marktkopplungsphase vorbehalten.
- Schreibt das Benachrichtigungskanal-Gateway nicht neu; `NotificationService.send()` behält die boolesche Rückgabe-Kompatibilität bei, strukturierte Ergebnisse werden über neue kompatible Schnittstellen bereitgestellt.
- Migriert, löscht oder schreibt legacy-`AGENT_EVENT_ALERT_RULES_JSON` nicht automatisch um.

## P5 Technische Indikatorregeln

P5 fügt in die bestehende Bewertungskette der Alert-API, des Web-Alarmzentrums und von `src/services/alert_worker.py` Tagesbalken-Indikatorregeln hinzu. Regeln werden weiterhin in `alert_rules` geschrieben; Auslösung, Degradierung, Fehler, Benachrichtigungsergebnisse und persistierte Kühlung nutzen weiterhin die P2-P4-Semantik von `alert_triggers`, `alert_notifications` und `alert_cooldowns`.

Von P5 unterstützte `alert_type` und `parameters`:

| alert_type | parameters | Auslösesemantik |
| --- | --- | --- |
| `ma_price_cross` | `direction=above|below`, `window` Standard `20`, Ganzzahl `[2,250]` | close kreuzt die MA(window)-Kante nach oben/unten |
| `rsi_threshold` | `direction=above|below`, `period` Standard `12`, Ganzzahl `[2,250]`, `threshold` Pflicht und `0..100` | RSI kreuzt die Schwelle-Kante nach oben/unten |
| `macd_cross` | `direction=bullish_cross|bearish_cross`, `fast_period=12`, `slow_period=26`, `signal_period=9`, alle `[2,250]` und `fast_period < slow_period` | DIF/DEA golden cross/death cross an der Kante |
| `kdj_cross` | `direction=bullish_cross|bearish_cross`, `period=9`, `k_period=3`, `d_period=3`, alle `[2,250]` | K/D golden cross/death cross an der Kante |
| `cci_threshold` | `direction=above|below`, `period` Standard `14`, Ganzzahl `[2,250]`, `threshold` Pflicht und endliche Zahl | CCI kreuzt die Schwelle-Kante nach oben/unten |

Bewertungsregeln:

- Die Erstversion verwendet einheitlich den Tagesbalken-close, keine Minutenbalken.
- Kantenauslösung vergleicht nur die letzten beiden geschlossenen Tagesbalken; wenn das aktuelle level die Schwelle bereits erfüllt, aber nicht an der Kante liegt, wird weiterhin `not_triggered` zurückgegeben, um zu vermeiden, dass am ersten Erstellungstag historische Zustände als neue Auslösung fehlgemeldet werden.
- Kantenauslösung umfasst den Fall, dass der vorherige Balken genau gleich der Schwelle oder der Nulllinie ist: `above` / `bullish_cross` verwendet `prev <= threshold < current`, `below` / `bearish_cross` verwendet `prev >= threshold > current`.
- partial bar verwendet nur eine Heuristik der Server-Lokalzeit: Ist die aktuelle lokale Zeit vor 16:00, wird die letzte Zeile konservativ verworfen, wenn ihr Datum dem lokalen Heute entspricht oder das Datum nicht bestimmbar ist; es wird weder zwischen A-Aktien-, Hongkong- und US-Marktzeitzonen noch Handelskalendern unterschieden. Die Marktphasen-Baseline von Issue #1386 P0 wird vorerst nicht an technische Indikatorregeln angebunden; die präzise partial-bar-Bestimmung des Alarms bleibt späteren Phasen vorbehalten.
- `src/services/alert_indicators.py` normalisiert OHLCV selbst und berechnet MA, RSI, MACD, KDJ, CCI; es verlässt sich nicht auf vom fetcher vorberechnete MA5/MA10/MA20.
- RSI verwendet Wilder's EMA / SMMA: `avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()`, `avg_loss` analog, kein rolling SMA.
- MACD verwendet `EMA(fast_period) - EMA(slow_period)` für DIF, DEA ist das `EMA(signal_period)` von DIF; golden cross/death cross vergleichen den Kantenübergang von DIF-DEA relativ zu 0.
- KDJ verwendet die Höchst-/Tiefstpreise der letzten `period` Tage für RSV und erhält K/D über EMA mit `alpha=1/k_period`, `alpha=1/d_period`; golden cross/death cross vergleichen den Kantenübergang von K-D relativ zu 0.
- CCI verwendet den typischen Preis `(high + low + close) / 3` und berechnet `(TP - MA(TP)) / (0.015 * mean_deviation)` über den `period`-Tagesmittelwert und die mittlere absolute Abweichung.
- `compute_required_bars(alert_type, params)` definiert die Mindestanzahl gültiger closed bars: MA=`window+1`, RSI=`period+1`, MACD=`slow_period+signal_period+1`, KDJ=`period+k_period+d_period+1`, CCI=`period+1`.
- Die Abruf-Tage verwenden `requested_days = min(max(required_bars * 3, required_bars + 30), 365)`; die API lehnt Kombinationsperioden mit `required_bars > 365` ab, um Regeln mit dauerhaft unzureichender Stichprobe zu vermeiden; Tagesdaten werden in derselben worker-Runde nach `(stock_code, requested_days)` gecacht und am Rundenende freigegeben.
- Fehlende Daten, fehlende Spalten oder weniger als `required_bars` gültige Stichproben schreiben `degraded`; Datenquellenausnahmen folgen der `volume_spike`-Semantik und geben `evaluation_error` / `failed` zurück, ohne Benachrichtigung zu senden.

Kompatibilitätsgrenzen:

- `AGENT_EVENT_ALERT_RULES_JSON` bleibt der legacy-JSON-Pfad und unterstützt nur die drei Regeltypen `price_cross`, `price_change_percent`, `volume_spike`; P5-technische Indikatoren werden nur über Alert-API / Web erstellt.
- `src/agent/events.py`'s legacy-`AlertType` oder `_RUNTIME_SUPPORTED_ALERT_TYPES` werden nicht erweitert.
- Parameterfehler bei P5-Erstellung/-Aktualisierung folgen dem bestehenden Fehlervertrag der Alert-API: HTTP 400 + `validation_error`; unsupported-Typen geben HTTP 400 + `unsupported_alert_type` zurück.
- Das Web-Alarmzentrum erweitert nur das bestehende Erstellungsformular, die Listenanzeige, den Typfilter und den dry-run-Test; kein neuer Regel-Editor; der dry-run-Test schreibt keine Auslösungshistorie, und die API-Antwort verwendet weiterhin den Dreizustand `triggered` / `not_triggered` / `evaluation_error`; der vom worker geschriebene `degraded`-Status wird über die Auslösungshistorie eingesehen.
- Nach dem Rollback des P5-PR bleiben die in der Datenbank erstellten technischen Indikatorregel-Datensätze erhalten; der alte Code überspringt bei der worker-Ladephase unsupported-`alert_type`-Einträge, ohne die Ausführung der drei legacy-Regeltypen zu beeinträchtigen. Für eine Bereinigung muss der Maintainer die zugehörigen `alert_rules`-Datensätze nach Bestätigung manuell löschen.

P5 macht nicht:

- Unterstützt keine MACD-Balken-Vergrößerung/-Verkleinerung.
- Unterstützt keine KDJ-Überkauft/Überverkauft-Bereichsregeln.
- Unterstützt keine MA-MA-Doppelgleitendenschnitt-Kreuzungen.
- Unterstützt keine Minutenbalken, keine präzise Marktkalenderbestimmung und keine präzisen partial bars mehrerer Marktzeitzonen.
- Unterstützt keine legacy-`AGENT_EVENT_ALERT_RULES_JSON`-technischen Indikatorregeln.
- Führt kein DSL, keine Regelengine, keine neuen Datenbanktabellen und keine technische Indikatorregelengine innerhalb der Analyse-Berichtspipeline ein.

## P6 Kopplung von Positionen und Watchlist

P6 fügt in die bestehende Bewertungskette der Alert-API, des Web-Alarmzentrums und von `src/services/alert_worker.py` die drei Zielumfänge `watchlist`, `portfolio_holdings`, `portfolio_account` hinzu. Regeln werden weiterhin in `alert_rules` geschrieben; Auslösung, Degradierung, Fehler, Benachrichtigungsergebnisse und persistierte Kühlung nutzen weiterhin die P2-P4-Semantik von `alert_triggers`, `alert_notifications` und `alert_cooldowns`, ohne neue Tabellen oder Migrationen.

### P6 scope/type-Matrix

| `target_scope` | `target` | Erlaubte `alert_type` | Bewertungsart |
| --- | --- | --- | --- |
| `single_symbol` | Aktiencode | P1-Drei-Typen Preis/Volumen + P5-technische Indikatoren | Einzelregel-Einzelziel |
| `watchlist` | `default` | P1-Drei-Typen Preis/Volumen + P5-technische Indikatoren | `STOCK_LIST` pro Runde aktualisieren und lesen, nach Aktiencode expandieren |
| `portfolio_holdings` | `all` oder active account ID | P1-Drei-Typen Preis/Volumen + P5-technische Indikatoren | symbol aus Nicht-Null-Positionen des Positions-Snapshots expandieren, nach symbol deduplizieren |
| `portfolio_account` | `all` oder active account ID | `portfolio_stop_loss`, `portfolio_concentration`, `portfolio_drawdown`, `portfolio_price_stale` | Kontostufige Risikobewertung, keine Expansion zu Einzelzielen |

Bei der Erstellung/Aktualisierung von Regeln validieren `watchlist` / `portfolio_holdings` das übergeordnete `target` nicht als Aktiencode; `portfolio_account` verbietet Preis-/Volumen-/technische Indikatortypen; `portfolio_holdings` und `portfolio_account` validieren bei `target=<id>`, dass das Konto existiert und active ist; falls nicht, HTTP 400 + `validation_error`. legacy-`AGENT_EVENT_ALERT_RULES_JSON` unterstützt keine watchlist-, portfolio- oder technischen Indikatorerweiterungen und unterstützt weiterhin nur `single_symbol` mit `price_cross`, `price_change_percent`, `volume_spike`.

### Target Identity Contract

P6 trennt darstellbare Ziele von persistierbaren Zielen:

| Szenario | `effective_target` | `display_target` |
| --- | --- | --- |
| `single_symbol` | `<symbol>` | `<symbol>` |
| `watchlist`-expandiertes Unterziel | `<symbol>` | `Watchlist - <symbol>` |
| `portfolio_holdings`-expandiertes Unterziel | `<symbol>` | `Position - <symbol>` |
| `portfolio_account target=all` | `account:all` | `Alle Konten` |
| `portfolio_account target=<id>` | `account:<id>` | `Konto <id>` |

- `alert_triggers.target`, `alert_cooldowns.target` und das P4-Dedupe `rule_id + target + data_source + data_timestamp` verwenden alle `effective_target`.
- `RuntimeAlertRule.key` verwendet für expandierte Unterziele `{parent_key}|{effective_target}`, damit der in-process-Fallback bei fehlgeschlagenem DB-cooldown-Lesen verschiedene Unterziele derselben übergeordneten Regel nicht gegenseitig unterdrückt.
- `display_target` wird nicht in `alert_triggers.target` geschrieben, sondern nur für Benachrichtigungstitel, dry-run-`target_results` und Web-Anzeige verwendet.
- P6 macht keine übergreifende Benachrichtigungszusammenführung desselben Ziels über Regeln; trifft dieselbe Aktie gleichzeitig eine watchlist-Unterregel und eine unabhängige `single_symbol`-Regel, wird pro Regel unabhängig protokolliert und benachrichtigt.

### Dry-run-Aggregation

- `POST /api/v1/alerts/rules/{rule_id}/test` gibt für Batch-Regeln aggregierte Felder zurück: `evaluated_count`, `triggered_count`, `degraded_count`, `skipped_count`, `target_results`.
- Der Soft-Cap der expandierten Ziele ist 100; Ziele über dem Soft-Cap im dry-run werden als aggregiertes Ergebnis `degraded` markiert und protokolliert. Zur worker-Laufzeit werden nur die ersten 100 expandierten Ziele bewertet und eine warning geschrieben; für den overflow selbst wird keine `alert_triggers`-Historie geschrieben.
- Der dry-run verwendet begrenzte parallele Bewertung, Einzelziel-Timeout 10 Sekunden, Gesamtbewertungs-Timeout 30 Sekunden; nicht abgeschlossene Ziele werden als `skipped` markiert.
- Ist ein Ziel triggered, ist das top-level `status=triggered`; ohne Auslösung, aber mit erfolgreicher Bewertung, skipped oder degraded ist das top-level `status=not_triggered`; nur wenn keine Expansion möglich ist oder alles fehlschlägt, wird `evaluation_error` zurückgegeben.
- Leere watchlist / leere holdings: dry-run gibt `not_triggered` zurück und gibt in `target_results` `record_status=skipped` an; der worker schreibt die `skipped`-Historie.
- `degraded_count` zählt alle Einträge mit `record_status=degraded` unter den vollständigen Expansions-Bewertungsergebnissen; `target_results` zeigt nur die ersten 20 Einträge, sortiert mit triggered zuerst, dann degraded/failed, dann nach target.

### Positionsrisikoregeln

| `alert_type` | Parameter | Beobachtungswert | Auslösesemantik |
| --- | --- | --- | --- |
| `portfolio_stop_loss` | `mode=near|breach`, Standard `near` | maximales `loss_pct` der betroffenen Ziele | `near` verwendet `stop_loss.near_alert`, `breach` zählt nur items mit `is_triggered=true`; pro Konto pro Runde maximal eine Auslösung |
| `portfolio_concentration` | - | `concentration.top_weight_pct` | `top_weight_pct >= portfolio_risk_concentration_alert_pct` |
| `portfolio_drawdown` | - | `drawdown.max_drawdown_pct` | nutzt `drawdown.alert` von `PortfolioRiskService` wieder; `current_drawdown_pct` wird in diagnostics geschrieben |
| `portfolio_price_stale` | - | Anzahl der Positionen mit stale/missing Preis | jede Position mit `price_stale=true` oder `price_available=false` |

portfolio-diagnostics müssen `account_id` (oder `all`), `currency`, `as_of`, `price_stale`, `fx_stale`, `data_available`, `top_affected_symbols` enthalten. `portfolio_stop_loss`, `portfolio_concentration`, `portfolio_drawdown` nutzen `PortfolioRiskService.get_risk_report()` wieder; `portfolio_price_stale` nutzt die position-price-metadata von `PortfolioService.get_portfolio_snapshot()` wieder.

### Web- und cooldown-Zusammenfassung

- Das Web-Erstellungsformular erhält eine Zielumfang-Auswahl; `watchlist` / `portfolio_holdings` zeigen nur price/volume/P5-technische Indikatortypen, `portfolio_account` nur die vier portfolio-Risikotypen.
- Schlägt das Laden der Kontenliste bei `portfolio_holdings` / `portfolio_account` fehl, behält das Formular die Option `all` und zeigt den Fehler.
- `cooldown_active` in der Regelliste ist für `single_symbol` und `portfolio_account` genau; `watchlist` / `portfolio_holdings` sind übergeordnete Regelzusammenfassungen und stellen nicht den Kühlungszustand jedes Unterziels dar; der Unterziel-Kühlungszustand richtet sich nach Auslösungshistorie und `effective_target`.
- Die dry-run-UI zeigt aggregierte Zählungen und bis zu 20 `target_results`-Detailzeilen.

P6 macht nicht:

- Macht kein P7-Market-Light.
- Macht keine Erinnerungen vor Finanzberichts- oder Dividenden-/Ex-Datum; solche Regeln benötigen nach einem stabilen Datumsvertrag ein separates Follow-up.
- Macht keine Sektorstufen-Konzentrationsalarme; die P6-Konzentration verwendet die symbol-Dimension `top_weight_pct`.
- Macht keine übergreifende Benachrichtigungszusammenführung desselben Ziels über Regeln, keine Minutenbalken, keine präzise Bestimmung mehrerer Marktzeitzonen und keine legacy-JSON-Erweiterung.

## Phasenwahrnehmung und öffentliche Zusammenfassungskopplung (Refs #1386 P6)

Dieser Abschnitt beschreibt die Alarm-Sichtbarkeitskopplung von #1386 P6, abgegrenzt von dem obigen „P6 Kopplung von Positionen und Watchlist". Diese Kopplung fügt keine Alarmtabellen hinzu, macht keine Migration und löst keine leichte LLM-Analyse automatisch aus; sie schreibt nur die zum Auslösezeitpunkt öffentlichen phase/pack-Zusammenfassungen in die bestehende Auslösungshistorie.

- `AlertTriggerItem` behält die `diagnostics`-Zeichenkette und erhält die abgeleiteten Felder `market_phase_summary`, `analysis_context_pack_overview`, `analysis_visibility_source`.
- Echte `status=triggered`-worker-Datensätze fügen in den JSON-diagnostics den sibling-key `analysis_visibility` zusammen, der `market_phase_summary`, `analysis_context_pack_overview`, `source` enthält. Alte reine Text-diagnostics behalten den Originaltext; die abgeleiteten API-Felder geben `null` zurück, source gibt `legacy_text` zurück.
- `analysis_visibility_source` nimmt Werte `alert_trigger_market_context`, `analysis_history_snapshot`, `evaluator_snapshot`, `legacy_text` oder `null` an.
- symbol-Ziele konstruieren die Auslösephase über `get_market_for_stock(normalize_stock_code(effective_target))`; `target_scope=market` verwendet direkt `normalize_market_region(target)` und leitet `cn|hk|us|jp|kr` nicht als Aktiencode ab; kann die kontostufige Phase den Markt nicht eindeutig bestimmen, darf die Zusammenfassung auf `unknown` fallen.
- `analysis_context_pack_overview` stammt nur aus einer bereits vom evaluator mitgeführten overview oder einem historischen Snapshot der letzten 30 Tage. Die jüngste historische Abfrage nutzt die Codevarianten-Kandidaten des Historie-Dienstes wieder und wird best-effort mit kurzer In-Batch-Caching ausgeführt; fehlt oder kann sie nicht geparst werden, wird `null` zurückgegeben, ohne pack zu erfinden.
- Alarmbenachrichtigungen geben nur öffentliche Zusammenfassungen aus: Phasen-Label, trigger source, partial-bar-warning, Datenqualitätsstufe und die ersten beiden limitations. Benachrichtigungen dürfen kein raw-context-pack, keinen Prompt, keinen Nachrichtentext, kein vollständiges diagnostics-JSON, keine webhook-URL, kein token und keine sensiblen Positionsdetails ausgeben.
- Die Web-Alarmhistorie zeigt phase-badge, Datenqualitätsstufe und limitations-Leerzustand; alte Auslösungsdatensätze ohne öffentliche Zusammenfassung beeinträchtigen das Lesen der Liste nicht.
- #1390 P6 nutzt `DecisionSignal` weiter wieder: Echte Auslösungen auf Aktienebene verknüpfen bevorzugt das neueste aktive Signal desselben Ziels und schreiben das niedrig-sensible `decision_signal_summary` in diagnostics; ohne aktives Signal wird nur ein minimales `source_type=alert/action=alert`-Signal erzeugt. `trace_id=alert-rule-<hash>` dient nur dem best-effort-idempotenten Dedupe von Same-Source-Wiederholungen und überschreibt nicht das aktive Signal; neu erzeugte Alarmsignale schreiben kein `market_phase`, um eine wiederholte Erzeugung derselben Regel über Phasen hinweg zu vermeiden. Auslösungen von `market`, `portfolio_account`, overflow oder nicht in eine konkrete Aktie auflösbare Auslösungen erzeugen kein Einzelaktien-Signal.

Felder, Redaktion, Migration und Rollback-Grenzen von DecisionSignal siehe [DecisionSignal — Themendokument zu Entscheidungssignalen](decision-signals.md).

Benutzergrenze von #1386 P7: Die Alarmkopplung erklärt nur die zum Auslösezeitpunkt bereits öffentlichen Phasen- und Datenqualitätszusammenfassungen; sie löst keine leichte LLM-Intraday-Analyse automatisch aus und fügt keine Alarmtabellen, Regeltypen, Umgebungsvariablen oder Migrationen hinzu. Für eine phasenweise Analyse sollte weiterhin der manuelle Analyse-Einstieg über Analyse-API / Web ausgelöst werden; Alarmbenachrichtigungen behalten nur Phasen-Label, trigger source, partial-bar-warning, Datenqualitätsstufe und die ersten beiden limitations.

Der Rollback dieser Kopplung erfordert nur den Revert der worker/API/Web-Änderungen; das bestehende `diagnostics.analysis_visibility` bleibt als gewöhnliche JSON-diagnostics erhalten, und der alte Code liest diesen sibling-key nicht.

## P7 Strukturierte Ampel-Alarme

P7 fügt in die bestehende Alert-API, das Web-Alarmzentrum und `src/services/alert_worker.py` den `target_scope=market` hinzu, konsumiert das strukturierte `MarketLightSnapshot`, parst kein Markdown, erweitert kein legacy-`AGENT_EVENT_ALERT_RULES_JSON` und fügt keine Tabellen hinzu. Die Marktübersichtshistorie schreibt weiterhin einen `analysis_history(code=MARKET, report_type=market_review)`-Datensatz; die Multi-Markt-Übersicht speichert über `context_snapshot.market_light_snapshots` die Snapshot-Karte der diesmal tatsächlich durchgeführten Übersicht je region.

### P7 scope/type-Matrix

| `target_scope` | `target` | Erlaubte `alert_type` | Parameter | Auslösesemantik |
| --- | --- | --- | --- | --- |
| `market` | `cn` / `hk` / `us` / `jp` / `kr` | `market_light_status` | `statuses=["red","yellow"]`, nur `red/yellow` erlaubt, Standard `["red","yellow"]` | löst aus, wenn der aktuelle `MarketLightSnapshot.status` in der Liste ist |
| `market` | `cn` / `hk` / `us` / `jp` / `kr` | `market_light_score_drop` | `min_drop > 0` | `prev.score - current.score >= min_drop`, und `prev.trade_date < current.trade_date` |

Die scope/type-Validierung ist eine zweiseitige Einschränkung: `target_scope=market` kann nur die zwei Market-Light-Regeltypen verwenden; `market_light_*`-Regeln können nur `target_scope=market` verwenden. `target` wird nach `strip().lower()` strikt auf `cn|hk|us|jp|kr` begrenzt; ein ungültiges target gibt HTTP 400 + `validation_error` zurück.

### `MarketLightSnapshot`-Vertrag

Die Felder des strukturierten Snapshots sind: `region`, `trade_date`, `status`, `score`, `label`, `temperature_label`, `reasons`, `guidance`, `dimensions`, `data_quality`. `trade_date` nimmt in der Erstversion fest `MarketOverview.date`; P7 parst kein provider-quote-as-of.

`dimensions` verwenden den canonical scorer als einzige Quelle; `build_market_light_snapshot()`, der Marktübersichts-Injektionsblock und der Alarm-Service implementieren das scoring nicht erneut. `_build_market_temperature()` ist nur ein thin wrapper; die `status`-Schwelle der Ampel bleibt `60/40`, die temperature-label-Schwelle bleibt `70/55/40`.

| dimension | `available=true`-Bedingung | fallback score |
| --- | --- | --- |
| `breadth` | `has_market_stats && (up_count + down_count) > 0` | `50` |
| `index` | `indices` nicht leer und mindestens ein `change_pct != None` | `50` |
| `limit` | `has_market_stats && (limit_up_count + limit_down_count) > 0` | `50` |

`data_quality=unavailable` bedeutet `index.available=false`, beide market-Regeltypen geben `skipped` zurück und lösen keine Benachrichtigung aus; `partial` bedeutet mindestens eine dimension mit Fallback, `ok` bedeutet alle drei available. `market_light_status` kann unter `ok/partial` auslösen; bei `partial`-Auslösung müssen diagnostics `missing_dimensions` enthalten. `market_light_score_drop` vergleicht direkt die canonical aggregate score; `partial` auf beiden Seiten erlaubt weiterhin den Vergleich, aber diagnostics müssen `partial_comparison=true` und `missing_dimensions` enthalten.

### Baseline, Handelstage und Dedupe

- Die Marktübersichtspersistenz muss das `MarketLightSnapshot` aus derselben `MarketOverview` erzeugen, die auch die Berichtserzeugung nutzt; ein zweites Kurzarufen in der persist-Phase ist verboten.
- `load_previous_snapshot(region, before_trade_date)` scannt `analysis_history(code=MARKET, report_type=market_review)`, überspringt legacy-Datensätze ohne `context_snapshot.market_light_snapshots[region]`, wählt zuerst das größte `snapshot.trade_date` kleiner als `before_trade_date` und nimmt dann innerhalb desselben `trade_date` nach `created_at DESC, id DESC` den neuesten gültigen Snapshot; ein später eingefügter Backfill eines alten Handelstags überschreibt die korrekte Baseline nicht.
- Ist das Ziel-`trade_date` nur ein beschädigter Snapshot, gibt `market_light_score_drop` `degraded` zurück und fällt nicht automatisch auf einen älteren Handelstag für einen best-effort-Vergleich zurück.
- `market_light_score_drop` macht in der Erstversion nur Vergleiche über Handelstage hinweg; ohne Baseline des vorherigen Handelstags oder bei Baseline desselben Tages wird `skipped` zurückgegeben, bei Abfrage-/Parse-Ausnahmen `degraded`.
- Der worker führt für `target_scope=market` einen region-Handelstags-Gate aus und respektiert `TRADING_DAY_CHECK_ENABLED` / `config.trading_day_check_enabled`; bei deaktivierter Prüfung ist die Bewertung erlaubt, bei aktivierter Prüfung und Nicht-Handelstag der region wird `skipped` zurückgegeben, ohne den aktuellen Snapshot abzurufen.
- Die Auslösungshistorie schreibt `target=<region>`, `observed_value=<score>`, `data_source=market_light`, `data_timestamp=<trade_date 00:00:00>` und nutzt weiterhin das P4-Dedupe `rule_id + target + data_source + data_timestamp`.

### Web- und Rollbackgrenzen

- Das Web-Alarmzentrum erhält `market`-scope, region-Auswahl, Parametersteuerungen der zwei market-Regeltypen, Typfilter, region-Anzeige und Parameteranzeige; die API-snake_case-Zuordnung verwendet `statuses` und `min_drop`.
- legacy-`AGENT_EVENT_ALERT_RULES_JSON` unterstützt keine market-Regeln; P7 aktualisiert `.env.example` nicht, da keine neuen Konfigurationsoptionen hinzugefügt werden.
- P7 macht keine Index-Kursverfall-', Sektor-Bewegungs-, Limit-Preis-Strukturverschlechterungs-, Minutenbalken-, mehrzeitzonen-präzise-quote-as-of-Analyse und führt kein DSL/keine Regelengine ein.

## P8 Benutzerkonfiguration und Deployment-Grenzen

P8 fügt keine Regeltypen, keine API, keine Tabellenstrukturen und kein worker-Verhalten hinzu; es fasst die in P0-P7 zusammengeführten Fähigkeiten als Konfigurationsbeschreibung für Benutzer und Betreiber zusammen. Der Alarm-worker wird nur in der schedule-Mode registriert; der Kernschalter bleibt `AGENT_EVENT_MONITOR_ENABLED`, das Polling-Intervall bleibt `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`. Die Benachrichtigungskanäle laufen weiter über die alert-Route; Details siehe `NOTIFICATION_ALERT_CHANNELS` und `route_type=alert` in [Benachrichtigungskonfiguration](notifications.md).

### Lokale Konfiguration

Beim lokalen Ausführen von `python main.py --schedule`, `python main.py --serve --schedule` oder einer äquivalenten eingebauten schedule-Mode wird nach dem Setzen von `AGENT_EVENT_MONITOR_ENABLED=true` der Hintergrund-Alarm-worker gestartet; `AGENT_EVENT_MONITOR_INTERVAL_MINUTES` steuert das Polling-Intervall.

Es gibt zwei Regelquellen:

- Über Alert-API / Web-Alarmzentrum persistierte Regeln: empfohlener Einstieg, unterstützt `single_symbol`, `watchlist`, `portfolio_holdings`, `portfolio_account`, `market` und deckt Echtzeitpreis, Kursänderungsprozentsatz, Volumen, Tagesbalken-technische Indikatoren, Positionsrisiko und Ampel-Regeln ab.
- legacy-`AGENT_EVENT_ALERT_RULES_JSON`: unterstützt nur die drei Basisregeltypen `price_cross`, `price_change_percent`, `volume_spike` von `single_symbol`; unterstützt keine P5-technischen Indikatoren, kein P6-watchlist/portfolio und kein P7-market-light. Das System migriert, löscht oder schreibt legacy-JSON nicht automatisch um.

### Docker

Der Standardbefehl von `docker/Dockerfile` im Repository ist `python main.py --schedule`; daher aktiviert die Konfiguration von `AGENT_EVENT_MONITOR_ENABLED=true` im Container den Alarm-worker in der schedule-Mode. Web/API-persistierte Regeln hängen von der Anwendungsdatenbank ab; bei Docker-Deployment muss das `data/`-Datenbankvolume erhalten bleiben, damit nach einem Container-Neubau Regeln, Auslösungshistorie, Benachrichtigungsversuche und Kühlungszustand nicht verloren gehen. Legacy-JSON wird weiterhin über Umgebungsvariablen injiziert und ist kein Docker-spezifisches Konfigurationssystem.

### GitHub Actions

Der mitgelieferte `.github/workflows/00-daily-analysis.yml` ist ein einmaliger Analyse-Workflow, der tatsächlich `python main.py`, `python main.py --market-review` oder `python main.py --no-market-review` aufruft; er führt keinen `--schedule`-Hintergrund-Alarm-worker aus und mappt auch keine `AGENT_EVENT_*`-Variablen. Das bloße Hinzufügen von `AGENT_EVENT_MONITOR_ENABLED` oder `AGENT_EVENT_ALERT_RULES_JSON` in repository Secrets / Variables lässt die Standard-Actions nicht mit kontinuierlichem Alarm-Polling beginnen.

Für Alarm-Polling in GitHub Actions ist ein späterer separater PR erforderlich, der die schedule-Startweise, env-Zuordnung, Regelquellen und die persistierte Datenbankstrategie klärt; P8 ändert den bestehenden Workflow nicht.

### Web und Desktop

Das Web-Alarmzentrum `/alerts` ist der Haupteinstieg für persistierte Regeln: Regeln können erstellt, aktiviert/deaktiviert, gelöscht und einmalig dry-run-getestet werden; Auslösungshistorie, Benachrichtigungsversuche und schreibgeschützter Kühlungszustand werden eingesehen. Der Listen-Kühlungszustand von Batch-Regeln ist eine übergeordnete Regelzusammenfassung; ob ein Unterziel gekühlt ist, richtet sich nach `target` / `effective_target` in der Auslösungshistorie.

Desktop fügt keine native Alarmverwaltungsoberfläche hinzu; Desktop-Benutzer nutzen die `/alerts`-Seite des eingebauten oder externen WebUI wieder. Desktop-Rollback erfordert keine Bereinigung zusätzlichen Zustands.

### Status, Benachrichtigung und Rollback

Der worker schreibt `triggered`, `skipped`, `degraded`, `failed` in `alert_triggers` als Bewertungshistorie; normal nicht ausgelöst wird nicht protokolliert. `skipped` bedeutet, dass die Regel in dieser Runde keine bewertbare Bedingung hatte, z. B. Nicht-Handelstag des Marktes oder fehlende Baseline des vorherigen Handelstags; `degraded` bedeutet, dass Datenquelle, Positions-Snapshot, historischer Snapshot oder Parse-Prozess eine Ausnahme aufwiesen und das Ergebnis nicht zur Auslösung einer Benachrichtigung verwendet werden kann.

Nach echten Auslösungen werden `alert_notifications` und `alert_cooldowns` geschrieben; DB-persistierte Regeln deduplizieren denselben Datenpunkt best-effort nach `rule_id + target + data_source + data_timestamp`. legacy-JSON-Regeln verwenden weiterhin nur den in-process-fingerprint und schreiben keine persistierte Kühlung.

Der Rollback von P8 erfordert nur den Revert von Dokument-, Konfigurationsbeschreibungs- und Web-Textänderungen; es gibt keine Datenbankmigration oder Benutzerdatenbereinigung. Beim Rollback früherer Phasen werden bereits erstellte persistierte Regeln nicht automatisch gelöscht; sie werden gemäß der Phasen-Rollback-Erläuterung unten behandelt.

## Phasengrenzen

- P0: Dieses Dokument, Verträge, Speicherbewertung und Kompatibilitätstests.
- P1: Alert-API MVP, Erstversion deckt nur die bestehenden drei Laufzeitregeltypen ab.
- P2: Alarmbewertungs-worker und runtime-Vereinheitlichung, sodass persistierte active rules und legacy-JSON koexistieren.
- P3: Web-Alarmzentrum MVP.
- P4: Auslösungshistorie, Benachrichtigungsergebnisse und Kühlungszustand.
- P5: Technische Indikatorregeln.
- P6: Kopplung von Positionen und Watchlist.
- P7: Ampel und Marktkopplung.
- P8: Dokumentation, Migration und Abschluss.

## P0 macht nicht

- P0 fügt kein `api/v1/schemas/alerts.py` oder keine Alert-API hinzu.
- P0 fügt keine Web-Alarmzentrum-Seite, keine Route und keinen Seitenleisten-Einstieg hinzu.
- P0 fügt keine Datenbanktabellen, kein repository und keine Migration hinzu.
- P0 implementiert kein Schreiben von Auslösungshistorie, Benachrichtigungsergebnissen oder Kühlungszustand.
- P0 migriert, löscht oder überschreibt `AGENT_EVENT_ALERT_RULES_JSON` nicht automatisch.
- P0 implementiert keine MACD-, KDJ-, CCI-, RSI-, Positionsrisiko- oder Market-Light-Alarmregeln.
- P0 schreibt `NotificationService` oder das Benachrichtigungs-Routingframework nicht neu.

## Rollback

- P0 ist der Abschluss von Dokument und Tests. Wird nur P0 zurückgerollt, reicht der Revert des zugehörigen PR; es gibt keine Datenbank-, Konfigurations- oder Benutzerdatenmigration, die zusätzlich behandelt werden muss.
- P1 fügt Alert-API-Code und die SQLite-Tabellen `alert_rules` / `alert_triggers` / `alert_notifications` hinzu. Der minimale Rollback-Weg ist der Revert des P1-PR; der Revert entfernt API, service, repository, schema und ORM-Definitionen, aber die von `Base.metadata.create_all()` bereits erstellten SQLite-Tabellen und -Daten werden nicht automatisch gelöscht. Für eine Bereinigung muss der Maintainer die zugehörigen Tabellen nach Bestätigung, dass die historischen Daten nicht mehr benötigt werden, manuell löschen.
- P3 ist eine Web- und Dokumentänderung. Der minimale Rollback-Weg ist der Revert des P3-PR; bestehende Regeln, Auslösungshistorie und legacy-JSON-Konfiguration werden nicht gelöscht.
- P4 fügt die SQLite-Tabelle `alert_cooldowns` hinzu und beginnt, `alert_notifications` zu schreiben. Der minimale Rollback-Weg ist der Revert des P4-PR; bereits erstellte `alert_cooldowns`-, `alert_triggers`-, `alert_notifications`-Daten werden nicht automatisch gelöscht. Für eine Bereinigung muss der Maintainer die entsprechenden Tabellen oder Datensätze nach Bestätigung manuell löschen.
- P5 fügt von Alert-API/Web unterstützte technische Indikatorregeln hinzu. Der minimale Rollback-Weg ist der Revert des P5-PR; bereits erstellte P5-`alert_rules`-Datensätze werden nicht automatisch gelöscht, und der alte Code überspringt unsupported-`alert_type`-Einträge in der worker-Ladephase, ohne die Ausführung der drei legacy-Regeltypen zu beeinträchtigen. Für eine Bereinigung muss der Maintainer die zugehörigen Regel-Datensätze nach Bestätigung manuell löschen.
- P6 fügt von Alert-API/Web unterstützte watchlist-, portfolio-holdings- und portfolio-account-Regeln hinzu. Der minimale Rollback-Weg ist der Revert des P6-PR; es gibt keine neuen Tabellen oder Migrationen, und bereits erstellte P6-`alert_rules` bleiben erhalten. Vor dem Rollback wird empfohlen, P6-Regeln, die nicht `single_symbol` sind, zu deaktivieren/löschen; sonst könnte der alte worker das übergeordnete `target` von `watchlist` / `portfolio_holdings` als Aktiencode bewerten und failed/skipped-Rauschen erzeugen; portfolio-spezifische `alert_type`-Werte werden in der worker-Ladephase übersprungen.
- P7 fügt von Alert-API/Web unterstützte `market`-Regeln und die `market_light_snapshots`-Historie der Marktübersicht hinzu. Der minimale Rollback-Weg ist der Revert des P7-PR; es gibt keine neuen Tabellen oder Migrationen, und bereits erstellte P7-`alert_rules` bleiben erhalten. Vor dem Rollback wird empfohlen, Regeln mit `target_scope=market` zu deaktivieren/löschen; der alte worker überspringt unsupported-`market_light_*`-Typen oder erzeugt Konfigurationsrauschen wegen nicht erkannter scope/type.
