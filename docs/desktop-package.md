# Hinweise zum Desktop-Paket (Electron + React UI)

Dieses Projekt lässt sich als Desktop-Anwendung verpacken. Electron dient dabei als Desktop-Shell, die React UI von `apps/dsa-web` als Oberfläche.

## Architektur-Übersicht

- Die React UI (mit Vite gebaut) wird vom lokalen FastAPI-Dienst bereitgestellt
- Beim Start zieht Electron den Backend-Dienst automatisch hoch und lädt die UI, sobald `/api/health` bereit ist
- Im Windows-Portable-/Installationsmodus liegen die Benutzerkonfiguration `.env` und die Datenbank im selben Verzeichnis wie die exe; die macOS-Paketversion nutzt das Electron-Benutzerdatenverzeichnis für Laufzeitkonfiguration
- Der Desktop startet automatisch einen verfügbaren Port aus dem Bereich `8000-8100` des lokalen Rechners und synchronisiert den tatsächlich gewählten Port an das eingebaute Backend; die Desktop-Version ist nicht von `WEBUI_PORT` in der `.env` abhängig, um die Fenster-Verbindungsadresse zu bestimmen. So wird vermieden, dass Electron nach einer Portänderung durch den Benutzer weiterhin auf den alten Port wartet und dadurch beim Start ein Timeout auftritt
- Das Desktop-Backend wird standardmäßig zusammen mit `requirements.txt` installiert und `futu-api==10.8.6808` eingefroren; die Windows-/macOS-Build-Skripte führen im Quellcode-Umfeld und im PyInstaller-Artefakt jeweils ein `import futu` aus, damit das Release-Paket das SDK tatsächlich mitführt und es nicht nur installiert ist.

## Lokale Entwicklung

Ein-Klick-Start (Entwicklungsmodus):

```bash
powershell -ExecutionPolicy Bypass -File scripts\run-desktop.ps1
```

Oder manuell ausführen:

1) React UI bauen (Ausgabe nach `static/`)

```bash
cd apps/dsa-web
npm install
npm run build
```

2) Electron-App starten (zieht das Backend automatisch hoch)

```bash
cd apps/dsa-desktop
npm install
npm run dev
```

Beim ersten Start wird automatisch aus `.env.example` eine `.env` erzeugt.

## Verpacken (Windows)

### Voraussetzungen

- Node.js 18+
- Python 3.10+
- Windows-Entwicklermodus aktivieren (electron-builder benötigt symbolische Verknüpfungen)
  - Einstellungen -> Datenschutz und Sicherheit -> Entwickleroptionen -> Entwicklermodus

### Ein-Klick-Verpacken

```bash
powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
```

Dieses Skript führt der Reihe nach aus:
1. React UI bauen
2. Python-Abhängigkeiten installieren
3. Backend mit PyInstaller verpacken
4. Desktop-Anwendung mit electron-builder verpacken

Das aktuelle Windows-Installationsprogramm nutzt den NSIS-Assistenten, unterstützt nur die Installation für den aktuellen Benutzer und deaktiviert die Admin-Erhöhung. Beim Installieren lässt sich das Zielverzeichnis manuell wählen (z. B. außerhalb des C-Laufwerks). Das Installationsprogramm verhindert über den NSIS-Rückruf `.onVerifyInstDir` auf Installer-Ebene die Auswahl von geschützten Systemverzeichnissen wie `Program Files` oder `Windows` – bei diesen Pfaden wird die Schaltfläche „Weiter" automatisch deaktiviert. Nach der Installation erzeugt bzw. liest die Desktop-Version weiterhin nach bestehender Logik neben dem Installationsverzeichnis `.env`, `data/stock_analysis.db` (inklusive `data/stock_analysis.db-wal` / `data/stock_analysis.db-shm`) und `logs/desktop.log`. Empfohlen wird das standardmäßige per-user Installationsverzeichnis. Falls keine Installation gewünscht ist, kann weiterhin das portable `win-unpacked`-Paket verteilt werden.

