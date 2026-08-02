# Marktunterstützung und Grenzen

## Einzelaktien-suffix-only-MVP für japanische/koreanische Aktien (Issue #1718, Refs #1718)

Im aktuellen Stand werden manuell eingegebene Yahoo-Finance-Suffixcodes für japanische und koreanische Aktien unterstützt; sie gelangen in die bestehende Kette aus Einzelaktien-Analyse, Verlaufsspeicherung und Basisanzeige der Berichte. Die Web-Autovervollständigung enthält eine Reihe gängiger Seed-Indizes für japanische/koreanische Aktien und unterstützt die Suche nach Suffixcode, chinesischem/englischem Namen oder gängigen Aliasen.

Unterstützte Formate:

- Japan: `7203.T`, `6758.T`
- Korea KOSPI: `005930.KS`
- Korea KOSDAQ: `035720.KQ`

Einschränkungen und Grenzen:

- Bei der manuellen Eingabe eines nackten Codes wird zunächst der lokale/entfernte Aktienpool durchsucht; trifft ein nackter Code wie `005930`, `000660` japanische/koreanische Einträge wie `005930.KS`, `000660.KS`, wird die Analyse gemäß dem getroffenen Markt eingereicht; wird im Aktienpool nichts getroffen, greift weiterhin die bestehende Regel für 6-stellige Zifferncodes mit der Standard-Bedeutung A-Aktien und bleibt als nachvollziehbare Grenze der Marktmehrdeutigkeit erhalten.
- Die Suffix-Erkennung für japanische/koreanische Aktien ist in einem gemeinsamen Marktcode-Werkzeug konzentriert; Datenquellen-Routing, Markterkennung im Prompt, Handelstage-Kalender und die Nacktcode-Auflösung der Aktienindizes verwenden dieselbe Regelgruppe wieder, wodurch die Regelabweichung bei späteren Markterweiterungen reduziert wird.
- Tageslinien und grundlegende Echtzeit-/Nahezu-Echtzeit-Kursdaten japanischer/koreanischer Aktien laufen ausschließlich über `YfinanceFetcher`; A-Aktien-spezifische Datenquellen wie AkShare, Tushare, Efinance, Pytdx, Baostock werden nicht versucht; yfinance-Quotes tragen nach Möglichkeit Qualitätsmetadaten wie `market`, `currency`, `data_quality`, `missing_fields`.
- Die Fundamentaldaten nutzen den bestehenden leichten Offshore-yfinance-Pfad erneut; A-Aktien-spezifische Fähigkeiten wie Kapitalfluss, Dragon-Tiger-Liste und Branchensektoren werden auf `not_supported` herabgestuft; der Offshore-Fundamentalkontext markiert zudem provider, as_of, data_quality und fehlende Blöcke.
- Der Berichts-Prompt enthält nun Marktsemantik für japanische/koreanische Aktien, um das Aufpfropfen von A-Aktien-Konzepten wie Limit-Up/Limit-Down, Nordwärts-Kapitalfluss, Dragon-Tiger-Liste und Margin-Trading/Wertpapierleihgeschäft zu vermeiden.
- Die Handelstage-Kalender registrieren `jp: XTKS / Asia/Tokyo` und `kr: XKRX / Asia/Seoul`. Bei japanischen Aktien erkennt die reguläre Phase Vorhandel, während des Handels, Mittagspause, die Schlussauktion 15:25-15:30, Nachbörse und Nicht-Handelstage; bei koreanischen Aktien erkennt die reguläre Phase Vorhandel, während des Handels, die Schlussauktion 15:20-15:30, Nachbörse und Nicht-Handelstage. Fehlt der lokalen `exchange-calendars`-Version der jeweilige Kalender, bleiben die bestehenden fail-open/fail-closed-Semantiken unverändert.

Hinweise zu Kompatibilität und Rollback (für Treffer der strukturellen Erkennung):

