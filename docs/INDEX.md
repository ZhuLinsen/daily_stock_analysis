# Dokumentationszentrum

Dies ist der Einstiegspunkt in die Projektdokumentation. Das README ist für Projektüberblick und Schnellstart zuständig; vollständigere Hinweise zu Konfiguration, Bereitstellung, Funktionen und Fehlerbehebung starten von hier aus.

## Auswahl nach Szenario

| Ich möchte | Zuerst ansehen | Danach ansehen |
| --- | --- | --- |
| Schnell wissen, was das Projekt kann | [README](../README.md) | [Vollständiger Konfigurations- und Bereitstellungsleitfaden](full-guide.md) |
| Das Projekt zum ersten Mal zum Laufen bringen | [Client-Installation und -Konfiguration für Einsteiger](beginner-client-setup.md) | [Vollständiger Konfigurations- und Bereitstellungsleitfaden](full-guide.md) |
| Großmodelle-Kanäle konfigurieren | [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md) | [Konfigurationsleitfaden für LLM-Anbieter](llm-providers.md) |
| Push-Benachrichtigungen konfigurieren | [Fähigkeits-Baseline für Benachrichtigungen](notifications.md) | [Vollständiger Konfigurations- und Bereitstellungsleitfaden](full-guide.md) |
| Auf einem Server oder einer Cloud-Plattform bereitstellen | [Bereitstellungsleitfaden](DEPLOY.md) | [Cloud-WebUI-Bereitstellung](deploy-webui-cloud.md), [Zeabur-Bereitstellung](docker/zeabur-deployment.md) |
| Bot / IM-Anbindung nutzen | [Bot-Befehle und Anbindung](bot-command.md) | [Bot-Plattformkonfiguration](bot/) |
| Laufzeitprobleme eingrenzen | [FAQ](FAQ.md) | [Änderungsprotokoll](CHANGELOG.md) |
| Datenquellen-Fehler oder -Degradierung behandeln | [Datenquellen-Stabilität und Fehlerbehandlungs-Diagramm](data-source-stability.md) | [FAQ](FAQ.md) |
| An der Entwicklung teilnehmen oder PRs einreichen | [Beitragsleitfaden](CONTRIBUTING.md) | [API-Spezifikation](architecture/api_spec.json) |

## Schnellstart

| Dokument | Inhalt |
| --- | --- |
| [README](../README.md) | Projektpositionierung, Kernfunktionen, Schnellstart, Push-Wirkung |
| [Client-Installation und -Konfiguration für Einsteiger](beginner-client-setup.md) | Client-Download für Nutzer ohne Code-Erfahrung, Konfiguration der Modelle Anspire Open / AIHubMix, Nachrichtenquellen-Konfiguration und häufige Fragen |
| [Vollständiger Konfigurations- und Bereitstellungsleitfaden](full-guide.md) | Umgebungsvorbereitung, Ausführungsarten, Konfigurationshinweise, Bereitstellungspfade und häufige Fragen |
| [FAQ](FAQ.md) | Häufige Fragen zu Konfiguration, Modellen, Benachrichtigungen, Bereitstellung und Laufzeit |
| [Datenquellen-Stabilität und Fehlerbehandlungs-Diagramm](data-source-stability.md) | Anwendungsszenarien, Fallback-Pfade und empfohlene Konfiguration der angebundenen Quellen wie Tushare, TickFlow, AkShare, Efinance, YFinance und Longbridge |
| [Änderungsprotokoll](CHANGELOG.md) | Versionsänderungen, Fähigkeitsanpassungen und Migrationshinweise |

## Konfiguration

