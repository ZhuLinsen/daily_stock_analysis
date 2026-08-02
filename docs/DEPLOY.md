# 🚀 Bereitstellungs-Anleitung

Dieses Dokument beschreibt, wie das intelligente Analyse-System für A-Aktien-Watchlisten auf einem Server bereitgestellt wird.

## 📋 Vergleich der Bereitstellungsoptionen

| Option | Vorteile | Nachteile | Empfohlener Einsatzbereich |
|------|------|------|----------|
| **Docker Compose** ⭐ | Ein-Klick-Deployment, isolierte Umgebung, einfach zu migrieren, einfach zu aktualisieren | Docker muss installiert sein | **Empfohlen**: für die meisten Szenarien |
| **Direkte Bereitstellung** | Einfach und direkt, keine zusätzlichen Abhängigkeiten | Abhängig von der Umgebung, Migration aufwendig | Kurzzeitige Tests |
| **Systemd-Dienst** | Systemweite Verwaltung, Autostart beim Hochfahren | Aufwendige Konfiguration | Langfristiger stabiler Betrieb |
| **Supervisor** | Prozessverwaltung, automatischer Neustart | Zusätzliche Installation erforderlich | Verwaltung mehrerer Prozesse |

**Fazit: Empfohlen wird die Verwendung von Docker Compose — Migration am schnellsten und bequemsten!**

---

## 🐳 Option 1: Docker Compose-Bereitstellung (empfohlen)

### 1. Docker installieren

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# CentOS
sudo yum install -y docker docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

### 2. Konfigurationsdatei vorbereiten

```bash
# Code klonen (oder Code auf den Server hochladen)
git clone <your-repo-url> /opt/stock-analyzer
cd /opt/stock-analyzer

# Konfigurationsdatei kopieren und bearbeiten
cp .env.example .env
vim .env  # Echte API-Keys usw. eintragen
```

### 3. Mit einem Klick starten

```bash
# Bauen und starten (enthält gleichzeitig den geplanten Analyse- und den Web-UI-Dienst)
docker-compose -f ./docker/docker-compose.yml up -d

# Logs ansehen
docker-compose -f ./docker/docker-compose.yml logs -f

# Laufenden Status anzeigen
docker-compose -f ./docker/docker-compose.yml ps
```

Nach erfolgreichem Start kannst du in deinem Browser `http://Server-Public-IP:8000` eingeben, um die Web-Verwaltungsoberfläche zu öffnen. Falls sie sich nicht öffnen lässt, denke daran, im „Security Group" (Sicherheitsgruppe) der Cloud-Server-Konsole den Port 8000 freizugeben.

> Du weißt nicht, wie du darauf zugreifen kannst? → [Anleitung für den Zugriff auf die Web-Oberfläche des Cloud-Servers](deploy-webui-cloud.md)

### 3.1 Ressourcen-Empfehlungen

Standardmäßig setzt `docker/docker-compose.yml` für jeden Dienst `limits.memory: 1G` und `reservations.memory: 512M` — dies ist der empfohlene Ausgangspunkt für vollständige Analyseszenarien.

- Minimal möglich: `512M`, nur geeignet für leichtgewichtige Web/API-Szenarien mit einer einzelnen Aktie und geringer Nebenläufigkeit; empfohlen wird `MAX_WORKERS=1` zu setzen.
- Empfohlen: `1G`, geeignet für die normale Analyse beim separaten Betrieb von `server` oder `analyzer`.
- Hohe Last: `2G+`, geeignet für den gleichzeitigen Start von `server + analyzer`, mehrere Aktien, standardmäßig `MAX_WORKERS=3`, Marktrückblick, erweiterte Nachrichten, Bildberichte oder die eingebaute Aktienauswahl.

Wenn nur `512M` verfügbar ist, vermeide es bitte, `server` und `analyzer` gleichzeitig zu starten, und deaktiviere nicht zwingend erforderliche Marktrückblick-, erweiterte Nachrichten- und Bildbericht-Funktionen.

### 4. Häufige Verwaltungsbefehle

```bash
# Dienst stoppen
docker-compose -f ./docker/docker-compose.yml down

# Dienst neu starten
docker-compose -f ./docker/docker-compose.yml restart

# Nach Code-Update neu bereitstellen
git pull
docker-compose -f ./docker/docker-compose.yml build --no-cache
docker-compose -f ./docker/docker-compose.yml up -d

# In den Container zur Fehlersuche wechseln
docker-compose -f ./docker/docker-compose.yml exec -u dsa stock-analyzer bash

# Eine Analyse manuell ausführen
docker-compose -f ./docker/docker-compose.yml exec -u dsa stock-analyzer python main.py --no-notify
```

