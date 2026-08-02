# Beitragsleitfaden

Vielen Dank für dein Interesse an diesem Projekt! Beiträge jeder Art sind willkommen.

## 🐛 Bug melden

1. Zuerst [Issues](https://github.com/ZhuLinsen/daily_stock_analysis/issues) durchsuchen, um sicherzustellen, dass das Problem noch nicht gemeldet wurde
2. Ein neues Issue mit der Bug-Report-Vorlage erstellen
3. Detaillierte Schritte zur Reproduktion und Umgebungsinformationen angeben

## 💡 Funktionsvorschläge

1. Zuerst die Issues durchsuchen, um sicherzustellen, dass der Vorschlag noch nicht eingebracht wurde
2. Ein neues Issue mit der Feature-Request-Vorlage erstellen
3. Dein Nutzungsszenario und die gewünschte Funktion detailliert beschreiben

## 🔧 Code beitragen

### Entwicklungsumgebung

```bash
# Repository klonen
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis

# Virtuelle Umgebung erstellen
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Abhängigkeiten installieren
pip install -r requirements.txt

# Umgebungsvariablen konfigurieren
cp .env.example .env
```

### Ablauf für das Einbringen

1. Dieses Repository forken
2. Feature-Branch erstellen: `git checkout -b feature/your-feature`
3. Änderungen committen: `git commit -m 'feat: add some feature'`
4. Branch pushen: `git push origin feature/your-feature`
5. Pull Request erstellen

### Commit-Konventionen

Die [Conventional Commits](https://www.conventionalcommits.org/)-Konvention verwenden:

```
feat: neue Funktion
fix: Bug-Fix
docs: Dokumentationsänderung
style: Codeformatierung (ohne Funktionsänderung)
refactor: Refactoring
perf: Leistungsoptimierung
test: Tests betreffend
chore: Build/Werkzeuge betreffend
```

Beispiele:
```
feat: DingTalk-Roboter-Support hinzufügen
fix: 429-Rate-Limit-Retry-Logik reparieren
docs: README-Bereitstellungshinweise aktualisieren
```

### Codestil

- Python-Code folgt PEP 8
- Funktionen und Klassen benötigen Docstrings
- Wichtige Logik mit Kommentaren versehen
- Neue Funktionen erfordern aktualisierte zugehörige Dokumentation

### Automatische CI-Prüfung

Nach dem Einreichen des PR führt die CI automatisch die folgenden Prüfungen aus:

| Prüfpunkt | Erläuterung | Muss bestehen |
|--------|------|:--------:|
| backend-gate | `scripts/ci_gate.sh` (py_compile + schwere flake8-Fehler + lokale Kernskripte + offline pytest) | ✅ |
| docker-build | Docker-Image-Build und Smoke-Test kritischer Modul-Importe | ✅ |
| web-gate | Bei Frontend-Änderungen Ausführen von `npm run lint` + `npm run build` | ✅ (wenn ausgelöst) |
| pr-review | Automatische Auslösung bei PR pausiert; nur noch manuell über `workflow_dispatch` durch Maintainer mit PR-Nummer; liest PR-Metadaten und Diff über die GitHub-API, ohne den Code von Fork-PRs zu checken oder auszuführen | ❌ (Hilfsprüfung) |
| network-smoke | Zeitlich/manuell Ausführen von `pytest -m network` + `scripts/test.sh quick` (nicht blockierend) | ❌ (Beobachtung) |

**Lokale Prüfungen:**

```bash
# Backend-Gate (empfohlen)
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh

# Frontend-Gate (falls apps/dsa-web geändert wurde)
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

## 📋 Bevorzugte Beitragsrichtungen

Für die aktuellen Kernfunktionen und Haupteinstiegspunkte des Projekts siehe [README](../README.md):

- 🔔 Neue Benachrichtigungskanäle (DingTalk, Feishu, Telegram)
- 🤖 Neue AI-Modell-Support (GPT-4, Claude)
- 📊 Anbindung neuer Datenquellen
- 🐛 Bug-Fixes und Leistungsoptimierung
- 📖 Dokumentationsverbesserung und Übersetzung

## ❓ Fragen

Bei Fragen jederzeit gern:
- Ein Issue zur Diskussion erstellen
- Vorhandene Issues und Discussions ansehen

Nochmals vielen Dank für deinen Beitrag! 🎉
