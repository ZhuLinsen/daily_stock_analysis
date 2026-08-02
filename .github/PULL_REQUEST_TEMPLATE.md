<!--
Für chinesische Beitragende: bitte direkt auf Chinesisch ausfüllen.
Für englische Beitragende: bitte auf Englisch ausfüllen. Alle mit (EN) markierten Felder akzeptieren Englisch.
-->

## PR Type

- [ ] fix
- [ ] feat
- [ ] refactor
- [ ] docs
- [ ] chore
- [ ] test

## Background And Problem

Bitte beschreiben Sie das aktuelle Problem, den betroffenen Umfang und das Auslöseszenario.  
*(EN) Describe the problem, its impact, and what triggers it.*

## Scope Of Change

Bitte listen Sie die in diesem PR geänderten Module und Dateien auf.  
*(EN) List the modules and files changed in this PR.*

> Hinweis: Bitte listen Sie den Dateiumfang vollständig gemäß dem tatsächlichen `git diff` auf (empfohlen: Gesamtzahl der Dateien angeben), um Unstimmigkeiten durch ausgelassene Dokument-/Backend-/API-/Frontend-Dateien zu vermeiden.

> Falls dieser PR Kollaborations- und Governance-Dateien wie `.github/PULL_REQUEST_TEMPLATE.md`, `.github/copilot-instructions.md`, `AGENTS.md`, `.github/instructions/*` oder `.claude/skills/**` ändert, ergänzen Sie bitte „Änderungsgrund + Auswirkungsbereich + Rollback-Verfahren (Standard: revert)" unter Summary / Compatibility / Rollback, um Inkonsistenzen zwischen Scope und Beschreibung zu vermeiden.

> Empfohlen: Führen Sie zuerst die folgenden Befehle aus und fügen Sie deren Ausgabe ein, um Abweichungen vom tatsächlichen diff zu vermeiden:

```bash
BASE_REF=$(git merge-base HEAD origin/main)
git diff --stat "$BASE_REF"..HEAD
git diff --name-only "$BASE_REF"..HEAD
```

- Gesamtzahl der Dateien / geänderte Zeilen (empfohlen: `git diff --stat "$BASE_REF"..HEAD` einfügen):
- Dateiliste (vollständig nach tatsächlichem diff, einzeln aufgeführt):
- Dokumentations-Update-Dateien (`docs/*`):

## Issue Link

Eines davon ist anzugeben / Fill in one of:
- `Fixes #<issue_number>`
- `Refs #<issue_number>`
- Ohne Issue: Begründung und Abnahmekriterien angeben / If no issue, explain the motivation and acceptance criteria

## Verification Commands And Results

