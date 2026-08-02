# Leitfaden für den Web-Zugriff auf dem Cloud-Server

Wenn Sie das Projekt bereits auf einem Cloud-Server bereitgestellt haben, aber nicht wissen, welche Adresse Sie im Browser eingeben müssen, um das Web-Verwaltungsinterface zu öffnen, dann ist dieses Tutorial genau für Sie.

> Eigentlich sind es nur zwei Schritte: Den Dienst im externen Netz lauschen lassen und dann die Adresse im Browser eingeben.

---

## Inhaltsverzeichnis

- [Methode 1: Direkte Bereitstellung (pip + python)](#methode-1-direkte-bereitstellung-pip--python)
- [Methode 2: Docker Compose](#methode-2-docker-compose)
- [Öffnen der Oberfläche im Browser](#öffnen-der-oberfläche-im-browser)
- [Bestätigen, dass der Docker-Rebuild wirksam ist](#bestätigen-dass-der-docker-rebuild-wirksam-ist)
- [Zugriff nicht möglich? Diese Punkte zuerst prüfen](#zugriff-nicht-möglich-diese-punkte-zuerst-prüfen)
- [Optional: Nginx-Reverse-Proxy (Domain / Port 80 binden)](#optional-nginx-reverse-proxy-domain--port-80-binden)
- [Sicherheitsempfehlungen](#sicherheitsempfehlungen)

---

## Methode 1: Direkte Bereitstellung (pip + python)

### Schritt 1: Die Listenadresse in .env ändern

Öffnen Sie `.env` mit einem Editor (im Projektverzeichnis, also in dem Verzeichnis, das `main.py` enthält) und suchen Sie diese Zeile:

```env
WEBUI_HOST=127.0.0.1
```

Ändern Sie `127.0.0.1` in `0.0.0.0`:

```env
WEBUI_HOST=0.0.0.0
```

> `127.0.0.1` bedeutet, dass nur der eigene Rechner zugreifen kann, `0.0.0.0` bedeutet, dass Zugriffe von beliebigen Quellen erlaubt sind. Auf dem Cloud-Server muss `WEBUI_HOST` in `.env` auf `0.0.0.0` geändert werden – oder Sie übergeben im Startbefehl explizit `--host 0.0.0.0` –, damit das Interface von außen geöffnet werden kann.

### Schritt 2: Dienst starten

Im Projektverzeichnis ausführen:

```bash
# Nur das Web-Interface starten (ohne automatische Analyse)
python main.py --webui-only

# Oder: Web-Interface starten (beim Start einmalig analysieren; für die tägliche geplante Analyse --schedule hinzufügen oder SCHEDULE_ENABLED=true setzen)
python main.py --webui
```

Nach erfolgreichem Start gibt das Terminal etwas Ähnliches aus:

```
FastAPI 服务已启动: http://0.0.0.0:8000
```

Wenn Sie möchten, dass der Dienst nach dem Schließen des Terminals weiterläuft, können Sie `nohup` verwenden:

```bash
nohup python main.py --webui-only > /dev/null 2>&1 &
```

> Die Logdateien werden vom Programm automatisch in das Verzeichnis `logs/` geschrieben. Ansehen können Sie sie mit `tail -f logs/stock_analysis_*.log`.

### Port ändern (optional)

Der Standardport ist 8000. Wenn Sie einen anderen Port verwenden möchten, setzen Sie ihn in `.env`:

```env
WEBUI_PORT=8888
```

Anschließend den Dienst neu starten.

---

## Methode 2: Docker Compose

### Schritt 1: Sicherstellen, dass die .env-Konfiguration vorhanden ist

Das Projekt `docker/docker-compose.yml` setzt innerhalb des Containers bereits automatisch `WEBUI_HOST=0.0.0.0`. Sie müssen die Listenadresse in `.env` nicht mehr ändern – Docker übernimmt das automatisch.

`env_file: ../.env` in Docker Compose injiziert `.env` lediglich als **Startumgebungsvariablen** in den Container. Es erzeugt kein `/app/.env` im Container und führt auch nicht dazu, dass die WebUI beim Speichern der Konfiguration in die `.env` des Hosts zurückschreibt. Die neue WebUI zeigt, wenn der aktiven `.env` bestimmte Schlüssel fehlen, die beim Start injizierten gleichnamigen Umgebungsvariablen als Fallback an – daher sind auf der Seite die beim Docker-Start injizierten Konfigurationen sichtbar; „Export .env" exportiert aber weiterhin nur den Inhalt der aktuell aktiven Konfigurationsdatei.

Wenn die in der WebUI gespeicherten Konfigurationen auch nach dem Löschen, Neubau oder Upgrade des Containers erhalten bleiben sollen, legen Sie die aktive Konfigurationsdatei in ein eingehängtes Datenvolumen, z. B. indem Sie in `environment` der Compose-Datei ergänzen:

```yaml
- ENV_FILE=/app/data/runtime.env
```

Gleichzeitig die Mount-Konfiguration `../data:/app/data` beibehalten. Hinweis: Wenn im `../.env` beim Start, in `docker run -e` oder im `environment:`-Block der Compose-Datei noch gleichnamige alte Werte stehen, können diese Startumgebungsvariablen nach einem Container-Neustart die in der Laufzeitdatei gespeicherten Werte weiterhin überschreiben. Damit die in der WebUI gespeicherten Werte übernehmen, bitte die gleichnamigen Konfigurationen in der Startumgebung synchron aktualisieren oder entfernen.

### Schritt 2: Dienst starten

Im Projektverzeichnis ausführen:

```bash
# Gleichzeitig geplante Analyse + Web-Interface starten (empfohlen)
docker-compose -f ./docker/docker-compose.yml up -d

# Oder nur den Web-Interface-Dienst starten
docker-compose -f ./docker/docker-compose.yml up -d server
```

Nach dem Start den Status ansehen:

```bash
docker-compose -f ./docker/docker-compose.yml ps
```

Wenn der Status des `server`-Dienstes `running` ist, läuft das Web-Interface bereits.

### Port ändern (optional)

Der Standardport ist 8000. Wenn Sie einen anderen Port verwenden möchten, setzen Sie ihn in `.env`:

```env
API_PORT=8888
```

Anschließend die Container neu starten:

```bash
docker-compose -f ./docker/docker-compose.yml down
docker-compose -f ./docker/docker-compose.yml up -d
```

---

## Öffnen der Oberfläche im Browser

Nach dem Start des Dienstes geben Sie in die Adresszeile des Browsers ein:

```
http://ÖFFENTLICHE_IP_DEINES_SERVERS:8000
```

Ist Ihre Server-IP zum Beispiel `1.2.3.4`, geben Sie ein:

```
http://1.2.3.4:8000
```

Wenn Ihre Domain bereits auf diesen Server aufgelöst ist, können Sie auch direkt über die Domain zugreifen:

```
http://your-domain.com:8000
```

> **Wo finde ich die öffentliche IP?** Melden Sie sich in der Konsole Ihres Cloud-Servers an (Alibaba Cloud/Tencent Cloud/AWS usw.). In der Instanzliste finden Sie die „öffentliche IP" oder „elastische IP".

---

## Bestätigen, dass der Docker-Rebuild wirksam ist

Zuerst zwei Dinge unterscheiden:

1. **Veröffentlichte Docker-Image-Version**: Ansehen des Image-Tags, das Sie beim Deployment verwendet haben, z. B. `ghcr.io/zhulinsen/daily_stock_analysis:v3.12.0`. Die Docker-Veröffentlichung des Repositorys wird von `.github/workflows/docker-publish.yml` anhand des Git-Tags `v*.*.*` ausgelöst, daher sollte die Docker-Version anhand des Image-Tags / der GitHub Releases bestimmt werden.
2. **Frontend-Build, den die aktuelle Seite lädt**: Ansehen der Versionsinformationskarte auf der Seite „Systemeinstellungen" der WebUI, um zu prüfen, ob die statischen Ressourcen im Browser bereits aktualisiert sind.

Das heißt: **Die Versionsinformationen unter „Systemeinstellungen" eignen sich besser dafür, festzustellen, ob das Frontend erfolgreich neu gebaut wurde; sie sind nicht gleichbedeutend mit der veröffentlichten Docker-Image-Version.**

Die WebUI zeigt jetzt auf der Seite „Systemeinstellungen" eine schreibgeschützte Karte „Versionsinformationen" mit:

- `WebUI-Version`
- `Codeversion`
- `Buildzeit`

Offizielle Docker-/Desktop-Veröffentlichungen injizieren das Release-Tag als `WebUI-Version` und zeigen den zugehörigen Commit als `Codeversion`. Beim direkten Build aus einem Git-Clone verwendet die WebUI `git describe` und den aktuellen Commit; hat die Build-Umgebung weder Release-Informationen noch Git-Metadaten, wird die Version eindeutig als `development` angezeigt und die Buildzeit gibt nicht mehr fälschlich eine Release-Version vor.

Nachdem Sie `docker-compose -f ./docker/docker-compose.yml up -d --build` erneut ausgeführt oder den Frontend-Build `npm run build` separat wiederholt haben, können Sie den Browser aktualisieren und zu „Systemeinstellungen" gehen, um zu prüfen, ob sich `Codeversion` und `Buildzeit` geändert haben; beide zusammen bestätigen, von welchem Code und Build die aktuell im Browser geladenen statischen Ressourcen stammen.

Wenn Sie prüfen möchten, „welche offizielle Version ich gerade bereitgestellt habe", bevorzugen Sie folgende Methoden:

```yaml
# Methode 1: image tag in docker-compose / im Deployment-Skript ansehen
image: ghcr.io/zhulinsen/daily_stock_analysis:v3.12.0
```

```bash
# Methode 2: Den Pull-Befehl nachsehen
docker pull ghcr.io/zhulinsen/daily_stock_analysis:v3.12.0
```

Wenn Sie ständig `latest` verwenden, empfiehlt es sich, auf ein explizites Versionstag umzusteigen; sonst ist es schwer, allein anhand der Seiteninformationen im Container festzustellen, ob bereits wiederholt auf dieselbe Version aktualisiert wurde.

Beim Prüfen der lokalen Frontend-Verpackungskette wird empfohlen, folgende Befehle als minimalen Verifikationsschritt auszuführen:

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

Nach erfolgreichem `build` enthalten die unter `static` erzeugten `index.html`/JS/CSS-Ressourcen die aktuelle Version, den Commit und die Buildzeit und erzeugen `build-info.json`. Beim Start wird der Quellcode-Hash dieser Datei verglichen – selbst wenn `rsync -a` alte Zeitstempel beibehalten hat, kann so eine Diskrepanz zwischen Quellcode und statischen Artefakten erkannt und neu gebaut werden. Nach dem Aktualisieren sollte eine Änderung in der Karte „Versionsinformationen" sichtbar sein.

---

## Zugriff nicht möglich? Diese Punkte zuerst prüfen

### 1. Sicherheitsgruppe / Firewall lässt den Port nicht durch

Das ist die häufigste Ursache. Cloud-Server öffnen standardmäßig nur den Port 22 (SSH). Port 8000 (oder den geänderten Port) muss manuell freigegeben werden.

**Vorgehen** (am Beispiel Alibaba Cloud):
1. In der Alibaba-Cloud-Konsole anmelden -> Cloud Server ECS -> Ihre Instanz finden
2. „Sicherheitsgruppe" -> „Regeln konfigurieren" -> „Sicherheitsgruppenregel hinzufügen" klicken
3. Richtung „Eingehend" wählen, Portbereich `8000/8000` eintragen, Zugriffsobjekt `0.0.0.0/0`, dann „Bestimmen" klicken

Bei Tencent Cloud, AWS und anderen Anbietern funktioniert es ähnlich: „Sicherheitsgruppe" oder „Firewall-Regel" finden und eine neue Eingangsregel anlegen, die den TCP-Port 8000 erlaubt.

### 2. Die Systemfirewall des Servers blockiert

Wenn auf Ihrem System `ufw` oder `firewalld` aktiv ist, müssen Sie den Port ebenfalls freigeben:

```bash
# Ubuntu / Debian (ufw)
sudo ufw allow 8000

# CentOS / RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

### 3. Bei direkter Bereitstellung wurde WEBUI_HOST in .env nicht geändert

Das ist die zweithäufigste Ursache. In `.env` steht standardmäßig `WEBUI_HOST=127.0.0.1`. Damit lauscht der Dienst nur auf dem eigenen Rechner und ist von außen gar nicht erreichbar.

So ändern: `.env` öffnen, `WEBUI_HOST=127.0.0.1` in `WEBUI_HOST=0.0.0.0` ändern und den Dienst neu starten; alternativ kann im Startbefehl explizit `--host 0.0.0.0` ergänzt werden.

> Bei der Docker-Variante ist diese Änderung nicht nötig; dieser Schritt kann übersprungen werden.

### 4. Der Port stimmt nicht überein

Prüfen, ob der Port in der Zugriffsadresse mit dem in `.env` / im Startbefehl gesetzten Port übereinstimmt.

- Direkte Bereitstellung: Standard 8000, änderbar über `WEBUI_PORT=xxxx`
- Docker: Standard 8000, änderbar über `API_PORT=xxxx`

### 5. Die Seite öffnet, aber UI-Elemente erscheinen unnatürlich groß / das Layout ist zerstört

**Symptom**: Der Browser erreicht Port 8000, die Seite hat Inhalt, aber Text, Schaltflächen und Karten erscheinen unnatürlich groß, ohne korrektes Layout und Farbschema.

**Ursache**: `static/index.html` existiert, aber die CSS/JS-Ressourcen fehlen (`static/assets/` ist leer oder existiert nicht). Der Browser lädt das HTML-Gerüst, bekommt aber weder Styles noch Skripte und fällt auf ein nacktes HTML-Rendering zurück.

Prüfen Sie zunächst mit den Entwicklertools des Browsers (F12 -> Tab „Network"), ob es **404**-Fehler für `/assets/index-*.js` oder `/assets/index-*.css` gibt. Falls ja, beheben Sie das wie folgt:

**Docker-Benutzer**:

```bash
docker-compose -f ./docker/docker-compose.yml down
docker-compose -f ./docker/docker-compose.yml build --no-cache
docker-compose -f ./docker/docker-compose.yml up -d
```

Nach dem Rebuild mit `Ctrl+Shift+R` den Browser-Cache hart aktualisieren und die Seite erneut aufrufen.

**Benutzer der direkten Bereitstellung**: Zuerst sicherstellen, dass Node.js 18+ installiert ist (empfohlen 20+), dann das Frontend manuell bauen:

```bash
cd apps/dsa-web
npm ci
npm run build
cd ../..
python main.py --webui-only
```

---

## Optional: Nginx-Reverse-Proxy (Domain / Port 80 binden)

Wenn Sie eine Domain haben oder das `:8000` in der Adresse vermeiden möchten, können Sie Nginx als Reverse-Proxy verwenden und den Traffic der Ports 80/443 an den Backend-Dienst weiterleiten.

### Nginx installieren

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y nginx

# CentOS
sudo yum install -y nginx
```

### Beispiel einer Konfigurationsdatei

Neue Datei `/etc/nginx/conf.d/stock-analyzer.conf` anlegen, Inhalt wie folgt (ersetzen Sie `your-domain.com` durch Ihre Domain oder IP):

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 支持 WebSocket（Agent 对话页面需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Konfiguration aktivieren und Nginx neu laden

```bash
sudo nginx -t            # Prüfen, ob die Konfiguration Syntaxfehler hat
sudo systemctl reload nginx
```

Nach erfolgreicher Konfiguration erreichen Sie die Seite direkt über `http://your-domain.com` – ohne Portnummer.

> **Hinweise bei Verwendung von Nginx**:
> - Wenn Sie die Web-Login-Authentifizierung aktiviert haben (`ADMIN_AUTH_ENABLED=true`), empfiehlt es sich, zusätzlich `TRUST_X_FORWARDED_FOR=true` in `.env` zu aktivieren, da das System sonst die echte IP möglicherweise nicht korrekt erkennt. Diese Option gilt für Bereitstellungen mit **einer einzigen vertrauenswürdigen Reverse-Proxy-Ebene** (Nginx -> App); bei mehrstufigen Proxies oder CDN (CDN -> Nginx -> App) kann der Schlüssel für das Login-Rate-Limiting auf die Edge-Proxy-IP statt auf die echte Client-IP zurückfallen – bitte je nach tatsächlicher Topologie bewerten.
> - Für HTTPS können Sie mit [Certbot](https://certbot.eff.org/) automatisch ein kostenloses Let's-Encrypt-Zertifikat beantragen.

---

## Sicherheitsempfehlungen

Bevor Sie das Web-Interface öffentlich ins Internet legen, wird dringend empfohlen, den Passwortschutz zu aktivieren:

In `.env` setzen:

```env
ADMIN_AUTH_ENABLED=true
```

Nach dem Neustart des Dienstes werden Sie beim ersten Seitenbesuch aufgefordert, ein initiales Passwort festzulegen. Danach müssen Sie beim Öffnen der Einstellungsseite jedes Mal das Passwort eingeben. So wird verhindert, dass sensible Konfigurationen wie API Keys von anderen gesehen werden.

> Wenn Sie das Passwort vergessen haben, führen Sie auf dem Server aus: `python -m src.auth reset_password`

---

Haben Sie andere Probleme? Gerne ein [Issue einreichen](https://github.com/ZhuLinsen/daily_stock_analysis/issues).
