# Laufzeit-Diagnose und Datenzuverlässigkeit 1.0 (Phase 0)

Dieses Dokument definiert die **Phase 0 (P0)** von #1391: Ohne neue Seiten einzuführen und ohne die globale Analysestrategie sowie die zentrale Fallback-Semantik zu verändern, werden die Vertragsgrenzen konsolidiert und der Umfang der diesmaligen Laufzeit-Fixes eingegrenzt.

## Ziel

- Einheitliche Begriffe für die nachfolgende Umsetzung bereitstellen: `trace_id`, Aufzeichnung der kritischen Pfade, Diagnose-Zusammenfassung, entsensibilisierte Fehlerbehebungs-Informationen.
- Den Umfang der ersten Phase klar abstecken, um zu vermeiden, dass die Anforderung zu einer „vollständigen Observability-Plattform“ ausgeweitet wird.
- Die Fail-open-, Sicherheits- und Retention-Baseline festlegen, um das Regressionsrisiko zu senken.

## Umfang dieses Dokuments (diese Runde)

- Dieses Dokument ist der Phase-0-Vertrag und die Abnahmegrenze. Der aktuelle PR ist docs + runtime fix. In dieser Runde werden die A-Aktien-Zugehörigkeitsgrenzen von `baostock_fetcher.py`, `pytdx_fetcher.py` und `tushare_fetcher.py` vervollständigt und über `tests/test_a_share_fetcher_code_conversion.py` einer Regression geprüft.
- Die Zugehörigkeitsgrenze muss sowohl nackte Codes als auch Präfix-Codes abdecken (z. B. `000001`, `000001.SZ`, `SH000001`, `SH.000001`, `SZ000001`, `SZ.000001`), damit die SH/SZ-Präfix-Semantik nicht falsch zugeordnet wird.
- Sofern keine neuen LLM-bezogenen Anforderungen zur Migration von Provider-/Modell-/Base-URL-Semantik bestehen, wird die Tushare-A-Aktien-Zugehörigkeit in dieser Runde auf `600/601/603/605/688` und `000/001/002/003/300/301` begrenzt; die Szenarien `605`, `001`, `003` und `301` werden dabei mitregressiert. Diese Umfangsänderung gilt nicht als Erweiterung der Provider-Konfiguration oder der Routing-Strategie.

## Nicht-Ziele

- Kein OpenTelemetry-/APM-/Grafana-artiges Monitoring-System.
- In der ersten Version keine Darstellung von p95, vollständigen Provider-Aufruf-Details oder einem vollständigen Operations-Panel.
- Keine Änderung der bestehenden Datenquellen-Priorität, Analysestrategie oder Benachrichtigungsstrategie.
- Keine Änderung der LLM-Provider-Liste, der Base URL, der `llm_call`-Laufzeitparameter, der `REPORT_*`-Konfigurationssemantik und des Migrationspfads; die diesmaligen Änderungen beschränken sich auf die A-Aktien-Code-Zugehörigkeitsauflösung und die Diagnose-Feldgrenzen.

### Abnahmegrenze (diese Runde)

- Diese Runde ist ein `fix` (docs + runtime fix). Die Änderung konsolidiert nur die A-Aktien-Code-Zugehörigkeitssemantik und ändert weder die Provider-Liste, die Base URL, die `llm_call`-Laufzeitsemantik noch den `REPORT_*`-Konfigurations-Migrationspfad.
- `data_provider/baostock_fetcher.py`, `data_provider/pytdx_fetcher.py` und `data_provider/tushare_fetcher.py` behandeln in dieser Runde nur:
  - Nackte Codes und Suffix-Codes: `000001`, `000001.SH`, `000001.SZ`
  - Präfix-Codes: `SH000001`, `SH.000001`, `SZ000001`, `SZ.000001`
- Die Szenarien `SH000001`/`SH.000001`/`SZ000001`/`SZ.000001` sind Correctness-Blocker und müssen über `tests/test_a_share_fetcher_code_conversion.py` regressiv abgedeckt werden.
- Die minimale Regression ist `python -m pytest tests/test_a_share_fetcher_code_conversion.py` und `./scripts/ci_gate.sh`; die Ergebnisse und Blockaden werden in der PR-Beschreibung mitgeteilt.
- Die Rollback-Priorität besteht darin, die drei in dieser Runde geänderten Dateien auf den Stand vor dem Merge zurückzusetzen; die übrigen Bereiche sollten nicht mit zurückgerollt werden.