Bitte tragen Sie die tatsächlich ausgeführten Befehle und deren wesentliche Ergebnisse ein (nicht nur „getestet" schreiben).  
*(EN) Paste the commands you actually ran and their key output (don't just write "tested"):*

```bash
# example
./scripts/ci_gate.sh
python -m pytest -m "not network"
```

> Die `Full-suite note` muss mit dem aktuellen Head-CI-Ergebnis dieses PR übereinstimmen; falls bei der lokalen Reproduktion umgebungsbedingte Fehler auftreten, kennzeichnen Sie diese bitte ausdrücklich als „lokale Umgebungsunterschiede" und geben Sie die GitHub-CI-Bewertung mit Link an.  
> Vermeiden Sie bitte Formulierungen über historische Fehler, die nichts mit diesem PR zu tun haben; tragen Sie die tatsächlichen Ergebnisse ein.
> Falls in der historischen Beschreibung noch ein `./scripts/ci_gate.sh`-Fehler festgehalten ist, ändern Sie diesen bitte auf den aktuellen Head-CI-Status oder erläutern Sie die Quelle der Abweichung zum Head CI.
> Wenn die `Full-suite note` nicht mit dem aktuellen Head CI übereinstimmt, ist der PR-Text unvollständig; aktualisieren Sie bitte zuerst die PR-Beschreibung, bevor Sie einreichen.

- Bitte füllen Sie unten nach den tatsächlichen Ergebnissen aus und halten Sie sie mit der `Full-suite note` konsistent (jedes leere Feld gilt als fehlende Information):
  - ai-governance: `pass` / `fail`, mit Link
  - backend-gate: `pass` / `fail`, mit Link
  - docker-build: `pass` / `fail`, mit Link
  - web-gate: `pass` / `fail`, mit Link
  - Falls dieser PR Prozess-/Template-Kollaborationsdateien wie `.github/PULL_REQUEST_TEMPLATE.md` ändert, erläutern Sie bitte zuerst die Notwendigkeit der Änderung und die Auswirkungsgrenzen und legen Sie das Rollback-Verfahren klar fest (Standard: `revert this PR`); andernfalls trennen Sie dies bitte in der nächsten Version in einen separaten chore-PR auf.

Wesentliche Ausgabe/Fazit / Key output & conclusion:

- [Pflichtfeld] Aktueller Head CI: `ai-governance:pass / backend-gate:pass / docker-build:pass / web-gate:pass` (durch tatsächliche Ergebnisse ersetzen) und passenden Link angeben.  
- Falls lokale Fehlerphänomene festgehalten werden sollen, schreiben Sie bitte im selben Absatz „lokale Umgebungsunterschiede + aktuelles CI-Ergebnis (bestanden/fehlgeschlagen) + CI-Link".  
- Falls alles bestanden ist, ergänzen Sie: `Aktueller Status: alle bestanden (pass)` und legen Sie fest, dass der Head CI vollständig auf pass steht.  

- Empfohlen: Fügen Sie diese Zeile direkt in den ersten Absatz der PR-Beschreibung ein: `Aktueller Head CI: ai-governance:pass / backend-gate:pass / docker-build:pass / web-gate:pass` (nur Beispiel, durch tatsächliche Ergebnisse ersetzen).

> Falls die oben genannten Prüfpunkte mit dem PR-Text kollidieren, aktualisieren Sie bitte zuerst die PR-Beschreibung, bevor Sie einreichen, um zu vermeiden, dass die Prüfung wegen inkonsistentem Status blockiert wird.

## Visual Evidence (if applicable)

[Pflichtfeld] Falls dieser PR das Berichtsformat, die Berichtsdarstellung oder die Web-UI-Oberfläche ändert, fügen Sie hier bitte Screenshots der betroffenen Berichte/Seiten ein; bei Vorher-/Nachher-Unterschieden bevorzugt den Vorher-Nachher-Vergleich anfügen. Screenshots von Issue-/PR-Abläufen, Review-Screenshots, einmalige Abnahme-Screenshots und temporäre visuelle Belege bitte in der PR-Beschreibung, in PR-Kommentaren, als GitHub-Anhänge, in Actions-Artefakten oder als extern zugängliche Links unterbringen und nicht als Repository-Dateien einpflegen.
*(EN) If this PR changes report formatting, report rendering, or Web UI, attach screenshots of the affected report/page here; before/after screenshots are preferred when relevant. Issue/PR process screenshots, review screenshots, one-off acceptance screenshots, and temporary visual evidence should be linked from the PR body/comments, GitHub attachments, Actions artifacts, or external accessible evidence; do not commit them as repository files.)*

> Falls keine Screenshots verfügbar sind, geben Sie bitte im Feld „Grund" ausdrücklich Ersatzbelege an (z. B. Playwright/e2e-Artefaktpfade, Review-Links) samt nachvollziehbaren Befehlen; das Feld darf nicht leer bleiben. Bei Änderungen an Web-Einstellungen/Berichtsdarstellung muss sichergestellt sein, dass Screenshots oder Ersatzbelege eindeutig auf die geänderten Elemente verweisen.
>
> Falls dieser PR die Web-UI ändert, wird empfohlen, mindestens einen reproduzierbaren Pfad anzugeben, z. B. (bevorzugt die Settings-Seite):
>
> - Playwright-Screenshot-Artefakt: `apps/dsa-web/e2e/smoke.spec.ts` (`cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page renders title and save actions after login"`)
> - Review-Beleglink: direkt Actions-Artefakte, GitHub-Kommentaranhänge oder extern zugängliche Links verwenden.

> Vorlage für Ersatzbelege (Empfehlung für Änderungen an der Settings-Seite):
> - Befehl: `cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page"`
> - Artefaktpfad: `apps/dsa-web/test-results/**/smoke-settings-page-*.png`
> - Hinweis: Auf dem Screenshot müssen die in dieser Änderung betroffenen Systemeinstellungen sichtbar sein (Felder, Labels, Hilfetexte)

- Screenshot-Links (Pflichtfeld bei Web-UI-/Berichtsänderungen; falls nicht vorhanden, unten unter „Grund für Nicht-Anwendbarkeit" Ersatzbelege angeben):
- Empfohlene Benennung für die Settings-Seite: `smoke-settings-page-zh` / `smoke-settings-page-en`
- Vorher-Nachher-Vergleich / Before & After (falls vorhanden):
- Hinweis zu geänderten Settings-Feldern: Der Screenshot oder das Artefakt muss das Feld `MARKET_REVIEW_REGION` samt Hilfetext-Block (Chinesisch/Englisch) eindeutig enthalten.
- Grund für Nicht-Anwendbarkeit / Reason if not applicable (falls keine Screenshots beigefügt sind, muss dieser Punkt ausgefüllt werden und reproduzierbare Belege samt Befehlen enthalten):
  - Playwright-Befehl (falls keine Screenshots): `cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page"`
  - Artefaktpfad (falls keine Screenshots): `apps/dsa-web/test-results/**/smoke-settings-page-*.png`
  - Hinweis: Auf dem Screenshot (oder im Artefakt) müssen die Texte der geänderten Einstellungsfelder und die Hilfetexte sichtbar sein.

> Falls dieser PR Web-Einstellungsfelder ändert (Felder, Texte oder Hilfetexte), müssen Screenshots oder Ersatzbelege auf den entsprechenden Bereich der Einstellungen verweisen und auf die Änderung rückführbar sein; dieser Punkt ist ein Pflichtfeld.

> Falls dieser PR die Web-UI oder die Berichtsdarstellung ändert und keine Screenshots verfügbar sind, muss das Grundfeld reproduzierbare Ersatzbelege enthalten (z. B. Playwright-Screenshot-Artefaktpfad + Befehl) und darf nicht leer bleiben.

## Compatibility And Risk

Bitte beschreiben Sie die Auswirkungen auf die Kompatibilität und potenzielle Risiken (falls keine vorhanden, bitte `None` schreiben).  
*(EN) Describe compatibility impact and potential risks (write `None` if not applicable).*

- Falls dieser PR die Kompatibilitätssemantik von Drittanbieter-Modellen/APIs, Anfrageparameter, Routing-Präfixe oder Provider-Fallback ändert, geben Sie bitte einen **offiziellen Quelllink oder eine Ankündigung** an und legen Sie dar, ob es sich um eine dauerhafte Einschränkung, eine aktuelle Laufzeit-Einschränkung oder eine temporäre Kompatibilitätsbehandlung handelt.  
  Bitte ergänzen Sie unten die betroffenen externen APIs/Dienste, den Regressionsumfang und das Zurückfall-Verfahren.  
  *(EN) If this PR changes third-party model/API compatibility, request parameters, routing prefixes, or provider fallback behavior, include an **official source link or announcement** and clarify whether the rule is permanent, runtime-specific, or a temporary compatibility workaround.)*
- Falls dieser PR keine Drittanbieter-Modelle/APIs, provider/model/base URL oder Laufzeit-Konfigurationsspeicher-/Bereinigungs-/Migrationslogik berührt, bestätigen Sie bitte direkt mit folgendem Text (ohne weitere Ausführung):  
  `Dieser PR ändert provider/model/base URL und die Semantik der Laufzeit-Konfigurationsbereinigung/-migration nicht; bestehende Konfiguration bleibt unverändert; Rollback erfolgt durch Revert dieses Commits.`
- Falls dieser PR `.github/PULL_REQUEST_TEMPLATE.md` / PR-Prozess-Template-Dateien ändert, legen Sie hier bitte klar dar: Es betrifft nur den Kollaborationsprozess und die Template-Pflege, nicht das Laufzeitverhalten; Rollback erfolgt per Revert; ergänzen Sie zudem, ob der automatisierte Commit-Prozess betroffen ist.  
  *(EN) If this PR changes `.github/PULL_REQUEST_TEMPLATE.md` or other PR workflow files, state that it only affects contribution governance templates (no runtime behavior), provide rollback by revert, and note any CI/checklist impact.)*
