# Multi-Strategie-Anlageempfehlung: Baseline-Semantik, Phase-1-Konvergenz, Phase-2/3/4-Grenzen

Diese Seite ist das Themendokument für Issue #1964 „Multi-Strategie-Anlageempfehlung" und dokumentiert die **semantischen Konvergenzgrenzen** der Systemeinschätzungen von 2 oder mehr Strategien/Skills (Fähigkeiten): die Menge gültiger Nachweise, die Isolierung ungültiger Einschätzungen, die Lagergruppierung, der Konsensgrad und die Konsistenz über die Verbraucherflächen hinweg. Die Baseline ist für die Vertragsgrenzen und die Bestandsaufnahme des Ist-Zustands verantwortlich; Phase 1 erledigt nur innerhalb des Baseline-Vertrags die Sortierung der gültigen Nachweis-Menge, die deterministische Synthese von `strategy_synthesis`, die Konvergenz des DecisionAgent-Prompts, die Konsistenz der vier Renderer sowie die E2E-Gegenbeispiel-Abdeckung; Phase 1.5 erweitert den Phase-1-Vertrag um gesteuertes kollaboratives Reasoning v0 (`mediator_v0`), das nur Konfliktthemen, Strategieantworten, softened Korrekturen und Gründe für Konfidenzreduktionen erfasst; Phase 1.6 erweitert um einen injizierbaren LLM-Mediator v1 (`llm_mediator_v1`), der nur schema-konforme strukturierte Revisionen zulässt und bei fehlender, anomaler oder außerhalb des Bereichs liegender Ausgabe auf v0 zurückfällt; Phase 1.7 erweitert um ein injizierbares Strategie-Self-Review v2 (`self_review_v2`), das nur konfliktbeteiligten Strategien erlaubt, nach festem Schema zu prüfen, und bei Überschreitung durch einen Teilnehmer die gesamte Runde auf die Baseline zurückfallen lässt; Phase 1.8 erweitert um eine Revisionsprojektion v3 (`revision_projection`), die nur das synthetisierte Signal, die Konfidenz und den Konfliktstatus nach Annahme der softened Revisionen als Vorschau zeigt, ohne das autoritative `final_signal` zu überschreiben; Phase 1.9 erweitert um konfigurierbares mehrrundiges kollaboratives Reasoning v4 (`multi_round_v4`), das gemäß `max_rounds` strukturierte Revisionen fortsetzt und `round_history` beibehält; überschreitet eine Runde die Grenzen, kehrt es zum zuvor verifizierten Ergebnis der vorherigen Runde zurück; Phase 2 fügt nur unter dem Vertrag von Phase 1/1.5/1.6/1.7/1.8/1.9 parallele und gestaffelte Planung für 2–4 Strategien hinzu; Phase 3 ergänzt nur auf Basis von Phase 2 die vollständige mehrsprachige Darstellung im Frontend; Phase 4 ergänzt nur innerhalb desselben `CONTRACT_VERSION = "1.0"` den echten Skill-Outcome-Gewichts-Feedback-Kreislauf. Alle Einschränkungen der Baseline gelten dauerhaft für alle nachfolgenden Phasen; Phase N darf die in der Baseline bereits fixierten Grenzen nicht stillschweigend herabsetzen.

## Skill-Opinion-Stichprobengrenzen (Issue #1904 P2 PR1)

`AgentRuntimeFacts.skill_opinions` projiziert nur die niedervertraulichen Felder der einzelnen SkillAgents: `skill_id`, das kanonische `signal`, `confidence` und den Zeitpunkt der Opinion. `skill_consensus` / `strategy_consensus`, der DecisionAgent, Basis-Agents sowie Invalid Opinions dürfen nicht in diese Menge gelangen; erscheinen in derselben Ausführung mehrere gültige Einschätzungen derselben `skill_id`, wird nur die letzte beibehalten. Beim ersten Parsen muss der SkillAgent eine Confidence ablehnen, die nicht numerisch, nicht endlich oder außerhalb von `[0, 1]` liegt; `AgentOpinion` behält die Eingabe-Gültigkeitsmarkierung für die defensive Prüfung der RuntimeFacts bei; es ist verboten, ungültige Eingaben zu clampen und als gültige Stichprobe weiterzuverwenden.

Nach erfolgreichem Speichern des Analyseverlaufs schreibt die Pipeline das Sidecar `skill_opinion_samples` im Best-Effort-Verfahren. Die Prüfung der Existenz des Elternverlaufs und das Einfügen der Stichprobe müssen in demselben atomaren SQLite-Schreibvorgang erfolgen; das Löschen des Verlaufs nutzt denselben Schreibvorgang mit locked retry; unabhängig davon, ob das Einfügen oder das Löschen zuerst erfolgt, dürfen keine verwaisten Stichproben zurückbleiben. Der Idempotenzschlüssel ist `(analysis_history_id, skill_id, sample_schema_version)`; eine wiederholte Ausführung darf die erstmals gespeicherte unveränderliche Stichprobe nicht überschreiben. Fehler beim Schreiben protokollieren nur den niedervertraulichen Fehlertyp und dürfen weder den Bericht, noch den Verlauf, noch den DecisionSignal-Hauptfluss zum Scheitern bringen.

Derzeit gilt `sample_schema_version=skill-opinion-sample-v1`. `skill_version` und `horizon` bleiben nur als leere Kompatibilitätsbits erhalten: Die bestehenden Skill-Definitionen und SkillAgent-Ausgaben haben keinen vertrauenswürdigen Versions- und Periodenvertrag, daher dürfen sie in dieser Phase weder aus den LLM-`raw_data` erraten noch gefälscht werden. PR1 erstellt keine Outcomes, bietet keine Skill-Leistungsstatistiken, implementiert kein `get_skill_summary()` und ändert auch die Gewichte von `AgentMemory` / `SkillAggregator` nicht.

## Skill-Opinion-Outcome-Grenzen (Issue #1904 P2)

`skill_opinion_outcomes` stellt eine unveränderliche `skill_opinion_sample` unter einem `horizon` und einer `engine_version` als eigenständiges Posterior-Ergebnis dar; der eindeutige Schlüssel ist `(skill_opinion_sample_id, horizon, engine_version)`. Die anfänglichen Horizons erlauben nur `1d`, `3d`, `5d`, `10d`; das `limit` jeder Ausführung begrenzt die Anzahl der zu verarbeitenden `sample × horizon`-Outcome-Schlüssel, nicht die Anzahl der Stichproben. Explizit leere Horizons, leere Skill-/Aktienfilter und ein außerhalb des Bereichs liegendes `limit` müssen fail closed und dürfen nicht zu einem vollständigen Lauf degenerieren.

Jedes Outcome verwendet ausschließlich das eigene kanonische `signal` der Stichprobe; es darf weder die finale Agent-Entscheidung noch `skill_consensus` noch die Signale anderer Skills lesen. `strong_buy` / `buy` werden als bullish bewertet, `strong_sell` / `sell` als bearish; nur eine strikt positive Richtungsrendite ist ein `hit`, eine Nullrendite ist ein `miss`. `hold` wird nach vollständigem Preisfenster als `observational` gespeichert und erzeugt keine Richtungskorrektheit.

Das historische Analysedatum stammt aus `enhanced_context.date` und fällt erst bei Fehlen auf das Erstellungsdatum des Verlaufs zurück. Backtest und Outcome teilen sich die Auflösung der Aktienidentität, den Wiederaufbau unterstützter alter Marktsnapshots und die Bestimmung der autoritativen Startsitzung: Bevorzugt wird ein marktkonsistentes und gültiges `market_phase_summary.effective_daily_bar_date` verwendet; fehlt dieses Feld, wird nur abgeleitet, wenn Phase und Handelskalender den Startpunkt belegen können, andernfalls fail closed — es darf kein beliebig früherer lokaler Tagesbalken gewählt werden. Outcome akzeptiert nur das geprüfte `expected_start_date`. Zur Kompatibilität mit bestehenden Verläufen darf der Backtest, wenn bereits ein exakter lokaler Balken zum nicht-Sitzungs-`effective_daily_bar_date` existiert, über ein explizites `backtest_start_date` schreibgeschützt abspielen; dieser Fallback gehört nicht zu den autoritativen Outcome-Stichproben, löst kein Refill ungültiger Daten aus und fließt nicht in die Skill-Outcome-Statistik oder die Gewichtskalibrierung ein. Der gemeinsame Fenster-Resolver bevorzugt bei einem angegebenen Startpunkt das vollständige Fenster, und Start- sowie Vorwärtsbalken müssen aus derselben gespeicherten Code-Form stammen; es darf nicht über Kandidaten hinweg zusammengefügt werden.

