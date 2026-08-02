# Laufzeit-Diagnose und Datenzuverlässigkeit 1.0 (Phase 3)

Dieses Dokument beschreibt den Lieferumfang von Phase 3 für #1391: Ohne neue Konfiguration hinzuzufügen, werden die Sichtbarkeit der Laufzeit-Diagnose vervollständigt und historische Fehlerbehebungs-Informationen in den Backend-Kontext-Snapshot zurückgeführt, damit in Selbstbereitstellungs-Umgebungen Anomalien schnell lokalisiert werden können.

## Umfang dieser Runde

- Die Detailansicht historischer Berichte erhält eine standardmäßig eingeklappte Sektion „Laufzeit-Diagnose / Datenzuverlässigkeit“; ab #1523 wird der Web-Anzeigetitel in „Laufzeit-Diagnose / Laufzeitstatus“ angepasst, der Titel der historischen Phase bleibt unverändert.
- Das Aufgaben-Panel zeigt für laufende Aufgaben standardmäßig eingeklappte Trace-Informationen, um sie mit Backend-Logs, SSE und historischen Berichtsdaten zu verknüpfen.
- Historische Berichte beziehen die Diagnosezusammenfassung über eine schreibgeschützte Schnittstelle:

```http
GET /api/v1/history/{record_id}/diagnostics
```

- Wenn die synchrone Analyseresponse bereits `diagnostic_summary` enthält, kann das Frontend diese direkt anzeigen, ohne zusätzlich die Historien-Schnittstelle abzufragen.
- Das Diagnose-Panel unterstützt das Kopieren des vom Backend erzeugten, entsensibilisierten `copy_text` für Issues oder Deployment-Fehlerbehebung.
- Der Analysepfad ergänzt nach dem Speichern der Historie die Aufgaben-/Provider-/LLM-/Benachrichtigungsdiagnose in `context_snapshot.diagnostics`; die Historien-Diagnoseschnittstelle aggregiert sie einheitlich zu einer benutzerlesbaren Zusammenfassung.
- Das Run-Flow-Panel der Startseite verwendet denselben `RunFlowSnapshot`-Vertrag, um aktive Tasks, abgeschlossene Reports und die Markt-Nachbetrachtung anzuzeigen; aktive Tasks erhalten über die optionalen Inkrement-Ereignisse der Task-SSE eine Echtzeit-Ereignisliste, und nach Abschluss oder Verbindungsabbruch wird der Snapshot erneut abgerufen, um endgültige Konsistenz sicherzustellen.

## Echtzeit-Inkrement des Run-Flows

Der Run-Flow-Inkrement fügt keinen eigenen SSE-Endpoint hinzu und verwendet weiterhin:

```http
GET /api/v1/analysis/tasks/stream
```

Kompatibler Vertrag:

- Der Ereignistyp bleibt `task_progress`.
- Die vorhandenen Task-Payload-Felder bleiben unverändert.
- Wenn das diesmalige Fortschrittsupdate aus der Laufzeit-Diagnose stammt, kann optional das Feld `flow_event` ergänzt werden; ältere Clients ignorieren dieses Feld einfach.
- `flow_event` verwendet dieselbe entsensibilisierte Ereignisstruktur wie `RunFlowSnapshot.events[]`: `id`, `timestamp`, `severity`, `type`, `node_id`, `title`, `message`, `metadata`.
- Für aktive Tasks können die Echtzeit-Ereignisse `provider_run_started` / `llm_run_started` ergänzt werden; diese Ereignisse dienen nur der Anzeige der laufenden „running“-Karte und werden nach Abschluss durch die Ergebnis-Ereignisse `provider_run` / `llm_run` mit derselben `node_id` überschrieben; die historische Diagnose richtet sich weiterhin nach dem endgültigen Ergebnis.
- Das Backend-TaskQueue behält für jeden aktiven Task nur die letzten N Run-Flow-Ereignisse, um ein unbegrenztes Speicherwachstum zu vermeiden; die vollständige Historie bleibt in `context_snapshot.diagnostics` und den historischen `RunFlowSnapshot`-Datensätzen maßgeblich.

Beispiel:

