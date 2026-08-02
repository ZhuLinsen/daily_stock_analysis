# Integrierte Screening-Engine

DSA pflegt die Screening-Fähigkeiten als Teil des Hauptprojekts. Die Implementierung orientiert sich an [AlphaSift](https://github.com/ZhuLinsen/alphasift) im Commit [`9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf`](https://github.com/ZhuLinsen/alphasift/commit/9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf) und wird gemäß Apache License 2.0 modifiziert und vertrieben. Abgeleitete Dateien behalten die Quellen-Header; die Lizenz liegt unter `src/services/screening/LICENSE`, Drittanbieter-Angaben finden sich in der Datei `THIRD_PARTY_NOTICES.md` im Wurzelverzeichnis.

## Codegrenzen

- `src/services/screening/`: Snapshot, Tages-K, Strategieladung, Filterung, Scoring, Risiko, LLM-Reranking und Hotspot-Implementierung.
- `src/services/screening/strategies/`: Mit den DSA-Versionen veröffentlichte Strategie-YAMLs.
- `src/services/screening/pipeline.py`: Direkter Einstiegspunkt der integrierten Screening-Pipeline.
- `src/services/screening_service.py`: DSA-Business-Orchestrierung, ruft die Pipeline direkt auf und ist für Konfiguration, Datenquellenkontext, Antwortnormalisierung, Caching und Fehlerzuordnung zuständig.
- `src/storage.py`: Persistiert abgeschlossene Screening-Läufe über die bestehende SQLAlchemy/SQLite-Infrastruktur von DSA, ohne eine separate Dateidatenbank anzulegen.
- `api/v1/endpoints/screening.py`: Die `/api/v1/screening`-API.
- `apps/dsa-web/src/api/screening.ts` und `StockScreeningPage.tsx`: Web-Aufruf und -Anzeige.

Die Serviceschicht ruft `screening.pipeline`, `screening.strategy` und `screening.hotspot` statisch auf. Die Kernlogik nutzt keine Modulnamen-Detektion, keine dynamischen Adapter und keine mehrfachen Routing-Verteilungen; daher werden Codestruktur, Fehlergrenzen und Verpackungs-Sammeleinstellungen direkt vom Hauptprojekt definiert.

## Konfiguration

Standardmäßig deaktiviert:

```dotenv
SCREENING_ENABLED=false
```

Häufige Optionen:

```dotenv
SCREENING_DATA_DIR=data/screening
SCREENING_SOURCE_CALL_TIMEOUT_SEC=
SCREENING_SNAPSHOT_CALL_TIMEOUT_SEC=60
SCREENING_DAILY_CALL_TIMEOUT_SEC=20
SCREENING_EASTMONEY_MIN_INTERVAL_SEC=1.0
SCREENING_EASTMONEY_JITTER_SEC=0.3
```

Pfad-, Timeout- und Rate-Limiting-Einträge betreffen nur die integrierte Screening-Kette. Das vollständige Beispiel richtet sich nach `.env.example`.

## API-Vertrag

| Pfad | Methode | Verhalten |
| --- | --- | --- |
| `/api/v1/screening/status` | GET | Gibt Schalter, Engine-Status, Vertragsversion, Referenzprojekt und Datenquellen-Health-Informationen zurück |
| `/api/v1/screening/strategies` | GET | Gibt integrierte Strategien zurück |
| `/api/v1/screening/hotspots` | GET | Liest den Cache oder aktualisiert Hotspot-Themen explizit |
| `/api/v1/screening/hotspots/{topic}` | GET | Gibt Themenrouten, Komponentenaktien und Kernaktien zurück |
| `/api/v1/screening/screen` | POST | Führt das Screening synchron aus |
| `/api/v1/screening/screen/tasks` | POST | Reicht Hintergrund-Screening-Aufgaben ein |
| `/api/v1/screening/screen/tasks/{task_id}` | GET | Fragt Aufgabenfortschritt, Fehler oder Endergebnis ab |
| `/api/v1/screening/history` | GET | Fragt Zusammenfassungen der letzten abgeschlossenen Screening-Läufe nach Strategie und Markt ab |
| `/api/v1/screening/history/{run_id}` | GET | Liest einen einzelnen vollständig persistierten Screening-Ergebnislauf |
| `/api/v1/screening/source-history` | GET | Aggregiert Snapshot-Quellentreffer, Fehler und Degradierungszahlen über historische Läufe |

Hintergrundaufgaben verwenden `report_type=screening_screen`; die Web-App speichert die ID der aktiven Aufgabe und pollt bei der Seitenwiederherstellung weiter. Die Aufgabenwarteschlange bleibt für den Laufzeitfortschritt zuständig; nach Abschluss wird das Ergebnis zusätzlich in die DSA-Datenbank geschrieben, sodass es nach einem Dienstneustart weiterhin über `run_id` abfragbar ist.

## Kernablauf

```text
Strategieladung
  -> Gesamtmarkt-Snapshot und Feldnormalisierung
  -> Harte Filterung
  -> Faktor-Scoring und Risikoadjustierung
  -> Kandidatenkontext-Ergänzung
  -> LLM-Reranking (degradierbar)
  -> Top-Kandidaten: DSA Kursdaten/Fundamentaldaten/Nachrichten-Anreicherung
  -> API-normalisierte Antwort und Persistierung in der DSA-Datenbank
  -> Nutzer wechselt bei Bedarf in die DSA-Tiefenanalyse einzelner Aktien
```

- Der Gesamtmarkt-Snapshot versucht es gemäß der konfigurierten Datenquellenpriorität; nach einem Fehlschlag einer einzelnen Datenquelle wird degradiert weitergeführt, dabei werden Source-Health und Last-Good-Cache protokolliert.
- Mit `TUSHARE_TOKEN` wird standardmäßig Tushare bevorzugt, sonst standardmäßig bei Sina gestartet; ein explizites `SNAPSHOT_SOURCE_PRIORITY` hat immer Vorrang.
- Bei der Tages-K wird bevorzugt die historische DSA-Kursdatenkette wiederverwendet; gibt es kein Ergebnis, greift die Datenquellen-Degradierung der Screening-Engine.
- Vor dem LLM-Reranking wird nur begrenzter Kandidatenkontext ergänzt; die Endkandidaten erhalten anschließend Kursdaten, Fundamentaldaten, Nachrichten und Zusammenfassungen, um die Anfragemenge zu begrenzen.
- Modell, Kanal, base URL, zusätzliche Header, Fallback, Timeout und Token-Obergrenze werden im Umfang eines einzelnen Aufrufs injiziert, ohne die Nutzerkonfiguration zu überschreiben.
- Schlägt eine Echtzeit-Hotspot-Anfrage fehl, wird bevorzugt der Last-Good-Cache verwendet; ohne Cache wird ein stabiler Leerzustand mit klarer Fehlermeldung zurückgegeben.

## Caching und Persistierung

| Daten | Ort | Gültigkeit/Verhalten |
| --- | --- | --- |
| Gesamtmarkt-Snapshot | `data/screening/snapshot.last_good.json` | Wird verwendet, wenn alle Echtzeitquellen fehlschlagen; unterliegt einer maximalen Altersbeschränkung und wird als stale/fallback markiert |
| Einzelaktien-Tages-K | `data/screening/daily_history/` | Nach Code, Quelle und Rückschaufenster abgelegt, Standard-TTL 24 Stunden; bei vollständigem Ausfall der Echtzeitquellen kann abgelaufener Cache verwendet und als stale markiert werden |
| Branchen-/Konzept-Zuordnung | `data/screening/industry_provider_cache/` | Standard-TTL 24 Stunden; speichert zusätzlich die Sektor-Hitze-Historie für Trendberechnungen |
| Hotspot-Liste und -Historie | `data/screening/hotspots.json`, `hotspot.history.jsonl` | Schreiben bei explizitem Refresh; bei Echtzeit-Fehlschlag Rückfall auf den letzten verfügbaren Snapshot |
| Hotspot-Details | `data/screening/hotspot_details/` | Standard-TTL 30 Minuten; bei Echtzeit-Fehlschlag kann auf abgelaufene Details zurückgegriffen und das Alter der Daten zurückgegeben werden |
| DSA-Echtzeit-Kursdaten | Kursdaten-Cache des `DataFetcherManager` | Standard-TTL 10 Minuten, übernimmt `REALTIME_CACHE_TTL` |
| DSA-Fundamentaldaten/Kapitalfluss | Fundamentaldaten-Cache des `DataFetcherManager` | Standard-TTL 120 Sekunden, übernimmt `FUNDAMENTAL_CACHE_TTL_SECONDS` |
| DSA-Nachrichten/Meldungsereignisse | In-Memory-Cache des `SearchService` | Erfolgreiche Ergebnisse Standard-TTL 10 Minuten; nach Dienstneustart werden sie erneut abgefragt |
| Vollständiges Screening-Ergebnis | DSA-Datenbank, Tabelle `screening_runs` | Nach Abschluss idempotent über `run_id` geschrieben; ein Datenbankschreibfehler blockiert den Screening-Hauptablauf nicht |

Das Kandidatenkontext-Modul unterstützt zusätzlich einen 24-Stunden-Datei-Cache, doch die DSA-Integration deaktiviert standardmäßig dessen eigenständiges Abrufen von Nachrichten/Meldungen und nutzt stattdessen die eigenen Nachrichten-, Fundamentaldaten- und Echtzeit-Kursdaten-Ketten von DSA, um zu vermeiden, dass dieselben Kandidaten zwei Datenquellen-Sätze doppelt anfragen.

## Grenze zwischen den beiden Strategietypen

In DSA existieren zwei Strategiedateien mit unterschiedlichen Zwecken:

| Ort | Gelöstes Problem | Laderseite | Ausführungsphase |
| --- | --- | --- | --- |
| `src/services/screening/strategies/*.yaml` | Welche Kandidaten aus dem Gesamtmarkt gefiltert werden | `src/services/screening/strategy.py` | Snapshot-Filterung, Faktor-Scoring, Risiko und Sortierung |
| `strategies/*.yaml` | Wie eine einzelne Aktie analysiert und zu einer Schlussfolgerung geführt wird | `src/agent/skills/base.py` | DSA-Agent-/Berichtanalyse |

Selbst bei gleichem Namen wie `shrink_pullback` oder `volume_breakout` verwenden beide unterschiedliche Verzeichnisse, Schemas und Loader und überschreiben sich nicht gegenseitig. Screening-Strategien können über `analysis_skills` die für die nächste Phase empfohlenen DSA-Analyse-Skills deklarieren; die Web-Schaltfläche "Mit DSA tief analysieren" trägt diese Skills explizit mit. Screening-Strategien ohne deklarierte Zuordnung verwenden weiterhin die aktuell ausgewählte Strategie des Nutzers oder die DSA-Standard-Analysestrategie, ohne eine unzuverlässige Zwangszuordnung vorzunehmen.

## Wiederverwendung nativer DSA-Fähigkeiten

- Kursdaten: Bei der Tages-K wird bevorzugt der DSA-`DataFetcherManager` aufgerufen; nur ohne Ergebnis greift der eigene Multi-Quellen-Fallback des Screening-Moduls; die Endkandidaten werden weiterhin mit DSA-Echtzeit-Kursdaten ergänzt.
- Fundamentaldaten und Nachrichten: Die Endkandidaten nutzen den DSA-Fundamentaldatenkontext und den `SearchService` wieder; der Kapitalfluss stammt aus dem DSA-Fundamentaldatenkontext, wichtige Meldungs-/Gewinn-/Veräußerungsereignisse rufen DSA `search_stock_events` auf, ohne einen separaten eigenen Nachrichtenzugang zu pflegen.
- Modell: Übernommen werden die DSA-LiteLLM-Modelle, Kanäle, Fallback, base URL, zusätzliche Header, Timeout und Token-Konfiguration.
- Aufgaben und Seiten: Wiederverwendet werden die DSA-Hintergrundaufgabenwarteschlange, das Web-Polling und die gleichnamigen Web-Ressourcen des Desktop-Clients.
- Speicherung und Folgeanalyse: Laufergebnisse werden in die DSA-Datenbank geschrieben; Kandidaten können in die native DSA-Einzelaktienanalyse wechseln und tragen dabei die Strategie-Skills mit.

Im Vergleich zum festen Referenz-Commit sind Snapshot, Tages-K, US-Aktien, Branchen/Konzepte, Hotspots, Kandidaten-Nachrichten/Meldungen/Kapitalfluss, Feldnormalisierung, Filterung, Scoring, Risiko, Sortierung und Datenquellen-Circuit-Breaker als rohe Daten- und Screening-Fähigkeiten vollständig übernommen; darunter werden Meldungen/Ereignisse und Kapitalfluss in der DSA-Orchestrierungsschicht jeweils an die native Ereignissuche und den Fundamentaldatenkontext angeschlossen. Das Referenzprojekt bietet darüber hinaus einen separaten CLI/Server, einen JSON-Datei-Store, Berichts-Rendering, Doctor, Lauf-/Datenquellen-Historie und T+N-Bewertung: Diese Implementierung übernimmt nur die Betriebshistorie und Datenquellen-Historie, die DSA tatsächlich fehlen, und schließt sie an die DSA-Datenbank an; CLI/Server werden nicht doppelt aufgebaut, T+N-Bewertung und Performance-Statistiken nutzen weiterhin den bestehenden DSA-`BacktestService`, um eine zweite Backtest-Wahrheitsquelle zu vermeiden. Die Echtzeit-Source-Health wird bereits über `/status` zurückgegeben, die historische Stabilität wird über `/source-history` ergänzt.

## Nutzen

1. Screening-Service, Strategien, API, Web und Verpackungsskripte entwickeln sich in derselben Version weiter und vermeiden Vertragsdrift.
2. Die Serviceschicht hat nur einen nativen Aufrufpfad; Statusproben und Business-Anfragen spiegeln dieselbe Implementierung wider.
3. Docker- und Desktop-Artefakte sammeln direkt dieselben Modul- und Strategieressourcen, das Deployment-Ergebnis ist konsistenter.
4. Datenquellen-Degradierung, Scoring und Strategieänderungen können im Haupt-Repository vollständig überprüft und regressionstestet werden.
5. Quell-Commit, Lizenz und dateiweise Zuordnung sind klar, sodass Upstream-Fixes später gezielt synchronisiert werden können.

## Risiken und Kontrollen

| Risiko | Auswirkung | Kontrollmaßnahme |
| --- | --- | --- |
| Größere Pflegefläche des Haupt-Repositorys | Datenquellen- oder Strategieprobleme werden von DSA direkt getragen | Modulgrenzen, Vertragstests und CI-Verpackungsproben wirken zusammen |
| Zunehmende Abweichung vom Referenzprojekt | Upstream-Fixes lassen sich nicht direkt übernehmen | Festes Referenz-Revison, Modul-für-Modul-Vergleich und selektive Portierung |
| Rate-Limiting oder Feldänderungen bei Datenquellen | Degradierung von Snapshot, Hotspots oder Tages-K | Timeout, Retry, Source-Health und Last-Good-Cache |
| LLM-Timeout oder Formatfehler | Reranking unverfügbar oder Erklärfelder fehlen | Faktor-Sortierung beibehalten, Parse-Error und Warning protokollieren |
| Änderung der Cache-Verzeichnisse | Alte Caches werden nach dem Upgrade nicht automatisch wiederverwendet | Neues Verzeichnis ist unabhängig als `data/screening`; vor dem Upgrade bei Bedarf sichern |
| Wachstum der Lauferstellung | Vollständige Kandidatenergebnisse vergrößern die Datenbank | Historische Schnittstellen lesen standardmäßig nur Zusammenfassungen; der Betrieb kann nach bestehender DB-Sicherungs-/Aufbewahrungsstrategie verwalten |
| Umbenennung von Konfiguration und API | Alte Automatisierung muss angepasst werden | `SCREENING_ENABLED` und `/api/v1/screening` in den Release-Hinweisen klar benennen |
| Lizenzattributionslücke | Compliance-Risiko bei der Veröffentlichung | LICENSE, THIRD_PARTY_NOTICES und abgeleitete Datei-Header beibehalten |

Screening-Ergebnisse dienen nur der Recherche und unterstützenden Einschätzung, stellen keine Anlageberatung dar und garantieren weder Rendite noch Datenvollständigkeit.

## Referenzimplementierung aktualisieren

AlphaSift ist eine Referenzquelle, keine automatische Synchronisationsquelle. Bei Updates gilt:

1. Ziel-Commit und Lizenzänderungen dokumentieren;
2. die DSA-spezifischen Änderungen in `src/services/screening/` vergleichen und Modul für Modul selektiv portieren;
3. abgeleitete Datei-Header, `REFERENCE_REVISION` und `THIRD_PARTY_NOTICES.md` aktualisieren;
4. Pipeline, API/Web-Felder, Datenquellen-Degradierung, Strategieressourcen und eingefrorene Verpackung prüfen;
5. dieses Dokument und `docs/CHANGELOG.md` aktualisieren, anschließend Backend-, Web- und Docker-/Desktop-Verifikation durchführen.

## Rollback

- Business-Rollback: `SCREENING_ENABLED=false` setzen und neu starten; normale Einzelaktienanalyse, Berichte, Benachrichtigungen und die Fragen-Funktion bleiben unberührt.
- Code-Rollback: Den Commit revertieren, der die integrierte Engine eingeführt hat, und Backend, Docker und Desktop-Artefakte neu bauen.
- Daten-Rollback: Falls Screening-Caches und Lauferstellung erhalten bleiben sollen, zuerst `data/screening/` und die DSA-Datenbank sichern; ein Code-Rollback löscht die Nutzerdaten in `screening_runs` nicht aktiv.
