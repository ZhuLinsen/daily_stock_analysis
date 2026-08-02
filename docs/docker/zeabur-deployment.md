# Zeabur-Bereitstellungsleitfaden

Dieser Leitfaden beschreibt ausführlich, wie das A-Aktien-Watchlist-Intelligenz-Analysesystem auf Zeabur bereitgestellt wird, einschließlich der Funktionen WebUI und Discord-Bot.

## Inhaltsverzeichnis

- [1. Vorbereitung vor der Bereitstellung](#1-vorbereitung-vor-der-bereitstellung)
- [2. Bereitstellung auf Zeabur](#2-bereitstellung-auf-zeabur)
- [3. Startbefehl konfigurieren](#3-startbefehl-konfigurieren)
- [4. Discord-Bot-Bereitstellung](#4-discord-bot-bereitstellung)
- [5. Konfiguration der Umgebungsvariablen](#5-konfiguration-der-umgebungsvariablen)
- [6. Mount-Konfiguration](#6-mount-konfiguration)
- [7. Health-Check](#7-health-check)
- [8. Häufige Probleme](#8-häufige-probleme)

## 1. Vorbereitung vor der Bereitstellung

### 1.1 Voraussetzungen

- Zeabur-Konto
- GitHub-Konto (zum Verbinden des Repositorys)
- Discord-Entwicklerkonto (falls ein Bot bereitgestellt werden soll)
- Zugehörige API-Schlüssel (z. B. Gemini API Key, Suchdienst-API-Key usw.)

### 1.2 Vorbereitung des Repositorys

Stellen Sie sicher, dass Ihr Repository folgende Dateien enthält:

- `.github/workflows/docker-publish.yml` (wird automatisch erstellt)
- `docker/Dockerfile` (bereits vorhanden)
- Den vollständigen Projektcode

## 2. Bereitstellung auf Zeabur

### 2.1 GitHub-Repository verbinden

1. In der Zeabur-Konsole anmelden
2. „Neues Projekt" klicken
3. „Von GitHub importieren" wählen
4. Ihr Repository und Ihren Branch wählen (empfohlen `main`)
5. „Importieren" klicken

### 2.2 Build-Regeln konfigurieren

Zeabur erkennt die Datei `.github/workflows/docker-publish.yml` automatisch und baut das Image über GitHub Actions.

Wenn keine automatische Erkennung erfolgt, kann manuell konfiguriert werden:

1. Auf der Projektseite „Build-Regeln" klicken
2. „Dockerfile" wählen
3. Dockerfile-Pfad eintragen: `docker/Dockerfile`
4. „Speichern" klicken

### 2.3 Dienst starten

1. Warten, bis der Image-Build abgeschlossen ist
2. „Dienst starten" klicken
3. Nach dem Start des Dienstes kann auf dem Tab „Zugriff" die Zugriffsadresse abgerufen werden

### 2.4 Frontend-Build und statische Ressourcen

FastAPI hostet automatisch die Frontend-Ressourcen im Verzeichnis `static/`. Den Ausgabeort des Frontend-Bundles bestimmt
`apps/dsa-web/vite.config.ts`; standardmäßig wird nach dem Projektstammverzeichnis `static/` ausgegeben.

Das Dockerfile verwendet bereits einen mehrstufigen Build; das Frontend wird beim Image-Build automatisch gepackt.
Zum Überschreiben der Standard-Statikressourcen kann manuell auf dem Host gebaut und in den Container unter `/app/static` eingehängt werden.

### 2.5 Empfehlungen zur Ressourcenkonfiguration

Der Zeabur-Dienst sollte mit mindestens `1G` Arbeitsspeicher starten; `512M` eignet sich nur für leichtgewichtige Web/API-, Einzelaktien- und Niedrigparallel-Szenarien, und es wird empfohlen, `MAX_WORKERS=1` zu setzen.

- Minimal ausprobierbar: `512M` – nicht mehrere schwere Tasks gleichzeitig ausführen.
- Empfohlen: `1G` – geeignet für die reguläre Analyse mit einem einzelnen Dienst.
- Hohe Last: `2G+` – geeignet für gleichzeitigen Betrieb von Web/API mit geplanter Analyse, mehreren Aktien, Marktreview, Nachrichtenerweiterung, Bildberichten oder eingebauter Aktienauswahl.

Wenn nur `512M` zur Verfügung steht, vermeiden Sie bitte die gleichzeitige Bereitstellung einer Kombination mehrerer Dienste wie `server + analyzer` und deaktivieren Sie nicht zwingend benötigte Fähigkeiten wie Marktreview, Nachrichtenerweiterung und Bildberichte.

## 3. Startbefehl konfigurieren

### 3.1 Unterstützte Startmodi

Das System unterstützt mehrere Startmodi; je nach Bedarf können verschiedene Startbefehle konfiguriert werden:

| Modus | Startbefehl | Beschreibung |
|------|----------|------|
| Geplanter-Task-Modus (Standard) | `python main.py --schedule` | Aktienanalyse nach Plan ausführen |
| FastAPI-Modus | `python main.py --serve` | FastAPI starten und Analyse ausführen |
| Nur-FastAPI-Modus | `python main.py --serve-only` | Nur FastAPI starten, ohne Analyse |
| Nur Marktreview | `python main.py --market-review` | Nur die Marktreview-Analyse ausführen |

### 3.2 Startbefehl konfigurieren

1. In der Zeabur-Konsole zur Dienstseite gehen
2. „Einstellungen" klicken
3. Den Konfigurationspunkt „Startbefehl" finden
4. Den benötigten Startbefehl eingeben, z. B.:
    - FastAPI starten: `python main.py --serve`
    - Nur FastAPI starten: `python main.py --serve-only --host 0.0.0.0 --port 8000`
    - Geplante Tasks starten: `python main.py --schedule`
5. „Speichern" klicken
6. Dienst neu starten

## 4. Discord-Bot-Bereitstellung

### 4.1 Vorbereitung

1. Discord-Anwendung und Bot erstellen
   - Die [Discord-Entwicklerplattform](https://discord.com/developers/applications) besuchen
   - „New Application" klicken, um eine neue Anwendung zu erstellen
   - Auf dem Tab „Bot" „Add Bot" klicken, um den Bot zu erstellen
   - Das Bot-Token kopieren

2. Bot-Berechtigungen konfigurieren
   - Auf dem Tab „Bot" nach unten zu „Privileged Gateway Intents" scrollen
   - „Server Members Intent" und „Message Content Intent" aktivieren
   - Unter „OAuth2" -> „URL Generator" den Umfang „bot" wählen
   - Die gewünschten Berechtigungen wählen (z. B. „Send Messages", „Read Messages/View Channels" usw.)
   - Den erzeugten Einladungslink kopieren und den Bot zu Ihrem Server hinzufügen

### 4.2 Umgebungsvariablen konfigurieren

In der Konfiguration der „Umgebungsvariablen" in der Zeabur-Konsole folgende Variablen hinzufügen:

| Variablenname | Beschreibung | Beispielwert |
|--------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord-Bot-Token | `MTAxMjM0NTY3ODkwMTEyMzQ1Ng.GhIjKl.MnOpQrStUvWxYz1234567890` |
| `DISCORD_MAIN_CHANNEL_ID` | Hauptkanal-ID | `123456789012345678` |
| `DISCORD_WEBHOOK_URL` | Discord-Webhook-URL (optional) | `https://discord.com/api/webhooks/...` |

### 4.3 Bot starten

Die Bot-Funktion wird standardmäßig über die Konfiguration aktiviert; ein spezieller Startbefehl ist nicht erforderlich. Stellen Sie sicher, dass Ihre Konfigurationsdatei die botbezogene Konfiguration enthält oder über Umgebungsvariablen gesetzt ist.

## 5. Konfiguration der Umgebungsvariablen

### 5.1 Basis-Umgebungsvariablen

| Variablenname | Beschreibung | Standardwert |
|--------|------|--------|
| `PYTHONUNBUFFERED` | Python-ungepufferte Ausgabe aktivieren | `1` |
| `LOG_DIR` | Log-Verzeichnis | `/app/logs` |
| `DATABASE_PATH` | Datenbankpfad | `/app/data/stock_analysis.db` |

### 5.2 Konfiguration des API-Dienstes

| Variablenname | Beschreibung | Standardwert |
|--------|------|--------|
| `API_HOST` | Listenadresse des API-Dienstes | `0.0.0.0` |
| `API_PORT` | Port des API-Dienstes | `8000` |

> Die älteren Umgebungsvariablen `WEBUI_HOST`/`WEBUI_PORT`/`WEBUI_ENABLED` sind weiterhin kompatibel und werden automatisch an den API-Dienst weitergeleitet.

### 5.3 Analysebezogene Konfiguration

| Variablenname | Beschreibung |
|--------|------|
| `ANSPIRE_API_KEYS` | Anspire-Open-API-Schlüssel (gemeinsam für Großmodell und Suche, empfohlen) |
| `AIHUBMIX_KEY` | AIHubMix-API-Schlüssel (ein Schlüssel für mehrere Modelle, empfohlen) |
| `GEMINI_API_KEY` | Gemini-API-Schlüssel |
| `OPENAI_API_KEY` | OpenAI-kompatibler API-Schlüssel |
| `SERPAPI_API_KEYS` | SerpAPI-Schlüssel (empfohlen) |
| `TAVILY_API_KEYS` | Tavily-API-Schlüssel (kommasepariert) |
| `BOCHA_API_KEYS` | Bocha-API-Schlüssel (kommasepariert) |
| `BRAVE_API_KEYS` | Brave-Search-API-Schlüssel (kommasepariert) |
| `MINIMAX_API_KEYS` | MiniMax-API-Schlüssel (kommasepariert) |
| `SEARXNG_BASE_URLS` | SearXNG-Instanzadressen (kommasepariert, kontingentloser Fallback, muss in settings.yml `format: json` aktivieren); bei leerem Wert werden automatisch öffentliche Instanzen entdeckt |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Ob bei leerem `SEARXNG_BASE_URLS` automatisch öffentliche Instanzen von `searx.space` geholt werden (Standard `true`) |

### 5.4 Konfigurationsmethode

In der Zeabur-Konsole:

1. Zur Dienstseite gehen
2. „Umgebungsvariablen" klicken
3. „Umgebungsvariable hinzufügen" klicken
4. Variablennamen und -wert eingeben
5. „Speichern" klicken
6. Dienst neu starten

## 6. Mount-Konfiguration

### 6.1 Unterstützte Mount-Verzeichnisse

| Verzeichnis | Beschreibung |
|------|------|
| `/app/data` | Datenbank und Datendateien |
| `/app/logs` | Logdateien |
| `/app/reports` | Analyseberichte |

### 6.2 Mount konfigurieren

1. In der Zeabur-Konsole zur Dienstseite gehen
2. „Speicher" klicken
3. „Speichervolumen hinzufügen" klicken
4. „Persistenter Speicher" wählen
5. Den Mount-Pfad konfigurieren:
   - Pfad des Speichervolumens: `/app/data`
   - Pfad im Container: `/app/data`
6. „Speichern" klicken
7. Für andere zu mountende Verzeichnisse die obigen Schritte wiederholen

### 6.3 Hinweise

- Nach dem Mounten werden die Daten persistent gespeichert und gehen durch einen Container-Neustart nicht verloren
- Es wird empfohlen, mindestens das Verzeichnis `/app/data` zu mounten, um die Datenbank zu sichern

## 7. Health-Check

Das System verfügt über einen eingebauten Health-Check-Mechanismus. Standardmäßig wird geprüft:

- WebUI-Modus: Endpunkt `http://localhost:8000/health` prüfen
- FastAPI-Modus: Endpunkt `http://localhost:8000/api/health` prüfen
- Nicht-Servicemodus: immer Gesundheitsstatus zurückgeben

Die Health-Check-Konfiguration lautet:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || curl -f http://localhost:8000/health \
    || python -c "import sys; sys.exit(0)"
```

## 8. Häufige Probleme

### 8.1 Der API-Dienst ist nicht erreichbar

- Prüfen, ob der Startbefehl den Parameter `--serve` oder `--serve-only` enthält
- Prüfen, ob auf dem Tab „Zugriff" eine Domain konfiguriert wurde
- Firewall-Einstellungen prüfen

### 8.2 Der Bot antwortet nicht

- Prüfen, ob das Discord-Bot-Token korrekt ist
- Prüfen, ob der Bot zum Server hinzugefügt wurde
- Prüfen, ob die Bot-Berechtigungen ausreichen
- Logdateien auf Fehlermeldungen prüfen

### 8.3 Analyse-Tasks werden nicht ausgeführt

- Prüfen, ob die Konfiguration der geplanten Tasks korrekt ist
- Prüfen, ob die API-Schlüssel gültig sind
- Logdateien auf Fehlermeldungen prüfen

### 8.4 Datenverlust

- Sicherstellen, dass das Verzeichnis `/app/data` gemountet ist
- Prüfen, ob die Speichervolumen-Konfiguration korrekt ist

## 9. Erweiterte Konfiguration

### 9.1 Multi-Instanz-Bereitstellung

Sie können mehrere Instanzen auf Zeabur bereitstellen, um verschiedene Funktionen abzudecken:

1. Eine Instanz für den API-Dienst (`python main.py --serve-only`)
2. Eine Instanz für geplante Tasks (`python main.py --schedule`)
3. Eine Instanz für den Bot (`python main.py --discord-bot`)

Stellen Sie sicher, dass sie dasselbe `/app/data`-Speichervolumen teilen, um die Datenbank gemeinsam zu nutzen.

### 9.2 Benutzerdefinierte Domain

Auf dem Tab „Zugriff" in der Zeabur-Konsole können Sie:

1. Die automatisch erzeugte Domain verwenden
2. Eine benutzerdefinierte Domain binden
3. HTTPS konfigurieren

## 10. Deployment aktualisieren

### 10.1 Automatisches Update

Wenn Sie neuen Code in das Repository pushen:

1. GitHub Actions baut automatisch ein neues Image
2. Zeabur erkennt das neue Image
3. Sie können „Automatisches Deployment" wählen oder das Deployment manuell auslösen

### 10.2 Manuelles Update

1. In der Zeabur-Konsole zur Dienstseite gehen
2. „Deployment-Verlauf" klicken
3. „Erneut bereitstellen" wählen
4. Oder „Image aktualisieren" klicken

## 11. Monitoring und Logs

### 11.1 Logs ansehen

In der Zeabur-Konsole zur Dienstseite gehen und den Tab „Logs" klicken, um Echtzeit- und historische Logs einzusehen.

### 11.2 Monitoring-Metriken

Zeabur bietet grundlegende Monitoring-Metriken:

- CPU-Auslastung
- Speicherauslastung
- Netzwerkverkehr
- Festplattenauslastung

Auf dem Tab „Monitoring" werden die detaillierten Metriken angezeigt.

## 12. Fehlerbehebung

### 12.1 Detaillierte Logs ansehen

```bash
# In den Container wechseln
zeabur exec <服务名> bash

# Logdateien ansehen
cat /app/logs/stock_analysis_20260125.log
```

### 12.2 Konfiguration prüfen

```bash
# In den Container wechseln
zeabur exec <服务名> bash

# Umgebungsvariablen prüfen
printenv | grep -i discord
printenv | grep -i webui
```

### 12.3 Verbindung testen

```bash
# Netzwerkverbindung testen
zeabur exec <服务名> curl -I https://api.discord.com

# API-Verbindung testen
zeabur exec <服务名> python -c "import requests; print(requests.get('https://api.discord.com').status_code)"
```

## 13. Best Practices

1. **Persistenten Speicher verwenden**: Immer das Verzeichnis `/app/data` mounten, um die Datenbank zu sichern
2. **Sinnvolle Health-Checks konfigurieren**: Die Health-Check-Parameter an die tatsächliche Situation anpassen
3. **Umgebungsvariablen für sensible Informationen verwenden**: API-Schlüssel nicht fest im Code verdrahten
4. **Daten regelmäßig sichern**: Regelmäßig den Inhalt des Verzeichnisses `/app/data` für ein Backup herunterladen
5. **Passenden Startmodus verwenden**: Den passenden Startbefehl je nach Bedarf wählen
6. **Dienststatus überwachen**: Regelmäßig Dienststatus und Logs prüfen
7. **Speicher nach Last konfigurieren**: Für vollständige Analysen werden `1G` als Einstieg empfohlen; bei `512M`-Umgebungen `MAX_WORKERS=1` setzen, bei hoher Last `2G+` verwenden

## 14. Kontakt

Bei Fragen wenden Sie sich gerne an die Projekt-Wartenden oder stellen Sie eine Frage in den GitHub Issues.