## Begriffe und Vertrag (P0-Entwurf)

### 1) `trace_id`

- Bedeutung: Einheitliche Korrelations-ID für eine Analyse-Laufkette.
- Anforderungen:
  - Jede Analyse-Aufgabe hat nur eine `trace_id`.
  - Kann am Einstiegspunkt erzeugt oder aus einer vorhandenen Aufgaben-ID abgeleitet werden (z. B. Web-Aufgaben).
  - Erscheint in Logs/strukturierter Diagnose zur Fehlerkorrelation.

### 2) `RunDiagnosticSummary`

- Bedeutung: Kurze Laufzeit-Diagnosezusammenfassung für Benutzer.
- Empfohlene Felder (in der ersten Version minimal gehalten):
  - `trace_id`
  - `status`: `ok` / `degraded` / `failed`
  - `data_status`: ob kritische Datenpfade degradiert sind
  - `notify_status`: Zusammenfassung des Benachrichtigungsergebnisses
  - `error_hint`: entsensibilisierte Kurzursache
- Hinweis: Dies ist eine für Benutzer wahrnehmbare Fähigkeit, nicht gleichbedeutend mit dem vollständigen internen Ereignisprotokoll.

### 3) Aufzeichnung der kritischen Pfade (minimale Menge)

In der ersten Version müssen nur die folgenden Ergebnisse der kritischen Knoten erfasst werden (Erfolg/Fehlschlag/Degradierung + kurze Ursache):

- `realtime_quote`
- `daily_data`
- `llm_call`
- `report_persist`
- `notification_dispatch`

> Hinweis: `news`, `fundamental`, `capital_flow` usw. werden in spätere Erweiterungen verschoben und sind kein Blocker der ersten Version.

## Sicherheits- und Stabilitätsgrenzen (P0 muss eingehalten werden)

### Fail-open

- Ein Fehler bei der Diagnose-Erfassung darf den Hauptanalyseablauf nicht blockieren.
- Selbst wenn das Schreiben der Diagnose fehlschlägt, müssen weiterhin Analyseergebnisse erzeugt werden (außer der Hauptablauf selbst schlägt fehl).

### Entsensibilisierung

- Kopierte Fehlerbehebungs-Informationen dürfen keine Schlüssel, Tokens, vollständige Webhook-URLs oder Benutzerkontokennungen enthalten.
- Fehlermeldungen werden primär als Zusammenfassung ausgegeben, um die Weitergabe sensibler Originaltexte von Drittanbietern zu vermeiden.

### Retention

- Die Aufbewahrungsdauer der Diagnosedaten sollte konfigurierbar sein oder einheitlich bereinigt werden können.
- Die Standardstrategie ist konservativ (z. B. nur das notwendige Zeitfenster aufbewahren), um ein unbegrenztes Wachstum zu vermeiden.

### Kompatibilität

- Neue Felder sollten bevorzugt ergänzt werden und dürfen die bestehenden Lese-Pfade von API / Web / Desktop nicht brechen.
- Alte historische Datensätze ohne neue Felder sollten sicher zurückfallen können.

## Phase-0-Lieferliste

- [x] Ziele/Nicht-Ziele klären, um ein Ausufern des Umfangs zu verhindern.
- [x] Minimalvertrag für `trace_id` und `RunDiagnosticSummary` definieren.
- [x] Abdeckungsumfang der kritischen Pfade der ersten Version klären.
- [x] Fail-open-, Entsensibilisierungs-, Retention- und Kompatibilitäts-Baseline festlegen.

## Nachfolgende Phasen (nur Hinweis, nicht in P0 umgesetzt)

- Phase 1: Durchgängige `trace_id` und minimale Aufzeichnung der kritischen Pfade umsetzen.
- Phase 2: `RunDiagnosticSummary` erzeugen und persistieren, Kopieren entsensibilisierter Fehlerbehebungs-Informationen unterstützen.
- Phase 3: Minimale Web-Darstellung (standardmäßig eingeklappt) und Ergänzung von Dokumentation und Rollback-Hinweisen.
