# AGENTS.md

Diese Datei definiert den Standard-Entwicklungsablauf dieses Repositories, um wiederholte Kommunikation zu reduzieren, Nacharbeit zu vermeiden und Änderungen mit der bestehenden Projektstruktur konsistent zu halten.

Wenn diese Datei nicht mit Skripten, Workflows oder dem aktuellen Codezustand im Repository übereinstimmt, gelten die tatsächlich ausführbaren Inhalte als maßgeblich; entsprechende Änderungen sollten die Dokumentation gleich mitkorrigieren, um eine weitere Abweichung der Regeln zu vermeiden.

## 1. Harte Regeln

- Bestehende Verzeichnisgrenzen einhalten:
  - Backend-Logik bevorzugt in `src/`, `data_provider/`, `api/`, `bot/`
  - Web-Frontend-Änderungen in `apps/dsa-web/`
  - Desktop-Änderungen in `apps/dsa-desktop/`
  - Änderungen an Bereitstellung und Pipelines in `scripts/`, `.github/workflows/`, `docker/`
- Ohne ausdrückliche Bestätigung keine `git commit`, `git tag` oder `git push` ausführen.
- Commit-Messages auf Englisch verfassen, ohne `Co-Authored-By`.
- Keine Schlüssel, Konten, Pfade, Modellnamen, Ports oder umgebungsabhängige Logik hartkodieren.
- Bevorzugt bestehende Module, Konfigurationseinstiege, Skripte und Tests wiederverwenden; keine parallelen Implementierungen neu anlegen.
- Standardmäßig steht Stabilität über „beiläufiger Optimierung"; Refactorings, Abstraktionen und Infrastruktur-Migrationen, die nicht unmittelbar für die aktuelle Aufgabe nötig sind, sind zu unterlassen.
- Beim Hinzufügen neuer Konfigurationsoptionen muss `.env.example` und die zugehörige Dokumentation synchron aktualisiert werden.
- Bei Änderungen an nutzersichtbaren Fähigkeiten, CLI/API-Verhalten, Bereitstellungs- oder Benachrichtigungswegen sowie Berichtsstrukturen müssen die zugehörigen Dokumente und `docs/CHANGELOG.md` synchron aktualisiert werden.
- Bei Änderungen an Berichtsformat, Berichtsdarstellung oder Web-UI müssen PR-Beschreibungen Screenshots der betroffenen Berichte/Seiten enthalten; bei Vorher-/Nachher-Unterschieden vorzugsweise Vorher-/Nachher-Vergleiche; falls keine Screenshots möglich sind, Grund und alternativen visuellen Nachweis angeben.
- Screenshots aus Issue-/PR-Abläufen, Review-Screenshots, einmalige Abnahmescreenshots und temporäre visuelle Belege dürfen nicht als Repository-Dateien eingecheckt werden; sie gehören in die PR-Beschreibung, PR-Kommentare, GitHub-Anhänge, Actions-Artefakte oder externe, zugängliche Nachweis-Links. Ausgenommen sind Abbildungen, die die Produktdokumentation langfristig benötigt – deren Dateinamen und Dokumentationssemantik müssen jedoch von konkreten Issue-/PR-Nummern entkoppelt sein.
- Die `[Unreleased]`-Sektion von `docs/CHANGELOG.md` verwendet ein **flaches Format**: Jeder Eintrag steht in einer eigenen Zeile im Format `- [Typ] Beschreibung`. Zulässige Typen: `新功能`/`改进`/`修复`/`文档`/`测试`/`chore`. **Es ist verboten, innerhalb von `[Unreleased]` neue `### Typ-Überschriften` anzulegen**, um Merge-Konflikte bei parallelen PRs zu reduzieren. Beim Release fasst der Maintainer die Einträge in einem formalen Format mit Überschriften zusammen.
- `README.md` dient ausschließlich der Projektpositionierung, dem Überblick über Kernfunktionen, dem Schnellstart, den wichtigsten Einstiegspunkten sowie Sponsoring/Zusammenarbeit auf Startseitenebene; nicht unbedingt erforderliche README-Updates vermeiden, um ein Aufblähen zu verhindern.
- Detailliertere Modulverhalten, Seiteninteraktionen, themenspezifische Konfigurationen, Fehlerbehebung, Feldverträge, Implementierungssemantik und Randbedingungen bevorzugt in den zugehörigen `docs/*.md` oder Themendokumenten aktualisieren, nicht in der README.
- Bei Änderungen an einem der zweisprachigen Dokumente ist zu prüfen, ob das andere synchron aktualisiert werden muss; falls nicht, ist der Grund in der Lieferbeschreibung anzugeben.
- Kommentare, Docstrings und Logtexte sollen klar und präzise sein; Englisch ist nicht zwingend, sollten aber zum Kontext der Datei passen.