- Falls dieser PR von einer bestimmten Laufzeit / einem festgelegten Abhängigkeitsfenster abhängt (z. B. LiteLLM-Versionsbereich, OpenAI-kompatible Routen, YAML-Alias-Verhalten), geben Sie bitte die aktuell verifizierte Kompatibilitätsspanne und die abgedeckten Pfade an.  
  *(EN) If this PR depends on a specific runtime or pinned dependency window (for example a LiteLLM version range, OpenAI-compatible routing, or YAML alias behavior), state the compatibility window you verified and which code paths were covered.)*
- Falls dieser PR Laufzeit-Konfigurationsspeicher-/Bereinigungs-/Migrations- oder Backfill-Logik berührt, legen Sie bitte ausdrücklich dar, ob bestehende Konfiguration automatisch überschrieben, geleert, migriert oder unverändert gelassen wird, sowie wie Nutzer das ursprüngliche Verhalten wiederherstellen können.  
  *(EN) If this PR touches runtime config save/cleanup/migration/backfill logic, explicitly describe whether existing config is rewritten, cleared, migrated, or left intact, and how users can restore the previous behavior.)*
- Falls dieser PR provider/model/base URL oder Laufzeit-Konfigurationsspeicher-/Bereinigungs-/Migrationslogik **nicht berührt** (diese Zeile dient nur als Erklärung), schreiben Sie bitte ausdrücklich: `Dieser PR ändert provider/model/base URL und die Semantik der Laufzeit-Konfigurationsbereinigung/-migration nicht; bestehende Konfiguration bleibt unverändert; Rollback erfolgt durch Revert dieses Commits.`

