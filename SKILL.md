---
name: "stock_analyzer"
description: "Analysiert Aktien und den Markt. Wird aufgerufen, wenn der Benutzer eine einzelne oder mehrere Aktien analysieren oder einen Marktrückblick durchführen möchte."
---

# Aktienanalysator

Diese Skill basiert auf der Logik in `src/services/analyzer_service.py` und bietet Funktionen zur Analyse einzelner Aktien und des gesamten Markts.

## Ausgabestruktur (`AnalysisResult`)

Die Analysefunktionen geben ein `AnalysisResult`-Objekt (oder eine Liste davon) zurück, das eine umfangreiche Struktur aufweist. Im Folgenden ein kurzer Überblick über seine Kernkomponenten mit einem realen Beispielausgabe:

Die `dashboard`-Eigenschaft enthält die Kernanalyse und ist in vier Hauptabschnitte unterteilt:
1.  **`core_conclusion`**: Eine Ein-Satz-Zusammenfassung, Signaltyp und Positionsgrößen-Empfehlung.
2.  **`data_perspective`**: Technische Daten, einschließlich Trendstatus, Preislage, Volumenanalyse und Chip-Struktur.
3.  **`intelligence`**: Qualitative Informationen wie Nachrichten, Risikoalarme und positive Katalysatoren.
4.  **`battle_plan`**: Umsetzbare Strategien, einschließlich Präzisionspunkten (Kauf-/Verkaufsziele), Positionsgrößenstrategie und Risikokontroll-Checkliste.

## Konfiguration (`Config`)

Alle Analysefunktionen können ein optionales `config`-Objekt akzeptieren. Dieses Objekt enthält sämtliche Konfigurationen der Anwendung, z. B. API-Schlüssel, Benachrichtigungseinstellungen und Analyseparameter.

Wenn kein `config`-Objekt übergeben wird, verwenden die Funktionen automatisch die globale Singleton-Instanz, die aus der `.env`-Datei geladen wird.

**Referenz:** [`Config`](src/config.py)

## Funktionen

### 1. Eine einzelne Aktie analysieren

**Beschreibung:** Analysiert eine einzelne Aktie und gibt das Analyseergebnis zurück.

**Wann verwenden:** Wenn der Benutzer die Analyse einer bestimmten Aktie anfordert.

**Eingaben:**
- `stock_code` (str): Der zu analysierende Aktiencode.
- `config` (Config, optional): Konfigurationsobjekt. Standard: `None`.
- `full_report` (bool, optional): Ob ein vollständiger Bericht erstellt werden soll. Standard: `False`.
- `notifier` (NotificationService, optional): Benachrichtigungsservice-Objekt. Standard: `None`.

**Ausgabe:** `Optional[AnalysisResult]`
Ein `AnalysisResult`-Objekt mit dem Analyseergebnis, oder `None`, wenn die Analyse fehlschlägt.

**Beispiel:**

```python
from src.services.analyzer_service import analyze_stock

# Analyse einer einzelnen Aktie
result = analyze_stock("600989")
if result:
    print(f"Aktie: {result.name} ({result.code})")
    print(f"Stimmungswert: {result.sentiment_score}")
    print(f"Handlungsempfehlung: {result.operation_advice}")
```

**Referenz:** [`analyze_stock`](src/services/analyzer_service.py)

### 2. Mehrere Aktien analysieren

**Beschreibung:** Analysiert eine Liste von Aktien und gibt eine Liste von Analyseergebnissen zurück.

**Wann verwenden:** Wenn der Benutzer mehrere Aktien gleichzeitig analysieren möchte.

**Eingaben:**
- `stock_codes` (List[str]): Die Liste der zu analysierenden Aktiencodes.
- `config` (Config, optional): Konfigurationsobjekt. Standard: `None`.
- `full_report` (bool, optional): Ob für jede Aktie ein vollständiger Bericht erstellt werden soll. Standard: `False`.
- `notifier` (NotificationService, optional): Benachrichtigungsservice-Objekt. Standard: `None`.

**Ausgabe:** `List[AnalysisResult]`
Eine Liste von `AnalysisResult`-Objekten.

**Beispiel:**

```python
from src.services.analyzer_service import analyze_stocks

# Analyse mehrerer Aktien
results = analyze_stocks(["600989", "000001"])
for result in results:
    print(f"Aktie: {result.name}, Handlungsempfehlung: {result.operation_advice}")
```

**Referenz:** [`analyze_stocks`](src/services/analyzer_service.py)


### 3. Marktrückblick durchführen

**Beschreibung:** Führt einen Rückblick über den gesamten Markt durch und gibt einen Bericht zurück.

**Wann verwenden:** Wenn der Benutzer einen Marktüberblick, eine Zusammenfassung oder einen Rückblick anfordert.

**Eingaben:**
- `config` (Config, optional): Konfigurationsobjekt. Standard: `None`.
- `notifier` (NotificationService, optional): Benachrichtigungsservice-Objekt. Standard: `None`.

**Ausgabe:** `Optional[str]`
Ein String mit dem Marktrückblick-Bericht, oder `None`, wenn er fehlschlägt.

**Beispiel:**

```python
from src.services.analyzer_service import perform_market_review

# Marktrückblick durchführen
report = perform_market_review()
if report:
    print(report)
```

**Referenz:** [`perform_market_review`](src/services/analyzer_service.py)
