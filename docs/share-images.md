# Vorlage für geteilte Bildberichte und Datenbefüllung

Geteilte Bilder wandeln die Einzelaktienanalyse und den Markt-Rückblick in ein für soziale Plattformen geeignetes 1080px-Langbild um. Einzelaktien und Markt verwenden zwei voneinander unabhängige Informationsstrukturen, teilen sich jedoch das DSA-Branding, die Repo-Kennzeichnung `ZhuLinsen/daily_stock_analysis` und den Risikohinweis. Im GitHub-Bereich wird kein QR-Code platziert; der Xiaohongshu-Bereich wird durch die Deployment-Konfiguration bestimmt und bei fehlender Konfiguration vollständig ausgeblendet, damit Forks oder private Deployments das Maintainer-Konto nicht standardmäßig bewerben.

## Wie die Laufzeit die Daten befüllt

Die bestehende Benachrichtigungskette muss die Bilddaten nicht manuell zusammenbauen:

```text
Einzelaktien-AnalysisResult
  -> AnalysisResult.to_dict()  strukturiertes JSON + stabiles Markdown
  -> share_image liest zuerst das JSON, Markdown als kompatibler Fallback
  -> HTML der Einzelaktien-Entscheidungskarte
  -> wkhtmltoimage / markdown-to-file / Playwright erzeugt PNG

Markt-MarketOverview + market_light + LLM-Rückblick
  -> MarketAnalyzer erzeugt market_review_payload + stabiles Markdown
  -> share_image liest zuerst das Payload, Markdown als kompatibler Fallback
  -> HTML der Markt-Rückblick-Karte
  -> wkhtmltoimage / markdown-to-file / Playwright erzeugt PNG
```

`MARKDOWN_TO_IMAGE_CHANNELS`, `MD2IMG_ENGINE` und `MARKDOWN_TO_IMAGE_MAX_CHARS` steuern weiterhin, welche Benachrichtigungskanäle in Bilder umgewandelt werden, welches Rendering-Programm verwendet wird und wie lang die maximale Eingabelänge ist. Schlägt die Umwandlung fehl, wird weiterhin auf Textbenachrichtigungen zurückgegriffen.

Das Xiaohongshu-Branding verwendet folgende optionale Konfiguration; sind alle vier Werte leer, wird dieser Bereich deaktiviert:

```dotenv
SHARE_IMAGE_XIAOHONGSHU_URL=https://example.com/my-xiaohongshu
SHARE_IMAGE_XIAOHONGSHU_HANDLE=@我的账号
SHARE_IMAGE_XIAOHONGSHU_ID=123456789
SHARE_IMAGE_XIAOHONGSHU_QR_PATH=assets/my-xiaohongshu-qr.png
```

Der QR-Code-Pfad unterstützt absolute Pfade oder relative Pfade zum Projektstamm; das gebündelte Desktop-Backend löst relative Pfade zusätzlich aus dem PyInstaller-Ressourcenverzeichnis auf. Die Account-URL akzeptiert nur `http://` oder `https://`. Der QR-Code wird beim Umwandeln als eingebettete Data URI gerendert und ist nicht von einer Laufzeit-Netzwerkverbindung abhängig.

## Web-Ein-Klick-Freigabe

In der Browser-Version zeigen die historischen Einzelaktienberichte, der Markt-Rückblick und die rechte obere Ecke des vollständigen Berichts-Drawers einen „Teilen“-Button. Beim Laden eines Berichts ruft die Seite zuerst `GET /api/v1/history/{record_id}/share-image` auf, um das PNG vorab zu erzeugen und zwischenzuspeichern; erst wenn dies abgeschlossen ist, wird der Button klickbar, sodass `navigator.share()` innerhalb des kurzlebigen Nutzeraktivierungsfensters des Klicks synchron aufgerufen werden kann. Browser mit Unterstützung für das Teilen von Dateien öffnen die System-Freigabefläche; andere Browser laden das PNG direkt herunter. Deklariert der Browser zwar Datei-Freigabe, schlägt die System-Freigabefläche aber tatsächlich fehl, wird – außer bei aktivem Abbruch durch den Nutzer – automatisch auf den Download des bereits erzeugten PNG zurückgegriffen.