## Rollback Plan

Bitte geben Sie mindestens einen umsetzbaren Rollback-Schritt an (Pflichtfeld).  
*(EN) Provide at least one actionable rollback step (required).*

- Bei Kompatibilitätsfixes sollte standardmäßig der **minimale Rollback-Weg** angegeben werden (z. B. `revert this PR`), einschließlich der Angabe, ob zusätzliche Konfigurations- oder Daten-Rollbacks erforderlich sind.  
  *(EN) For compatibility fixes, include the **minimal rollback path** (for example `revert this PR`) and whether any additional config or data rollback is required.)*

## EXTRACT_PROMPT Change (if applicable)

Falls dieser PR den `EXTRACT_PROMPT` in `src/services/image_stock_extractor.py` ändert, fügen Sie hier bitte den vollständigen, aktualisierten Prompt ein.  
*If this PR changes `EXTRACT_PROMPT` in `src/services/image_stock_extractor.py`, paste the full updated prompt here:*

<details>
<summary>Aufklappen / Expand: Full EXTRACT_PROMPT</summary>

```
(paste full prompt here)
```

</details>

## Checklist

- [ ] Dieser PR hat eine klare Motivation und einen klaren Nutzen / This PR has a clear motivation and value
- [ ] Reproduzierbare Verifikationsbefehle und -ergebnisse wurden bereitgestellt / Reproducible verification commands and results are included
- [ ] Kompatibilität und Risiken wurden bewertet / Compatibility and risk have been assessed
- [ ] Ein Rollback-Plan wurde bereitgestellt / A rollback plan is provided
- [ ] Bei Änderungen am Berichtsformat oder der Web-UI wurden betroffene Berichts-/Seiten-Screenshots in der PR-Beschreibung/in Kommentaren verlinkt, und einmalige Abnahme-Screenshots wurden nicht als Repository-Dateien eingecheckt / If report formatting or Web UI changed, affected report/page screenshots are linked in the PR body/comments and one-off acceptance screenshots are not committed as repository files
- [ ] Falls dieser PR Web-Einstellungsfelder ändert (Felder, Texte oder Hilfetexte), Screenshots der Einstellungsseite bereitstellen; falls nicht möglich, alternative visuelle Belege (Befehl + Artefaktpfad) angeben, die auf die geänderten Elemente verweisen / If Web settings fields changed (labels or help text), screenshots of the settings page are required; if unavailable, provide alternative visual evidence with command + artifact path that points to the changed item.
- [ ] Bei benutzersichtbaren Änderungen wurden die relevanten Dokumente und `docs/CHANGELOG.md` aktualisiert; `README.md` wird nur bei Änderungen auf Homepage-Ebene aktualisiert, Details vorzugsweise in `docs/*.md` / If user-visible changes are included, relevant docs and `docs/CHANGELOG.md` are updated; `README.md` is updated only for homepage-level changes, with details kept in `docs/*.md`