```json
{
  "task_id": "3f87...",
  "trace_id": "3f87...",
  "stock_code": "600519",
  "status": "processing",
  "progress": 64,
  "message": "LLM erzeugt gerade die Analyseergebnisse",
  "flow_event": {
    "id": "flow_0002",
    "timestamp": "2026-06-08T22:30:24",
    "severity": "success",
    "type": "llm_run",
    "node_id": "llm_analysis_1",
    "title": "LLM erfolgreich",
    "message": "LLM deepseek-chat erfolgreich"
  }
}
```

Die Aufzeichnungsfunktion der Laufzeit-Diagnose löst nach dem erfolgreichen Schreiben der In-Memory-Diagnosen für Provider, LLM, Historie-Speicherung und Benachrichtigung fail-open den Event-Sink aus. Ein Sink-Fehler wird nur als warning protokolliert und ändert nicht die Erfolgs-/Fehlschlags-Bewertung von Analyse, Speicherung oder Benachrichtigung.

Auch die Nachrichten-/Intelligence-Suche wird in dieselbe Provider-Diagnosesemantik aufgenommen: `SearchService.search_stock_news()` erfasst mit `data_type=news_search` die Versuche von Such-Providern wie Tavily, SearXNG, Bocha und Brave sowie die Anzahl der gefilterten Ergebnisse, Cache-Treffer und Fehlerursachen. Wenn mehrere Such-Provider nacheinander versucht werden, wird in der Web-Run-Flow-Hauptgrafik standardmäßig ein aggregierter „Nachrichten-/Stimmungs“-Knoten angezeigt; die Karte zeigt die Provider-Kette und den Status, die Knotendetails zeigen Erfolgs-/Fehlschlags-Zahlen sowie Fallback-/Retry-Zahlen; bei Bedarf zur Fehlerbehebung kann der aggregierte Knoten aufgeklappt werden, um die einzelnen Provider-Versuche zu sehen.

Die Datenquellen-Swimlane der Run-Flow-Topologie wird bevorzugt nach der Startzeit der Knoten sortiert; wenn für Provider-/LLM-Knoten nur Abschlusszeit und Dauer vorhanden sind, wird `started_at` über `ended_at - duration_ms` abgeleitet und auf der Karte angezeigt. Knoten ohne verfügbare Zeit behalten die ursprüngliche Anzeige-Reihenfolge als Fallback. Die Hauptgrafik drückt die Prozessstruktur „Einstieg -> Datenquellen -> ContextPack -> LLM -> Speichern/Benachrichtigung“ aus; vollständige Fehlerbehebungsdetails bleiben in der Ereignisliste, den Knotendetails und dem aufgeklappten Zustand aggregierter Knoten erhalten.

Die Web-Run-Flow-Hauptgrafik verwendet ein internes Frontend-Anzeigemodell und ändert den Backend-`RunFlowSnapshot`-Vertrag nicht:

- Provider-Attempts werden nach `metadata.data_type` zu Datenquellen-Knoten aggregiert, z. B. Echtzeit-Kursdaten, Tagesdaten, Nachrichten-/Stimmungslage.
- `context_block_*`-Knoten werden standardmäßig in die `ContextPack`-Details eingeklappt, um eine Vermischung mit den Provider-Attempts in der Datenquellen-Swimlane zu vermeiden.
- Durch Klicken auf einen aggregierten Knoten kann die Attempts-Tabelle im Detailbereich angezeigt werden; nach Klicken auf „Attempts aufklappen“ kehren die Unter-Provider-Knoten der aktuellen Aggregationsgruppe in die Topologie zurück.
- Die Ereignisliste zeigt weiterhin alle Ereignisse; die mit Ereignissen verknüpften Knoten werden auf die aktuell sichtbaren Knoten abgebildet, bei Einklappung auf den aggregierten Knoten, bei Aufklappung auf den konkreten Attempt.
- Topologie-Verbindungen verwenden eine Multi-Verbindungspunkt-Strategie: Der horizontale Hauptablauf verläuft über die linken und rechten Ports, die vertikalen Beziehungen innerhalb derselben Swimlane von unten nach oben, und Fallback/Retry verwenden weiterhin Text-Labels und gestrichelte Linienstile.