Wenn für ein Outcome die autoritative Startsitzung feststeht, der zugehörige Startbalken aber noch nicht geschrieben wurde oder zukünftige lokale Tagesbalken nicht ausreichen, wird es als wiederholbares `pending` gespeichert. Kandidatenschlüssel werden fair nach dem Zeitpunkt des letzten Versuchs geplant (bei fehlendem Outcome nach dem Erstellungszeitpunkt der Stichprobe); jeder erneute Versuch aktualisiert `pending.updated_at` und stellt ihn ans Ende der Warteschlange, damit kontinuierlich hinzukommende fehlende Schlüssel alte Wiederholungen nicht aushungern und Wiederholungen neue Stichproben nicht rückwärts blockieren. Ein beschädigtes oder nach dem Analysedatum liegendes `effective_daily_bar_date`, Konflikte zwischen Aktienmarkt und Snapshot-Markt sowie Startpunkte, die nicht durch vertrauenswürdige Phase und Handelskalender belegt werden können, werden als Endzustand `unable` gespeichert und dürfen nicht als `missing_start_bar` für dauerhafte Wiederholungen getarnt werden. Unter derselben Engine-Version ist nur `pending` aktualisierbar; `evaluated`, `observational` und `unable` sind nicht überschreibbar; Regeländerungen müssen die Engine-Version erhöhen. Das Löschen von Verläufen erfolgt in demselben Schreibvorgang explizit in der Reihenfolge outcome → sample → history und darf sich nicht auf den SQLite-Fremdschlüsselschalter verlassen.