## Automatisches Verpacken und Release über GitHub CI

Das Repository unterstützt es, über GitHub Actions die Desktop-Version automatisch zu bauen und auf GitHub Releases hochzuladen:

- Workflow: `.github/workflows/desktop-release.yml`
- Auslöser:
  - Automatisch nach dem Pushen eines semantischen Tags (z. B. `v3.2.12`)
  - Manuell auf der Actions-Seite auslösen und `release_tag` angeben
- Artefakte:
  - Windows-Installationsprogramm: In den Release-Anhängen und lokal unter `apps/dsa-desktop/dist/` einheitlich als `daily-stock-analysis-windows-installer-<tag>.exe`
  - Metadaten für Windows-Auto-Update: Die Release-Anhänge enthalten zusätzlich `latest.yml` und `*.blockmap`, damit die installierte Desktop-Version Updates im Hintergrund herunterladen und prüfen kann; normale Benutzer müssen diese Metadaten nicht manuell herunterladen. Nach dem Download führt der Benutzer die Bestätigung „Neu starten und installieren" aus; die Desktop-Version stoppt dann zuerst das eingebaute Backend, sichert die Laufzeitdateien und führt den Installer im stillen Modus aus.
  - Windows-Portablepaket: `daily-stock-analysis-windows-noinstall-<tag>.zip`
  - macOS Intel: `daily-stock-analysis-macos-x64-<tag>.dmg`
  - macOS Apple Silicon: `daily-stock-analysis-macos-arm64-<tag>.dmg`

### macOS meldet „Anwendung ist beschädigt und kann nicht geöffnet werden"

Das aktuelle macOS-DMG ist noch nicht mit einem Apple-Developer-Zertifikat signiert und notarisiert. Die Build-Konfiguration erzeugt explizit eine unsigned App, bereinigt vor der ersten Ausführung des PyInstaller-Artefakts eine unvollständige Signatur und entfernt sie über den electron-builder `afterPack`-Hook vor der DMG-Erstellung erneut aus der kompletten `.app`; die CI prüft zusätzlich die originale Electron-`.app` sowie die nach dem DMG-Mount erzeugte `.app`, um eine erneute Veröffentlichung von Artefakten mit beschädigter Signatur wie `code has no resources but signature indicates they must be present` zu verhindern. Diese Behandlung kann nur die unvollständige Signatur aus v3.27.0 abschwächen, **verleiht der Anwendung aber kein Vertrauen von Apple**. Nach dem Download über den Browser kann macOS Gatekeeper weiterhin „Der Entwickler kann nicht verifiziert werden" melden, den Start blockieren oder eine manuelle Bestätigung des Benutzers verlangen.

Bitte prüfen Sie in der folgenden Reihenfolge:

1. Laden Sie die Anhänge nur von den offiziellen [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) des Projekts herunter und prüfen Sie, dass die Installationsarchitektur zum Mac passt: Apple-Chips (M1/M2/M3/M4 usw.) verwenden `daily-stock-analysis-macos-arm64-<tag>.dmg`, Intel-Chips `daily-stock-analysis-macos-x64-<tag>.dmg`. Umgehen Sie Gatekeeper nicht bei Installationsprogrammen von Dritten oder unbekannter Herkunft.
2. Öffnen Sie das DMG, ziehen Sie `Daily Stock Analysis` in den „Programme"-Ordner und starten Sie es einmal. Wird es blockiert, gehen Sie zu „Systemeinstellungen -> Datenschutz & Sicherheit", bestätigen Sie den Anwendungsnamen an der Sicherheitsmeldung und klicken Sie dann auf „Trotzdem öffnen" und bestätigen Sie gemäß der Systemmeldung erneut. Bei älteren macOS-Versionen lautet der entsprechende Einstieg „Systemeinstellungen -> Sicherheit -> Allgemein".
3. Nur wenn das Installationsprogramm nachweislich aus dem obigen offiziellen Release stammt und „Trotzdem öffnen" weiterhin nicht weiterhilft, öffnen Sie „Terminal", entfernen das Download-Isolationsattribut der Anwendung und starten sie erneut:

