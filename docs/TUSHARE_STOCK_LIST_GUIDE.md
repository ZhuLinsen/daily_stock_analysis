# Verwendungshinweise zum Tushare-Listenabruf-Tool

## Funktionsübersicht

Ruft aus Tushare Pro die Listen für A-Aktien, Hongkong-Aktien und US-Aktien ab und speichert sie als CSV-Dateien lokal.

## Schnellstart

### 1. Token konfigurieren

Fügen Sie in der `.env`-Datei im Projektstammverzeichnis das Tushare-Token hinzu:

```bash
TUSHARE_TOKEN=dein_tushare_token
```

> Token abrufen: Unter [Tushare Pro](https://tushare.pro/weborder/#/login) registrieren und abrufen.

### 2. Skript ausführen

```bash
python3 scripts/fetch_tushare_stock_list.py
```

Falls eine Korrektur der A-Aktien-Namen erforderlich ist, kann `--a-rk` hinzugefügt werden. Das Skript behält dann `stock_basic` als Basisquelle bei und verwendet `rt_k`, um Namen mit den Präfixen `XD`, `XR`, `DR`, `N`, `C` zurückzubesetzen, und überschreibt die Ausgabe in `data/stock_list_a.csv`:

```bash
python3 scripts/fetch_tushare_stock_list.py --a-rk
```

### 3. Ausgabe prüfen

Die Daten werden im Verzeichnis `data/` gespeichert:

```
data/
├── stock_list_a.csv       # A-Aktien-Liste (mit --a-rk die korrigierten Namen)
├── stock_list_hk.csv      # Hongkong-Aktien-Liste
├── stock_list_us.csv      # US-Aktien-Liste
└── README_stock_list.md   # Datenbeschreibungsdokument
```

## Funktionseigenschaften

✅ **Automatische Paginierung**: US-Aktiendaten werden automatisch seitenweise gelesen (5000 Einträge pro Seite)
✅ **Intelligentes Rate-Limiting**: 5-10 Sekunden zufällige Pause zwischen den Anfragen
✅ **Fehlerbehandlung**: Ein fehlgeschlagener Markt blockiert nicht die anderen Märkte
✅ **Fortschrittsanzeige**: Lese-Fortschritt wird in Echtzeit angezeigt
✅ **Automatische Dokumentation**: Erzeugt ein detailliertes Datenbeschreibungsdokument

## Hinweise zu den Märkten

| Markt | Schnittstelle | Punkteanforderung | Datenmenge |
|------|------|----------|--------|
| A-Aktien | stock_basic | 2000 Punkte | ~5000 Aktien |
| Hongkong-Aktien | hk_basic | 2000 Punkte | ~2000 Aktien |
| US-Aktien | us_basic | 120 Test / 5000 offiziell | ~10000 Aktien |

## Format der Ausgabedateien

### A-Aktien (stock_list_a.csv)

Bei Ausführung mit `--a-rk` werden in diese Datei die korrigierten A-Aktien-Namen geschrieben.

```csv
ts_code,symbol,name,area,industry,market,exchange,list_date,...
000001.SZ,000001,Ping An Bank,Shenzhen,Banking,Main Board,SZSE,19910403,...
600519.SH,600519,Kweichow Moutai,Guizhou,Spirits,Main Board,SSE,20010827,...
```

### Hongkong-Aktien (stock_list_hk.csv)

```csv
ts_code,name,fullname,market,list_date,trade_unit,curr_type,...
00700.HK,Tencent Holdings,Tencent Holdings Ltd.,Main Board,20040616,100,HKD,...
00005.HK,HSBC Holdings,HSBC Holdings plc,Main Board,19750401,100,HKD,...
```

### US-Aktien (stock_list_us.csv)

```csv
ts_code,name,enname,classify,list_date,...
AAPL,Apple,Apple Inc.,EQT,19801212,...
TSLA,Tesla,Tesla Inc.,EQT,20100629,...
BABA,Alibaba,Alibaba Group,ADR,20140919,...
```

## Anwendungsbeispiele

### Daten mit Python lesen

```python
import pandas as pd

# A-Aktien lesen
a_stocks = pd.read_csv('data/stock_list_a.csv')
print(f"A-Aktien-Anzahl: {len(a_stocks)}")

# Hauptplatine (Main Board) filtern
main_board = a_stocks[a_stocks['market'] == 'Main Board']
print(f"Main-Board-Anzahl: {len(main_board)}")

# Bestimmte Aktie suchen
stock = a_stocks[a_stocks['ts_code'] == '600519.SH']
print(stock[['name', 'industry', 'list_date']])
```

### Aktien-Autovervollständigungsindex aktualisieren

Empfohlen wird die Verwendung des Ein-Klick-Aktualisierungsskripts; es verwendet beim Abruf der A-Aktien standardmäßig `--a-rk` und erzeugt und synchronisiert anschließend den Autovervollständigungsindex:

```bash
pip install -r requirements.txt
python3 scripts/refresh_stock_index.py
```

Die Erzeugung des Autovervollständigungsindex ist auf `pypinyin` angewiesen, um die vollständige Pinyin- und die Pinyin-Initialen-Felder für chinesische Aktien zu schreiben; fehlt diese Abhängigkeit, schlägt das Skript direkt fehl, um einen degradierten Index zu vermeiden, der die Pinyin-Suche nicht unterstützt.

Wenn Sie nur die CSVs einzeln aktualisieren möchten, können Sie zuerst die Daten abrufen:

```bash
python3 scripts/fetch_tushare_stock_list.py --a-rk
```

Wenn bereits eine neue CSV vorliegt und nur der Index neu erzeugt werden soll:

```bash
python3 scripts/generate_index_from_csv.py --test  # zuerst testen
python3 scripts/generate_index_from_csv.py         # nach Bestätigung erzeugen
```

### Lokaler Client lädt den neuesten Index automatisch ab

Die neue Client-Version liest standardmäßig den neuesten `apps/dsa-web/public/stocks.index.json` vom `main`-Branch des GitHub-Projekts und cached ihn lokal in `data/cache/stocks.index.json`. Das Frontend greift weiterhin auf das lokale `/stocks.index.json` zu und muss nicht direkt über Cross-Origin auf GitHub zugreifen.

Adresse des Remote-Index, Prüffrequenz und Netzwerk-Timeout sind systemseitig eingebaute Werte und bieten keine Nutzerkonfiguration; der Nutzer entscheidet nur, ob die Funktion aktiviert wird:

```bash
STOCK_INDEX_REMOTE_UPDATE_ENABLED=true
```

Bei Standardaktivierung prüft das System höchstens alle 48 Stunden auf Aktualisierungen. Falls die Laufumgebung auf das GitHub-raw nicht zugreifen kann, ein Timeout auftritt oder der zurückgegebene Inhalt kein gültiger Aktienindex ist, behält die Anwendung den vorhandenen Cache; ohne Remote-Cache wird der mit der Anwendung mitgelieferte integrierte Index weiterverwendet. Ein fehlgeschlagenes Remote-Update blockiert weder den WebUI-Start, die Aktien-Autovervollständigung noch den Analyseablauf; nach dem Überschreiten eines systemseitigen Schwellenwerts für wiederholte Fehlschläge werden die Wiederholungsversuche innerhalb dieses Prozesses pausiert, bis zum nächsten 48-Stunden-Fenster.

## Hinweise

1. **Punkteanforderung**: Achten Sie darauf, dass das Konto genügend Punkte hat (A-Aktien/Hongkong-Aktien 2000, US-Aktien 120 Test).
2. **Anfragebegrenzung**: Beachten Sie das Limit für Anfragen pro Minute der API.
3. **Datenaktualisierung**: Die Maintainer empfehlen, alle drei Tage zu aktualisieren und in das Repository zu committen; der lokale Client prüft standardmäßig höchstens alle 48 Stunden auf Indexaktualisierungen in GitHub `main`. Später kann die Aktualisierung und das Einreichen von PRs über einen GitHub-Actions-Workflow automatisiert werden.
4. **Netzwerkverbindung**: Eine stabile Netzwerkverbindung ist erforderlich.

## Häufige Fragen

### F: Die Meldung "TUSHARE_TOKEN nicht gefunden" erscheint?
**A**: Bitte konfigurieren Sie in der `.env`-Datei `TUSHARE_TOKEN=dein_token`.

### F: Die Meldung "Kontopunkte nicht ausreichend" erscheint?
**A**:
- A-Aktien/Hongkong-Aktien benötigen 2000 Punkte
- US-Aktien: 120 Punkte für den Test, 5000 Punkte für die offizielle Berechtigung
- Unter https://tushare.pro nachsehen, wie Punkte erlangt werden

### F: Was tun, wenn das Lesen fehlschlägt?
**A**:
1. Netzwerkverbindung prüfen
2. Prüfen, ob das Token korrekt ist
3. Prüfen, ob die Kontopunkte ausreichen
4. Das Skript führt keine automatischen Wiederholungen durch; nach einem fehlgeschlagenen Einzelrequest wird ein Fehler ausgegeben und das Skript beendet sich. Bitte die Ursache ermitteln und erneut ausführen.

### F: Wie hoch ist die Datenaktualisierungsfrequenz?
**A**: Für die lokalen CSVs der Maintainer und den Repository-Index wird empfohlen, alle drei Tage zu aktualisieren und in das Repository zu committen; bei hochwirksamen Ereignissen wie dem Entfernen des ST-Prefixes oder Umbenennungen kann vorzeitig aktualisiert werden. Künftig kann die Aktualisierung und das Einreichen von PRs über einen GitHub-Actions-Workflow automatisiert werden. Für den normalen lokalen Client prüft das System standardmäßig höchstens alle 48 Stunden auf den neuesten Index in GitHub `main`.

### F: Beeinträchtigt ein nicht erreichbares GitHub-raw die Nutzung?
**A**: Nein. Das Remote-Index-Update ist best-effort: Bei einem Fehlschlag wird der vorhandene Remote-Cache oder der mit der Anwendung mitgelieferte integrierte Index weiterverwendet; ist der Index vollständig unverfügbar, greift die Web-Autovervollständigung auf den vorhandenen Fallback zurück, und Aktiencodes können weiterhin manuell eingegeben werden.

## Verwandte Links

- [Tushare-Website](https://tushare.pro)
- [Tushare-Dokumentation](https://tushare.pro/document/2)
- [Möglichkeiten, Punkte zu erlangen](https://tushare.pro/document/1)
- [API-Daten-Debugging](https://tushare.pro/document/2)