## Run-Flow-API

```http
GET /api/v1/analysis/tasks/{task_id}/flow
GET /api/v1/history/{record_id}/flow
```

- Beide Schnittstellen geben denselben `RunFlowSnapshot`-Vertrag zurück.
- Wenn aktiven Tasks die Diagnose fehlt, wird ein Skeleton-Flow zurückgegeben, ohne Provider-/LLM-Ereignisse zu erfinden.
- Wenn ein aktiver Task bereits kürzliche `flow_event`-Einträge besitzt, gibt der Snapshot diese echten Ereignisse zurück und kann anhand der Knoten-Metadaten in den Ereignissen temporäre Knoten ergänzen.
- Abgeschlossene Historien bauen die vollständige Topologie bevorzugt aus `context_snapshot.diagnostics` und `analysis_context_pack_overview`.
- Historische Datensätze der Markt-Nachbetrachtung verwenden `code=MARKET`, `report_type=market_review` und laufen ebenfalls über `/history/{record_id}/flow` und das Web-Run-Flow-Panel; es gibt keinen separaten UI-Zweig.
- `cancel_requested` und `cancelled` sind gültige Run-Flow-Status; ein vom Benutzer abgebrochener Vorgang darf nicht als `failed` abgebildet werden.

## Run-Flow-Ansicht

Die Run-Flow-Ansicht ist ein visueller Fehlerbehebungs-Einstieg über der Laufzeit-Diagnosezusammenfassung und dient dazu, die grobe Kette einer Analyse von der Auslösung über die Datenerfassung, den ContextPack-Aufbau und die LLM-Erzeugung bis zum Speichern/Benachrichtigen zu verbinden. Sie ersetzt nicht das `copy_text` der Diagnosezusammenfassung, sondern organisiert dieselben entsensibilisierten Diagnosenachweise als Knoten, Verbindungen, Ereignisse und Zusammenfassungsmetriken, damit Anomalien oder degradierte Abschnitte von der Web-Startseite aus schnell lokalisiert werden können.

Das Backend stellt zwei schreibgeschützte Snapshot-Schnittstellen bereit:

```http
GET /api/v1/analysis/tasks/{task_id}/flow
GET /api/v1/history/{record_id}/flow
```

- `tasks/{task_id}/flow` richtet sich an aktive Tasks. Solange sich die Aufgabe noch in der In-Memory-Warteschlange befindet, wird bevorzugt der aktuelle Task-Snapshot zurückgegeben; wenn die Aufgabe bereits abgeschlossen ist, kann über dieselbe `task_id`/`query_id` versucht werden, die historische Diagnose zu lesen. Fehlt die Diagnose, wird ein Skeleton-Flow zurückgegeben, ohne Provider-, LLM- oder Benachrichtigungsereignisse zu erfinden.
- `history/{record_id}/flow` richtet sich an historische Berichte und unterstützt den Primärschlüssel des historischen Datensatzes oder eine auflösbare `query_id`. Gewöhnliche Einzelaktien-Analysen und die `MARKET`/`market_review`-Markt-Nachbetrachtung verwenden denselben `RunFlowSnapshot`-Vertrag.
- Wenn auf derselben Seite eine Einzelaktien-Analyse ausgelöst wird, kann der Einzelaktien-Ablauf den Tages-Marktkontext bei Bedarf erzeugen oder wiederverwenden; dies ist kein separater Einzelaktien-Analyseschritt, sondern die Erzeugung des Prompt-Hintergrunds. Das Backend speichert diesen Marktkontext über eine unabhängige `market_context_*`-`query_id` mit `scope=daily_market_context`, um eine gemeinsame Nutzung der `query_id` mit dem Einzelaktien-Bericht zu vermeiden.
- Zur Kompatibilität mit frühzeitig geschriebenen Mischdiagnosen führt der Run-Flow beim Lesen der Historie eine risikoarme Filterung nach Berichtstyp durch: `MARKET`/`market_review`-Datensätze verbergen die Provider-Knoten für Einzelaktien-Kursdaten, Tagesdaten, Technik, Fundamentaldaten und Chip-Verteilung; Einzelaktien-Datensätze verbergen die Markt-Nachrichtensuche vor dem ersten Einzelaktien-Kurs sowie die Markt-Speicher-/Benachrichtigungsknoten vor dem ersten Einzelaktien-LLM.
- Bei übersprungenen oder nicht konfigurierten Benachrichtigungen sind `attempts=0` erlaubt; der Run-Flow zeigt dies als skipped, sodass `/flow` nicht mehr wegen fehlgeschlagener Pydantic-Validierung einen 500 zurückgibt.
- Die Snapshot-Ebene enthält `summary`, `lanes`, `nodes`, `edges`, `events` und `generated_at`. Knotenstatus verwenden `pending/running/success/failed/degraded/fallback/timeout/cancel_requested/cancelled/skipped/unknown`, wobei vom Benutzer abgebrochene Status nicht als `failed` abgebildet werden.
- Bei alten Historien, fehlendem `context_snapshot.diagnostics` oder unzureichenden Nachweisen gibt das Backend `unknown` oder Skeleton-Knoten zurück; die Webseite zeigt sie als leer/unbekannt an, ohne die Detailansicht des Berichts zu beeinträchtigen.