```bash
xattr -dr com.apple.quarantine "/Applications/Daily Stock Analysis.app"
```

Falls die App nicht in `/Applications` liegt, ersetzen Sie den Pfad im Befehl durch den tatsächlichen `.app`-Pfad. Führen Sie `xattr` nicht auf dem gesamten „Programme"-Ordner aus und auch nicht bei Anwendungen unbekannter Herkunft. Unterschiedliche macOS-Versionen können unsigned Anwendungen weiterhin ablehnen; das Entfernen der quarantine-Garantie bedeutet nicht, dass sie dadurch freigegeben wird. Um die Meldung dauerhaft zu beseitigen, muss die Apple-Developer-Signierung und Notarisierung (notarization) in den Release-Prozess eingebunden werden; das gehört nicht zu den obigen vorübergehenden Freigabeschritten.

Wartende können mit folgenden Befehlen zwischen „erwarteter unsigned Ablehnung" und „nicht veröffentlichbarer unvollständiger Signatur" unterscheiden:

```bash
codesign -d "/Applications/Daily Stock Analysis.app"
spctl --assess --type execute --verbose=4 "/Applications/Daily Stock Analysis.app"
```

Bei den aktuellen unsigned Artefakten enthält `codesign -d` erwartungsgemäß `code object is not signed at all`, und `spctl` lehnt erwartungsgemäß ab; wenn die Ausgabe `code has no resources but signature indicates they must be present` oder eine andere Signaturbeschädigung zeigt, sollte dies als Release-Blockade gewertet werden.

Empfohlener Release-Prozess:

1. Code in `main` zusammenführen
2. Version über den automatischen Tag-Workflow erzeugen (oder Tag manuell erstellen)
3. Der `desktop-release`-Workflow baut automatisch und hängt die Installationsprogramme beider Plattformen an die entsprechende GitHub Release an

## Reproduzierbare Verifikation vor dem Release (Desktop-Updatekette)

Die Auto-Updatekette der Desktop-Version hängt vom Windows-NSIS-Installationsartefakt sowie den Metadaten `latest.yml` und `*.blockmap` ab. Die aktuelle Desktop-CI deckt den veröffentlichbaren Pfad der `desktop-release`-Paketartefakte nicht ab. Vor dem Commit werden folgende lokale Verifikationen empfohlen:

Hinweis: Diese Checkliste konzentriert sich auf die Windows-NSIS-Installationsversion und die Release-Metadaten von `electron-updater`. Die aktuelle Linux-Umgebung kann Windows-Installationsprogramme und Updater-Metadaten (`latest.yml` / `*.blockmap`) nicht direkt erzeugen; solche Ketten müssen in der Windows-Release-Umgebung (Release-Executor) oder auf einem Windows-Rechner nachgeprüft werden.

Falls die obige Verifikation in einer Nicht-Windows-Umgebung nicht abgeschlossen werden kann, geben Sie bitte in den PR-Abnahmehinweisen explizit den verantwortlichen Prüfer der Windows-Releasekette, das Prüfzeitfenster sowie das Prüfergebnis der `desktop-release`-Artefakte an (Konsistenz und Herunterladbarkeit von Release/tag sowie `daily-stock-analysis-windows-installer-<tag>.exe`, `latest.yml`, `*.blockmap`).

1. Zuerst die statischen Web-Artefakte bauen (Einstiegspunkte für Desktop-Hauptfenster und Einstellungsseite)

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

2. Zurück zur Desktop-Version, Abhängigkeiten vervollständigen, Preload-Unit-Tests ausführen und dann Electron-Paket bauen

```bash
cd ../dsa-desktop
npm ci
npm test
npm run build
```

In der Windows-Release-Prüfumgebung kann zusätzlich ausgeführt werden:

```powershell
./scripts/verify-desktop-updater-artifacts.ps1 -ReleaseTag v$(node -p "require('./apps/dsa-desktop/package.json').version")
```

