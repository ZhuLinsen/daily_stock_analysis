# Repository Claude Skills

Dieses Verzeichnis enthält repositoryweite Kollaborations-Skills und gehört zum Versionsbestand.

- Quelle der Wahrheit für Regeln: `AGENTS.md` im Repository-Root
- Kompatibler Einstiegspunkt: `CLAUDE.md` im Root (sollte ein Symlink auf `AGENTS.md` sein)
- Skills in diesem Verzeichnis müssen mit `AGENTS.md` konsistent bleiben
- `.claude/reviews/` enthält lokale Analyse-Artefakte und ist keine Quelle der Wahrheit für Regeln

Falls künftig andere Agent-Verzeichnisse unterstützt werden sollen (z. B. `.agents/skills/` oder `.github/skills/`), sollte zunächst eine einzige Quelle der Wahrheit festgelegt und dann über Skripte oder Spiegel-Synchronisierung aktualisiert werden, anstatt mehrere inhaltsgleiche Dateien dauerhaft manuell zu pflegen.
