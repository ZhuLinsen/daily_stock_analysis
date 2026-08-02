# DecisionSignal — Themendokument zu Entscheidungssignalen

Diese Seite schließt #1390 P7 ab und erklärt, wie DSA die AI-Empfehlungen aus Einzelaktien-Analyse, Agent, Alarm und Portfolio-Risiko als abfragbare, rückmeldbare und nachträglich bewertbare `DecisionSignal`-Assets festschreibt. Es ist ein strukturierter Index über den Berichten, ersetzt aber weder die Markdown-Berichte, `operation_advice`, den dreizuständigen `decision_type`, die Alarmregeln noch ein echtes Handelssystem.

## Fähigkeitsgrenzen

- `DecisionSignal` zeichnet nur Empfehlung, Nachweiszusammenfassung, Risiko, Beobachtungsbedingungen, Lebenszyklus und Quelle auf; es führt weder Aufträge aus noch positioniert es um.
- Schreibfehler, Extraktionsfehler, Fehler bei der Alarm-Signal-Verknüpfung und Fehler beim Benachrichtigungsversand blockieren weder die Hauptanalyse, die Alarmauslösung noch das Speichern des Berichts.
- #1756 hat `decision_profile` feldifiziert und die Semantik von server-side filter, Dedupe, Verlängerung und active-Unwirksamkeit korrigiert; #1757 fügt auf diesem formalen Feldvertrag das Reassess-Persist nach Benutzerbestätigung hinzu. Beide fügen weder Umgebungsvariablen, config-registry-Einträge noch Inhalte zu `.env.example` hinzu.
- Es gibt derzeit keinen `DECISION_SIGNAL_*`-Schalter; das Deaktivieren oder Zurückrollen der Signalfunktion erfolgt durch Revert des entsprechenden Codes.

## Felder und Enums

Die Kernfelder sind in `api/v1/schemas/decision_signals.py` definiert und umfassen hauptsächlich:

- Identität und Quelle: `stock_code`, `stock_name`, `market`, `source_type`, `source_agent`, `source_report_id`, `trace_id`, `decision_profile`, `trigger_source`.
- Empfehlungssemantik: `action`, `action_label`, `confidence`, `score`, `horizon`, `market_phase`, `plan_quality`, `status`.
- Plan und Erklärung: `entry_low`, `entry_high`, `stop_loss`, `target_price`, `invalidation`, `watch_conditions`, `reason`, `risk_summary`, `catalyst_summary`.
- Nachweis und Qualität: `evidence`, `data_quality_summary`, `metadata`.
- Lebenszyklus: `expires_at`, `created_at`, `updated_at`.

Enum-Werte:

| Feld | Werte |
| --- | --- |
| `market` | `cn`, `hk`, `us`, `jp`, `kr`, `tw` |
| `source_type` | `analysis`, `agent`, `alert`, `market_review`, `manual` |
| `market_phase` | `premarket`, `intraday`, `lunch_break`, `closing_auction`, `postmarket`, `non_trading`, `unknown` |
| `action` | `buy`, `add`, `hold`, `reduce`, `sell`, `watch`, `avoid`, `alert` |
| `horizon` | `intraday`, `1d`, `3d`, `5d`, `10d`, `swing`, `long` |
| `decision_profile` | `conservative`, `balanced`, `aggressive`; Datenbank-`NULL` bedeutet legacy / unknown |
| `plan_quality` | `complete`, `partial`, `minimal`, `unknown` |
| `status` | `active`, `expired`, `invalidated`, `closed`, `archived` |

Die Web-Anzeige muss diese wire values in für die aktuelle UI-Sprache lesbare Labels übersetzen; API-Antworten behalten weiterhin die ursprünglichen Enum-Werte.

## Canonical-Bewertung und action-Definition

Einzelaktien-Analyse, technische Bewertungs-fallback, Anzeige-fallback der Berichte und `DecisionSignal`-Extraktion teilen sich die Definition `decision-scale-v1`. `decision_type` behält nur `buy|hold|sell` für kompatible Statistiken; die feinere ausführbare Semantik folgt dem achtzuständigen `action`.