Web-Einstieg:

- Die Karte der aktiven Aufgaben auf der Startseite bietet einen Run-Flow-Einstieg; nach dem Öffnen des Drawers wird der Task-Snapshot über `task_id` abgerufen.
- Die Zusammenfassung historischer Berichte und der Bereich Laufzeit-Diagnose bieten einen Run-Flow-Einstieg; nach dem Öffnen des Drawers wird der Historien-Snapshot über die historische Datensatz-ID abgerufen.
- Das Panel zeigt Zusammenfassung, Basistopologie, Ereignisliste und Knotendetails; komplexe Topologie-Aggregation, Echtzeit-Inkrement-Ereignisse und Layout-Politur werden in späteren Phasen weiter konsolidiert.

Entsensibilisierungs- und Kompatibilitätsgrenzen:

- Der Run-Flow liest nur vorhandene Aufgabeninformationen, historische Ergebnisse und die niedrigsensiblen Diagnosefelder aus `context_snapshot.diagnostics`; es werden keine neuen Konfigurationsoptionen hinzugefügt, keine Datenbankstruktur geändert und keine alte Historie migriert.
- `model`, `provider` und `fallback_model` dienen nur der Anzeige der tatsächlich diagnostizierten Aufrufinformationen; sie beteiligen sich nicht an Modellauswahl, Request-Routing, Base-URL-Auflösung oder Konfigurationsspeicherung.
- `metadata`, Fehlermeldungen und lokale Pfade werden vom Backend gekürzt und entsensibilisiert, um API-Keys, Tokens, Cookies, Webhooks, Prompts/Rohantworten, Proxy-Header und lokale absolute Pfade nicht preiszugeben.
- Beim Rollback können der Web-Einstieg und der Abfragepfad entfernt werden; die neu hinzugefügten schreibgeschützten Snapshot-Schnittstellen des Backends ändern nicht die Erfolgs-/Fehlschlags-Semantik der bestehenden Analyse-, Historien-, Benachrichtigungs- oder Diagnosezusammenfassungs-Schnittstellen.

## Statustexte

Gesamtstatus:

- `normal`: normal
- `degraded`: teilweise degradiert
- `failed`: fehlgeschlagen
- `unknown`: unbekannt

Komponentenstatus:

- `ok`: normal
- `degraded`: nach kürzlichem Fehlschlag degradiert
- `failed`: fehlgeschlagen
- `unknown`: unbekannt
- `not_configured`: nicht konfiguriert
- `skipped`: übersprungen

## Interaktionsgrenzen

- Der Diagnosebereich ist standardmäßig eingeklappt, um den Hauptinhalt des Berichts nicht zu verdrängen.
- Auf der ersten Anzeige werden nur der Gesamtstatus, die Hauptursache und die notwendigen Trace-Informationen gezeigt.
- Komponentenstatus und erweiterte JSON-Felder liegen im aufgeklappten Bereich; die erweiterten Felder werden noch einmal sekundär eingeklappt, um Informationsüberlastung zu vermeiden.
- Bei alten Berichten, Schnittstellenfehlern oder unzureichenden Nachweisen wird `unknown` angezeigt, ohne das Lesen des Berichts zu beeinträchtigen.