Der Electron-Desktop-Runtime zeigt den Button standardmäßig nicht. Die aktuellen Windows/macOS-Pakete verteilen kein `wkhtmltoimage`, `markdown-to-file` oder Playwright/Chromium-Renderer mit, damit Desktop-Nutzer beim Laden der Seite nicht in den Fehlerzustand `share_image_unavailable` geraten.

Die manuelle Web-Erzeugung unterliegt nicht der Einschränkung von `MARKDOWN_TO_IMAGE_CHANNELS`, der Server muss jedoch weiterhin einen verfügbaren `MD2IMG_ENGINE` konfigurieren. Bei Verwendung von Playwright zuerst ausführen:

```bash
cd apps/dsa-web
npm ci
npx playwright install chromium
```

Die strukturierten Daten dienen der präzisen Befüllung von Feldern wie Name, Aktion, Bewertung, Preis, Marktbreite und Sektor; das Markdown bleibt weiterhin für den kompatiblen Fallback alter Aufrufe sowie für Textabschnitte wie Pläne und Risiken zuständig. Manche historischen JSON-Daten enthalten nur die tatsächlich vorhandenen Felder und leeren keine vorhandenen Kursdaten, technischen Referenzen oder Ausführungspunkte aus dem Markdown. Die Vorlage leitet Aktionen nicht selbst aus Bewertungen ab und erfindet auch keine Preise oder Indikatoren. Wenn Felder `N/A`, `-`, leer oder ohne entsprechendes Modul sind, wird die zugehörige Karte automatisch ausgeblendet.

## Feldzuordnung der Einzelaktien-Karte

| Bildbereich | Projektfeld / Erzeugungsquelle | Befüllungsregel |
| --- | --- | --- |
| Aktienname, Code | `AnalysisResult.name`, `AnalysisResult.code` | Direkt aus dem strukturierten Feld lesen, der Markdown-Titel dient nur als Fallback |
| Aktion, Bewertung, Trend | `action_label` / `operation_advice`, `sentiment_score`, `trend_prediction`, `confidence_level` | Endgültiges kalibriertes Ergebnis verwenden, Bewertungsspanne 0–100, Konfidenzgrad der Schlussfolgerung kennzeichnen |
| Kernschlussfolgerung | `dashboard.core_conclusion.one_sentence` | Bei fehlendem Wert ausblenden |
| Marktschnappschuss | `market_snapshot` | Aktueller/Schlusskurs, Veränderung, Umsatzverhältnis und Umschlagsrate nach verfügbaren Feldern anzeigen; die Datenquelle fließt in die Fußnote ein |
| Ausführungsplan | `dashboard.battle_plan.sniper_points` | Nur ideale/bestätigte Kaufpunkte, Stop-Loss und das erste Zielpreisniveau anzeigen; komplexe Triggerbedingungen bleiben im vollständigen Bericht |
| Technische Referenz | `dashboard.data_perspective` | Gleitmittelzustand, Trend-Score, MA5-Abweichung, Unterstützung und Widerstand anzeigen; strukturiertes Umsatzverhältnis/strukturierte Umschlagsrate werden bei bereits vorhandenem Schnappschuss nicht als langwierige Volumenbeschreibung doppelt angezeigt, bei fehlenden strukturierten Volumendaten in alten Datensätzen bleibt der Markdown-Fallback erhalten |
| Nächste Beobachtung | `dashboard.phase_decision` | Aktionsfenster, Zeitpunkt der nächsten Prüfung und höchstens zwei Beobachtungsbedingungen anzeigen |
| Katalysatoren und Risiken | `dashboard.intelligence` | `positive_catalysts` und `risk_alerts` jeweils höchstens 2 Kurzzusammenfassungen anzeigen |
| Haltempfehlung | `core_conclusion.position_advice` | Nur zwischen „nicht gehalten“ und „gehalten“ unterscheiden; Positionsgröße, Aufbau und Risikokontrollen bleiben als Langtext im vollständigen Bericht |

