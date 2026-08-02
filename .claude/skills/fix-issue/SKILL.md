# Fix Issue

Setzt die Behebung auf Grundlage der Issue-Analyse um und ergänzt gemäß den Repository-Regeln Verifikation, Risiken und Rollback-Hinweise.

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis

## Usage

```text
/fix-issue <issue_number>
```

## Prerequisites

Führe vorzugsweise zuerst `/analyze-issue <issue_number>` aus, um sicherzustellen, dass das Problem zutrifft und die Grenzen klar sind.

## Instructions

### Schritt 1: Analyse-Basis bestätigen

Prüfe, ob `.claude/reviews/issues/issue-<number>.md` existiert; falls nicht, führe zuerst die Issue-Analyse nach oder ergänze in dieser Behebung mindestens die minimale Analyse-Schlussfolgerung.

### Schritt 2: Neueste Code-Basis synchronisieren und sichere Arbeitsweise wählen

Bevor du mit der Behebung beginnst oder einen PR erstellst/aktualisierst, ziehe zuerst gemäß `AGENTS.md` den neuesten Stand:

```bash
git status --short
git fetch --all --prune
# Nur ausführen, wenn das Arbeitsverzeichnis sauber ist und der aktuelle Branch fast-forward-fähig ist:
git pull --ff-only
```

- Standardmäßig auf dem aktuellen Arbeitsbaum minimale, relevante Änderungen vornehmen
- `git pull --ff-only` nur ausführen und dessen Ergebnis nur akzeptieren, wenn das Arbeitsverzeichnis sauber ist und der aktuelle Branch ein fast-forward-fähiges Upstream hat
- Bei lokalen Änderungen, Konflikten, ungetrackten Risikodateien, fehlendem Upstream-Branch oder wenn kein fast-forward möglich ist, kein `stash`/`reset` ausführen, den Branch nicht erzwungen wechseln und den lokalen Zustand nicht überschreiben; zuerst lokalen HEAD, verwendete Remote-Basis und den Grund für die nicht mögliche Aktualisierung des lokalen Arbeitsbaums festhalten
- Soll später ein PR erstellt/aktualisiert werden, zuerst den Unterschied zwischen aktuellem Branch und Ziel-Basis erläutern; bei Bedarf den Nutzer um Bestätigung für rebase, merge oder das Weiterarbeiten auf dem aktuellen Branch bitten
- Standardmäßig nicht den Branch wechseln oder den aktuellen Arbeitszustand des Nutzers verändern
- Nur wenn der Nutzer ausdrücklich einen Branch anfordert, die minimal nötigen Branch-Operationen ausführen

### Schritt 3: Behebung umsetzen

- Lokalisiere die relevanten Dateien anhand der Issue-Schlussfolgerung
- Bevorzugt bestehende Module, Konfigurations-Einstiegspunkte, Skripte und Tests wiederverwenden
- Das Standardverhalten abwärtskompatibel halten und Fallback/fail-open nicht brechen
- Betrifft die Behebung benutzersichtbares Verhalten, Konfigurationssemantik, CLI/API, Deployment, Benachrichtigungen oder die Berichtsstruktur, aktualisiere parallel die relevanten Dokumente, `docs/CHANGELOG.md` und `.env.example`
- Beim Eintragen in `docs/CHANGELOG.md` eine Zeile im Abschnitt `[Unreleased]` anhängen, Format `- [Typ] Beschreibung`; `[Typ]` aus `[Neu]/[Verbesserung]/[Behebung]/[Dokumentation]/[Test]/[chore]` je nach Änderungsinhalt wählen; `[Behebung]` nur verwenden, wenn ein Bug behoben wird; **keine** `### Kategorie-Überschriften` innerhalb von `[Unreleased]` hinzufügen
- `README.md` trägt nur Informationen auf Homepage-Ebene wie Projektpositionierung, Kernfunktionen, Schnellstart, Haupteinstiegspunkte, Sponsoring/Zusammenarbeit; README nur bei Bedarf aktualisieren, um ein ständiges Anwachsen zu vermeiden
- Detailliertere Modulverhalten, Seiteninteraktionen, Themenkonfiguration, Troubleshooting, Feldverträge, Implementierungssemantik und Randbedingungen bevorzugt in den entsprechenden `docs/*.md` aktualisieren

### Schritt 4: Nach Änderungsumfang verifizieren

Führe gemäß der Verifikationsmatrix der `AGENTS.md` die nächstgelegene Prüfung aus:

- Backend bevorzugt: `./scripts/ci_gate.sh`
- Mindestanforderung Backend: `python -m py_compile <changed_python_files>`
- Frontend: `cd apps/dsa-web && npm ci && npm run lint && npm run build`
- Desktop: zuerst Web bauen, dann Desktop bauen

Kann keine vollständige Verifikation durchgeführt werden, müssen Lücken, Gründe und potenzielle Risiken festgehalten werden.

### Schritt 5: Issue-Analysedokument aktualisieren

Ergänze in `.claude/reviews/issues/issue-<number>.md`:

```markdown
## Fix Implementation

**Date**: YYYY-MM-DD

### Changes Made

- Dateien und Änderungspunkte:

### Validation

- Ausgeführt:
- Nicht ausgeführt:

### Risks

- Risikopunkte:

### Rollback

- Rollback-Verfahren:
```

### Schritt 6: Nachfolgeaktionen, die Bestätigung erfordern

Fordert der Nutzer die Erstellung eines PR, das Generieren eines PR-Titels oder das Zusammenstellen der PR-Beschreibung an, sollte der PR-Titel den Empfehlungen der `AGENTS.md` folgen:

- Format `<Typ>: <Änderungsinhalt>` verwenden, z. B. `fix: Verlust des Marktanalyse-Verlaufs behoben`
- Als Typ vorzugsweise `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci` verwenden
- Der Titel beschreibt nur die tatsächlichen Änderungen; empfohlen wird, keine Präfixe wie `[codex]`, `codex`, `autocode`, `copilot` oder andere Tool-/Agent-Herkunftsangaben hinzuzufügen
- Diese Konvention dient nur der Konsistenz in der Zusammenarbeit und darf nicht allein als process blocker verwendet werden

Nur nach ausdrücklicher Bestätigung durch den Nutzer ausführen:

- Branch erstellen
- `git commit`
- `git push`
- PR erstellen
- Unter dem Issue antworten oder das Issue schließen

## Allowed Auto-Actions (No Confirmation Needed)

- Code lesen und analysieren
- `git fetch --all --prune` ausführen und bei sauberem, fast-forward-fähigem Arbeitsverzeichnis `git pull --ff-only` ausführen
- Minimale, direkt mit der aktuellen Aufgabe zusammenhängende Behebungen anwenden
- Nicht-destruktive lokale Verifikationen ausführen
- Lokales Issue-Analysedokument aktualisieren

## Actions Requiring Confirmation

1. Branch wechseln oder erstellen
2. `git commit`
3. `git push`
4. PR erstellen
5. Auf Issue antworten oder Issue schließen