| Dokument | Inhalt |
| --- | --- |
| [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md) | Großmodelle-Kanäle, dreischichtige Konfiguration, Web-Einstellungsseite und Konfiguration gängiger Modelle |
| [Konfigurationsleitfaden für LLM-Anbieter](llm-providers.md) | Provider-Voreinstellungen, Actions-Zuordnung, Fehlerklassifizierung und Diagnoseempfehlungen |
| [LiteLLM-YAML-Beispiel](examples/litellm_config.example.yaml) | Beispiel für die Multi-Kanal-Konfiguration von LiteLLM |
| [Fähigkeits-Baseline für Benachrichtigungen](notifications.md) | Konfiguration der Benachrichtigungskanäle WeCom, Feishu, Telegram, Discord, Slack, E-Mail usw. |
| [Leitfaden zur Tushare-Aktienliste](TUSHARE_STOCK_LIST_GUIDE.md) | Konfiguration und Verwendungshinweise zur Tushare-Aktienliste |

## Nutzungsthemen

| Dokument | Inhalt |
| --- | --- |
| [Bot-Befehle und Anbindung](bot-command.md) | Bot-Befehle, Webhook, Plattformanbindung und Callback-Hinweise |
| [Bot-Plattformkonfiguration](bot/) | Screenshots und ergänzende Hinweise zur Konfiguration von Bots wie Feishu, DingTalk und Discord |
| [Echtzeit-Alarmzentrum](alerts.md) | EventMonitor-Baseline, Web-Regelverwaltung, Benachrichtigungsergebnisse, Kühlstatus und Phasengrenzen |
| [DecisionSignal-Entscheidungssignale](decision-signals.md) | Feld-Semantik des AI-Vorschlags-Pools, API, Web-Anzeige, Alarm-/Benachrichtigungs-/Kombinationsrisiko-Verknüpfung, Nachbewertung, Entsensibilisierung, Migration und Rollback |
| [Informations-/Intelligence-Quellen](intelligence-sources.md) | Konfiguration, Tests, Abruf, Deduplizierung, Speicherung, Abfrage und Sicherheitsgrenzen von RSS/Atom-konformen Informationsquellen |
| [Analyse-Kontextpaket-Vertrag, Laufzeitkonsum und Sichtbarkeit](analysis-context-pack.md) | Erstversion-Umfang des AnalysisContextPack, Feldqualitätsstatus, interne P1/P2-Verträge, P3-Prompt-Zusammenfassungskonsum, P4-Historie/API/Web-Niedrigsensibilitäts-Sichtbarkeit, P5-Datenqualitäts-Score, P6-Migration/Rollback und Quellcode-Anker; der vollständige Leitfaden ergänzt die #1386-Phasenbewusste Analyse, Migration und Rollback-Einstiege |
| [Bilderkennungs-Prompt](image-extract-prompt.md) | Prompt und Nutzungsgrenzen der Bilderkennung von Aktieninformationen |
| [OpenClaw-Skill-Integration](openclaw-skill-integration.md) | Hinweise zur externen Integration von OpenClaw / Skill |

## Bereitstellung und Paketerstellung

| Dokument | Inhalt |
| --- | --- |
| [Bereitstellungsleitfaden](DEPLOY.md) | Serverbereitstellung, Docker, systemd, Supervisor usw. |
| [Cloud-WebUI-Bereitstellung](deploy-webui-cloud.md) | Bereitstellungshinweise für den Zugriff auf die WebUI von einem Cloud-Server |
| [Zeabur-Bereitstellung](docker/zeabur-deployment.md) | Bereitstellungshinweise für die Zeabur-Plattform |
| [Hinweise zum Packen der Desktop-Version](desktop-package.md) | Packenhinweise für die Electron-Desktopversion und das Web-Build-Artefakt |

## Referenz und Entwicklung

| Dokument | Inhalt |
| --- | --- |
| [API-Spezifikation](architecture/api_spec.json) | FastAPI-OpenAPI-Spezifikationsartefakt |
| [Beitragsleitfaden](CONTRIBUTING.md) | Anforderungen an Issues, PRs, Tests, Dokumentsynchronisation und Zusammenarbeit |

## Mehrsprachigkeit

| Dokument | Inhalt |
| --- | --- |
| [Englisches Dokumentationsverzeichnis](INDEX_EN.md) | English documentation index |
| [Englisches README](README_EN.md) | English project overview and quick start |
| [Deutsches README](README_DE.md) | Projektüberblick und Schnellstart auf Deutsch |