## 1.1 PR-Titel-Regel (nicht blockierende Empfehlung)

- Empfohlen wird `<Typ>: <Änderungsinhalt>` als PR-Titel, z. B. `fix: 修复大盘分析历史记录丢失`. Bevorzugte Typen sind `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`.
- Der Titel soll den tatsächlichen Änderungsinhalt beschreiben; Präfixe wie `[codex]`, `codex`, `autocode`, `copilot` oder andere Tool-/Agent-Quellen sollten nicht ergänzt werden.
- Diese Regel dient lediglich der kollaborativen Lesbarkeit und Konsistenz und darf allein kein Blocker im Review-Prozess sein.

## 1.2 Untergrenze der Beitragsqualität

- Dieses Repository akzeptiert keine PRs, die reine Codemengen anhäufen, die Diff-Fläche aufblähen oder Review-Rückmeldungen nur mit Pflastern beantworten, statt zu einer echten Design-Konvergenz zu kommen.
- Beitragsqualität bemisst sich danach, ob ein klares Problem gelöst wird, ob die Auswirkungsfläche minimiert ist, ob bestehende Verträge konsistent bleiben und ob echte Risikopfade abgedeckt sind – nicht anhand neuer Zeilenzahlen, Dateianzahl, Feature-Werbung oder dem Eindruck von „vollständig".
- Bitte behandeln Sie dieses Repository nicht als kostengünstiges Versuchsfeld, als Showcase für den Lebenslauf oder als Ort für Contribution-Farming. Jeder PR muss belegen, dass der Autor die Verträge des aktuellen Systems versteht und grundlegende Selbstprüfung, Integration und Validierung durchgeführt hat.
- Die Nutzung von KI-gestützter Entwicklung ist an sich kein Problem; problematisch ist das Einreichen von KI-generiertem Code, der ohne menschliche semantische Prüfung, ohne Validierung und ohne Konvergenz bleibt. Solche PRs gelten als qualitativ minderwertige Einreichungen.
- Nach Review-Feedback ist es nicht akzeptabel, nur an der vom Reviewer genannten Stelle lokale Pflaster hinzuzufügen. Der Autor muss alle Einstiegspunkte, Konfigurationen, Tests, Dokumente, Workflows und nutzersichtbaren Pfade derselben Geschäftssemantik erneut prüfen.
- Wenn ein PR auch nach mehreren Review-Runden weiterhin dieselben Vertragsabweichungen, wiederholte Fallbacks, Tests, die die echte Risikoebene umgehen, oder Widersprüche zwischen PR-Body und tatsächlichem Diff aufweist, kann der Maintainer ein Schließen mit Neuanfertigung verlangen, statt punktuell weiter zu reviewen.

## 2. Governance von KI-Kollaborations-Assets

