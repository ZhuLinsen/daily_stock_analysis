# AnalysisContextPack：P0-Bestandsaufnahme, P1/P2-Verträge, P3-Runtime-Konsum, P4-Sichtbarkeit, P5-Datenqualität, #1386 P6-Kopplung und #1389 P6-Migration/Rollback

Diese Seite ist das Themendokument für Issue #1389. Es dokumentiert die realen Quellen, Konsumpfade und Feldstatus-Grenzen des aktuellen DSA-Analysekontexts sowie die internen Verträge des `AnalysisContextPack`, den Builder, den Laufzeitkonsum, die niedrig-sensible Sichtbarkeit, die Datenqualitäts-Bewertung, die Kopplung mit Alarmen/Positionen/Historie/Backtest sowie die Migrations- und Rollback-Grenzen. P0 übernimmt die Bestandsaufnahme des Ist-Zustands und die Vertragsgrenzen; P1 fügt nur das interne schema/envelope, den Block-Katalog, die Typkonventionen und die redigierte Serialisierung hinzu; P2 assembliert das pack nur aus bereits vorhandenen Pipeline-Artefakten; P3 speist die niedrig-sensible Zusammenfassung nur in die normale Analyse und den initialen Agent-Prompt ein; P4 macht die niedrig-sensible Übersicht nur in der Historie-Detailansicht, der synchronen Analyse-Antwort, dem completed task status und der Web-Reportseite sichtbar; P5 ergänzt innerhalb derselben `PACK_VERSION = "1.0"` die Datenqualitäts-Bewertung, den `fetch_failed`-Status, die Prompt-Datenbegrenzung und die niedrig-sensible Übersichtsdarstellung; #1386 P6 nutzt dieselbe öffentliche Übersicht für die Kopplung von Alarm, Position, Historie, Backtest und Benachrichtigung und fügt bei der manuellen Positionsanalyse einen optionalen Hilfs-`portfolio`-Block hinzu; #1389 P6 ergänzt nur Dokumentation, Konfigurationssichtbarkeit sowie Migrations- und Rollback-Hinweise, ohne neues pack-runtime, pack-feature-flag, DB-Migration oder Schema-Version.

## Terminologie und Grenzen

Im aktuellen Repository gibt es mehrere Dateneigenen, die als context / snapshot bezeichnet werden. P0 muss diese zunächst disambiguieren, um zu vermeiden, dass bestehende Laufzeitstrukturen fälschlich als zukünftiges pack beschrieben werden.

| Begriff | Aktuelle Bedeutung | Wichtigste aktuelle Konsumenten | P0-Grenze |
| --- | --- | --- | --- |
| `storage.get_analysis_context()` | Ein in `src/storage.py` aus den OHLCV-Daten der letzten zwei Tage aus der Datenbank erzeugter, vereinfachter technischer Kontext mit `today`, `yesterday`, `volume_change_ratio`, `price_change_ratio`, `ma_status` usw. Die aktuelle Implementierung akzeptiert `target_date`, nutzt aber faktisch die Daten der letzten zwei Tage. | Hauptkette der normalen Analyse, Agent-Tool `get_analysis_context` | Als historische technische Eingabequelle dokumentieren, nicht direkt mit dem zukünftigen pack gleichsetzen. |
| `enhanced_context` | In der normalen Analyse der von `src/core/pipeline.py` anhand des vereinfachten DB-Kontexts, der Echtzeitkurse, der Chip-Verteilung, des Trends, der Fundamentaldaten und der Sprache angereicherte Prompt-Kontext. | Prompt-Rendering in `src/analyzer.py`, `_build_context_snapshot()` | Aktuelle Prompt-Eingabeebene dokumentieren; P0 ändert weder Feldnamen noch Struktur. |
| `analysis_history.context_snapshot` | Der nach Abschluss der Analyse in die Verlaufstabelle geschriebene persistierte Schnappschuss. Die normale Analyse enthält üblicherweise `enhanced_context`, `news_content`, `realtime_quote_raw`, `chip_distribution_raw`; der Agent-Pfad speichert `initial_context`. | Verlaufsdetail, synchrone analysis/status-Antworten, Backtest, teils Fundamentaldaten-Fallback-Anzeige | Als persistierte Konsumebene dokumentieren; `context_snapshot.enhanced_context.date`-Kompatibilität muss erhalten bleiben. |
| Agent executor message context | Von `AgentExecutor._build_user_message()` in die erste Benutzernachricht injizierter Kontext, gültig für den `AGENT_ARCH=single`-Pfad; enthält derzeit Aktiencode, Berichtstyp, Ausgabesprache, `realtime_quote`, `chip_distribution`, `news_context`. | Erste LLM-Nachricht des Einzel-Agents | Aktuelle, in der ersten Runde sichtbare Felder dokumentieren; P0 ergänzt keine Laufzeit-Injektion. |
| Agent orchestrator `AgentContext` | Von `AgentOrchestrator._build_context()` in den geteilten Kontext des Multi-Agents geschriebene Daten, gültig für den `AGENT_ARCH=multi`-Pfad; kann `realtime_quote`, `daily_history`, `chip_distribution`, `trend_result`, `news_context` vorab injizieren. | Technical / Intel / Risk / Decision Multi-Agent-Kette | Als interne, geteilte Datengebene des Orchestrators dokumentieren; `fundamental_context` nicht vorab injizieren; ob `trend_result` existiert, hängt davon ab, ob der Caller es übergibt. |

## P0-Umfang und Nicht-Ziele

Das Ziel von P0 ist, dass nachfolgende P1/P2/P3 das `AnalysisContextPack` auf Basis der realen Repository-Grenzen entwerfen können, statt die Laufzeit vorzeitig umzubauen.

- P0 deckt die Bestandsaufnahme des Kontexts über sieben Pfade ab: normale Analyse, Agent, Alarm, Position, Backtest, Historie und Benachrichtigung.
- P0 fixiert die Wortliste der Feldqualitätsstatus; P1 hat das interne `AnalysisContextPack`-Schema bereits hinzugefügt, erstellt aber weiterhin keinen Builder, bindet kein runtime an und macht das vollständige pack nicht öffentlich.
- P0 fügt keinen Builder, keine Konfigurationsoptionen, keine Datenbankfelder hinzu und verändert weder API-, Berichts-, Historie- noch Benachrichtigungs-Payloads.
- P0 bindet kein runtime an, ändert keine Analyse-, Agent-, Alarm-, Positions-, Backtest- oder Benachrichtigungslogik in `src/`.
- P0 packt `market_review`, `market_light` oder das Ampeln-Sonderpfad-Schnappschuss nicht; diese werden nur als andere `report_kind`-/Sonderpfad-Konsumgrenzen in historischen Schnappschüssen dokumentiert.
- P0 nahm `fetch_failed` damals nicht in die Wortliste der Feldqualitätsstatus auf; P5 hat diesen Status innerhalb desselben 1.0-umbrella ergänzt, um „nicht unterstützt" klar von „dieses Abrufen ist fehlgeschlagen" zu unterscheiden.
- P0 erweitert README nicht um Implementierungsdetails; diese Seite dient als Themendokument und wird über die Einstiege `docs/INDEX.md` / `docs/INDEX_EN.md` aufgefunden.

## P1 Interner Vertrag

P1 setzt `src/schemas/analysis_context_pack.py` um und definiert nur das interne schema/envelope, damit P2-Builder und P3-runtime beim Konsum dieselbe Struktur wiederverwenden können. P1 füllt keine Laufzeitdaten, fügt keinen fetcher hinzu, ändert keinen Prompt, schreibt kein history/task/report-metadata und macht das vollständige pack weder für API, Web, Bot, Desktop noch Benachrichtigungen sichtbar.

Das P1-Schema umfasst:

- `PACK_VERSION = "1.0"`, markiert über `AnalysisContextPack.pack_version` die Vertragsversion.
- `ContextFieldStatus`: In der ersten P1-Version sind nur `available`, `missing`, `not_supported`, `fallback`, `stale`, `estimated`, `partial` erlaubt; P5 hat `fetch_failed` ergänzt, das bedeutet, dass der Abruf eines Felds oder Datenblocks in diesem Durchlauf eindeutig fehlgeschlagen ist, nicht aber die gesamte Analyse.
- `AnalysisSubject`: Oberste Identitäts-Slot mit nur `code`, `stock_name`, `market`; `exchange`, `currency`, `industry` sind für spätere Erweiterungen vorgesehen. Der P2-Builder erweitert das P1-Schema nicht und fügt auch keinen neuen `identity`-Block hinzu.
- `AnalysisContextItem`: Feldebene-Eingabeposten mit `status`, `value`, `source`, `timestamp`, `fallback_from`, `missing_reason`, `warnings`, `metadata`.
- `AnalysisContextBlock`: Gruppierung auf Datenblock-Ebene mit `status`, `items`, `source`, `timestamp`, `warnings`, `metadata`, wobei `items` ein `Dict[str, AnalysisContextItem]` ist.
- `DataQuality`: P1 behält nur die Container `warnings` und `metadata`; P5 hat `overall_score`, `level`, `block_scores`, `limitations` ergänzt, bleibt aber niedrig-sensibel und trägt keine raw-payload.
- `AnalysisContextPack`: Oberstes envelope mit `pack_version`, `subject`, `phase`, `blocks`, `data_quality`, `metadata`, `created_at`.

Zeitfeld-Konvention:

- `AnalysisContextPack.created_at` verwendet `datetime` und wird über `model_dump(mode="json")` als ISO-8601-Zeichenkette ausgegeben.
- `AnalysisContextItem.timestamp` und `AnalysisContextBlock.timestamp` verwenden `Optional[str]` und sind als ISO-8601-datetime-Zeichenketten konventioniert; das P1-Schema validiert dieses Format bei der Konstruktion; reine Datumsangaben, natürliche Sprachzeit oder schrägstrichgetrennte Daten werden abgelehnt; der P2-Builder erzwingt beim Wiederverwenden bestehender Artefakt-Zeitstempel keine zweite Konvertierung.

Statussemantik:

- `block.status` beschreibt die Verfügbarkeit des gesamten Blocks.
- `item.status` beschreibt die Qualität auf Feldebene.
- P1 implementiert keine automatische Aggregationsableitung von `item.status` zu `block.status`.

P1-Block-Katalog:

| block key | P1-Semantik | P1-Grenze |
| --- | --- | --- |
| `quote` | Echtzeitkurse und quotierungsbezogene Eingaben | Definiert nur die ausdrückbare Position, ruft keine Daten ab und füllt keine. |
| `daily_bars` | Vollständiges Tagesbalken-Fenster und Datum des letzten vollständigen Tagesbalkens | P1 beurteilt keinen partial bar. |
| `technical` | Technische Indikatoren, Volumen-Preis-Struktur und Formationen | P1 erzeugt keine Indikatoren. |
| `fundamentals` | Bewertung, Wachstum, Profitabilität, Finanzberichte und Aktionärsrendite | P1 fügt keinen Fundamentaldaten-fetcher hinzu. |
| `news` | Nachrichten, Unternehmensmeldungen, Stimmung und Katalysator-Ereignisse | P1 ändert die Nachrichtensuche nicht. |
| `portfolio` | Ob Position gehalten, Kontozusammenfassung, Kosten, Menge, Positionsgröße und stale-Zusammenfassung | P1 bezieht keine Transaktionsströme, Kassenströme oder vollständige Kontoprivatsphäre-Daten ein. |
| `chip` / `capital_flow` | Chip-Verteilung, Kapitalfluss und Main-Player-Verhalten | Späterer Erweiterungsschlüssel, P1 erlaubt nur den Vertragsausdruck. |
| `events` / `market_context` | Risikoereignisse, Marktbreite, Indizes, Sektoren und Hot-Environment | Späterer Erweiterungsschlüssel; `market_review` / `market_light` werden nicht als Erstversion des Einzelaktien-packs verwendet. |

Das `phase`-Feld akzeptiert nur das Produkt von #1386 `MarketPhaseContext.to_dict()` und bleibt `Dict[str, Any]`; es definiert weder ein phase-enum noch ein phase-Submodell neu.

Redaktionsgrenzen:

- `AnalysisContextPack.to_safe_dict()` führt zuerst `model_dump(mode="json")` aus und ruft danach `redact_sensitive_mapping()` auf.
- `redact_sensitive_mapping()` führt nur eine key-basierte, rekursive Redaktion von dict/list durch; bei Treffern sensibler Schlüssel oder Phrasen wie `api_key`, `access_token`, `refresh_token`, `authorization_header`, `webhook_url`, `password`, `cookie`, `secret`, `token`, `sendkey`, `license_key` wird der Wert durch `[REDACTED]` ersetzt.
- P1 scannt keine gewöhnlichen Zeichenkettenwerte, führt keine URL-Regex-Redaktion durch und behandelt weder `data_api` noch bloße `api` / `key` als sensiblen Treffer, um diesen Vertrag nicht zu einer generischen secrets engine auszubauen.

## P2 Builder-Vertrag

P2 fügt `AnalysisContextBuilder` hinzu, aber die Erstversion ist nur ein assembler: Er assembliert aus den Artefakten, die die normale Analyse-Pipeline bereits erhalten hat, das interne `AnalysisContextPack`. Der Punkt „vorhandene Datenquellen wiederverwenden" in den Issue-Abnahmekriterien wird in diesem slice so interpretiert, dass bereits von der Pipeline gefetchte Artefakte wie `realtime_quote`, `base_context`, `enhanced_context`, `trend_result`, `chip_data`, `fundamental_context`, `news_context` wiederverwendet werden; der Builder selbst ist zero-fetch, er ruft weder DB, fetcher, SearchService, Agent-Tools noch einen konkreten provider auf.

Der P2-Eingabevertrag verwendet `PipelineAnalysisArtifacts`: `code`, `stock_name`, `market`, `phase`, `base_context`, `enhanced_context`, `realtime_quote`, `trend_result`, `chip_data`, `fundamental_context`, `news_context`, `news_result_count`, `metadata`. Der Einzelaktien-`build()` und der Batch-`build_batch()` nutzen dieselbe Struktur, damit bei der P3-runtime-Anbindung die Signatur nicht erneut geändert werden muss.

P2-Block-Assemblierungsgrenzen:

- `subject` schreibt weiterhin nur die drei Felder `code`, `stock_name`, `market` und erweitert `AnalysisSubject` nicht.
- `phase` akzeptiert nur das übergebene Produkt von `MarketPhaseContext.to_dict()` und leitet es nicht aus `enhanced_context` rückwärts ab.
- `quote` wird aus `realtime_quote` assembliert; fehlt es, gilt `missing`; `source=fallback` oder explizites `fallback_from` wird auf `fallback` abgebildet, aber `source` behält die echte erfolgreiche Quelle; `fallback_from` wird nur ausgefüllt, wenn artifact/metadata es explizit liefern, sonst wird nur ein stabiler warning-code protokolliert und keine provider-Kette erfunden.
- `quote` gibt die `fetched_at`, `provider_timestamp`, `is_stale`, `stale_seconds`, `fallback_from` aus #1386 P3 durch. Die Statuspriorität ist fest `STALE > FALLBACK > AVAILABLE`: explizite Marker wie `is_stale=True`, `price_stale`, `quote_stale`, `quote_stale_seconds` werden als `stale` markiert; `stale_seconds` mit `is_stale=False` ist nur Metadaten und führt nicht für sich allein zu einer stale-Ableitung. Der Builder bildet nur Upstream-Artefakte ab und macht keine Qualitätsbewertung.
- `daily_bars` drückt nur das vollständige Tagesbalken-Fenster aus und liest bevorzugt `base_context.today`, `base_context.yesterday`, `base_context.date`, `base_context.data_missing`; reine Datumsangaben kommen in `value` oder `metadata`, nicht in `timestamp`.
- `is_partial_bar`, `is_estimated`, `estimated_fields` auf `enhanced_context.today` gehen bevorzugt in `technical`; fehlen sie, bleibt die alte heuristic mit `enhanced_context.today.data_source` als `realtime:*` kompatibel. partial/estimated gehen nur in `technical`; `daily_bars` trägt kein partial/estimated; der warning verwendet `intraday_realtime_overlay`.
- `technical` nutzt bevorzugt `trend_result.to_dict()`; ohne trend-artifact gilt `missing`.
- `chip` nutzt `chip_data.to_dict()`; ohne chip-artifact ist der Standard `missing`, nur wenn das eingehende metadata/artifact explizit not_supported angibt, wird `not_supported` markiert.
- `fundamentals` liest nur den Parameter `fundamental_context`; `ok` wird auf `available`, `not_supported` auf `not_supported`, `partial` auf `partial` abgebildet; nach P5 wird `failed` auf `fetch_failed` plus stabiler reason-code `fundamental_pipeline_failed` abgebildet; der Originaltext von `errors[]` wird nicht geschrieben.
- `news`: nicht leere Zeichenkette gilt als `available`, leer oder fehlend als `missing`; `news_result_count` wird in pack-metadata geschrieben.

