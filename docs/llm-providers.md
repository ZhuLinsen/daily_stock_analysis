# LLM-Anbieter-Konfigurationsleitfaden

Dieses Dokument richtet sich an Nutzer, die zum ersten Mal konfigurieren. Es erklärt, wie die LLM-Konfigurationsweise gewählt wird, wie die Voreinstellungen der Web-Einstellungsseite "AI-Modellkonfiguration" auf `.env` / GitHub Actions abgebildet werden und wie häufige Erkennungsfehler behandelt werden.

> Diese Seite führt keine neuen externen Provider, Modellnamen oder Base-URL-Kompatibilitätsverhalten ein, sondern fasst nur Konfigurationsreferenzen und offizielle Quellen zusammen; die tatsächliche Kompatibilität richtet sich weiterhin nach den aktuellen Laufzeitabhängigkeiten und Testergebnissen des Repositorys.

> - Laufzeitbasis: `requirements.txt` sperrt aktuell `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`; die Kompatibilitätssemantik richtet sich nach der unter dieser Versionsbeschränkung realisierten Implementierung.
> - Verifikationsschleife: Die Regression der Systemkonfigurationskette findet sich in `tests/test_system_config_service.py` und `tests/test_system_config_api.py`; die Interaktionsregression der Konfigurationsseite auf der `Web`-Seite findet sich in den bestehenden Komponententestfällen.
> - Fallback-Pfad: Alte Variablen bleiben ohne automatische Migration erhalten; ein Rollback ist möglich über Web/Desktop-Export einer Sicherung mit anschließendem `POST /api/v1/system/config/import` oder über die manuelle Wiederherstellung der historischen `LLM_*`- / `LITELLM_*`- / `AGENT_*`- / `VISION_MODEL`-Konfiguration.

Tatsächlich verfügbare Modelle, Kontingente, Regionseinschränkungen und Preise richten sich nach den Konsolen der jeweiligen Anbieter; schlägt das Laden der Modellliste fehl, kann der Modellname in der Web-App manuell eingetragen werden. Die von der Web-Einstellungsseite angezeigten Provider-Fähigkeits-Labels, Links zu offiziellen Quellen und Konfigurationshinweise stammen aus statischen Provider-Templates und dienen nur der Konfigurationsreferenz; sie bedeuten nicht, dass die Laufzeitfähigkeit bereits verifiziert wurde.

## Zuerst die Konfigurationsweise wählen

| Weise | Für wen geeignet | Hauptvariablen | Erläuterung |
| --- | --- | --- | --- |
| Minimal-Legacy | Nutzer, die schnell ein einzelnes Modell zum Laufen bringen möchten | `LITELLM_MODEL` + passender Provider-Key | Wenigste Variablen, geeignet für den schnellen lokalen Start; nicht für komplexe Fallbacks. |
| Channels | Nutzer mit mehreren Providern, mehreren Keys oder Fallback | `LLM_CHANNELS` + `LLM_<CHANNEL>_*` | Empfohlener Standardpfad; genau diese Konfigurationsebene speichert auch die Web-Einstellungsseite. |
| YAML | Nutzer, die LiteLLM-Routing, Lastverteilung und Enterprise-Gateways kennen | `LITELLM_CONFIG` / `LITELLM_CONFIG_YAML` | Höchste Priorität; sobald sie gültig wirksam ist, nehmen Channels und Legacy an dieser Anfrage nicht mehr teil. |

Die Priorität bleibt unverändert: `LITELLM_CONFIG` / `LITELLM_CONFIG_YAML` > `LLM_CHANNELS` > Legacy-Provider-Keys. P4 ergänzt nur die Dokumentation, migriert, leert oder überschreibt alte Konfiguration nicht stillschweigend.