## Kompatibilitätsgrenzen

- In dieser Runde werden keine neuen `.env`-Konfigurationsoptionen hinzugefügt, die Datenbankstruktur nicht geändert und keine Datenmigration eingeführt.
- Das Web konsumiert nur die in Phase 1/2 ergänzten optionalen Felder und die schreibgeschützten Diagnose-Schnittstellen; das Backend vervollständigt die Diagnose-Persistenz und -Aktualisierung in `src/core/pipeline.py`, `src/services/run_diagnostics.py`, `src/storage.py` und `src/services/history_service.py` und stellt über `api/v1/endpoints/history.py` lesbare Endpoints bereit.
- Der Backend-Änderungsumfang umfasst Task-Orchestrierung, Nachschreiben nach dem Speichern der Historie, Abfrage der historischen Diagnose und Erfassung der Benachrichtigungsergebnis-Diagnose; diese Pfade ergänzen lediglich die Diagnose-Snapshots `context_snapshot.diagnostics` und die Zusammenfassung und ändern weder den Hauptanalyseablauf noch die Erfolgs-/Fehlschlags-Semantik der Benachrichtigungssendung noch die Hauptfelder des historischen Berichts.
- Der Kopiertext wird vom Backend erzeugt und entsensibilisiert; das Frontend ist nur für Anzeige und Kopieren zuständig.
- Desktop verwendet das Web-Build-Artefakt; Electron-Hauptprozess oder Packaging-Skripte werden nicht separat geändert.
- Die Kompatibilitätssemantik von Laufzeitkonfiguration/Modell/Provider/base_url wird nicht angepasst: Außer im Diagnose-Persistenzpfad werden Provider-Priorität, LiteLLM-Routing, Laufzeitbereinigung und Konfigurations-Rollback-Logik nicht geändert.
- Die Kompatibilitätsregeln für alte Historien und alte Konfigurationen bleiben unverändert: Die neuen optionalen Felder der historischen Diagnoseabfrage beeinträchtigen das Parsen bestehender Historien-Abfrageantworten nicht; der Rollback erfolgt durch Entfernen der diesmaligen Anzeige und der zugehörigen Frontend-Abfragepfade oder durch Wiederherstellen von Modell und Konfiguration gemäß den vorhandenen Leitfäden.
- Rollback-Strategie: Zuerst Frontend-Anzeige und Abfrage-Einstieg zurückrollen; falls die neuen Pfade vollständig isoliert werden müssen, kann der PR dieser Runde zurückgerollt werden (nach dem Rollback bleibt die ursprüngliche Response der historischen Datensätze erhalten, und die neuen Diagnose-Endpoints werden nicht mehr im Web angezeigt).

### Klarstellung zur strukturierten Detektion

Die strukturierte Detektion der Review dieser Runde hat Risiken bei externer Modell-/API-Kompatibilität und Laufzeitkonfigurations-Migration getroffen; die Schlussfolgerung nach Prüfung lautet wie folgt:

- Modellname/Provider/Base URL: In dieser Runde werden keine Modellnamen, Provider, Base-URLs, Kanäle oder Fallback-Standardwerte hinzugefügt, ersetzt oder neu geordnet; auch die Auflösungspriorität von `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `LITELLM_FALLBACK_MODELS`, `OPENAI_*`, `GEMINI_*`, `ANTHROPIC_*` und `DEEPSEEK_*` wird nicht geändert.
- SDK-/Abhängigkeits-Standardwerte: In dieser Runde werden `requirements.txt`, die Abhängigkeitseinschränkungen von `package.json` oder die Standardparameter der LiteLLM/OpenAI-kompatiblen Aufrufe nicht geändert; externe Quellen richten sich weiterhin nach den in `docs/llm-providers.md` und `docs/LLM_CONFIG_GUIDE*.md` dokumentierten offiziellen Dokumentationen und den aktuell gesperrten Abhängigkeiten.
- Bereinigung vor dem Speichern/Konfigurationsmigration: In dieser Runde werden keine Änderungen an Migrations-, Bereinigungs-, Lösch- oder Rückschreibstrategien für `.env`, Web-Einstellungsseiten-Kanäle, Desktop-Benutzerdatenverzeichnisse, Docker-Laufzeitkonfigurationsdateien oder alte Konfigurationen ausgelöst.
- Die tatsächlichen Laufzeitänderungen dieser Runde schreiben lediglich vorhandene Analyse-Traces, Provider-/LLM-/Benachrichtigungsergebnisse und entsensibilisierte Fehlerzusammenfassungen in `context_snapshot.diagnostics` und stellen sie über die schreibgeschützten Historien-Schnittstellen und das standardmäßig eingeklappte Web-Panel dar; ein Fehler bei der Diagnose-Erfassung wird nach fail-open behandelt und ändert nicht die Erfolgs-/Fehlschlags-Bewertung von Analyse oder Benachrichtigung.
- Daher handelt es sich hierbei um einen Fehlalarm/dokumentarische Klarstellung der strukturierten Detektion; es sind keine neuen offiziellen Quellen, Migrationsschritte für alte Konfigurationen oder Provider-Rollback-Pfade auszuführen. Falls ein Rollback nötig ist, genügt es, den Diagnose-Anzeige-/Abfrage-Einstieg gemäß der Rollback-Strategie dieses Abschnitts zu entfernen; die Wiederherstellungspfade für Modell und Laufzeitkonfiguration bleiben unverändert.

## Kompatibilitätsregression und Validierung (wichtiger Nachweis vor PR-Merge)

- Backend-Regressionsabdeckung:
  - `tests/test_pipeline_market_phase_context.py`
  - `tests/test_realtime_types.py`
  - `tests/test_scheduler_background.py`
  - `tests/test_analysis_api_contract.py` (Teilmenge: Verträge zu Diagnose-Kontext-Ein-/Ausgabe und Statusabfrage)
  - `tests/test_analysis_history.py` (Teilmenge: Historien-API und Persistenzpfad)
- Abdeckungsverhältnis: Der API-Vertrag wird durch `tests/test_analysis_api_contract.py` und `tests/test_analysis_history.py` abgedeckt; Task-Orchestrierung, Historien-Speicherung und `context_snapshot.diagnostics` werden durch `tests/test_pipeline_market_phase_context.py` abgedeckt; der Benachrichtigungspfad wird durch die vorhandenen Benachrichtigungsregressionen und Importprüfungen in `./scripts/ci_gate.sh` abgesichert.
- Regressionsbefehle (vor PR-Merge muss bestätigt werden, dass alle bestehen):

```bash
./scripts/ci_gate.sh
python -m pytest tests/test_realtime_types.py tests/test_scheduler_background.py tests/test_pipeline_market_phase_context.py tests/test_analysis_api_contract.py tests/test_analysis_history.py
cd apps/dsa-web && npm run lint && npm run build
```

## Validierungsvorschlag

```bash
cd apps/dsa-web
npm run lint
npm run build
```

Zusätzlich ausführbar (nicht blockierend):

```bash
cd apps/dsa-web
npm test -- --run src/components/report/__tests__/ReportDiagnostics.test.tsx src/components/tasks/__tests__/TaskPanel.test.tsx src/hooks/__tests__/useTaskStream.test.tsx
```

Zusätzliche deterministische Skriptprüfung:

```bash
python -m py_compile api/v1/endpoints/analysis.py api/v1/endpoints/history.py api/v1/schemas/analysis.py api/v1/schemas/history.py src/core/pipeline.py src/services/run_diagnostics.py src/storage.py
```

## Rollback

Minimaler Rollback: Den Phase-3-PR reverten. Da diese Runde eine Erweiterung um optionale Felder und lesbare Schnittstellen ist, bleiben nach dem Rollback die Backend-Historien-Snapshots und die bereits gespeicherten Daten erhalten; das Web zeigt das Diagnose-Panel und den Trace-Diagnose-Einstieg nicht mehr an.