P2 assembliert `portfolio`, `events`, `market_context` nicht und zerlegt `capital_flow` auch nicht in einen eigenen Block; die Erstversion belässt es nur in den coverage/source-chain-metadata der fundamentals. P2 änderte damals auch keinen Prompt, ließ weder die normale Analyse noch den Agent-runtime das pack konsumieren, schrieb kein history/task/report-metadata und setzte das vollständige pack nicht für API/Web/Bot/Desktop/Benachrichtigungen aus; P5 ergänzt nur auf dem bestehenden Builder die niedrig-sensible Bewertung, die `fetch_failed`-Unterteilung und die Prompt-Begrenzung, ohne neuen fetcher.

## P3 Runtime-Konsum

P3 bindet nach dem P2-`AnalysisContextBuilder` den Laufzeitkonsum an, begrenzt die Konsumfläche aber auf die niedrig-sensible `analysis_context_pack_summary`. `StockAnalysisPipeline` ist der einzige Produzent der summary: Im normalen Analysepfad und im Agent-Pfad werden `PipelineAnalysisArtifacts` -> `AnalysisContextBuilder.build()` -> `format_analysis_context_pack_prompt_section()` durchlaufen; nachgelagerte Komponenten (analyzer, single-agent, multi-agent) empfangen nur die summary-Zeichenkette, konstruieren selbst kein vollständiges pack und lesen auch keine block-item-Rohwerte aus `AnalysisContextPack.to_safe_dict()`.

Die Reihenfolge des Prompts der normalen Analyse ist fest: Basisinformationen -> #1386 Rendering-Block `market_phase_context` -> `analysis_context_pack_summary` -> bestehende Blöcke wie technische Daten, Echtzeitkurse, Nachrichten. `analysis_context_pack_summary` enthält nur subject, `pack_version`, block `status` / `source` / `warnings` / `missing_reason`, `metadata.news_result_count`, `data_quality.warnings` und die P5-niedrig-sensible Datenbegrenzung; es darf `news.content`, `trend_result`, `chip`, `fundamental_context` und andere raw-payloads nicht ausgeben.

Auch der Agent-Pfad übergibt nur die summary. `AgentExecutor._build_user_message()` fügt die summary nach dem market-phase-Abschnitt und vor dem pre-fetched JSON ein; `AgentOrchestrator._build_context()` legt die summary nur in `ctx.meta["analysis_context_pack_summary"]` ab und darf nicht in `ctx.data` schreiben; `BaseAgent._build_messages()` fügt die summary nach der market-phase-user-message und vor `_inject_cached_data()` ein. Der Agent-Pfad liest nach dem Vorabruf von `_ensure_agent_history()` einmal `storage.get_analysis_context()` als niedrig-sensible Statusquelle für `daily_bars`; nur bei Lesefehler oder ohne verfügbaren Kontext wird `daily_bars_missing` markiert. Dieser Lesevorgang ist fail-open und schreibt keine Rohdaten der Tagesbalken in den Agent-runtime-Kontext. Die erste Agent-Runde nutzt die Nachrichtenrecherche der normalen Analyse nicht wieder; `news`-Block als `missing` ist der aktuell erwartete P3-Zustand.

P3 persistierte damals kein vollständiges pack, fügte keine API/Web/Bot/Desktop-Felder hinzu, änderte nicht das JSON-Schema der Berichte und schrieb die summary nicht in `analysis_history.context_snapshot`, task status oder report-metadata; history-snapshot und diagnostic-snapshot entfernen runtime-Prompt-Schlüssel wie `market_phase_context`, `analysis_context_pack`, `analysis_context_pack_summary`. P4 ergänzt darauf aufbauend die niedrig-sensible Übersicht; die Sichtbarkeit deckt nur Historie-Detailansicht, synchrone Analyse-Antwort, completed task status und Web-Reportseite ab; P5 nutzt weiterhin denselben summary-Konsumpfad und ändert das von LLM ausgegebene JSON-Schema nicht. Ein Wiederverwendungs-Cache des pack auf Agent-Tool-Ebene bleibt Folgearbeit.

## #1381 Daily Market Context

#1381 fügt außerhalb des AnalysisContextPack einen kleinen täglichen Zusammenfassungskanal des Marktumfelds hinzu, um `market_review` / `market_light` nicht direkt zu packen. `DAILY_MARKET_CONTEXT_ENABLED` ist standardmäßig aktiviert; wenn `MARKET_REVIEW_ENABLED=true` und `DAILY_MARKET_CONTEXT_ENABLED=true` sind, lädt `StockAnalysisPipeline` je nach Aktienmarkt (`cn` / `hk` / `us`) den Marktkontext des Tages: bevorzugt wird derselbe Tageseintrag desselben Marktes aus `analysis_history(code=MARKET, report_type=market_review)` wiederverwendet; nur wenn kein Eintrag desselben Tages existiert, wird `run_market_review(..., return_structured=True, send_notification=False)` aufgerufen, um den Kontext dieses Durchlaufs zu erzeugen, wobei ein in-process-cache die doppelte Erzeugung innerhalb derselben Pipeline vermeidet und auf dem parallelen CLI/Zeitplan-Pfad über den market-review-lock serialisiert wird. `DAILY_MARKET_CONTEXT_ENABLED=false` deaktiviert nur die niedrig-sensible Zusammenfassungs-Injektion und den Schutz-Guardrail der Einzelaktien-Analyse, nicht die Marktübersicht selbst.