- `AGENTS.md` ist die einzige verbindliche Quelle für die KI-Kollaborationsregeln im Repository.
- `CLAUDE.md` muss ein symbolischer Link auf `AGENTS.md` sein, für Kompatibilität mit dem Claude-Ökosystem.
- `.github/copilot-instructions.md` und `.github/instructions/*.instructions.md` sind Spiegel oder geschichtete Ergänzungen für GitHub Copilot / Coding Agents; bei Konflikten mit dieser Datei gilt `AGENTS.md`.
- Die Kollaborations-Skills des Repositories liegen in `.claude/skills/`, Analyse-Artefakte in `.claude/reviews/`; Ersteres kann eingecheckt werden, Letzteres gilt standardmäßig als lokales Artefakt.
- `SKILL.md` im Stammverzeichnis und `docs/openclaw-skill-integration.md` sind Produkt- oder externe Integrationsbeschreibungen, keine verbindliche Quelle für Repository-Kollaborationsregeln.
- Falls künftig `.agents/skills/` oder andere agentenspezifische Verzeichnisse hinzukommen, muss zunächst die einzige verbindliche Quelle festgelegt und dann per Skript oder Spiegel synchronisiert werden; eine manuelle, dauerhafte Pflege mehrerer inhaltsgleicher Dokumente ist verboten.
- Bei Änderungen an KI-Kollaborations-Governance-Assets ausführen:

```bash
python scripts/check_ai_assets.py
```

## 3. Repository-Überblick

- Projektpositionierung: Intelligentes Aktienanalyse-System für A-Aktien, Hongkong-Aktien und US-Aktien.
- Hauptablauf: Daten abrufen -> technische Analyse / Nachrichtenrecherche -> LLM-Analyse -> Bericht erstellen -> Benachrichtigung pushen.
- Wichtige Einstiegspunkte:
  - `main.py`: Haupteinstieg für Analysetasks
  - `server.py`: Einstieg für den FastAPI-Service
  - `apps/dsa-web/`: Web-Frontend
  - `apps/dsa-desktop/`: Electron-Desktop
  - `.github/workflows/`: CI, Release, tägliche Tasks
- Kernverantwortlichkeiten:
  - `src/core/`: Orchestrierung des Hauptablaufs
  - `src/services/`: Geschäftsserviceschicht
  - `src/repositories/`: Datenzugriffsschicht
  - `src/reports/`: Berichtserstellung
  - `src/schemas/`: Schema / Datenstrukturen
  - `data_provider/`: Multi-Datenquellen-Adaptern und Fallback
  - `api/`: FastAPI-API
  - `bot/`: Bot-Anbindung
  - `scripts/`: Lokale Skripte
  - `.github/scripts/`: GitHub-Automatisierungsskripte
  - `tests/`: pytest-Tests
  - `docs/`: Dokumentation und Anleitungen

## 4. Häufig verwendete Befehle

### App ausführen

```bash
python main.py
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review
python main.py --schedule
python main.py --serve
python main.py --serve-only
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### Backend-Validierung

```bash
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
```

### Web / Desktop

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build

cd ../dsa-desktop
npm install
npm run build
```

### PR / CI-Belege

```bash
gh pr view <pr_number>
gh pr checks <pr_number>
gh run view <run_id> --log-failed
```

## 5. Standard-Workflow

1. Zuerst den Aufgabentyp bestimmen: `fix / feat / refactor / docs / chore / test / review`
2. Erst bestehende Implementierungen, Konfigurationen, Tests, Skripte, Workflows und Dokumente lesen, dann ändern.
3. Die Änderungsgrenzen identifizieren: Backend / API / Web / Desktop / Workflow / Docs / KI-Kollaborations-Assets.
4. Zuerst prüfen, ob Hochrisikobereiche betroffen sind: Konfigurationssemantik, API/Schema, Datenquellen-Fallback, Berichtsstruktur, Authentifizierung, Scheduler, Release-Abläufe, Desktop-Startkette.
5. Nur die minimalen Änderungen vornehmen, die unmittelbar mit der aktuellen Aufgabe zusammenhängen; kein beiläufiges Mitnehmen unzusammenhängender Refactorings.
6. Bei Widersprüchen zwischen Dokumenten, Skripten und Workflow-Beschreibungen dem tatsächlichen Code und Workflow vertrauen und erst danach entscheiden, ob die Dokumente mitkorrigiert werden.
7. Nach der Änderung die Prüfungen gemäß der unten stehenden Validierungsmatrix ausführen.
8. Die finale Lieferung muss standardmäßig beschreiben:
   - Was geändert wurde
   - Warum so geändert
   - Validierungssituation
   - Nicht validierte Punkte
   - Risikopunkte
   - Rückrollmöglichkeit

