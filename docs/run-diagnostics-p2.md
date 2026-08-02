# Laufzeit-Diagnose und Datenzuverlässigkeit 1.0 (Phase 2)

Dieses Dokument beschreibt den Backend-Umsetzungsumfang von Phase 2 für #1391: Auf Basis der `trace_id` und der Provider-Run-Einträge aus Phase 1 wird eine benutzerlesbare Laufzeit-Diagnosezusammenfassung erzeugt und ein kopierbarer, entsensibilisierter Fehlerbehebungstext bereitgestellt.

## Umfang dieser Runde

- Neue Aggregationslogik für `RunDiagnosticSummary`, die den Gesamtstatus ausgibt:
  - `normal` / normal
  - `degraded` / teilweise degradiert
  - `failed` / fehlgeschlagen
  - `unknown` / unbekannt
- Die Zusammenfassung deckt die folgenden kritischen Pfade ab:
  - Echtzeit-Kursdaten
  - Tagesdaten
  - Nachrichtensuche
  - LLM
  - Benachrichtigung
  - Speichern der Historie
- Die synchronen/asynchronen Aufgabenergebnisse von `AnalysisService` erhalten optional `diagnostic_summary`.
- Neue Diagnose-API für historische Berichte:

```http
GET /api/v1/history/{record_id}/diagnostics
```

`record_id` unterstützt den Primärschlüssel des historischen Datensatzes oder `query_id` und gibt die Diagnosezusammenfassung sowie `copy_text` zurück.

## Kopierbare Fehlerbehebungs-Informationen

`copy_text` ist ein auf Issues/Fehlerbehebung ausgerichteter Klartext und enthält:

- `trace_id`
- `query_id`
- `stock_code`
- `trigger_source`
- Gesamter `data_status`
- Kurzer Status für Echtzeit-Kursdaten, Tagesdaten, Nachrichten, LLM, Benachrichtigung und Historie-Speicherung
- Hauptursache

Vor der Erzeugung werden die Entsensibilisierungsregeln der Laufzeit-Diagnose wiederverwendet, um die Ausgabe sensibler Informationen wie Tokens, API-Keys, Authorization, Cookies, Webhook-URLs, E-Mail-Passwörter und Proxy-Anmeldedaten zu vermeiden.

## Kompatibilitätsgrenzen

- In dieser Runde werden keine neuen Konfigurationsoptionen hinzugefügt, die Datenquellen-Priorität nicht geändert und die Fallback-Strategie nicht verändert.
- In dieser Runde werden keine LLM-/Provider-/Base-URL-/Konfigurationsmigrations-Semantiken geändert; es werden lediglich Diagnosefelder im Historien-Snapshot und eine Abfrage-Schnittstelle ergänzt.
- Die API ergänzt nur optionale Felder und eine neue schreibgeschützte Schnittstelle; ältere Clients können sie ignorieren.
- Wenn alte Berichte kein `context_snapshot.diagnostics` enthalten, wird `unknown` zurückgegeben, ohne einen Fehler auszulösen.
- Die Benachrichtigungsdiagnose wird im Kontext der aktuellen Aufgabe erfasst; wenn zum Zeitpunkt des Speicherns eines historischen Berichts noch keine Benachrichtigungsnachweise vorliegen, wird in der Zusammenfassung das Benachrichtigungsergebnis als unbekannt angezeigt.
- Ein Fehler bei der Erzeugung der Diagnosezusammenfassung darf weder das Lesen des Berichts noch den Hauptanalyseablauf beeinträchtigen.

### Klarstellung zum strukturierten Detektions-Alarm

- Der vom automatisierten Detektor gemeldete „Modell-/Provider-/Base-URL-Kompatibilitäts-Risiko“ stammt daher, dass `src/agent/factory.py` einen **sicheren numerischen Fallback** (`_coerce_config_int`) für `agent_max_steps` und `agent_orchestrator_timeout_s` hinzugefügt hat; der Scanner kann diesen daher fälschlich als konfigurationsrelevanten Pfad erkennen. Dieser Treffer ist durch Test- und Routingschutz ausgelöst und keine Änderung der Laufzeitkonfiguration oder der Kompatibilitätssemantik.
- Wenn eine numerische Konfiguration ungültige Werte enthält, protokolliert das System eine `warning` im Log `src.agent.factory` (Beispiel: `[AgentFactory] Invalid value for agent_max_steps...`) und fällt auf den Standardwert zurück; das Log dient zur Lokalisierung von Problemen wie „Parameter wirkungslos“ und ist unabhängig von der Modell-/Provider-/Base-URL-Kompatibilität.
- In dieser Runde wird bestätigt, dass keine stille Migration/Löschung/Überschreibung stattfindet:
  - `src/core/pipeline.py` und `src/services/analysis_service.py` fügen nur Diagnose-Einträge hinzu und ändern keine `litellm_model`-, `agent_litellm_model`-, `openai_base_url`- oder Kanal-`LLM_*`-Felder in der `Config`.
  - `_coerce_config_int` in `src/agent/factory.py` berechnet `max_steps` und `timeout_seconds` nur beim Erstellen der Ausführungsparameter und schreibt nicht in das `config`-Objekt zurück; die Originalwerte von `litellm_model`, `agent_litellm_model` und `openai_base_url` werden im Konstruktionspfad vollständig durchgereicht.
  - In dieser Runde werden keine Laufzeitbereinigung, kein Persistenz-Rückschreiben und keine Migrationsprozesse der `Config` ausgelöst, sodass kein Risiko besteht, dass die Laufzeitkonfiguration durch Rückschreiben überschrieben wird.
- Regressionsvalidierung: `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_does_not_mutate_llm_route_config` und `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_multi_arch_does_not_mutate_llm_route_config` bestätigen ausdrücklich, dass diese Felder nach `build_agent_executor` ihren Originalwert behalten.
- Rollback-Pfad: Zum Wiederherstellen des alten Verhaltens die betreffenden Commits dieser Runde entfernen; oder die `diag_*`-Felder aus der Deserialisierungs-Kette von `context_snapshot`/`RunDiagnosticSummary` entfernen. Für den Hauptablauf und die Modell-/Provider-Konfiguration sind keine zusätzlichen Migrationen oder Reparaturen erforderlich.

## Validierungsvorschlag

```bash
python -m pytest tests/test_run_diagnostics_p2.py tests/test_run_diagnostics_p1.py
python -m py_compile src/services/run_diagnostics.py src/services/history_service.py api/v1/endpoints/history.py api/v1/schemas/history.py
```