> Falls die aktuelle Ausführungsumgebung keine Windows-NSIS-Installer erzeugen kann, geben Sie bitte in den Übergabe-Hinweisen die Plattformbeschränkung ausdrücklich an und verlangen Sie, dass der zuständige Prüfer der Windows-Releasekette diese Verifikation nachholt.

3. Prüfen, ob die Update-Metadaten erzeugt wurden

```bash
ls -1 dist | sort
ls -1 dist/*.yml dist/*.blockmap 2>/dev/null || true
```

4. Version und Release-Anhänge zwangsweise angleichen (kann in der Windows-Umgebung oder auf einem Executor, der NSIS-Artefakte erzeugen kann, nachgeprüft werden)

```bash
RELEASE_TAG="v$(node -p \"require('./package.json').version\")"
REPO="ZhuLinsen/daily_stock_analysis"

for f in dist/*latest.yml dist/*.blockmap dist/daily-stock-analysis-windows-installer-*.exe; do
  [ -f \"$f\" ] && echo \"[FOUND] $f\"
done

if [ -f dist/latest.yml ]; then
  echo \"---- Version-Auszug aus latest.yml ----\"
  grep -E \"^version:|^files:|^sha512:\" dist/latest.yml
fi

echo \"---- Release-Liste (manuell abzugleichen) ----\"
echo \"Release Tag: $RELEASE_TAG\"
echo \"Release-Adresse: https://github.com/$REPO/releases/tag/$RELEASE_TAG\"
echo \"Zu prüfende Anhänge:\"
echo \"- daily-stock-analysis-windows-installer-*.exe\"
echo \"- latest.yml\"
echo \"- *.blockmap\"
echo \"Außerdem prüfen, dass die Semver-Version in latest.yml mit dem Tag übereinstimmt und path/url mit dem Anhangnamen des Installationsprogramms übereinstimmt\"
```

5a. Empfohlene „nachprüfbare Ausgaben" für die PR-Beschreibung (Windows):

```bash
echo "release-tag=${RELEASE_TAG}"
echo "latest.yml version:"
grep -E "^version:" dist/latest.yml
echo "latest.yml files:"
sed -n '1,80p' dist/latest.yml
echo "packaging artifacts:"
ls -1 dist/*.yml dist/*.blockmap dist/*installer*.exe 2>/dev/null | sort
```

Prüfliste der Windows-Releasekette (nach dem PR vom Release-Team/Wartenden ausgeführt):

- Version von release/tag und `daily-stock-analysis-windows-installer-<tag>.exe` stimmen überein;
- `latest.yml`, `daily-stock-analysis-windows-installer-<tag>.exe` und `*.blockmap` erscheinen zum selben Tag synchron und sind herunterladbar;
- `version` in `latest.yml` ist semantisch mit dem Release-Tag konsistent (Vergleich nach Entfernen des `v`-Präfixes), und `path` / `files.url` stimmen mit dem Anhangnamen des Installationsprogramms überein;
- Fehlen die oben genannten Dateien oder stimmt `release-tag` nicht überein, muss dies als Blockade markiert und der `desktop-release`-Verpackungsprozess nachgeholt werden.

5. Die Konsistenz zwischen Windows/NSIS-Artefakten und Release-Anhängen bitte manuell in einer Windows-Umgebung prüfen (der Release-Prozess kann manuell ausgelöst werden) und nach dem Upgrade den Verbleib der Laufzeitdateien überprüfen:

   1. Vor und nach der Installation jeweils die SHA256 von `.env`, `data/stock_analysis.db`, `data/stock_analysis.db-wal`, `data/stock_analysis.db-shm` und `logs/desktop.log` im Installationsverzeichnis erfassen;
   2. Nach dem nächsten Start der Desktop-Version prüfen, dass die oben genannten Dateien weiterhin existieren und mit der Aufzeichnung vor der Installation übereinstimmen;
   3. Bei Abweichung kann nach dem Beenden der Anwendung geprüft werden, ob `.dsa-desktop-update-backup` im Benutzerdatenverzeichnis vollständig bereinigt wurde, und anhand der neuesten Logs zusammenhängend nachvollzogen werden.