- Auf der benutzerseitig sichtbaren Fläche gibt es zwei Feldtypen: `operation_advice` behält die textuelle Definition (z. B. „Halt und beobachte"), während `action` als einheitliche 8-Zustands-Entscheidungsdefinition (z. B. `hold/watch/reduce`) für Risikokontrolle, Backtest und Listenanzeige dient. Neu erzeugte oder vor dem finalen Speichern neu berechnete Einzelaktien-Berichte sollten beide bevorzugt konsistent halten; wenn historische Datensätze oder Kompatibilitäts-Payloads weiterhin semantische Konflikte aufweisen, ist `action` standardmäßig das bevorzugte Feld für strukturierte Anzeigen wie Listen, Backtest und DecisionSignal, während `operation_advice` nur als erklärender Text erhalten bleibt.

| score | signal key | `action` | legacy `decision_type` | Semantik |
| --- | --- | --- | --- | --- |
| 80-100 | `strong_buy` | `buy` | `buy` | Starker Kauf, Chance mit hoher Trefferquote, ausführbarer Kauf/Aufstockungsplan |
| 60-79 | `buy` | `buy` | `buy` | Eher positive Chance, wenige zu bestätigende Punkte erlaubt |
| 40-59 | `watch` | `watch` | `hold` | Signaldissens oder unzureichende Bestätigung, auf Auslösebedingung warten |
| 20-39 | `reduce` | `reduce` | `sell` | Risiko deutlich gestiegen, Exposition vorrangig reduzieren |
| 0-19 | `sell` | `sell` | `sell` | Trend oder Risiko deutlich verschlechtert, Ausstieg vorrangig |

Wenn `score >= 60` aber das endgültige `action` dennoch `hold/watch` ist, oder `score < 40` aber das endgültige `action` weiterhin `hold/watch` ist, muss es eine klare guardrail-Erklärung geben, z. B. `dashboard.decision_stability.reason`, `dashboard.decision_score_calibration.guardrail_reason` oder `metadata.guardrail_reason`. Die Risikokontroll-Herabstufung behält `raw_score`, `adjusted_score`, `raw_action`, `final_action` und den Grund; neutrale Aktionen ohne klaren Grund werden bei der DecisionSignal-Extraktion anhand der canonical score auf `buy/reduce/sell` ausgerichtet.

## Lebenszyklus, Dedupe und Status

`src/services/decision_signal_service.py` ist der Haupteinstieg für den Signallebenszyklus:

- `horizon` und `expires_at` haben Vorrang, wenn sie explizit übergeben werden.
- Ohne übergebenen `horizon` gilt für `alert` oder die Phasen premarket/intraday/Mittagspause/Auktionsphase standardmäßig `intraday`; für postmarket, Nicht-Handelszeit, unbekannte Phase oder fehlende Phase standardmäßig `3d`.
- Die Ablaufzeit von `intraday` liest bevorzugt das niedrig-sensible `metadata.market_phase_summary.minutes_to_close/minutes_to_open`; fehlt es, gilt je Markt ein fallback-TTL.
- `expired`, `invalidated`, `closed`, `archived` können über `PATCH /status` nicht direkt zu `active` zurückgeführt werden.
- Dedupe aus derselben Quelle nutzt bevorzugt `(source_report_id, source_type, market, stock_code, decision_profile, action, horizon, market_phase)`; ohne report, aber mit `trace_id`, wird die trace-Dimension verwendet.
- `decision_profile` ist Teil der Signalidentität: `NULL` matcht nur `NULL`, ein nicht leeres profile nur dasselbe profile. Exact dedup, relaxed dedup, horizon/phase fill, expired refresh, active invalidation und stale backfill invalidation folgen alle dieser same-profile-Semantik.
- Ein neues aktives Gegensignal markiert nur das alte aktive Signal desselben profiles als `invalidated` und schreibt die Invalidierungsquelle in metadata. Verschiedene nicht-`NULL`-profile können auch bei gegensätzlichen Aktionen koexistieren.
- Expired duplicate refresh überschreibt `decision_profile` nicht; nur Datensätze desselben profiles können aufgefrischt werden.

## API

Die aktuell öffentlichen Schnittstellen werden durch `api/v1/endpoints/decision_signals.py` und `docs/architecture/api_spec.json` beschrieben:

- `POST /api/v1/decision-signals`: Erstellt oder dedupliziert über den Same-Source-Schlüssel und gibt `{ item, created }` zurück.
- `GET /api/v1/decision-signals`: Paginierte Abfrage mit Unterstützung für Markt, Aktie, Aktion, Phase, `decision_profile`, Quelle, Status, Zeitbereich und Positionsfilter. Ein weggelassenes oder leeres `decision_profile` fügt keine profile-Bedingung hinzu und gibt alle profile zurück; `decision_profile=unknown` fragt `NULL`-Zeilen ab; ein gültiges profile matcht exakt.
- `GET /api/v1/decision-signals/{signal_id}`: Fragt einen einzelnen Datensatz ab.
- `PATCH /api/v1/decision-signals/{signal_id}/status`: Aktualisiert Status und optional metadata.
- `GET /api/v1/decision-signals/latest/{stock_code}`: Fragt das neueste aktive Signal einer Aktie ab.
- `POST /api/v1/decision-signals/outcomes/run`: Löst die nachträgliche Bewertung explizit aus.
- `GET /api/v1/decision-signals/outcomes`, `GET /api/v1/decision-signals/outcomes/stats`, `GET /api/v1/decision-signals/{signal_id}/outcomes`: Fragt nachträgliche Ergebnisse und Statistiken ab.
- `GET/PUT /api/v1/decision-signals/{signal_id}/feedback`: Fragt das Feedback useful / not useful ab oder schreibt es.
- `POST /api/v1/decision-signals/reassess`: Berechnet auf Basis des persistierten Berichts-Snapshots der Quelle die Signale unter verschiedenen Entscheidungsstilen neu; `persist=false` nur Vorschau, `persist=true` lässt den Server neu berechnen und speichert die Ergebnisse, die den guardrail passieren.

Diese Schnittstellen erben die bestehende Administrator-Authentifizierung von `/api/v1/*`; bei `ADMIN_AUTH_ENABLED=true` ist ein gültiges Administrator-Session-Cookie erforderlich.

## Historische Leistung der Entscheidungsstile

#1758 fügt in die bestehende Antwort von `GET /api/v1/decision-signals/outcomes/stats` `profile_calibration` ein, ohne neuen endpoint, Datenbanktabelle, Konfigurationsoption oder Kurzanfrage. Die alten globalen Statistikfelder und die acht Arten eindimensionaler breakdowns behalten ihre ursprüngliche Definition; eine Stichprobe bleibt eine `(signal_id, horizon, engine_version)`-outcome-Datensatz, und verschiedene Rückblickperioden desselben Signals werden jeweils separat gezählt, nicht als unabhängige Signalanzahl verstanden.

`profile_calibration.minimum_completed_sample_size` ist fest `30`; die breakdowns umfassen:

- `decision_profile`
- `decision_profile_action`
- `decision_profile_horizon`
- `decision_profile_market_phase`
- `decision_profile_data_quality_level`
- `profile_source`

Die `dimensions` jedes buckets sind strukturierte Felder und verwenden keine verketteten Zeichenketten. Die Profile-Kalibrierung wird anhand folgender Quellen interpretiert:

- `decision_profile` liest das aktuelle formale Feld des verknüpften Signals; `NULL` oder ungültige Werte fallen unter `unknown`, ohne auf `balanced` zurückzufallen.
- `profile_source` liest die aktuelle metadata des verknüpften Signals und akzeptiert nur `auto_default`, `backfill_defaulted`, `legacy_unknown`, `user_selected`; andere Fälle fallen unter `unknown`. Dies ist eine aktuelle Attribution, kein outcome-Zeitpunkt-Snapshot; nach einer legitimen Ersetzung der metadata kann sich die statistische Zuordnung ändern.
- `action`, `horizon`, `market_phase`, `data_quality_level` lesen die eingefrorenen Felder des outcome. Beim Erzeugen eines neuen outcome nutzt die Datenqualität bevorzugt das explizite level von `data_quality_summary`; nur wenn die summary fehlt oder im gültigen JSON kein explizites level vorhanden ist, wird das normalisierte `metadata.data_quality_level` verwendet. Ein bereits vorhandenes outcome wird durch diese Leseregel nicht stillschweigend überschrieben.

Jedes bucket nutzt unabhängig die Schwelle `completed >= 30`; weder das übergeordnete bucket, noch die globalen Stichproben noch andere sibling buckets können es freischalten. Bei unzureichender Stichprobe werden counts weiterhin zurückgegeben, aber `hit_rate_pct`, `avg_stock_return_pct`, `miss_rate_pct`, `unable_rate_pct`, `max_adverse_excursion_pct` sind alle `null`; die Web-Seite zeigt nur die Stichprobengröße und „Stichprobe unzureichend, nur zur Beobachtung.". Bei ausreichender Stichprobe:

- Trefferquote ist `hit / (hit + miss)`, Verfehlerquote ist `miss / (hit + miss)`, neutral geht nicht in diese beiden Nenner ein.
- Nicht-bewertbare Quote ist `unable / total`.
- Der durchschnittliche Kursveränderungsbereich der Ziele übernimmt den Mittelwert von `stock_return_pct` der bestehenden completed outcomes; er repräsentiert weder Strategie- noch Portfoliorendite.
- Die maximale adverse Bewegung verwendet nur die im outcome gespeicherten Preise. Für `buy/add/hold/watch/alert` nach `(start_price - min_low) / start_price`, für `sell/reduce/avoid` nach `(max_high - start_price) / start_price`, Ergebnis nicht kleiner als 0; fehlt der Preis, ist er nicht endlich oder ist der Startpreis nicht positiv, ist die Zeile nicht berechenbar. Das bucket gibt das Maximum unter den berechenbaren Zeilen zurück; gibt es keine berechenbare Zeile, ist es `null`, ohne zur Auffüllung der Kennzahl Marktpreise abzurufen.

Die Web-Seite bietet innerhalb der bestehenden Karte „Signal-Leistungsstatistik" drei Benutzereinstiege „Konservativ / Ausgewogen / Aggressiv", wählt standardmäßig ausgewogen und stellt nur zwei Unteransichten „nach empfohlener Aktion" und „nach Rückblickperiode" bereit. Sie rankt nicht, empfiehlt keinen Stil und fügt weder Anfragen, Routen, Navigation noch Einstellungspunkte hinzu; wenn das alte Backend kein `profile_calibration` hat, wird weiterhin die ursprüngliche Statistik-Karte angezeigt.

## Reassess-Preview und -Persist

`reassess` verwendet nur den persistierten Historie-Berichts-Snapshot, der `source_report_id` entspricht. `persist=false` dient der Vorschau vor der Benutzerbestätigung; `persist=true` berechnet mit demselben `source_report_id + decision_profile` serverseitig neu und vertraut keinen Entscheidungsfeldern aus vorheriger Vorschau oder Client-Cache.

Der Request unterstützt nur:

```json
{
  "source_report_id": 123,
  "decision_profile": "aggressive",
  "persist": false
}
```

Vertragsgrenzen:

- `source_report_id` ist die einzige Tatsachenquelle; die Neubewertung liest nur den entsprechenden persistierten Historie-Berichts-Snapshot.
- Der Request erlaubt nur `source_report_id`, `decision_profile`, `persist`. `signal_id` wird nicht unterstützt, und autoritative Felder wie `action`, `score`, `confidence`, `horizon`, `invalidation`, `stop_loss`, `target_price`, `metadata`, `scoring_breakdown` oder `guardrail_result` werden vom Client nicht akzeptiert; zusätzliche Felder geben HTTP 422 zurück und werden nicht stillschweigend ignoriert.
- Die Neubewertung ruft keine Echtzeitkurse stillschweigend ab und füllt den Historie-Snapshot auch nicht mit aktuellen Marktdaten auf.
- Die Inhaltsvalidierung des Quellberichts ist in preview/persist konsistent: fehlender oder ungültiger `source_report_id` gibt HTTP 422 zurück; Bericht nicht vorhanden gibt HTTP 404 `source_report_not_found`; kein Einzelaktien-Bericht gibt HTTP 400 `unsupported_report_type`; ein unzureichender persistierter Snapshot für die Entscheidungssignal-Erzeugung gibt HTTP 400 `unsupported_report_snapshot`. Persist verlangt außerdem, dass der Quellbericht ein gültiges `created_at` hat, sonst gibt er HTTP 400 `unsupported_report_snapshot` zurück und schreibt nicht in die Datenbank; preview hängt nicht von diesem Speicher-Lebenszyklusfeld ab.
- Die Datenqualität wird auf `high`, `medium`, `low`, `poor`, `unknown` normalisiert; der guardrail verwendet nur die normalisierte Stufe.
- Ein erfolgreiches Preview gibt `preview`, `item=null`, `created=false` zurück; es schreibt nicht in die Datenbank und geht weder in Liste, latest noch Zeitleiste ein.
- Ein erfolgreicher Persist gibt `preview=null`, das autoritative `item` des Backends und `persist_status` zurück. `persist_status=created` bedeutet neu erzeugt; `existing` bedeutet, dass ein Datensatz mit derselben feldifizierten Identität bereits existiert und nicht überschrieben wurde; `refreshed` bedeutet, dass nach der bestehenden Semantik von expired refresh / dimension-fill ein Datensatz wiederverwendet und aufgefrischt wurde. Das Kompatibilitätsfeld `created` ist nur bei `created` `true`. `persist_status` beschreibt nur die disposition dieses Schreibvorgangs, nicht, dass `item.status` zwingend `active` ist; neu erzeugte historische Signale können auch als `expired/invalidated` zurückkommen, weil sie abgelaufen oder von einem neueren Gegensignal ersetzt wurden.
- Reassess-Persist und lazy backfill teilen sich denselben Historie-Lebenszyklus: `created_at` verankert die Quellberichtszeit, `expires_at` wird aus Berichtszeit, horizon, market und dem persistierten `market_phase_summary` berechnet. Die Phasenzusammenfassung behält nur `phase/session_date/minutes_to_open/minutes_to_close`; die Gültigkeitsdauer wird nicht mit dem Speichertag oder Echtzeitkursen neu vergeben.
- Die Invalidierungsreihenfolge gegensätzlicher Signale desselben profiles wird ebenfalls nach dem unveränderlichen `created_at` des Historie-Signals beurteilt; das `updated_at` eines expired refresh ändert die Historie-Priorität nicht. Das Speichern eines alten Berichts darf ein neueres Gegensignal nicht verdrängen; ein historisches item, das noch in der Gültigkeit liegt, aber von einem neueren Gegensignal ersetzt wurde, wird als `invalidated` zurückgegeben, und die API gibt den finalen Datenbankstatus nach der Invalidierungsverarbeitung zurück.
- Ein `created`-item schreibt `source_type=analysis`, die ursprüngliche `source_report_id`, `source_agent=decision_profile_reassess`, `trigger_source=web:decision_profile_reassess` und das formale `decision_profile`; metadata speichert `profile_source=user_selected`, `profile_policy_version`, `signal_generation_version`, `scoring_version`, `scoring_breakdown`, `data_quality_level` und das vollständige `guardrail_result`.
- Ein `existing`-item behält die ursprünglichen source-Felder und metadata unverändert. Beispiel: Wenn die normale Analyse bereits ein `balanced/auto_default`-Signal derselben Identität automatisch erzeugt hat und der Benutzer die balanced-reassess erneut bestätigt, wird dieser Datensatz zurückgegeben, nicht zu `user_selected` überschrieben und kein Erfolg bei der Neuerzeugung behauptet. Ein terminales existing wird nicht reaktiviert.
- Ein `refreshed`-item behält die unveränderliche ursprüngliche Erstellungs-provenance (`source_type`, `source_report_id`, `source_agent`, `trigger_source`, `created_at` usw.) und folgt den zwei bestehenden Teilsemantiken des #1756-repository: expired refresh aktualisiert die änderbaren Entscheidungsfelder, die Gültigkeitsdauer und die Reassess-audit-metadata dieses Durchlaufs; active relaxed dimension-fill füllt nur fehlende horizon/market phase auf und behält die ursprüngliche metadata. Der Client muss das vom Backend zurückgegebene item als maßgeblich ansehen und darf allein aus `refreshed` nicht schließen, dass metadata ersetzt wurde.
- `guardrail_result` sind maschinelle Audit-Daten und zeichnen `raw_action`, `final_action`, `passed`, `violations`, `adjustments`, `adjusted` auf; `warnings` sind eine benutzerlesbare Zusammenfassung. Tests und Client-Logik sollten sich bevorzugt auf den stabilen `code` der warning verlassen; `message` dient nur der Erstversion-Anzeige.
- `MIN_ACTIONABLE_CONFIDENCE = 0.5`. Alle `buy/add` müssen außerdem horizon, invalidation oder stop loss und eine gültige Preisbeziehung haben, und die Datenqualität darf nicht `poor/unknown` sein; aggressives `buy/add` verlangt zusätzlich eine explizite invalidation und akzeptiert kein `long`-horizon.
- Bei fehlender Konfidenz/invalidation oder unzureichender Datenqualität wird auditierbar auf `watch` herabgestuft und `passed=true, adjusted=true` aufgezeichnet. Widersprechen sich die Preisbeziehungen, lässt sich ohne Umschreibung der Historie-Snapshot-Semantik kein gültiger Plan speichern; daher wird `passed=false` aufgezeichnet.
- Ein reines Preview-`passed=false` wird weiterhin mit HTTP 200 angezeigt; die UI muss `blocked_reason` hervorheben. Ergibt die Persist-Neuberechnung `passed=false`, gibt sie HTTP 400 `guardrail_blocked` mit `blocked_reason` und strukturierten `warnings` zurück, schreibt nicht in die Datenbank und gibt kein `created=true` zurück.
- Jede Persist-Neuberechnung muss zuerst `guardrail_result.passed=true` erfüllen, bevor sie in die Schreibkette eintritt; `item.action` von `created/refreshed` entspricht dem `guardrail_result.final_action` dieses Durchlaufs. `existing` gibt den ursprünglichen Datensatz und seine ursprüngliche metadata zurück, ohne dieses guardrail-audit vorzutäuschen.
- Die Standardanalyse und lazy backfill erzeugen weiterhin nur automatisch `balanced`; der Benutzer kann balanced, conservative oder aggressive explizit auswählen und bestätigen, wobei conservative/aggressive nicht automatisch erzeugt werden.
- aggressive ist keine Sampling-Temperatursemantik und erzeugt auch nicht automatisch drei profile-Signale.

## Web-Anzeige

Der Web-Einstieg liegt unter `/decision-signals`:

- Standardabfrage `status=active`.
- Oben auf der Seite gibt es einen seitenweiten Hauptpfad „Aktuelle Aktie", unabhängig von der erweiterten Listenfilterung. Nachdem der Benutzer die Hauptaktie übermittelt, einen Autovervollständigungs-Kandidaten auswählt oder auf einen Kandidaten-chip klickt, teilen sich latest active und Zeitleiste denselben angewendeten Aktienkontext; nur eine Änderung des Eingabeentwurfs löst keine latest- oder Zeitleistenabfrage aus.
- Kandidaten für die aktuelle Aktie zeigen bevorzugt zuletzt analysierte Aktien; gibt es keine historischen Kandidaten oder schlägt das Laden historischer Kandidaten fehl, werden aktive, beliebte Aktien mit hoher Popularität aus dem Aktienindex als Fallback angezeigt. Kandidaten dienen nur als manueller Klick-Einstieg; beim Laden der Seite wird keine Abfrage automatisch übermittelt; sind sowohl Historie als auch Aktienindex nicht verfügbar, wird nur ein Fallback-Text ohne Kandidaten angezeigt.
- Der Kontext der aktuellen Aktie zeigt den angewendeten Code, Namen und ableitbaren Markt und bietet einen Clear-Einstieg. Das Leeren bringt latest und Zeitleiste in den Führungszustand zurück, ohne die erweiterte Listenfilterung oder die Quellendetails-Schublade der Liste zu beeinflussen.
- Unterstützt erweiterte Listenfilterung nach Markt, Aktiencode, Aktion, Marktphase, Quelle, Quellbericht-ID und Status; diese Filter sind nicht mit dem Kontext der aktuellen Aktie gleichzusetzen und verunreinigen auch nicht die latest-active-Abfrage.
- Die Signalleiste einer einzelnen Aktie nutzt die bestehende `GET /api/v1/decision-signals`-list-API wieder; es wird kein timeline-endpoint hinzugefügt. Die Zeitleiste fragt erst ab, wenn eine nicht leere aktuelle Aktie angewendet ist; ohne aktuelle Aktie wird nur der Führungszustand angezeigt, keine market-only- oder globale Zeitleiste abgerufen.
- Die Zeitleiste unterstützt nur die drei Zeitbereiche `30d`, `90d`, `180d`, Standard `90d`; pro Anfrage maximal 100 Einträge. Gibt `total > items.length` zurück, zeigt die Web-Seite „Es werden nur die letzten 100 Signale angezeigt, bitte den Zeitbereich verkleinern", um eine stillschweigend unvollständige Spur zu vermeiden.
- Der Zeitleistenfilter behält ein separates market-, range-, status-Formular und einen Abfragebutton. Bei Auswahl einer neuen aktuellen Aktie wird der Zeitleisten-markt nur dieses eine Mal initialisiert, wenn der Markt ableitbar ist; der Benutzer kann den markt danach manuell ändern, und die Abfrage basiert auf dem Formular-Snapshot zum Zeitpunkt des Button-Submits.
- Der Zeitleisten-status-Filter unterstützt nur `all` und `active`: `all` sendet kein `status`, `active` sendet `status=active`. P1 bietet keinen terminal-status-Filter und keine Frontend-Terminal-Filterung.
- Die Zeitleiste unterstützt einen profile-Filter und nutzt die server-side `decision_profile`-Abfrage der list-API wieder; `unknown` dient nur der Filterung und Anzeige von legacy-`NULL`-Zeilen. Die normale erweiterte Liste erhält keinen neuen profile-Filter.
- Die Signal-Leistungsstatistik behält die Definition der global bereits nachbewerteten outcomes; sie ist nicht gleich der Anzahl der aktuell sichtbaren Signale und ändert sich auch nicht mit der aktuellen Aktie oder der erweiterten Listenfilterung; bei 0 bereits nachbewerteten Stichproben zeigt die Web-Seite einen Null-Stichproben-Leerzustand statt einer Gruppe von `0/-`-Kennzahlen.
- Die Web-Anzeige liest bevorzugt das formale `decision_profile`-Feld und fällt nur bei fehlendem Feld auf legacy-metadata zurück; historische Signale mit fehlendem oder ungültigem profile werden als `unknown` angezeigt, nicht fälschlich als `balanced`.
- Der markt-Filter unterstützt in API/Service-Ebene und Web-Frontend bereits `cn/hk/us/jp/kr/tw`; die Frontend-Lokalisierungslabels für `jp/kr/tw` sind vollständig ergänzt, `tw`-Signale können über die API normal geschrieben, nach `market=tw` abgefragt und auf der Web-DecisionSignal-Seite über den Marktfilter als taiwanische Aktien (tw) ausgewählt werden; Alarme (Ampel) unterstützen die Märkte `cn/hk/us/jp/kr`.
- Die Detailschublade zeigt Aktion, Status, Bewertung, Konfidenz, Periode, Planqualität, Marktphase, Preisplan, Risiko, Beobachtungsbedingungen, Nachweis, Datenqualität und metadata.
- Die Detailschublade oder der Seitenkontext mit einer bestehenden Quellbericht-ID kann ein Reassess-Preview auslösen; ohne verfügbare Quellbericht-ID ist der Einstieg deaktiviert. Das Preview selbst geht nicht in Liste, latest oder Zeitleiste ein; nach dem Passieren des guardrail kann es vom Benutzer in einer zweiten Bestätigung gespeichert werden. Das Speichern fordert erneut `persist=true` an und verwendet nach Erfolg nur das `item` des Backends aus der Antwort; `created`, `existing`, `refreshed` verwenden unterschiedliche Rückmeldungen, existing wird nicht als neu erzeugt beschrieben, terminales existing wird nicht optimistisch in aktive latest/Zeitleiste injiziert, nur created/refreshed werden nach dem zurückgegebenen Status aktualisiert und die zugehörigen Ansichten aufgefrischt. Die Web-Seite fügt das Preview nicht zu einem lokalen Signal zusammen.
- Guardrail-Anpassungs-warnings beim Speichern bleiben angezeigt. Wird die Persist-Neuberechnung durch den guardrail blockiert, zeigt die Web-Seite `blocked_reason` und strukturierte warning, behält das Preview zum Verständnis des Benutzers bei und fügt das fehlgeschlagene Ergebnis nicht der Zeitleiste hinzu.
- Das Analyseformular auf der Startseite bietet kein `decision_profile`; der Standardpfad der automatischen Erzeugung verwendet weiterhin nur `balanced`.
- Die Web-Seite kann Signale nur auf `closed`, `invalidated` oder `archived` setzen und bietet keine Wiederherstellung eines terminalen Status zu active.
- Die Historie-Berichtsdetailseite zeigt Signale vom Typ `source_type=analysis`, die an den Bericht gebunden sind, nicht mehr eingebettet und löst beim Öffnen der Berichtsdetails auch keine `source_report_id`-Signalabfrage aus; zum Anzeigen des Quellsignals eines Berichts geht man einheitlich zur Seite `/decision-signals` und filtert exakt nach der Quellbericht-ID oder öffnet den Deep-Link `/decision-signals?sourceReportId=<recordId>`. Dieser Filter und der Deep-Link verwenden beide eine exakte Abfrage `source_type=analysis + source_report_id`, um den best-effort-Lazy-Backfill-Einstieg alter Berichte zu erhalten.
- Die Positionsseite fragt das neueste aktive Signal jedes eindeutigen Holdings asynchron ab; schlägt die Abfrage eines einzelnen Fehl, wird nur ein Degradationshinweis angezeigt, ohne den Portfolio-Snapshot oder die Signale anderer Positionen zu blockieren.

Alle benutzersichtbaren Enums müssen i18n-Labels verwenden; technische IDs, Aktiencodes, API-Feldnamen, env-keys und URL-Beispiele dürfen Englisch bleiben.

## Decision-Profile-Identität

Nach #1756 ist `decision_profile` das formale nullable Feld von `decision_signals`; metadata behält gleichzeitig Kompatibilitätsfelder:

- `decision_profile=balanced`
- `profile_source=auto_default`: Pfad der normalen Neuanalyse.
- `profile_source=backfill_defaulted`: Lazy-backfill-Pfad historischer Berichte.
- `profile_policy_version=decision-profile-v1`
- `signal_generation_version=legacy-report-extractor-v1`
- `decision_signal_metadata_version=decision-signal-metadata-v1`

- Bei neuen Schreibvorgängen hat das top-level gültige `decision_profile` Vorrang; explizites top-level `null`, leere oder ungültige Werte werden direkt abgelehnt. Nur wenn das top-level fehlt, wird auf gültiges `metadata.decision_profile` zurückgegriffen; fehlen beide oder ist das metadata-profile ungültig, wird standardmäßig `balanced` geschrieben.
- Neue Schreibvorgänge synchronisieren `metadata.decision_profile` auf den formalen Feldwert, um Doppelquellen-Konflikte zu vermeiden; weggelassene oder explizite `null`-metadata werden wie ohne metadata behandelt, object wird flach kopiert, Nicht-object wird abgelehnt.
- Bei PATCH-metadata: Weglassen behält den ursprünglichen Wert, explizites `null` leert auf SQL-`NULL`, object ersetzt das gesamte Paket. Bei formalem profile nicht-`NULL` werden konfligierende Werte in metadata überschrieben; bei formalem profile legacy-`NULL` wird der profile-key aus dem Request-object entfernt und das formale Feld nicht angehoben.
- Automatische Invalidierungsschreibvorgänge folgen ebenfalls der formalen Feldautorität: bei formalem profile nicht-`NULL` wird metadata-profile synchronisiert; bei legacy-`NULL` werden nur Invalidierungsinformationen angehängt, die ursprüngliche legacy-metadata bleibt erhalten, kein profile wird injiziert oder gelöscht.
- Legacy / unknown wird nur über Datenbank-`NULL` dargestellt. Die normale automatische Erzeugung und lazy backfill schreiben kein `scoring_version` oder `scoring_breakdown`; nur der explizit vom Benutzer ausgelöste Reassess-Pfad erzeugt und audit diese Felder nach der profile-policy. Dies bedeutet weder die automatische Erzeugung von drei profiles noch die profile-aware outcome calibration von #1758.
- Lazy-backfill-Semantik: Weggelassenes profile behält den alten Lazy-Backfill von `source_type=analysis + source_report_id`; `decision_profile=balanced` kann balanced-backfill erzeugen; `decision_profile=unknown`, `conservative`, `aggressive` erzeugen keine Zeilen automatisch. Backfill und Reassess-Persist teilen sich Quellberichtszeit, Historie-TTL und superseded-Beurteilung; es gibt keinen zweiten Historie-Lebenszyklus.

## Marktstruktur-metadata

Wenn die normale Einzelaktien-Analyse und die Agent-Einzelaktien-Analyse `market_structure_context` mitführen, hängt die automatische DecisionSignal-Extraktion die folgenden niedrig-sensiblen Felder an metadata an:

- `market_structure_version`
- `market_theme_version`
- `stock_market_position_version`
- `market_structure_status`
- `primary_theme`
- `theme_phase`
- `stock_role`
- `market_structure_risk_tags`

Diese Felder dienen nur der Erklärung des Themenumfelds des Signals; sie beteiligen sich nicht an der Berechnung von `action`, `score`, `horizon`, dem Same-Source-Dedupe-Schlüssel oder dem Lebenszyklus. Sie sind auch kein Beweis einer Themenführerschaft; wenn `market_structure_risk_tags` oder fehlende Nachweise zeigen, dass Bestandteile, leader stocks unvollständig sind, sollten Client und nachträgliche Analyse dies als degradierten Themen-Nachweis behandeln.

`provider` / `dataset` in den Snapshot-Feldern stammen aus den Metadaten der Marktstruktur-Extraktionskette und sind persistierte Nachweise nach der Ausführung; sie beteiligen sich nicht an LLM-provider/model-Routing, `base URL`-Auflösung, `.env`-Rückschreibung oder Konfigurationsmigration; der verifizierbare Umfang siehe `src/schemas/market_structure.py`.

## Alarm, Benachrichtigung und Portfolio-Risiko

- Ein echter aktiver Aktienalarm verknüpft bevorzugt das neueste aktive Signal desselben Ziels und schreibt das niedrig-sensible `decision_signal_summary` in `alert_triggers.diagnostics`.
- Ohne aktives Signal erzeugt der Alarm-worker nur ein minimales `source_type=alert/action=alert`-Signal.
- `trace_id=alert-rule-<hash>` des Alarmsignals dient nur dem best-effort-Dedupe von Same-Source-Wiederholungen und überschreibt nicht den aktiven Signalbestand selbst.
- Benachrichtigungen referenzieren nur öffentliche Zusammenfassungsfelder: `action`, `horizon`, `reason`, `watch_conditions`, `risk_summary`, `source_report_id`.
- `reason` in Benachrichtigungen wird nach der Redaktion vollständig angezeigt, um ein Abschneiden fester Zeichenanzahl im Satz zu vermeiden; `watch_conditions` und `risk_summary` behalten weiterhin ein kompaktes Zusammenfassungslimit.
- Benachrichtigungen dürfen kein Signal-`metadata`, kein `evidence`, keine rohen diagnostics, keine webhook-URL, kein token und kein cookie ausgeben.
- `decision_signal_risk` von `GET /api/v1/portfolio/risk` zählt nur aktive `sell/reduce/alert`-Signale der aktuellen Positionen; bei Abfragefehler fail-open.

Weitere Details zu Alarmen und Benachrichtigungen siehe `docs/alerts.md` und `docs/notifications.md`.

## Nachträgliche Bewertung und Feedback

P5 speichert Benutzerfeedback und nachträgliche Ergebnisse über sidecar-Tabellen, ohne die Haupttabelle `decision_signals` zu erweitern:

- `decision_signal_feedback` speichert das neueste `useful|not_useful`-Feedback jedes Signals, optional Grund/Bemerkung und Quelle.
- `decision_signal_outcomes` speichert nachträgliche Bewertungsergebnisse idempotent nach `(signal_id, horizon, engine_version)`.
- Aktuell `engine_version=decision-signal-v1`.
- Die nachträgliche Bewertung unterstützt nur die tagesbalkenverifizierbaren `1d/3d/5d/10d`; `intraday/swing/long`, nicht-direktionale Aktionen, fehlende Preise und unzureichende forward-bars schreiben `eval_status=unable` und einen klaren `unable_reason`.
- Bei der Bewertung werden action, market, market_phase, source_type, source_agent, plan_quality, data_quality_level, holding_state und andere statistische Dimensionen eingefroren; historische Statistiken hängen nicht von späteren live joins ab.

## Redaktions- und Niedrig-Sensibilitätsgrenzen

Signalwrites und Statusaktualisierungen verwenden `sanitize_decision_signal_text()` und `sanitize_decision_signal_payload()` aus `src/utils/sanitize.py`:

- Textfelder, JSON-Felder und anzeigefähige kurze Texte werden vor dem Schreiben redigiert.
- Abdeckung von sensiblen keys, Bearer, Authorization/Cookie-Headern oder Zuweisungen, token-ähnlichen Zeichenketten, webhook-URLs, URL-userinfo sowie URLs mit sensiblen query/fragment-Parametern.
- Gewöhnliche Nachweis-URLs bleiben erhalten, um die Rückverfolgbarkeit der Quelle zu gewährleisten.
- `trace_id` ist das Identitätsfeld für Same-Source-Dedupe; enthält es Credentials, die redigiert würden, lehnt die API den Request ab, statt den durch die Redaktion beschädigten Identitätswert zu speichern.
- Die JSON-Anzeige der Web-Seite zeigt nur die bereits redigierten Backend-Daten und sollte keine rohen diagnostics oder Konfigurationswerte neu zusammensetzen.

Die globale Abnahme von P7 bestätigt, dass Signalpools, Benachrichtigungszusammenfassungen und Web-Anzeige kein token, kein cookie, keine webhook-URL, keinen API-Key, kein E-Mail-Passwort und andere sensible Informationen preisgeben.

## Migration und Rollback

#1756 führt eine nicht-destruktive Migration für SQLite durch.

Migrationserläuterung:

- Nach dem Upgrade sind keine neuen `.env`, `.env.example` oder Web-Einstellungspunkte erforderlich.
- Existing SQLite führt nur bei fehlender Spalte `ALTER TABLE ADD COLUMN decision_profile` aus; es droppt/rebuildet `decision_signals` nicht und löscht auch keine alten Indexe.
- Die Migration erzeugt profile-aware Indexe idempotent und parst `metadata_json` zeilenweise defensiv: nur gültiges `metadata.decision_profile` wird in das formale Feld backgefüllt; invalid JSON, Nicht-object oder ungültige profiles bleiben `NULL`. Das Startprotokoll protokolliert Statistiken zu backfilled, invalid JSON, non-object, invalid profile und skipped existing profile; diese Statistiken dienen nur der Diagnose und blockieren den Start nicht.
- Alte historische Berichte werden nicht in Stapeln backgefüllt. Nur wenn die Signalliste-Schnittstelle explizit aufgerufen wird oder auf der Web-AI-Empfehlungsseite eine exakte Abfrage `source_type=analysis + source_report_id` nach Quellbericht-ID ausgelöst wird und kein Treffer vorliegt, erfolgt ein best-effort-Lazy-Backfill.
- Bereits vorhandene `decision_signals`-, feedback- und outcome-Daten bleiben kompatibel.

Rollback-Erläuterung:

- Es gibt derzeit keinen `DECISION_SIGNAL_*`-Schalter; der Rollback zum Deaktivieren von Signalextraktion/-schreiben ist der Revert des zugehörigen Codes.
- Nach dem Rollback laufen das Speichern normaler Berichte, die Alarmauslösung, der Benachrichtigungsversand und der Hauptablauf des Portfolio-Risikos weiter über die bestehenden Pfade.
- Der Rollback löscht historische `decision_signals`, `decision_signal_feedback` oder `decision_signal_outcomes`-Daten nicht automatisch; bei Bedarf sollte der Maintainer separat eine Datenbereinigungsstrategie festlegen.
