# Analyze Issue

Analysiert ein GitHub-Issue und bewertet dessen Echtheit, Priorität, Verantwortungsbereich des Repositorys sowie empfohlene Maßnahmen.

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis/issues

## Usage

```text
/analyze-issue <issue_number>
```

## Instructions

Analysiere in präzisem Deutsch und folge vorrangig der `AGENTS.md` im Repository-Root.

### Schritt 1: Neueste Code-Basis synchronisieren

Vor der Analyse eines Issues muss der Remote-Stand aufgefrischt und die lokale Codebasis möglichst sicher auf den neuesten Stand gebracht werden:

```bash
git status --short
git fetch --all --prune
# Nur ausführen, wenn das Arbeitsverzeichnis sauber ist und der aktuelle Branch fast-forward-fähig ist:
git pull --ff-only
```

- Führe `git pull --ff-only` nur aus und akzeptiere dessen Ergebnis nur, wenn das Arbeitsverzeichnis sauber ist und der aktuelle Branch ein fast-forward-fähiges Upstream hat.
- Bei lokalen Änderungen, Konflikten, ungetrackten Risikodateien, fehlendem Upstream-Branch oder wenn kein fast-forward möglich ist, führe kein `stash`/`reset` aus, wechsle nicht erzwungen den Branch und überschreibe nicht den lokalen Zustand; analysiere stattdessen anhand des bereits gefetchten `origin/main` oder der relevanten Remote-Refs.
- Halte das Synchronisationsergebnis im Abschnitt `Evidence` des Ausgabedokuments fest: lokaler HEAD, verwendete Remote-Basis sowie ggf. den Grund, warum der lokale Arbeitsbaum nicht aktualisiert wurde.

### Schritt 2: Issue-Informationen abrufen

```bash
gh issue view <issue_number> --repo ZhuLinsen/daily_stock_analysis
gh issue view <issue_number> --repo ZhuLinsen/daily_stock_analysis --comments
```

Handelt es sich um einen Bug, prüfe vorrangig, ob im Issue-Template folgende Informationen angegeben wurden:

- ob auf die neueste Version synchronisiert wurde
- Commit-Hash / Versionsbasis
- Laufzeitumgebung und Reproduktionsschritte
- Log- oder Fehlermeldungen

### Schritt 3: Vier Kernfragen beantworten

1. Ist die Version klar?
2. Ist das Problem real und verifizierbar?
3. Fällt es in den Verantwortungsbereich des Repositorys?
4. Ist es eine sofortige Bearbeitung wert?

### Schritt 4: Evidenzprüfung anhand des aktuellen Repository-Zustands

- Lies den relevanten Code, die Konfiguration, Tests, Skripte, Workflows und Dokumentation
- Betrifft das Problem API, Datenquellen-Fallback, Berichtsgenerierung, Benachrichtigungsversand, Authentifizierung, Desktop oder Release-Prozess, benenne den Auswirkungsbereich ausdrücklich
- Bewerte, ob es sich um einen tatsächlichen Bug, ein Umgebungskonfigurationsproblem, ein Nutzungsproblem oder ein Problem mit externen Abhängigkeiten handelt
- Wird ein bereits behobener Bug vermutet, prüfe den aktuellen Code statt nur die Issue-Beschreibung

### Schritt 5: Schlussfolgerung bilden

Gib mindestens die folgenden Felder an:

- `Versionsbasis`: neueste / nicht neueste / nicht angegeben
- `Plausibel`: ja/nein + Begründung
- `Ist es ein Issue`: ja/nein + Begründung
- `Gut lösbar`: ja/nein + Schwierigkeiten
- `Fazit`: `zutreffend / teilweise zutreffend / nicht zutreffend`
- `Kategorie`: `bug / feature / docs / question / external`
- `Priorität`: `P0 / P1 / P2 / P3`
- `Schwierigkeit`: `easy / medium / hard`
- `Empfohlene Maßnahme`: `sofort beheben / zeitlich einplanen / Dokumentation klären / schließen`

### Schritt 6: Analysedokument erstellen

Speichere in `.claude/reviews/issues/issue-<number>.md`

## Output Document Format

```markdown
# Issue #<number> Analysis

**Date**: YYYY-MM-DD
**Status**: Pending Review

## Summary

- Versionsbasis:
- Plausibel:
- Ist es ein Issue:
- Gut lösbar:
- Fazit:
- Kategorie:
- Priorität:
- Schwierigkeit:
- Empfohlene Maßnahme:

## Evidence

- Code-Synchronisationsbasis:
- Wichtigste Issue-Informationen:
- Wichtigste Code-/Skript-/Workflow-Evidenz:

## Impact Scope

- Betroffene Module:
- Betroffene Laufpfade (lokal / Docker / GitHub Actions / API / Web / Desktop):

## Root Cause / Main Reasoning

<Root Cause oder wichtigste Bewertungsgrundlage>

## Proposed Handling

<Empfohlene Art der Behebung, Klärung oder Schließung>

Wird im Anschluss die Erstellung eines PR empfohlen, sollte der vorgeschlagene PR-Titel der `AGENTS.md` entsprechen: Format `<Typ>: <Änderungsinhalt>`, ohne Präfixe wie `[codex]`, `codex`, `autocode`, `copilot` oder andere Tool-/Agent-Herkunftsangaben; diese Konvention dient nur der Konsistenz in der Zusammenarbeit und darf nicht allein als Blocker für den Review-Prozess verwendet werden.

## Risks And Rollback

- Risikopunkte:
- Falls behoben, Rollback-Verfahren:

## Draft Reply

<Empfohlener Antwortinhalt>
```

## Allowed Auto-Actions (No Confirmation Needed)

- Issue-Details und Kommentare abrufen
- `git fetch --all --prune` ausführen und bei sauberem, fast-forward-fähigem Arbeitsverzeichnis `git pull --ff-only` ausführen
- Relevanten Code, Konfiguration, Skripte, Workflows und Dokumentation lesen
- Analysedokument erstellen

## Actions Requiring Confirmation

Bevor die folgenden Aktionen ausgeführt werden, zuerst den Nutzer fragen:

1. Labels hinzufügen oder ändern
2. Unter dem Issue kommentieren
3. Issue schließen
4. Mit der Behebung des Issues beginnen