Unter Windows wird die Ausführung mit PowerShell empfohlen:

```bash
Get-FileHash .env,data\\stock_analysis.db,data\\stock_analysis.db-wal,data\\stock_analysis.db-shm,logs\\desktop.log -Algorithm SHA256
```

Hinweis: Vor „Neu starten und installieren" in der Windows-NSIS-Installationsversion stoppt die Anwendung das eingebaute Backend, sichert die obigen Laufzeitdateien neben dem Installationsverzeichnis und führt den Update-Installer im stillen Modus aus. Ziel ist es, zu vermeiden, dass der Installationsassistent den noch laufenden Desktop-Prozess vorzeitig überschreibt, und gleichzeitig das Risiko von Dateiverlust während des Updates zu senken; schlägt die Wiederherstellung fehl, zeigt die Desktop-Version einen Update-Installationsfehler an und behält einen manuellen Download-Pfad für den Rückfall bei. Diese Korrektur betrifft nur die Windows-Update-Installationskette und die Behandlung des Prozesslebenszyklus des eingebauten Backends; sie berührt weder die Speichersemantik der Einstellungen noch die Laufzeit-Bereinigungsstrategie des Modells noch das Konfigurationsmigrationsverhalten.

### Schrittweises Verpacken

1) React UI bauen

```bash
cd apps/dsa-web
npm install
npm run build
```

2) Python-Backend nach dem bestehenden Skript verpacken (das Skript sammelt die eingebaute DSA-Aktienauswahl-Engine, das Futu SDK und die AkShare-Datendateien)

- Windows:

```bash
powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1
```

- macOS:

```bash
bash scripts/build-backend-macos.sh
```

Das Skript führt nach der Installation der Abhängigkeiten `--collect-all src.services.screening`, `--collect-all futu` und `--collect-data akshare` aus. Nach dem Build wird über die eingefrorene ausführbare Datei geprüft, dass `src.services.screening.pipeline`, `futu` und `orjson` importierbar sind, die Anzahl der eingebauten Strategien abgeglichen und bestätigt, dass `file_fold/calendar.json` von AkShare in das eingefrorene Artefakt gelangt ist. So wird vermieden, dass das Release-Paket in den Pfaden Aktienauswahl, Hot-Topics, Futu-Positionsimport oder Tageslinien-Anreicherung wegen fehlender Module/package data degradiert. Die eingebaute Aktienauswahl-Implementierung orientiert sich an AlphaSift. Bei Änderungen an `requirements.txt`, dem Futu-Broker, dem Desktop-Verpackungseinstieg oder den zugehörigen Workflows führt die PR-Haupt-CI jeweils die Blockade-Prüfungen `desktop-futu-package-windows` und `desktop-futu-package-macos` aus.

3) Electron-Desktop-Anwendung verpacken

```bash
cd apps/dsa-desktop
npm install
npm run build
```

Die Verpackungsartefakte liegen unter `apps/dsa-desktop/dist/`. Der Windows-Installer erzeugt `daily-stock-analysis-windows-installer-<tag>.exe`; im Installationsassistenten kann das Installationsverzeichnis gewählt werden.

## Verzeichnisstruktur

