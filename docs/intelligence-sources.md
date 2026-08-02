# MVP für Informations-/Nachrichtenquellen

Die erste Version von Issue #1707 konzentriert sich auf "konforme Erfassung von Nachrichtenquellen, lokale Speicherung und abfragbare Belege" und vermischt RSS/Atom nicht mit der Semantik der bedarfsgerechten Suche und fügt auch nicht standardmäßig eine separate Stimmungs-/Medienseite hinzu.

## Funktionsumfang

- Unterstützt die Konfiguration von RSS-/Atom-HTTP(S)-Quellen.
- Unterstützt NewsNow-HTTP-JSON-Quellen; standardmäßig sind gängige Finanzquellen wie CLS Trending, Xueqiu-Hot-Stocks, Wallstreetcn-Schnellnachrichten, Jin10-Daten und Gelonghui-Ereignisse integriert.
- Unterstützt die Abfrage integrierter RSS/Atom/NewsNow-Vorlagen und erlaubt es, aus einer Vorlage testbare, start- und stoppbare Nachrichtenquellen zu erstellen; ebenso lassen sich alle integrierten Standardquellen per Klick anlegen.
- Speichert Quellkonfiguration, Aktivierungsstatus, Geltungsbereich und den Status des letzten Abrufs.
- Abgerufene Einträge werden in `intelligence_items` gespeichert: Titel, Zusammenfassung, URL, Quelle, Veröffentlichungszeit, Abrufzeit, Markt und Geltungsbereich.
- Deduplizierung über die URL; Einträge ohne URL verwenden den Fallback-Schlüssel `no-url:intel:<hash>`.
- Unterstützt Geltungsbereiche `symbol` / `market` / `sector` sowie Marktkennzeichen `cn` / `hk` / `us` / `jp` / `kr` / `tw` / `global`.
- Der Abruf-Batch verwendet Fail-open: Ein fehlgeschlagener einzelner Feed blockiert weder andere Feeds noch die Haupt-Analysekette.
- Unterstützt eine Retention-Bereinigung, um ein unbegrenztes Wachstum des Nachrichtenpools zu vermeiden.

## Sicherheitsgrenzen

Benutzerdefinierte URLs durchlaufen eine Basisvalidierung:

- Es sind nur absolute `http`-/`https`-URLs erlaubt.
- URLs mit username/password sind untersagt.
- `localhost`, `.local`, Loopback-Adressen, interne Adressen, Link-Local-Adressen, Reservierte Adressen, Shared-Adressbereiche und Multicast-Adressen sind verboten.
- In den Phasen Auflösung und Abruf werden Umgebungsproxys (wie `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`) explizit deaktiviert, um zu verhindern, dass die Validierungsgrenze über Umgebungsproxys umgangen wird.
- In der Verbindungsphase wird das DNS-Auflösungsergebnis des Ziel-Hosts erneut geprüft, um zu vermeiden, dass die Auflösung nach der Validierung zu eingeschränkten Adressen driftet.
- Auch die finale URL nach Weiterleitungen wird erneut validiert.
- Fehlermeldungen maskieren gängige `token`- / `key`- / `secret`-Query-Parameter.

Ausdrücklich kein Ziel: kein Anti-Scraping, kein simulierter Login, kein Cookie-Auslesen und kein direkter Abruf nicht autorisierter Portale.

## Konfigurationseinträge

```env
NEWS_INTEL_RETENTION_DAYS=30
NEWS_INTEL_FETCH_TIMEOUT_SEC=8
NEWS_INTEL_MAX_ITEMS_PER_SOURCE=50
NEWS_INTEL_AUTO_FETCH_ENABLED=false
NEWSNOW_BASE_URL=https://newsnow.busiyi.world
```

`NEWSNOW_BASE_URL` wird verwendet, um `GET {NEWSNOW_BASE_URL}/api/s?id=<source_id>` zusammenzusetzen.

`NEWS_INTEL_AUTO_FETCH_ENABLED` ist standardmäßig deaktiviert. Nach dem Setzen auf `true` führen Einzelaktien-Analyse, Agent-Analyse und Markt-Review vor dem Lesen des lokalen Nachrichtenpools einen Fail-open-Auto-Refresh aus: Fehlende integrierte Nachrichtenquellen werden automatisch erstellt und aktiviert, vorhandene, aber deaktivierte integrierte Standardquellen werden reaktiviert, anschließend werden alle aktivierten Quellen abgerufen und in `intelligence_items` geschrieben. Um zu vermeiden, dass für jede Aktie erneut externe Seiten angefragt werden, gilt innerhalb des laufenden Prozesses eine Abkühlzeit von 60 Minuten; innerhalb dieser Zeit werden die lokalen Datenbankdaten wiederverwendet.

**Hinweis zur Kompatibilität externer Abhängigkeiten:**

