# Leitfaden zur Integration des openclaw-Skill

Dieses Dokument erklärt, wie über einen [openclaw](https://github.com/openclaw/openclaw)-Skill die REST-API von daily_stock_analysis aufgerufen wird, um im openclaw-Dialog eine Aktienanalyse auszulösen.

## Überblick

- **Integrationsweise**: Der openclaw-Skill ruft die daily_stock_analysis (DSA) REST API über HTTP auf
- **Anwendungsszenario**: Der DSA-API-Dienst ist bereits bereitgestellt, und man möchte im openclaw-Dialog eine Analyse auslösen (z. B. „Analysiere mir Maotai“ / „analyze AAPL“)

## Voraussetzungen

1. **daily_stock_analysis muss bereits laufen**: `python main.py --serve-only` ausführen oder über Docker bereitstellen, damit die API dauerhaft verfügbar ist
2. **openclaw benötigt HTTP-Aufruffähigkeit**: z. B. curl über `system.run` ausführen oder ein eingebautes HTTP-Tool (z. B. api-tester usw.)
3. **Hinweis**: GitHub Actions dient nur geplanten Aufgaben und stellt die API nicht dauerhaft bereit; DSA muss lokal oder per Docker laufen

## Zentrale API-Referenz

| Schnittstelle | Methode | Zweck |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | Analyse auslösen (Hauptzugang) |
| `/api/v1/analysis/status/{task_id}` | GET | Status asynchroner Aufgaben |
| `/api/v1/agent/chat` | POST | Agent-Strategieaktienabfrage (erfordert `AGENT_MODE=true`) |
| `/api/health` | GET | Health-Check |

### Anfragetext zum Auslösen einer Analyse

```json
{
  "stock_code": "600519",
  "report_type": "detailed",
  "force_refresh": true,
  "async_mode": false
}
```

- `stock_code`: Aktiencode (erforderlich)
- `report_type`: `simple` | `detailed` | `brief`
- `force_refresh`: boolescher Wert, ob eine erzwungene Aktualisierung erfolgen soll (Cache ignorieren)
- `async_mode`: boolescher Wert; bei `false` synchrone Rückgabe, bei `true` Rückgabe von 202 + `task_id`, das gepollt werden muss

**Hinweis**: `force_refresh` und `async_mode` sind vom Typ Boolean, keine Strings.

### Response-Beispiel (Synchronmodus)

```json
{
  "query_id": "abc123def456",
  "stock_code": "600519",
  "stock_name": "Moutai (Kweichow Moutai)",
  "report": {
    "summary": {
      "analysis_summary": "...",
      "operation_advice": "Halten",
      "action": "hold",
      "action_label": "Halten",
      "trend_prediction": "bullish",
      "sentiment_score": 75
    },
    "strategy": {
      "ideal_buy": "1850",
      "stop_loss": "1780",
      "take_profit": "1950"
    }
  },
  "created_at": "2026-03-13T10:00:00"
}
```

## Wichtige Einschränkungen und Hinweise

- **Nur Aktiencodes werden unterstützt**: Die API akzeptiert keine chinesischen Namen (z. B. „Maotai“); der Skill muss diese auflösen oder den Benutzer auffordern, einen Code anzugeben (z. B. 600519, AAPL)
- **Zeitbedarf im Synchronmodus**: Bei `async_mode: false` dauert eine einzelne Analyse etwa 2–5 Minuten; es muss sichergestellt sein, dass das Timeout von openclaw oder des HTTP-Clients ausreicht
- **Asynchronmodus**: `async_mode: true` gibt 202 + `task_id` zurück; `GET /api/v1/analysis/status/{task_id}` muss gepollt werden, bis `status: completed` erreicht ist

## Format der Aktiencodes

| Typ | Format | Beispiel |
|------|------|------|
| A-Aktien | 6-stellige Zahl | `600519`, `000001`, `300750` |
| Beijinger Börse | 6-stellig, beginnend mit 8/4/92, unterstützt `BJ`-Präfix oder `.BJ`-Suffix | `920748`, `BJ920493`, `920493.BJ` |
| Hongkong-Aktien | hk + 5-stellige Zahl | `hk00700`, `hk09988` |
| US-Aktien | 1-5 Buchstaben (optional .X-Suffix) | `AAPL`, `TSLA`, `BRK.B` |
| US-Aktienindizes | SPX/DJI/IXIC usw. | `SPX`, `DJI`, `NASDAQ`, `VIX` |

## Konfiguration

In `~/.openclaw/openclaw.json` konfigurieren:

```json
{
  "skills": {
    "entries": {
      "daily-stock-analysis": {
        "enabled": true,
        "env": {
          "DSA_BASE_URL": "http://localhost:8000"
        }
      }
    }
  }
}
```

- Lokale Bereitstellung: `http://localhost:8000` oder `http://127.0.0.1:8000`
- Remote-Bereitstellung: Durch die tatsächliche URL ersetzen
- **Empfehlung**: `DSA_BASE_URL` nicht mit `/` enden lassen

## Fehlerresponse-Format

| Statuscode | error-Feld | Erläuterung |
|--------|-------------|------|
| 400 | `validation_error` | Parameterfehler (z. B. fehlendes stock_code) |
| 409 | `duplicate_task` | Diese Aktie wird gerade analysiert; wiederholte Einreichung wird abgelehnt |
| 500 | `internal_error` / `analysis_failed` | Im Analyseprozess ist ein Fehler aufgetreten |

## Vollständiges SKILL.md-Beispiel

Den folgenden Inhalt unter `~/.openclaw/skills/daily-stock-analysis/SKILL.md` speichern:

```markdown
---
name: daily-stock-analysis
description: Ruft die daily_stock_analysis-API für die intelligente Aktienanalyse auf. Verwenden, wenn der Benutzer z. B. „Analysiere Maotai", „analyze AAPL" oder „Schau dir 600519 an" fragt. Es werden nur Aktiencodes unterstützt, keine chinesischen Namen.
metadata:
  {"openclaw": {"requires": {"env": ["DSA_BASE_URL"]}, "primaryEnv": "DSA_BASE_URL"}}
---

## Auslösebedingungen

Wenn der Benutzer die Analyse einer Aktie anfordert (z. B. „Analysiere Maotai", „analyze AAPL", „Schau dir 600519 an"), diesen Skill verwenden.

## Arbeitsablauf

1. **Aktiencode extrahieren**: Den Aktiencode aus der Benutzernachricht erkennen (z. B. 600519, AAPL, hk00700). Wenn der Benutzer nur einen chinesischen Namen angibt (z. B. „Maotai"), den Benutzer zur Angabe eines Aktiencodes auffordern oder ein gängiges Mapping verwenden (Maotai→600519).
2. **API aufrufen**: Eine POST-Anfrage an `{DSA_BASE_URL}/api/v1/analysis/analyze` senden, Anfragetext:
   ```json
   {"stock_code": "<extrahierter Code>", "report_type": "detailed", "force_refresh": true, "async_mode": false, "skills": ["bull_trend"]}
   ```
   > `skills` ist ein optionales Array von Strategie-IDs; das historische Feld `strategies` bleibt weiterhin kompatibel, es wird empfohlen, bevorzugt `skills` zu verwenden.
3. **Auf die Antwort warten**: Im Synchronmodus dauert die Analyse etwa 2–5 Minuten; bitte sicherstellen, dass das Timeout des HTTP-Clients ausreicht (empfohlen ≥300 Sekunden).
4. **Ergebnisse auswerten**: `operation_advice`, `trend_prediction` und `analysis_summary` aus `report.summary` der Response sowie `ideal_buy`, `stop_loss` und `take_profit` aus `report.strategy` extrahieren und dem Benutzer in einem kompakten Format präsentieren. Externe Integrationen können weiterhin nur das Freitextfeld `operation_advice` lesen; für eine strukturierte Darstellung können bevorzugt das optionale `action` / `action_label` gelesen werden (acht Zustände: `buy|add|hold|reduce|sell|watch|avoid|alert`). Fehlen Felder in alten Historien, kann auf die Textdarstellung von `operation_advice` zurückgefallen werden; dieser Fallback entspricht jedoch nicht einer stabilen API-action; für die alte Drei-Zustands-Statistik bleibt `decision_type` maßgeblich.
5. **Fehlerbehandlung**:
   - Verbindungsfehler: Hinweis, zu prüfen, ob DSA läuft und ob DSA_BASE_URL korrekt ist
   - 400: Format von stock_code prüfen
   - 409: Diese Aktie wird gerade analysiert; später erneut versuchen oder den Aufgabenstatus abfragen
   - 500: Hinweis, die DSA-Logs zur Fehlersuche anzusehen

## Format der Aktiencodes

- A-Aktien: 6-stellige Zahl (600519, 000001)
- Beijinger Börse: 6-stellig, beginnend mit 8/4/92, unterstützt BJ-Präfix oder .BJ-Suffix (920748, BJ920493, 920493.BJ)
- Hongkong-Aktien: hk + 5-stellige Zahl (hk00700)
- US-Aktien: 1–5 Buchstaben (AAPL, TSLA, BRK.B)
- US-Aktienindizes: SPX, DJI, IXIC usw.
```

## Agent-Strategieaktienabfrage (optional)

Wenn für daily_stock_analysis `AGENT_MODE=true` aktiviert ist, kann die Agent-Strategieaktienabfrage-Schnittstelle aufgerufen werden; sie unterstützt mehrrundige Dialoge und mehrere Strategien (Chan-Theorie, MA-Golden-Cross usw.):

```bash
# {DSA_BASE_URL} durch die tatsächlich konfigurierte API-Adresse ersetzen (z. B. http://localhost:8000)
curl -X POST {DSA_BASE_URL}/api/v1/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Analysiere 600519 mit der Chan-Theorie", "session_id": "optional-session-id"}'
```

Die Response enthält `content` (Analyse-Schlussfolgerung) und `session_id` (für mehrrundige Dialoge).

## Fehlerbehebung

| Erscheinung | Mögliche Ursache | Behandlungsvorschlag |
|------|----------|----------|
| Verbindungsfehler | DSA läuft nicht, falscher Port, Firewall | Bestätigen, dass `python main.py --serve-only` gestartet ist; `DSA_BASE_URL` prüfen |
| 400-Fehler | stock_code falsch formatiert oder fehlt | Code-Format prüfen (siehe Tabelle oben), sicherstellen, dass der Anfragetext `stock_code` enthält |
| 500-Fehler | AI-Konfiguration, Datenquelle, Netzwerkproblem | DSA-Logs ansehen, bestätigen, dass GEMINI_API_KEY usw. konfiguriert ist |
| Agent 400 | Agent-Modus nicht aktiviert | In der `.env` von DSA `AGENT_MODE=true` setzen |
| Analyse-Timeout | Wartezeit im Synchronmodus zu lang | HTTP-Client-Timeout erhöhen oder `async_mode: true` mit Status-Polling verwenden |

## Hinweise zur Authentifizierung

Standardmäßig benötigt die DSA-API keine Authentifizierung. Wenn in der `.env` `ADMIN_AUTH_ENABLED=true` aktiviert ist, muss der Skill beim Aufruf den nach dem Login erhaltenen Cookie mitführen; die genaue Vorgehensweise hängt von den HTTP-Tool-Fähigkeiten von openclaw ab (die aktuelle API unterstützt nur Cookie-Authentifizierung, kein Bearer Token).