**Background：** `#1381` fokussiert die Wiederverwendung und den Fallback der Tagesmarktumgebung bei der Einzelaktien-Analyse und ändert weder die bestehende Intraday-Phase, die Tagesberichte noch die Statusmodellierung. Dieser Abschnitt stimmt mit dem #1381-Eintrag in `docs/CHANGELOG.md` [Unreleased] überein und dient als Konvergenzgrenze der Änderungsbeschreibung dieser Runde.
**Scope (Implementierungsumfang dieser Runde):** `#1381` deckt nur die Marktkontext-Injektion des Backend-runtime, die Wiederverwendung und den Schutz-Guardrail für den Tages-/Zielhandelstag ab; es umfasst keine eigenständige API, keine eigenständige Web-Phase-Anzeige der Ergebnisse, keine strukturierte Persistenz der Vierphasen-Tagesberichte und keine neue Tagesbericht-Statustabelle. Die beteiligten Haupteinstiege sind `main.py` (Zeitplan und `--no-market-review`), `src/core/pipeline.py`, `src/core/market_review.py`, `src/services/daily_market_context.py`, `src/analyzer.py`, `src/analysis_context_pack_overview.py`, `src/agent/executor.py`, `src/agent/orchestrator.py`, `src/agent/agents/base_agent.py`, `src/daily_market_context_guardrail.py`; auf der Web-Seite werden nur der Text/Hilfetext der Einstellung `DAILY_MARKET_CONTEXT_ENABLED` synchronisiert, keine neue Phasen-Ergebnisanzeige.
**Abnahme-Closed-Loop-Grenze:** Dieser PR entspricht nur dem runtime-Einstieg und den Guardrail-Unterzielen von `#1381`; Issue #1381 darf erst als vollständig abgenommen gelten, wenn die eigenständige API, die Web-Phasen-Anzeige, die Vierphasen-Tagesbericht-Persistenz und die Tagesbericht-Statustabelle in nachfolgenden Änderungen umgesetzt und verifiziert wurden.
**Acceptance Criteria (Abnahmegrenze):** Diese Runde nimmt nur runtime und Konfigurationseinstiege ab und bezieht keine eigenständige Phasen-Anzeige der API/Web-UI in den PR-Prozess ein. Der aktuelle Abnahmepfad ist begrenzt auf `tests/test_main_schedule_mode.py`, `tests/test_pipeline_daily_market_context.py`, `tests/test_daily_market_context.py`, `tests/test_daily_market_context_guardrail.py`, `tests/test_agent_executor.py`, `tests/test_config_env_compat.py`, `tests/test_config_registry.py` und `apps/dsa-web/tests/system_config_i18n.test.ts`. Die Schwerpunktabdeckungen sind: `--no-market-review` unterbindet die Erzeugung der Marktübersicht, `DAILY_MARKET_CONTEXT_ENABLED=false` deaktiviert die Einzelaktien-Kontext-Injektion, behält aber die Marktübersicht, ein einzelner schedule nutzt dasselbe `target_date` wieder, Kontextladen über mehrere Märkte (`cn,us`), `daily_market_context` wird nur einmal in derselben Analyse-Hauptkette injiziert, und die normale Analyse sowie der Agent-Pfad wenden den Guardrail an, ohne das rohe `market_review_payload` weiterzugeben.
**Compatibility/Risk (Kompatibilität und Risiko):** `#1381` ändert weder `provider/model/base_url`, Standardmodell noch die Semantik von Konfigurationsbereinigung/Backfill/Migration; es fügt keine Datenbank- oder Laufzeitkonfigurationstabellen-Änderungen hinzu. `main.py::_bootstrap_environment`, `src/core/pipeline.py`, `src/analyzer.py`, `src/agent/executor.py`, `src/agent/orchestrator.py`, `src/agent/agents/base_agent.py`, `src/services/daily_market_context.py`, `src/daily_market_context_guardrail.py` konsumieren den LLM- und Marktübersichtskontext nur in bestehenden Lese-Pfaden und fügen keine `SystemConfig`-Speicher- oder Rückschreibzweige hinzu. Als offizielle Kompatibilitätsbasis gelten weiterhin `LiteLLM OpenAI-compatible` und `OpenAI Chat Completion` (siehe unten „Kompatibilitätsnachweise und Verifikationsgrenzen"); der Rollback-Weg ist der übliche Release-Rollback (Rücknahme der zugehörigen Commits), bei Bedarf ergänzt um einen Neustart und die Bereinigung von `env_file` / `--env-file` / prozessbezogenen gleichnamigen Umgebungsüberschreibungen, um die historisch persistierten Benutzerkonfigurationen wiederherzustellen.
**Kompatibilitätsnachweise und Verifikationsgrenzen:** Diese Runde nutzt nur den bestehenden LLM-Konfigurationslese-Pfad, fügt keinen `.env`-Schreibzweig hinzu und keine neuen Konfigurationsmigrations-/Bereinigungs-/Rückschreibeinstiege. Als offizielle Grundlage gelten: `LiteLLM OpenAI-compatible` <https://docs.litellm.ai/docs/providers/openai_compatible>, `OpenAI Chat Completion` <https://platform.openai.com/docs/api-reference/chat/create>; die Versionsbeschränkungen siehe `requirements.txt` (`litellm`, `openai`) im aktuellen Fenster. Rückverfolgbare Codepfade: `main.py::_bootstrap_environment`, `src/analyzer.py::_init_litellm`, `src/agent/agents/base_agent.py::_get_analyzer_config` (nur lesend), `src/agent/executor.py`, `src/agent/orchestrator.py`, `src/core/pipeline.py`, `src/services/daily_market_context.py`, `src/daily_market_context_guardrail.py`. Regressions-Verifikationspunkte sind `tests/test_config_env_compat.py`, `tests/test_config_registry.py`, `tests/test_system_config_service.py`, `tests/test_system_config_api.py`, `tests/test_llm_channel_config.py`, `tests/test_market_review_runtime.py`.

Normale Analyse und Agent-Analyse empfangen nur niedrig-sensible Felder: `daily_market_context` (region, trade_date, summary, risk_tags, source, optional position_cap) und den Prompt-Abschnitt `daily_market_context_summary`; das vollständige `market_review_payload`, rohe Nachrichten, Schlüssel oder Benachrichtigungskonfiguration werden nicht weitergegeben. Die normale Analyse fügt die Marktzusammenfassung nach dem Marktphasen-Abschnitt und vor den technischen Daten in den Prompt ein; der Einzel-Agent- und der Multi-Agent-Pfad fügen dieselbe Zusammenfassung nach der market-phase und vor den pre-fetched Daten ein. Der freie Chat des Agents injiziert die Marktzusammenfassung nur, wenn der Aufrufer bereits `daily_market_context` / `daily_market_context_summary` geliefert hat; er löst nicht für jeden Chat automatisch eine Marktübersicht aus.

Die Nachbearbeitung der Ergebnisse fügt einen konservativen Marktumfeld-Guardrail hinzu: Wenn Zusammenfassung oder Tags `high_risk`, `market_cooling`, `conservative`, `low_position_cap` zeigen und der Kontext konservativ/hochriskant ist, wird eine `buy`-Entscheidung des Modells (einschließlich Kauf-Empfehlungen wie „sofort kaufen/nachjagen/aggressiv aufstocken") zu Abwarten oder kleiner Position mit Bestätigung abgeschwächt und die hohe Konfidenz auf mittel herabgestuft. Dieser Guardrail ändert nur die niedrig-sensible Begrenzungserklärung der jeweiligen `AnalysisResult` und des dashboards und fügt keine Datenbanktabelle oder API-Felder hinzu. Der Rollback-Weg ist die Rücknahme der #1381-bezogenen Dienste, der Prompt-Injektion und des guardrail-Codes; die bestehenden Verlaufsaufzeichnungen der Marktübersicht bleiben kompatibel.

## P4 Historie-Datensätze, Task-Status und Web-Sichtbarkeit

P4 projiziert das in P3 aufgebaute `AnalysisContextPack` auf die öffentliche, niedrig-sensible `analysis_context_pack_overview`. Diese Übersicht wird von einem dedizierten renderer erzeugt; die öffentliche API darf `AnalysisContextPack.to_safe_dict()` oder einen vollständigen pack-dump nicht direkt zurückgeben. Der renderer gibt nur Whitelist-Felder aus: `pack_version`, `created_at`, `subject.code` / `stock_name` / `market`, `key` / `label` / `status` / `source` / `warnings` / `missing_reasons` der Datenblöcke, nach block-status gezählte `counts`, top-level `data_quality.warnings` und `metadata.trigger_source` / `metadata.news_result_count`. P5 ergänzt auf derselben Übersicht das niedrig-sensible Objekt `data_quality`, ohne die top-level `warnings` zu wiederholen.

Die Übersicht gibt `blocks.*.items`, `items.value`, `news.content`, `trend_result`, `chip`, `fundamental_context`-raw-payloads nicht aus, ebenso keine sensiblen Schlüssel oder Werte wie `api_key`, `token`, `cookie`, `webhook_url`, `password`, `secret`, `authorization`, `sendkey`, `license_key`.

Die P4-Persistenzfläche schreibt `analysis_context_pack_overview` nur auf die oberste Ebene von `analysis_history.context_snapshot`. Laufzeit-Prompt-Felder werden weiterhin aus `enhanced_context` und history-snapshot entfernt: `market_phase_context`, `analysis_context_pack`, `analysis_context_pack_summary` gehen nicht in die öffentliche Historie-Detailansicht oder den Task-Status. Bei `SAVE_CONTEXT_SNAPSHOT=false` wird die gesamte `analysis_history.context_snapshot` nicht persistiert; damit werden auch overview, `market_phase_summary`, `enhanced_context` oder raw-snapshot-Felder nicht in die Datenbank geschrieben; alte Datensätze oder Datensätze ohne overview geben weiterhin leere Felder zurück, ohne das Lesen der Historie-Detailansicht zu beeinträchtigen.

Das öffentliche API-Feld ist fest `report.details.analysis_context_pack_overview`; die Web-Seite liest nach tiefem camelCase `analysisContextPackOverview`. Die Verdrahtungsflächen umfassen:

- `GET /api/v1/history/{record_id}` Historie-Detailansicht.
- Die synchrone Antwort `AnalysisResultResponse.report.details` von `POST /api/v1/analysis/analyze`, wobei die overview von der bereits persistierten `analysis_history.context_snapshot` abhängt; bei `SAVE_CONTEXT_SNAPSHOT=false` ist die Rückgabe der overview für neue Datensätze nicht garantiert.
- completed `GET /api/v1/analysis/status/{task_id}`, einschließlich In-Memory-Queue-Enrichment und DB-completed-Fallback.

Das an die Web-Seite zurückgegebene `details.context_snapshot` der API entfernt über `sanitize_context_snapshot_for_api()` die top-level `analysis_context_pack_overview`, damit das raw-snapshot-Panel sie nicht doppelt anzeigt oder als vollständigen Kontext exportiert; die overview wird nur separat über `extract_analysis_context_pack_overview()` entnommen. Der Agent-Pfad und der normale Analyse-Pfad schreiben dieselbe overview-Form; ohne Nachrichtenzählung im Agent kann `metadata.news_result_count` leer sein.

Die P4-Web-Anzeige rendert `AnalysisContextSummary` nur auf der Berichtsdetailseite, nach den Strategiepunkten und Nachrichten und vor der Laufzeitdiagnose; dieser Bereich ist standardmäßig eingeklappt. Der eingeklappte Kopf zeigt die Anzahl verfügbarer, fehlender, sonstiger Nicht-Null-Status und den Auslösegrund; jeder Datenblock zeigt im ausgeklappten Zustand nur Status, Quelle, Warnung und Erklärung. Ist die Quelle leer, wird „Eingabequelle nicht erfasst" angezeigt; die Erklärungszeile übersetzt bekannte Fehlgründe in Ursache, Auswirkung auf diese Analyse und einen kurzen Bearbeitungshinweis und behält den Diagnosecode in Klammern; bei unbekannter Ursache wird ein allgemeiner Hinweis je nach block-Status gegeben. Degradierte Status ohne Fehlgrund wie `fallback`, `stale`, `estimated`, `partial` werden ebenfalls in derselben Erklärungszeile erklärt, ohne neue Verarbeitungs-, Umfangs- oder Nachweisfelder hinzuzufügen. Die nachrichtenbezogenen Informationen der Berichtsseite werden über eine eigene Schnittstelle geladen; ob sie vorhanden sind, kann nicht über `metadata.news_result_count` der overview abgeleitet werden; der Nachrichtenbereich erläutert nur, dass er Zusatzinformationen zur Berichtsseite ist, und der Eingabedatenblock nur, ob Nachrichten in die LLM-Analyse dieses Durchlaufs eingegangen sind, damit die beiden Datenumfänge nicht als ein Ergebnis-Set vermischt werden. Der ausgeklappte Bereich zeigt weiterhin Statuszählung und Nachrichtenergebnisanzahl. Nach P5 zeigt der eingeklappte Kopf außerdem Qualitätspunktzahl/Stufe; nach dem Ausklappen werden `limitations` und der `fetch_failed`-Status angezeigt. Ohne overview wird kein Platzhalter gerendert. In #1386 P4b zeigt die Web-Seite auf derselben Berichtsdetailseite das Phasen-Label `report.meta.market_phase_summary` und nutzt weiterhin diese niedrig-sensible Datenqualitäts-Zusammenfassung; die öffentliche Fläche von vollständigem pack, prompt-summary, raw-payload oder snapshot-internen Feldern wird nicht erweitert. P4/P5 decken weder die AnalysisContextPack-Datenqualitäts-Zusammenfassung des pending/processing-TaskPanels noch die SSE-Sichtbarkeit der laufenden overview ab; sie ändern weder Benachrichtigungszusammenfassung, Bot/Desktop-spezifische Anzeige noch `market_review`-overview.

## P5 Datenqualitäts-Bewertung und Prompt-Datenbegrenzung

P5 ergänzt ohne Versionserhöhung von `PACK_VERSION`, ohne neuen fetcher, ohne neue Konfigurationsoptionen und ohne historische Migration drei Dinge: die interne niedrig-sensible Datenqualitäts-Bewertung, einen modellübergreifend einheitlichen Prompt-Datenbegrenzungs-Block sowie die niedrig-sensible Sichtbarkeitserweiterung der bestehenden `analysis_context_pack_overview`. #1389 P5 ändert weiterhin das von LLM ausgegebene JSON-Schema nicht und erzwingt auch keine Nachbearbeitungs-Umschreibung; #1386 P5 konsumiert die hier niedrig-sensible Eingabequalität und gibt im Berichts-`dashboard.phase_decision` Intraday-Aktionsfelder und Qualitäts-Guardrail-Ergebnisse aus.

Der Statusvertrag fügt `fetch_failed` hinzu, das „der Abruf des aktuellen Felds oder Datenblocks ist in diesem Durchlauf eindeutig fehlgeschlagen" bedeutet. Die Erstversion verwendet es nur bei eindeutigem Fehlschlag eines bestehenden Artefakts, z. B. `fundamental_context.status == "failed"`; leere Nachrichten, nicht konfigurierte Suche, fehlendes realtime-quote-artifact oder fehlende Chip-Verteilung behalten die bestehende `missing` / `not_supported`-Semantik, damit nicht aktivierte Fähigkeiten nicht fälschlich als Abruffehler gemeldet werden. `fetch_failed` bedeutet nicht, dass die gesamte Analyse fehlgeschlagen ist.

`DataQuality` ergänzt folgende niedrig-sensible Felder und behält die alten `warnings` / `metadata`:

- `overall_score: Optional[int]`: Gesamtpunktzahl 0-100.
- `level: Optional["good"|"usable"|"limited"|"poor"]`: `>=85 good`, `>=70 usable`, `>=55 limited`, sonst `poor`.
- `block_scores: Dict[str, int]`: Statuspunktzahlen der festen sechs Blöcke.
- `limitations: List[str]`: maximal 5 stabile Begrenzungshinweise in der Form `block: status`.

Die Bewertung berechnet nur die festen sechs Blöcke und wird durch das Fehlen von Hilfsblöcken nicht neu normalisiert; zukünftige neue Blöcke beeinflussen die Gesamtpunktzahl nicht automatisch. Die Gewichte sind fest `quote=25`, `daily_bars=25`, `technical=25`, `news=10`, `fundamentals=10`, `chip=5`; die Statuspunktzahlen sind fest `available=100`, `partial=75`, `estimated=75`, `not_supported=70`, `fallback=65`, `stale=50`, `missing=35`, `fetch_failed=25`. Die Gesamtpunktzahl lautet `round(sum(block_score * weight) / 100)`.

`limitations` listet bevorzugt `stale`, `fallback`, `missing`, `fetch_failed`, `partial`, `estimated` der Kernblöcke `quote` / `daily_bars` / `technical`; danach `fetch_failed`, `fallback`, `stale` der Hilfsblöcke `news` / `fundamentals` / `chip`. Das bloße Fehlen eines Hilfsblocks geht nicht in die Begrenzungsliste ein, damit Nachrichtenmangel, nicht konfigurierte Suche oder nicht unterstützte Fähigkeiten nicht als positiv/negativ interpretiert werden.

Die Prompt-Datenbegrenzung wird nur innerhalb von `format_analysis_context_pack_prompt_section()` gerendert, direkt nach der pack-summary; damit nutzen normale Analyse, single Agent und multi-agent denselben Konsumpfad. In chinesischer Ausgabe `数据限制`, in englischer Ausgabe `Data Limitations`; die Bewertungszeile wird nur ausgegeben, wenn eine echte score existiert. Ist `quote`, `daily_bars` oder `technical` in degradiertem Status, verlangt der Prompt ausdrücklich, dass `confidence_level` des finalen JSON nicht `高` / `High` sein darf. Der Prompt verwendet weiterhin nur status/source/warnings/missing_reason/niedrig-sensible Bewertung und gibt kein raw-payload, keinen Nachrichtentext, keine rohen Trendwerte, keine secrets, keine tokens und kein webhook aus.

#1386 P2-full fügt nach P5-score/limitations und vor confidence/safety eine minimale Kreuzbedingung `phase × degraded data` hinzu: Wenn `AnalysisContextPack.phase` aus einem gültigen `MarketPhaseContext` stammt und `quote`, `daily_bars` oder `technical` einen degradierten Status aufweisen, ergänzt der Prompt nur, wie die Datenqualität in der aktuellen Phase die Intraday-Beurteilung, den Eröffnungsplan oder die konservative Analyse einschränkt; er ersetzt nicht die P5-confidence/safety-Regeln und wiederholt auch nicht den phase-only-Text von `market_phase_context`. Fehlt `pack.phase`, ist es kein dict oder enthält eine ungültige phase, erfolgt fail-open und es bleibt nur die allgemeine P5-Datenbegrenzung.

Die overview erweitert nur die bestehende öffentliche Fläche: Die Whitelist von `analysis_context_pack_overview.data_quality` umfasst `overall_score`, `level`, `block_scores`, `limitations`, ohne `warnings` erneut öffentlich zu machen. `render_analysis_context_pack_overview()` sowie `extract_analysis_context_pack_overview()` / der persistierte sanitizer bereinigen dieses Objekt; alte overviews ohne `data_quality` werden weiterhin normal gelesen. `details.context_snapshot` entfernt weiterhin die top-level `analysis_context_pack_overview` und macht das vollständige pack nicht öffentlich.

## P6 Kopplung von Alarm, Position, Historie und Backtest

#1386 P6 fügt keine neue pack-Version hinzu und macht das vollständige pack auch nicht auf weiteren öffentlichen Flächen sichtbar. Es nutzt nur die in P4/P5 definierte `analysis_context_pack_overview` und das in #1386 definierte `market_phase_summary`:

- Alarmauslösungs-Datensätze werden weiterhin in das bestehende Textfeld `alert_triggers.diagnostics` geschrieben; wenn die diagnostics JSON-fähig sind, führt der worker `analysis_visibility.analysis_context_pack_overview` zusammen, wobei die Quelle nur eine mitgelieferte overview des evaluator oder ein historischer Snapshot der letzten 30 Tage sein darf. Alte reine Text-diagnostics werden nicht überschrieben; das abgeleitete API-Feld ist leer und die source ist `legacy_text`.
- Die manuelle Positionsanalyse erstellt über die API einen niedrig-sensiblen `portfolio_context` und übergibt ihn an die Pipeline; der builder fügt dem pack einen optionalen `portfolio`-Block hinzu. Dieser Block enthält nur Konten-ID/Name, symbol, market, currency, quantity, avg cost, total cost, unrealisierter PnL, price source/provider/date/stale/available und cost method; keine Transaktionsströme, Kassenströme, Nachrichtentexte, Prompts, Schlüssel oder webhooks.
- Der `portfolio`-Block ist ein Hilfsblock mit `metadata={"auxiliary": true, "quality_weighted": false}`; er ändert weder Gewichte, Gesamtpunktzahl noch limitations-Linie der festen sechs P5-Blöcke `quote`, `daily_bars`, `technical`, `news`, `fundamentals`, `chip`.
- `portfolio_context` wird nur innerhalb der Aufgabenausführung durchgereicht; `TaskInfo.to_dict()`, die Taskliste und die SSE-Payloads `task_created/task_started/task_completed/task_failed/task_progress` setzen dieses Objekt nicht aus.
- Historie-Liste, Einzelaktien-Historie, StockBar und Backtest-Ergebnisse lesen nur das öffentliche `market_phase_summary` auf der obersten Ebene des `context_snapshot`; alte Datensätze, `SAVE_CONTEXT_SNAPSHOT=false` oder Parsing-Fehler geben `null` / `unknown` zurück, ohne zu scheitern.
- Der Backtest-Phase-Filter bucketed nur anhand der öffentlichen summary: `premarket` bleibt premarket, `intraday|lunch_break|closing_auction` wird intraday zugeordnet, `postmarket` bleibt postmarket, `non_trading|missing|invalid` wird unknown zugeordnet. Bei aktivem Phase-Filter liest das repository zuerst Ergebnisse und snapshots in Stapeln nach SQL-Bedingungen; die Service-Ebene bucketed und paginiert anschließend und berechnet Statistiken, um eine temporäre Filterung nach der API-Pagination zu vermeiden.
- Die Benachrichtigungszusammenfassung konsumiert nur `market_phase_summary` und `analysis_context_pack_overview.data_quality` und gibt Phase, trigger source, partial-bar-warning, Qualitätsstufe und die ersten beiden limitations aus; kein raw-pack, keine `analysis_context_pack_summary`-Prompt-Zeichenkette, keine Nachrichtentexte und keine sensiblen Positionsdetails.

## P6 Dokumentation, Migration und Rollback

P6 ändert das Laufzeitverhalten von P1-P5 nicht; es schreibt nur die bereits umgesetzten Vertrags-, Sichtbarkeits-, Konfigurations-, Migrations- und Rollback-Grenzen als stabile Dokumentation. Es fügt kein pack-enable/disable-feature-flag hinzu, erhöht `PACK_VERSION = "1.0"` nicht, fügt keine API-Parameter hinzu, ändert das Berichts-JSON-Schema nicht und führt keine Datenbankmigration durch.

Die vier Datengebenen müssen getrennt verstanden werden:

| Datengebene | Ort | Sichtbarkeit | P6-Grenze |
| --- | --- | --- | --- |
| Internes vollständiges pack | Produkt von `AnalysisContextPack` / `AnalysisContextBuilder` | Nur interne Laufzeitnutzung | Keine öffentliche API, nicht in die Historie schreiben, kein extern stabiles wire-contract zusagen. |
| Niedrig-sensible LLM-Zusammenfassung | `analysis_context_pack_summary` | Normale Analyse, single Agent, multi-agent Prompt | Enthält nur subject, pack version, block status/source/warnings/missing reason, Nachrichtenergebnisanzahl und Datenbegrenzung; keine `items.value`, keine Nachrichtentexte, keine raw-payloads von Trend/Chip/Fundamentaldaten, keine secrets, tokens oder webhooks. |
| Öffentliche niedrig-sensible overview | `report.details.analysis_context_pack_overview` | Historie-Detailansicht, synchrone Analyse-Antwort, completed task status, Web-Reportseite | Gibt nur Whitelist-Felder und die niedrig-sensible `data_quality`-Bewertung aus; kein vollständiges pack, keine prompt-summary, kein raw-payload. |
| Historischer Kontext-Snapshot | `analysis_history.context_snapshot` | Nach Persistenz für Historie/API/Web/Diagnose lesbar | `details.context_snapshot` entfernt über `sanitize_context_snapshot_for_api()` `analysis_context_pack_overview` und `market_phase_summary`, damit das raw-Panel die stabile Zusammenfassung nicht doppelt öffentlich macht. |

Sichtbarkeitsmatrix der Zusammenfassung:

| Konsumfläche | Ausgesetzter Inhalt | Nicht ausgesetzter Inhalt |
| --- | --- | --- |
| LLM-Prompt | Niedrig-sensible Statuszusammenfassung und Datenbegrenzung von `analysis_context_pack_summary` | Vollständiges pack, `items.value`, Nachrichtentexte, raw-payloads von Trend/Chip/Fundamentaldaten, secret/token/webhook |
| `GET /api/v1/history/{record_id}` | `report.details.analysis_context_pack_overview` | Vollständiges pack, prompt-summary, rohes `analysis_context_pack_overview`-Duplikat |
| Synchrone `POST /api/v1/analysis/analyze` | `report.details.analysis_context_pack_overview`, sofern `analysis_history.context_snapshot` dieses Durchlaufs bereits persistiert ist | Vollständiges pack, prompt-summary |
| completed `GET /api/v1/analysis/status/{task_id}` | `status.result.report.details.analysis_context_pack_overview` | Vollständiges pack, prompt-summary |
| Web-Reportseite | Standardmäßig eingeklapptes `AnalysisContextSummary` mit block-Status, Quelle, Warnung, Erklärung inkl. Auswirkung/Empfehlung/Diagnosecode, Qualitätspunktzahl und Begrenzung | Vollständiges pack, raw-payload, prompt-summary, Status der separat geladenen Nachrichteninformationen der Berichtsseite |
| rohes `details.context_snapshot` | Bereinigter historischer Snapshot | Top-level `analysis_context_pack_overview`, `market_phase_summary` |
| Benachrichtigungs-, Bot-, Desktop-spezifische Anzeige | P6 fügt keine spezifische Anzeige hinzu | Vollständiges pack, prompt-summary, raw-payload |

Der vollständige Satz der Feldqualitätsstatus bleibt `available`, `missing`, `not_supported`, `fallback`, `stale`, `estimated`, `partial`, `fetch_failed`. Diese Status erklären die Qualität der Eingabedaten; sie drücken nicht aus, ob die Analysenaufgabe, der Alarm, der Backtest oder die Benachrichtigungszustellung selbst erfolgreich oder fehlgeschlagen ist.

Redaktionsgrenzen:

- Das vollständige `AnalysisContextPack` geht nicht in die öffentliche API, Web, Benachrichtigungen, Bot oder Desktop-spezifische Anzeigen.
- `AnalysisContextPack.to_safe_dict()` dient nur als interne sichere Serialisierungs-Hilfsfunktion; die öffentliche overview muss weiterhin über `render_analysis_context_pack_overview()` projiziert werden.
- `analysis_context_pack_summary` und overview dürfen keine `items.value`, keine Nachrichtentexte, keine raw-payloads von `trend_result`, `chip`, `fundamental_context`, keinen API-Key, kein token, kein cookie, keine vollständige webhook-URL, kein E-Mail-Passwort, kein secret, keine authorization, keinen sendkey und keinen license key ausgeben.
- Eine bereits persistierte overview muss beim erneuten Lesen über `extract_analysis_context_pack_overview()` / den persistierten sanitizer laufen; das API-Transparenzpanel muss die top-level stabile Zusammenfassung weiterhin über `sanitize_context_snapshot_for_api()` entfernen.

Migrationsgrenzen:

- P6 führt keine DB-Migration durch; alte Verlaufsdatensätze ohne `analysis_context_pack_overview` oder `data_quality` geben leere Felder zurück und der Bericht wird weiterhin normal gelesen.
- `SAVE_CONTEXT_SNAPSHOT=true` ist das Standardverhalten und persistiert `analysis_history.context_snapshot` weiterhin als Quelle für Historie-Transparenz und Diagnose.
- `SAVE_CONTEXT_SNAPSHOT=false` oder CLI `--no-context-snapshot` stoppt die Persistierung der gesamten `analysis_history.context_snapshot`; mit anderen Worten, neue Historie persistiert die gesamte `analysis_history.context_snapshot` nicht mehr, einschließlich `enhanced_context`, `market_phase_summary`, `analysis_context_pack_overview`, `diagnostics`, `realtime_quote_raw` und anderer raw-snapshot-Felder.
- Das Deaktivieren der Persistierung beeinflusst weder die Erstellung des `AnalysisContextPack` dieses Durchlaufs noch die Injektion von `analysis_context_pack_summary` in den Prompt noch das In-Memory-`result.diagnostic_context_snapshot`.

Rollback-Möglichkeiten:

| Mittel | Wirkung | Was es nicht kann |
| --- | --- | --- |
| Release- oder Code-Rollback der P3-P5-bezogenen Änderungen | Entfernt pack-prompt-summary, overview und Datenqualitäts-Anbindung | - |
| `SAVE_CONTEXT_SNAPSHOT=false` oder `--no-context-snapshot` | Stoppt das Speichern neuer historischer `context_snapshot`, sodass aus neuer Historie keine overview / phase summary / raw snapshot mehr öffentlich werden | Kann die pack-Erstellung dieses Durchlaufs oder die niedrig-sensible summary im LLM-Prompt nicht deaktivieren |
| Laufzeit-Hauptschalter des packs | Existiert derzeit nicht | Kann die P3-P5-pack-Anbindung nicht per env mit einem Klick deaktivieren; Code-Rollback oder eine spätere separate Konzeption erforderlich |

## Feldqualitätsstatus

Die Feldqualitätsstatus des zukünftigen packs werden in P0 zunächst auf sieben Wörter fixiert; P5 ergänzt `fetch_failed` innerhalb desselben 1.0-umbrella. Sie beschreiben die Qualität eines Felds oder Datenblocks, nicht ob ein Geschäftsablauf erfolgreich war.

| Status | Bedeutung | Beispielgrenze |
| --- | --- | --- |
| `available` | Das Feld existiert, Quelle und Zeitstempel sind erklärbar und der aktuelle Pfad kann es normal verwenden. | Echtzeitkurse geben Preis und Quelle zurück; das historische K-Linien-Fenster erfüllt die Berechnungsanforderungen. |
| `missing` | Der aktuelle Pfad benötigt das Feld, hat es aber tatsächlich nicht erhalten oder es ist leer. | DB hat keine letzten Tagesbalken; die normale Analyse geht in das `data_missing`-Ergebnis. |
| `not_supported` | Der aktuelle Markt, die Datenquelle oder der Pfad unterstützt das Feld nicht; dies sollte nicht fälschlich als Fehler gemeldet werden. | Manche Märkte haben keine Chip-Verteilung oder keinen Kapitalfluss. |
| `fallback` | Die bevorzugte Quelle ist nicht verfügbar; es wurde eine Ersatzquelle oder ein alter Pfad verwendet. | Positionspreis fällt von Echtzeitkurs auf historischen Schlusskurs zurück. |
| `stale` | Das Feld existiert, aber die Zeitfrische ist unzureichend. | `price_stale` / `fx_stale` in der Positionsbewertung. |
| `estimated` | Das Feld ist ein Schätzwert und sollte nicht als vollständige Tatsache behandelt werden. | Intraday-Tagesbalken mit Echtzeitpreis ergänzt, dann technische Schätzung erzeugt. |
| `partial` | Der Datenblock ist teils verfügbar, teils fehlend. | Ampel `data_quality=partial` oder Tool liefert `partial_cache`. |
| `fetch_failed` | Der aktuelle Pfad hat den Abruf nachweislich versucht, aber dieser Abruf ist fehlgeschlagen. | `fundamental_context.status == "failed"` wird als fehlgeschlagener Abruf des Fundamentaldaten-Blocks abgebildet. |

## Bestehende Statuszuordnung

Das aktuelle Repository enthält bereits mehrere Statuswörter. P0 stellt nur Zuordnungen oder Nicht-Zuordnungen her, um zu vermeiden, dass Geschäftsergebnisstatus später in das Feldqualitäts-Enum gemischt werden.

| Bestehendes Wort oder Feld | Aktueller Ort | Empfohlene Beziehung | Erläuterung |
| --- | --- | --- | --- |
| `data_missing` | Fehlendes Historiedaten-Ergebnis der normalen Analyse | auf `missing` abbildbar | Dies ist ein fehlender Kernerfassungs-Input, kein Geschäftserfolgsstatus. |
| `cache_hit` / `partial_cache` | Agent-Historiedaten-Tool | `partial_cache` auf `partial` abbildbar | `cache_hit` ist Quellen-/Cache-Metadaten, kein Qualitätsstatus. |
| `source` / `data_source` / `realtime_source` | Datenquelle, Alarm, Kontext-Snapshot | nicht abbilden | Dies sind Quellen-Metadaten und sollten parallel zu den Feldqualitätsstatus gespeichert werden. |
| `price_source=missing` | Positions-Snapshot | auf `missing` abbildbar | Zeigt an, dass der Bewertungspreis nicht verfügbar ist. |
| `price_stale` / `fx_stale` | Positions-Snapshot | auf `stale` abbildbar | Originalfeld als Geschäfts-Metadaten behalten. |
| `triggered` / `skipped` / `degraded` / `failed` | Alarm-Bewertung und -Datensatz | nicht abbilden | Dies ist das Ergebnis der Regelbewertung oder des Datensatzes, kein feldebener Qualitätsstatus. |
| `insufficient_data` / `completed` / `error` | Backtest-Dienst | nicht abbilden | Dies ist der Ausführungsstatus des Backtests; kann in der pack-Zusammenfassung zur Erklärung des Auslösegrunds dienen. |
| `sent` / `no_channel` / `partial_failed` / `all_failed` | Benachrichtigungsversand | nicht abbilden | Dies ist das Zustellungsergebnis der Benachrichtigung und kann nicht auf die Eingabequalität der Analyse zurückgerechnet werden. |
| `data_quality=ok/partial/unavailable` | Ampel | `partial` abbildbar, `unavailable` je nach Feldszenario auf `missing` oder `not_supported` abbildbar | P0 nimmt die Ampel nicht in das Erstversion-Einzelaktien-pack auf. |
| `fetch_failed` | Datenqualitäts-Unterteilung | von P5 auf `fetch_failed` abgebildet | Nur bei eindeutigem Fehlschlag eines bestehenden Artefakts verwenden; bedeutet nicht, dass die gesamte Analyse fehlgeschlagen ist. |

## Sieben-Pfade-Bestandsaufnahme

### Normale Analyse

Die Hauptkette der normalen Analyse assembliert die Eingaben in `src/core/pipeline.py`: zuerst `storage.get_analysis_context()` lesen, dann je nach Verfügbarkeit Echtzeitkurse, Chip-Verteilung, Trendanalyse, Nachrichten, Fundamentaldaten und Berichtssprache ergänzen und schließlich an `src/analyzer.py` zur Prompt-Renderung übergeben. Die aktuellen Dopplungen betreffen hauptsächlich Echtzeit-Felder, die gleichzeitig in `enhanced_context.realtime`, `realtime_quote_raw` und report-meta existieren; bei den Namen gibt es mehrere Quellenfelder wie `source`, `data_source`, `realtime_source`.

Das Erstversion-pack kann aus dem normalen Analysepfad die Kernidentität der Einzelaktie, Kurse, Tagesbalken, Technik, Nachrichten, Fundamentaldaten und die Datenqualitäts-Zusammenfassung extrahieren; P0 ändert weder `_enhance_context()`, `_build_context_snapshot()` noch den analyzer-Prompt.

### Agent

Der Agent hat drei Datengebenen, die getrennt dokumentiert werden müssen. Der Agent-Pfad in `src/core/pipeline.py` erstellt `initial_context`, das fest `fundamental_context` enthält und bei Verfügbarkeit `trend_result` ergänzt und schließlich als `context_snapshot` des Agent-Pfads persistiert. `AgentExecutor._build_user_message()` gilt nur für `AGENT_ARCH=single` und injiziert in der ersten Nachricht nur explizit bereits erhaltene Kontexte wie `realtime_quote`, `chip_distribution`, `news_context`, nicht explizit `fundamental_context` oder `trend_result`. `AgentOrchestrator._build_context()` gilt für `AGENT_ARCH=multi` und kann `realtime_quote`, `daily_history`, `chip_distribution`, `trend_result`, `news_context` vorab injizieren; diese Felder, die in `AgentContext` gelangen, werden als pre-fetched data in die stage-agent-Nachrichten injiziert; der Orchestrator injiziert jedoch `fundamental_context` nicht vorab. `trend_result` existiert nicht von Natur aus, sondern hängt davon ab, ob der Caller es übergibt.

Agent-Tools rufen außerdem eigenständig Tools wie `get_realtime_quote`, `get_daily_history`, `get_chip_distribution`, `get_analysis_context`, `get_stock_info` auf, was leicht zu doppelten Anfragen mit dem Vorabruf der normalen Analyse führt. Die aktuelle pack-Erzeugung nutzt nach dem Vorabruf der Agent-Historie nur den Tagesbalken-Verfügbarkeitsstatus aus `storage.get_analysis_context()` wieder und nutzt bzw. setzt keinen vollständigen pack-cache auf Tool-Ebene aus; P5 entscheidet später, ob eine tiefere Datenqualitäts-Bewertung und Tool-Cache-Wiederverwendung erfolgt.

### Alarm

Die Alarmkette bewertet in `src/services/alert_worker.py` die Regeln, protokolliert die Auslösungshistorie und verteilt Benachrichtigungen; die konkrete Feldsemantik siehe [Echtzeit-Alarmzentrum](alerts.md). Alarmstatus wie `triggered`, `skipped`, `degraded`, `failed` sind Zustände der Regelbewertung oder des Datensatzes und können nicht direkt in das Feldqualitäts-Enum geschrieben werden.

Das Erstversion-pack nimmt die Alarmregel-Bewertung nicht als Eingabedatenblock auf; Alarme konsumieren später nur die Feldqualitäts-Zusammenfassung des packs, z. B. ob der Kernkurs gefallback, stale oder partial ist.

### Position

Der Positions-Snapshot aggregiert in `src/services/portfolio_service.py` Konto, Positionen, Kosten, Preise, Wechselkurse und Risikoeingaben; die API-Ausgabestruktur liegt in `api/v1/schemas/portfolio.py`. Es gibt bereits Felder wie `price_source`, `price_provider`, `price_date`, `price_stale`, `price_available`, `fx_stale`.

Das Erstversion-pack kann „ob Position gehalten, Kontozusammenfassung, Kosten, Menge, Positionsgröße, unrealisierter Gewinn/Verlust, stale-Zusammenfassung von Preis/Wechselkurs" erfassen, bezieht aber keine Transaktionsströme, Kassenströme, Unternehmensmaßnahmen oder vollständige Kontoprivatsphäre-Daten ein.

### Backtest

Der Backtest-Dienst konsumiert in `src/services/backtest_service.py` und `src/repositories/backtest_repo.py` historische Analyse-Datensätze und Tagesbalken-Daten. Das bestehende `parse_analysis_date_from_snapshot()` ist zur Auflösung des Analysedatums von `analysis_history.context_snapshot.enhanced_context.date` abhängig.

P0 muss `enhanced_context.date` als Kompatibilitätsgrenze markieren. Das spätere pack kann ein klareres Datumsfeld hinzufügen, darf aber die Datumsstelle des aktuellen historischen Snapshot ohne Migration nicht löschen oder umbenennen.

### Historie

Die Historie-Detailansicht gibt in `src/services/history_service.py`, `api/v1/endpoints/history.py`, `api/v1/schemas/history.py` Felder wie `raw_result`, `news_content`, `context_snapshot` zurück. Synchrone analysis/status-Antworten lesen in `api/v1/endpoints/analysis.py` ebenfalls `context_snapshot.enhanced_context`, `realtime_quote_raw` und den Fundamentaldaten-Fallback.

P0 dokumentiert nur die Historie-Konsumfläche. Das vollständige pack sollte nicht standardmäßig in der Historie-Detailansicht oder der öffentlichen API sichtbar sein; falls P4 später etwas anzeigen möchte, sollten Zusammenfassung, Quelle und Degradationserklärung bevorzugt ausgesetzt werden.

### Benachrichtigung

Die Benachrichtigungskette konsumiert in `src/notification.py` Ausgaben wie `AnalysisResult`, dashboard, market snapshot, data_sources und protokolliert Zustellstatus wie `sent`, `no_channel`, `partial_failed`, `all_failed`; Kanal-Konfiguration und Grenzen siehe [Benachrichtigungsfähigkeits-Baseline](notifications.md).

Benachrichtigungen sind keine Faktdaten-Ebene; ein Zustellfehler darf nicht fälschlich als Eingabequalitätsfehler geschrieben werden. Nachgelagert sollte die pack-Zusammenfassung nur bei Bedarf konsumiert werden, z. B. „Echtzeitkurse degradiert", „Fundamentaldaten fehlen", „Nachrichtenquelle unzureichend".

## Quellcode-Anker

| Domäne | Anker |
| --- | --- |
| Normale Analyse | `src/core/pipeline.py`, `src/storage.py`, `src/analyzer.py` |
| Agent | `src/agent/orchestrator.py`, `src/agent/executor.py`, `src/agent/tools/data_tools.py` |
| Alarm | `src/services/alert_worker.py`, `docs/alerts.md` |
| Position | `src/services/portfolio_service.py`, `api/v1/schemas/portfolio.py` |
| Backtest | `src/services/backtest_service.py`, `src/repositories/backtest_repo.py` |
| Historie | `src/services/history_service.py`, `api/v1/endpoints/history.py`, `api/v1/endpoints/analysis.py`, `api/v1/schemas/history.py` |
| Benachrichtigung | `src/notification.py`, `docs/notifications.md` |

## Kompatibilitäts- und Sicherheitsgrenzen

- `analysis_history.context_snapshot.enhanced_context.date` ist der aktuelle Kompatibilitätspunkt der Backtest-Datumsauflösung; P1/P2 dürfen ihn ohne Migration nicht brechen.
- Das vollständige pack wird nicht standardmäßig für Historie, API, Web oder Benachrichtigungen öffentlich; P4/P5 setzen nur die niedrig-sensible Zusammenfassung `analysis_context_pack_overview`, Quelle, fallback, stale, missing reason, block-status-Zählung und die niedrig-sensible `data_quality`-Bewertung aus.
- pack, Protokolle, historische Snapshots und API-Antworten dürfen keine API-Key, tokens, cookies, vollständige webhook-URLs, E-Mail-Passwörter, private Umgebungsvariablen oder andere Schlüssel aufzeichnen.
- Qualitäts-Metadaten wie `source`, `timestamp`, `fallback`, `stale`, `partial` dienen nur zur Erklärung der Eingabebeschränkungen, nicht zum Blockieren der Analyse; es sei denn, der bestehende Kernpfad war von Natur aus fail-fast.
- Die premarket / intraday-Phasenwahrnehmung von #1386 ist ein wichtiger Hintergrund für die späteren Felder `phase` / `data_quality`; P0 dokumentiert nur die Beziehung und bindet kein runtime an.
