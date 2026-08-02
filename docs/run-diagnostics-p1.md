# Laufzeit-Diagnose und Datenzuverlässigkeit 1.0 (Phase 1)

Dieses Dokument beschreibt den minimalen Laufzeit-Umsetzungsumfang von Phase 1 für #1391: Vereinheitlichung von `trace_id` sowie strukturierte Erfassung der Provider-Versuche für die ersten kritischen Datenpfade.

## Umfang dieser Runde

- Beim Erstellen von asynchronen API-/Web-Aufgaben verwendet `TaskInfo` `task_id` als standardmäßige `trace_id`.
- Aufgabenliste, Aufgabenstatus und SSE-Ereignisse erhalten zusätzlich das Feld `trace_id`; ältere Clients können dieses Feld ignorieren.
- Bei der synchronen Analyse wird die jeweilige `query_id` als standardmäßige `trace_id` verwendet.
- Die Pipeline erstellt zur Laufzeit einen leichtgewichtigen Diagnose-Kontext, der die Tagesdaten-Vorbereitung und die Einzelaktien-Analyse durchgängig begleitet.
- `data_provider/base.py` erfasst für die folgenden Pfade Ereignisse im `ProviderRun`-Stil:
  - `daily_data`
  - `realtime_quote`
- Die Diagnose-Einträge werden in den Speicher-Kontext geschrieben und mit `context_snapshot.diagnostics` der Analyse gespeichert; alte historische Datensätze ohne dieses Feld bleiben kompatibel.

## `ProviderRun`-Felder

Die Felder der ersten Version bleiben minimal:

- `trace_id`
- `data_type`
- `provider`
- `operation`
- `success`
- `latency_ms`
- `error_type`
- `error_message_sanitized`
- `fallback_to`
- `record_count`
- `created_at`

Fehlerzusammenfassungen werden grundlegend entsensibilisiert, um die Ausgabe von Tokens, API-Keys, Authorization, Cookies oder Webhook-URLs mit sensiblen Parametern zu vermeiden.

## Stabilitätsgrenzen

- Ein Fehler bei der Diagnose-Erfassung wird nur als warning aufgezeichnet und beeinträchtigt weder die Hauptanalyse, den Datenquellen-Fallback noch das Speichern der Historie.
- In dieser Runde werden keine neuen Konfigurationsoptionen hinzugefügt, die Datenquellen-Priorität nicht geändert und die Fallback-Strategie nicht verändert.
- In dieser Runde werden keine neuen Web-Anzeigekomponenten hinzugefügt; `trace_id` und Provider-Runs gehen zunächst in API/SSE/Historien-Snapshots ein, damit spätere Phasen 2/3 sie aggregieren und anzeigen können.

## Validierungsvorschlag

```bash
python -m pytest tests/test_run_diagnostics_p1.py tests/test_analysis_api_contract.py::AnalysisApiContractTestCase::test_get_analysis_status_normalizes_completed_queue_result_contract
python -m py_compile src/services/run_diagnostics.py src/services/task_queue.py src/services/analysis_service.py src/core/pipeline.py data_provider/base.py api/v1/schemas/analysis.py api/v1/endpoints/analysis.py
```