- `#1815` fügt diesmal nur optionale Feldmetadaten im `yfinance`-Quote-/Fundamentalkontext hinzu (z. B. `market`, `currency`, `data_quality`, `missing_fields`, `provider`); LLM provider/model/base URL, Konfigurationsschema, Laufzeit-Umgebungsvariablen, Datenbankfelder, bestehende Cache-Serialisierung oder die Nachrichtenprotokollversion werden nicht geändert.
- Konfigurationssemantisch bezogen auf diesen PR werden keine provider, models oder base URLs neu hinzugefügt oder ersetzt; es gibt keine neuen Konfigurationsbereinigungs-/Migrationszweige; gespeicherte Konfigurationen bleiben unverändert; der Rollback-Weg ist das Zurückrollen dieses Commits.
- Die externe API-Grenze bleibt auf den bestehenden `yfinance`-fetch-Pfad (inklusive `Ticker`/`history`/`fast_info`) und die bestehende Fallback-Logik beschränkt; es wurde kein API-Gateway/host neu hinzugefügt oder migriert, und `YFINANCE_PRIORITY` ist der einzige betroffene sichtbare Parameter. Die Zuordnung der JP/KR-Hauptindizes zu den Yahoo-Symbolen lautet (verifizierbar):
  - Nikkei 225: `^N225` (<https://finance.yahoo.com/quote/%5EN225/>)
  - TOPIX: `^TOPX` (<https://finance.yahoo.com/quote/%5ETOPX/>)
  - KOSPI: `^KS11` (<https://finance.yahoo.com/quote/%5EKS11/>)
  - KOSDAQ: `^KQ11` (<https://finance.yahoo.com/quote/%5EKQ11/>)
  - Abhängige Version: `yfinance>=0.2.0` in `requirements.txt`; die Regressionsabdeckung liegt in `tests/test_yfinance_jp_kr_indices.py` und `tests/test_yfinance_hk_indices.py`.
- Kompatibilität und Rollback: `MARKET_REVIEW_REGION` behält gültige Komma-Teilmengen (z. B. `cn,us`) und das `both`-Verhalten in vollem Umfang bei; ungültige oder leere Werte fallen auf `cn` zurück; gespeicherte Konfigurationen werden nicht geleert oder migriert.
- Laufzeitgrenze: Die JP/KR-Indizes werden nach der fail-open-Konvention von market_review einzeln abgerufen; der Fehlschlag eines einzelnen Postens blockiert die übrigen Indizes und anderen Märkte nicht; wenn für beide Märkte keine verfügbaren Hauptindex-Kursdaten vorliegen, wird lokal sichtbar `None/leer` zurückgegeben und der Hauptfluss kann weiterhin nach den übrigen Märkten ausgeben oder direkt degradieren.
- Basis der Kompatibilitätsverifikation: Kurs-/Fundamentalkontexte werden in `data_provider/base.py` und `realtime_types.py` nach der bestehenden `getattr`/optional-Feld-Konvention nachgelagert durchgereicht, ohne die neuen Felder erzwungen zu lesen oder zu schreiben; es gibt keine Konfigurationsmigrationsskripte, und es wurden keine Änderungen an den provider/model/base-URL-Fallbackpfaden beobachtet.
- Rollback-Weg: Falls die neuen Metadatenfelder an irgendeiner Seite Kompatibilitätsprobleme verursachen, können die Felder zunächst ignoriert und die bestehende Kette aus Markterkennung + Kursanzeige weiterlaufen; bei Bedarf diesen Commit zurücksetzen oder durch Entfernen der `jp/kr`-`MarketSymbol`- und Routenerweiterungen das alte Verhalten wiederherstellen.

Nicht zugesagte Punkte:

- Keine Zusage für Echtzeit-Kursdaten; Yahoo-Finance-Daten können verzögert sein oder Felder fehlen.
- Keine Zusage für vollständige Fundamentaldaten, Branchen/Sektoren, Marktbreite oder Anzahl gestiegener/gefallener Titel. Das JP/KR-Marktreview v1 liefert nur Hauptindizes, Nachrichten-Hinweise und eine Template-/LLM-Review, keine japanisch/koreanische Marktbreite oder Sektor-Rankings.
- Keine Zusage für eine vollständige Aktienliste des gesamten japanischen/koreanischen Markts; die Web-Autovervollständigung deckt derzeit nur die gängigen Werte in den mitgelieferten Seed-Indizes ab (auf je ca. 30 führende Werte erweitert); bei fehlendem Treffer können Suffixcodes weiterhin manuell eingegeben werden.
- Der Portfolio erhält keine vollständige Berechnungsbasis für JPY/KRW-Wechselkurse, Kosten und Marktkapitalisierung; die zugehörigen Felder geben nur den Markttyp frei, um die Ablehnung durch Frontend-/Backend-Validierung zu vermeiden.

Rollback-Weg: Markterkennung für `jp/kr`, Handelstage-Kalender-Registrierung, YFinance-Routenerweiterungen, Web/API-Typfreigaben und die japanisch/koreanischen Seed-Indizes unter `scripts/stock_index_seeds/` entfernen sowie die Fähigkeitsdeklarationen in diesem Dokument löschen.

## Marktreview v1 für japanische/koreanische Aktien (Issue #1815 Phase 2)

Das Marktreview `MARKET_REVIEW_REGION` erhält neu `jp` und `kr` und bezieht sie in die Multi-Markt-Reihenfolge von `both` ein: `cn,hk,us,jp,kr`.

Umfang der Unterstützung:

- `jp`: über Yahoo Finance werden der Nikkei 225 `^N225` und der TOPIX `^TOPX` bezogen und ein Marktreview für japanische Aktien ausgegeben. Verifizierbare Seiten:
  - `^N225`: <https://finance.yahoo.com/quote/%5EN225/>
  - `^TOPX`: <https://finance.yahoo.com/quote/%5ETOPX/>
- `kr`: über Yahoo Finance werden KOSPI `^KS11` und KOSDAQ `^KQ11` bezogen und ein Marktreview für koreanische Aktien ausgegeben. Verifizierbare Seiten:
  - `^KS11`: <https://finance.yahoo.com/quote/%5EKS11/>
  - `^KQ11`: <https://finance.yahoo.com/quote/%5EKQ11/>
- Die Web-Einstellungsseite akzeptiert über das Textfeld `MARKET_REVIEW_REGION` kommaseparierte Teilmengen (z. B. `cn,jp`, `cn,us,jp,kr`); die Handelstage-Prüfung filtert die am jeweiligen Tag geöffneten Märkte aus `both` gemäß `XTKS / Asia/Tokyo` und `XKRX / Asia/Seoul`.
- Review-Strategie, Nachrichten-Suchbegriffe, Prompt-Marktsemantik und chinesisch-/englischsprachige Benachrichtigungstitel werden jeweils über ein eigenes JP/KR-Profile behandelt.

Hinweise (Kompatibilitäts- und Abnahmekriterien):

- Die Online-Datenverfügbarkeit stammt aus den Yahoo-Finance-Indexseiten und dem API-Vertrag; die aktuelle Implementierung deckt nur das Index-Routing und das Degradierungsverhalten in `data_provider/yfinance_fetcher.py` ab; es wird keine Stabilitätszusage für die Echtzeit-Kursdatenkonnektivität gegeben.
- Die zu diesem Ziel gehörige lokale automatisierte Verifikation nutzt standardmäßig Offline-Regression: `tests/test_yfinance_jp_kr_indices.py`, `tests/test_yfinance_hk_indices.py` (gemeinsame Zuordnung/Rollback) und `tests/test_trading_calendar.py` (Handelstage-Filter). Für eine zusätzliche Echtzeit-Verfügbarkeitsprüfung können in einer vernetzten Umgebung die oben genannten Yahoo-Finance-Seiten direkt für eine einmalige Stichprobe aufgerufen werden.

- Externe Kompatibilitätsgrenze (Standardannahme der aktuellen Implementierung):
  - Datenquelle: `yfinance` (Versionuntergrenze `yfinance>=0.2.0` in `requirements.txt`)
  - Langfristige Einschränkung: `^N225`, `^TOPX`, `^KS11`, `^KQ11` müssen bei Yahoo Finance eine durchsuchbare Quote-Seite haben; nicht durchsuchbar gilt als Index-Ebene-unverfügbar, und der `market_review`-fail-open-Mechanismus degradiert auf die Ausgabe der vorhandenen Märkte, ohne den Hauptfluss zu unterbrechen.
- Kompatibilitätsverifikation (verifizierbar):
  - <https://finance.yahoo.com/quote/%5EN225/>
  - <https://finance.yahoo.com/quote/%5ETOPX/>
  - <https://finance.yahoo.com/quote/%5EKS11/>
  - <https://finance.yahoo.com/quote/%5EKQ11/>
  - Reproduzierbarer Online-Verifikationsbefehl (optional):
```bash
python - <<'PY'
from yfinance import Ticker
for symbol in ("^N225", "^TOPX", "^KS11", "^KQ11"):
    data = Ticker(symbol).history(period="5d")
    print(symbol, "rows", len(data))
PY
```

Grenzen:

- Das JP/KR-Marktreview v1 liefert keine Anzahl gestiegener/gefallener Titel, kein Limit-Up/Limit-Down, keine Branchen-/Sektor-Rankings und keine Kapitalfluss-Statistik; im strukturierten Payload erscheint `breadth` weiterhin nur, wenn Marktbreitendaten vorhanden sind.
- Fehlschläge beim Abruf eines einzelnen JP/KR-Index werden nach der bestehenden yfinance-fail-open-Logik übersprungen und ziehen weder andere Indizes noch andere Märkte in Mitleidenschaft.
- Fehlt `exchange-calendars` der jeweilige Börsenkalender, gelten weiterhin die bestehenden fail-open/fail-closed-Semantiken für Handelstage.

Rollback-Weg: `jp` / `kr` aus den gültigen Werten von `MARKET_REVIEW_REGION`, den Web-Einstellungs-Enums, MarketProfile/MarketStrategy, `_MARKET_REVIEW_MARKETS` und aus diesem Dokument entfernen.

## Taiwan-Einzelaktienunterstützung (suffix-only, Issue #1772 / #1777)

Im aktuellen Stand werden manuell eingegebene Yahoo-Finance-Suffixcodes für taiwanische Aktien unterstützt; sie gelangen in die bestehende Kette aus Einzelaktien-Analyse, Verlaufsspeicherung, Berichts-Rendering, DecisionSignal, Portfolio und Intelligence. TWSE-notierte Aktien verwenden das Suffix `.TW`, TPEx-notierte (OTC) Aktien das Suffix `.TWO`; beide werden zu demselben Marktlabel `tw` zusammengeführt.

Die Taiwan-Aktienkette hat sich in jüngster Zeit von einem frühen MVP zu einem erstklassigen Einzelaktien-Analysemarkt entwickelt: Markterkennung, Datenrouting, Handelstage-Kalender/Marktphase, YFinance-Tageslinien und Basiskurse, Hauptindizes, Service-Schicht-/API-/Web-Marktenums, TWD-Währungsangabe, Berichtsblock der drei institutionellen Anlegertypen und LLM-Prompt-Konsum sind alle angebunden. Als Grenzen bleiben bestehen: der taiwanische Aktienpool-Seed/die Autovervollständigung, das Marktreview `MARKET_REVIEW_REGION=tw`, die Market-Light-Ampelwarnungen für den Gesamtmarkt sowie vollständige taiwanische Marktbreite/Sektor-Rankings sind noch nicht aufgenommen.

Unterstützte Formate:

- Notiert (TWSE): `2330.TW`, `0050.TW`
- OTC (TPEx): `6488.TWO`, `5483.TWO`
- Die Code-Basis ist 4-6-stellig (Stammaktien 4-stellig, ETF/sonstige bis 6-stellig, z. B. `00878.TW`, `006208.TW`), also breiter als die 4-5 Stellen des japanischen `.T`.

Einschränkungen und Grenzen:

- **Streng suffix-only**: Nackte Codes ohne Suffix wie `2330`, `00878` gelangen nicht in die Taiwan-Marktsemantik (`detect_market` / `get_market_for_stock` geben `tw` nur bei explizitem `.TW`/`.TWO`-Suffix zurück). Aktuell ist keine taiwanische Aktienindex-/Seed-Auflösung eingebaut, und die Web-Autovervollständigung verspricht keinen vollständigen taiwanischen Aktienpool; bei fehlendem Treffer bitte den vollständigen Suffixcode manuell eingeben.
- Tageslinien und grundlegende Echtzeit-/Nahezu-Echtzeit-Kursdaten taiwanischer Aktien laufen ausschließlich über `YfinanceFetcher`; A-Aktien-spezifische Datenquellen wie AkShare, Tushare, Efinance, Pytdx, Baostock werden nicht versucht.
- Die Fundamentaldaten nutzen den bestehenden leichten Offshore-yfinance-Pfad erneut; der Block `institution` konsumiert zusätzlich die Daten der drei institutionellen Anlegertypen für Taiwan und rendert sie in den Bericht; A-Aktien-spezifische Fähigkeiten wie Kapitalfluss, Dragon-Tiger-Liste und Branchensektoren werden auf `not_supported` herabgestuft.
- Der Berichts-Prompt enthält nun Taiwan-Marktsemantik (Neuer Taiwan-Dollar, die drei institutionellen Anlegertypen, TWSE/TPEx ±10 % Limit-Up/Limit-Down) und injiziert den Netto-Kauf-/Verkaufsüberschuss der drei institutionellen Anlegertypen in den LLM-Analysekontext, um das Aufpfropfen von A-Aktien-Konzepten wie Nordwärts-Kapitalfluss und Dragon-Tiger-Liste zu vermeiden.
- Der Handelstage-Kalender registriert `tw: XTAI / Asia/Taipei`. TWSE handelt durchgehend 09:00–13:30 ohne Mittagspause; die Schlussauktion 13:25–13:30 ist als 5-Minuten-Heuristikfenster modelliert (`_CLOSING_AUCTION_WINDOW_MINUTES["tw"]=5`, `market_phase` kann `closing_auction` zurückgeben). Auch für JP/KR wurden die Schlussauktionsfenster nach den regulären Handelszeiten ergänzt (JP 15:25-15:30, KR 15:20-15:30). Fehlt der lokalen `exchange-calendars`-Version der jeweilige Kalender, bleiben die bestehenden fail-open/fail-closed-Semantiken unverändert.
- Als Hauptindizes werden der gewichtete Index `^TWII` und der OTC-Index `^TWOII` bereitgestellt.
- Datenebene für Kauf-/Verkaufsüberschuss der drei institutionellen Anlegertypen (institutional flows): `TwInstitutionalFetcher` (`data_provider/tw_institutional_fetcher.py`) liefert für die notierten (TWSE T86, Legacy-`rwd`-Endpunkt) und die OTC- (TPEx OpenAPI) Werte die täglichen Kauf-/Verkaufsüberschüsse von Auslandsinvestoren, Investment Trusts, Eigenhändlern und den drei institutionellen Anlegertypen (Einheit: **Stückzahl**; es wird ein Tagescache über den gesamten Markt nach Datum+Markt angelegt und daraus die Einzelaktien gefiltert; die Umrechnung der Minguo-Jahreszahlen von TPEx in westliche Jahreszahlen ist durch Unit-Tests abgedeckt). Schnittstellenfehler/Rate-Limits/leere Antworten/fehlende Felder geben durchgängig **fail-open** keine Daten zurück und unterbrechen die Analyse nicht; dies wirkt nur auf `.TW`/`.TWO` und verändert die bestehenden Marktabläufe nicht. Die Datenquelle sind offene Regierungsdaten unter der „Government Data Open Licensing Terms Version 1" (OGDL v1, erlaubt kommerzielle Nutzung und Weiterverbreitung, mit Quellenangabe).
- Der Fetcher für die drei institutionellen Anlegertypen verfügt über einen durchstichsicheren Concurrency-Cache und einen auf TWSE/TPEx aufgeteilten Circuit-Breaker-Schutz; die TPEx OpenAPI bedient nur den neuesten Handelstag; eine übergebene, vom Servicedatum abweichende ausdrückliche Datumsangabe führt fail-open zu „keine Daten", damit falsche Tagesdaten nicht still in den Bericht gelangen.
- Finanzbeträge taiwanischer Aktien werden mit TWD -> „Neuer Taiwan-Dollar" gekennzeichnet, um nicht in den im A-Aktien-Kontext standardmäßigen „Yuan" zu fallen.

Nicht zugesagte Punkte:

- Keine Zusage für Echtzeit-Kursdaten; Yahoo-Finance-Daten können verzögert sein oder Felder fehlen.
- Keine Zusage für vollständige Fundamentaldaten, Branchen/Sektoren, Marktbreite, Anzahl gestiegener/gefallener Titel oder ein Taiwan-Marktreview; `MARKET_REVIEW_REGION` akzeptiert weiterhin nur `cn/hk/us/jp/kr/both` oder kommaseparierte Teilmengen dieser Märkte.
- Taiwan-Aktienindizes/-Seeds und die Web-Autovervollständigung sind noch nicht vollständig angebunden; die MarketRegion der Warnungen und die Market-Light-Warnungen des Backends bleiben bei `cn/hk/us` und enthalten kein `tw`.
- Der Portfolio erhält keine vollständige Berechnungsbasis für TWD-Wechselkurse, Kosten und Marktkapitalisierung; das Taiwan-Portfolio ist aktuell ein Markt mit partieller Bewertung (partial valuation).

Rollback-Weg: Markterkennung für `tw`, Handelstage-Kalender-Registrierung, YFinance-Routenerweiterungen, Datenebene/Berichts-Konsum der drei institutionellen Anlegertypen, TWD-Kennzeichnung, Service-Schicht-/API-Marktenums sowie Frontend-Markttyp-Freigaben entfernen und die Fähigkeitsdeklarationen in diesem Dokument löschen.

## Portfolio- und Market-Light-Grenzen für japanische/koreanische Aktien (Issue #1815 Phase 3)

Das Portfolio lässt JP/KR-Konten, Transaktionen und Positions-Snapshots in die bestehende Kette; Konten-/Positions-Snapshots werden jedoch als `data_quality=partial` markiert und über `limitations` ausdrücklich mit `realtime_quote_best_effort`, `fx_and_cost_basis_partial`, `sector_and_risk_metrics_limited` gekennzeichnet; eine vollständige Berechnungsbasis für JPY/KRW-Wechselkurse, Kosten, Marktkapitalisierung, Branchenkonzentration oder Portfoliorisikokennzahlen wird nicht zugesagt.

- JP/KR-Konten, Transaktionen, Kassenflüsse und Corporate-Action-APIs bleiben erstell-/abfragbar; aktuell werden keine JPY/KRW-Wechselkursquellen, Steuermodelle, Prüfungen von Handelseinheiten/Mindestpreisstufen oder Branchenzuordnungen neu hinzugefügt.
- Market-Light-Snapshots und Market-Light-Warnungen unterstützen weiterhin nur `cn` / `hk` / `us`.
- Das Dropdown für den Warnungsmarkt im Web zeigt `jp` / `kr` nicht an; der Backend-`normalize_market_region()` liefert für `jp` / `kr` einen expliziten unsupported-Fehler.
- Auf der Web-Einstellungsseite wird `MARKET_REVIEW_REGION` von einem festen Enum-Dropdown zu einer Freitexteingabe umgestellt, um kommaseparierte Teilmengen wie `cn,us,jp`, `cn,hk,us` zu speichern; diese UI-Änderung betrifft nur die Marktreview-Konfiguration, nicht die Marktenums der Market-Light-Warnungen.
- Die bestehenden Werte `cn`, `hk`, `us` von `MARKET_REVIEW_REGION` können unverändert beibehalten werden; wer die Drei-Markt-Reviewgrenze von `both` vor der JP/KR-Erweiterung beibehalten möchte, sollte auf `cn,hk,us` umstellen; nur wer eine Fünf-Markt-Review einbeziehen möchte, verwendet weiterhin `both` oder konfiguriert explizit `cn,hk,us,jp,kr`.
- Diese Runde der Grenzkonvergenz ändert weder die Persistenzsemantik von LLM Provider / Model / Base URL noch führt sie Bereinigungen oder Rückschreibungen von Standardmodellen oder Laufzeitkonfiguration durch; Konfigurationsaktualisierungen bleiben **atomare Upserts** (`ConfigManager.apply_updates`); Speichern/Importieren schreibt nur die übergebenen Schlüssel, und nicht übergebene alte Werte wie `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, `OPENAI_BASE_URL` bleiben erhalten und werden nicht geleert.
- Direkt verifizierbarer Konfigurationskompatibilitätsnachweis: In dieser Runde wurden keine externen provider/Models/Base-URLs neu hinzugefügt oder ersetzt; weiterhin werden die LiteLLM-OpenAI-kompatible Route (<https://docs.litellm.ai/docs/providers/openai_compatible>), die OpenAI-Chat-Completions-Request-Form (<https://platform.openai.com/docs/api-reference/chat/create>) sowie die zentral gepflegten offiziellen Quelllinks der Provider im [Leitfaden zur Konfiguration von LLM-Anbietern](llm-providers.md#offizielle-quellen-und-kompatibilität) verwendet. Das aktuelle Laufzeit-Abhängigkeitsfenster richtet sich nach `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` in `requirements.txt`; alte Konfigurationen haben kein Migrationsskript oder Bereinigungszweige, und Speichern/Importieren schreibt weiterhin nur die in diesem Commit übergebenen Schlüssel über `ConfigManager.apply_updates`. Der Rollbackpfad ist, `MARKET_REVIEW_REGION` in der `.env`/im Konfigurations-Backup vor der Änderung wiederherzustellen oder direkt diesen PR zu reverten; nicht übergebene bestehende Laufzeitkonfigurationen wie `LITELLM_CONFIG`, `LLM_CHANNELS`, `LLM_OPENAI_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `VISION_MODEL`, `OPENAI_*` benötigen keine Migration. Als Regressionsnachweis dienen `tests/test_system_config_service.py::SystemConfigServiceTestCase::test_update_market_review_region_does_not_trigger_runtime_model_cleanup` und `tests/test_config_env_compat.py::test_market_review_region_updates_do_not_change_llm_provider_model_contract`.
- Maßstab für sichtbare Web-UI-Nachweise: Wenn der Zielbereich der Market-Light-Warnung auf „Gesamtmarkt" umgeschaltet wird, zeigt das Dropdown der Marktregion nur A-Aktien, Hongkong-Aktien und US-Aktien an, keine japanischen/koreanischen Aktien; auf der Einstellungsseite wird `MARKET_REVIEW_REGION` als Textfeld für kommaseparierte Werte gerendert. Das Repository speichert keine einmaligen Screenshot-Nachweise; als Ersatznachweise dienen die Assertions in `apps/dsa-web/src/components/alerts/__tests__/AlertRuleForm.test.tsx`, `apps/dsa-web/src/components/settings/__tests__/SettingsField.test.tsx` und `apps/dsa-web/tests/system_config_i18n.test.ts`.

Rollback-Weg: Die Erweiterungen `data_quality` / `limitations` der Portfolio-Snapshots entfernen und die alten Grenzangaben der Warnungs-Frontend/Backend-Marktenums wiederherstellen; für einen vollständigen Rollback die `jp/kr`-Markterkennung, Handelstage-Kalender-Registrierung, YFinance-Routenerweiterungen, Web/API-Typfreigaben und die japanisch/koreanischen Seed-Indizes unter `scripts/stock_index_seeds/` entfernen sowie die Fähigkeitsdeklarationen in diesem Dokument löschen.
