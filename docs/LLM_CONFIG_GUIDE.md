# LLM (Large Model) Konfigurationsleitfaden

Willkommen! Egal ob du ein völliger Neuling im Umgang mit AI bist oder ein erfahrener Profi, der alle APIs beherrscht — dieser Leitfaden hilft dir, das Large Model (LLM) schnell zum Laufen zu bringen.

Dieses Projekt bietet extern eine einheitliche AI-Modell-Anbindung und unterstützt offizielle Haupt-APIs, OpenAI-kompatible Plattformen sowie lokale Modelle. Im Hintergrund wird dies von [LiteLLM](https://docs.litellm.ai/) angetrieben, aber die meisten Nutzer müssen nur den Standardpfad „Anbieter wählen, API-Key eintragen, Hauptmodell/Kanal wählen" verstehen. Um Nutzern in verschiedenen Stadien gerecht zu werden, haben wir eine „Drei-Ebenen-Prioritäts"-Konfiguration entworfen — wähle einfach die Methode, die am besten zu dir passt.

Wenn du gerade einen konkreten Anbieter auswählst, GitHub-Actions-Secrets/Variables konfigurierst, `details.reason`-Fehler untersuchst oder eine Konfiguration zurückrollen möchtest, schau bitte zuerst in den [LLM-Anbieter-Konfigurationsleitfaden](./llm-providers.md). Dieses Dokument pflegt zentral die Provider-Presets, Actions-Variablen-Zuordnung, Laufzeit-Fähigkeitserkennungsgrenzen und Empfehlungen zur Fehlerbehandlung.

> Die provider/model/Base-URL-Erläuterungen auf dieser Seite fügen dieses Mal keine neuen externen Kompatibilitätssemantiken hinzu; sie dienen nur zur Synchronisierung der laufenden Konventionen. Die tatsächliche Kompatibilitätsbeurteilung folgt weiterhin den im aktuellen Repository gesperrten Abhängigkeiten und der Laufzeitimplementierung:
> - Abhängigkeitsgrenze: `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (konsistent mit `requirements.txt`).
> - Kompatibilitäts-Verifikationseintritt: `tests/test_system_config_service.py`, `tests/test_system_config_api.py` sowie die bestehenden Frontend-Regressionsfälle der Modellkonfigurationsseite.
> - Rückfallpfad: Bevorzugt die `.env`-Konfigurationssicherung + `POST /api/v1/system/config/import` zur Wiederherstellung verwenden; alternativ können vor dem Neustart die alten `LITELLM_MODEL` / `LLM_*` / `AGENT_LITELLM_MODEL` / `VISION_MODEL` / `LLM_TEMPERATURE` / `LLM_USAGE_HMAC_*` manuell nachgefüllt werden.

> **Hinweis**: Die Erläuterungen zu provider/model/base URL auf dieser Seite folgen den aktuellen Abhängigkeitseinschränkungen und historischen Konventionen und sind nur Dokumentationsergänzung; es werden keine neuen Laufzeit-Provider, Modelle oder Base-URL-Verhaltensänderungen eingeführt.

---

## Schnellnavigation: Welchen Abschnitt solltest du lesen?

1. **【Neuling】** "Ich will das System nur schnell zum Laufen bringen, so einfach wie möglich!" -> [Weg zu Methode 1: Extrem einfache Modellkonfiguration](#methode-1-extrem-einfache-modellkonfiguration-für-neulinge)
2. **【Fortgeschritten】** "Ich habe mehrere Keys, möchte Backup-Modelle konfigurieren und eigene URLs (Base URL) ändern." -> [Weg zu Methode 2: Kanal(Channels)-Modus-Konfiguration](#methode-2-kanalchannels-modus-konfiguration-für-fortgeschrittenemehrere-modelle)
3. **【Profi】** "Ich möchte komplexes Load Balancing, Request-Routing und sogar hochverfügbare Multi-Heterogen-Plattformen!" -> [Weg zu Methode 3: YAML-Erweiterte Konfiguration](#methode-3-yaml-erweiterte-konfiguration-für-profis)
4. **【Lokales Modell】** "Ich möchte das lokale Ollama-Modell verwenden!" -> [Weg zu Beispiel 4: Verwenden des lokalen Ollama-Modells](#beispiel-4-verwenden-des-lokalen-ollama-modells)
5. **【Bildmodell】** "Ich möchte Aktiencodes per Bilderkennung erfassen!" -> [Weg zu Erweiterte Funktion: Bildmodell (Vision)-Konfiguration](#erweiterte-funktion-bildmodell-vision-konfiguration)

---

## Generation Backend (Phase 4)

Das Generation-Backend ist die äußere Laufzeitwahl für normale Analysen, den Marktrückblick und `generate_text()`. Standard bleibt `litellm`; der Null-Konfigurationspfad und das historische Verhalten bleiben unverändert. `codex_cli` / `claude_code_cli` / `opencode_cli` sind explizit opt-in lokale CLI-Backends und derzeit als **experimental/limited** markiert.

```env
GENERATION_BACKEND=litellm
GENERATION_FALLBACK_BACKEND=litellm
GENERATION_BACKEND_TIMEOUT_SECONDS=300
GENERATION_BACKEND_MAX_OUTPUT_BYTES=1048576
GENERATION_BACKEND_MAX_CONCURRENCY=1
LOCAL_CLI_BACKEND_MAX_CONCURRENCY=1
# Optional: Bei leer lassen wird das Standardmodell der lokalen OpenCode-Instanz verwendet; bei Konfiguration wird es als --model-Override an OpenCode übergeben.
# OPENCODE_CLI_MODEL=provider/model
AGENT_BACKEND=auto
AGENT_GENERATION_BACKEND=auto
```

- `GENERATION_BACKEND=litellm|codex_cli|claude_code_cli|opencode_cli`. Lokale CLI-Backends sind Generation-Backends, keine LiteLLM-Provider; schreibe nicht `LITELLM_MODEL=codex_cli/...`, `LITELLM_MODEL=claude_code_cli/...` oder `LITELLM_MODEL=opencode_cli/...`.
- Bei `GENERATION_BACKEND=opencode_cli` wird standardmäßig kein `--model` übergeben; die lokale OpenCode-Instanz verwendet ihre eigene Standardmodell-Konfiguration. `OPENCODE_CLI_MODEL` ist nur ein optionaler Override-Wert und wird bei Konfiguration als einzelner `--model`-Parameter an OpenCode übergeben. Provider-Authentifizierung, Konto und Modellverfügbarkeit werden von der lokalen OpenCode-Instanz selbst verwaltet; DSA übernimmt diese Konfigurationen nicht.
- `GENERATION_FALLBACK_BACKEND` ist standardmäßig `litellm`, wenn nicht konfiguriert; ein expliziter leerer Wert `GENERATION_FALLBACK_BACKEND=` in der lokalen `.env` deaktiviert das Backend-Level-Fallback; wenn primary und fallback gleich sind, wird dies als no-op aufgelöst. Wenn der mitgelieferte GitHub-Actions-Workflow diese Variable nicht konfiguriert, exportiert er explizit `litellm`; um das Backend-Fallback in Actions zu deaktivieren, setze das Fallback auf das primary backend, z. B. `GENERATION_BACKEND=codex_cli` + `GENERATION_FALLBACK_BACKEND=codex_cli`.
- Bei `GENERATION_BACKEND=codex_cli|claude_code_cli` ohne Gemini/OpenAI/Anthropic/DeepSeek-API-Key versuchen normale Analysen und der Marktrückblick weiterhin das lokale CLI-Backend; wenn die entsprechende executable nicht existiert, wird ein strukturiertes `command_not_found` zurückgegeben, nicht „API Key nicht konfiguriert".
- Das aktuelle `codex_cli`-Preset verwendet `codex --ask-for-approval never exec --sandbox read-only --output-last-message <temp-file> -`: Normale Analysen sind unbemannte Generation-Aufgaben; festes `never` verhindert, dass nicht-interaktive Ausführungen bei manuellen Genehmigungsanfragen hängen bleiben, während `read-only` weiterhin eine Nur-Lese-Grenze sicherstellt. DSA liest die endgültige Antwort aus der temporären Datei; die gleichzeitig an stdout gedruckten Duplikatinhalte von Codex CLI werden aus der Diagnosevorschau und der Ausgabegrößenstatistik ausgeschlossen und nehmen nicht an der Hauptanalyse-JSON-Parsing teil. Offizielle Referenzen: [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive) und [Codex CLI command line options](https://developers.openai.com/codex/cli/reference). Dieses Repository hat real `codex-cli 0.144.3` verifiziert und deklariert keine breitere Mindestversion; wenn die CLI-Version die Preset-Parameter nicht unterstützt, gibt DSA strukturierte `capability_unsupported` / `cli_contract_unsupported`-Diagnosen zurück und fällt bei konfiguriertem Backend-Fallback auf `litellm` zurück.
- Das aktuelle `claude_code_cli`-Preset verwendet `claude --safe-mode --tools "" --disallowedTools "mcp__*" --strict-mcp-config --no-session-persistence --output-format json -p <static instruction>`, das vollständige DSA-Prompt wird über stdin übergeben. DSA extrahiert Text nur aus den finalen `result/success`-Feldern des Claude-JSON-Envelopes; wenn später `--json-schema` aktiviert wird, muss der Schema-Modus `structured_output` extrahieren und läuft weiterhin durch die bestehenden DSA-Validatoren: JSON-Validator, minimal parser contract, `_parse_response()`, integrity retry, placeholder fill und usage telemetry. Parameterreferenz: [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference); die in diesem PR smoke-verifizierte Version ist `claude 2.1.177 (Claude Code)`, es wird keine breitere Mindestversion deklariert.
- Das aktuelle `opencode_cli`-Preset verwendet `opencode --pure run --format json [--model <OPENCODE_CLI_MODEL>] <static instruction> --file <temp prompt file>`; `--model` wird nur bei expliziter Konfiguration von `OPENCODE_CLI_MODEL` angehängt. Das vollständige DSA-Prompt wird in eine zugriffsgeschützte temporäre Datei geschrieben und gelangt nicht in argv. DSA parst nur den `text`-Inhalt ohne Tool-Events aus dem OpenCode-JSON-Event-Output und verlangt ein normales `step_finish`; Ereignisse wie `tool_use`, `error`, `question`, `permission` führen zu strukturierten Fehlern. Parameterreferenz: [OpenCode CLI reference](https://opencode.ai/docs/cli), Projektkonfigurations-Zusammenführungssemantik: [OpenCode config reference](https://opencode.ai/docs/config); die in diesem PR smoke-verifizierte Version ist `opencode 1.17.11`, es wird keine breitere Mindestversion deklariert.
- Lokale CLI-Backends unterstützen kein Streaming. Bei angefordertem Stream wird automatisch auf non-stream heruntergestuft; dadurch wird kein `capability_unsupported` zurückgegeben.
- Lokale CLI-Usage ist normalerweise nicht verfügbar; das System schreibt keine fake 0-Token, fake cost oder fake cache-Telemetrie.
- Die lokale CLI-Ausführungsgrenzen sind hart begrenzt: `GENERATION_BACKEND_TIMEOUT_SECONDS` maximal `3600`, `GENERATION_BACKEND_MAX_OUTPUT_BYTES` maximal `33554432`, `GENERATION_BACKEND_MAX_CONCURRENCY` maximal `16`, `LOCAL_CLI_BACKEND_MAX_CONCURRENCY` maximal `4`. Wenn die Summe aus diagnostischem stdout/stderr und finaler Antwort das Ausgabelimit überschreitet, wird ein strukturiertes `output_too_large` zurückgegeben; beim `--output-last-message`-Preset wird die in stdout mehrfach gedruckte finale Antwort nicht doppelt gezählt und nicht als `stdout_preview` freigegeben.
- `stdout_preview` / `stderr_preview` der lokalen CLI werden vor dem Schreiben strukturierter Diagnostics von kurzen Credential-Zuweisungen desensibilisiert, unabhängig von der Wertlänge: Großbuchstaben-Umgebungsvariablen-Zuweisungen folgen der fail-closed-Sensitivnamen-Entscheidung des Child-Env; skalare Zuweisungen in JSON, YAML und normalen Logs verwenden eine engere Credential-Feld-Allowlist; URLs verwenden weiterhin unabhängige Regeln für userinfo / webhook / sensitive Parameter. Gewöhnliche Troubleshooting-Felder wie `token_budget`, `session_id`, `sort_key` werden nicht allein wegen der Teilstrings `token`, `session` oder `key` gelöscht; unquotierte sensitive YAML-Skalare haben jedoch keine zuverlässige Zeilengrenze, daher wird ab diesem Wert bis zum Zeilenende fail-closed desensibilisiert, und nachfolgende Felder in derselben Zeile werden ebenfalls nicht erhalten.
- Die Standard-Nebenläufigkeit lokaler CLIs ist 1; die effektive Nebenläufigkeit ist `min(LOCAL_CLI_BACKEND_MAX_CONCURRENCY, GENERATION_BACKEND_MAX_CONCURRENCY)` und erbt nicht `MAX_WORKERS`.
- `AGENT_GENERATION_BACKEND=auto` erbt die local-CLI-Werte von `GENERATION_BACKEND` nicht; Agent-Tool-Aufrufe verwenden weiterhin LiteLLM. Die Web-Einstellungsseite legt nur `auto|litellm` offen; das manuelle Schreiben von `AGENT_GENERATION_BACKEND=codex_cli|claude_code_cli|opencode_cli` implementiert keinen text-only Agent-Modus und gibt eine eindeutige unsupported-tool-calling-Diagnose zurück.
- Die DSA-Tool-Oberfläche aus Phase 6a bleibt die einzige Toolschema-, Berechtigungsmetadaten-, Scope-Guard-, strukturierte Fehler- und Audit-/Desensibilisierungsgrenze; der Codex-AgentBackend aus Phase 6 kann Tools nur über diese Tool-Oberfläche ausführen. `codex_cli` / `claude_code_cli` / `opencode_cli` bleiben generation-only und können nicht als Agent-Tool-Fallback verwendet werden.
- Die Schnellprüfung des Generation-Backends auf der Web-Einstellungsseite liest nur die gespeicherte `.env`, Laufzeit-Fallback-Werte und ungespeicherte Entwürfe; sie schreibt keine Konfiguration, lädt die Laufzeit nicht neu und initiiert keine echten Modellanfragen. `available` bedeutet nur, dass die aktuelle Konfiguration die Bedingungen für einen Versuch erfüllt. Der JSON-Smoke-Test ist eine separate explizite Operation, die einen echten Generation-Backend-Request mit einem serverseitig festen JSON-Prompt und -Schema initiiert, um Extractor, JSON-Kontrakt, Timeout, Ausgabelimits und usage-unavailable-Semantik zu verifizieren.
- `GET /api/v1/system/config/generation-backends/status` liest nur die gespeicherte Konfiguration; ungespeicherte Entwürfe erfordern `POST /api/v1/system/config/generation-backends/status/preview` oder `POST /api/v1/system/config/generation-backends/smoke-test`. Maskierte Schlüsselfelder verwenden weiterhin die gespeicherten Werte. `health_status` und `last_error_code/message` repräsentieren nur das Ergebnis der aktuellen Berechnung, keinen historisch persistenten Health-Status.

### Codex Local Agent (Phase 6 Experimental Prototyp)

`AGENT_BACKEND` bestimmt nur die Ausführung der bestehenden Ask-Stock-Chats und beeinflusst weder normale Berichte, geplante Analysen, Marktrückblick, die normale Agent-Analyse-Pipeline, den LiteLLM-Multi-Agent noch Deep Research:

```env
# auto (empfohlen) aktiviert das experimentelle Codex nicht automatisch; auto und litellm behalten den ursprünglichen Standardmodellpfad bei.
AGENT_BACKEND=auto
# Bei expliziter Aktivierung:
# AGENT_BACKEND=codex_app_server
# AGENT_ARCH=single
```

Web-Aktivierungsschritte: Öffne „Einstellungen → Agent-Einstellungen → Ask-Stock-Generierungsmethode", wähle „Codex Local Agent (Experimentell)", bestätige die Architektur als „Einzelner Agent" und setze das Gesamtzeitlimit des Agents auf einen Wert größer als 0 und speichere. Die Einstellungsseite prüft nur, ob die aktuelle Konfiguration, der lokale Codex-Befehl und das benötigte App-Server-Protokoll einen Versuch zulassen; sie loggt sich nicht ein, ruft keine Modelle auf und liest keine Aktiendaten. Nach dem Speichern kannst du direkt zur Ask-Stock-Seite zurückkehren und eine Frage stellen; die erste Frage ist die erste reale Ausführung. Um das ursprüngliche Verhalten wiederherzustellen, wähle „Automatisch (empfohlen)" und speichere.

- Codex muss auf dem Gerät installiert und eingeloggt sein, **auf dem das DSA-Backend läuft**; DSA liest oder speichert keine Codex-Anmeldedaten, der App-Server-Prozess verwendet den eigenen Login-Status von Codex. Docker, Remote-Server und Desktop haben voneinander unabhängige PATHs / Login-Status. Wenn der Desktop aus Finder/Dock gestartet wird, erbt das Backend nur den von der Desktop-App konstruierten echten PATH; wenn der Statusbericht Codex nicht findet, installiere die Codex-CLI an einer im Backend-PATH sichtbaren Position und starte DSA vollständig neu; verifiziere nicht nur in einem anderen Terminalfenster.
- Der Codex-App-Server-Agent aus Phase 6 unterstützt derzeit macOS, Linux und Umgebungen, in denen das DSA-Backend vollständig in WSL läuft; ein natives Windows-Backend wird vor der Statusprüfung und dem Transportstart klar abgelehnt. Diese Einschränkung betrifft nicht die bestehende Windows-Generierungsfähigkeit von `GENERATION_BACKEND=codex_cli` aus Phase 2.
- Codex bietet derzeit nur schreibgeschützte Abfragen für den gespeicherten Analysekontext, die globale Backtest-Zusammenfassung und die Strategie-Backtest-Zusammenfassung. Diese Phase verifiziert und verspricht nur die unabhängigen Prozess-, Stop-, Timeout- und Reclaim-Schleifen dieser drei Tools; Echtzeitkurse, Nachrichten, Markt-Hotspots, Neuberechnung technischer Indikatoren, Detail-Backtests einzelner Aktien und Positionstools sind in dieser Phase nicht enthalten und erscheinen daher nicht in der Tool-Liste von Codex. Wenn du diese Fähigkeiten benötigst, wähle in der Web-Oberfläche „Standardmodell". Ein expliziter Aktiencode oder die in der Web-Oberfläche ausgewählte einzige Aktie legt nur für die freigegebenen historischen Analysekontext-Tools einen Aktienbereich fest; bei Namensmehrdeutigkeiten wird nicht geraten.
- Diese Fähigkeit ist kein Offline-Modell. Aktiencodes, Fragen, Nachrichten, Positionskontext und desensibilisierte Tool-Ergebnisse können von den von Codex selbst konfigurierten Diensten verarbeitet werden.
- Derzeit wird nur Single-Agent-Chat unterstützt; Codex Multi Agent und Codex Deep Research werden nicht unterstützt. Die bestehenden LiteLLM-Multi-Agent- und Deep-Research-Funktionen sind davon nicht betroffen.
- Jeder Chat erstellt einen neuen ephemeren App-Server-Thread; DSA speichert weiterhin den ursprünglichen sichtbaren Sitzungsverlauf und injiziert ihn in der nächsten Runde, injiziert jedoch keinen LiteLLM-Provider-Trace. Der Web-Client erhält keine Chain-of-Thought, rohes JSON-RPC, stderr oder vollständige Tool-Parameter/Ergebnisse; Codex empfängt nur die desensibilisierten Tool-Ergebnisse, die für die Vervollständigung der aktuellen Analyse erforderlich sind.
- Wenn der Benutzer die Ask-Stock-Funktion stoppt, zeigt die Seite zuerst „Wird gestoppt". DSA unterbricht die Codex-Runde und beendet und recycelt die in dieser Runde unabhängig laufenden Tool-Prozesse; erst nach Bestätigung, dass sowohl Codex als auch die Tool-Prozesse beendet wurden, gibt die ursprüngliche Ask-Stock-Anfrage das finale „Gestoppt" zurück. Timeout und Client-Verbindungsabbruch folgen derselben Bereinigungsgrenze und kündigen keine vorzeitige Beendigung an, solange noch Aufgaben dieser Runde im Hintergrund laufen. Dieser Vertrag gilt nur für Codex und ändert nicht die Ausführungsweise des Standard-LiteLLM-Agents.
- Codex muss ein `AGENT_ORCHESTRATOR_TIMEOUT_S` größer als 0 verwenden, um sicherzustellen, dass Erfolg, Fehler, Timeout oder Stop innerhalb einer klaren Zeitspanne enden; die alte Semantik von `0` (Zeitlimit deaktivieren) bleibt nur dem Standard-LiteLLM-Pfad vorbehalten. Bei der Auswahl von Codex wird vor dem Speichern und Ausführen klar abgelehnt, nicht stillschweigend durch 600 Sekunden ersetzt.
- Die Schnellstatusprüfung prüft nur Konfiguration, executable, Version und die App-Server-Schemafähigkeiten, von denen der Produktionspfad tatsächlich abhängt; sie sendet keine Modell-Anfragen und beweist auch nicht, dass Codex eingeloggt ist, das Modell verfügbar ist oder der echte Tool-Kreislauf funktioniert. Der Status drückt nur „kann es versuchen" aus; echte Befehls-, Protokoll-, Login-, Modell- und Tool-Fehler werden beim Senden einer Frage durch den Benutzer in der ursprünglichen Kategorie zurückgegeben. Der Chat wird bei jedem Laden einmal geprüft; nach einem Fehler muss der Benutzer manuell erneut prüfen, kein automatischer Retry.
- Der formelle Chat wählt das tatsächliche Backend serverseitig. Erst nachdem der Server die Kontextvorbereitung abgeschlossen und die Benutzerfrage gespeichert hat, sendet SSE das einzige `accepted`-Ereignis und startet dann die Modellausführung. Die Web-Oberfläche behält vor `accepted` Eingabe, Aktienbereich, Nachfragekontext und Fähigkeitsauswahl bei; daher erzeugen Umgebungs- oder Speicherfehler keine Geister-Nachrichten auf der Seite. Das in `accepted` zurückgegebene tatsächliche Backend bestimmt die Art des Stopps.
- Jede Ask-Stock-Runde teilt ein Gesamtressourcenbudget der gesamten Runde: Die kumulierte Ausgabe und Ereignisanzahl des App-Servers ist begrenzt, die Gesamtzahl der Tool-Aufrufe folgt dem bestehenden `AGENT_MAX_STEPS`, und der Zustand dieser Runde wird nach Abschluss sofort aufgeräumt. Tool-Prozesse werden nach den ursprünglichen UTF-8-Ergebnis-Bytes gemessen und melden gültige Ergebnisse nicht wegen JSON-Escaping fälschlich als Handler-Absturz; bei Überschreitung wird ein eindeutiger Fehler zurückgegeben und die Prozesse dieser Runde werden recycelt, ohne Retry oder Backend-Wechsel.
- Aktuell wird gemäß der [Codex App Server v2 Dokumentation](https://developers.openai.com/codex/app-server/) JSONL stdio, ephemeres `thread/start`, `turn/start` / `turn/interrupt` und experimentelle dynamische Tools verwendet. Die lokale Akzeptanzversion vom 2026-07-15 ist `codex-cli 0.144.3`; dieses Projekt rät daraus nicht auf eine allgemeine Mindestversion. Die Kompatibilitätsprüfung der Einstellungsseite entscheidet nur, ob ein Versuch erlaubt ist; die endgültige Verfügbarkeit richtet sich nach dem realen Ausführungsergebnis der Benutzerfrage.

### Datenschutz und Grenzen des lokalen CLI-Backends

- Das lokale CLI-Backend ist kein Offline-Modell; die Dienste hinter Codex / Claude Code / OpenCode können Aktiencodes, Nachrichten, Positionskontext, Analyse-Prompts, Berichtsentwürfe usw. verarbeiten.
- Docker, Cloud-Server und CI besitzen nicht automatisch deinen lokalen CLI-Login-Status.
- GitHub Actions gibt nur Konfigurationswerte weiter und installiert oder loggt keine lokalen CLIs ein; wenn du das lokale CLI-Backend in Actions opt-in aktivierst und auf dem Runner die executable oder der Login-Status fehlt, solltest du einen strukturierten Fehler sehen.
- DSA liest keine Codex/Claude/OpenCode-Credential-Dateien, aber Subprozesse können den eigenen Login-Status der CLI lesen.
- Beim Start des Desktops über Finder/Dock auf macOS wird der shell PATH nicht geerbt; das gepackte Desktop-Paket ergänzt beim Starten des Backends gängige Homebrew-Pfade (z. B. `/opt/homebrew/bin`, `/usr/local/bin`). Wenn die Einstellungsprüfung weiterhin die CLI-executable nicht findet, beende und öffne DSA vollständig neu; das Öffnen des CLI-Interaktionsfensters ändert den PATH des bereits laufenden Backends nicht.
- DSA erbt standardmäßig nur eine minimale Laufzeitumgebung und lehnt die Wildcard-Vererbung von `CLAUDE_*`, `ANTHROPIC_*`, `OPENCODE_*`, `OPENAI_*`, `GOOGLE_*`, `GEMINI_*`, `AWS_*`, `AZURE_*`, `VERTEX_*`, `*_API_KEY`, `*_AUTH_TOKEN`, `*_ACCESS_TOKEN`, `*_SECRET`, `*_PASSWORD` ab, um das Risiko von Lecks bei DSA-API-Keys, Provider-Tokens und Webhook-Tokens zu verringern. `CODEX_HOME` ist eine präzise Ausnahme zur Kompatibilität mit dem bestehenden Codex-CLI-Login-Verzeichnis; die `CODEX_CLI_*`-Wildcard wird nicht wiederhergestellt.
- `opencode_cli` schreibt eine minimale Projekt-`opencode.json` in ein temporäres cwd, um Teilen, automatische Updates, Snapshots und häufige Tool-Berechtigungen zu deaktivieren; die aufgelöste OpenCode-Konfiguration kann jedoch weiterhin die lokale globale Konfiguration des Benutzers enthalten. Die Laufzeitsicherheitsgrenze hängt gleichzeitig von `--pure`, der env-Denylist, den Prompt-Datei-Berechtigungen und dem fail-closed Event-Extractor ab.
- Die Web-Einstellungsseite legt nur sichere Presets offen und erlaubt keine beliebigen command / argv / shell-Strings.
- `codex_cli` / `claude_code_cli` / `opencode_cli` bleiben als experimental/limited markiert; wenn deine CLI-Version den im Repository verifizierten nicht-interaktiven Ausgabevertrag nicht unterstützt, gibt DSA strukturierte `capability_unsupported`, `cli_contract_unsupported`, `invalid_json`, `schema_validation_failed` oder entsprechende Backend-Fehler zurück und fällt bei konfiguriertem Backend-Fallback auf `litellm` zurück. Wenn du das Risiko von Versionsdrift nicht akzeptieren kannst, behalte `GENERATION_BACKEND=litellm` bei.
- `opencode_cli` unterstützt kein OpenCode serve / web / ACP / MCP / attach / `--dangerously-skip-permissions`; DSA behandelt OpenCode-Final-Text nicht als Agent-Tool-Erfolg.

## Methode 1: Extrem einfache Modellkonfiguration (für Neulinge)

**Ziel:** Du musst nur den API-Key und den passenden Modellnamen eintragen, um sofort loszulegen. Keine komplizierten Konzepte nötig.

Wenn du nur ein Modell verwenden willst, ist dies der schnellste Weg. Öffne die `.env`-Datei im Projektstammverzeichnis (falls keine vorhanden, kopiere `.env.example` und benenne sie in `.env` um).

### Anspire-Open-Beispiel:

> 💡 **Empfohlen: [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC)**: Bietet eine integrierte Erfahrung aus chinesisch-optimierter Online-Suche und OpenAI-kompatiblem Pfad — ideal für Nutzer, die nur einen Key vorbereiten möchten.
> - Die folgenden Konfigurationsbeispiele dienen der Veranschaulichung; Modell- und Gateway-Verfügbarkeit richten sich nach der Kontoberechtigung und der Anspire-Konsole; Dokumentationsbeispiele ersetzen keine tatsächliche Konnektivitätsverifikation.
> - Empfohlen wird, auf der Web-Einstellungsseite auf „Verbindung testen" zu klicken, um echte Authentifizierung und Modellverfügbarkeit zu prüfen, statt Dokumentstandardwerte als Verfügbarkeitszusagen zu betrachten.

```env
# Anspire Open API Keys (mehrere unterstützt, kommagetrennt)
# Erhalt: https://open.anspire.cn/?share_code=QFBC0FYC
# Wenn die Standard-Prioritätsbedingung erfüllt ist, nutzt das System diesen Key für Suche und LLM (nur Beispiel-Fallback-Pfad).
# Beispielmodell: Doubao-Seed-2.0-lite; Beispiel-Gateway: https://open-gateway.anspire.cn/v6
ANSPIRE_API_KEYS=sk-xxxxxxxxxxxxxxxx
# Optional: Modell oder Gateway je nach Konsolenverfügbarkeit wechseln
# ANSPIRE_LLM_MODEL=Doubao-Seed-2.0-pro
# ANSPIRE_LLM_BASE_URL=https://open-gateway.anspire.ai/v6
```

### Beispiel 1: Verwendung einer allgemeinen Drittanbieter-Plattform (OpenAI-kompatibel, empfohlen)

Die überwiegende Mehrheit der Drittanbieter-Aggregationsplattformen (z. B. SiliconFlow, AIHubmix, Alibaba Bailian, Zhipu usw.) ist mit dem OpenAI-Interface-Format kompatibel. Solange die Plattform einen API-Key und eine Base-URL bereitstellt, kannst du sie nach folgendem Format problemlos konfigurieren:

```env
# Den von der Plattform bereitgestellten API-Key eintragen
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
# Die Interface-Adresse der Plattform eintragen (sehr wichtig: endet in der Regel mit /v1)
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
# Den konkreten Modellnamen auf der Plattform eintragen (sehr wichtig: das Präfix openai/ für die Systemerkennung nicht vergessen)
LITELLM_MODEL=openai/deepseek-ai/DeepSeek-V3 
```

### Beispiel 2: Verwendung des offiziellen DeepSeek-Interfaces
```env
# Den bei der offiziellen DeepSeek-Plattform beantragten API-Key eintragen
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```
*Kompatibilitätshinweis: Wenn nur diese Zeile eingetragen wird, verwendet das System weiterhin standardmäßig `deepseek/deepseek-chat` und weist im Log auf die Migration hin.*
`deepseek-chat` / `deepseek-reasoner` bleiben für die Kompatibilität mit alten Konfigurationen nutzbar, aber DeepSeek hat sie offiziell als nach 2026/07/24 veraltet markiert; für neue Konfigurationen wird empfohlen, über den Web-Schnellkanal oder explizit `LITELLM_MODEL=deepseek/deepseek-v4-flash` auf `deepseek-v4-flash` / `deepseek-v4-pro` zu migrieren.

### Beispiel 3: Verwendung der kostenlosen Gemini-API
```env
# Den erhaltenen Google-Gemini-Key eintragen
GEMINI_API_KEY=AIzac...
```

### Beispiel 4: Verwendung des lokalen Ollama-Modells
```env
# Ollama benötigt keinen API-Key; nach lokalem `ollama serve` sofort nutzbar
OLLAMA_API_BASE=http://localhost:11434
LITELLM_MODEL=ollama/qwen3:8b
```

> **Wichtig**: Ollama muss über `OLLAMA_API_BASE` konfiguriert werden, **nicht** über `OPENAI_BASE_URL`; sonst fügt das System die URL falsch zusammen (z. B. 404, `api/generate/api/show`). Bei Remote-Ollama setze `OLLAMA_API_BASE` auf die tatsächliche Adresse (z. B. `http://192.168.1.100:11434`). Die aktuellen Abhängigkeitseinschränkungen sind `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (konsistent mit requirements.txt).

> **Glückwunsch! Neulinge können ab hier das Programm ausführen!**
> Du willst testen, ob es funktioniert? Gib im Hauptverzeichnis in der Befehlszeile ein: `python scripts/check_env.py --llm`

---

## Methode 2: Kanal(Channels)-Modus-Konfiguration (für Fortgeschrittene/mehrere Modelle)

**Ziel:** Ich habe Keys von mehreren verschiedenen Plattformen und möchte sie gemischt verwenden. Wenn das Hauptmodell hängt oder das Netzwerk ausfällt, soll automatisch auf ein Backup-Modell umgeschaltet werden.

**Die Webseite kann direkt konfigurieren:** Nach dem Start kannst du in **Web UI → „Systemeinstellungen -> AI-Modell -> AI-Modell-Anbindung"** sehr anschaulich visuell konfigurieren!

> **Ergänzung zur neuen Editor-Umgebung**: Für DeepSeek, Alibaba Bailian (DashScope) sowie andere OpenAI-kompatible `/v1/models`-Kanäle unterstützt die Einstellungsseite jetzt direkt „Modelle abrufen", lädt die verfügbaren Modelle von `{base_url}/models` und lässt Mehrfachauswahl zu; im Hintergrund wird weiterhin das ursprüngliche Kommaformat `LLM_{CHANNEL}_MODELS=model1,model2` gespeichert. Wenn der Kanal dieses Interface nicht unterstützt, die Authentifizierung fehlschlägt oder derzeit nicht erreichbar ist, kann die Modellliste weiterhin manuell ausgefüllt werden, ohne das Speichern zu beeinträchtigen.

### Status der Erstkonfiguration

Das Backend bietet einen schreibgeschützten Status-Endpunkt `GET /api/v1/system/config/setup/status`, um zu prüfen, ob die grundlegendsten Konfigurationstypen im Erststart-Kreislauf bereits bereit sind: LLM-Hauptkanal, Agent-Kanal, Watchlist, Benachrichtigungskanäle und lokaler Speicher. Dieser Endpunkt liest nur die gespeicherte `.env` und die Umgebungsvariablen des aktuellen Prozesses; er lädt die Laufzeitkonfiguration nicht neu, schreibt nicht in `.env`, testet keine echten Modelle und erstellt keine Datenbankdateien; der Frontend-Assistent und spätere Smoke-Runs können schrittweise auf diesem Endpunkt aufbauen.

### Kompatibilitäts- / Migrations- / Rollback-Regeln des Web-Kanal-Editors

- Die provider / Base-URL / Beispielmodelle in den Presets dienen nur der **Formularinitialisierung**; beim tatsächlichen Speichern werden die aktuell eingegebenen `LLM_{CHANNEL}_PROTOCOL`, `LLM_{CHANNEL}_BASE_URL`, `LLM_{CHANNEL}_MODELS`, `LLM_{CHANNEL}_API_KEY(S)` geschrieben, ohne im Hintergrund heimlich auf andere Providernamen oder URLs zu ändern.
- „Modelle abrufen" auf der Einstellungsseite ruft `{base_url}/models` nur für `OpenAI Compatible` / `DeepSeek`-Kanäle auf; „Verbindung testen" initiiert standardmäßig eine minimale Chat-Anfrage nur für das erste Element der Modellliste und zeigt das backend-normalisierte `resolved_model` im Ergebnis an. Wenn `details.reason=model_access_denied` zurückgegeben wird (z. B. das in Issue #1208 beobachtete SiliconFlow / OpenAI Compatible, das über LiteLLM `Model disabled` zurückgibt), behandle es als best-effort-Modellverfügbarkeits-Diagnose auf Basis des Providertexts; prüfe zuerst, ob das Modell unter dem aktuellen Konto/Key freigeschaltet ist, passe ggf. die Modellreihenfolge an oder entferne nicht verfügbare Modelle und versuche erneut; nicht abgedeckte oder semantisch abweichende Providertexte laufen weiter in die Fallback-Diagnose. Die optionale „Laufzeit-Fähigkeitsprüfung" wird nur nach expliziter Auswahl durch den Benutzer ausgelöst und initiiert zusätzliche JSON-/Tools-/Stream-/Vision-Smoke-Anfragen; die Ergebnisse repräsentieren nur eine best-effort-Prüfung für das aktuelle Konto, Modell und den Endpunkt. Die von der obigen Prüfung zurückgegebenen `stage / error_code / details / latency_ms / capability_results` dienen nur strukturierten Diagnosehinweisen, werden **nicht** in `.env` zurückgeschrieben und verhindern auch kein Speichern.
- Wenn `details.reason=provider_blocked` zurückgegeben wird, hat der Anbieter oder das Transit-Gateway diese Anfrage eindeutig blockiert; dies unterscheidet sich von lokalen Netzwerk-/TLS-Anomalien und `model_access_denied`; prüfe zuerst Kontorrisiko-Kontrolle, Region oder Anfragequellenbeschränkungen, Modellberechtigungen, Agent-Gateway-Richtlinien und Content-Security-Richtlinien.
- Die Laufzeit-Fähigkeitsprüfung erzeugt echte LLM-Anfragen und kann Kosten für Token/Bildinput, RPM/TPM-Limits, unzureichendes Guthaben oder Timeouts verursachen. Ein fehlgeschlagener Test kann aus Kontoberechtigung, nicht freigeschaltetem Modell, Endpunktregion, Guthaben, Kompatibilitätsschicht des Anbieters oder der LiteLLM-Konvertierungspfad stammen und bedeutet nicht, dass der Provider die entsprechende Fähigkeit global nicht unterstützt. P3 hat nicht alle realen Provider online smoke-getestet; die Kompatibilitätsgrundlage stammt aus der LiteLLM-`completion()` / OpenAI-I/O-Format / Streaming / Exception-Mapping unter den aktuellen Abhängigkeitseinschränkungen `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` sowie den JSON-Mode-, Tool-Calling-, Streaming- und Vision-Input-Formen der OpenAI Chat Completions.
- Zugehörige externe Quellen: LiteLLM Python SDK / OpenAI-I/O-Format / Streaming / Exception-Mapping: <https://docs.litellm.ai/>; LiteLLM OpenAI-kompatibles Routing: <https://docs.litellm.ai/docs/providers/openai_compatible>; OpenAI Chat Completions: <https://platform.openai.com/docs/api-reference/chat/create>; JSON mode: <https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat>; tool calling: <https://platform.openai.com/docs/guides/function-calling?api-mode=chat>; streaming: <https://platform.openai.com/docs/guides/streaming-responses?api-mode=chat>; vision input: <https://platform.openai.com/docs/guides/images-vision?api-mode=chat>.
- Beim Speichern eines Kanals wird nur der in dieser Übermittlung abgegebene Key aktualisiert; die gesamte alte Konfiguration wird durch einen Kanalmodus-Wechsel nicht stillschweigend migriert. Einzig synchron **bereinigt** werden Laufzeitmodell-Referenzen: Wenn `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL` oder `LITELLM_FALLBACK_MODELS` auf Modelle zeigen, die in den aktuell aktivierten Kanälen nicht mehr existieren, werden diese ungültigen Referenzen vor dem Speichern auf der Einstellungsseite geleert/entfernt, damit die Laufzeit nicht weiter auf ungültige Modelle zeigt; selbst wenn die aktuell aktivierten Kanäle keine wählbaren Modelle haben, werden alte Werte von verwalteten Providern bereinigt, denen der legacy Key fehlt. Direktverbindungsmodelle wie `cohere/*`, `google/*`, `xai/*` dienen nur der Erläuterung der historischen `direct-env`-Kompatibilitäts-Erhaltungssemantik und sind keine Verfügbarkeitszusagen; ob sie verfügbar sind, ist anhand der offiziellen Modell-/API-Dokumente der jeweiligen Hersteller zu verifizieren.
- Backend-Konsistenzgrundlage: Der Konfigurationsvalidierungspfad in `SystemConfigService._validate_llm_runtime_selection` (`src/services/system_config_service.py`) bestimmt die Laufzeitquelle über `_uses_direct_env_provider` (`src/config.py`); derzeit sind nur `gemini`, `vertex_ai`, `anthropic`, `openai`, `deepseek` verwaltete Key-Provider; `cohere`, `google`, `xai` stehen nicht auf dieser Whitelist und bleiben daher Direktverbindungsmodelle.
- Der Rollback-Weg bleibt ebenfalls minimal: Setze die Modellliste des betreffenden Kanals zurück und wähle Hauptmodell / Fallback erneut, oder stelle die früheren `LLM_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `LLM_TEMPERATURE`, `LLM_USAGE_HMAC_*` über den Desktop-Export-Backup / manuelles `.env` wieder her; kein zusätzliches Migrationsskript nötig. Für die Web-Wiederherstellung kann nach Aktivierung der Administrator-Authentifizierung (`ADMIN_AUTH_ENABLED=true`) auch `POST /api/v1/system/config/import` zum Rollback verwendet werden.
- Die Abhängigkeitseinschränkung dieses Repositories für diesen Pfad ist `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (siehe `requirements.txt`); die Regressionsabdeckung umfasst `tests/test_system_config_service.py`, `tests/test_system_config_api.py` und `apps/dsa-web/src/components/settings/__tests__/LLMChannelEditor.test.tsx`.

> **Hinweis zu externen Provider-Beispielmodellen**: Provider-Präfixwerte wie `cohere/*`, `google/*`, `xai/*` dienen nur der Erläuterung der aktuellen Speicherbereinigungssemantik und **stellen keine Modell-für-Modell-Verfügbarkeitszusicherung innerhalb dieser Abhängigkeitseinschränkung dar**. Konkrete Modellnamen in Dokumenten oder Tests sind Stichproben für das Konfigurations-Erhaltungsverhalten, keine Produktionsempfehlungen; die tatsächliche Verfügbarkeit richtet sich nach den offiziellen Modelldokumenten des jeweiligen Anbieters und ist mit der Repository-Abhängigkeitseinschränkung `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` abzugleichen.

### Rollback- und Kompatibilitätsnachweise

- Abhängigkeitseinschränkung und Umfang der stillen Bereinigung: Unter `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` bereinigt das Speichern nur ungültige Laufzeitmodell-Referenzen (`LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `LITELLM_FALLBACK_MODELS`); Nicht-Kanal-Direktverbindungsmodelle wie `cohere/*`, `google/*`, `xai/*` werden beibehalten.
- Rollback-Weg: Nach Desktop-Export eines Backups kann die Wiederherstellung über `POST /api/v1/system/config/import` erfolgen; alternativ die historischen `LITELLM_* / AGENT_LITELLM_MODEL / VISION_MODEL / LLM_TEMPERATURE / LLM_USAGE_HMAC_*` manuell in `.env` nachfüllen und nach Neustart wirksam werden. Vor der Web-Importierung die Administrator-Authentifizierung aktivieren (`ADMIN_AUTH_ENABLED=true`).
- Rollback-Regressionsnachweis: `tests/test_system_config_service.py::test_import_desktop_env_restores_runtime_models_after_cleanup` deckt „Laufzeitreferenzen nach Bereinigung mit Desktop-Export-Backup wiederherstellen" ab.
- Direktverbindungs-Provider-Regressionsnachweise: `tests/test_system_config_service.py::SystemConfigServiceTestCase::test_validate_accepts_minimax_model_as_direct_env_provider`, `test_validate_accepts_cohere_model_as_direct_env_provider`, `test_validate_accepts_google_model_as_direct_env_provider`, `test_validate_accepts_xai_model_as_direct_env_provider` decken die Erhaltungssemantik der Direktverbindungs-Provider ab.
- Frontend-Regressionsbefehl: `cd apps/dsa-web && npm run lint && npm run build && npm run test -- src/components/settings/__tests__/LLMChannelEditor.test.tsx`.
- Empfohlene Rollback-Operationskette (inkl. Einstellungsseiten-Aktualisierung): Zuerst Desktop-Backup exportieren, `POST /api/v1/system/config/import` ausführen, dann über `GET /api/v1/system/config` die Seitenkonfiguration aktualisieren und bestätigen, dass `LITELLM_MODEL / AGENT_LITELLM_MODEL / VISION_MODEL / LLM_TEMPERATURE / LLM_USAGE_HMAC_*` mit der Modellliste übereinstimmen, bevor du fortfährst.

### Häufige offizielle Dokumentquellen (zum Abgleichen von Preset-Provider / Base URL / Modellnamen)

- OpenAI Compatible Spezifikation (LiteLLM): <https://docs.litellm.ai/docs/providers/openai_compatible>
- OpenAI offiziell: <https://platform.openai.com/docs/api-reference/chat>
- DeepSeek offiziell: <https://api-docs.deepseek.com/>
- Anspire Open: <https://open.anspire.cn/?share_code=QFBC0FYC>
- Alibaba Bailian DashScope Kompatibilitätsmodus: <https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- Moonshot / Kimi offiziell: <https://platform.moonshot.ai/docs/guide/compatibility>
- Anthropic offiziell: <https://docs.anthropic.com/en/api/messages>
- Gemini offiziell: <https://ai.google.dev/gemini-api/docs/openai>
- Cohere offiziell: <https://docs.cohere.com/>
- Cohere API-Referenz: <https://docs.cohere.com/reference/>
- Cohere LiteLLM Provider: <https://docs.litellm.ai/docs/providers/cohere>
- Google Gemini API und Modelle: <https://ai.google.dev/gemini-api/docs/openai>, <https://ai.google.dev/gemini-api/docs/models>
- Google LiteLLM Provider: <https://docs.litellm.ai/docs/providers/gemini>
- xAI offiziell: <https://docs.x.ai/docs>
- xAI LiteLLM Provider: <https://docs.litellm.ai/docs/providers/xai>
- Ollama offiziell: <https://github.com/ollama/ollama/blob/main/docs/api.md>

Wenn die Web-Version nicht praktisch ist, ist die Konfiguration in der `.env`-Datei ebenfalls sehr geschmeidig; sie ermöglicht die gleichzeitige Verwaltung mehrerer Drittanbieter-Plattformen. Die Regeln lauten:

1. **Zuerst deklarieren, wie viele Kanäle du hast**: `LLM_CHANNELS=Kanalname1,Kanalname2`
2. **Für jeden Kanal die Konfiguration separat ausfüllen** (beachte: alles GROSSSCHREIBEN): `LLM_{Kanalname}_XXX`

### Beispiel: Gleichzeitige Konfiguration von DeepSeek und einer Aggregationsplattform mit Backup-Umschaltung
```env
# 1. Kanalmodus aktivieren, hier zwei Kanäle deklarieren: deepseek und aihubmix
LLM_CHANNELS=deepseek,aihubmix

# 2. Kanal eins: DeepSeek offiziell konfigurieren
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_DEEPSEEK_API_KEY=sk-1111111111111
LLM_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro

# 3. Kanal zwei: Eine gängige Aggregations-Transit-API konfigurieren
LLM_AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1
LLM_AIHUBMIX_API_KEY=sk-2222222222222
LLM_AIHUBMIX_MODELS=gpt-5.5,claude-sonnet-4-6

# 4. 【Entscheidend】Hauptmodell und Backup-Modellliste festlegen
# Normalerweise wird bevorzugt dieses deepseek-Modell verwendet:
LITELLM_MODEL=deepseek/deepseek-v4-flash
# Optional: Agent-Ask-Stock separat ein Hauptmodell zuweisen (leer = erbt das Hauptmodell)
AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro
# Wenn das Hauptmodell ausfällt, werden sofort nacheinander diese beiden Backup-Modelle versucht:
LITELLM_FALLBACK_MODELS=openai/gpt-5.4-mini,anthropic/claude-sonnet-4-6
```

### Beispiel: Ollama-Kanalmodus (lokales Modell, kein API-Key nötig)
```env
# 1. Kanalmodus aktivieren, ollama-Kanal deklarieren
LLM_CHANNELS=ollama

# 2. Ollama-Adresse konfigurieren (lokal standardmäßig Port 11434)
LLM_OLLAMA_BASE_URL=http://localhost:11434
LLM_OLLAMA_MODELS=qwen3:8b,llama3.2

# 3. Hauptmodell festlegen
LITELLM_MODEL=ollama/qwen3:8b
```

### Beispiel: Hermes lokale HTTP-Generation (Phase 3)
```env
LLM_CHANNELS=hermes
LLM_HERMES_PROTOCOL=openai
LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1
LLM_HERMES_API_KEY=sk-local-hermes
LLM_HERMES_MODELS=hermes-agent
LITELLM_MODEL=openai/hermes-agent
```

Hermes ist ein reservierter Kanalname und unterstützt nur lokale Loopback-`/v1`-OpenAI-kompatible Generation. Phase 3 verifiziert nur normale Analysen und JSON-Ausgaben; Stream/SSE, Tools, Vision, Agent-Tools, Remote-Hermes und Prozesslebenszyklusverwaltung werden nicht unterstützt. Der Hermes-API-Key kann nur mit einem einzelnen `LLM_HERMES_API_KEY` verwendet werden; konfiguriere nicht `LLM_HERMES_API_KEYS` oder `LLM_HERMES_EXTRA_HEADERS`. Wenn die Hermes-Konfiguration ungültig ist, verhindert das System ein stillschweigendes Legacy-Provider-Fallback, um eine fälschliche Verwendung externer Modelle zu vermeiden. Beim Speichern des reservierten Hermes-Kanals in der Web-Einstellungsseite werden alte `LLM_HERMES_API_KEYS` / `LLM_HERMES_EXTRA_HEADERS` explizit geleert und eine Warnung zurückgegeben; zur Wiederherstellung alter Werte diese manuell aus der `.env`-Sicherung, der Git-Historie oder dem Desktop-Export-Backup wiederherstellen, aber Phase 3 lehnt weiterhin nicht-leere Multi-Key-/Extra-Headers-Konfigurationen ab.

### Hinweise zum Ausfüllen von MiniMax-Kanalmodellen

- Wenn du MiniMax über einen OpenAI-kompatiblen Kanal anbindest, fülle im Kanalmodell direkt `minimax/<Modellname>` ein, z. B. `minimax/MiniMax-M1`.
- Die Dropdowns für Hauptmodell, Agent-Hauptmodell, Fallback und Vision auf der Web-Einstellungsseite behalten diesen Wert unverändert bei und schreiben ihn nicht mehr fälschlich in `openai/minimax/<Modellname>` um.

### Kompatibilitätshinweis für Standardmodell-Ask-Stock / LiteLLM-Konfiguration

- Bei `AGENT_BACKEND=auto|litellm` verwendet der Ask-Stock-Agent dieselbe Drei-Ebenen-Priorität wie normale Analysen: `LITELLM_CONFIG` (LiteLLM-YAML) > `LLM_CHANNELS` > legacy-Provider-Keys. Solange eine obere Konfiguration wirksam ist, nimmt die untere Konfiguration nicht mehr an dieser Anfrage teil; Codex verwendet dieses Modell-Routing nicht.
- Im YAML-Modus nutzt der Agent direkt die LiteLLM-`model_list` / `model_name`-Routingsemantik; im Kanalmodus wird bevorzugt `AGENT_LITELLM_MODEL` gelesen, bei leer übernimmt es `LITELLM_MODEL` und fällt dann nach `LITELLM_FALLBACK_MODELS` weiter zurück.
- Wenn du YAML / Channels nicht aktiviert hast und `AGENT_LITELLM_MODEL` ebenfalls leer ist, aber lokal weiterhin legacy-Umgebungsvariablen vorhanden sind, erbt der Ask-Stock-Agent weiterhin die alte Konfiguration: `GEMINI_API_KEY + GEMINI_MODEL` -> `gemini/<model>`, `OPENAI_API_KEY + OPENAI_MODEL` -> `openai/<model>`, `ANTHROPIC_API_KEY + ANTHROPIC_MODEL` -> `anthropic/<model>`.
- Diese Kompatibilitätslogik erweitert nur „bei Fehlern die echte Backend-Fehlerursache beibehalten" und „bei nicht konfiguriertem LLM eine spezifischere Diagnose geben" und **löscht, leert, migriert oder schreibt** deine bestehenden `GEMINI_*` / `OPENAI_*` / `ANTHROPIC_*` / `LITELLM_*`-Konfigurationen **nicht** stillschweigend um.
- Wenn die aktuelle Umgebung keine gültige Agent-Modellkette hat, gibt die Ask-Stock-Seite weiterhin nach Fehlersemantik zurück und zeigt direkt die echte Backend-Konfigurationsdiagnose; sobald eine gültige Modellquelle ergänzt ist, ist die Funktion wiederhergestellt, ohne ein zusätzliches Konfigurationsmigrationsskript auszuführen.
- Die empfohlene neue Konfigurationsweise bleibt das explizite Setzen von `LITELLM_MODEL` / `AGENT_LITELLM_MODEL` oder die Verwendung von `LLM_CHANNELS`; legacy-Provider-Keys bleiben derzeit als Kompatibilitäts-Rollback-Pfad erhalten, damit alte `.env`, lokale macOS-Entwicklungsumgebungen und historische Deployments reibungslos weiterlaufen.

### Komprimierung des sichtbaren Ask-Stock-Konversationskontexts

Standardmäßig injiziert die Ask-Stock-Funktion weiterhin nur die letzten 20 sichtbaren Unterhaltungen gemäß historischem Verhalten. Die folgende LLM-Komprimierung gilt nur für Ask-Stock mit „Standardmodell": Der Codex-Agent verwendet immer die letzten 20 benutzersichtbaren Unterhaltungen und ruft `AGENT_LITELLM_MODEL` nicht auf, um eine Verlaufssummary zu erzeugen. Ein Wechsel zu Codex löscht die gespeicherte Komprimierungskonfiguration nicht; nach dem Wechsel zurück zu „Standardmodell" wirkt sie weiter. Um bei langen Sitzungen des Standardmodells Token zu sparen, kann Folgendes aktiviert werden:

```env
AGENT_CONTEXT_COMPRESSION_ENABLED=true
AGENT_CONTEXT_COMPRESSION_PROFILE=balanced
# Bei leer folgt dem profile preset
AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS=
AGENT_CONTEXT_PROTECTED_TURNS=
```

Die Komprimierung verarbeitet nur die unter `session_id` sichtbaren `user` / `assistant`-Textverläufe, nicht provider traces, thinking blocks, tool calls oder tool results, und ändert auch nicht die Durchleitung von Tool-Aufrufen derselben Runde. Die drei Presets sind `cost` (6000 tokens / 2 geschützte Runden), `balanced` (12000 / 4) und `long_context_raw_first` (24000 / 6); wenn trigger / protected leer sind, folgen sie dem aktuellen profile, bei expliziter Angabe überschreiben sie das profile.

Der Single-Agent-Pfad der Ask-Stock-Funktion pflegt zusätzlich einen provider-aware Trace-Split für die Cross-Round-Protokollwiedergabe von DeepSeek-V4-Thinking + Tool-Calls: Nur wenn in derselben Runde gleichzeitig `tool_calls` und `reasoning_content` auftreten, werden die letzten 3 minimalen Protokollmaterialien unter `session_id + provider + model` gespeichert und in der nächsten Runde in der ursprünglichen Reihenfolge vor die entsprechende sichtbare assistant-Antwort zurückinjiziert. Dieser Trace kann nur unverändert erhalten oder vollständig verworfen werden; er nimmt nicht an Summarys teil, wird nicht in Web-Sitzungsnachrichten geschrieben und fügt keine `.env`-Konfiguration hinzu; bei nicht übereinstimmendem model/provider, durch Summary überdecktem Anker oder unzureichendem Budget wird er vollständig übersprungen. Claude extended thinking deckt in dieser Runde nur adapter/storage-Level-opaque `thinking` / `redacted_thinking` / `signature`-Block-Plumbing und Offline-Fixtures ab; es wird keine Produktions-End-to-End-Unterstützung deklariert; die Multi-Agent-Trace-Injektion bleibt Follow-up. Externe Protokollreferenzen umfassen die DeepSeek-Thinking-Mode-Dokumentation (<https://api-docs.deepseek.com/guides/thinking_mode>) und die Anthropic-Claude-extended-thinking-Dokumentation (<https://platform.claude.com/docs/en/docs/build-with-claude/extended-thinking>); das LiteLLM-Kompatibilitätsfenster richtet sich weiterhin nach `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` in `requirements.txt`.

### Kompatibilitätshinweis für strikte temperature-Modelle

- Moonshot gibt offiziell an, dass die Kimi-API mit dem OpenAI-Interface kompatibel ist und die Base-URL `https://api.moonshot.ai/v1` lautet: <https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart>
- LiteLLM verlangt offiziell, dass OpenAI-kompatible Kanalmodellnamen das Präfix `openai/` verwenden: <https://docs.litellm.ai/docs/providers/openai_compatible>
- Die offizielle Kompatibilitätsdokumentation von Moonshot unterscheidet zwei feste Werte: **thinking-Modus fest `1.0`, non-thinking-Modus fest `0.6`**; andere Werte werden vom Interface abgelehnt: <https://platform.moonshot.ai/docs/guide/compatibility#parameters-differences-in-request-body>
- Im OpenAI-Chat-Completions-Standard ist `temperature` ein optionaler Parameter; für Modelle wie GPT-5 / o-Serie, die nur die Standardtemperature akzeptieren, lässt dieses Projekt `temperature` auf der Anfrageebene weg, damit der Server den Standardwert verwendet, statt dein `LLM_TEMPERATURE` umzuschreiben: <https://platform.openai.com/docs/api-reference/chat/create>
- Die aktuelle Laufzeit-Abhängigkeitseinschränkung des Repositories ist `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (siehe `requirements.txt`); diese Kompatibilitätslogik wurde unter dieser Einschränkung für Hauptanalyse, Marktrückblick, Agent-Direktverbindung zu LiteLLM und den Kanal-Konnektivitätstest der Systemeinstellungsseite regressionsverifiziert.
- Daher normalisiert dieses Projekt `kimi-k2.6` und seine `kimi-k2.6-*`-Varianten vor dem Senden der Anfrage nach **tatsächlichem Anfragemodus**: Der Standard-/Thinking-Pfad verwendet `temperature=1.0`; wenn in deinem LiteLLM-YAML-Routing-Alias explizit `litellm_params.extra_body.thinking.type: disabled` (oder eine äquivalente non-thinking-Konfiguration) geschrieben steht, wird automatisch auf `temperature=0.6` umgeschaltet. Dein gespeichertes `LLM_TEMPERATURE` in `.env` oder den Web-Einstellungen wird nicht umgeschrieben.
- Wenn eine kompatible Plattform für nicht registrierte neue Modelle einen eindeutigen Parameterfehler zurückgibt (z. B. `temperature` nicht unterstützt, nur Standard `1.0` erlaubt, `top_p` nicht unterstützt), korrigiert die Laufzeit die Parameter **für die aktuelle Anfrage** einmal und wiederholt; erst nach erfolgreichem Retry wird diese Strategie prozessintern gecacht. Dieser Cache wird nicht in `.env` zurückgeschrieben; nach einem Dienstneustart wird erneut nach Konfiguration und Anpassungsregeln entschieden.
- Für Streaming-Antworten, die bereits Teile erzeugt haben, wechselt das System die Parameter nicht nach halber Ausgabe; es bleibt beim stabilen Pfad „non-streaming-Retry mit gleichem Modell / Fallback-Modell", um inkonsistente Antworten zu vermeiden.
- `SystemConfigService` aktualisiert beim Speichern in den Web-Einstellungen / Desktop-`.env`-Import nur den von dir übermittelten Key; es leert, migriert oder schreibt das bestehende `LLM_TEMPERATURE` nicht stillschweigend, weil auf ein striktes temperature-Modell umgeschaltet wurde; temporäre Parameterstrategien in Kanal-Testanfragen werden ebenfalls nicht in die Konfigurationsdatei zurückgeschrieben.
- Nicht-strikte Hauptmodelle, nicht-strikte Fallbacks und Anfragen nach dem Zurückschalten auf normale Modelle verwenden weiterhin deine konfigurierte Temperatur; das heißt, alte Konfigurationen müssen nicht migriert werden — ein Modellwechsel stellt das ursprüngliche Verhalten automatisch wieder her.
- Die Kompatibilitäts-Regressionsabdeckung dieses Repositories siehe: `tests/test_llm_channel_config.py`, `tests/test_market_analyzer_generate_text.py`, `tests/test_agent_pipeline.py`, `tests/test_system_config_service.py`.
- Minimale Rollback-Methode: Die diesbezüglichen Änderungen der LLM-Parameter-Anpassung direkt zurückrollen; keine separate Migration des bestehenden `LLM_TEMPERATURE` nötig.

### Kompatibilitäts- und Rollback-Prüfcheckliste (nach PR-Review-Kriterien)

- Laufzeit-Abhängigkeitseinschränkung: `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (konsistent mit `requirements.txt`).
- Regressionsverifikations-Eintritte:
  - Kanalmodell-Erkennung und -Verbindung: `tests/test_llm_channel_config.py`
  - Laufzeitquellen-Bereinigung und -Wiederherstellung (inkl. Desktop-Export-Backup-Kette): `tests/test_system_config_service.py`
  - Interface-Validierung und problemorientierte Felder: `tests/test_system_config_api.py`
  - Einstellungsseiten-Interaktion und Hinweise nach dem Speichern: `apps/dsa-web/src/components/settings/__tests__/LLMChannelEditor.test.tsx`
- Rollback-Pfad für alte Konfigurationen: `Desktop-Export-Backup -> /api/v1/system/config/import` oder manuelle Wiederherstellung von `LLM_* / LITELLM_* / AGENT_LITELLM_MODEL / VISION_MODEL / LLM_TEMPERATURE / LLM_USAGE_HMAC_*`; vor der Web-Importierung eines Backups ist ebenfalls `ADMIN_AUTH_ENABLED=true` erforderlich, sonst wird 403 zurückgegeben.

> **Kritischer Stolperfalle-Hinweis**: Wenn du `LLM_CHANNELS` aktivierst, werden die direkt außerhalb geschriebenen `DEEPSEEK_API_KEY` oder `OPENAI_API_KEY` **vollständig wirkungslos (vom System komplett ignoriert)**! Verwende **nur eines von beiden** — schreibe niemals sowohl den Neulingsmodus als auch den Kanalmodus, sonst kommt es zu Konflikten.
> **Docker-Hinweis**: Wenn du in `docker compose environment:` oder `docker run -e` Variablen wie `LITELLM_MODEL`, `LLM_CHANNELS`, `LLM_DEEPSEEK_MODELS` explizit übergibst, überschreiben diese Umgebungsvariablen nach dem Container-Neustart die von der Web-Einstellungsseite geschriebene `.env`; die Deployment-Konfiguration muss synchron angepasst werden.

### Kompatibilitätsgrundlage und Rollback-Audit-Erläuterung (Erläuterung zur diesbezüglichen PR-Anpassung)

- Offizielle und Laufzeit-Kompatibilitätsgrundlage in zwei Ebenen: Ebene eins ist die offizielle Interface-Semantik (LiteLLM-OpenAI-kompatibles Routing, OpenAI Chat Completions, Moonshot/Kimi-Dokumente und offizielle Modellbeschreibungen); Ebene zwei ist die tatsächliche Fehlerklassifizierung unter der aktuellen Laufzeitsemantik dieses Repositories (`litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`).
- Die diesbezügliche Kompatibilitätswiederherstellung verwendet nur die Strategie „lokale Laufzeitfehlerklassifizierung + Einzelanfragen-Korrektur-Retry + prozessinterner Cache", schreibt nicht in `.env`, führt keine Konfigurationsmigration durch und umgeht auf dem Ausführungspfad dynamisch nicht unterstützte Parameter (`temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`). Zum Rollback ist kein zusätzlicher Migrationsbefehl nötig; die alten Werte wiederherstellen genügt.
- Regression und Nachweise: `tests/test_llm_param_recovery.py`, `tests/test_system_config_service.py`, `tests/test_llm_channel_config.py`, `tests/test_system_config_api.py`, `tests/test_market_analyzer_generate_text.py`, `tests/test_agent_pipeline.py`; für Desktop-Import und Laufzeitbereinigungs-Rollback gibt es zusätzlich die direkte Abdeckung durch `test_import_desktop_env_restores_runtime_models_after_cleanup`.

---

### LLM-usage-HMAC-Telemetrie

Die P0a-Usage-Telemetrie erzeugt für tatsächlich gesendete Messages einen HMAC-SHA256-Fingerprint, um später zu beurteilen, ob dieselben Prompt-/Message-Präfixe stabil sind. Diese Fähigkeit schreibt nur lokale `llm_usage`-Datensätze und ändert weder Prompt, Provider-Parameter, Cache-Hinweise, Modellausgabe noch die Fallback-Reihenfolge.

Die Usage-Quelle wird in drei Ebenen gelesen:

- Bevorzugt werden die öffentlichen Antwortfelder `usage` des Provider / LiteLLM gelesen.
- Danach wird das öffentliche LiteLLM-Antwortfeld `usage_metadata` gelesen.
- Zuletzt wird `_hidden_params["usage"]` gelesen; dies ist ein best-effort-Fallback von LiteLLM private/internal und kein stabiler öffentlicher Vertrag; fehlt es, bedeutet das nur, dass die usage/cache-Telemetrie möglicherweise unvollständig ist, nicht dass die Modellanfrage fehlgeschlagen ist.

Die Cache-Token-Normalisierung führt nur eine allowlistete best-effort-Normalisierung durch. Externe Feldgrundlagen und Laufzeitgrenzen sind wie folgt, um offizielle stabile Verträge, das aktuelle LiteLLM-Normalisierungsverhalten und die Kompatibilitäts-Allowlist dieses Repositories nicht zu vermischen:

| Provider / Quelle | Gelesenes Feld | Grundlage und Grenze | Abdeckung |
| --- | --- | --- | --- |
| OpenAI | `usage.prompt_tokens_details.cached_tokens` | Die offizielle Prompt-Caching-Dokumentation erklärt, dass unter 1024 Tokens ebenfalls `cached_tokens=0` zurückgegeben wird: <https://developers.openai.com/api/docs/guides/prompt-caching> | unit/mock-Abdeckung; dieser PR hat kein OpenAI-live-smoke durchgeführt |
| Anthropic | `cache_creation_input_tokens` / `cache_read_input_tokens` / `input_tokens` | Die offizielle Prompt-Caching-Dokumentation definiert `total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens`: <https://platform.claude.com/docs/en/build-with-claude/prompt-caching> | unit/mock-Abdeckung; dieser PR hat kein Anthropic-live-smoke durchgeführt |
| Gemini / Vertex AI | Offizielles Feld ist `UsageMetadata.cachedContentTokenCount`; die Laufzeit konsumiert die von LiteLLM freigegebenen snake_case-/normalisierten Felder wie `cached_content_token_count`, `cache_read_input_tokens` oder `prompt_tokens_details.cached_tokens` | Offizielle Gemini-`UsageMetadata`-Felder siehe <https://ai.google.dev/api/generate-content#UsageMetadata>; dieses Repository fügt kein natives camelCase-Runtime-Fallback hinzu; die Laufzeitgrenze richtet sich nach `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` | unit/mock-Abdeckung; dieser PR hat kein Gemini-/Vertex-live-smoke durchgeführt |
| DeepSeek | `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` | Die DeepSeek-Chat-Completion-Dokumentation erklärt `prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens`: <https://api-docs.deepseek.com/api/create-chat-completion> | unit/mock-Abdeckung; dieser PR hat nur ein desensibilisiertes DeepSeek-smoke durchgeführt und speichert keine vollständige Antwort |
| GLM / OpenAI-kompatible / StepFun und andere kompatible Plattformen | Werte, die aus der modellierten token/cache-count-Allowlist auf einheitliche Felder abgebildet werden können | Kein offizieller stabiler Cache-Telemetrie-Vertrag deklariert; nur best-effort-Normalisierung unter dem aktuellen LiteLLM-/OpenAI-kompatiblen Shape; nicht modellierte Metadaten werden nicht persistiert | unit/fixture/mock-Abdeckung; dieser PR hat für diese Provider kein live-smoke durchgeführt |
| LiteLLM öffentliche Antwortform | `usage` / `usage_metadata` | Konsumiert nach der Response-/`Usage`-Objekform des aktuellen Abhängigkeitsfensters `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`; keine LiteLLM-2.x-Kompatibilitätszusage | Analyzer / Agent / usage-Tests abgedeckt |
| LiteLLM privater Fallback | `_hidden_params["usage"]` | private/internal best-effort-Fallback, kein stabiler öffentlicher LiteLLM-Vertrag; ergänzt nur in engen Szenarien wie public usage zero-only/no-signal die Streaming-Usage und ändert keine Provider-Anfrageparameter | unit/mock-Abdeckung; bei fehlen betrifft es nur die Telemetrie-Vollständigkeit, nicht einen Modellanfragefehler |

```env
LLM_USAGE_HMAC_SECRET=
LLM_USAGE_HMAC_KEY_VERSION=local-v1
```

- Wenn `LLM_USAGE_HMAC_SECRET` leer ist, generiert das System im Datenverzeichnis `.llm_usage_hmac_secret`, geeignet für lokale Vergleiche bei Single-Deployment.
- Nur wenn HMAC über Deployments hinweg verglichen werden soll, wird explizit dasselbe hoch-entrope Zufallsgeheimnis konfiguriert; empfohlen wird die Generierung mit `openssl rand -hex 32`.
- `.llm_usage_hmac_secret` ist ein lokales Secret-Artefakt und wird in `.gitignore` nach Dateiname ignoriert.
- Beim Rotieren des Secrets muss `LLM_USAGE_HMAC_KEY_VERSION` synchron aktualisiert werden, damit HMACs, die mit verschiedenen Secrets erzeugt wurden, nicht fälschlich verglichen werden.
- Reuse nicht das Login-Session-Secret und committe keine echten Secrets in die Versionskontrolle oder setze sie in Issues, Logs oder Screenshots aus.

### Provider-Prompt-Cache-Konfiguration (P1 / P1.5)

Die Prompt-Cache-Konfiguration steuert nur, ob dieses Projekt Cache-Usage/-Diagnosen aufzeichnet und ob der Hauptanalysepfad aktiv verifizierte provider-spezifische Hinweise sendet; sie steuert nicht das implizite / provider-verwaltete Caching von OpenAI, Gemini, DeepSeek und anderen Providern.

```env
LLM_PROMPT_CACHE_TELEMETRY_ENABLED=true
LLM_PROMPT_CACHE_HINTS_ENABLED=false
LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL=off
```

- Bei `LLM_PROMPT_CACHE_TELEMETRY_ENABLED=false` werden raw-usage-JSON des Providers, normalisierte Cache-Felder und Cache-Entscheidungs-Diagnosen nicht persistiert; die grundlegende Token-Usage-Aufzeichnung bleibt kompatibel.
- `LLM_PROMPT_CACHE_HINTS_ENABLED=true` erlaubt nur dem Hauptanalyse-/Analyzer-LiteLLM-Pfad, an im Registry verifizierte oder smoke-getestete Provider/Routen Hinweise wie `prompt_cache_key`, `cache_control`, `user_id` zu senden. Der Ask-Stock-Agent-Pfad zeichnet derzeit nur Fähigkeits-/Usage-Diagnosen auf und sendet keine provider-spezifischen Hinweise aktiv. Unbekannte OpenAI-kompatible Gateways sind standardmäßig telemetry-only.
- `LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL=basic` bietet nur in Debug-Logs und testbeobachtbaren Objekten nicht-sensitive Enumerationen wie provider, api surface, verification status, hint applied / disabled reason. `debug` bietet im selben Umfang zusätzlich HMAC-abgeleitete route/cache-Diagnosen und matched caps id, verbietet aber weiterhin raw prompt, request body, message content, Aktien-/Benutzeroriginaltext, webhook oder API key; diese Diagnosen sind kein Output der öffentlichen Usage-API oder der normalen Einstellungsseite.
- Die Provider-Cache-Capability-Registry ist eine code-level manuelle Fähigkeitstabelle in `src/llm/provider_cache.py`. Einträge tragen `doc_sources`, `last_verified_at` und `verification_status`; nach dem Hinzufügen neuer Provider oder dem Upgrade von LiteLLM sollten Einträge und Tests synchron aktualisiert werden.
- Prompt-Cache-Key, Route-Key und DeepSeek-Session-Isolation verwenden `LLM_USAGE_HMAC_SECRET` / `.llm_usage_hmac_secret` für domain-separated HMAC; es wird kein Prompt-Cache-spezifisches Secret neu eingeführt.

### Legacy-Message-Stabilitätsaudit (P0.5a)

P0.5a fügt im normalen Einzelaktien-Analysepfad interne Stabilitätsaudit-Felder zu den legacy `[system, user]`-Messages hinzu und schreibt sie weiterhin in lokale `llm_usage`. Es verwendet das oben genannte Message-HMAC, ändert weder Prompt-Inhalt, Message-Reihenfolge, Provider-Anfrageparameter, Cache-Hinweise, Modellausgabe noch Fallback-Reihenfolge und erweitert auch nicht die öffentliche Usage-API oder die Web-Seite.

Neue Felder dienen nur der Wartungsdiagnose:

- `language`, `market_group`, `analysis_mode`, `legacy_prompt_mode`, `provider`, `transport`, `message_count` beschreiben den niederempfindlichen Routingkontext dieses normalen Einzelaktien-Analyseaufrufs.
- `skill_config_hmac` ist ein HMAC-SHA256, der aus den geparsten Skill-Prompt-Fragmenten, der Standard-Skill-Strategie und dem legacy Prompt-Modus erzeugt wird, um zu beurteilen, ob sich die System-Message mit der Skill-Konfiguration ändert; der Skill-Originaltext wird nicht gespeichert.
- `known_dynamic_marker_positions` ist ein JSON-String und zeichnet nur `marker_name`, `message_role`, `char_offset` auf; es werden keine Aktiencodes, Aktiennamen, Daten, Nachrichtentexte, Kursdatenwerte, headers, Antworttexte oder Prompt-Fragmente gespeichert.
- `estimated_total_prompt_tokens`, `approx_common_prefix_chars`, `approx_common_prefix_tokens` werden basierend auf einer stabilen kanonischen Render-Darstellung im Projekt geschätzt: `role + "\n" + content` in Message-Reihenfolge verketten und mit festen Trennzeichen verbinden. Diese Definition beansprucht nicht, den echten Wire-Bytes des Providers zu entsprechen.
- `char_offset` ist die Position des Markers innerhalb des `content` der zugehörigen Message; `approx_common_prefix_chars` ist die Anzahl der Zeichen vom Start der kanonischen Render-Darstellung bis zum ersten bekannten dynamischen Marker. Ohne Marker sind die Common-Prefix-Felder `NULL`.
- Die Token-Schätzung verwendet `ceil(chars / 3)`, dient nur der Diagnose, ersetzt weder die Provider-Usage noch nimmt sie an der Cache-Threshold-Entscheidung teil; bei chinesischen Szenarien kann sie zu niedrig liegen.

P0.5a führt kein PromptBlock-IR, `block_id`, `stability_class`, `static_prefix_hash` oder `dynamic_context_hash` ein. Die Pfade Agent, research und market review sind vorerst nicht an dieses Audit angebunden.

---

## Methode 3: YAML-Erweiterte Konfiguration (für Profis)

**Ziel:** Mir ist die Lernschwelle egal; ich will maximale Kontrolle und mit nativen Regeln unternehmensgerechte Hochverfügbarkeit!

Diese Ebene wird direkt auf die LiteLLM-Routingfähigkeiten der zugrunde liegenden Schicht abgebildet und unterstützt hohe Nebenläufigkeit, automatische Retries, RPM/TPM-Load-Balancing und mehr.

### Konfigurationshinweise für lokale Ausführung / Docker-Bereitstellung

1. In `.env` nur eine Zeile als Verweis auf die Deklaration lassen:
   ```env
   LITELLM_CONFIG=./litellm_config.yaml
   ```
2. Im Projektstammverzeichnis eine `litellm_config.yaml` erstellen (orientiere dich an der mitgelieferten `docs/examples/litellm_config.example.yaml`).

Beispiel `litellm_config.yaml`:
```yaml
model_list:
  - model_name: my-smart-model
    litellm_params:
      model: deepseek/deepseek-v4-flash
      api_base: https://api.deepseek.com
      api_key: "os.environ/MY_CUSTOM_SECRET_KEY"  # Key aus der Umgebungsvariable lesen, sicher gegen Leck

  # Ollama lokales Modell (kein api_key nötig)
  - model_name: ollama/qwen3:8b
    litellm_params:
      model: ollama/qwen3:8b
      api_base: http://localhost:11434
```

### GitHub-Actions-Konfigurationshinweise

1. `Settings` → `Secrets and variables` → `Actions`. Nicht-sensitive Konfigurationen (z. B. Modellnamen, Schalter, Base-URL) können in `Secret` oder `Variables` abgelegt werden; alle Schlüsselfelder wie `*_API_KEY` / `*_API_KEYS` und `LLM_<NAME>_API_KEY` / `LLM_<NAME>_API_KEYS` bitte einheitlich unter dem Tab `Secret` → `New repository secret` ablegen.

2. Gemäß der Tabelle konfigurieren; nur wenn alle Pflichtkonfigurationen korrekt sind, kann der YAML-Erweiterte-Konfigurationsmodus wirksam werden. Die Schreibweise der YAML-Konfigurationsdatei richtet sich nach der mitgelieferten `docs/examples/litellm_config.example.yaml`.

| Secret-Name | Beschreibung | Pflicht |
|------------|------|:----:|
| `LITELLM_CONFIG` | Pfad zur erweiterten Modellrouting-Konfigurationsdatei, in der Regel `./litellm_config.yaml` | Pflicht |
| `LITELLM_MODEL` | Standard-Hauptmodellname oder Routing-Alias | Pflicht |
| `LITELLM_CONFIG_YAML` | Enthält den Inhalt der YAML-Konfigurationsdatei; eine physische Datei im Repository muss nicht eingecheckt werden | Optional |
| `LITELLM_API_KEY` | Zum Speichern des API-Keys, der in der Konfigurationsdatei referenziert werden kann (Umgebungsvariablen-Referenz). Da GitHub Actions die importierte Umgebungsvariable explizit angeben muss, kannst du Umgebungsvariablen nicht frei benennen wie im lokalen Ausführungsmodus | Optional, muss im repository secret konfiguriert werden |
| `ANTHROPIC_API_KEY` | Wenn mehrere API-Keys benötigt werden, kann dieser Variablenname ebenfalls verwendet werden | Optional, muss im repository secret konfiguriert werden |
| `OPENAI_API_KEY` | Wie oben, kann zum Speichern des API-Keys verwendet werden | Optional, muss im repository secret konfiguriert werden |

Der Kanalmodus erfordert kein Hochladen der YAML-Datei. Die mitgelieferte `00-daily-analysis.yml` leitet bereits explizit die folgenden gängigen Felder durch:

- Laufzeitauswahl: `GENERATION_BACKEND`, `GENERATION_FALLBACK_BACKEND`, `GENERATION_BACKEND_TIMEOUT_SECONDS`, `GENERATION_BACKEND_MAX_OUTPUT_BYTES`, `GENERATION_BACKEND_MAX_CONCURRENCY`, `LOCAL_CLI_BACKEND_MAX_CONCURRENCY`, `AGENT_GENERATION_BACKEND`, `LLM_CHANNELS`, `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `VISION_PROVIDER_PRIORITY`, `LLM_TEMPERATURE`, `LLM_USAGE_HMAC_SECRET`, `LLM_USAGE_HMAC_KEY_VERSION`, `LLM_PROMPT_CACHE_TELEMETRY_ENABLED`, `LLM_PROMPT_CACHE_HINTS_ENABLED`, `LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL`
- Mehrere Keys: `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`, `DEEPSEEK_API_KEYS` (der aktuelle Workflow importiert nur aus repository secrets und liest keine gleichnamigen Variables)
- Gängige Kanalnamen: `primary`, `secondary`, `aihubmix`, `deepseek`, `dashscope`, `zhipu`, `moonshot`, `minimax`, `volcengine`, `siliconflow`, `openrouter`, `gemini`, `anthropic`, `openai`, `ollama`

Wenn du z. B. in GitHub Actions `LLM_CHANNELS=primary,deepseek` konfigurierst, müssen synchron `LLM_PRIMARY_*` / `LLM_DEEPSEEK_*` konfiguriert werden. Dabei werden `LLM_<NAME>_API_KEY` / `LLM_<NAME>_API_KEYS` derzeit ebenfalls nur aus repository secrets importiert; wenn du diese Werte in Variables ablegst, greifen sie zur Laufzeit nicht. Bei benutzerdefinierten Kanalnamen (z. B. `my_proxy`) muss GitHub Actions außerdem in der Workflow-`env:` explizit die zugehörige `LLM_MY_PROXY_*`-Abbildung hinzufügen; lokale `.env` und Docker sind von dieser Einschränkung nicht betroffen.


> **Drei-Ebenen-Mutual-Exclusion-Regel**: Die YAML hat die höchste Priorität! Sobald eine YAML konfiguriert ist, werden **Kanalmodus** und **Neulings-Einfachmodus** alle ignoriert. Die Systempriorität lautet: `YAML-Konfiguration > Kanalmodus > Einfaches Einzelmodell`.

---

## Erweiterte Funktion: Bildmodell (Vision)-Konfiguration

Einige spezifische Funktionen im System (z. B. das Hochladen eines Aktiensoftware-Screenshots, damit die AI den Aktiencode aus dem Screenshot extrahiert und in die Watchlist aufnimmt) benötigen zwingend ein Modell mit „visuellen Fähigkeiten". Du musst ihm in `.env` separat ein bildfähiges Modell zuweisen.

```env
# Den für die Bilderkennung speziell verwendeten Modellnamen angeben
VISION_MODEL=openai/gpt-5.5
# Vergiss nicht, den API-KEY des entsprechenden Anbieters einzutragen; für OpenAI-kompatible Kanäle OPENAI_API_KEY angeben:
# OPENAI_API_KEY=xxx
```

**Backup-Bilderkennungsmechanismus:** Um gelegentliche Ausfälle zu verhindern, verfügt das System über eine integrierte Umschaltstrategie. Wenn der Hauptvision-Modellaufruf fehlschlägt, versucht es in der folgenden Reihenfolge, ob es einen Key für ein anderes Bildmodell gibt:
```env
# Standard-Backup-Reihenfolge:
VISION_PROVIDER_PRIORITY=gemini,anthropic,openai
```

---

## Erkennung und Fehlerbehebung (Troubleshooting)

Nach der Konfiguration bist du nervös, ob alles stimmt? Gib in der Befehlszeile (Terminal) den folgenden Code ein, um einen „Arzttermin" zu buchen:

- `python scripts/check_env.py --config` : Reine Prüfung, ob die Logik in der `.env`-Konfigurationsdatei korrekt ist und ob etwas fehlt. (Ergebnis in Sekunden, keine Netzwerkaufrufe, reine lokale Text-/Schreibprüfung)
- `python scripts/check_env.py --llm` : Das System sendet dem Large Model tatsächlich eine Begrüßung, damit du seine Antwort mit eigenen Augen siehst. Damit lässt sich gründlich testen, ob **dein Netzwerk funktioniert und das Konto Guthaben hat**.

### Häufige Stolperfalle-Antwortstation

| Welcher merkwürdige Fehler tritt auf? | Was könnte der Übeltäter sein? | Wie behebt man es? |
|----------------------|----------------------|------------------|
| **Die Oberfläche meldet Hauptmodell nicht konfiguriert** | Das System weiß nicht, welches Modell von welchem Anbieter du verwenden willst | In `.env` eine klare Angabe schreiben: `LITELLM_MODEL=provider/deinModellname`. Z. B. `openai/gpt-5.5` |
| **Ich habe Keys mehrerer Anbieter geschrieben, warum greift hartnäckig nur einer? Und Änderungen wirken nicht?** | Du hast **Einfachmodus** und **Kanalmodus** vermischt! | Entscheide dich für einen einzigen Weg — wenn du Einfachheit willst, lösche alles, was mit `LLM_CHANNELS` beginnt; wenn du reichhaltige Backup-Umschaltung willst, wechsle alles vollständig in die Reihen unter `LLM_CHANNELS`. |
| **Fehlercode 400 oder 401 oder Invalid API Key** | API-Key falsch eingetragen, ein Teil fehlt beim Kopieren, Kontoaufladung noch nicht eingegangen oder Modellname falsch getippt (extrem häufig). | 1. Prüfe, ob vor/nach dem kopierten Key fälschliche Leerzeichen stehen.<br> 2. Prüfe, ob am Ende der Base-URL ein `/v1` fehlt.<br> 3. Prüfe, ob beim Modellnamen ein Präfix wie `openai/` fehlt! |
| **Kimi K2.6 meldet `invalid temperature` (evtl. Hinweis, dass nur `1.0` oder `0.6` erlaubt sind)** | Das Modell verlangt je nach thinking/non-thinking-Modus unterschiedliche feste temperature; alte Konfiguration oder Aufruf-Einstieg kann noch `0.7` übergeben. | Nach dem Upgrade verwendet das System für `kimi-k2.6` Standard-/Thinking-Anfragen automatisch `temperature=1.0`; wenn du in der LiteLLM-YAML-Route thinking explizit deaktivierst, wird automatisch `0.6` verwendet. Der Modellname wird empfohlen als `openai/kimi-k2.6` in Verbindung mit der OpenAI-kompatiblen Base-URL und dem API-Key von Moonshot / Aggregationsplattform. Nicht-Kimi-Fallbacks verwenden weiterhin dein konfiguriertes `LLM_TEMPERATURE`. |
| **GPT-5 / o-Serie meldet `temperature` nicht unterstützt oder nur Standardwert erlaubt** | Diese Modelle akzeptieren nur die serverseitigen Standard-Sampling-Parameter, aber alte Aufruf-Einstiege übergeben explizit `0.7`. | Nach dem Upgrade lässt die Anfrageebene `temperature` weg, sodass der Server den Standardwert verwendet; `.env` / Web-Einstellungen `LLM_TEMPERATURE` wird nicht umgeschrieben, nach dem Zurückschalten auf normale Modelle wird weiterhin der Originalwert gesendet. |
| **Es dreht sich endlos, am Ende Timeout / ConnectionRefused usw.** | 1. Im Inland die ausländischen Originale (wie Google, OpenAI) ohne Proxy verwenden, dadurch blockiert.<br>2. Dein gekaufter Cloud-Server kann keine Auslandsverbindungen herstellen. | **Inländische offizielle** Anbieter (wie DeepSeek, Alibaba) oder **OpenAI-kompatible Aggregations-Transit-Interfaces** werden sehr empfohlen. Denn die Transit-Station löst die Netzwerkprobleme für dich. |
| **Ollama meldet 404, `Could not get model info` oder `api/generate/api/show`** | Ollama fälschlich über `OPENAI_BASE_URL` konfiguriert; das System fügt die URL falsch zusammen | Auf `OLLAMA_API_BASE=http://localhost:11434` oder den Kanalmodus (`LLM_CHANNELS=ollama` + `LLM_OLLAMA_BASE_URL`) umstellen |

*Eine Mahnung für fortgeschrittene Profis: Wenn du den **Agent-Modus (Deep-Thinking-Online-Suche Ask-Stock)** aktivierst, ist hier ein Erfahrungstipp: Bevorzuge ein Large Model mit stärkerer logischer Ableitungsfähigkeit wie `deepseek-v4-pro`. Wenn du zur Kostenersparnis ein kleines Modell für den Agent verwendest, wird seine logische Fähigkeit wahrscheinlich nicht mithalten — nicht nur, dass die Erwartungen nicht erfüllt werden, sondern es werden auch viele leere Abläufe vergeblich durchlaufen.*