Die Vorlage unterstützt die aktuellen chinesischen, englischen und koreanischen Berichtslabels des Projekts; Posterkategorien, Indikatorlabels und die Fußnote folgen der Berichtssprache. Enthält ein „Entscheidungs-Dashboard“ nur eine Aktie, wird automatisch die Einzelaktien-Karte verwendet; bei mehreren Aktien bleibt das Mehr-Aktien-Report-Layout erhalten, damit nicht fälschlich die erste Aktie als ganzer Bericht behandelt wird. Zusammengesetzte Aktionen wie `强烈买入`, `Strong Buy` usw. behalten das vollständige Aktionslabel.

## Feldzuordnung der Markt-Karte

| Bildbereich | Projektfeld / Erzeugungsquelle | Befüllungsregel |
| --- | --- | --- |
| Datum, Marktbereich | `MarketOverview.date`, Rückblick-Region | Titel für A-/US-/HK-/JP-/KR-Marktrückblick erzeugen; mehrspurige Berichte gleichen `market_review_payload.markets` abschnittsweise ab |
| Marktsignal | `market_light.score`, `temperature_label`, `label`, `guidance` | Deterministisches Marktampel-Ergebnis verwenden, keine zweite Bewertung durch die Vorlage |
| Index-Performance | `MarketOverview.indices`, `color_scheme` | Höchstens 4 Hauptindizes mit letztem Wert und Veränderung anzeigen; das strukturierte Payload hält die `green_up` / `red_up`-Farbsemantik zum Erzeugungszeitpunkt |
| Marktbreite | `up_count`, `down_count`, `limit_up_count`, `limit_down_count`, `total_amount` | Nur anzeigen, wenn die Datenquelle dies unterstützt und der Bericht strukturierte Daten enthält |
| Signal-Aufschlüsselung | `market_light.dimensions` | Nur deterministische Bewertungen mit `available != false` anzeigen; Platzhalter-Score 50 nicht unterstützter Dimensionen nicht als echte Daten behandeln |
| Starke/Schwache Sektoren | `sectors.top`, `sectors.bottom` | Jeweils Top 3 der führenden und nachgebenden Sektoren anzeigen; Märkte ohne Sektor-Ranking automatisch ausblenden |
| Kapitalbeobachtung | Abschnitt „Kapital und Stimmung“ des Rückblicks | Auf-/Abwärtsverhältnis, inkrementelles Handelsvolumen und Kapitalstil destillieren; Umsatzvolumen oder Nachrichten nicht als Nettozufluss ausgeben |
| Wichtige Verfolgung | Richtungen „beobachten/meiden“ im „Handelsplan von morgen“ des Rückblicks | Jeweils höchstens 2 Sektoren oder Themen anzeigen; das aktuelle Payload enthält kein `leader_stocks`, daher werden keine wichtigen Einzelaktien erfunden |
| Strategie für morgen | Abschnitt „Handelsplan von morgen“ des Rückblicks | Schlussfolgerung, Positionsspanne und Ungültigkeitsbedingungen anzeigen, nicht mit der wichtigen Verfolgung duplizieren |
| Risikohinweis | Abschnitt „Risikohinweis“ des Rückblicks | Höchstens 2 Einträge anzeigen, doppelte Haftungsausschlüsse filtern |

## Manuelle Befüllung oder lokale Vorschau

