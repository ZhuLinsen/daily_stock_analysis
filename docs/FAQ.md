# ❓ Häufig gestellte Fragen (FAQ)

Dieses Dokument fasst häufig auftretende Probleme und ihre Lösungen bei der Nutzung zusammen.

---

## 📊 Datenbezogene Fragen

### Q1: Preise von US-Aktien (z. B. AMD, AAPL) werden bei der Analyse falsch angezeigt?

**Symptom**: Nach Eingabe eines US-Aktiencodes ist der angezeigte Preis deutlich falsch (z. B. zeigt AMD 7,33), oder der Code wird fälschlich als A-Aktie erkannt.

**Ursache**: Die Code-Matching-Logik früherer Versionen hat zuerst die Regeln für inländische A-Aktien versucht, was zu Code-Konflikten führte.

**Lösung**:
1. In v2.3.0 behoben; das System unterstützt jetzt die automatische Erkennung von US-Aktiencodes.
2. Falls das Problem weiterhin besteht, kann in `.env` gesetzt werden:
   ```bash
   YFINANCE_PRIORITY=0
   ```
   Dadurch wird der Yahoo-Finance-Datensource für US-Aktiendaten priorisiert.

> 📌 Zugehöriges Issue: [#153](https://github.com/ZhuLinsen/daily_stock_analysis/issues/153)

---

### Q2: Das Feld „Volumenverhältnis" im Bericht ist leer oder N/A?

**Symptom**: Im Analysebericht fehlen die Daten zum Volumenverhältnis, was die Beurteilung der Volumenveränderung durch die AI beeinträchtigt.

**Ursache**: Einige Standard-Echtzeitkursquellen (z. B. das Sina-Interface) liefern das Feld Volumenverhältnis nicht.

**Lösung**:
1. In v2.3.0 behoben; das Tencent-Interface unterstützt jetzt die Analyse des Volumenverhältnisses.
2. Empfohlene Priorität der Echtzeitkursquellen:
   ```bash
   REALTIME_SOURCE_PRIORITY=tencent,akshare_sina,efinance,akshare_em
   ```
3. Das System verfügt über eine integrierte Berechnung des 5-Tage-Durchschnittsvolumens als Fallback-Logik.

> 📌 Zugehöriges Issue: [#155](https://github.com/ZhuLinsen/daily_stock_analysis/issues/155)

---

### Q3: Tushare-Datenabruf schlägt fehl, Hinweis auf falsches Token?

**Symptom**: Das Log zeigt `Tushare-Datenabruf fehlgeschlagen: Token nicht korrekt, bitte bestätigen`

**Lösung**:
1. **Kein Tushare-Konto**: Keine Konfiguration von `TUSHARE_TOKEN` nötig; das System verwendet automatisch die kostenlosen Datensources (AkShare, Efinance).
2. **Mit Tushare-Konto**: Prüfe, ob das Token korrekt ist; einsehbar im persönlichen Bereich von [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ).
3. Alle Kernfunktionen dieses Projekts funktionieren auch ohne Tushare einwandfrei.

---

### Q4: Datenabruf wird limitiert oder gibt leere Werte zurück?

**Symptom**: Das Log zeigt „Circuit-Breaker ausgelöst" oder Daten geben `None` zurück, oder es treten `RemoteDisconnected`, geschlossene Verbindungen zu `push2his.eastmoney.com` usw. auf.

**Ursache**: Kostenlose Datensources (East Money, Sina usw.) verfügen über Anti-Scraping-Mechanismen; eine große Anzahl von Anfragen in kurzer Zeit wird limitiert.

**Lösung**:
1. Das System verfügt über eingebaute automatische Umschaltung mehrerer Datensources und Circuit-Breaker-Schutz.
2. Die Anzahl der Watchlist-Aktien reduzieren oder die Anfrageintervalle vergrößern.
3. Häufige manuelle Analysetrigger vermeiden.
4. Wenn das East-Money-Interface häufig fehlschlägt, kann `ENABLE_EASTMONEY_PATCH=true` gesetzt werden, um den East-Money-Patch zu aktivieren (injiziert NID-Token und zufälligen User-Agent, reduziert die Wahrscheinlichkeit der Limitierung).
5. `MAX_WORKERS=1` einstellen, um seriell abzurufen und den gleichzeitigen Druck auf East Money zu verringern.

---

## ⚙️ Konfigurationsbezogene Fragen

### Q5: GitHub Actions schlägt fehl, Hinweis auf fehlende Umgebungsvariablen?

**Symptom**: Das Actions-Log zeigt, dass `GEMINI_API_KEY` oder `STOCK_LIST` nicht definiert sind.

**Ursache**: GitHub unterscheidet zwischen `Secrets` (verschlüsselt) und `Variables` (normale Variablen); eine falsche Konfigurationsposition führt zu Lesefehlern.

**Lösung**:
1. Gehe zu `Settings` → `Secrets and variables` → `Actions` des Repositories.
2. **Secrets** (auf `New repository secret` klicken): speichern sensible Informationen
   - `GEMINI_API_KEY`
   - `OPENAI_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - Verschiedene Webhook-URLs
3. **Variables** (auf den Tab `Variables` klicken): speichern nicht-sensible Konfiguration
   - `STOCK_LIST`
   - `GEMINI_MODEL`
   - `REPORT_TYPE`

> Kompatibilitätshinweis: Der tägliche Analyse-Workflow bindet auch eine Umgebung namens `STOCK_LIST`; daher kann ein fälschlich in die Variables dieser Umgebung eingetragener `STOCK_LIST` ebenfalls gelesen werden. Der empfohlene Ort bleibt jedoch Repository variables. Konfiguriere für diese Umgebung keine required reviewers, wait timer oder Deploy-Branch-Beschränkungen, es sei denn, du möchtest, dass der tägliche Task auf manuelle Genehmigung wartet.

---

### Q6: Nach Änderungen an der .env-Datei greift die Konfiguration nicht?

**Lösung**:
1. Stelle sicher, dass die `.env`-Datei im Projektstammverzeichnis liegt.
2. **Docker-Bereitstellung / WebUI-Systemeinstellungen**:
   - `--env-file .env` / Compose `env_file` injizieren die `.env` des Hosts nur als Start-Umgebungsvariablen in den Container; sie erstellen oder schreiben `/app/.env` im Container nicht automatisch zurück.
   - Wenn der aktuell aktive `.env`-Datei bestimmte Keys fehlen, zeigt die WebUI-Einstellungsseite die gleichnamigen, beim Start injizierten Umgebungsvariablen als Fallback an; „Export .env" exportiert jedoch weiterhin nur den Inhalt der aktuell aktiven Konfigurationsdatei.
   - Nach dem Speichern in der WebUI werden `STOCK_LIST`, `SCHEDULE_ENABLED`, `SCHEDULE_TIME`, `SCHEDULE_TIMES`, `SCHEDULE_RUN_IMMEDIATELY`, `RUN_IMMEDIATELY` in die `.env` im Container zurückgeschrieben.
   - Nach dem Speichern in der WebUI wird ein Konfigurations-Reload des laufenden Prozesses ausgelöst; die aktiven Lesepfade nutzen synchron die zuletzt zurückgeschriebene `.env`, z. B. liest der geplante Task weiterhin den gespeicherten `STOCK_LIST` hot-read.
   - Wenn im Container-Startbefehl gleichnamige Umgebungsvariablen übergeben wurden (z. B. `--env-file .env`, `docker run -e ...` oder Compose `environment:`), können diese Start-Umgebungsvariablen beim nächsten Neustart weiterhin Vorrang haben; damit die in der WebUI gespeicherten Werte übernehmen, müssen diese gleichnamigen Overrides synchron aktualisiert oder entfernt werden.
   - Um die in der WebUI gespeicherte Konfiguration zu persistieren, setze `ENV_FILE` auf eine beschreibbare Daten-Volume-Datei wie `/app/data/runtime.env` und mounte nicht die einzelne Host-`.env`-Datei auf `/app/.env`.
   - Nach dem Speichern von `SCHEDULE_ENABLED`, `SCHEDULE_TIME`, `SCHEDULE_TIMES` starten bzw. stoppen WebUI/API/Desktop-Langzeitprozesse den Runtime-Scheduler nach der neuen Konfiguration oder bauen ihn neu auf.
   - `SCHEDULE_RUN_IMMEDIATELY` und `RUN_IMMEDIATELY` bleiben Start-/Einmal-Lauf-Konfiguration; nach dem Speichern wird nicht sofort eine Analyse ausgelöst.
3. **Nach manueller Änderung der `.env` bei Docker**: Nach der Änderung wird ein Neustart des Containers empfohlen.
   ```bash
   docker-compose down && docker-compose up -d
   ```
4. **GitHub Actions**: `.env`-Dateien greifen nicht; die Konfiguration muss in Secrets/Variables erfolgen.
5. Prüfe, ob mehrere `.env`-Dateien (z. B. `.env.local`) zu Überlagerungen führen.

---

### Q7: Wie konfiguriere ich einen Proxy für den Zugriff auf Gemini/OpenAI-APIs?

**Lösung**:

In `.env` konfigurieren:
```bash
USE_PROXY=true
PROXY_HOST=127.0.0.1
PROXY_PORT=10809
```

> ⚠️ Hinweis: Die Proxy-Konfiguration gilt nur für die lokale Ausführung; in der GitHub-Actions-Umgebung ist kein Proxy nötig.

---

### Häufige Fragen zur LLM-Konfiguration

> Vollständige Erklärung siehe [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md).

**F: Ich habe GEMINI_API_KEY und LLM_CHANNELS konfiguriert, warum wird nur ein Kanal verwendet?**

Das System wählt nach Priorität nur einen aus: erweiterte Modell-Routing-YAML (`LITELLM_CONFIG`) > `LLM_CHANNELS` > legacy Keys. Die YAML wird jedoch nur wirksam, wenn die Datei korrekt geparst werden kann und eine gültige `model_list` erzeugt; wenn der YAML-Pfad ungültig oder der Inhalt leer ist, fällt das System automatisch auf `LLM_CHANNELS` oder legacy Keys zurück. Sobald eine Ebene tatsächlich greift, nehmen Konfigurationen mit niedrigerer Priorität nicht mehr an der Verarbeitung teil.

**F: check_env gibt „Kein verfügbares AI-Modell konfiguriert" aus, was tun?**

Wähle zuerst standardmäßig einen Anbieter und fülle den entsprechenden API-Key aus; wenn ein festes Hauptmodell gewünscht ist, ergänze `LITELLM_MODEL=provider/model`; für Modellumschaltung konfiguriere `LLM_CHANNELS` oder die erweiterte Modell-Routing-YAML. Führe `python scripts/check_env.py --config` aus, um die Konfiguration zu validieren, und `python scripts/check_env.py --llm`, um die API real zu testen.

**F: Wie verwende ich mehrere Modelle gleichzeitig (z. B. AIHubmix + DeepSeek + Gemini)?**

Verwende den Kanalmodus: `LLM_CHANNELS=aihubmix,deepseek,gemini` setzen und für jeden Kanal `LLM_{NAME}_BASE_URL`, `LLM_{NAME}_API_KEY`, `LLM_{NAME}_MODELS` konfigurieren. Alternativ kann die Konfiguration visuell unter Web-Einstellungsseite → AI-Modell → AI-Modell-Anbindung erfolgen.

**F: Die Ask-Stock/Agent-Funktion meldet kein verfügbares LLM, aber ich habe nur die alten `GEMINI_*` / `OPENAI_*` / `ANTHROPIC_*`-Konfigurationen, was tun?**

Prüfe zuerst, ob aktuell `LITELLM_CONFIG` oder `LLM_CHANNELS` aktiviert ist; wenn ja, überschreiben die oberen Konfigurationen die legacy Keys. Wenn du diese beiden Ebenen nicht aktiviert hast und `AGENT_LITELLM_MODEL` leer ist, erbt der Ask-Stock-Agent weiterhin automatisch die legacy-Provider-Modelle: `GEMINI_MODEL`, `OPENAI_MODEL`, `ANTHROPIC_MODEL` werden jeweils auf LiteLLM-Modellnamen mit dem entsprechenden Provider-Präfix abgebildet. Diese Reparatur migriert oder leert alte Konfigurationen nicht stillschweigend, sondern gibt die „wahre fehlende Ursache" direkt an das Frontend zurück, damit du besser beurteilen kannst, ob ein Key fehlt, ein Modellname fehlt oder die obere Konfiguration überschrieben wurde. Vollständige Kompatibilitätssemantik siehe „Kompatibilitätshinweis für Ask-Stock-Agent / LiteLLM-Konfiguration" im [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md).

---

## 📱 Push-Benachrichtigungsbezogene Fragen

### Q8: Der Roboter-Push schlägt fehl, Hinweis auf zu lange Nachricht?

**Symptom**: Analyse erfolgreich, aber keine Push-Benachrichtigung erhalten; das Log zeigt einen 400-Fehler oder `Message too long`.

**Ursache**: Die Nachrichtenlängenlimits der Plattformen unterscheiden sich:
- WeCom: 4 KB
- Feishu: 20 KB
- DingTalk: 20 KB

**Lösung**:
1. **Automatische Aufteilung**: Die neueste Version realisiert das automatische Aufteilen langer Nachrichten.
2. **Einzelaktien-Push-Modus**: `SINGLE_STOCK_NOTIFY=true` setzen; nach jeder abgeschlossenen Aktienanalyse wird sofort gepusht.
3. **Kompakter Bericht**: `REPORT_TYPE=simple` setzen, um das kompakte Format zu verwenden.

---

### Q9: Telegram-Push-Benachrichtigungen kommen nicht an?

**Lösung**:
1. Bestätige, dass `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID` konfiguriert sind.
2. Chat-ID ermitteln:
   - Dem Bot eine beliebige Nachricht senden
   - `https://api.telegram.org/bot<TOKEN>/getUpdates` aufrufen
   - Im zurückgegebenen JSON `chat.id` finden
3. Stelle sicher, dass der Bot zur Zielgruppe hinzugefügt wurde (bei Gruppen-Chat).
4. Bei lokaler Ausführung muss die Telegram-API erreichbar sein (ggf. Proxy erforderlich).

---

### Q10: WeCom-Markdown-Format wird nicht korrekt angezeigt?

**Lösung**:
1. WeCom unterstützt Markdown nur eingeschränkt; versuche Folgendes zu setzen:
   ```bash
   WECHAT_MSG_TYPE=text
   ```
2. Dadurch werden Nachrichten im reinen Textformat gesendet.

---

## 🤖 AI-Modellbezogene Fragen

### Q11: Gemini-API gibt 429-Fehler zurück (zu viele Anfragen)?

**Symptom**: Das Log zeigt `Resource has been exhausted` oder `429 Too Many Requests`.

**Lösung**:
1. Die Gemini-Free-Version hat ein Ratenlimit (etwa 15 RPM).
2. Die Anzahl der gleichzeitig analysierten Aktien reduzieren.
3. Die Anfrageverzögerung erhöhen:
   ```bash
   GEMINI_REQUEST_DELAY=5
   ANALYSIS_DELAY=10
   ```
4. Oder auf eine OpenAI-kompatible API als Alternative wechseln.

---

### Q12: Wie verwende ich inländische Modelle wie DeepSeek?

**Konfigurationsmethode**:

```bash
# GEMINI_API_KEY muss nicht konfiguriert werden
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
# deepseek-chat / deepseek-reasoner bleiben kompatibel, sind aber offiziell als nach 2026/07/24 veraltet markiert
```

Unterstützte Modelldienste:
- DeepSeek: `https://api.deepseek.com`
- Qwen (Tongyi Qianwen): `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Moonshot: `https://api.moonshot.cn/v1`

---

### Q12b: Wie verwende ich das lokale Ollama-Modell?

**Konfigurationsmethode**: `OLLAMA_API_BASE` + `LITELLM_MODEL` oder Kanalmodus (`LLM_CHANNELS=ollama` + `LLM_OLLAMA_BASE_URL` + `LLM_OLLAMA_MODELS`) verwenden.

**Stolperfalle vermeiden**: Ollama nicht über `OPENAI_BASE_URL` konfigurieren, sonst fügt das System die URL falsch zusammen (z. B. 404, `api/generate/api/show`). Details siehe [LLM-Konfigurationsleitfaden](LLM_CONFIG_GUIDE.md) Beispiel 4 und Kanalbeispiele.

---

### Q12c: Zur Laufzeit tritt `OllamaException / APIConnectionError` (All LLM models failed) auf, was tun?

**Symptom**: Im Log erscheint `litellm.APIConnectionError: OllamaException` oder `Analysis failed: All LLM models failed (tried 1 model(s))`.

Prüfe nacheinander die folgenden 5 Prüfpunkte:

1. **Ist der Ollama-Dienst gestartet?**
   ```bash
   # Prozesse anzeigen
   pgrep -a ollama
   # Bei keiner Ausgabe zuerst starten
   ollama serve
   ```
   Bestätige, dass der Dienst lauscht: `curl http://localhost:11434` sollte `Ollama is running` zurückgeben.

2. **Ist `OLLAMA_API_BASE` korrekt konfiguriert?**
   - ✅ Richtig: `OLLAMA_API_BASE=http://localhost:11434`
   - ❌ Falsch: Die Ollama-Adresse in `OPENAI_BASE_URL` einzutragen führt zu einem falsch zusammengesetzten URL-Pfad (z. B. `…/api/generate/api/show`).

3. **Hat der Modellname das Präfix `ollama/`?**
   - ✅ Richtig: `LITELLM_MODEL=ollama/qwen3:8b`
   - ❌ Falsch: `LITELLM_MODEL=qwen3:8b` (Präfix fehlt; litellm kann nicht zu Ollama routen)

4. **Ist das Modell lokal heruntergeladen?**
   ```bash
   ollama list          # vorhandene Modelle anzeigen
   ollama pull qwen3:8b # falls nicht vorhanden, zuerst pullen
   ```

5. **Netzwerk und Firewall bei Remote-Bereitstellung / Docker**
   - Wenn Ollama und das Programm nicht auf demselben Host laufen, `OLLAMA_API_BASE` auf die tatsächliche IP ändern, z. B. `http://192.168.1.100:11434`.
   - Bestätige, dass die Firewall Port 11434 freigibt und Ollama beim Start an die richtige Adresse gebunden ist (`OLLAMA_HOST=0.0.0.0:11434`).

> Vollständige Konfigurationsbeispiele siehe [LLM-Konfigurationsleitfaden → Beispiel 4 (Ollama)](LLM_CONFIG_GUIDE.md#example-4-ollama).

---

## 🐳 Docker-bezogene Fragen

### Q13: Docker-Container beendet sich direkt nach dem Start?

**Lösung**:
1. Container-Logs ansehen:
   ```bash
   docker logs <container_id>
   ```
2. Häufige Ursachen:
   - Umgebungsvariablen nicht korrekt konfiguriert
   - Formatfehler in der `.env`-Datei (z. B. überflüssige Leerzeichen)
   - Versionskonflikte bei Abhängigkeitspaketen

---

### Q14: Der API-Dienst in Docker ist nicht erreichbar?

**Lösung**:
1. Stelle sicher, dass der Startbefehl `--host 0.0.0.0` enthält (nicht 127.0.0.1).
2. Prüfe die korrekte Port-Mapping:
   ```yaml
   ports:
     - "8000:8000"
   ```

---

### Q14.1: Netzwerk-/DNS-Auflösungsfehler in Docker (z. B. api.tushare.pro, searchapi.eastmoney.com nicht auflösbar)?

**Symptom**: Das Log zeigt `Temporary failure in name resolution` oder `NameResolutionError`; weder Aktiendaten-APIs noch Large-Model-APIs sind erreichbar.

**Ursache**: In benutzerdefinierten Bridge-Netzwerken verwendet der Container den eingebauten DNS von Docker, der in bestimmten Netzwerkumgebungen (z. B. Bypass-Routern) fehlschlagen kann.

**Lösung** (in Prioritätsreihenfolge ausprobieren):

1. **DNS explizit konfigurieren**: Unter `x-common` in `docker/docker-compose.yml` hinzufügen:
   ```yaml
   dns:
     - 223.5.5.5
     - 119.29.29.29
     - 8.8.8.8
   ```
   Danach `docker-compose down` und `docker-compose up -d --force-recreate` ausführen, um die Container neu zu erstellen.

2. **Host-Netzwerkmodus verwenden**: Wenn das oben Genannte weiterhin wirkungslos ist, kann unter dem `server`-Dienst `network_mode: host` hinzugefügt und das `ports`-Mapping entfernt werden. Im Host-Modus ist `ports` wirkungslos; **der Port wird über `--port` im `command` festgelegt**. Falls der Standardport des Hosts bereits belegt ist, kann ein anderer Port gewählt werden (z. B. `API_PORT=8080` in `.env` setzen) und entsprechend `http://localhost:8080` aufgerufen werden.

> 📌 Zugehöriges Issue: [#372](https://github.com/ZhuLinsen/daily_stock_analysis/issues/372)

---

### Q14.2: In welcher Datei steht bei der Docker-Installation die Softwareversion?

**Fazit**: Für Docker-Nutzer ist **die maßgeblichste Version nicht eine Python-Quelldatei-Konstante, sondern das tatsächlich verwendete Image-Tag**.

**Warum**:
1. Der Docker-Release des Repositories wird durch `.github/workflows/docker-publish.yml` ausgelöst; nur beim Pushen von Git-Tags der Form `v*.*.*` (z. B. `v3.12.0`) wird das entsprechende Release-Image erzeugt.
2. Das bedeutet, die Docker-Image-Version folgt im Wesentlichen dem **GitHub Release / Git-Tag**, nicht einer fest in `main.py`, `server.py` oder anderem Backend-Quellcode eingetragenen Version.
3. Die `version` in `apps/dsa-web/package.json` ist derzeit ein Platzhalterwert `0.0.0`; die WebUI-„Versionsinformation"-Karte eignet sich besser zur Bestätigung, ob statische Ressourcen neu gebaut wurden, und sollte nicht als Docker-Release-Version betrachtet werden.
4. Die Desktop-Version wird separat gepflegt und steht im Feld `version` von `apps/dsa-desktop/package.json`; sie repräsentiert nur das Electron-Desktop-Paket, nicht die Docker-Image-Version.

**So ermittelst du die aktuelle Docker-Version**:
1. **Zuerst auf das Image-Tag in den Deployment-Befehlen oder der Compose-Datei schauen**: z. B. `ghcr.io/zhulinsen/daily_stock_analysis:v3.12.0`, wobei `v3.12.0` die aktuelle Bereitstellungsversion ist.
2. **Wenn du `latest` gezogen hast**: Schau dir das damalige `docker pull` / `docker-compose.yml` / Deployment-Skript an oder gleiche mit [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) ab, um die zugehörige Release-Notiz zu bestätigen.
3. **Wenn du nur bestätigen willst, ob das Frontend auf einen neuen Build aktualisiert wurde**: Öffne die „Systemeinstellungen"-Seite der WebUI und prüfe die Build-ID / Build-Zeit; das hilft, zu bestätigen, ob statische Ressourcen aktualisiert wurden, ist aber nicht gleichbedeutend mit der Docker-Image-Release-Version.

**Empfehlung**: Wenn du wiederholte Updates vermeiden möchtest, verwende bei der Bereitstellung möglichst ein festes, eindeutiges Version-Tag (z. B. `v3.12.0`) und verlasse dich nicht langfristig auf `latest`.

---

## 🔧 Andere Fragen

### Q15: Wie führe ich nur den Marktrückblick aus, ohne einzelne Aktien zu analysieren?

**Methode**:
```bash
# Lokale Ausführung
python main.py --market-only

# GitHub Actions
# Bei manuellem Auslösen mode: market-only wählen
```

---

### Q16: Die Zählung von Kauf/Abwarten/Verkauf im Analyseergebnis stimmt nicht?

**Ursache**: Frühere Versionen verwendeten Regex-Matching für die Zählung, das von den tatsächlichen Empfehlungen abweichen konnte.

**Lösung**: In der neuesten Version behoben; das AI-Modell gibt jetzt direkt das Feld `decision_type` aus, um eine genaue Zählung zu ermöglichen.

---

### Q17: Warum wird bei manuellem Auslösen am Wochenende in GitHub Actions trotzdem „Kein Handelstag, übersprungen" angezeigt?

**Symptom**: `TRADING_DAY_CHECK_ENABLED` wurde konfiguriert oder eine manuelle Ausführung gewünscht, aber das Log meldet weiterhin „Alle relevanten Märkte sind heute keine Handelstage, Ausführung übersprungen".

**Lösung**:
1. `Actions → Tägliche Aktienanalyse → Run workflow` öffnen.
2. Bei manuellem Auslösen `force_run` auf `true` setzen (einmalige erzwungene Ausführung).
3. Falls die Handelstagsprüfung dauerhaft deaktiviert werden soll, unter `Settings → Secrets and variables → Actions` setzen:
   ```bash
   TRADING_DAY_CHECK_ENABLED=false
   ```

**Regelerklärung**:
- `TRADING_DAY_CHECK_ENABLED=true` und `force_run=false`: An Nicht-Handelstagen überspringen (Standard).
- `force_run=true`: Diese Ausführung erfolgt auch an Nicht-Handelstagen.
- `TRADING_DAY_CHECK_ENABLED=false`: Weder bei geplanten noch bei manuellen Ausführungen wird eine Handelstagsprüfung durchgeführt.

---

## 💬 Noch Fragen?

Wenn die oben genannten Inhalte dein Problem nicht gelöst haben, kannst du gerne:
1. Den [vollständigen Konfigurationsleitfaden](full-guide.md) ansehen
2. Ein [GitHub-Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues) suchen oder einreichen
3. Das [Änderungsprotokoll](CHANGELOG.md) ansehen, um die neuesten Fixes zu erfahren

---

*Zuletzt aktualisiert: 2026-04-20*