### 5. Datenpersistenz

Die Daten werden automatisch in den Verzeichnissen des Host-Systems gespeichert:
- `./data/` - Datenbankdateien
- `./logs/` - Logdateien
- `./reports/` - Analyseberichte

### 6. Hinweise zu Berechtigungen

Der Starteinstieg des Docker-Images erstellt und repariert automatisch die Berechtigungen der entsprechenden Mount-Verzeichnisse `./data`, `./logs`, `./reports` und führt die Anwendung anschließend als Nicht-root-Benutzer (`dsa`, UID 1000) aus. Bei normaler Bereitstellung ist kein manuelles `chown` / `chmod` erforderlich.

Wenn du explizit `--user` / Compose `user:` angibst oder Umgebungen wie schreibgeschützte Mounts, rootless Docker oder NFS verwendest, in denen der Container die Eigentümer nicht reparieren kann, stelle bitte sicher, dass der tatsächlich ausführende Benutzer Schreibberechtigung für diese Verzeichnisse besitzt.

---

## 🖥️ Option 2: Direkte Bereitstellung

### 1. Python-Umgebung installieren

```bash
# Python 3.10+ installieren
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip

# Virtuelle Umgebung erstellen
python3.10 -m venv /opt/stock-analyzer/venv
source /opt/stock-analyzer/venv/bin/activate
```

### 2. Abhängigkeiten installieren

```bash
cd /opt/stock-analyzer
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. Umgebungsvariablen konfigurieren

```bash
cp .env.example .env
vim .env  # Konfiguration eintragen
```

### 4. Ausführen

```bash
# Einmalige Ausführung
python main.py

# Geplanter Task-Modus (im Vordergrund)
python main.py --schedule

# Hintergrundausführung (mit nohup)
nohup python main.py --schedule > /dev/null 2>&1 &

# Web-Verwaltungsoberfläche starten (für Cloud-Server zuerst WEBUI_HOST=0.0.0.0 in .env setzen)
python main.py --webui-only

# Web-Oberfläche starten (führt beim Start einmal eine Analyse aus; für tägliche Ausführung --schedule hinzufügen oder SCHEDULE_ENABLED=true setzen)
python main.py --webui
```

> Du weißt nicht, wie du darauf zugreifen kannst? → [Anleitung für den Zugriff auf die Web-Oberfläche des Cloud-Servers](deploy-webui-cloud.md)

---

## 🔧 Option 3: Systemd-Dienst

Erstelle eine Systemd-Dienstdatei, um Autostart beim Hochfahren und automatische Neustarts zu erreichen:

### 1. Dienstdatei erstellen

```bash
sudo vim /etc/systemd/system/stock-analyzer.service
```

Inhalt:
```ini
[Unit]
Description=Intelligentes Analyse-System für A-Aktien-Watchlisten
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/stock-analyzer
Environment="PATH=/opt/stock-analyzer/venv/bin"
ExecStart=/opt/stock-analyzer/venv/bin/python main.py --schedule
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

### 2. Dienst starten

```bash
# Konfiguration neu laden
sudo systemctl daemon-reload

# Dienst starten
sudo systemctl start stock-analyzer

# Autostart beim Hochfahren aktivieren
sudo systemctl enable stock-analyzer

# Status anzeigen
sudo systemctl status stock-analyzer

# Logs ansehen
journalctl -u stock-analyzer -f
```

---

## ⚙️ Konfigurationshinweise

### Pflichtkonfigurationen