- **Offizielles Projekt und Deployment-Anleitung**: https://github.com/qqhann/newsnow
- **Der aktuelle Standardwert** `https://newsnow.busiyi.world` ist eine öffentliche Beispielinstanz, **kein offizielles Deployment**, und birgt folgende Risiken:
  - Sie kann durch offizielle Wartung, Rate-Limiting oder die Einstellung des Dienstes unverfügbar werden.
  - Es wird keine Stabilität, Zuverlässigkeit oder Datenkorrektheit garantiert; die Instanz dient nur der Vorführung und dem Test.
  - Alle Nutzer zeigen auf dieselbe öffentliche Instanz, was zu Rate-Limiting führen kann.
- **Starke Empfehlung für die Produktion**: Eine eigene NewsNow-Instanz betreiben oder eine bestätigt kontrollierbare private/unternehmensinterne Bereitstellung anbinden, um Stabilität und Datenzuverlässigkeit sicherzustellen.

**Verifikation der API-Vertragskompatibilität (vor dem Deployment zwingend):**

- Grundlegende Erreichbarkeit und Rückgabeformat prüfen:
  ```bash
  curl -sS "${NEWSNOW_BASE_URL}/api/s?id=cls-hot" | python -c "import sys, json; data=json.load(sys.stdin); assert isinstance(data, dict) and isinstance(data.get('items'), list); print('OK')"
  ```
- Die Feldkompatibilität im Detail kann anhand des automatisierten Tests `test_newsnow_source_fetches_json_items` geprüft werden; abgedeckt sind u. a. `status`, `id`, `items[].title`, `items[].url`/`mobileUrl`, `items[].pubDate`/`items[].extra.date`.
- **Die Deployment-Instanz liegt nicht im Umfang der automatisierten Freigabeprüfung**; wenn man sich auf die öffentliche Beispielinstanz verlässt, muss die obige Verifikation vor dem Deployment zwingend in der tatsächlichen Produktionsumgebung durchgeführt werden.

## API

Alle Schnittstellen befinden sich unter `/api/v1/intelligence`.

- `POST /sources`: Erstellt eine Nachrichtenquelle.
- `GET /sources`: Fragt Nachrichtenquellen ab.
- `GET /sources/templates?market=hk`: Fragt Vorlagen integrierter Nachrichtenquellen ab.
- `POST /sources/templates/{template_id}`: Erstellt eine Nachrichtenquelle aus einer integrierten Vorlage; Name, Aktivierungsstatus, Geltungsbereich und Beschreibung können überschrieben werden.
- `POST /sources/defaults`: Erstellt per Klick alle integrierten Standardquellen; die Schnittstelle ist idempotent, vorhandene gleichnamige Quellen geben `created=false` zurück und werden nicht erneut angelegt. Wird kein `enabled` übergeben, werden sie standardmäßig mit `false` erstellt; für eine standardmäßige Aktivierung kann `{ "enabled": true }` übergeben werden.
- `POST /sources/test`: Testet die Payload, ohne sie zu speichern.
- `POST /sources/{source_id}/fetch?dry_run=false`: Ruft eine einzelne Quelle ab.
- `POST /sources/fetch-enabled`: Ruft Fail-open alle aktivierten Quellen ab.
- `GET /items?scope_type=market&market=cn&days=7`: Fragt Nachrichteneinträge ab.

Wenn in der lokalen `.env`, unter Docker oder in anderen Laufumgebungen mit explizit durchgereichten Umgebungsvariablen automatisch "Quelle anlegen -> abrufen -> speichern -> analysieren und konsumieren" ablaufen soll, setzen Sie:

```env
NEWS_INTEL_AUTO_FETCH_ENABLED=true
```

Dieser Schalter bedeutet, dass der Nutzer ausdrücklich zustimmt, dass die Laufzeit auf die konfigurierten externen RSS/Atom/NewsNow-HTTP-Quellen zugreift; er ist standardmäßig aus, um unbestätigte externe Anfragen, Last auf der öffentlichen NewsNow-Beispielinstanz und Veränderungen der Analyse-Prompts zu vermeiden.

> Hinweis: Der Schalter wirkt nur, wenn er in den Umgebungsvariablen des tatsächlich ausführenden Prozesses sichtbar ist. Die im Repository mitgelieferte `00-daily-analysis.yml` verwendet für `env` eine Allowlist-Mapping-Strategie; wird eine Variable nicht explizit in das Mapping aufgenommen, wird sie selbst dann nicht in die Laufumgebung injiziert, wenn sie in den Repository-Variables/Secrets gesetzt ist. Daher empfängt der Standard-Workflow diesen Schalter nicht automatisch. Um diese Funktion im mitgelieferten Tagesanalyse-Workflow zu aktivieren, müssen Sie die Variable explizit im Workflow durchreichen oder die Umgebungsvariablen direkt lokal/per Docker konfigurieren.

## NewsNow-Standardquellen

NewsNow ist kein RSS, sondern eine aggregierte Trend-Plattform. DSA liest die JSON-Antworten direkt über die HTTP-API, ohne dass MCP erforderlich ist:

```text
GET {NEWSNOW_BASE_URL}/api/s?id=cls-hot
```

Dieser PR bindet zunächst die folgenden finanzbezogenen Standardquellen an, damit die Kette "Quellenkonfiguration -> Abruf -> Speicherung -> Analyse lesen" durchläuft:

- `cls-hot`: CLS Trending, eher A-Aktien und thematische Trends.
- `xueqiu-hotstock`: Xueqiu-Hot-Stocks, eher Einzelaktien-Aufmerksamkeit.
- `wallstreetcn-quick`: Wallstreetcn-Schnellnachrichten, eher Makro, Rohstoffe und Marktereignisse.
- `jin10`: Jin10-Daten, eher globale Makro- und Auslandsmarktereignisse.
- `gelonghui`: Gelonghui-Ereignisse, eher Hongkong-Aktien- und China-Concept-Stock-Kontext.

Wenn weitere inländische Plattformen benötigt werden, können über `POST /sources` manuell weitere NewsNow-Quellen hinzugefügt werden, mit `source_type=newsnow` und der `url` `https://<your-newsnow>/api/s?id=<source_id>`. Falls RSS bevorzugt wird, können auch konforme RSS-Quellen wie RSSHub über `source_type=rss` angebunden werden.

## Empfehlungen für spätere Anbindungen

Auf der Basis der ersten Version liest die Analyse-Kette den lokalen Nachrichtenpool best-effort:

- Die traditionelle Einzelaktien-Analyse liest bevorzugt Nachrichten zu `symbol=<Aktiencode>` und ergänzt `market`-bezogene Nachrichten des gleichen Marktes; der Inhalt wird an den bestehenden `news_context` angehängt und zusammen mit der AnalysisContextPack-Zusammenfassung und dem historischen `news_content` gespeichert.
- Auch die Agent-Analyse injiziert lokale Nachrichtenbelege über `news_context`, sodass der Agent nicht erneut suchen muss, um die bereits gespeicherten Nachrichten zu sehen.
- Das Markt-Review führt `market`-bezogene Nachrichten des gleichen Marktes in die Marktnachrichtenliste zusammen; Prompt, strukturierte Payload und das Nachrichtenfeld des Berichts zeigen Quellenlinks.
- Wenn `NEWS_INTEL_AUTO_FETCH_ENABLED=true` gesetzt ist, führt der oben genannte Einstiegspunkt zuerst einen Fail-open-Auto-Refresh des lokalen Nachrichtenpools aus; ein fehlgeschlagener Refresh blockiert die Analyse nicht.
- Diese Funktion fügt nur einen lokalen Nachrichten-Konsumpfad hinzu und ändert weder Modellnamen, provider/base URL, die Standardmodell-Strategie, die Fallback-Strategie, die Bereinigung vor `save_context_snapshot` noch die Semantik der Laufzeitkonfiguration; bestehende Deployment-Konfigurationen bleiben kompatibel, als Rollback reicht es, den lokalen Nachrichten-Konsumpfad zu deaktivieren oder die lokalen Nachrichtenquellen-Konfiguration/Daten zu entfernen.

Spätere PRs können den NewsNow-HTTP-Provider, die Beleg-Anzeige im Bericht sowie die Web-Einstellungen/Berichtsansicht weiter ausbauen.

## Hinweise zu Kompatibilität und Rollback (Issue #1707)

- Diese Funktion ändert nicht die Semantik der Drittanbieter-LLM-Provider, fügt keine neuen provider/model/base-URL/Standardmodell-Strategie/Laufzeit-Routing- oder Konfigurations-Migrationszweige hinzu.
- Das Modell-/API-Kompatibilitätsrisiko in den strukturierten Detektions-Hinweisen ist bei dieser Änderung nicht gegeben: Die `news_context`-Injektionskette verwendet ausschließlich die bestehende Konstruktion der LLM-Analyseeingaben (`src/core/pipeline.py`, `src/market_analyzer.py`, `src/analyzer.py`) und fügt weder `.env`-Schreibvorgänge noch Bereinigung vor dem Speichern oder Leer-/Rückschreiblogik hinzu.
- Rollback-Methode: `revert` dieses PR; falls nur eine Downgrade-Konfiguration nötig ist, genügt es, die lokalen Nachrichtenquellen-Konfigurationen zu deaktivieren und zu entfernen (einschließlich der Bestände der Tabelle `sources` und von `intelligence_items`), ohne Auswirkungen auf die bestehenden Modelle, Provider oder andere historische Analyse-Ketten.

## Wiederverwendbarer Inhalt für die PR-Beschreibung (Issue #1707)

- Refs: `#1707`
- Kompatibilitätsfazit: Diese Änderung fügt nur eine lokale Nachrichten-Konsumkette hinzu und ändert weder Modellnamen/provider/base URL noch Standardmodell-Strategie, Fallback-Strategie, Bereinigung vor dem Speichern oder Laufzeit-Konfigurationsmigration. Die Erweiterungen von `news_context` und `market_review_payload` sind best-effort-Anhängungen und beeinflussen weder bestehende Verträge noch die Kompatibilitätsgrenze.
- Rollback-Plan: Der minimale Rollback-Pfad ist `revert this PR`; falls nur eine Downgrade-Anbindung nötig ist, können die lokalen Nachrichtenquellen (`sources` und `intelligence_items`) zur Laufzeit deaktiviert und bereinigt werden.
