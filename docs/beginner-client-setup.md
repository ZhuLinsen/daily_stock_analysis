# Einrichtungsleitfaden für den Anfänger-Client

Dieses Dokument ist für Benutzer gedacht, die keinen Code schreiben können und den Client einfach herunterladen und direkt verwenden möchten. Das Ziel ist einfach: Client herunterladen, einen Modellservice-Key eintragen, Aktiencodes eintragen und dann den ersten Analysebericht erzeugen.

> Dieses Projekt erzeugt unterstützende Analyseberichte, die keine Anlageberatung darstellen. Beim echten Handel musst du das Risiko selbst einschätzen.

## Vorbereitung

1. Ein Windows- oder macOS-Computer.
2. Ein Modellservice-Key; empfohlen wird, einen der folgenden auszuwählen:
   - [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC): Unterstützt gängige globale Modelle; ein Key kann gleichzeitig für Modell und Nachrichtensuche verwendet werden — für die erste Konfiguration am wenigsten Aufwand.
   - [AIHubMix](https://aihubmix.com/?aff=CfMq): Unterstützt gängige globale Modelle, geeignet für Benutzer, die auf einer Plattform mehrere Modelle wechseln möchten.
3. Die Aktiencodes, die du analysieren möchtest, z. B. `600519,hk00700,AAPL`.

## 1. Client herunterladen

Die Release-Seite öffnen:

<https://github.com/ZhuLinsen/daily_stock_analysis/releases/latest>

Im Abschnitt `Assets` (Anlagen) unten auf der Seite herunterladen:

| Computer | Welches herunterladen |
| --- | --- |
| Windows | `daily-stock-analysis-windows-installer-<Versionsnummer>.exe` |
| Windows, keine Installation gewünscht | `daily-stock-analysis-windows-noinstall-<Versionsnummer>.zip` |
| macOS Apple-Chip | `daily-stock-analysis-macos-arm64-<Versionsnummer>.dmg` |
| macOS Intel-Chip | `daily-stock-analysis-macos-x64-<Versionsnummer>.dmg` |

Lade `latest.yml` und `*.blockmap` nicht herunter; es sind keine Client-Installationspakete.

Du weißt nicht, welcher Chip in deinem Mac steckt: Klicke oben links auf das Apple-Symbol -> Über diesen Mac; bei M1/M2/M3/M4 wähle `arm64`, bei Intel wähle `x64`.

## 2. Installieren und öffnen

- Windows-Installationspaket: `.exe` doppelklicken, den Anweisungen folgen; der Installationsordner kann beim Standardwert bleiben.
- Windows-Installationsfreies Paket: `.zip` entpacken, `Daily Stock Analysis.exe` doppelklicken.
- macOS: `.dmg` doppelklicken, die App in den `Programme`-Ordner (Applications) ziehen. Das aktuelle DMG ist nicht mit der Apple-Developer-Signatur signiert und nicht notariell beglaubigt; Gatekeeper kann den Start weiterhin blockieren; öffne nur die offiziellen Anlagen von GitHub Releases unter „Datenschutz und Sicherheit" zum Öffnen; vollständige Einschränkungen und Troubleshooting siehe `docs/desktop-package.md`.

macOS-Benutzer sollten vor einem Upgrade empfehlenswerterweise in den Client-Einstellungen ein Konfigurations-Backup exportieren.

## 3. AI-Modell konfigurieren

Den Client öffnen und gehen zu:

`Systemeinstellungen -> AI-Modell`

Nur eines der folgenden Schemata auswählen.

> Wichtig: Nach jeder Änderung an den Einstellungen auf die Speichern-Schaltfläche der Seite klicken; erst wenn der Speicher-Erfolgshinweis erscheint, die Seite wechseln oder zur Startseite zurückkehren.

### Schema A: Anspire Open

1. [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC) öffnen, registrieren / einloggen und einen API-Key erstellen.
2. Zurück im Client im Schnellhinzufügen-Kanal `Anspire Open` auswählen.
3. Den API-Key einfügen.
4. Beim Modellnamen ein in der Konsole freigeschaltetes Modell auswählen; wenn unsicher, zuerst das von der Konsole empfohlene oder ein leichtgewichtiges Modell wählen.
5. Auf Speichern klicken; nach dem Erfolgshinweis auf Verbindung testen klicken.

### Schema B: AIHubMix

1. [AIHubMix](https://aihubmix.com/?aff=CfMq) öffnen, registrieren / einloggen und einen API-Key erstellen.
2. Zurück im Client im Schnellhinzufügen-Kanal `AIHubmix (Aggregationsplattform)` auswählen.
3. Den API-Key einfügen.
4. Beim Modellnamen ein in der Konsole freigeschaltetes Modell auswählen; wenn unsicher, zuerst das von der Konsole empfohlene Modell wählen.
5. Auf Speichern klicken; nach dem Erfolgshinweis auf Verbindung testen klicken.

Wenn der Test erfolgreich ist, mit dem nächsten Schritt fortfahren.

## 4. Watchlist ausfüllen

Gehen zu:

`Systemeinstellungen -> Grundeinstellungen`

`Watchlist` finden und ausfüllen:

`600519,hk00700,AAPL`

Mehrere Aktien mit englischen Kommas trennen. Häufige Schreibweisen:

- A-Aktien: `600519`, `300750`, `000001`
- Hongkong-Aktien: `hk00700`, `hk09988`
- US-Aktien: `AAPL`, `TSLA`, `NVDA`

Nach dem Ausfüllen auf Speichern klicken und erst nach dem Erfolgshinweis zur Startseite zurückkehren.

## 5. Empfohlene Konfiguration einer Nachrichtenquelle

Eine Nachrichtenquelle ist nicht Pflicht, aber eine Konfiguration wird empfohlen. Sie beeinflusst aktuelle Nachrichten, Unternehmensmeldungen, ereignisgesteuerte Themen, Hot-Spot-Themen und Risikohinweise.

Gehen zu:

`Systemeinstellungen -> Datensources`

Nach deinem Modellservice auswählen:

1. Mit Anspire Open: `Anspire API Keys` finden, denselben Anspire-Key eintragen, nach erfolgreichem Speichern fertig.
2. Mit AIHubMix: Empfohlen wird, zusätzlich einen Key von [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) oder [Tavily](https://tavily.com/) zu beantragen und in `SerpAPI API Keys` bzw. `Tavily API Keys` einzutragen; nach erfolgreichem Speichern fertig.

Wenn du zuerst ausprobieren möchtest, kannst du die Nachrichtenquelle auch überspringen; der Client kann weiterhin Basisanalysen erzeugen.

## 6. Analyse starten

Zurück zur Startseite:

1. Einen Aktiencode eingeben, z. B. `600519`.
2. Auf Analyse klicken.
3. Warten, bis die Aufgabe von „In der Warteschlange", „Wird analysiert" zu „Analyse abgeschlossen" wechselt.
4. Den Bericht im Verlauf ansehen.

## Häufige Fragen

### Auf der Download-Seite gibt es viele Dateien, welche soll ich herunterladen?

Normale Windows-Benutzer laden das Installationspaket `.exe` herunter. Lade `latest.yml` oder `*.blockmap` nicht herunter.

### Der API-Key ist eingetragen, funktioniert aber trotzdem nicht?

Diese Punkte prüfen:

1. Ob der Key vollständig kopiert wurde und keine überflüssigen Leerzeichen enthält.
2. Ob das Plattformkonto ein Guthaben oder Kontingent hat.
3. Ob das aktuelle Modell freigeschaltet ist.
4. Ob der Verbindungstest „Modell existiert nicht", „Unzureichende Berechtigung" oder „Unzureichendes Guthaben" meldet.

### Die Konfiguration ist durcheinander, was tun?

In den Client-Einstellungen ein Konfigurations-Backup exportieren. Bei Problemen kann das frühere Backup importiert werden, oder nur diese drei Punkte neu konfigurieren: AI-Modell, Watchlist, Nachrichtenquelle.