Im Windows-Installationsmodus unterstützt der Installer nur die Installation für den aktuellen Benutzer und deaktiviert die Admin-Erhöhung; der Benutzer kann das Installationsverzeichnis im Assistenten wählen; der Installer verhindert auf Installer-Ebene die Auswahl von geschützten Systemverzeichnissen wie `Program Files` oder `Windows` (bei Auswahl wird „Weiter" automatisch deaktiviert). Nach der Installation erzeugt bzw. liest die Anwendung neben dem Installationsverzeichnis `.env`, `data/stock_analysis.db` (inklusive `data/stock_analysis.db-wal` / `data/stock_analysis.db-shm`) und `logs/desktop.log`. Bitte behalten Sie den Standard-Pfad per-user bei oder wählen Sie ein anderes vom Benutzer beschreibbares Verzeichnis.

Im `win-unpacked`-Modus ohne Installation sieht die Verzeichnisstruktur so aus:

```
win-unpacked/
  Daily Stock Analysis.exe    <- Doppelklick zum Starten
  .env                        <- Benutzerkonfigurationsdatei (beim ersten Start automatisch erzeugt)
  data/
    stock_analysis.db         <- Hauptdatenbankdatei
    stock_analysis.db-wal     <- WAL-Protokolldatei (Update-Backup/Wiederherstellung)
    stock_analysis.db-shm     <- WAL-Shared-Meta-Datei (Update-Backup/Wiederherstellung)
  logs/
    desktop.log               <- Laufzeitprotokoll
  resources/
    .env.example              <- Konfigurationsvorlage
    backend/
      stock_analysis.exe      <- Backend-Dienst
```

## Hinweise zur Konfigurationsdatei

- Die `.env` der Windows-Desktop-Version liegt im selben Verzeichnis wie die exe
- Bei der macOS-Paketversion liegen `.env`, `data/` und `logs/` im Electron-Benutzerdatenverzeichnis, um einen Verlust beim Ersetzen der `.app` zu vermeiden
- Beim ersten Start wird automatisch aus `.env.example` eine Kopie erzeugt
- Beim Upgrade von einer alten Version migriert die neue Version, wenn die `.env`, `data/stock_analysis.db` oder die Logdateien im alten `.app`-Paket noch zugänglich sind, diese automatisch in das Benutzerdatenverzeichnis, sofern die Zieldateien nicht existieren; vorhandene Zieldateien werden nicht überschrieben
- Der Benutzer muss in `.env` Folgendes konfigurieren:
  - `GEMINI_API_KEY` oder `OPENAI_API_KEY`: für die KI-Analyse erforderlich
  - `STOCK_LIST`: Watchlist-Liste (kommasepariert)
  - Weitere optionale Konfigurationen siehe `.env.example`

### Konfigurations-Backup / Wiederherstellung `.env`

- Sowohl WebUI als auch Desktop können unter `Systemeinstellungen -> Konfigurations-Backup` die Schaltflächen `Export .env` und `Import .env` sehen
- Die WebUI benötigt im Nicht-Desktop-Betrieb zuerst die Aktivierung der Administrator-Authentifizierung und einen Login; ohne Authentifizierung sind die Schaltflächen deaktiviert und die API gibt `403` zurück
- `Export .env` exportiert die aktuell **gespeicherte** `.env`-Backupdatei; lokal vorhandene Entwürfe, bei denen auf der Seite noch nicht „Konfiguration speichern" geklickt wurde, werden nicht exportiert
- `Import .env` liest die Schlüssel-Wert-Paare der Backupdatei und führt sie in die aktuelle Konfiguration zusammen; nach dem Import wird sofort ein Konfigurations-Reload ausgelöst
- Der Import ist eine „Schlüssel-Ebene-Überschreibung" und kein kompletter Dateiaustausch: Schlüssel, die in der Backupdatei vorkommen, überschreiben den aktuellen Wert; Schlüssel, die nicht vorkommen, bleiben unverändert
- Wenn auf der aktuellen Seite noch nicht gespeicherte Entwürfe vorhanden sind, wird vor dem Import eine Bestätigung angezeigt, um lokale Entwürfe und gespeicherte Konfiguration nicht zu vermischen
- Wenn die Webseite standardmäßig `ADMIN_AUTH_ENABLED=false` hat, zeigt die Einstellungsseite die Schaltflächen deaktiviert an und weist darauf hin, zuerst die Admin-Authentifizierung zu aktivieren; die Desktop-Version ist von dieser Konfiguration nicht betroffen und kann das Konfigurations-Backup/die Wiederherstellung weiterhin direkt nutzen.

> Empfehlung: macOS-Benutzer, die von einer alten Version upgraden, können vor dem Upgrade einmal `Export .env` als Sicherung ausführen; wenn die alte `.app` bereits vollständig ersetzt wurde, können die alten Dateien im Paket nicht aus dem Nichts wiederhergestellt werden, sondern nur über den Backup-Import.

### Versionsinformationen auf der Einstellungsseite

- „Desktop-Version" unter `Systemeinstellungen -> Versionsinformationen` wird von `app.getVersion()` des Electron-Hauptprozesses bereitgestellt und über die Preload-Bridge an das Frontend durchgereicht
- Der Entwicklungsmodus `npm run dev` und der Verpackungsmodus `npm run build` / das Installationsprogramm nutzen beide dieselbe Versions-Injektionskette; in `preload.js` wird keine separate, fest verdrahtete Versionsnummer mehr gepflegt
- `README.md` behält weiterhin die Einstiegs-Hinweise zu Installation und Ausführung; solche Laufzeitdetails der Desktop-Version werden einheitlich in diesem Fachdokument gepflegt, damit das Einsteigerdokument nicht aufbläht

### Zugriff auf die Windows-Desktop-WebUI im LAN

- Die Desktop-Version erlaubt standardmäßig weiterhin über `WEBUI_HOST=127.0.0.1` nur den Zugriff vom lokalen Rechner, um eine unbeabsichtigte Freigabe des Backend-Dienstes nach der Installation zu vermeiden
- Um anderen Geräten im selben LAN Zugriff zu ermöglichen, setzen Sie in der `.env` der Desktop-Version oder unter `Systemeinstellungen -> WebUI-Listenadresse` `WEBUI_HOST=0.0.0.0` und starten Sie die Desktop-Version nach dem Speichern neu
- Die Desktop-Version wählt automatisch einen freien Port aus `8000-8100` und übergibt ihn an das Backend; im Normalfall ist es weiterhin `8000`. Ist der Port belegt, kann in `logs/desktop.log` nach `Using port ...` und `Backend launch command=...` gesucht werden
- Die Windows-Firewall oder die Security-Group des Servers muss den tatsächlich lauschenden Port noch freigeben; vor einer externen Freigabe wird empfohlen, zusätzlich `ADMIN_AUTH_ENABLED` zu aktivieren
- Selbst wenn das Backend an `0.0.0.0` bindet, verwendet das Desktop-Fenster für die Health-Checks und das Laden der Seite weiterhin eine lokal erreichbare Adresse

### Update-Hinweis der Desktop-Version

- Nach dem Laden der Hauptoberfläche prüft die Anwendung im Hintergrund die neueste offizielle Version der GitHub Releases und vergleicht sie per semantischer Version mit der aktuellen `app.getVersion()`
- Die Windows-NSIS-Installationsversion lädt die neue Version automatisch über die eingebaute GitHub-Updatequelle herunter; nach dem Download erscheint eine einmalige Benachrichtigung; nach Bestätigung durch den Benutzer wird still neu gestartet und installiert
- Die stille Installation des automatischen Updates nutzt das aktuelle Installationsverzeichnis erneut; hat der Benutzer bei der Installation ein Nicht-Standardverzeichnis oder ein Verzeichnis mit Leerzeichen gewählt, wird beim späteren automatischen Update weiterhin dasselbe Verzeichnis überschrieben
- Im Bereich „Desktop-Update" unter `Systemeinstellungen -> Versionsinformationen` kann manuell nach Updates gesucht werden; ist ein Update bereits heruntergeladen, wird die Aktion „Neu starten und installieren" angezeigt
- Das Windows-Portablepaket, der Entwicklungsmodus und das macOS-DMG behalten weiterhin den kompatiblen Pfad „Benachrichtigung + Sprung zur Downloadseite" bei; ein Netzwerkfehler blockiert den Start der Desktop-Version nicht
- Fehler bei der Versionsprüfung, GitHub-API-Timeout, fehlende Update-Metadaten oder Anomalien beim Download/der Installation werden in `logs/desktop.log` protokolliert; bei der manuellen Prüfung auf der Einstellungsseite wird ein Fehlerstatus angezeigt

## Häufige Probleme

### Nach dem Start bleibt „Preparing backend..." dauerhaft sichtbar

1. `logs/desktop.log` auf Fehlermeldungen prüfen
2. Sicherstellen, dass die `.env` existiert und korrekt konfiguriert ist
3. Sicherstellen, dass die Ports 8000-8100 nicht belegt sind; die Desktop-Version wählt automatisch einen dieser freien Ports, ein manuelles Ändern von `WEBUI_PORT` über die `.env` ist nicht nötig
4. Zeigt das Log an, dass der von Electron erwartete Port und der tatsächlich vom Backend lauschende Port nicht übereinstimmen, sollte vorrangig auf eine Version mit der Port-Synchronisationskorrektur der Desktop-Version aktualisiert werden

### Backend meldet beim Start ModuleNotFoundError

Beim Verpacken mit PyInstaller fehlte ein Modul. Es müssen in den Backend-Build-Skripten für Windows und macOS synchron `--hidden-import`-Einträge ergänzt und die eingefrorenen Artefakte einer Laufzeit-Importprüfung unterzogen werden. Die aktuellen Skripte installieren, frieren ein und prüfen explizit das für den LiteLLM-Laufzeitpfad benötigte `orjson`; enthält das Log `No module named 'orjson'`, bitte auf eine korrigierte Version upgraden und neu bauen – Abhängigkeiten dürfen nicht nur manuell in das bereits veröffentlichte Verzeichnis installiert werden.

Meldet das Log, dass `akshare/file_fold/calendar.json` fehlt, bedeutet das, dass das eingefrorene Backend-Artefakt die AkShare package data nicht vollständig eingesammelt hat. Bitte mit den aktuellen `scripts/build-backend.ps1` oder `scripts/build-backend-macos.sh` neu bauen; das Skript prüft diese Datei, bevor der Desktop-Pfad erzeugt wird, und bricht bei fehlender Datei direkt ab.

### UI lädt eine leere Seite

Sicherstellen, dass `static/index.html` existiert; falls nicht, muss die React UI neu gebaut werden.

### Konfigurationsmigration nach macOS-Upgrade

Alte Versionen schrieben die Laufzeit-`.env`, die Datenbank und Logs in das `.app`-Paket. Die neue Version nutzt stattdessen das Electron-Benutzerdatenverzeichnis und führt eine einmalige Migration durch, solange die Dateien im alten `.app`-Paket noch zugänglich sind. Die Migrationsregel lautet „nur kopieren, wenn das Ziel nicht existiert", um die in der neuen Version bereits gespeicherte Konfiguration nicht zu überschreiben.

Wurde die alte `.app` bereits vollständig ersetzt, kann die `.env` im alten Paket von der neuen Version nicht automatisch wiederhergestellt werden. In diesem Fall kann die vor dem Upgrade exportierte `.env` unter `Systemeinstellungen -> Konfigurations-Backup` manuell importiert werden; nach einer abgeschlossenen Migration oder Neukonfiguration nutzen spätere Versionen weiterhin das Benutzerdatenverzeichnis und gehen beim Ersetzen der `.app` nicht mehr verloren.

## Verteilung an Benutzer

Die Windows-Verteilung hat jetzt zwei Varianten:

1. Installationsprogramm: `daily-stock-analysis-windows-installer-<tag>.exe` unter `apps/dsa-desktop/dist/` verteilen; der Benutzer kann beim Installieren das Zielverzeichnis selbst wählen
2. Portable Variante: den gesamten Ordner `apps/dsa-desktop/dist/win-unpacked/` an den Benutzer verteilen

Bei der `win-unpacked`-Portable-Variante muss der Benutzer nur:

1. Den Ordner entpacken
2. In `.env` den API Key und die Aktienliste konfigurieren
3. Per Doppelklick auf `Daily Stock Analysis.exe` starten