| Konfigurationspunkt | Beschreibung | Woher beziehen |
|--------|------|----------|
| `ANSPIRE_API_KEYS` / `AIHUBMIX_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Mindestens ein AI-Modell konfigurieren; empfohlen wird bevorzugt Anspire oder AIHubMix | Konsole des jeweiligen Anbieters |
| `STOCK_LIST` | Watchlist | Kommagetrennte Aktiencodes |
| Benachrichtigungskanal | Mindestens einen konfigurieren, z. B. WeCom, Feishu, Telegram oder E-Mail | Entsprechende Benachrichtigungsplattform |

### Optionale Konfigurationen

| Konfigurationspunkt | Standardwert | Beschreibung |
|--------|--------|------|
| `SCHEDULE_ENABLED` | `false` | Ob der geplante Task aktiviert ist |
| `SCHEDULE_TIME` | `18:00` | Tägliche Ausführungszeit |
| `MARKET_REVIEW_ENABLED` | `true` | Ob der Marktrückblick aktiviert ist |
| `ANSPIRE_API_KEYS` | - | Anspire Large Model und Nachrichtensuche (empfohlen) |
| `AIHUBMIX_KEY` | - | AIHubMix ein Key für mehrere Modelle (empfohlen) |
| `SERPAPI_API_KEYS` | - | SerpAPI Echtzeit-Finanznachrichtensuche (empfohlen) |
| `TAVILY_API_KEYS` | - | Tavily Nachrichtensuche (optional) |
| `MINIMAX_API_KEYS` | - | MiniMax Suche (optional) |

---

## 🌐 Proxy-Konfiguration

Wenn der Server in China steht, benötigt der Zugriff auf die Gemini API einen Proxy:

### Docker-Methode

`docker-compose.yml` bearbeiten:
```yaml
environment:
  - http_proxy=http://your-proxy:port
  - https_proxy=http://your-proxy:port
```

### Direkte Bereitstellung

Oben in `main.py` bearbeiten:
```python
os.environ["http_proxy"] = "http://your-proxy:port"
os.environ["https_proxy"] = "http://your-proxy:port"
```

---

## 📊 Überwachung und Wartung

### Logs ansehen

```bash
# Docker-Methode
docker-compose -f ./docker/docker-compose.yml logs -f --tail=100

# Direkte Bereitstellung
tail -f /opt/stock-analyzer/logs/stock_analysis_*.log
```

### Health-Check

```bash
# Prozesse prüfen
ps aux | grep main.py

# Neueste Berichte prüfen
ls -la /opt/stock-analyzer/reports/
```

### Regelmäßige Wartung

```bash
# Alte Logs aufräumen (7 Tage aufbewahren)
find /opt/stock-analyzer/logs -mtime +7 -delete