Die Outcome-Kernphase (#2116) baut auf dem bereits zusammengeführten #2073 auf und liefert nur den Outcome-Evaluator, das Repository und den Service-Kern; Leistungsstatistiken, Stichproben-Suffizienz, Rangfolgen oder Gewichtsanpassungen waren damals nicht enthalten. Die darauf folgende schreibgeschützte Statistikphase wird im nächsten Abschnitt separat definiert; diese Phase fügt weiterhin weder eine Admin-API, Schema, OpenAPI noch eine automatische Auslösung der Haupt-Pipeline hinzu und passt auch keine Laufzeitgewichte an. Falls später ein Betriebszugang benötigt wird, sollte er anhand des tatsächlichen Aufrufers und des Berechtigungsvertrags unabhängig geprüft werden.

### Skill-Opinion-Outcome-Leistungsstatistik

Die Outcome-Statistik ist eine schreibgeschützte Datenfläche, die je `skill_id + horizon + engine_version` unabhängig in Buckets aufgeteilt wird. Kein Bucket darf Indikatoren anderer Horizons desselben Skills, anderer Skills, anderer Engine-Versionen oder globaler Stichproben ausleihen, um sie freizuschalten. Die derzeitige feste Schwelle ist `evaluated >= 30`; nur die durch das eigene Signal der einzelnen Skill-Opinion erzeugten `hit` / `miss` zählen in `evaluated`; `pending`, `observational` und `unable` behalten nur Zähler und fließen nicht in die Stichproben-Suffizienz ein.

Bei unzureichenden Stichproben ist der `sample_status` des Buckets `observational`; die Zähler werden weiterhin zurückgegeben, aber `hit_rate_pct`, `miss_rate_pct`, `avg_directional_return_pct` und `unable_rate_pct` sind alle `null`; es dürfen keine Rangfolgen ausgegeben oder Gewichte abgeleitet werden. Bei ausreichenden Stichproben wird die hit/miss-Rate mit `hit + miss` als Nenner berechnet, die durchschnittliche Richtungsrendite verwendet nur die evaluated-Zeilen; die unable-Rate verwendet als Nenner die Endzustandsaufzeichnungen `evaluated + observational + unable`; temporäres `pending` darf den Anteil dauerhafter Fehler nicht verwässern.

Die schreibgeschützte Statistikphase (PR #2119) modifiziert selbst weder `BacktestService.get_skill_summary()`, `AgentMemory` noch `SkillAggregator` und fügt weder eine API, noch eine automatische Pipeline-Auslösung, noch eine Web-Darstellung hinzu; Phase 4 weiter unten schließt auf Basis dieses Statistikvertrags unabhängig ein konservatives Laufzeitgewicht an. Die derzeitige kombinierte Implementierung konsumiert weiterhin schreibgeschützt die bereits persistierten Outcomes und übernimmt nicht die automatische Auslösung des Evaluators.

## Terminologie und Grenzen

Das aktuelle Repository enthält mehrere Datenflächen mit den Namen opinion / signal / consensus / synthesis; die Baseline muss diese zunächst disambiguieren, um zu vermeiden, dass bestehende Laufzeitstrukturen fälschlich als zukünftige Phasen beschrieben werden.

| Terminus | Aktuelle Bedeutung | Aktuelle Hauptkonsumenten | Baseline-Grenze |
| --- | --- | --- | --- |
| `AgentOpinion` | Die Opinion-Datenklasse, die von allen Agents in `src/agent/protocols.py` (einschließlich SkillAgent, TechnicalAgent, IntelAgent, RiskAgent, DecisionAgent) erzeugt wird, mit `agent_name` / `signal` / `confidence` / `reasoning` / `key_levels` / `raw_data`. | Orchestrator, Aggregator, DecisionAgent, Disagreement, Renderer | Als Träger der Roh-Opinions erfasst; die Baseline fügt keine Felder hinzu und spaltet `AgentOpinion` auch nicht in zwei Klassen auf. |
| `StrategyOpinion` | Die interne normalisierte Sicht in `src/agent/protocols.py`, mit `skill_id` / `signal` / `original_signal` / `invalid_signal`; nur innerhalb von Aggregator/Synthesizer verwendet. | `SkillAggregator`, `ConflictDetector`, `StrategySynthesizer` | Als interne normalisierte Sicht für Berechnungen erfasst; geht weder in `ctx.opinions` noch in öffentliche Payloads noch in den DecisionAgent-Prompt ein. |
| Signal / Kanonisches Signal | Normalisiertes Handelssignal-Label; die Canonical-Werte sind ausschließlich die fünf kleingeschriebenen Strings `strong_buy` / `buy` / `hold` / `sell` / `strong_sell`. | Gesamte Kette | Als einzige zulässige Eingabeform für alle nachgelagerten Berechnungen erfasst; Großschreibungs-Aliassee, `"strong buy"` und die Originalwerte des Signal-Enums müssen erst über `normalize_strategy_signal()` in canonical umgewandelt werden, bevor sie an Berechnungen teilnehmen. |
| Valid Opinion / Invalid Opinion | Eine Opinion mit `is_valid_strategy_signal(signal) == True`, die nicht mit `invalid_signal=True` markiert ist, gilt als Valid, der Rest als Invalid. | Orchestrator-Sortierung, Aggregator, DecisionAgent | Als gültige/ungültige Beurteilung der Vertragsschicht erfasst; die Baseline definiert nur die Beurteilungsfunktion und die Semantik, ohne den Sortierort vorzugeben. |
| Evidence Chain | Die **Menge gültiger Einschätzungen**, die in den DecisionAgent-Prompt und die numerischen Berechnungen von `strategy_synthesis` eingeht. | DecisionAgent, Aggregator | Als Entscheidungseingabe-Fläche erfasst; die Baseline legt fest, dass die Evidence Chain nur aus Valid Opinions besteht und Invalid nicht hineingemischt werden darf. |
| Diagnostics | Auffangposition für die Diagnose ungültiger Einschätzungen, nur für Protokolle, Debugging und die benutzersichtbare Zählung „weitere N Strategien konnten nicht verarbeitet werden". | Renderer-Anzeige, Protokolle | Als Diagnosefläche erfasst; die Baseline legt fest, dass Invalid in die Diagnostics gelangen muss und nicht stillschweigend in `hold` umgewandelt und in die Evidence Chain gemischt werden darf. |
| `strategy_synthesis` | Top-Level-Payload von `dashboard.strategy_synthesis`, mit `final_signal` / `consensus_level` / `conflict_severity` / `supporting_skills` / `opposing_skills` / `summary_params`. | Die vier Renderer Markdown, WeChat, Notification, History | Als öffentliche niedervertrauliche Payload erfasst; die Baseline legt fest, dass diese Payload die **einzige autoritative Synthesequelle** ist und das LLM-Dashboard sie nicht rückwärts überschreiben darf. |
| `disagreement_summary` | `ctx.meta["agent_disagreement_summary"]`, eine niedervertrauliche Zusammenfassung von Agent-Meinungsverschiedenheiten aus `build_agent_disagreement_summary()`. | DecisionAgent-Prompt, Protokolle | Als Hinweisfläche des Entscheidungspfads erfasst; die Baseline legt fest, dass nur aus Valid Opinions gebucktet wird und Invalid nicht in `bullish_agents` / `bearish_agents` / `neutral_agents` gelangen darf. |
| Konsensgrad | `strategy_synthesis.consensus_level`, Werte `high` / `medium` / `low` / `insufficient`. | Renderer-Anzeige, interne Beurteilung des Aggregators | Als Konsensgrad-Enum erfasst; die Baseline legt fest, dass bei ≤ 1 valid oder `sum(confidence) == 0` zwingend `insufficient` gilt und kein `high` ausgegeben werden darf. |

## Baseline-Umfang und Nicht-Ziele

Ziel der Baseline ist, dass Phase 1/2/3/4 alle Laufzeitänderungen auf Basis desselben semantischen Vertrags entwerfen, statt in jeder PR-Runde „gültige Einschätzung", „Konsens" und „Unterstützerseite" neu zu definieren.

- Die Baseline deckt die semantischen Konvergenzgrenzen der sieben Verbraucherflächen SkillAgent → Orchestrator → Aggregator → Synthesizer → DecisionAgent → Disagreement → Renderer ab.
- Die Baseline fixiert das Canonical-Signal-Enum, die Valid/Invalid-Beurteilungsfunktion, das Trennungsprinzip von Evidence Chain / Diagnostics, die dynamische Zweilager-Semantik, die Konsensschwellen-Stufung, das `strategy_synthesis`-Payload-Schema, die Invariantenliste und die Gegenbeispielmatrix; Phase 1 ist die erste codebasierte Umsetzung dieser Grenzen.
- Die Baseline führt keine parallele Planung, keine vollständige mehrsprachige Frontend-Anzeige und keine Gewichts-Backtest-Rückkopplung ein; diese bleiben Phase 2/3/4 vorbehalten.
- Die Baseline ändert weder bestehende `AgentOpinion`-Felder, noch fügt sie Datenbankfelder hinzu, noch ändert sie die API-Rückgabestruktur (`strategy_synthesis` wurde bereits in einer früheren PR hinzugefügt), noch fügt sie Konfigurationseinträge hinzu.
- Die Baseline erweitert den Vertrag nicht zu einem generischen Opinion-Registry; die `AgentOpinion`-Struktur wird vom bestehenden Code gepflegt, dieser Vertrag regelt nur ihren **semantischen Verarbeitungsablauf**.

## Interner Baseline-Vertrag

### Canonical Signal und Valid-Beurteilung

Das Canonical Signal ist die **einzige zulässige Bewertungs-/Gewichtungs-/Gruppierungseingabeform** der Baseline. Der Normalisierungseinstieg sind die zwei Funktionen in `src/agent/protocols.py`:

- `normalize_strategy_signal(signal)` gibt das Tupel `(canonical, invalid, original)` zurück. Es akzeptiert das `Signal`-Enum, Strings mit beliebiger Groß-/Kleinschreibung sowie die Aliassee `"strong buy"` / `"strong-buy"` und mappt sie einheitlich auf die canonical-Menge. Kann nicht gemappt werden, ist `invalid=True`, und `canonical` degeneriert zu `default` (standardmäßig `"hold"`), muss aber **zwingend** zusammen mit `invalid=True` an die nachgelagerten Komponenten durchgereicht werden und darf nicht allein verwendet werden.
- `is_valid_strategy_signal(signal)` ist die **einzige Wahrheitsquelle** der Gültigkeitsbeurteilung der gesamten Baseline-Kette: Jedes Modul, das beurteilt, ob „diese Opinion für die Evidence Chain geeignet ist", muss diese Funktion aufrufen.

Die Baseline verbietet, außerhalb von `_STRATEGY_SIGNAL_ALIASES` eine zweite canonical-Mapping-Tabelle zu pflegen; `strategy_signal_score(canonical)` innerhalb von ConflictDetector und Synthesizer akzeptiert nur canonical-Werte; es ist verboten, über `op.original_signal` oder Großschreibungsvarianten nachzuschlagen.

### Trennung von Evidence Chain und Diagnostics

Die Baseline legt fest:

- **Die Evidence Chain ist ausschließlich die Menge der Valid Opinions.** DecisionAgent-Prompt, die numerischen Berechnungen von `strategy_synthesis` und das Bucketing von `disagreement_summary` müssen alle aus derselben Evidence Chain lesen.
- **Invalid Opinions müssen in die Diagnostics gelangen** (`ctx.meta["invalid_opinions"]` oder ein gleichwertiges Feld), nur für Protokolle, Diagnose und die benutzersichtbare Zählung „weitere N Strategien konnten nicht verarbeitet werden".
- Die beiden Mengen sind **disjunkt und ihre Vereinigung ist vollständig**: Eine Opinion ist entweder in der Evidence Chain oder in den Diagnostics und darf nicht gleichzeitig vorkommen oder in keiner von beiden.
- Invalid Opinions dürfen **nicht** stillschweigend in `hold` umgewandelt, mit beibehaltenem `confidence` versehen oder anonym in die Buckets `bullish_agents` / `bearish_agents` / `neutral_agents` gemischt werden.

Diagnostics-Struktur:

```python
ctx.meta["invalid_opinions"] = [
    {
        "agent_name": str,          # Originaler agent_name
        "raw_signal": str | None,   # Originales Signal-Literal (nicht normalisiert)
        "confidence": float,        # Originale Konfidenz, nur zur Diagnose, nimmt an keiner Berechnung teil
        "reason": str,              # "missing_signal" | "unrecognized_signal" | "invalid_flag"
    },
    ...
]
```

Die Baseline legt nur diese Struktur fest, nicht den **Codeort** der Sortierung — Phase 1 wird die Sortierung im Orchestrator verorten.

### Dynamische Zweilagerung (Supporting / Opposing)

Bei gegebenem Endsignal `final_signal` und canonical score `final_score = strategy_signal_score(final_signal)` wird für jede Valid Opinion `op` der Wert `op_score = strategy_signal_score(op.signal)` berechnet:

- **Wenn `final_signal == "hold"` (d. h. `final_score == 3.0`) ist:**
  - `op_score == 3.0` → `supporting_skills`
  - `op_score != 3.0` → `opposing_skills` (als Auffangbehälter für Einwände und Divergenzen, damit Beobachten- und Divergenzeinschätzungen nicht stillschweigend verworfen werden und bei der Anzeige kein Einwandhintergrund verloren geht)

- **Wenn `final_signal` ein Richtungssignal ist (`strong_buy` / `buy` / `sell` / `strong_sell`):**
  - Gleichgerichtet (beide bullish oder beide bearish) und `abs(op_score - final_score) ≤ 1.0` → `supporting_skills`
  - Gegenrichtung und `abs(op_score - final_score) ≥ 2.0` → `opposing_skills`
  - Sonst (`abs(diff) < 2.0` und nicht gleichgerichtet) → `opposing_skills` (in die Einwände aufgenommen, um ein drittes Lager `neutral_skills` zu vermeiden)

Die Baseline stellt klar, dass **`neutral_skills` kein formales Feld der Payload ist**. Jede Valid Opinion muss **exakt** in eines von `supporting_skills` oder `opposing_skills` fallen; die Gesamtzahl der Gruppierungsergebnisse muss gleich `summary_params.opinion_count` sein.

### Konsensschwellen

Die Baseline fixiert die Beurteilung des Konsensgrads gestuft nach der Anzahl der validen Stichproben:

| Anzahl valid | consensus_level | Erläuterung |
| --- | --- | --- |
| 0 | `insufficient` | Keine Nachweise zu synthetisieren, `final_signal` wird zwingend `hold`, `confidence=0.0` |
| 1 | `insufficient` | Eine einzelne Stichprobe bildet keinen „Konsens", auch bei vollständiger Übereinstimmung mit final darf kein `high` ausgegeben werden |
| ≥ 2, `sum(confidence) == 0` | `insufficient` | Die Konfidenz der gültigen Nachweise ist null, ein Konsens kann nicht aufgebaut werden |
| ≥ 2, `sum(confidence) > 0` | Wechsel in die aligned_ratio-Beurteilung | Siehe Tabelle unten |

Aligned-Ratio-Beurteilung (valid ≥ 2 und `sum(confidence) > 0`):

| Bedingung | consensus_level |
| --- | --- |
| `conflict_severity == "high"` | `low` |
| `aligned_ratio ≥ 2/3` und `conflict_count == 0` (äquivalent `conflict_severity == "none"`) | `high` |
| `conflict_severity == "medium"` und `aligned_ratio < 0.5` | `low` |
| Sonst | `medium` |

Dabei ist `aligned = Anzahl der valid, die gleichgerichtet zu `final_signal` sind und eine Score-Distanz ≤ 1.0 haben`, `aligned_ratio = aligned / len(valid)`.

Die Baseline verbietet, mit Fallbacks wie `sum(...) or 1.0` Nullgewichte als Nenner 1 zu verschleiern; Nullgewichte müssen explizit über den `insufficient`-Zweig laufen und `final_signal` auf `hold` zurückfallen lassen.

### `strategy_synthesis`-Payload-Schema

```json
{
  "final_signal": "hold",                 // canonical signal
  "weighted_score": 3.0,                  // 4 Nachkommastellen
  "confidence": 0.72,                     // reduzierte Konfidenz
  "original_confidence": 0.80,            // gewichtete Konfidenz vor der Reduktion
  "conflict_count": 0,
  "conflict_severity": "none",            // none | low | medium | high
  "conflicts": [ /* Liste der vom ConflictDetector ausgegebenen dicts */ ],
  "supporting_skills": [ /* opinion item */ ],
  "opposing_skills":   [ /* opinion item */ ],
  "consensus_level": "high",              // high | medium | low | insufficient
  "summary_key": "strategy_synthesis.no_conflicts",   // dynamischer i18n-Zusammenfassungsschlüssel, bestimmt durch Konsens- und Konfliktstatus
  "summary_params": {
    "opinion_count": 2,                   // Anzahl der valid Stichproben (Größe der Evidence Chain)
    "total_opinion_count": 4,             // valid + invalid (Original-Gesamtzahl der Eingaben vor der Sortierung)
    "invalid_opinion_count": 2,           // Länge der Diagnostics
    "final_signal": "hold",
    "consensus_level": "high",
    "conflict_severity": "none",
    "conflict_count": 0
  },
  "deliberation": {                       // optional; nur bei material conflicts ausgelöst
    "status": "completed",
    "mode": "multi_round_v4",
    "rounds": 2,
    "agenda": [ /* conflict agenda item */ ],
    "responses": [ /* per-agenda participant response */ ],
    "summary": {
      "resolution_status": "partially_resolved",
      "resolved_conflict_count": 0,
      "unresolved_conflict_count": 1,
      "minority_view_preserved": true,
      "confidence_adjustment": -0.06,
      "confidence_adjustment_reason_key": "deliberation.confidence.high_partially_resolved"
    },
    "round_history": [
      {
        "round": 1,
        "source_mode": "mediator_v0",
        "status": "baseline",
        "changed_response_count": 2,
        "confidence_adjustment": -0.06
      },
      {
        "round": 2,
        "source_mode": "multi_round_v4",
        "status": "accepted",
        "changed_response_count": 1,
        "confidence_adjustment": -0.09
      }
    ]
  },
  "revision_projection": {                // optional; Vorschau nur erzeugt, wenn deliberation vorhanden ist
    "status": "computed",
    "mode": "preview_only",
    "source_mode": "mediator_v0",
    "projected_signal": "hold",
    "projected_weighted_score": 3.0,
    "projected_confidence": 0.6696,
    "projected_original_confidence": 0.72,
    "projected_conflict_count": 1,
    "projected_conflict_severity": "medium",
    "projected_consensus_level": "low",
    "changed_skill_count": 2,
    "changed_skills": ["trend_v1", "theme_v1"],
    "final_signal_overridden": false
  }
}
```

Opinion-Item-Struktur (jedes Element von `supporting_skills` / `opposing_skills`):

```json
{
  "skill_id": "trend_v1",
  "agent_name": "skill_trend_v1",
  "signal": "hold",              // canonical
  "confidence": 0.80,            // 4 Nachkommastellen
  "reasoning": "...",
  "score_adjustment": 0,
  "conditions_met": []
}
```

Die Baseline stellt klar, dass `strategy_synthesis` das **vom SkillAggregator deterministisch erzeugte einzige autoritative Syntheseergebnis** ist. `_collect_strategy_synthesis()` des Orchestrators muss bevorzugt die Synthese aus `ctx.get_data("skill_consensus")` verwenden und darf nur dann, wenn der SkillAggregator nichts erzeugt hat, auf die `skill_consensus`-Opinion in `ctx.opinions` zurückfallen. **Das vom LLM zurückgegebene Dashboard darf `dashboard.strategy_synthesis` nicht überschreiben oder verändern**; `normalize_dashboard_payload` muss beim Erhalt der LLM-Ausgabe das `strategy_synthesis`-Feld der LLM-Seite entfernen, um zu vermeiden, dass LLM-Halluzinationen das autoritative Syntheseergebnis verunreinigen.

### Strategy Deliberation v0 (Phase 1.5)

`strategy_synthesis.deliberation` ist ein optionaler Block für kollaboratives Reasoning, der nur bei mittleren bis hohen Konflikten oder eindeutig kritischen Konflikttypen erzeugt wird. v0 verwendet den deterministischen `mediator_v0`, ruft kein LLM auf, lässt Strategien nicht frei chatten, verändert keine Original-Opinions und berechnet `final_signal` nicht neu. Seine Aufgabe ist es, Konflikte in prüfbare Themen zu überführen und Strategieantworten, leichte Korrekturen sowie Gründe für die Reduktion der synthetisierten Konfidenz zu erfassen.

Auslösebedingungen:

- `len(valid_opinions) >= 2`
- und es existiert ein Konflikt mit `severity in {"medium", "high"}`, oder der Konflikttyp gehört zu `directional_opposition` / `high_confidence_dissent`

v0-Revision erlaubt nur:

- `unchanged`: Die ursprüngliche Einschätzung beibehalten.
- `softened`: Nur die Konfidenz senken oder `strong_buy -> buy`, `strong_sell -> sell`; `buy` / `sell` / `hold` werden nicht umgekehrt, nur die Konfidenz darf gesenkt werden.

v0 verbietet ausdrücklich:

- `reversed`: Einschätzungen dürfen nicht umgekehrt werden.
- Eine Neuberechnung von `final_signal`.
- Die Einführung von mehrrundigem Debate, paralleler Planung, Frontend-Anzeige oder neuen Konfigurationseinträgen.

`deliberation.summary.confidence_adjustment` dient nur als zusätzliche konservative Reduktion durch den `StrategySynthesizer` nach der ursprünglichen Reduktion durch die Konfliktschwere. Bei hohem Konflikt mit teilweiser Auflösung beträgt sie standardmäßig etwa `-0.06`, ohne Auflösung etwa `-0.08`; bei mittlerem Konflikt mit teilweiser Auflösung etwa `-0.04`, ohne Auflösung etwa `-0.05`. Dieses Feld muss in der Payload erhalten bleiben, damit nachgelagerte Renderer oder die Web-UI zeigen können, „warum die Konfidenz weiter herabgesetzt wurde".

### LLM-Mediator v1 (Phase 1.6)

`llm_mediator_v1` ist ein injizierbarer Verstärkungsmodus von `StrategyDeliberation`, kein Standardlaufzeitverhalten. Aufrufer können dem `StrategySynthesizer(deliberation_mediator=...)` einen `LLMDeliberationMediator` injizieren; dieser erzeugt zuerst die v0-Baseline-Agenda und sendet dann die niedervertraulichen strukturierten Opinions/Conflicts/Baseline-Payload an das LLM-Callable. Das LLM darf nur ein JSON-Objekt desselben Schemas zurückgeben; bei zurückgegebenem Text, schlechtem JSON, fehlenden Feldern, ID-Drift oder einer außerhalb des Bereichs liegenden Revision muss bedingungslos auf v0 zurückgefallen werden.

v1-Schema-Guard:

- `agenda` muss die `agenda_id`-Menge von v0 erhalten; Teilnehmer dürfen nicht hinzugefügt, entfernt oder ersetzt werden.
- `responses` müssen die `(agenda_id, skill_id)`-Menge von v0 abdecken; nicht beteiligte Strategien dürfen nicht hinzugefügt werden.
- `revision` erlaubt nur `unchanged` / `softened`; `reversed` bleibt verboten.
- Eine in der v0-Baseline bereits `softened` Response muss `softened` bleiben, darf das Original-Signal nicht wiederherstellen, und `revised_confidence` darf nicht höher als der in der Baseline verifizierte Wert sein.
- Eine in der v0-Baseline `unchanged` Response darf unverändert bleiben oder gemäß den Originalregeln weiter `softened` werden; das Signal darf nicht umgekehrt und die Konfidenz nicht erhöht werden.
- `summary.confidence_adjustment` darf nicht optimistischer als in der v0-Baseline sein, und die einmalige zusätzliche Reduktion hat die Untergrenze `-0.10`, um zu verhindern, dass das LLM die deterministische Reduktion rückgängig macht.

Besteht die v1-Ausgabe die Validierung, gilt `deliberation.mode="llm_mediator_v1"`; andernfalls bleibt die `mediator_v0`-Ausgabe erhalten. v1 ruft weiterhin weder ein Strategie-Agent-Self-Review auf, betreibt kein mehrrundiges Debate, berechnet `final_signal` nicht neu und fügt keine Konfigurationseinträge hinzu.

### Strategy Self-Review v2 (Phase 1.7)

`self_review_v2` ist ein injizierbarer Self-Review-Modus von `StrategyDeliberation`, kein Standardlaufzeitverhalten. Aufrufer können dem `StrategySynthesizer(deliberation_mediator=...)` einen `StrategySelfReviewMediator` injizieren; dieser holt zuerst die Baseline-Deliberation (kann `mediator_v0` oder ein validiertes `llm_mediator_v1` sein) und ruft dann pro `(agenda_id, skill_id)` der Baseline-Response das Self-Review-Callable auf. In Zukunft kann dieses Callable von den tatsächlich konfliktbeteiligten Strategie-Agents ausgeführt werden; der aktuelle Vertrag legt nur Ein-/Ausgabe und das Degradationsverhalten fest.

v2-Self-Review-Guard:

- Jede Baseline-Response muss genau ihre eigene Response-JSON zurückgeben; die Antworten anderer Strategien dürfen nicht verändert werden.
- Die zurückgegebenen `agenda_id` / `skill_id` müssen exakt mit der Baseline-Response übereinstimmen.
- `revision` erlaubt weiterhin nur `unchanged` / `softened`; `reversed` bleibt verboten.
- Eine bereits `softened` Baseline darf nicht auf `unchanged` zurückgesetzt, das Original-Signal nicht wiederhergestellt und die Baseline-`revised_confidence` nicht erhöht werden.
- Eine `unchanged` Baseline darf unverändert bleiben oder gemäß den Originalregeln weiter `softened` werden; das Signal darf nicht umgekehrt und die Konfidenz nicht erhöht werden.
- Wenn v2 die Zusammenfassung aus den validierten Responses neu berechnet, darf die endgültige `confidence_adjustment` nicht optimistischer als die Eingabe-Baseline sein.
- Bei fehlendem Teilnehmer, schlechtem JSON, ID-Drift, unbefugten Änderungen oder dem Versuch von `reversed` fällt die gesamte Self-Review-Runde auf die Baseline-Deliberation zurück; eine Vermischung teilweise gültiger Self-Reviews ist verboten.

Besteht die v2-Ausgabe die Validierung, gilt `deliberation.mode="self_review_v2"`. v2 macht weiterhin nur eine Runde, fügt keine parallele Planung hinzu, berechnet `final_signal` nicht neu, verändert keine Original-Opinions und fügt keine Konfigurationseinträge hinzu.

### Revisionsprojektion v3 (Phase 1.8)

`strategy_synthesis.revision_projection` ist ein optionaler Vorschau-Block, der nur bei vorhandener `deliberation` vom `StrategySynthesizer` berechnet wird. Er liest die bereits durch die v0/v1/v2-Schema-Guards geprüften `responses`, wendet Antworten mit `revision="softened"` auf temporäre `StrategyOpinion`-Kopien an und zeigt das neue Syntheseergebnis über den confidence-gewichteten Score vorab.

v3-Ausgabegrenzen:

- `revision_projection.mode` ist fix auf `preview_only`.
- `source_mode` erfasst die Projektionsquelle: `mediator_v0` / `llm_mediator_v1` / `self_review_v2`.
- `projected_signal` / `projected_weighted_score` / `projected_confidence` beschreiben nur das Vorschauergebnis nach Annahme der softened Revisionen.
- `projected_conflict_count` / `projected_conflict_severity` / `projected_consensus_level` werden auf Basis der temporären Revisionskopien neu erkannt und überschreiben die Original-Conflicts nicht.
- `changed_skill_count` / `changed_skills` zählen nur die tatsächlich softened Strategien.
- `final_signal_overridden` muss fix auf `false` gesetzt sein, um klarzustellen, dass v3 das autoritative Endsignal nicht überschreibt.

v3 verbietet ausdrücklich:

- `projected_signal` zurück in das Top-Level-`final_signal` zu schreiben.
- `projected_weighted_score` zurück in das Top-Level-`weighted_score` zu schreiben.
- `projected_confidence` zurück in das Top-Level-`confidence` zu schreiben.
- Ohne `deliberation` eine leere Projektion auszugeben.
- Freitext, umgekehrte Signale oder neu hinzugefügte Strategieantworten zu akzeptieren, die nicht die v0/v1/v2-Guards durchlaufen haben.

v3 überprüft am Projektionseinstieg außerdem erneut `original_signal`, die zulässigen softened Signale und die Obergrenze von `revised_confidence`; selbst wenn der Aufrufer ein benutzerdefiniertes Ergebnis ohne die eingebauten Mediator-Guards injiziert hat, wird keine aggressivere Response auf die temporäre Opinion-Kopie angewendet.

### Konfigurierbare Multi-Round-Deliberation v4 (Phase 1.9)

`multi_round_v4` ist ein injizierbarer mehrrundiger Verstärkungsmodus von `StrategyDeliberation`, kein Standardlaufzeitverhalten. Aufrufer können dem `StrategySynthesizer(deliberation_mediator=...)` einen `MultiRoundDeliberationMediator` injizieren und über Konstruktorparameter konfigurieren:

- `fallback`: Der Baseline-Mediator der ersten Runde, kann `mediator_v0`, `llm_mediator_v1` oder `self_review_v2` sein.
- `max_rounds`: Obergrenze der Gesamtrunden, Bereich `1–4`; `1` entspricht nur der Beibehaltung der Fallback-Baseline.
- `stop_when_stable`: Ob vorzeitig gestoppt wird, wenn eine Runde keine Änderung der Responses aufweist, standardmäßig aktiviert.
- `round_completion(round_index, messages)`: Callable für strukturierte Revision der nächsten Runde, darf nur gleich-schema JSON zurückgeben.

v4-Runden-Guard:

- Jede Runde muss die `agenda_id`-Menge und die `(agenda_id, skill_id)`-Response-Menge der Vorrunde erhalten; Teilnehmer dürfen nicht hinzugefügt, entfernt oder ersetzt werden.
- `revision` erlaubt weiterhin nur `unchanged` / `softened`; `reversed` bleibt verboten.
- Eine in der Vorrunde bereits `softened` Response darf nicht zu `unchanged` zurückkehren.
- Eine in der Vorrunde bereits `softened` Response darf weder `revised_signal` wechseln noch `revised_confidence` erhöhen.
- Eine in der Vorrunde `unchanged` Response darf `unchanged` bleiben oder gemäß den Originalregeln `softened` werden.
- `summary.confidence_adjustment` darf nicht positiv und nicht optimistischer als in der Vorrunde sein; die Untergrenze pro Runde bleibt gemäß dem v1-Guard auf `-0.10` geklemmt.
- Bei schlechtem JSON, ID-Drift, außerhalb des Bereichs liegender Revision, Rücknahme von softened oder Erhöhung der Konfidenz in irgendeiner Runde werden die nachfolgenden Runden gestoppt und das in der Vorrunde verifizierte Ergebnis zurückgegeben; schlägt bereits Runde 2 fehl, bleibt die Fallback-Baseline erhalten.

v4-Ausgabe:

- Bei mindestens einer angenommenen zusätzlichen Revisionsrunde gilt `deliberation.mode="multi_round_v4"`.
- `deliberation.rounds` erfasst die tatsächlich angenommene Gesamtzahl der Runden.
- `deliberation.round_history` erfasst für die Baseline und jede angenommene Runde `round`, `source_mode`, `status`, `changed_response_count` und `confidence_adjustment`.
- v4 berechnet weiterhin kein Top-Level-`final_signal` neu, verändert keine Original-Opinions und überschreibt nicht direkt Top-Level-`weighted_score` oder `confidence`; die Top-Level-Konfidenz liest weiterhin nur die endgültige `deliberation.summary.confidence_adjustment` für die konservative Reduktion.

### Zentrale Invarianten

Die semantischen Grenzen der Baseline verdichten sich zu neun Invarianten. Alle Implementierungen jeder Phase N müssen diese neun gleichzeitig erfüllen; jede Verletzung gilt als Vertragsbruch.

| ID | Invariante | Szenario | Erwartung |
| --- | --- | --- | --- |
| I-1 | Exklusivität der Evidence Chain | Beliebiges Modul liest die Evidence Chain | Jeder Eintrag in der Menge muss `is_valid_strategy_signal == True` sein; Invalid darf nicht auftreten |
| I-2 | Keine stillschweigende Umwandlung | Fehlendes oder nicht erkennbares Signal | In die Diagnostics einordnen, nicht in `hold` umwandeln und in die Evidence Chain oder Buckets mischen |
| I-3 | Null-Nachweise → insufficient | Beliebiges gültiges Signal, aber `sum(confidences) == 0`, oder Anzahl valid = 0 | `final_signal="hold"`, `weighted_confidence=0.0`, `consensus_level="insufficient"`; die Ausgabe von `strong_sell` oder beliebiger Richtungssignale ist verboten |
| I-4 | Einzelne Stichprobe → insufficient | Genau 1 Valid Opinion | `consensus_level="insufficient"`, auch bei vollständiger Übereinstimmung mit final |
| I-5 | Hold-final-Konsistenz | `final_signal == "hold"` und mindestens 2 hold Valid Opinions vorhanden | Alle hold Opinions müssen in `supporting_skills` eingeordnet werden; die Beziehung zwischen `consensus_level` und der Anzahl der `supporting_skills` muss selbstkonsistent sein (bei `high` deckt supporting ≥ 2/3 ab) |
| I-6 | Payload- und Renderer-Semantik konsistent | Werte von `dashboard.strategy_synthesis` | Der tatsächliche Text der vier Renderer (Markdown / WeChat / Notification / History) muss exakt mit der Payload übereinstimmen; selbstwidersprüchliche Kombinationen wie „Konsensgrad: hoch + Unterstützende Strategien: keine" dürfen nicht auftreten |
| I-7 | Canonical-First-Bewertung | Bewertung, Gewichtung, Konfliktbeurteilung und Gruppierung innerhalb von Aggregator / ConflictDetector / Synthesizer | Muss die von `normalize_strategy_signal()` zurückgegebenen kleingeschriebenen canonical-Werte verwenden; es ist verboten, Rohstrings wie `"BUY"` in Großschreibung oder Aliassee direkt für `strategy_signal_score` nachzuschlagen |
| I-8 | Mehrsprachige Leer-Platzhalter | Anzeige bei leerem `supporting_skills` / `opposing_skills` | Muss über `labels.none_label` nach `report_language` nachgeschlagen werden; das Harcodeieren chinesischer `"无"` / englischer `"None"` / koreanischer `"없음"`-Literale in Code oder Templates ist verboten |
| I-9 | Monotone Konservativität der Deliberation | v1/v2/v4 revidieren auf Basis der in der oberen Schicht verifizierten Baseline, v3 wendet die Projektion an | Vorhandenes `softened` darf nicht zurückgenommen, das Original-Signal nicht wiederhergestellt, die baseline revised confidence nicht erhöht und die baseline confidence adjustment nicht erhöht werden; außerhalb des Bereichs liegende Ergebnisse fallen auf die obere Schicht zurück |

## Phase-1-Semantik-Konvergenz (Lieferumfang dieser PR)

Phase 1 ist die erste codebasierte Umsetzung des Baseline-Vertrags. Phase 1 **fügt keine Vertragsklauseln hinzu**, sondern bringt die in der Baseline bereits fixierten Grenzen in konkreten Code: Orchestrator-Sortierung, konvergente Berechnungen von Aggregator/Synthesizer, Konvergenz des DecisionAgent-Prompts, Disagreement-Konvergenz, Konsistenz der vier Renderer, E2E-Gegenbeispiel-Abdeckung.

Die in Phase 1 betroffenen Einstiegspunkte:

- `src/agent/protocols.py`: Hinzufügen von `is_valid_strategy_signal()` als einzige Wahrheitsquelle; `normalize_strategy_signal()` behält das invalid-Statusbit.
- `src/agent/skills/engine.py`: `StrategyEngine.process()` führt über `partition_only()` die einzige autoritative Sortierung durch und steuert anschließend über `process_partition()` Aggregation und Synthese; Valid bleibt in der Evidence Chain, Invalid wird in die Diagnostics geschrieben.
- `src/agent/orchestrator.py`: Vor dem DecisionAgent-Lauf `_run_strategy_engine(ctx)` aufrufen; im timeout / budget-skip-Frühbeendigungspfad `_apply_partition_fallback(ctx)` aufrufen, das nur sortiert und nicht synthetisiert, um ein Zurückfließen von Invalid in die Nachweiskette zu vermeiden.
- `src/agent/skills/aggregator.py`: `StrategyEngine` übergibt `valid_skill_opinions` an `SkillAggregator.calculate()`; die mathematischen Berechnungen verwenden nur Valid Opinions und gehen bei `valid_weight_sum == 0` explizit in den `insufficient`-Zweig.
- `src/agent/skills/synthesis.py`: `ConflictDetector` / `StrategySynthesizer` berechnen mit canonical signals; `_group_opinions()` implementiert § „Dynamische Zweilagerung"; `_consensus_level()` implementiert § „Konsensschwellen"; `summary_params` ergänzt `invalid_opinion_count` / `total_opinion_count`.
- `src/agent/agents/decision_agent.py`: `build_user_message()` konsumiert direkt `ctx.opinions` und filtert nicht erneut; im Prompt wird die Anzahl von `ctx.meta["invalid_opinions"]` wahrheitsgemäß angezeigt.
- `src/agent/disagreement.py`: `build_agent_disagreement_summary()` konsumiert direkt `ctx.opinions` (da die StrategyEngine die Sortierung abgeschlossen und der Orchestrator sie zurückgeschrieben hat); Invalid erscheint in den drei Buckets `bullish_agents` / `bearish_agents` / `neutral_agents` überhaupt nicht.
- `src/services/report_renderer.py`, `templates/report_markdown.j2`, `templates/report_wechat.j2`, `src/notification.py`, `src/services/history_service.py`: Lesen `strategy_synthesis.supporting_skills` / `opposing_skills` / `consensus_level` / `summary_params.invalid_opinion_count`; leere Listen werden über `labels.none_label` ausgegeben; `neutral_skills` wird nicht mehr konsumiert.
- `src/report_language.py`: `labels.none_label` ist in den drei Sprachen zh/en/ko vollständig; die Texte für Konsensgrad und Diagnosezählung sind vollständig.
- `tests/test_multi_agent.py`: Neue Gegenbeispielmatrix E2E-A..G, durchgängige Assertions über die gesamte Kette von SkillAgent-Eingabe → StrategyEngine-Sortierung/Aggregation → DecisionAgent-Prompt → Dashboard-Payload → Renderer-Tatsächlichtext.

Phase 1 ändert weder die `AgentOpinion`-Felder, noch die API-Rückgabestruktur, noch das Datenbankschema, noch fügt es Konfigurationseinträge hinzu, noch ändert es die Ausführungsweise bestehender Skills.

## Phase 2 Parallele Planung

Phase 2 fügt nur unter dem Vertrag von Phase 1/1.5/1.6/1.7/1.8/1.9 parallele und gestaffelte Planung für 2–4 Strategien hinzu:

- `src/agent/skills/scheduler.py::AgentSkillScheduler` führt specialist Skill Agents über einen Thread-Pool parallel aus; jeder Skill läuft mit einer `AgentContext`-Kopie und propagiert über eigenständiges `copy_context()` die in der Hauptpipeline eingefrorenen `ContextVar`-Zustände wie das target date in die Worker; der Hauptthread führt die strukturierten Opinions in Routenreihenfolge zusammen, um zu vermeiden, dass mehrere Skills gleichzeitig das gemeinsame `ctx.opinions` schreiben.
- Der finale Einstieg der specialists wählt höchstens 4 Strategien aus; `AGENT_SKILL_CONCURRENCY` steuert die Anzahl gleichzeitig laufender Worker, standardmäßig `3`, Bereich `1–4`. Beim Standardwert tritt die 4. Strategie in die nächste concurrency wave ein und wird von der Routenschicht nicht stillschweigend verworfen.
- `AGENT_SKILL_AGENT_TIMEOUT_S` bleibt die unabhängige Timeout-Obergrenze für einen einzelnen Skill; bei aktiviertem Pipeline-Gesamtbudget nimmt `_run_stage_agent()` weiterhin den kleineren Wert aus verbleibendem Pipeline-Budget und der unabhängigen Skill-Obergrenze.
- Timeout oder Exception eines einzelnen Skills führt über den Diagnostics-Pfad (`reason="skill_timeout"` / `"skill_error"`) in `ctx.meta["invalid_opinions"]` und blockiert weder andere Skills noch den Hauptfluss.
- Phase 2 ändert weder das Trennungsprinzip von Baseline Evidence Chain / Diagnostics, noch die Lagersemantik, noch die Konsensschwellen, noch das `strategy_synthesis`-Payload-Schema.
- Phase 2 ändert die Renderer-Anzeigelogik nicht; scheduler timeout/error/no-opinion und Signal-Validierungsfehler gehen einheitlich in die autoritativen Diagnostics der StrategyEngine ein; `invalid_opinion_count` / `total_opinion_count` decken diese fehlgeschlagenen Skills ab.
- `ctx.meta["skill_scheduler"]` dient nur als Laufzeitdiagnose und erfasst Planungsmodus, Parallelitätszahl, Einzel-Skill-Timeout, geplante Anzahl, abgeschlossene Anzahl und invalid-Anzahl; es darf nicht an der synthetisierten Bewertung teilnehmen.

## Phase 3 Vollständige mehrsprachige Frontend-Darstellung (in dieser PR nicht enthalten)

Phase 3 ergänzt nur auf Basis von Phase 2 die vollständige mehrsprachige Darstellung von `strategy_synthesis` im Frontend (`apps/dsa-web/`, `apps/dsa-desktop/`):

- Die Web-Berichtsdetailseite zeigt `final_signal` / `consensus_level` / `supporting_skills` / `opposing_skills` / `conflicts` / `invalid_opinion_count`.
- Desktop verwendet die Web-Anzeigelogik wieder.
- Die mehrsprachige Label-Tabelle verwendet die in `src/report_language.py` vorhandenen Sprachen zh/en/ko wieder; das Frontend projiziert nur und definiert nicht neu.
- Phase 3 ändert weder den Baseline-Vertrag, noch fügt es Payload-Felder hinzu, noch API-Endpunkte.

## Phase 4 Skill-Outcome-Gewichts-Feedback-Kreislauf

Phase 4 passt innerhalb desselben `CONTRACT_VERSION = "1.0"` nur mit echten, zurechenbaren
individuellen Skill Outcomes die relativen Laufzeitgewichte an. Die Gewichtsstatistik bleibt
strikt nach `skill_id + horizon + engine_version` in Buckets aufgeteilt; jeder Horizon muss
unabhängig `evaluated >= 30` erfüllen; Stichproben dürfen nicht über Horizon, Skill oder
Engine-Version hinweg zusammengesetzt werden, um Gewichte freizuschalten.

Ein einzelner ausreichender Bucket verwendet die symmetrische `Beta(15, 15)`-A-priori zur Schrumpfung der Trefferquote:

```text
n = hit + miss
posterior_hit_rate = (hit + 15) / (n + 30)
direction_score = 2 * posterior_hit_rate - 1
unable_rate = unable / (evaluated + observational + unable)
bucket_score = clamp(direction_score - 0.25 * unable_rate, -1, 1)
evidence_strength = n / (n + 30)
```

`pending` geht nicht in den Nenner der unable-Rate ein; `observational` / `unable` können die
evaluated-Schwelle nicht auffüllen. Da die aktuelle Opinion keinen vertrauenswürdigen Horizon hat,
wird nur über die bereits jeweils die Schwelle erfüllenden Buckets eine evidenzgewichtete
Modellmittelung durchgeführt:

```text
combined_score =
    sum(bucket_score * evidence_strength)
    / sum(evidence_strength)
performance_factor = exp(ln(1.2) * combined_score)
effective_weight = opinion.confidence * performance_factor
```

`performance_factor` ist auf das multiplikativ symmetrische Intervall `[1 / 1.2, 1.2]` begrenzt. Ohne
ausreichende Buckets, bei fehlgeschlagenem Statistiklesen, beschädigten Buckets, nicht endlichen
Werten oder `AGENT_SKILL_AUTOWEIGHT=false` muss der neutrale Faktor `1.0` zurückgegeben werden;
Gewichtsfehler dürfen die Analyse nicht unterbrechen. Die Laufzeit verwendet nicht mehr die globalen
oder nicht zurechenbaren Summaries von `BacktestService` als Ersatz für die Skill-Leistung. Diese Phase
konsumiert schreibgeschützt bereits persistierte Outcomes und fügt weder Pipeline-, API- noch
zeitgesteuerte Auslöseeinstiege des Evaluators hinzu.

`avg_directional_return_pct` bleibt derzeit eine schreibgeschützte beschreibende Kennzahl und nimmt
nicht an der Gewichtung teil. Wenn nur der Mittelwert ohne Streuung oder Standardfehler vorliegt,
würde eine direkte Aufnahme in die Formel eine Scheinpräzision erzeugen; bevor Renditen später
verwendet werden, muss zuerst ein versionierter risikoadjustierter Renditevertrag aufgebaut werden.

Phase 4 ändert weder das Baseline-Canonical-Signal, noch die Valid-Beurteilung, noch die
Konsensschwellen, noch die Lagersemantik; Gewichtsänderungen wirken sich nur auf `weighted_score`
und `confidence` aus, nicht auf den Beurteilungspfad von `consensus_level`. `AGENT_ARCH=single`
durchläuft `SkillAggregator` nicht und bleibt kompatibel.

## Verbraucherflächen-Bestandsaufnahme

Die sieben Verbraucherflächen der Baseline müssen strikt nach der folgenden Tabelle aufgeteilt sein und dürfen sich nicht über die Grenzen hinweg gegenseitig deren interne Daten konsumieren.

### SkillAgent

Jeder Skill erzeugt über `src/agent/skills/skill_agent.py` eine `AgentOpinion`. Die Baseline erlaubt dem Skill, beliebige Signal-Literale (einschließlich Großschreibung, Aliassee, `Signal`-Enum) auszugeben, und erlaubt dem Skill auch, bei unzureichenden Daten `signal=None` / fehlende Felder zu erzeugen — diese Fälle werden von der nachgelagerten Sortierung behandelt; der Skill selbst filtert sich nicht.

### StrategyEngine / Orchestrator (Sortierung und Verdrahtung)

Phase 1 ruft vor dem DecisionAgent-Lauf `_run_strategy_engine(ctx)` auf:

- `StrategyEngine.partition_only()` durchläuft alle Opinions, deren `agent_name` auf `is_skill_agent_name()` zutrifft, und verwendet `normalize_strategy_signal()`, um das canonical signal beizubehalten.
- Invalid wird aus der Evidence Chain entfernt und in `StrategyResult.invalid_records` geschrieben; der Orchestrator weist es dann `ctx.meta["invalid_opinions"]` zu.
- `StrategyEngine.process_partition()` übergibt nur `valid_skill_opinions` an Aggregator/Synthesizer; die erzeugte consensus opinion und `skill_consensus` werden von `_run_strategy_engine()` einmalig in den Kontext zurückgeschrieben.
- Wenn timeout / budget-skip vor dem vollständigen Engine-Lauf auftritt, nutzt `_apply_partition_fallback()` `partition_only()` erneut, schließt nur Sortierung und Diagnostics-Rückschreiben ab und erzeugt kein consensus.

Die Baseline legt fest, dass `StrategyEngine.partition_only()` die **einzige autoritative Sortierimplementierung** ist. Aggregator / DecisionAgent / Disagreement definieren nicht mehr jeweils eigene Valid/Invalid-Regeln, sondern konsumieren direkt die konvergierte Evidence Chain der Engine; der im Orchestrator verbliebene alte Wrapper dient nur zur Kompatibilität bestehender interner Aufrufe/Tests und gehört nicht zur normalen Laufzeitkette.

### SkillAggregator

Im normalen Lauf ruft die `StrategyEngine` `SkillAggregator.calculate(valid_skill_opinions)` auf. Der Aggregator wandelt die Eingabe in interne `StrategyOpinion` um, verwendet in den mathematischen Berechnungen nur Valid Opinions und schlägt strikt canonical signals für `strategy_signal_score` nach; selbst der Kompatibilitätseinstieg darf Invalid nicht an der Gewichtung teilnehmen lassen, wenn unsortierte Eingaben eintreffen. Für die folgenden drei Zustände wird explizit der `insufficient`-Zweig gewählt:

- `len(valid) == 0`: `final_signal="hold"`, `confidence=0.0`.
- `len(valid) == 1`: `final_signal` wird gemäß dem canonical signal dieser Opinion ausgegeben, aber `consensus_level="insufficient"`.
- `len(valid) ≥ 2` und `sum(confidence) == 0`: `final_signal="hold"`, `confidence=0.0`.

Die erzeugte `strategy_synthesis` wird von der `StrategyEngine` in `StrategyResult.skill_consensus_data` geladen und vom Orchestrator an `ctx.set_data("skill_consensus", {...})` gehängt; `_collect_strategy_synthesis()` liest von hier als autoritative Synthesequelle des Dashboards.

### DecisionAgent

`build_user_message()` liest die Einschätzungen aus `ctx.opinions` in den Prompt. Da die Orchestrator-Sortierung garantiert hat, dass `ctx.opinions` nur Valid enthält, macht der DecisionAgent **keine** zweite Filterung mehr. Die Anzeige „weitere N Strategien konnten nicht verarbeitet werden" im Prompt liest direkt die Länge von `ctx.meta["invalid_opinions"]`.

Das vom DecisionAgent ausgegebene Dashboard-JSON darf `dashboard.strategy_synthesis` nicht überschreiben; wenn das LLM-Ergebnis dieses Feld enthält, muss `normalize_dashboard_payload()` es entfernen und die autoritative Synthese der Aggregator-Seite beibehalten.

### Disagreement

`build_agent_disagreement_summary()` bildet die drei Buckets `bullish_agents` / `bearish_agents` / `neutral_agents` nur aus `ctx.opinions`. Da `ctx.opinions` nur noch Valid enthält, erscheint Invalid in den drei Buckets überhaupt nicht und wird auch nicht von `_normalize_signal()` stillschweigend auf `hold` zurückgesetzt.

Die Länge von `ctx.meta["invalid_opinions"]` wird als `disagreement_summary.diagnostics.invalid_count` separat im DecisionAgent-Prompt exponiert, damit das LLM den Text `data_limitations` als Referenz erzeugen kann.

### Renderer (vier Stück)

Alle Renderer lesen `dashboard.strategy_synthesis` zur Anzeige:

- `final_signal` / `consensus_level` / `conflict_severity` / `conflict_count`.
- `supporting_skills` / `opposing_skills` (`neutral_skills` wird nicht mehr konsumiert).
- `summary_params.invalid_opinion_count` → sprachabhängig „weitere N Strategien ungültig / konnten nicht verarbeitet werden" anzeigen.

Leere-Listen-Platzhalter müssen über `labels.none_label` (nach `report_language` nachgeschlagen) ausgegeben werden. Der von den vier Renderern angezeigte Endtext muss exakt mit der Payload übereinstimmen; intern widersprüchliche Kombinationen wie „Konsensgrad: hoch + Unterstützende Strategien: keine" dürfen nicht auftreten.

Historische Datensätze und externe Aufrufer können die lose Shape vor Vertragsumsetzung beibehalten. Die vier Renderer müssen zuerst über `normalize_strategy_synthesis_payload()` nicht-dict Top-Level-Werte als fehlend behandeln und nicht-dict Strategie-/Konflikt-Listenelemente herausfiltern; `strategy_invalid_opinion_count()` liest einheitlich den Diagnosezähler und führt nur für reine dezimale positive Ganzzahl-Strings eine enge Konvertierung durch, andere ungültige Werte degradieren auf 0. In History, Notification oder Templates ist es verboten, parallele handgeschriebene Leselogik beizubehalten.

### Diagnostics

`ctx.meta["invalid_opinions"]` darf nur von den folgenden drei Arten konsumiert werden:

- Protokolle: Erfassen von `agent_name` / `raw_signal` / `reason` zur Fehlersuche.
- DecisionAgent-Prompt: als Zählquelle für „weitere N Strategien konnten nicht verarbeitet werden".
- Renderer: als Quelle für `summary_params.invalid_opinion_count`.

Es ist verboten, die `confidence` aus den Diagnostics an irgendeiner Gewichtungsberechnung teilnehmen zu lassen; es ist verboten, `raw_signal` zurück in `ctx.opinions` zu stopfen.

## Gegenbeispielmatrix

Phase 1 muss die folgende E2E-Gegenbeispiel-Abdeckung liefern. E2E ist definiert als: von der SkillAgent-Eingabe über die Orchestrator-Sortierung → SkillAggregator → DecisionAgent-Prompt → finale Dashboard-Payload → tatsächliche Textausgabe der vier Renderer. Es ist verboten, lokale Unit-Tests als E2E auszugeben.

| Nr. | Eingabe | Assertionspunkte | Abgedeckte Invarianten |
| --- | --- | --- | --- |
| E2E-A | 1 valid `buy/0.8` + 2 invalid `moon/0.9` | ① DecisionAgent-Prompt enthält weder das Literal `moon` noch den invalid `agent_name` noch den `0.9`-Kontext; ② Länge von `ctx.meta["invalid_opinions"]` = 2; ③ `strategy_synthesis.summary_params.opinion_count == 1`, `invalid_opinion_count == 2`; ④ `consensus_level == "insufficient"`; ⑤ die Textausgabe der vier Renderer enthält „weitere 2 Strategien ungültig / konnten nicht verarbeitet werden" (sprachabhängig); ⑥ in `disagreement_summary.bullish_agents` / `neutral_agents` / `bearish_agents` erscheint das zu hold/0.9 umgewandelte moon nicht | I-1, I-2, I-4 |
| E2E-B | 2 valid `hold/0.0` | `final_signal="hold"`, `weighted_confidence=0.0`, `consensus_level="insufficient"`, **niemals** `strong_sell`; alle Renderer zeigen „unzureichende Nachweise (Beobachten)" (sprachabhängig) | I-3 |
| E2E-C | 1 valid `buy/0.0` + 1 valid `hold/0.0` | Szenario gemischter Nullgewichte: `final="hold"`, `confidence=0.0`, `consensus="insufficient"`, kein `strong_sell` | I-3 |
| E2E-D | 2 valid `hold/0.8` | ① `final_signal="hold"`, `consensus_level="high"`; ② Länge `supporting_skills` = 2, Länge `opposing_skills` = 0; ③ der tatsächliche Text der vier Renderer enthält gleichzeitig „hoher Konsens" und die beiden Skill-Namen; die Kombination „Unterstützende Strategien: keine" mit „Konsensgrad: hoch" darf nicht auftreten | I-5, I-6 |
| E2E-E | 1 valid `buy/0.8` + 9 invalid | `consensus_level="insufficient"` (**kein** high); die vier Renderer zeigen „basierend auf 1 gültigen Strategie beurteilt (weitere 9 Strategien ungültig / konnten nicht verarbeitet werden)" | I-4, I-6 |
| E2E-F | 2 Valid Opinions, eine mit `signal="BUY"` (Großschreibung) | Bei der internen Berechnung von `weighted_score` verwendet der Aggregator das canonical `buy` zum Nachschlagen (4.0) und darf **nicht** wegen Großschreibung 0 erhalten; `strategy_synthesis.final_signal` gibt canonical kleingeschrieben aus | I-7 |
| E2E-G | Leeres `supporting_skills` + `report_language="en"` | In der Ausgabe der vier Renderer erscheint nicht das chinesische `"无"`, sondern `"None"` (oder `labels.none_label` der entsprechenden Sprache) | I-8 |

## Quellcode-Anker

| Domäne | Anker |
| --- | --- |
| Signal-Normalisierung und Valid-Beurteilung | `src/agent/protocols.py::normalize_strategy_signal`, `is_valid_strategy_signal`, `strategy_signal_score` |
| StrategyEngine-Sortierung und Synthese-Facade | `src/agent/skills/engine.py::StrategyEngine.partition_only`, `process`, `process_partition` |
| Orchestrator-Verdrahtung und Frühbeendigungs-Sortierung | `src/agent/orchestrator.py::_run_strategy_engine`, `_apply_partition_fallback` |
| SkillAggregator | `src/agent/skills/aggregator.py::SkillAggregator.calculate`, `aggregate` (Kompatibilitätseinstieg) |
| ConflictDetector / StrategySynthesizer | `src/agent/skills/synthesis.py::ConflictDetector`, `StrategySynthesizer` |
| DecisionAgent-Prompt | `src/agent/agents/decision_agent.py::build_user_message` |
| Disagreement | `src/agent/disagreement.py::build_agent_disagreement_summary` |
| Dashboard-Synthese-Montage | `src/agent/orchestrator.py::_collect_strategy_synthesis` |
| Renderer · Markdown | `src/services/report_renderer.py::render`, `templates/report_markdown.j2` |
| Renderer · WeChat | `templates/report_wechat.j2` |
| Renderer · Notification | `src/notification.py` (Rendering der Strategie-Synthesezeile) |
| Renderer · History | `src/services/history_service.py` (Strategie-Syntheseblock in der Historiendetailansicht) |
| Mehrsprachigkeit und Antikorruption loser Payloads | `src/report_language.py::_REPORT_LABELS`, `normalize_strategy_synthesis_payload`, `strategy_invalid_opinion_count`, `localize_strategy_synthesis_summary`, `labels.none_label` |
| E2E-Gegenbeispielmatrix | `tests/test_multi_agent.py::TestP1SemanticConvergence`, `TestStrategyEngineE2E` |

## Kompatibilität und Rollback

### Eingestelltes Verhalten (nach Umsetzung von Phase 1)

| Altes Verhalten | Nach dem Vertrag |
| --- | --- |
| `normalize_strategy_signal` gibt bei unbekanntem Signal stillschweigend `default="hold"` zurück und mischt es in die Nachweiskette | Unbekannte Signale müssen in die Diagnostics eingeordnet werden; in `ctx.opinions` dürfen sie nicht auftreten |
| Der Aggregator verschleiert Nullgewichte über `sum(...) or 1.0` | Explizit `valid_weight_sum == 0` prüfen, den `insufficient`-Zweig wählen, `final_signal="hold"` |
| Renderer harcodieren `"无"` für die Anzeige leerer Lager | Über `labels.none_label` sprachabhängig nachschlagen |
| Der DecisionAgent filtert invalid selbst auf Prompt-Ebene | Die Sortierung erfolgt im Orchestrator, der DecisionAgent konsumiert direkt `ctx.opinions` |
| `strategy_synthesis` gibt `neutral_skills` aus | Nach dem Vertrag existiert dieses Feld nicht, die Renderer konsumieren es nicht mehr |
| Das LLM-Dashboard überschreibt `strategy_synthesis` | Die autoritative Synthese stammt vom Aggregator, das LLM-seitige Feld wird von `normalize_dashboard_payload` entfernt |

### Neu hinzugefügte Felder

- `ctx.meta["invalid_opinions"]`: Auffangposition für Diagnostics (Struktur siehe „Trennung von Evidence Chain und Diagnostics").
- `strategy_synthesis.summary_params.invalid_opinion_count`: Länge der Diagnostics.
- `strategy_synthesis.summary_params.total_opinion_count`: Original-Gesamtzahl von valid + invalid.

### Rollback-Methoden

| Mittel | Wirkung | Was nicht möglich ist |
| --- | --- | --- |
| Version-Rollback der Phase-1-Commit | Entfernt Orchestrator-Sortierung, Aggregator/Synthesizer-Konvergenz und Renderer-Konsistenzänderungen | Nur ein Teil der Invarianten kann nicht zurückgerollt werden; der Vertrag ist eine ganzheitliche Konvergenz |
| Nur das Vertragsdokument behalten, Code zurückrollen | Baseline-Text beibehalten, zum alten Verhalten zurückkehren | Hat nur Dokumentationsbedeutung, keinen Laufzeitnutzen; nicht empfohlen |
| Unabhängiges Rollback von Phase 2/3/4 | Laufzeitänderungen der jeweiligen Phase unabhängig zurückrollen | Die Baseline kann nicht zurückgerollt werden; jede Phase muss die acht Baseline-Invarianten stets erfüllen |

Die Baseline fügt keine Konfigurationseinträge hinzu, daher gibt es keinen Rollback-Schalter auf env-Ebene; dies ist eine bewusste Entscheidung — die Vertragsgrenzen sollen im Code konstant wirken und nicht über Umgebungsvariablen herabgesetzt werden.