Die Vorlage akzeptiert weiterhin das vom Projekt erzeugte Markdown; die neue Kette übergibt zusätzlich `AnalysisResult.to_dict()` oder `market_review_payload`. Für den Debug des kompatiblen Fallbacks kann ein minimaler Einzelaktienbericht vorbereitet werden:

```markdown
## 🟢 贵州茅台 (600519)

> 2026-07-31 15:00 | 评分: **72** | 看多

### 📌 核心结论

**买入**: 趋势偏强，等待回踩支撑后分批执行。

| 持仓情况 | 操作建议 |
| --- | --- |
| 空仓者 | 等待回踩确认，不追高。 |
| 持仓者 | 继续持有，跌破止损位退出。 |

### 🎯 作战计划

| 点位类型 | 价格 |
| --- | --- |
| 理想买入点 | 1420-1450 |
| 次优买入点 | 1380-1400 |
| 止损位 | 1350 |
| 目标位 | 1580 |
```

Eine HTML-Vorschau erzeugen:

```python
from pathlib import Path
from src.share_image import ShareImageBranding, build_share_image_html

markdown_text = Path("reports/example.md").read_text(encoding="utf-8")
branding = ShareImageBranding(
    xiaohongshu_url="https://example.com/my-xiaohongshu",
    xiaohongshu_handle="@我的账号",
    xiaohongshu_qr_path="assets/my-xiaohongshu-qr.png",
)
html = build_share_image_html(markdown_text, branding=branding)
Path("share-preview.html").write_text(html, encoding="utf-8")
```

Für die Vorschau mit echten Laufzeitdaten wird das strukturierte Ergebnis übergeben:

```python
html = build_share_image_html(
    markdown_text,
    structured_payload=analysis_result.to_dict(),
)
```

Für die tatsächliche PNG-Umwandlung der Benachrichtigung wird weiterhin aufgerufen:

```python
from src.md2img import markdown_to_image

png_bytes = markdown_to_image(
    markdown_text,
    structured_payload=analysis_result.to_dict(),
)
```

Marktberichte sollten die von `MarketAnalyzer` erzeugten Abschnitte „Marktsignale, Indexstruktur, Sektor-Hauptlinien, Nachrichtenkatalysatoren, Handelsplan für morgen, Risikohinweis“ übernehmen; es wird nicht empfohlen, extern ein eigenes Feldnamen-Set zu erfinden, da die Vorlage solche Felder sonst als fehlend behandelt.

## Visuelle und inhaltliche Grenzen

- Auf-/Abwärtsfarben bevorzugen das im strukturierten Payload gespeicherte `color_scheme`; bei alten Datensätzen wird aus den Farbmarkierungen des Endberichts wiederhergestellt. Die Vorlage codiert Auf-/Abwärtsfarben nicht nach Marktregion hart.
- Kauf, Stop-Loss und Ziel im geteilten Bild behalten nur scanbare Preise oder „auf Stabilisierung warten“; die vollständigen Bedingungen bleiben immer im Originalbericht.
- Ohne echte Preisreihe werden keine Pseudo-K-Linien gezeichnet; oben bleibt nur der nicht-datenbasierte Branding-Glow.
- Xiaohongshu-URL, -Account, -ID und -QR-Code-Pfad stammen aus der Laufzeitkonfiguration; sind alle leer, wird der Xiaohongshu-Bereich nicht gerendert. GitHub zeigt fest die Repo-Kennzeichnung `ZhuLinsen/daily_stock_analysis` und erzeugt keinen QR-Code.
- Marktberichte hängen kein vollständiges Markdown mehr an, wenn das Kernmodul bereits erfolgreich extrahiert wurde; zusätzliche Detailabschnitte bleiben im Originalbericht, das geteilte Bild zeigt nur die strukturierte Zusammenfassung.
- Die Bildfußzeile enthält fest den Hinweis „KI-generiert, nur für Forschungs- und Austauschzwecke, keine Anlageberatung“.