# Alte Berichte aufräumen (30 Tage aufbewahren)
find /opt/stock-analyzer/reports -mtime +30 -delete
```

---

## ❓ Häufige Fragen

### 1. Docker-Build schlägt fehl

```bash
# Cache leeren und neu bauen
docker-compose -f ./docker/docker-compose.yml build --no-cache
```

### 2. API-Zeitüberschreitung

Prüfe die Proxy-Konfiguration und stelle sicher, dass der Server auf die Gemini API zugreifen kann.

### 3. Datenbank ist gesperrt

```bash
# Dienst stoppen und Lock-Dateien löschen
rm /opt/stock-analyzer/data/*.lock
```

### 4. Nicht genügend Arbeitsspeicher

Standardmäßig wird im Compose `1G` empfohlen. Wenn weiterhin OOM auftritt oder die Plattform den Container beendet, erhöhe bitte das Speicherlimit in `docker-compose.yml`; beim gleichzeitigen Betrieb von `server + analyzer`, mehreren Aktien, Marktrückblick, Bildberichten oder der eingebauten Aktienauswahl werden `2G+` empfohlen:
```yaml
deploy:
  resources:
    limits:
      memory: 1G
    reservations:
      memory: 512M
```

Wenn in einer Umgebung mit geringer Ausstattung nur `512M` verfügbar ist, empfiehlt es sich, `MAX_WORKERS=1` zu setzen, nur einen der Dienste `server` oder `analyzer` zu starten und nicht zwingend erforderliche Marktrückblick-, erweiterte Nachrichten- und Bildbericht-Aufgaben zu reduzieren.

### 5. Nach dem Öffnen der WebUI sind die UI-Elemente abnormal vergrößert / das Layout ist zerstört

**Symptom**: Port 8000 ist erreichbar, aber Text, Buttons und Karten auf der Seite sind abnormal vergrößert und haben kein normales Layout.

**Grundursache**: `static/index.html` existiert, aber die CSS/JS-Ressourcendateien fehlen (`static/assets/` ist leer oder existiert nicht). Der Browser kann Styles und Skripte nicht laden, wodurch rohes HTML gerendert wird.

**Lösung**:

- **Docker-Bereitstellung**: Führe die folgenden Befehle aus, um das Image neu zu bauen (stelle sicher, dass das Frontend korrekt ins Image gepackt wurde):
  ```bash
  docker-compose -f ./docker/docker-compose.yml down
  docker-compose -f ./docker/docker-compose.yml build --no-cache
  docker-compose -f ./docker/docker-compose.yml up -d
  ```
  Nach dem Build den Browser-Cache aktualisieren (`Ctrl+Shift+R`) und dann erneut zugreifen.

- **Direkte Bereitstellung (pip + python)**: Zuerst das Frontend bauen, dann den Dienst starten:
  ```bash
  # Node.js 18+ installieren (empfohlen 20+, falls noch nicht installiert)
  # Frontend bauen
  cd apps/dsa-web
  npm ci
  npm run build
  cd ../..
  # Dienst starten
  python main.py --webui-only
  ```

**Überprüfung**: Prüfe mit den Browser-Entwicklertools (F12 → Network), ob es 404-Fehler für `/assets/index-*.js` und `/assets/index-*.css` gibt; falls ja, fehlen die Ressourcen — führe die oben genannten Schritte aus, um neu zu bauen.

---

## 🔄 Schnelle Migration

Von einem Server auf einen anderen migrieren:

```bash
# Quellserver: Paketieren
cd /opt/stock-analyzer
tar -czvf stock-analyzer-backup.tar.gz .env data/ logs/ reports/

# Zielserver: Bereitstellen
mkdir -p /opt/stock-analyzer
cd /opt/stock-analyzer
git clone <your-repo-url> .
tar -xzvf stock-analyzer-backup.tar.gz
docker-compose -f ./docker/docker-compose.yml up -d
```

---

## ☁️ Option 4: GitHub Actions-Bereitstellung (ohne Server)

**Die einfachste Lösung!** Kein Server erforderlich — nutzt die kostenlosen Rechenressourcen von GitHub.

### Vorteile
- ✅ **Vollständig kostenlos** (2000 Minuten pro Monat)
- ✅ **Kein Server erforderlich**
- ✅ **Automatische zeitgesteuerte Ausführung**
- ✅ **Null Wartungskosten**

### Einschränkungen
- ⚠️ Zustandslos (jede Ausführung ist eine neue Umgebung)
- ⚠️ Die zeitliche Planung kann einige Minuten Verzögerung haben
- ⚠️ Es kann keine HTTP API bereitgestellt werden

### Bereitstellungsschritte

#### 1. GitHub-Repository erstellen

```bash
# git initialisieren (falls noch nicht vorhanden)
cd /path/to/daily_stock_analysis
git init
git add .
git commit -m "Initial commit"

# GitHub-Repository erstellen und pushen
# Nachdem das neue Repository auf der GitHub-Webseite erstellt wurde:
git remote add origin https://github.com/dein-benutzername/daily_stock_analysis.git
git branch -M main
git push -u origin main
```

#### 2. Secrets konfigurieren (wichtig!)

Öffne die Repository-Seite → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Füge die folgenden Secrets hinzu:

| Secret-Name | Beschreibung | Pflicht |
|------------|------|------|
| `ANSPIRE_API_KEYS` | Anspire Open API Key (ein Key aktiviert Large Model und Suche) | Empfohlen |
| `AIHUBMIX_KEY` | AIHubMix API Key (ein Key für mehrere Modelle) | Empfohlen |
| `ANTHROPIC_API_KEY` | Anthropic API Key | Optional |
| `GEMINI_API_KEY` | Gemini AI API Key | Optional |
| `OPENAI_API_KEY` | OpenAI-kompatibler API Key | Optional |
| `WECHAT_WEBHOOK_URL` | WeCom-Roboter-Webhook | Optional* |
| `FEISHU_WEBHOOK_URL` | Feishu-Roboter-Webhook | Optional* |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | Optional* |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | Optional* |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID | Optional* |
| `EMAIL_SENDER` | Absender-E-Mail-Adresse | Optional* |
| `EMAIL_PASSWORD` | E-Mail-Autorisierungscode | Optional* |
| `SERVERCHAN3_SENDKEY` | ServerChan³ Sendkey | Optional* |
| `CUSTOM_WEBHOOK_URLS` | Benutzerdefinierte Webhooks (mehrere, kommagetrennt) | Optional* |
| `STOCK_LIST` | Watchlist, z. B. `600519,300750` | ✅ |
| `SERPAPI_API_KEYS` | SerpAPI Key | Empfohlen |
| `TAVILY_API_KEYS` | Tavily Such-API-Key | Optional |
| `BOCHA_API_KEYS` | Bocha-Such-API-Key | Optional |
| `BRAVE_API_KEYS` | Brave Search API Key | Optional |
| `MINIMAX_API_KEYS` | MiniMax Coding Plan Web Search | Optional |
| `SEARXNG_BASE_URLS` | Selbst gehostete SearXNG-Instanz (ohne Quotenbegrenzung als Fallback; `format: json` muss in settings.yml aktiviert sein); bei leer lassen wird automatisch eine öffentliche Instanz erkannt | Optional |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Ob bei leerem `SEARXNG_BASE_URLS` automatisch öffentliche Instanzen von `searx.space` abgerufen werden (Standard `true`) | Optional |
| `TUSHARE_TOKEN` | Tushare Token | Optional |
| `GEMINI_MODEL` | Modellname (Standard gemini-2.0-flash) | Optional |

> *Hinweis: Mindestens ein Benachrichtigungskanal konfigurieren; gleichzeitiges Pushen über mehrere Kanäle wird unterstützt.

#### 3. Workflow-Datei überprüfen

Stelle sicher, dass `.github/workflows/00-daily-analysis.yml` existiert und committet ist:

```bash
git add .github/workflows/00-daily-analysis.yml
git commit -m "Add GitHub Actions workflow"
git push
```

#### 4. Manuelle Testausführung

1. Repository-Seite öffnen → **Actions**-Tab
2. Den Workflow **„Tägliche Aktienanalyse"** auswählen
3. Auf die Schaltfläche **„Run workflow"** klicken
4. Ausführungsmodus wählen:
   - `full` - vollständige Analyse (Aktien + Markt)
   - `market-only` - nur Marktrückblick
   - `stocks-only` - nur Aktienanalyse
5. Auf die grüne Schaltfläche **„Run workflow"** klicken

#### 5. Ausführungs-Logs ansehen

- Auf der Actions-Seite ist die Ausführungshistorie sichtbar
- Auf eine bestimmte Ausführung klicken, um detaillierte Logs anzusehen
- Analyseberichte werden 30 Tage lang als Artifact gespeichert

### Hinweise zur Zeitplanung

Standardkonfiguration: **Montag bis Freitag, 18:00 Uhr Pekinger Zeit** automatische Ausführung

Zeit ändern: Bearbeite den cron-Ausdruck in `.github/workflows/00-daily-analysis.yml`:

```yaml
schedule:
  - cron: '0 10 * * 1-5'  # UTC-Zeit, +8 = Pekinger Zeit
```

Häufige cron-Beispiele:
| Ausdruck | Beschreibung |
|--------|------|
| `'0 10 * * 1-5'` | Montag bis Freitag 18:00 (Pekinger Zeit) |
| `'30 7 * * 1-5'` | Montag bis Freitag 15:30 (Pekinger Zeit) |
| `'0 10 * * *'` | Täglich 18:00 (Pekinger Zeit) |
| `'0 2 * * 1-5'` | Montag bis Freitag 10:00 (Pekinger Zeit) |

### Watchlist ändern

Methode 1: Repository-Secret `STOCK_LIST` ändern

Methode 2: Code direkt ändern und pushen:
```bash
# .env.example ändern oder einen Standardwert im Code setzen
git commit -am "Update stock list"
git push
```

### Häufige Fragen

**F: Warum wurde der geplante Task nicht ausgeführt?**
A: GitHub-Actions-Tasks können 5–15 Minuten Verzögerung haben und werden nur ausgelöst, wenn das Repository Aktivität aufweist. Ein längerer Zeitraum ohne Commits kann dazu führen, dass der Workflow deaktiviert wird.

**F: Wie kann ich historische Berichte ansehen?**
A: Actions → Ausführung auswählen → Artifacts → `analysis-reports-xxx` herunterladen

**F: Reicht das kostenlose Kontingent?**
A: Jede Ausführung dauert etwa 2–5 Minuten; 22 Arbeitstage pro Monat = 44–110 Minuten, weit unter dem Limit von 2000 Minuten.

---

## 🌐 Auf dem Cloud-Server bereitgestellt, aber du weißt nicht, wie du mit dem Browser darauf zugreifen kannst?

Details siehe → [Anleitung für den Zugriff auf die Web-Oberfläche des Cloud-Servers](deploy-webui-cloud.md)

Behandelt werden: Start und Zugriff für direkte Bereitstellung und Docker, Security-Group/Firewall-Konfiguration, Fehlersuche bei häufigen Problemen, Nginx-Reverse-Proxy (optional).

---

**Viel Erfolg bei der Bereitstellung! 🎉**
