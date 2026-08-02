# Analyze PR

Analysiert einen GitHub-Pull-Request und bewertet Notwendigkeit, Vollständigkeit der Beschreibung, Verifikationsnachweise, Hauptrisiken und ob direkt gemerged werden kann.

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis/pulls

## Usage

```text
/analyze-pr <pr_number>
```

## Instructions

Analysiere in präzisem Deutsch und folge vorrangig der `AGENTS.md` im Repository-Root sowie `.github/PULL_REQUEST_TEMPLATE.md`.

### Schritt 1: Neueste Code-Basis synchronisieren

Vor der Analyse eines PR muss der Remote-Stand aufgefrischt und die lokale Codebasis möglichst sicher auf den neuesten Stand gebracht werden:

```bash
git status --short
git fetch --all --prune
# Nur ausführen, wenn das Arbeitsverzeichnis sauber ist und der aktuelle Branch fast-forward-fähig ist:
git pull --ff-only
```

- Führe `git pull --ff-only` nur aus und akzeptiere dessen Ergebnis nur, wenn das Arbeitsverzeichnis sauber ist und der aktuelle Branch ein fast-forward-fähiges Upstream hat.
- Bei lokalen Änderungen, Konflikten, ungetrackten Risikodateien, fehlendem Upstream-Branch oder wenn kein fast-forward möglich ist, führe kein `stash`/`reset` aus, wechsle nicht erzwungen den Branch und überschreibe nicht den lokalen Zustand; analysiere stattdessen anhand des gefetchten `origin/main`, des PR-Head oder des GitHub-Diffs.
- Halte das Synchronisationsergebnis im Abschnitt `Validation Evidence` des Ausgabedokuments fest: lokaler HEAD, verwendete Remote-Basis sowie ggf. den Grund, warum der lokale Arbeitsbaum nicht aktualisiert wurde.

### Schritt 2: Grundlegende PR-Informationen abrufen

```bash
gh pr view <pr_number> --repo ZhuLinsen/daily_stock_analysis
gh pr view <pr_number> --repo ZhuLinsen/daily_stock_analysis --comments
gh pr checks <pr_number> --repo ZhuLinsen/daily_stock_analysis
gh pr diff <pr_number> --repo ZhuLinsen/daily_stock_analysis
```

Bei fehlgeschlagenem CI sieh dir zuerst die Fehlerprotokolle an, statt sofort alle Prüfungen lokal erneut auszuführen:

```bash
gh run view <run_id> --log-failed
```

### Schritt 3: Titel und Vollständigkeit der Beschreibung prüfen

Prüfe zuerst, ob der PR-Titel den nicht-blockierenden Empfehlungen der `AGENTS.md` entspricht:

- Das Format sollte `<Typ>: <Änderungsinhalt>` sein, z. B. `fix: Verlust des Marktanalyse-Verlaufs behoben`
- Als Typ vorzugsweise `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci` verwenden
- Keine Präfixe wie `[codex]`, `codex`, `autocode`, `copilot` oder andere Tool-/Agent-Herkunftsangaben enthalten
- Der Titel sollte die tatsächlichen Änderungen beschreiben; weicht der Titel vom diff ab, weise in der Vollständigkeit der Beschreibung darauf hin, aber nicht allein als Blocker für den Review-Prozess.

Vergleiche mit `.github/PULL_REQUEST_TEMPLATE.md`, ob folgende Abschnitte abgedeckt sind:

- `PR Type`
- `Background And Problem`
- `Scope Of Change`
- `Issue Link`
- `Verification Commands And Results`
- `Visual Evidence` (nur erforderlich, wenn der PR Berichtsformat, Berichtsdarstellung oder die Web-UI-Oberfläche ändert: Screenshots oder alternative visuelle Belege)
- `Compatibility And Risk`
- `Rollback Plan`

Betrifft der PR Kompatibilitätssemantik von Drittanbieter-Modellen/APIs, feste Anfrageparameter, OpenAI-kompatible Routen, YAML-Aliase, Fallback-Verhalten oder Laufzeit-Konfigurationsspeicher-/Bereinigungs-/Migrationslogik, prüfe zusätzlich, ob die Beschreibung Folgendes ausdrücklich angibt:

- offiziellen Quelllink oder Ankündigung
- aktuell festgelegte Abhängigkeiten / Laufzeit-Kompatibilitätsspanne (z. B. LiteLLM-Versionsfenster)
- die Abdeckung der verifizierten Aufrufketten
- ob bestehende Konfiguration stillschweigend überschrieben, geleert, migriert oder unverändert gelassen wird
- den minimalen Rollback-Pfad (in der Regel Revert dieses PR)

Ändert der PR das Berichtsformat, die Berichtsdarstellung oder die Web-UI-Oberfläche, prüfe zusätzlich, ob `Visual Evidence` Screenshots der betroffenen Berichte/Seiten enthält; bei Vorher-/Nachher-Unterschieden bevorzugt den Vorher-Nachher-Vergleich prüfen. Sind keine Screenshots möglich, sollten Grund und alternative visuelle Belege in der Beschreibung genannt werden.

### Schritt 4: Bevorzugt CI-/Diff-Evidenz verwenden

- Beurteile das Problem zuerst anhand von `gh pr checks`, PR-Diff, bestehenden Tests und Workflow-Logs
- Führe lokale Minimal-Verifikationen nur ergänzend durch, wenn CI den Änderungsumfang nicht abdeckt, die CI-Ergebnisse zur Beurteilung nicht ausreichen oder kritische Regressionsrisiken zu verifizieren sind
- Wechsle standardmäßig nicht den aktuellen Branch und führe kein `gh pr checkout` aus

Ist eine lokale Verifikation zwingend erforderlich, wähle die zum Änderungsumfang nächstgelegene Prüfung, z. B.:

- Backend: `./scripts/ci_gate.sh` oder `python -m py_compile <changed_python_files>`
- Frontend: `cd apps/dsa-web && npm ci && npm run lint && npm run build`
- Desktop: zuerst Web bauen, dann Electron bauen

### Schritt 5: Korrektheit und Risiken bewerten

Schwerpunktmäßig prüfen:

- ob ein klar definiertes Problem gelöst wird und keine sachfremden Änderungen enthalten sind
- ob die Kompatibilität von API / Schema / Web / Desktop gebrochen wird
- ob Fallback-, Degradationspfade, Benachrichtigungsketten oder der Release-Prozess gebrochen werden
- ob offensichtliche Logikfehler, verschluckte Ausnahmen, Sicherheitsprobleme oder Konfigurationssemantikänderungen ohne Dokumentations-Synchronisierung vorliegen

### Schritt 6: Review-Dokument erstellen

Speichere in `.claude/reviews/prs/pr-<number>.md`

## Output Document Format

```markdown
# PR #<number> Analysis

**Date**: YYYY-MM-DD
**Status**: Pending Review

## Findings

- [Schweregrad] file:line - Problembeschreibung

## Summary

- Notwendigkeit:
- Entsprechendes Issue vorhanden:
- PR-Typ:
- PR-Titel:
- Vollständigkeit der Beschreibung:
- Verifikationsstatus:
- Hauptrisiken:
- Direkt mergebar:

## Validation Evidence

- Code-Synchronisationsbasis:
- CI-Ergebnis:
- Lokale ergänzende Verifikation (falls vorhanden):

## Compatibility And Risk

- API / Web / Desktop:
- Konfiguration / Docker / GitHub Actions:
- Fallback / Benachrichtigungen / Berichtsstruktur:
- Drittanbieter-Abhängigkeiten / offizielle Einschränkungsquellen:
- Laufzeit-Kompatibilitätsfenster / abgedeckte Ketten:
- Risiko der Migration oder stillschweigenden Überschreibung bestehender Konfiguration:

## Draft Review Comment

<Empfohlener Kommentarinhalt>
```

## Allowed Auto-Actions (No Confirmation Needed)

- PR-Metadaten, diff, Kommentare und CI-Status abrufen
- `git fetch --all --prune` ausführen und bei sauberem, fast-forward-fähigem Arbeitsverzeichnis `git pull --ff-only` ausführen
- Relevanten Code, Vorlagen, Workflows und Dokumentation lesen
- Bei Bedarf minimale lokale Verifikationen ausführen
- Review-Dokument erstellen

## Actions Requiring Confirmation

Bevor die folgenden Aktionen ausgeführt werden, zuerst den Nutzer fragen:

1. Kommentar veröffentlichen
2. PR approven
3. Änderungen anfordern
4. PR mergen
5. PR schließen