## 6. Validierungsmatrix

### Prinzipien der CI-Abdeckung

Die aktuelle Repository-CI umfasst hauptsächlich:

| Prüfpunkt | Quelle | Beschreibung | Blockierend? |
| --- | --- | --- | --- |
| `ai-governance` | `.github/workflows/ci.yml` | Prüft die Beziehungen von `AGENTS.md` / `CLAUDE.md` / `.github`-Anweisungen / `.claude/skills` | Ja |
| `backend-gate` | `.github/workflows/ci.yml` | Führt `./scripts/ci_gate.sh` aus | Ja |
| `docker-build` | `.github/workflows/ci.yml` | Docker-Build und Smoke-Import kritischer Module | Ja |
| `web-gate` | `.github/workflows/ci.yml` | Bei Frontend-Änderungen `npm run lint` + `npm run build` ausführen | Ja (bei Auslösung) |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` + `scripts/test.sh quick` | Nein, Beobachtungspunkt |
| `pr-review` | `.github/workflows/pr-review.yml` | PR-Statikprüfung + AI-Review + automatische Labels | Nein, unterstützender Punkt |

Wenn für den PR bereits entsprechende CI-Ergebnisse vorliegen, können die CI-Schlussfolgerungen direkt zitiert werden. Wenn die CI die Änderungsfläche nicht abdeckt oder die lokale Umgebung stark von der CI-Umgebung abweicht, müssen lokale Validierung und Lücken ergänzend beschrieben werden.

### Je nach Änderungsfläche ausführen

- Python-Backend-Änderungen:
  - Anwendungsbereich: `main.py`, `src/`, `data_provider/`, `api/`, `bot/`, `tests/`
  - Bevorzugt ausführen: `./scripts/ci_gate.sh`
  - Mindestanforderung: `python -m py_compile <changed_python_files>`
  - Falls API, Task-Orchestrierung, Berichtserstellung, Benachrichtigungsversand, Datenquellen-Fallback, Authentifizierung oder Scheduler betroffen sind, muss in der Lieferbeschreibung angegeben werden, ob die entsprechenden Pfade abgedeckt wurden.

- Web-Frontend-Änderungen:
  - Anwendungsbereich: `apps/dsa-web/`
  - Standardausführung: `cd apps/dsa-web && npm ci && npm run lint && npm run build`
  - Falls API-Integration, Routing, Zustandsverwaltung, Markdown-/Diagramm-Rendering oder Authentifizierungszustand betroffen sind, müssen in der Lieferbeschreibung die betroffenen Flächen und nicht abgedeckte Risiken klar benannt werden.

- Desktop-Änderungen:
  - Anwendungsbereich: `apps/dsa-desktop/`, `scripts/run-desktop.ps1`, `scripts/build-desktop*.ps1`, `scripts/build-*.sh`, `docs/desktop-package.md`
  - Standardausführung: erst Web bauen, dann Desktop bauen
  - Falls eine vollständige Validierung aus Plattformgründen nicht möglich ist, muss klar angegeben werden, ob das Web-Build-Artefakt, der Electron-Build und die Auswirkungen auf den Release-Workflow validiert wurden.

- Änderungen an API / Schema / Authentifizierungs-Kopplung:
  - Anwendungsbereich: `api/**`, `src/schemas/**`, `src/services/**`, `apps/dsa-web/**`, `apps/dsa-desktop/**`
  - Mindestens die zugehörige Backend-Validierung plus Build-Validierung der betroffenen Clients abdecken.
  - Bei Änderungen an Login, Cookie, Sitzung, Polling-Status, Feldzugängen/-entfernungen oder Enum-Änderungen müssen die Kompatibilitätsauswirkungen explizit beschrieben werden.

- Änderungen an Dokumenten und Governance-Dateien:
  - Anwendungsbereich: `README.md`, `docs/**`, `AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/**`, `.claude/skills/**`
  - Keine erzwungenen Code-Tests.
  - Es muss bestätigt werden, dass Befehle, Konfigurationsoptionen, Dateinamen und Workflow-Namen mit dem tatsächlichen Repository übereinstimmen.
  - Bei Änderungen an KI-Kollaborations-Governance-Assets `python scripts/check_ai_assets.py` ausführen.

- Änderungen an Workflows / Skripten / Docker:
  - Anwendungsbereich: `.github/**`, `scripts/**`, `docker/**`
  - Die der Änderungsfläche am nächsten liegende lokale Validierung ausführen.
  - In der Lieferbeschreibung angeben, welche Pipeline, welcher Release-Pfad oder welcher Bereitstellungspfad betroffen ist.
  - Falls Docker-/GitHub-Actions-bezogene Validierungen nicht ausgeführt wurden, Grund und potenzielle Risiken klar angeben.

- Änderungen an Netzwerk oder Drittanbieter-Abhängigkeiten:
  - Zuerst Offline- oder deterministische Prüfungen ausführen.
  - Bevorzugt bestätigen, dass timeout, retry, fallback, Fehlermeldungstexte und Degradierungspfade weiterhin gelten.
  - Falls keine Online-Validierung durchgeführt wurde, müssen die Gründe explizit angegeben werden.

## 7. Stabilitäts-Schutzschranken

- Konfiguration und Ausführungseinstiege:
  - Bei Änderungen an der Semantik von `.env`, Standardwerten, CLI-Parametern, der Art des Service-Starts oder der Scheduler-Semantik muss gleichzeitig die Auswirkung auf lokale Ausführung, Docker, GitHub Actions, API, Web und Desktop bewertet werden.
  - Neue Konfigurationen sollten bevorzugt „ohne Konfiguration lauffähig, mit Konfiguration verstärkt" sein und gehäufte Schalter und sich gegenseitig ausschließende Modi vermeiden.

- Datenquellen und Fallback:
  - Bei Änderungen an `data_provider/` sind Datenquellen-Priorität, Fehler-Degradierung, Feldstandardisierung, Caching und Timeout-Strategien zu beachten.
  - Der Ausfall einer einzelnen Datenquelle darf den gesamten Analyseablauf nicht zu Fall bringen, außer die Anforderung verlangt explizit fail-fast.

- API / Web / Desktop-Kompatibilität:
  - Bei Änderungen an API / Schema / Authentifizierung / Berichts-Payload muss gleichzeitig die Kompatibilität von Backend, Web und Desktop geprüft werden.
  - Standardmäßig Felder ergänzen, alte Felder beibehalten oder eine Kompatibilitätsschicht bereitstellen, um bestehende Clients nicht ohne Warnung zu zerstören.

- Berichte / Prompts / Benachrichtigungen:
  - Bei Änderungen an Berichtsstruktur, Prompts, Extraktoren, Benachrichtigungsvorlagen oder Bot-Ketten prüfen, ob Upstream-Eingaben und Downstream-Konsumenten weiterhin kompatibel sind.
  - Der Ausfall eines einzelnen Benachrichtigungskanals darf den gesamten Analyse-Hauptablauf nicht zu Fall bringen, außer die Anforderung verlangt explizit fail-fast.
  - Bei Änderungen an `EXTRACT_PROMPT` in `src/services/image_stock_extractor.py` muss die PR-Beschreibung den vollständigen aktuellen Prompt enthalten.

- Workflows / Release / Verpackung:
  - Bei Änderungen an automatischen Tags, Release, Docker-Veröffentlichung, täglicher Analyse oder Desktop-Verpackung die Auslösebedingungen, Artefaktpfade, Berechtigungsgrenzen und Rückrollmöglichkeiten bewerten.
  - Automatische Tags bleiben standardmäßig opt-in: Nur wenn der Commit-Titel `#patch`, `#minor` oder `#major` enthält, wird die Versionsnummer aktualisiert – außer die Anforderung verlangt explizit eine Änderung der Release-Strategie.

## 8. Issue / PR / Skill-Workflow

- Im Repository existieren bereits folgende Skills, die bevorzugt wiederverwendet werden können:
  - `.claude/skills/analyze-issue/SKILL.md`
  - `.claude/skills/analyze-pr/SKILL.md`
  - `.claude/skills/fix-issue/SKILL.md`
- Ist die Aufgabe eindeutig Issue-Analyse, PR-Review oder Issue-Fix, bevorzugt den entsprechenden Skill ausführen und Artefakte in `.claude/reviews/` speichern.
- Befehle, Vorlagen, Validierungsreihenfolge und Lieferstruktur der Skills müssen mit `AGENTS.md` konsistent bleiben.
- Vor jeder PR-Erstellung/-Aktualisierung, PR-Review oder Issue-Analyse muss zunächst die aktuelle Code-Basis synchronisiert werden: Zuerst den Workspace-Status prüfen und `git fetch --all --prune` ausführen; ist der Workspace sauber und der aktuelle Branch fast-forward-fähig, dann `git pull --ff-only` ausführen. Bei lokalen Änderungen, Konfliktstatus, ungetrackten Risikodateien oder nicht möglichem Fast-Forward darf nicht erzwungen Branch gewechselt, gestasht, zurückgesetzt oder der lokale Zustand überschrieben werden; PR-Review / Issue-Analyse können stattdessen mit den bereits gefetchten Remote-Refs/PR-heads durchgeführt werden, wobei im Analysedokument klar festzuhalten ist, warum der lokale Arbeitsbaum nicht aktualisiert wurde, der aktuelle lokale HEAD und die verwendete Remote-Baseline; für PR-Erstellung/-Aktualisierung sind zuerst die Unterschiede zwischen aktuellem Branch und Ziel-Baseline zu erläutern und bei Bedarf den Nutzer um Bestätigung zu rebase, merge oder auf Basis des aktuellen Branches fortzufahren.
- Skills lesen standardmäßig bevorzugt CI-/Workflow-Belege und entscheiden erst danach, ob lokale Validierungen ergänzt werden.
- Abgesehen von der oben beschriebenen sicheren Fast-Forward-Synchronisierung für PR-Erstellung/-Aktualisierung, PR-Review / Issue-Analyse dürfen Skills standardmäßig keine Operationen ausführen, die den Remote- oder aktuellen Branch-Zustand verändern, wie `git pull`, `git push`, `git tag` oder `gh pr create`; diese Operationen erfordern die Bestätigung des Nutzers.
- Standard-Reihenfolge des PR-Reviews:
  1. Notwendigkeit
  2. Relevanz
  3. Titelvorschlag (`<Typ>: <Änderungsinhalt>`, ohne Tool-/Agent-Präfix; kein hartes Blockierkriterium)
  4. Vollständigkeit der Beschreibung (gegen `.github/PULL_REQUEST_TEMPLATE.md` prüfen)
  5. Validierungsbelege
  6. Korrektheit der Implementierung
  7. Merge-Entscheidung
- Bei PRs vom Typ `fix` müssen beschrieben werden: ursprüngliches Problem, Grundursache, Fix-Punkt, Regressionsrisiko.
- Blockierkriterien für den Merge:
  - Korrektheits- oder Sicherheitsprobleme
  - Blockierende CI nicht bestanden
  - PR-Beschreibung steht im Wesentlichen im Widerspruch zu den tatsächlichen Änderungen
  - Fehlender Rollback-Plan
  - Wiederholt nicht konvergierte Vertragsabweichungen, Patch-Stapelung oder verzerrte Validierungsbelege

## 8.1 Behandlung von Review-Feedback und Verbot von Patch-Stapelung

Wenn du Review-Feedback bearbeitest, ist es verboten, nur an der vom Reviewer genannten Stelle lokale Pflaster hinzuzufügen und dann zu behaupten, „alles sei behoben". Du musst zuerst die vom Reviewer aufgezeigten Geschäftsverträge erneut verstehen und dann alle Einstiegspunkte, Konfigurationen, Tests, Dokumente, Workflows und nutzersichtbaren Pfade derselben Semantik prüfen.

Nach Erhalt von Review-Feedback muss in folgender Reihenfolge vorgegangen werden:

1. Die vom Reviewer aufgezeigten ursprünglichen Probleme einzeln auflisten.
2. Die Grundursache erläutern, nicht nur beschreiben, „welche Zeilen geändert wurden".
3. Alle betroffenen Pfade derselben Semantik finden, z. B. runtime, API/Web, CLI, diagnostics, workflow, docs, tests.
4. Den vollständigen Vertrag beheben, nicht nur den aktuell fehlschlagenden Test oder die aktuelle Kommentarzeile.
5. Regressionstests ergänzen, die die Gegenbeispiele des Reviewers abdecken, eine Endpunktvalidierung, oder klar den Grund angeben, warum keine Validierung möglich ist.
6. Den PR-Body synchron aktualisieren, sodass scope, Validierungsergebnisse, Kompatibilität, Risiken und Rollback-Plan mit dem aktuellen head übereinstimmen.

Wenn du die oben beschriebene Konvergenz nicht erreichen kannst, staple keine weiteren Pflaster und behaupte nicht „ready for merge". Teile aktiv mit, dass der aktuelle PR aufgeteilt, geschlossen und neu gemacht werden muss, oder bitte den Maintainer um Bestätigung eines neuen minimalen Umfangs.

Folgende Verhaltensweisen gelten als qualitativ minderwertige PRs:

- Mit breiten Fallbacks, stillem Degradieren oder `return False/None/[]` unklare Verträge überdecken.
- Tests mocken die echte Risikoebene weg und belegen nur, dass die lokale Implementierung durchläuft.
- Nach bestandener CI behaupten, das Problem sei geschlossen, ohne die vom Reviewer aufgezeigten Gegenbeispiele abzudecken.
- PR-Body widerspricht tatsächlichem Diff, Validierungsergebnissen oder Kompatibilitätsrisiken.
- Nach dem Review weiterhin verstreute Pflaster ergänzen, statt die vollständige Semantik erneut zu konvergieren.
- Dieselbe Geschäftssemantik verhält sich in runtime, Web/API, docs, workflow und tests inkonsistent.

Bestandene CI belegt nur, dass automatisierte Prüfungen durchlaufen; sie ersetzt keine menschliche semantische Konvergenz und kann allein nicht belegen, dass die vom Reviewer aufgezeigten Gegenbeispiele geschlossen sind.

## 9. Lieferung und Release

- Standard-Lieferstruktur:
  - `Was geändert wurde`
  - `Warum so geändert`
  - `Validierungssituation`
  - `Nicht validierte Punkte`
  - `Risikopunkte`
  - `Rückrollmöglichkeit`
- Bei `docs`-Aufgaben kann direkt `Docs only, tests not run` geschrieben werden, dennoch muss angegeben werden, ob Befehle und Dateinamen abgeglichen wurden.
- Automatische Tags lösen standardmäßig nicht aus; nur wenn der Commit-Titel `#patch`, `#minor` oder `#major` enthält, wird die Versionsnummer aktualisiert.
- Manuelle Tags müssen annotierte Tags verwenden.
- Nutzersichtbare Änderungen werden bevorzugt über PRs gemergt, mit ausgefüllten Labels und Validierungsbeschreibungen.