Die Generation-Backend-Konfiguration ist ein weiter außen liegender Vertrag der Laufzeitwahl. Phase 4 unterstützt `GENERATION_BACKEND=litellm|codex_cli|claude_code_cli|opencode_cli`, aber ein lokales CLI-Backend ist kein LiteLLM-Provider; konfigurieren Sie es nicht als `LITELLM_MODEL=codex_cli/...`, `LITELLM_MODEL=claude_code_cli/...` oder `LITELLM_MODEL=opencode_cli/...`. Das Preset `codex_cli` verwendet `codex --ask-for-approval never exec --sandbox read-only --output-last-message <temp-file> -`, fixiert die unbemannte Genehmigungsstrategie und hält die Read-only-Grenze; das Preset `claude_code_cli` verwendet `claude --safe-mode --tools "" --disallowedTools "mcp__*" --strict-mcp-config --no-session-persistence --output-format json -p <static instruction>`, der vollständige DSA-Prompt läuft über stdin, und nur aus dem `result/success`-Feld des JSON-Envelopes wird der Endtext extrahiert; die Begründung der Parameter findet sich in der [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference); das Preset `opencode_cli` verwendet `opencode --pure run --format json [--model <OPENCODE_CLI_MODEL>] <static instruction> --file <temp prompt file>`, `--model` wird nur bei expliziter Konfiguration von `OPENCODE_CLI_MODEL` angehängt, der vollständige DSA-Prompt läuft über eine rechtegeschützte temporäre Datei, und nur aus dem JSON-Event-Text ohne Tool-Ereignisse wird der Endtext extrahiert; die Begründung der Parameter findet sich in der [OpenCode CLI reference](https://opencode.ai/docs/cli), die Semantik der Konfigurationszusammenführung in der [OpenCode config reference](https://opencode.ai/docs/config). Diagnose-stdout/stderr unterliegen zusammen mit der finalen Antwort der Gesamtobergrenze `GENERATION_BACKEND_MAX_OUTPUT_BYTES`; bei Überschreitung wird ein strukturiertes `output_too_large` zurückgegeben. Ein leerer Wert von `GENERATION_FALLBACK_BACKEND=` deaktiviert den Backend-Level-Fallback in der lokalen `.env`; ist keine Konfiguration gesetzt, wird standardmäßig auf `litellm` zurückgegriffen; der Standard-GitHub-Actions-Workflow verwendet bei fehlender Konfiguration dieser Variablen explizit `litellm`; zum Deaktivieren des Fallbacks kann das primäre Backend als Self-no-op gesetzt werden. Agent-Tool-Aufrufe verwenden weiterhin LiteLLM; die Web-Einstellungsseite exponiert nur `AGENT_GENERATION_BACKEND=auto|litellm`, handgeschriebenes `codex_cli|claude_code_cli|opencode_cli` aktiviert keinen Text-only-Agent-Modus, sondern liefert nur eine eindeutige unsupported-tool-calling-Diagnose.

Die Status-Schnittstelle und das Web-Panel des Generation-Backends zeigen leichte Checks und Smoke-Tests getrennt an: Der Schnellcheck liest nur die gespeicherte `.env`, die Laufzeit-Fallback-Werte und den aktuellen Entwurf, schreibt keine Konfiguration, lädt die Laufzeit nicht neu und löst keine echten Modellanfragen aus; nur der JSON-Smoke-Test führt mit einem festen JSON-Prompt und Schema echte Anfragen aus. `health_status` und `last_error_code/message` sind Ergebnisse der aktuellen Berechnung und stellen nicht den letzten historischen Fehler dar. `supports_tools=false` eines lokalen CLI-Presets bedeutet nur, dass die DSA-Agent-Toolaufrufkette nicht unterstützt wird, nicht dass normale Texterzeugung unverfügbar ist.

Phase 6a Tool Surface ist die einzige interne Tool-Oberfläche von AgentBackend: einheitliches DSA-Tool-Schema, Public-Descriptor, MCP-kompatibler Descriptor, Scope-Guard, strukturierte Fehler, Audit-Zusammenfassung und maskierte Diagnose. Stock-scoped Tool-Aufrufe müssen explizit `ToolAccessContext.stock_scope` übergeben; Tools, die einen `stock_code`-Parameter haben, aber keinen Stock-Scope deklarieren, schlagen fail-closed fehl. Der Codex-App-Server-Adapter von Phase 6 führt Tools ausschließlich über diese Tool-Oberfläche aus; er behandelt das `codex_cli`-Generation-Backend, den MCP-Server, das SDK oder den Endtext-Fallback nicht als Agent-Tool-Erfolg.

## Grenzen der Codex-App-Server-Fragen-Funktion

`AGENT_BACKEND=codex_app_server` ist eine experimentelle Betriebsart des bestehenden Fragen-Chats, kein neuer Provider-Modellkanal und ändert auch nicht `GENERATION_BACKEND`. In der Web-App muss nach der Auswahl unter "Einstellungen -> Agent-Einstellungen -> Fragen-Erzeugungsart" `AGENT_ARCH=single` und ein Gesamtzeitlimit größer 0 verwendet werden. Die Einstellungsseite prüft nur, ob Konfiguration, Codex-Befehl und das benötigte App-Server-Protokoll einen Versuch erlauben; nach dem Speichern kann der Nutzer direkt Fragen stellen, die erste Frage ist die erste echte Ausführung. `auto` (empfohlen) und `litellm` behalten stets den ursprünglichen LiteLLM-Fragen-Pfad bei.

- DSA verwendet [Codex App Server v2](https://developers.openai.com/codex/app-server/) mit JSONL-stdio, ephemeral thread und experimental dynamic tools und behandelt Chat-Abbrüche über `turn/interrupt`. Die Abnahmeversion vom 2026-07-15 ist `codex-cli 0.144.3`, daraus wird keine harte Mindestversion abgeleitet.
- Codex muss auf dem Gerät installiert und angemeldet sein, das das DSA-Backend ausführt; DSA liest oder speichert keine Codex-Anmeldedaten. PATH und Anmeldestatus von Docker, Remote-Servern und Desktop sind voneinander unabhängig.
- Der Codex-App-Server-Agent von Phase 6 unterstützt aktuell macOS, Linux und vollständig unter WSL laufende DSA-Backends, aber noch kein natives Windows; dies berührt nicht die Windows-Unterstützung des `codex_cli`-GenerationBackend von Phase 2.
- Codex hat aktuell nur Lesezugriff auf gespeicherte Analysekontexte, globale Backtest-Zusammenfassungen und Strategie-Backtest-Zusammenfassungen; in dieser Iteration werden nur der unabhängige Prozess, das Stoppen, das Timeout und der Wiederverwertungs-Kreislauf dieser drei Tools verifiziert. Echtzeit-Kursdaten, Nachrichten, Markt-Hotspots, Neuberechnung technischer Indikatoren, Backtest-Details einzelner Aktien und Positions-Tools sind nicht Teil der Verifikation dieser Iteration und werden daher nicht an Codex exponiert; wer diese Fähigkeiten benötigt, wählt das "Standardmodell". Eindeutige Aktiencodes oder in der Web-App eindeutig zugeordnete Aktien begründen nur für die freigegebenen Tools für historische Analysekontexte einen Aktienbereich; Mehrdeutigkeiten wie gleiche Namen über Märkte hinweg werden nicht erraten.
- Die LLM-Komprimierung des Fragen-Verlaufs gilt nur für das "Standardmodell". Codex verwendet stets die letzten 20 für den Nutzer sichtbaren Unterhaltungen und ruft `AGENT_LITELLM_MODEL` nicht zur Zusammenfassungserzeugung auf; bereits gespeicherte Komprimierungskonfigurationen bleiben erhalten und wirken nach dem Wechsel zurück zum Standardmodell weiter.
- Aktuell wird nur Single-Agent-Chat unterstützt, kein Codex Multi Agent / Codex Deep Research; die bestehenden LiteLLM Multi-Agent- und Deep-Research-Funktionen bleiben unberührt.
- Der cheap-Status löst keine Modellanfragen aus, prüft nur die vom Produktionspfad abhängigen App-Server-Schema-Fähigkeiten und bindet keine willkürliche Mindestversion. `scripts/codex_app_server_gate_a.py` im Repository dient nur der Durchführbarkeitsabnahme durch Maintainer, ist kein Einstellungsseiten-Button oder eine Produktions-API; die erste echte Frage eines normalen Nutzers ist die erste echte Ausführung.
- Wenn der Nutzer die Codex-Fragen-Funktion stoppt, zeigt die Web-App zuerst "Wird gestoppt"; das Backend unterbricht den Codex-Turn und beendet und wiederverwertet die in dieser Runde unabhängig laufenden Tool-Prozesse. Erst wenn sowohl Codex als auch die Tool-Prozesse beendet sind, gibt die ursprüngliche SSE-Anfrage das finale "Gestoppt" zurück. Timeout und Client-Verbindungsabbruch folgen derselben Bereinigungsgrenze und behandeln im Hintergrund noch laufende Aufgaben nicht als bereits beendet. Das Standardverhalten des LiteLLM-Agents bleibt unverändert.
- Der Basisstatus drückt nur "kann es lokal versuchen" aus, prüft weder Login, Modell noch einen echten Tool-Kreislauf und cached auch keine Erfolgsbelege. Der formelle Chat wählt das tatsächliche Backend serverseitig; nach Abschluss der Kontextvorbereitung und des Speicherns der Nutzernachricht wird ein eindeutiges `accepted`-Ereignis ausgegeben, danach startet das Modell. Die Web-App behält vor `accepted` Eingabe, Aktienbereich, Nachfragekontext und Skill-Auswahl bei und entscheidet über `accepted.backend` über die Art des Stoppens. Die kumulierte Ausgabe, Ereignisse und Tool-Aufrufe von Codex unterliegen dem Budget der gesamten Runde; die Anzahl der Tool-Aufrufe übernimmt `AGENT_MAX_STEPS`.
- Codex ist kein Offline-Modell; Aktiencodes, Nachrichten, Positionskontexte und maskierte Tool-Ergebnisse können von den durch Codex selbst konfigurierten Diensten verarbeitet werden.

Die Smoke-Verifikationsversionen dieses PR sind `claude 2.1.177 (Claude Code)` und `opencode 1.17.11`; es wird keine breitere Mindestversion deklariert. Wenn das vom Nutzer installierte CLI diese festen Preset-Parameter oder den nicht-interaktiven Ausgabevertrag nicht unterstützt, gibt DSA ein strukturiertes `capability_unsupported`, `cli_contract_unsupported`, `invalid_json`, `schema_validation_failed` oder den entsprechenden Backend-Fehler zurück und fällt bei konfiguriertem Backend-Fallback auf `litellm` zurück.

Ein lokales CLI-Backend ist kein Offline-Modell. Docker, Cloud-Server und CI besitzen nicht natürlich den lokalen CLI-Anmeldestatus; macOS erbt beim Start des Desktop-Clients über Finder/Dock nicht den Shell-PATH, das gepackte Desktop-CLI ergänzt beim Backend-Start gängige Homebrew-Pfade. Meldet die Einstellungsprüfung weiterhin, dass die CLI ausführbare Datei nicht gefunden wird, muss DSA vollständig beendet und neu geöffnet werden. DSA liest keine Codex/Claude/OpenCode-Credential-Dateien und erzeugt oder transportiert auch keine Provider-API-Keys für OpenCode; Unterprozesse können nach dem eigenen Mechanismus des CLI den lokalen Anmeldestatus oder die Konfiguration verwenden, Aktiencodes, Nachrichten, Positionskontexte, Analyse-Prompts und Berichtsentwürfe können von den Diensten hinter dem jeweiligen CLI verarbeitet werden. DSA erbt standardmäßig nur die minimale Laufzeitumgebung und lehnt die Wildcard-Vererbung von `CLAUDE_*`, `ANTHROPIC_*`, `OPENCODE_*`, Provider-API-Key/token/base-url/model-env und Webhook-Tokens ab, um das Risiko eines Konfigurationslecks aus dem Elternprozess zu senken; `CODEX_HOME` bleibt als Exact-Name-Ausnahme zur Kompatibilität mit dem bestehenden Codex-CLI-Anmeldeverzeichnis erhalten.

`opencode_cli` ist ein experimentelles/eingeschränktes Generation-Backend und unterstützt kein OpenCode serve / web / ACP / MCP / attach / `--dangerously-skip-permissions`. DSA verwendet standardmäßig das Standardmodell des lokalen OpenCode; `OPENCODE_CLI_MODEL` ist nur ein optionaler Modellüberschreibungswert und wird bei Konfiguration an OpenCode `--model` übergeben. DSA schreibt ein minimales Projekt-`opencode.json` in ein temporäres cwd, aber die aufgelöste OpenCode-Config kann weiterhin die globale lokale Nutzerkonfiguration enthalten; die Laufzeit-Sicherheitsgrenze stützt sich zugleich auf `--pure`, die Env-Denylist, die Dateiberechtigungen des Prompts und einen fail-closed Event-Extractor.

## Pfad der Web-Einstellungsseite

Es wird empfohlen, die Channels-Konfiguration bevorzugt über die Web-Einstellungsseite vorzunehmen:

1. Die "AI-Modellkonfiguration" der Einstellungsseite öffnen.
2. Unter "Kanal schnell hinzufügen" eine Anbieter-Voreinstellung wählen.
3. Den API-Key eintragen und bei Bedarf auf "Modelle abrufen" klicken.
4. Hauptmodell, Agent-Hauptmodell, Ersatzmodell und Vision-Modell auswählen und speichern.
5. Auf "Verbindung testen" klicken, um zu bestätigen, dass Authentifizierung, Modellname, Kontingent und Antwortformat normal sind.
6. Sollen JSON-/tools-/stream-/vision-Fähigkeiten bestätigt werden, die "Laufzeitfähigkeits-Erkennung" manuell ankreuzen und dann auslösen; diese Erkennung erzeugt echte LLM-Anfragen, das Ergebnis repräsentiert nur eine best-effort-Erkennung des aktuellen Kontos, Modells und Endpoints, schreibt nicht in `.env` zurück und blockiert das Speichern nicht.

## Channels-Beispiele

### Offizieller DeepSeek-Kanal

```env
LLM_CHANNELS=deepseek
LLM_DEEPSEEK_PROTOCOL=deepseek
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_DEEPSEEK_API_KEY=sk-xxx
LLM_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro
LITELLM_MODEL=deepseek/deepseek-v4-flash
```

### OpenAI-kompatibles Aggregations- oder Custom-Gateway

```env
LLM_CHANNELS=my_proxy
LLM_MY_PROXY_PROTOCOL=openai
LLM_MY_PROXY_BASE_URL=https://your-proxy.example.com/v1
LLM_MY_PROXY_API_KEY=sk-xxx
LLM_MY_PROXY_MODELS=gpt-5.5,claude-sonnet-4-6
```

Die OpenAI-kompatible Base URL füllt man nur bis zum anbieterseitig kompatiblen Einstiegspunkt aus und hängt kein zusätzliches `/chat/completions` an. Lokale `.env`, Docker und selbstgehostete Skripte können den Custom-Kanal direkt verwenden; GitHub Actions benötigt einen Workflow, der die gleichnamigen `LLM_MY_PROXY_*`-Variablen explizit durchreicht.
Das Xiaomi-MiMo-Beispiel gilt analog: geeignet für lokale `.env`, Docker oder selbstgehostete Skripte; wird unter GitHub Actions `LLM_CHANNELS=mimo` verwendet, muss im Workflow manuell die `LLM_MIMO_*`-Zuordnung ergänzt werden, bevor sie wirksam wird.

## Gängige Anbieter-Voreinstellungen

| Anbieter | Kanalname | Protokoll | Base URL | Modellbeispiele |
| --- | --- | --- | --- | --- |
| AIHubmix | `aihubmix` | `openai` | `https://aihubmix.com/v1` | `gpt-5.5,claude-sonnet-4-6,gemini-3.1-pro-preview` |
| Anspire Open | `anspire` | `openai` | `https://open-gateway.anspire.cn/v6` (Beispiel) | `Doubao-Seed-2.0-lite,Doubao-Seed-2.0-pro,qwen3.5-flash,MiniMax-M2.7` (Beispiel) |
| OpenAI | `openai` | `openai` | `https://api.openai.com/v1` | `gpt-5.5,gpt-5.4-mini` |
| DeepSeek | `deepseek` | `deepseek` | `https://api.deepseek.com` | `deepseek-v4-flash,deepseek-v4-pro` |
| Gemini | `gemini` | `gemini` | leer | `gemini-3.1-pro-preview,gemini-3-flash-preview` |
| Anthropic Claude | `anthropic` | `anthropic` | leer | `claude-sonnet-4-6,claude-opus-4-7` |
| Kimi / Moonshot | `moonshot` | `openai` | `https://api.moonshot.cn/v1` | `kimi-k2.6,kimi-k2.5` |
| Tongyi Qianwen / DashScope | `dashscope` | `openai` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3.6-plus,qwen3.6-flash` |
| Zhipu GLM | `zhipu` | `openai` | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.1,glm-4.7-flash` |
| MiniMax | `minimax` | `openai` | `https://api.minimax.io/v1` | `MiniMax-M3,MiniMax-M2.7,MiniMax-M2.7-highspeed` |
| Xiaomi MiMo | `mimo` | `openai` | von der offiziellen Konsole bereitgestellt (in Actions standardmäßig nicht gemappt) | nach offizieller Dokumentation/Konsole |
| Volcano Ark / Doubao | `volcengine` | `openai` | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-seed-1-6-251015,doubao-seed-1-6-thinking-251015` |
| SiliconFlow | `siliconflow` | `openai` | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3.2,Qwen/Qwen3-235B-A22B-Thinking-2507` |
| OpenRouter | `openrouter` | `openai` | `https://openrouter.ai/api/v1` | `~anthropic/claude-sonnet-latest,~openai/gpt-latest` |
| Ollama | `ollama` | `ollama` | `http://127.0.0.1:11434` | `llama3.2,qwen2.5` |

## Offizielle Quellen und Kompatibilität

| Anbieter | Offizielle Quelle | Kompatibilitätshinweis |
| --- | --- | --- |
| Anspire Open | [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC) | `ANSPIRE_API_KEYS` kann, wenn keine OpenAI-kompatible Quelle mit höherer Priorität konfiguriert ist, für das LLM-Gateway und die Suche verwendet werden; das Standardbeispiel der Seite und der `.env` ist `openai/Doubao-Seed-2.0-lite` + `https://open-gateway.anspire.cn/v6`; ob es verwendbar ist, richtet sich nach Konsole und Modellberechtigungen. |
| OpenAI | [Modellliste](https://platform.openai.com/docs/models) | Die offizielle Modellseite empfiehlt, bei `gpt-5.5` zu beginnen; für Szenarien mit niedriger Latenz/Kosten `gpt-5.4-mini` oder `gpt-5.4-nano` verwenden. |
| DeepSeek | [Schnellstart](https://api-docs.deepseek.com/) | Die offizielle OpenAI-Base-URL ist `https://api.deepseek.com`; `deepseek-chat` / `deepseek-reasoner` werden am 2026-07-24 abgekündigt, die aktuellen Templates verwenden direkt `deepseek-v4-flash` / `deepseek-v4-pro`. |
| Gemini | [Modellliste](https://ai.google.dev/gemini-api/docs/models) | Gemini 3.1 Pro / Gemini 3 Flash sind weiterhin Preview; für Produktionsstabilität kann in der Konsole auf die stabilen 2.5-Modelle zurückgewechselt werden. |
| Anthropic Claude | [Modellübersicht](https://docs.anthropic.com/en/docs/about-claude/models/all-models) | Die aktuellen Claude-API-IDs umfassen `claude-sonnet-4-6`, `claude-opus-4-7`; Sonnet eignet sich besser als Standardeinstiegspunkt mit gutem Preis-Leistungs-Verhältnis. |
| Kimi / Moonshot | [Kimi K2.6 Schnellstart](https://platform.kimi.com/docs/guide/kimi-k2-6-quickstart), [Modellliste](https://platform.kimi.com/docs/models) | Offiziell wird `kimi-k2.6` empfohlen; die `kimi-k2`-Serie wird am 2026-05-25 abgeschaltet, alte `moonshot-v1-*` bleiben nur als Wahl für stabile Altlast-Workloads erhalten. |
| Tongyi Qianwen / DashScope | [Textgenerierung](https://help.aliyun.com/zh/model-studio/text-generation-model/) | Bailian empfiehlt `qwen3.6-plus`; nach bestätigter Wirksamkeit kann `qwen3.6-flash` die Kosten senken. |
| Zhipu GLM | [Modellübersicht](https://docs.bigmodel.cn/cn/guide/start/model-overview), [GLM-5.1](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.1) | `glm-5.1` ist das aktuelle Flaggschiff; `glm-4.7-flash` dient als Beispiel für ein leichtes/kostenloses Modell. |
| MiniMax | [OpenAI-API-Kompatibilität](https://platform.minimax.io/docs/api-reference/text-chat), [Modellliste abrufen](https://platform.minimax.io/docs/api-reference/models/openai/list-models), [Pricing](https://platform.minimax.io/docs/guides/pricing-paygo) | Die offizielle OpenAI-kompatible Base URL ist `https://api.minimax.io/v1`; gelistet werden `MiniMax-M3` (Standard, unterstützt Bildeingabe, offiziell bis zu 1M Eingabekontext, pricing unterscheidet zwei Eingabepreisstufen `<=512K` und `>512K`), `MiniMax-M2.7`, `MiniMax-M2.7-highspeed` sowie das Legacy-Modell `MiniMax-M2.5`. Die Fallback-Kostenschätzung dieses Repositorys registriert M3 konservativ über die Preisstufe `<=512K` und behält die M2.5-Legacy-Preise für die Kompatibilität historischer Nutzerkonfigurationen bei; Coding-Tool-Szenarien in der China-Region können den dedizierten `.com`/Anthropic-Einstiegspunkt verwenden, maßgeblich ist die Konsole. |
| Xiaomi MiMo | Offizielle Dokumentation / Konsole | Aktuell über die OpenAI-kompatible Art angebunden; Base URL, Modellname und Berechtigungen richten sich nach der offiziellen MiMo-Dokumentation/Konsole; der `mimo`-Kanal ist im Standard-Workflow des Repositorys nicht explizit gemappt, für Actions bitte die Custom-Zuordnung nach dem Abschnitt "GitHub Actions-Konfiguration" dieses Dokuments ergänzen. |
| Volcano Ark / Doubao | [Online-Inferenz (allgemein)](https://www.volcengine.com/docs/82379/2121998), [Modellliste](https://www.volcengine.com/docs/82379/1949118) | Offizielle Beispiele verwenden `https://ark.cn-beijing.volces.com/api/v3` und `doubao-seed-1-6-251015`; bei Nutzung eines Coding-Plans bitte die dedizierte Base URL und Modellnamen verwenden und nicht das Online-Inferenz-Template dieser Tabelle anwenden. |
| SiliconFlow | [Modellliste](https://docs.siliconflow.cn/quickstart/models), [Modellliste-API abrufen](https://docs.siliconflow.cn/cn/api-reference/models/get-model-list) | Die Plattformmodelle werden in Echtzeit aktualisiert und `/models` benötigt einen API-Key; Templates geben nur Beispiele für gängige neue Modelle; vor dem Speichern wird empfohlen, in der Web-Einstellungsseite auf "Modelle abrufen" zu klicken, um die Sichtbarkeit für das Konto zu bestätigen. |
| OpenRouter | [Models API](https://openrouter.ai/docs/api/api-reference/models/get-models) | OpenRouter unterstützt latest-Router-Aliasse wie `~anthropic/claude-sonnet-latest`, `~openai/gpt-latest`; ein manueller Live-Smoke vom 2026-05-03 bestand mit Claude Sonnet latest als Standardbeispiel, GPT latest bleibt als je nach Kontoberechtigung umschaltbare Alternative erhalten. |
| LiteLLM | [OpenAI-Compatible Endpoints](https://docs.litellm.ai/docs/providers/openai_compatible) | OpenAI-kompatible Endpoints verlangen, dass das Laufzeitmodell als `openai/<model>` geschrieben wird; die Base URL füllt man nur bis zum anbieterseitig kompatiblen Einstiegspunkt aus und hängt kein zusätzliches `/chat/completions` an. |

Die Voreinstellungen dieser Seite garantieren nur, dass die Konfigurationsform zu den OpenAI-kompatiblen Routingregeln der aktuellen Abhängigkeiten passt; die tatsächliche Konnektivität hängt weiterhin von Kontoberechtigungen, Region, Kontingent und Modellfreischaltung des Anbieters ab. Die aktuelle LiteLLM-Versionsbeschränkung ist `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (siehe `requirements.txt`); sie behält die historische Mindestversion, schließt explizit die PyPI-Vorfallversionen aus und verhindert, dass künftige Hauptversionen automatisch Einzug halten.

## OpenAI-kompatible und LiteLLM-Regeln

- Das Kanal-`protocol` eines OpenAI-kompatiblen Providers ist in der Regel `openai`.
- Der Laufzeitmodellname wird in der Regel als `openai/<model>` geschrieben; z. B. kann `gpt-5.5` in einem Custom-Gateway als `openai/gpt-5.5` über LiteLLM geroutet werden.
- `Qwen/...`, `deepseek-ai/...` usw. sind Organisationsnamen-Präfixe von Anbietern oder Modell-Repositories und nicht gleichbedeutend mit einem LiteLLM-Provider-Präfix; wegen des enthaltenen Schrägstrichs nicht als `provider/model`-Routing fehlinterpretieren.
- Die Base URL füllt man nur bis zum vom Anbieter oder Gateway angegebenen kompatiblen Einstiegspunkt aus, üblicherweise bis `/v1`, `/api/v3` oder einem im Herstellerdokument festgelegten Pfad; `/chat/completions` nicht manuell anhängen.
- Im YAML-Modus nach der nativesen Semantik von LiteLLM `model_list` / `litellm_params` konfigurieren; solange das YAML gültig ist, hat es Vorrang vor Channels.

## GitHub-Actions-Konfiguration

Der mitgelieferte `.github/workflows/00-daily-analysis.yml` des Repositorys reicht nur die im Workflow explizit gelisteten Umgebungsvariablen durch. Bei der Kanalnutzung zuerst in den Repository-Variables oder Secrets `LLM_CHANNELS` setzen und dann nach Kanalnamen das passende `LLM_<CHANNEL>_*` ergänzen.

| Feld | Empfohlener Ort | Erläuterung |
| --- | --- | --- |
| `LLM_CHANNELS` | Variables oder Secrets | Kommagetrennte Kanalnamen, z. B. `deepseek,minimax,volcengine`. |
| `LLM_<CHANNEL>_PROTOCOL` | Variables oder Secrets | Nicht sensibel, in der Regel `openai`, `deepseek`, `gemini`, `anthropic` oder `ollama`. |
| `LLM_<CHANNEL>_BASE_URL` | Variables oder Secrets | Bei Nicht-Sensitivität bevorzugt in Variables; private Gateway-Adressen können in Secrets. |
| `LLM_<CHANNEL>_MODELS` | Variables oder Secrets | Nicht sensible Modellliste, kommagetrennt. |
| `LLM_<CHANNEL>_ENABLED` | Variables oder Secrets | Optional, bei fehlender Konfiguration standardmäßig aktiviert; mit `false` kann der Kanal übersprungen werden. |
| `LLM_<CHANNEL>_API_KEY` / `LLM_<CHANNEL>_API_KEYS` | Secrets | Schlüsselfelder müssen in die Repository-Secrets; gleichnamige Variables liest der Workflow nicht. |
| `LLM_<CHANNEL>_EXTRA_HEADERS` | Secrets oder Variables | JSON-String; sobald Authentifizierungs-, Mandanten-, Organisations- oder private Gateway-Informationen enthalten sind, in Secrets legen. |
| `LITELLM_CONFIG` | Variables oder Secrets | YAML-Dateipfad; bei Verwendung zusammen mit `LITELLM_CONFIG_YAML` schreibt der Workflow in diesen Pfad. |
| `LITELLM_CONFIG_YAML` | bevorzugt Secrets | Der YAML-Inhalt kann selbst private Gateways oder Header enthalten, daher Secrets empfehlen. |
| `LLM_USAGE_HMAC_SECRET` | Secrets | Optional; nur wenn usage-Message-HMACs über Deployments hinweg verglichen werden sollen, denselben zufälligen High-Entropy-Key konfigurieren, z. B. `openssl rand -hex 32`; nicht in Variables legen oder in die Versionskontrolle committen. |
| `LLM_USAGE_HMAC_KEY_VERSION` | Variables oder Secrets | Optional; beim Rotieren von `LLM_USAGE_HMAC_SECRET` das Versionslabel synchron aktualisieren, um einen falschen Vergleich von HMACs unterschiedlicher Keys zu vermeiden. |

Der Standard-Workflow hat `primary`, `secondary`, `aihubmix`, `anspire`, `deepseek`, `dashscope`, `zhipu`, `moonshot`, `minimax`, `volcengine`, `siliconflow`, `openrouter`, `gemini`, `anthropic`, `openai`, `ollama`, `hermes` explizit gemappt; `mimo` ist im Standard-Workflow nicht gemappt. Bei Verwendung von `mimo` (oder eines beliebigen nicht gelisteten Kanalnamens) müssen zusätzlich zur Konfiguration der gleichnamigen `LLM_<CHANNEL>_*` in Variables/Secrets die entsprechenden env-Zuordnungen synchron im Workflow ergänzt werden; lokale `.env`, Docker und selbstgehostete Skripte unterliegen dieser Einschränkung nicht.

Beim expliziten Rollback der HMAC-Telemetriekonfiguration kann `LLM_USAGE_HMAC_SECRET` entfernt und `LLM_USAGE_HMAC_KEY_VERSION` wiederhergestellt oder gelöscht werden; nach dem Leerlassen kehrt das System zum Standardverhalten der lokalen Erzeugung von `.llm_usage_hmac_secret` zurück.

Die Standard-Base-URL von Ollama `http://127.0.0.1:11434` ist primär für lokale Umgebungen, Docker oder Self-hosted Runner gedacht, die den Dienst erreichen können. GitHub-hosted Runner haben in der Regel keinen lokalen Ollama-Dienst; eine direkte Konfiguration von `LLM_CHANNELS=ollama` führt sehr wahrscheinlich zu Verbindungsfehlern.

### Hermes lokale HTTP-Erzeugung (Phase 3)

Hermes ist ein reserviertes Preset für die lokale HTTP-Erzeugung und wird nur über `LLM_CHANNELS=hermes` aktiviert. Standardprotokoll ist `openai`, Standardadresse ist `http://127.0.0.1:8642/v1`, Standardmodell ist `hermes-agent`:

```env
LLM_CHANNELS=hermes
LLM_HERMES_PROTOCOL=openai
LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1
LLM_HERMES_API_KEY=sk-local-hermes
LLM_HERMES_MODELS=hermes-agent
LITELLM_MODEL=openai/hermes-agent
```

Phase 3 unterstützt nur normale Analyse-/JSON-Erzeugung, nicht stream/SSE, tools, Vision, Agent-Tools, Remote-Hermes oder Prozesslebenszyklusverwaltung. `LLM_HERMES_API_KEY` sollte aus der lokalen `.env`, der Laufzeitkonfiguration oder den GitHub-Secrets stammen; nicht ins Repository schreiben. Hermes erlaubt nur Loopback-`/v1`-Endpoints, `localhost` wird nach `127.0.0.1` normalisiert, `LLM_HERMES_API_KEYS` und `LLM_HERMES_EXTRA_HEADERS` werden nicht unterstützt. Beim Speichern des reservierten Hermes-Kanals in der Web-Einstellungsseite werden diese beiden alten Felder geleert und eine Warnung angezeigt; zur Wiederherstellung alter Werte die `.env`-Sicherung, die Git-Historie oder die Desktop-Export-Sicherung verwenden, aber nicht leere Multi-Keys/Extra-Headers werden vom Backend weiterhin abgelehnt.

Unter GitHub Actions ist `127.0.0.1` eines GitHub-hosted Runners der Runner selbst, nicht der Nutzercomputer. Nur Self-hosted Runner oder Dienste auf demselben Rechner können auf lokales Hermes zugreifen; sonst schlägt die Verbindung fehl.

## Häufige Fehler und Bearbeitungsempfehlungen

| `details.reason` / Symptom | Häufige Ursache | Empfohlene Behandlung |
| --- | --- | --- |
| `missing_api_key` | API-Key ist leer oder die kommagetrennten `API_KEYS` enthalten keinen nicht leeren Teil. | Mindestens einen gültigen Key eintragen; ausgenommen lokale Ollama- oder localhost-kompatible Dienste. |
| `api_key_rejected` | Der Anbieter gibt 401 / 403 zurück; Key ungültig, Berechtigungen unzureichend oder Projekt nicht freigeschaltet. | Key erneut kopieren; Konto-Projekt, Organisation, Region und Modellberechtigungen prüfen. |
| `insufficient_balance` | Guthaben unzureichend, Rechnung nicht aktiviert oder Kontingent des Pakets erschöpft. | In der Anbieter-Konsole Guthaben, Rechnungsstatus und Modellpaket bestätigen. |
| `quota_exceeded` | Kontingent des Kontos oder der Organisation erschöpft. | Paket, Projektkontingent, Organisationskontingent und die Rechnungsseite des Anbieters prüfen. |
| `rate_limit` | RPM / TPM / Nebenläufigkeitslimit ausgelöst. | Nebenläufigkeit senken, auf ein leichtes Modell wechseln oder das Limit in der Konsole erhöhen. |
| `timeout` | Anfrage-Timeout, möglicherweise langsames Netz, langsame Anbieterantwort oder nicht reagierender lokaler Dienst. | Proxy, Firewall, Base URL, Modell-Kaltstart und Timeout-Einstellungen prüfen. |
| `dns_error` | Domain kann nicht aufgelöst werden. | Base-URL-Schreibweise, DNS, Proxy und Netz der Laufumgebung prüfen. |
| `tls_error` | TLS-Zertifikat, Proxy oder Man-in-the-Middle-Zertifikat anomal. | HTTPS-Zertifikatskette, Firmenproxy, selbstsignierte Zertifikate und Systemzeit prüfen. |
| `connection_refused` | Auf dem Zielport läuft kein Dienst oder der lokale Dienst ist nicht gestartet. | Base URL, Port, Firewall prüfen; bei Ollama bestätigen, dass der Rechner oder Runner den Dienst erreichen kann. |
| `endpoint_not_found` | Pfad `/models` oder des Chat-Endpoints existiert nicht. | Bestätigen, ob die Base URL bis zum kompatiblen Einstiegspunkt gefüllt ist; nicht zu viel oder zu wenig vom vom Hersteller verlangten Pfad anhängen. |
| `invalid_url` | base_url enthält nicht unterstützte Formen (Leerzeichen/Steuerzeichen, Backslash, `userinfo@host` usw.) oder die Parsing-Semantik ist unsicher. | `LLM_<CHANNEL>_BASE_URL` bereinigen (empfohlen: Variable zuerst leeren/löschen) und den Standardeinstiegspunkt des Providers behalten; für ein festes Gateway zuerst nach offiziellen kompatiblen Beispielen füllen. |
| `model_access_denied` | Best-effort-Einordnung der Modellverfügbarkeit anhand beobachteter Provider-Texte: Modell kann deaktiviert, nicht freigeschaltet, für das Konto unsichtbar sein oder der aktuelle Key hat keinen Zugriff. | Zuerst das "in diesem Test verwendete Modell" im Testergebnis ansehen und in der Anbieter-Konsole bestätigen, dass das Modell freigeschaltet ist; bei Bedarf die Modellreihenfolge anpassen, unverfügbare Modelle entfernen oder auf "Modelle abrufen" klicken, um die für das Konto sichtbaren Modelle abzugleichen. |
| `provider_blocked` | Der Anbieter oder das Relais-Gateway hat diese Anfrage eindeutig blockiert; möglich sind Konto-Risikokontrolle, Region, Anfragequelle, Modellberechtigungen, Reseller-Policy oder Content-Security-Policy. | Zuerst das "in diesem Test verwendete Modell" im Testergebnis und die Logs der Anbieter-Konsole ansehen; Konto-/Projektstatus, Regions- oder Quellenbeschränkungen, Gateway-Policies und Content-Security-Regeln prüfen, statt zuerst Base URL, TLS oder lokales Netz zu untersuchen. |
| `provider_prefix_mismatch` | LiteLLM-Provider-Präfix passt nicht zum Kanalprotokoll. | OpenAI-kompatible Kanäle verwenden in der Regel `openai/<model>`; `Qwen/...`, `deepseek-ai/...` nicht als Provider-Präfix fehlinterpretieren. |
| `non_json` | Der Anbieter gibt kein JSON zurück oder der Proxy gibt eine HTML-/Text-Fehlerseite zurück. | Base URL, Gateway-Pfad, Proxy-Fehlerseite und Chat-Completions-kompatiblen Einstiegspunkt prüfen. |
| `null_response` | LiteLLM hat kein parsebares Antwortobjekt zurückgegeben. | Prüfen, ob der Provider mit Chat Completions kompatibel ist; bei Bedarf Modell oder Endpoint wechseln und erneut versuchen. |
| `null_content` | Chat-Completion erfolgreich, aber `content` leer. | Auf ein kompatibles Textausgabemodell wechseln oder prüfen, ob tool-/vision-Antworten erzwungen werden. |
| `malformed_choices` | Der Antwort fehlt eine kompatible `choices`-Struktur. | Bestätigen, dass der Endpoint eine Chat-Completions-kompatible Schnittstelle ist, kein Embeddings-, Responses- oder sonstiges Protokoll-Einstiegspunkt. |
| `capability_unsupported` | JSON-/tools-/stream-/vision-Smoke-Parameter werden von Modell oder Endpoint nicht unterstützt. | Auf ein Modell mit dieser Fähigkeit wechseln oder das Ergebnis als einmalige Fähigkeitsdiagnose des aktuellen Kontos, Modells und Endpoints betrachten, nicht als globale Nicht-Unterstützung des Providers. |
| `unknown_error` | Vom Anbieter oder Client wurde eine nicht weiter aufgeschlüsselte Ausnahme geworfen. | Zuerst den Rohfehler in `details.message` / den Logs ansehen und dann nacheinander Netz, Authentifizierung, Modellname und Kontingent prüfen. |

Die vollständige Klassifikationslogik richtet sich nach der Fehlerklassifikationsimplementierung in `src/services/system_config_service.py`.

`model_access_denied` ist keine offizielle Fehlercode-Zuordnung über Provider hinweg. Zu den überprüfbaren Belegen dieser Klassifikation gehören:

- Die offizielle Fehlerbehandlungsdokumentation von SiliconFlow verlangt, bei der Schnittstellen-Fehlerbehebung den HTTP-Fehlercode und die `message` zu protokollieren; 403 bedeutet unzureichendes Guthaben oder fehlende Berechtigung, andere Fälle orientieren sich an der Fehler-`message`, und es wird empfohlen, ein anderes Modell auszuprobieren, um zu bestätigen, ob das Problem weiterhin besteht (Chinesisch: <https://docs.siliconflow.cn/cn/faqs/error-code>; Englisch: <https://docs.siliconflow.cn/en/faqs/error-code>).
- Das reale, maskierte Beispiel in Issue #1208 stammt aus Tests des SiliconFlow-/OpenAI-Compatiblen-Kanals und lieferte über LiteLLM `litellm.APIError: APIError: OpenAIException - Model disabled.` zurück.
- Online-Nachverifikationsprotokoll (2026-05-06T16:21:21Z): Unter der Beschränkung `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` war die lokale Verifikationsumgebung Python `3.13.12`, LiteLLM `1.82.3`, Base URL `https://api.siliconflow.cn/v1`, Modell `Qwen/Qwen3-235B-A22B-Thinking-2507`. Der direkte Aufruf der SiliconFlow Chat Completions lieferte HTTP `403` mit dem Antwortkörper `{"code":30003,"message":"Model disabled.","data":null}`; dasselbe Modell lieferte über LiteLLM `completion(model="openai/Qwen/Qwen3-235B-A22B-Thinking-2507")` `APIError: OpenAIException - Model disabled.` zurück.

Daher behandelt die aktuelle Laufzeit diese beobachtete Provider-`message` als best-effort-Diagnose der Modellverfügbarkeit, statt sie als offiziellen anbieterübergreifenden Fehlercode zu deklarieren. Die Implementierung tritt nur dann in diese Diagnose ein, wenn der Fehlertext zugleich `model` und ein klares Berechtigungs-, Deaktivierungs- oder Unverfügbarkeitssignal enthält; nicht abgedeckte oder semantisch unterschiedliche Provider-Texte laufen weiter in die bestehende Fallback-Diagnose. `provider_blocked` ist ebenfalls eine best-effort-Diagnose auf Basis eindeutiger Blockierungstexte und dient dazu, Anbieter-/Gateway-Policy-Blockierungen von lokalen Netz-, TLS- oder Modellunverfügbarkeitsproblemen zu unterscheiden.

## Grenzen der Laufzeitfähigkeits-Erkennung

- JSON-/tools-/stream-/vision-Smokes müssen in der Web-App explizit ausgelöst werden.
- Die Erkennung erzeugt echte LLM-Anfragen und kann Token-/Bildeingabekosten, RPM/TPM-Limits, unzureichendes Guthaben oder Timeouts mit sich bringen.
- Das Erkennungsergebnis repräsentiert nur ein einmaliges best-effort-Laufzeitergebnis des aktuellen Kontos, Modells und Endpoints.
- Das Erkennungsergebnis wird nicht in `.env` zurückgeschrieben und blockiert auch nicht das Speichern der Konfiguration.
- Ein fehlgeschlagener Fähigkeitstest bedeutet nicht, dass der Provider global nicht unterstützt; der Fehlschlag kann von Kontoberechtigungen, nicht freigeschalteten Modellen, der Endpoint-Region, dem Guthaben, der anbieterseitigen Kompatibilitätsschicht oder dem LiteLLM-Konvertierungspfad stammen.
- Die aktuelle Implementierung führt keinen Online-Smoke für alle echten Provider durch; Kompatibilitätsgrundlage sind `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` (siehe `requirements.txt`), das [LiteLLM Python SDK / OpenAI I/O format](https://docs.litellm.ai/), das [LiteLLM OpenAI-compatible Routing](https://docs.litellm.ai/docs/providers/openai_compatible) sowie die Anfrageformen [JSON mode](https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat), [tool calling](https://platform.openai.com/docs/guides/function-calling?api-mode=chat), [streaming](https://platform.openai.com/docs/guides/streaming-responses?api-mode=chat) und [vision input](https://platform.openai.com/docs/guides/images-vision?api-mode=chat) der OpenAI Chat Completions.

## Rollback-Wege

- Web-Einstellungsseite: Entsprechenden Kanal löschen oder deaktivieren und Hauptmodell / Agent-Modell / Fallback erneut auf die alten Werte setzen.
- `.env`: Aus der Sicherung `LLM_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `LITELLM_FALLBACK_MODELS` wiederherstellen.
- Von Channels zu Legacy: `LLM_CHANNELS` löschen oder leeren und Legacy-Provider-Key und `LITELLM_MODEL` beibehalten.
- Von YAML zu Channels/Legacy: `LITELLM_CONFIG` / `LITELLM_CONFIG_YAML` entfernen; nach dem Neustart wirkt die darunterliegende Konfiguration wieder.
- WebUI / Desktop-CLI: Über die in den Systemeinstellungen exportierte Konfigurationssicherung wiederherstellen.
- PR-Rollback: Den betreffenden Docs-PR revertieren; P4 betrifft keine Konfigurations-, Daten- oder Code-Migration.
