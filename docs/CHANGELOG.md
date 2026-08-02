# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) page.

## [Unreleased]
- [Fix] `offline_test_suite` von `scripts/ci_gate.sh` fügt für `pytest -m "not network"` `--timeout=120 -o timeout_method=thread` und `-o faulthandler_timeout=300` hinzu: Ein einzelner Test (einschließlich seines Teardowns), der länger als 2 Minuten dauert, schlägt direkt fehl; dauert ein einzelner Test (einschließlich seines Teardowns) länger als 5 Minuten, werden alle Thread-Stacks auf stderr gedumpt. Dazu kommt die neue Abhängigkeit `pytest-timeout>=2.3.0` in `.github/requirements-ci.txt`. Issue #2131 berichtete, dass der backend-gate in der Nähe des AlphaSift-Hotspot-Falls intermittierend ohne Traceback hängen blieb, bis er von GitHub Actions abgebrochen wurde. Dieser Fix stellt sicher, dass jeder künftige CI-Hang eine lokalisierbare Fehlermeldung oder einen Post-mortem-Stack hinterlässt, statt stillschweigend zu enden. Gleichzeitig wurden `Install backend gate dependencies` und `setup-python cache-dependency-path` in `.github/workflows/docker-publish.yml` an die backend-gate-Abhängigkeitsinstallation von `ci.yml` angeglichen, damit der Release-Workflow beim Ausführen desselben `./scripts/ci_gate.sh` nicht wegen fehlender `pytest-timeout` direkt fehlschlägt.
- [Fix] Die Auswahlstrategie-Leiste zeigt die vollständige chinesische Strategieliste stabil an und behält den Einstieg für die benutzerdefinierte Strategie-ID.
- [Fix] Die Detailansicht der Auswahl-Hotspots verwendet einheitlich chinesische Geschäftstexte und zeigt keine internen Klassennamen, Feldnamen oder Rohfehler der Datenquelle mehr an.
- [Verbesserung] Nach der Auswahl eines Hotspots werden zuerst die vorhandene Zusammenfassung der Rangliste und die Kernaktien angezeigt, im Hintergrund wird die vollständige Detailansicht ergänzt, und das Wartelimit für eine einzelne Hotspot-Quelle wird auf 8 Sekunden begrenzt.
- [Fix] Beim Aktualisieren der Hotspot-Rangliste mit beibehaltenem aktuellem Thema wird die Detail-Cache parallel umgangen und das Thema neu geladen, damit die neue Rangliste nicht weiter mit alten Routen und Bestandteilen kombiniert wird; bei nutzbarer Detailqualität und vollständigen Feldern werden die fehlgeschlagenen Versuche der darunterliegenden Datenquelle nicht mehr angezeigt.
- [Verbesserung] Hotspot-Bestandsanteile werden parallel aus EastMoney- und Tonghuashun-Daten geholt und nach fester Datenquellen-Priorität zusammengeführt; AkShare-Aufrufe nutzen die beendbaren Unterprozess-Timeouts von DSA, Tonghuashun-HTTP-Aufrufe setzen connect/read-Timeouts und begrenzen aktive Tasks über prozessweite Parallelitäts-Slots, wobei Worker vor der Rückgabe wieder freigegeben werden; Themendetails können bei Bedarf die Datenquellen-Priorität, Zeitfilterung, Cache und Request-Zusammenführung des nativen DSA-Suchdiensts wiederverwenden, um sichere, mit Links versehene aktuelle Meldungen zu ergänzen; echte Anbieteraufrufe verwenden ratenbegrenzte, beendbare und wiederverwendbare Unterprozesse und komprimieren Zusammenfassungen lokal, um zusätzliche LLM-Wartezeiten und Downgrade-Hinweise zu vermeiden; die explizite Suchanreicherung wird weder in den geteilten Hotspot-Detail-Cache noch in den Web-Seitencache geschrieben.
- [Fix] Die Endrotation der Auswahl behandelt die Analysator-Eingabereihenfolge als maßgeblich und erhält die Reihenfolge gleich bewerteter Kandidaten; die Hotspot-Nachrichtenanreicherung hängt `route` bzw. die ursprüngliche `timeline` an, die Suche mit gleichem Schlüssel erlaubt nur dem Cache-Owner, die Anbieterkette zu starten, und auch fehlgeschlagenes Starten oder Aufräumen von Unterprozessen gibt die globale Kapazität frei; die positive Timeout-Konfiguration des Standard-Anbieters für Hotspots überschreibt Sektoren, Bestandteile und den direkten Detail-Fallback und reicht die verbleibende harte Frist weiter; selbst bei deaktiviertem äußerem Budget bleibt die Einzelquellen-Sicherheitsgrenze erhalten; die aktive Nachrichtensuche überspannt Cache-Wartezeit, Neukonkurrenz und Anbieterausführung mit derselben absoluten Frist und unterscheidet gültige leere Ergebnisse von Laufzeitfehlern.
- [Verbesserung] Die Auswahlseite strafft doppelte Erklärungen und faltet Aufgabenkennung, Snapshot-Statistik und Sortierdiagnose in die Laufdetails.
- [Neues Feature] SkillAggregator generiert begrenzte Laufzeitgewichte auf Basis echter Skill-Outcome-Buckets, die die Schwelle von 30 eigenständig erfüllten evaluated Ergebnissen erfüllen, und zwar mit Beta-Prior-Kontraktion, unable-Bestrafung und mehrperiodiger Evidenzgewichtung; fehlende, zu kleine Stichproben oder anomale Statistiken bleiben neutral.
- [Verbesserung] Der vom AlphaSift-Referenzprojekt übernommene Auswahlkern und die Strategien werden offiziell in DSA übernommen, einheitlich über `ScreeningService`, `SCREENING_ENABLED` und `/api/v1/screening`, unter Beibehaltung der Apache-2.0-Zuordnung und der Quellversionsaufzeichnung.
- [Neues Feature] Integrierte Auswahlergebnisse werden per `run_id` in der DSA-Datenbank persistiert, neue Laufzeithistorie- und Datenquellen-Historie-APIs werden ergänzt, der DSA-Announcement-Ereigniskontext und dessen Suchcache angebunden, und Kandidaten können zusammen mit den auf die Screening-Strategie abgebildeten Skills an die DSA-Einzelaktien-Tiefenanalyse übergeben werden.
- [Fix] Outcome-Kandidaten werden fair nach dem Zeitpunkt des letzten Versuchs geplant, damit ständig neu hinzukommende fehlende Keys alte `pending`-Outcomes nicht dauerhaft von Wiederholungen ausschließen.
- [Neues Feature] Neue schreibgeschützte Skill-Opinion-Performance-Statistiken, unabhängig aggregiert nach Skill, Horizon und Outcome-Engine-Version; bei weniger als 30 evaluated Stichproben werden nur beobachtende Zählwerte zurückgegeben, keine Performance-Kennzahlen oder angepassten Laufzeitgewichte.
- [Fix] Liefert das Auswahl-Hauptmodell leeren Inhalt, Nicht-JSON oder eine Struktur mit geringer Abdeckung, werden weiterhin Backup-Modelle versucht; schlagen alle fehl, wird der Status des deterministischen Faktor-Rankings klar angezeigt. Das endgültige JSON muss im `content`- oder `output`-Block liegen; `reasoning_content` (Chain-of-Thought) wird als interne Hilfsgröße behandelt und nicht als Endergebnis.
- [Verbesserung] Die Web-Auswahl erzeugt mit einem anonymen Browser-Seed und der Lauf-ID Kandidatenkombinationen pro Lauf aus dem begrenzten Nah-Punkte-Pool nach der Endbewertung; ist Web Storage nicht verfügbar, wird derselbe temporäre Seed im Seitenspeicher der Session wiederverwendet; die lokale Bewertung deckt die vollständige Shortlist ab, die Fernanalyse hält das Mengenlimit ein, und nur Kandidaten, die dieselbe Nachanalyse abgeschlossen haben, nehmen an der Rotation teil; die vordere Hälfte des ursprünglichen Top-N, deutlich führende Kandidaten, harte Filter, Risiko-Neins und Bewertungen bleiben unverändert.
- [Verbesserung] Die Hotspot-Ranglistenaktualisierung und der lange Auswahlprozess entkoppeln das gegenseitige serielle Warten; Hotspot-Details werden nach Auswahl bei Bedarf geladen; die Auswahl verwendet standardmäßig einen erfolgreichen Gesamtmarkt-Snapshot innerhalb von 5 Minuten mit konsistenter Datenquellen-Priorität wieder, auch Ergebnisse von Backup-Quellen in derselben Quellenkette können wiederverwendet werden, und die Phasen Snapshot, Kandidatenkontext, LLM-Neubewertung, Endbewertung und Nachrichten-Ereignisanreicherung werden im Hintergrundtask angezeigt.
- [Fix] Die Tageslinien-Anreicherung der Auswahl injiziert jetzt einen request-spezifischen DSA-first-Fetcher, ersetzt keine prozessweiten Funktionen mehr temporär und vermeidet so, dass überlappende Requests Wrapper leaken oder Fallbacks doppelt ausführen; mehrere Nachanalysatoren stufen nach dem neuesten Score um, der Fernanalyse-Status folgt den tatsächlich eingereichten Kandidaten, überzählige Kandidaten werden einheitlich als `skipped` erfasst, und externe Antworten können nicht eingereichte Kandidaten nicht überschreiben.
- [Fix] Vereinheitlicht die Auflösung lokaler Tageskandidaten und gleichwertiger Codewindows für äquivalente Aktiencodes; kollidierende Codes von Shanghai-/Shenzhen-Börsen werden nicht mehr auf Bare Codes zurückgestuft, Backtests akzeptieren nur Startpunkte, die durch Snapshot oder Handelskalender bestätigt sind, und bevorzugen bei gleichem Startpunkt das vollständige Einzel-Codewindow.
- [Neues Feature] Neuer Kernservice, der `skill_opinion_outcomes` auf Basis der Signale der jeweiligen individuellen SkillAgent-Instanz, der versionierten Engine und lokal gespeicherter gleichwertiger Tagesfenster berechnet und persistiert.
- [Fix] #1970: Das Deaktivieren der Authentifizierung ist ein hochriskanter Vorgang; selbst mit gültigem Session-Cookie wird die erneute Eingabe des aktuellen Admin-Passworts zur zweiten Bestätigung erzwungen; der Disable-Zweig von `auth_update_settings` im Backend läuft einheitlich über die currentPassword-Prüfung und gibt bei Rate-Limit ebenso wie der Enable-Pfad 429 zurück; `AuthSettingsCard` im Frontend blockiert beim Deaktivieren der Authentifizierung das Absenden, wenn das aktuelle Passwort fehlt, und zeigt einen Inline-Hinweis.
<!-- Format neuer Einträge: - [Typ] Beschreibung (Typwerte: Neues Feature/Verbesserung/Fix/Dokumentation/Tests/chore)-->
<!-- Jeder Eintrag wird als eigene Zeile am Ende dieses Abschnitts angehängt, ohne Kategorietitel, um Konflikte beim Zusammenführen zu minimieren -->
- [Fix] `stdout_preview` / `stderr_preview` der lokalen CLI maskieren kurze Credentials gemäß den unabhängigen Verträgen für Umgebungsvariablen, JSON, YAML/Log-Skalare und URLs, damit API-Keys, Secrets oder Tokens unter 32 Zeichen nicht in Diagnosen gelangen; normale Felder werden nur nach sensiblen Namen beurteilt, sensible YAML-Skalare ohne Anführungszeichen werden fail-closed bis zum Zeilenende maskiert (refs #1784).
- [Verbesserung] Bildberichte verwenden jetzt eine eigenständige 1080px-Einzelaktien-Entscheidungskarte und eine hochdichte Markt-Rückblick-Karte, die Daten vorrangig aus `AnalysisResult.to_dict()` / `market_review_payload` präzise befüllen und einen Markdown-Fallback behalten; die Einzelaktien-Grafik ergänzt Konfidenzgrad, Trend-Score, Abweichungsrate und Phasen-Beobachtungsfenster, die Markt-Grafik ergänzt Ampel-Aufschlüsselung, starke/schwache Sektoren, Kapitalbeobachtung, Beobachtungs-/Meidungsrichtungen und Strategie-Ungültigkeitsbedingungen; Xiaohongshu-Account und QR-Code werden zu abschaltbarer/ersetzbarer Deployment-Konfiguration, und die GitHub-Repo-Adresse wird direkt angezeigt; Web-Historienberichte erzeugen das Bild vorab und lösen beim Klick synchron die System-Freigabe aus, mit Download-Fallback und Playwright-Rendering-Engine.
- [Fix] Unter dem NLTK-3.10-Importschutz verwechselte das PyInstaller-Freeze-Paket die eingebaute `_internal`-Standardbibliothek mit einem Modul im aktuellen Verzeichnis und startete fehl; neu wird ein Kompatibilitäts-Runtime-Hook ergänzt, der nur im Freeze-Paket vor NLTK ausgeführt wird und von den Windows-/macOS-Paketierungsskripten einheitlich angebunden ist.
- [Fix] Das geteilte Bild führt historische strukturierte Daten und Markdown feldweise zusammen, nutzt das persistierte Payload für mehrere Märkte regionenweise wieder, blendet nicht verfügbare Marktampel-Dimensionen aus und erhält `MARKET_REVIEW_COLOR_SCHEME`; die chinesischen, englischen und koreanischen Vorlagen folgen der Berichtssprache, und bei fehlgeschlagener nativer Web-Freigabe wird automatisch auf den Download zurückgegriffen.
- [Fix] Der Feishu-`FEISHU_SEND_AS_FILE`-Berichtszweig bereinigt vor dem Schreiben oder Hochladen einer `.md`-Datei einheitlich die versteckten `[dsa-market-region]`-Metadaten, damit ein Ein-Markt-Rückblick das interne Regionskennzeichen nicht an Endnutzer leakt; die Desktop-Runtime blendet den Web-Share-Button standardmäßig aus, damit Windows-/macOS-Pakete ohne mitgelieferten Renderer beim Laden der Seite nicht direkt nach der Vorabholung des geteilten Bildes in den Fehlerzustand geraten.
- [Fix] `redact_diagnostic_text()` verschluckt bei der Form `export SENSITIVE_ENV=$(printenv OTHER_SECRET) session_id=...` nicht mehr `session_id` und andere nicht sensible Diagnosefelder am Zeilenende, weil sich der zweite `$(...)`-Scan mit dem ersetzten Bereich des ersten sensiblen Zuweisungsdurchgangs überlappt hatte; der zweite Scan nutzt nun die bereits ersetzten Span-Listen des ersten Durchgangs als vertrauenswürdige Skip-Tabelle und versieht den führenden Regex der prior-head/prior-semicolon-Zweige mit dem Präfix `(?:export[ 	]+)?`, sodass `export FOO=$(...)` und `FOO=$(...)` in allen Zweigen gleich behandelt werden (behebt den PR #2118 Review-Blocker OR-COR-7c0a5d41).
- [Fix] `LongbridgeFetcher._compute_volume_ratio` hat bei `history_candlesticks_by_offset` die beiden Positionsparameter `time` und `count` vertauscht; die PyO3-Konvertierungsschicht warf `argument 'time': 'int' object cannot be converted to 'PyDateTime'`, die Ausnahme wurde von try/except stillschweigend in ein DEBUG-Log verschluckt, wodurch das Volume-Ratio-Feld in der Echtzeit-Kurskette für Hongkong-/US-Aktien stets None war und sich extern als „Keine Daten abgerufen" äußerte; jetzt wird mit adaptiven Keyword-Argumenten aufgerufen, die sowohl den SDK-Vertrag von 0.2.74 (forward, time, count) als auch von 4.x (forward, count, time) unterstützen, und beide Versionen sind mit Regressionstests gemäß dem Keyword-Argument-Vertrag abgedeckt (fixes #2100)

## [3.28.0] - 2026-07-26

### Release-Highlights

- feat: Die Multi-Agent-Mehrstrategien-Integration unterstützt geschichtete Deliberation, mediator/self-review, Revisionsprojektion und Multi-Round und vereinheitlicht die Verträge für finale Aktion und Erklärung.
- feat: Die AI-Empfehlungsseite zeigt neu die historische Performance gruppiert nach Entscheidungsstil; specialist-Opinion-Stichproben können persistiert und für die Posterior-Auswertung verwendet werden.
- feat: Neu `--portfolio futu`, mit dem echte Futu-OpenD-Konten schreibgeschützt LONG-Positionen in A-Aktien, Hongkong-Aktien und US-Aktien importieren können.
- feat: Die Web-Startseite und die API unterstützen das temporäre Auslösen einer Marktreview für einzelne oder mehrere Märkte, ohne die globale Konfiguration zu ändern.
- feat: Tushare unterstützt den Anschluss an ein selbst gehostetes Gateway oder kompatible Mirror über `TUSHARE_HTTP_URL`.
- fix: Verbesserung der Kursrouten und des Caches für Hongkong-Aktien, der englischen Nachrichtenabgleichung für ausländische Aktien, der Reihenfolge der Datenquellen-Fallbacks sowie der Stabilität der Desktop-Verpackung.

### Neue Funktionen

- Die Multi-Agent-Mehrstrategien-Integration erhält eine kontrollierte Deliberation v0, injizierbare mediator/self-review v1–v2, eine schreibgeschützte Revisionsprojektion v3 und multi-round v4; die Erweiterungsebene kann relativ zur Baseline der darunterliegenden Ebene nur gleich bleiben oder weiter abgeschwächt werden, sie überschreibt das autoritative Endsinal nicht.
- Der Modus `specialist` wählt maximal 4 Strategie-Experten und steuert über `AGENT_SKILL_CONCURRENCY` 1–4 parallele Worker; Worker erben Kontext wie das eingefrorene Zieldatum der Hauptpipeline, und ein fehlgeschlagener Skill blockiert weder andere Strategien noch die endgültige Entscheidung.
- Der Multi-Agent-Bericht verfolgt die endgültigen Pipeline-Anpassungen über die Benutzeraktionen in acht Zuständen und schließt ungültige Agent-Meinungen aus; nur wenn die kanonische Aktion eindeutig aufgelöst werden kann, werden explanation und DecisionSignal erzeugt, und mit demselben `final_action` wird der Vertrag für die finale Aktion vereinheitlicht.
- specialist persistiert nach erfolgreichem Speichern der Analysehistorie versionierte, wenig sensible und idempotente gültige Opinion-Stichproben als reale Daten für spätere Posterior-Auswertungen; in dieser Phase werden keine Outcomes berechnet, keine Performance ausgewertet und keine Gewichte angepasst.
- Die AI-Empfehlungsseite zeigt neu die historische Performance des Entscheidungsstils, mit der Schwelle von 30 abgeschlossenen Stichproben pro unabhängiger Gruppe für Treffer, Bereichsveränderung, nicht auswertbar und maximale adverse Abweichung, und bleibt zu den alten Statistik-APIs kompatibel.
- Neu `--portfolio futu`: schreibgeschützter Import der LONG-Positionen in A-Aktien, Hongkong-Aktien und US-Aktien eines echten Futu-OpenD-Kontos als Analyseliste.
- Die Web-Startseite und `POST /api/v1/analysis/market-review` unterstützen die temporäre Auswahl einzelner oder mehrerer Review-Märkte über eine streng validierte `region`; die einmalige Abdeckung liest/schreibt keine globale Konfiguration und durchzieht Aufgabenübermittlung, Status, SSE, Ergebnis und Verlauf.
- Die Tushare-Datenquelle unterstützt eine benutzerdefinierte Anbindungsadresse über `TUSHARE_HTTP_URL`; bleibt sie leer, wird weiterhin die offizielle Standardadresse verwendet (fixes #1985).

### Verbesserungen

- Die automatische Auslösung der PR Review wird pausiert; nur der manuelle `workflow_dispatch`-Einstieg bleibt erhalten, um doppelte Hilfs-Reviews und irreführende rote Lichter durch fehlgeschlagene Kommentarberechtigungen zu vermeiden; die regulären CI-Prüfungen bleiben unverändert.
- `.env.example` und der Tagesanalyse-Workflow bilden `TUSHARE_HTTP_URL` synchron ab, damit lokale und Cloud-Konfigurationszugänge konsistent bleiben.

### Behobene Probleme

- Behebung der Fehlbewertung englischer Nachrichtenrelevanz beim Mapping ausländischer Aktiencodes auf chinesische Anzeigenamen; die Auflösung von ausländischen Aktiencodes, englischen Namen und Aliasen wird vereinheitlicht, und erweiterte Suchbegriffe werden dedupliziert (fixes #2026).
- Der privilegierte `pull_request_target`-Workflow checkt nicht mehr den Kopf des Fork-PRs aus; sensible Schritte führen nur vertrauenswürdige Skripte des Hauptzweigs aus, PR-Metadaten und Diff werden über die GitHub API gelesen (fixes #2051).
- Fehlt die PR-Review-Ereignis-Payload, ist sie unlesbar oder die JSON ist ungültig, wird eine lokalisierbare Warnung ohne Payload-Leck ausgegeben und das bisherige Degradationsverhalten beibehalten (fixes #2070).
- Behebung des Windows-Problems, bei dem `mimetypes` beim Kaltstart die Registrierung las und den Prozess einfror.
- Vereinheitlicht die Erkennung von 4–5-stelligen Bare-Hongkong-Aktiencodes in `DataFetcherManager`, AkShare und Longbridge, damit 4-stellige Codes nicht falsch geroutet werden oder stillschweigend scheitern (fixes #2091).
- Die Echtzeit-Kursdaten für Hongkong-Aktien von AkShare erhalten einen 20-minütigen Markt-Cache und einen Concurrent-Kaltstart per single-flight; bei heißem Cache wird nicht mehr auf das Netzwerk-Rate-Limit gewartet, bei Fehlern der Hauptschnittstelle bleibt die Fallback-Schnittstelle von Sina erhalten (refs #1852).
- Die Standardpriorität von `TencentFetcher` wird auf den letzten Fallback der Tages-K-Datenquelle für A-Aktien angepasst, und eine explizite Überschreibung `TENCENT_PRIORITY` wird ergänzt (refs #2032).
- Die Web-Einstellungsseite und der Test-Einstieg für Benachrichtigungen ergänzen die Konfiguration für normale DingTalk-Gruppenbots, unterstützen das sichere Maskieren von Webhook und Secret, das Anzeigen der Hilfe und das Senden von Testbenachrichtigungen (refs #1957).
- Die normalen und Streaming-Schnittstellen von Agent Chat erben, wenn die Anfrage kein `report_language` angibt, das globale `REPORT_LANGUAGE`; ein explizit angeforderter Wert hat weiterhin Vorrang.
- Die WebUI zeigt Release-Version, Code-Version und Build-Zeit getrennt an und nutzt eine Zusammenfassung der Build-Eingaben, um die Wiederverwendung alter statischer Ressourcen bei unveränderten Zeitstempeln zu vermeiden (fixes #2093).
- Das unsigned macOS-Paket deaktiviert explizit die Electron-Signierung und den Hardened Runtime, räumt unvollständige Signaturen in den Phasen eingefrorenes Backend und electron-builder auf und prüft die Original-App und das DMG-Artefakt; diese Abschwächung ersetzt keine Apple-Developer-Signierung und -Notarisierung (refs #2075).

### Dokumentation

- Behebung defekter relativer Links in der Dokumentation.

## [3.27.0] - 2026-07-19

### Release-Highlights

- feat: Neues experimentelles Prototyp für den Single-Agent-Fragedienst des Codex App Server, die Standard-Pfade LiteLLM, Multi Agent, normaler Bericht und geplanter Task bleiben unverändert.
- feat: Die Web-AI-Empfehlungsseite unterstützt das Speichern von Entscheidungsstil-Signalen, die auf Basis von Schnappschüssen historischer Berichte neu berechnet werden, und vervollständigt die Guardrail-Semantik für Deduplikation, Verlängerung, Verfall und Prüfbarkeit.
- feat: Erster Vertrag der strukturierten Ausgabe für Mehrstrategien-Meinungen, der Meinungsnormalisierung, grundlegende Konflikterkennung, Aggregations-Metadaten und Report-Kompatibilitätsgrenzen abdeckt.
- improve: Die Berichtsseite zeigt Eingabedatenstatus, Quelle, Auswirkung von Anomalien, Behandlungsvorschläge und Diagnosecode klar an und unterscheidet Seiteninformationen von den Eingaben dieser Analyse.
- fix: Behebung, dass MiniMax-Inhalte das finale JSON verschmutzen, die Kompatibilität des `<think>`-Wrappers sowie die Konvergenz der Schlussfolgerung auf das finale Signal nach der Abdeckung des Mehr-Agenten-Risikos.
- fix: Ergänzt PE/PB-Bewertungsfelder der US-Echtzeit-Kursdaten, Beschreibungen der Multi-Markt-Tools und Hinweise zur macOS-Gatekeeper-Installation.

### Neue Funktionen

- Neues experimentelles Prototyp für den Single-Agent-Fragedienst des Codex App Server aus #1743 Phase 6, das nur drei bestehende schreibgeschützte Tool-Surface-Werkzeuge öffnet; die Standard-Pfade LiteLLM, Multi Agent, Deep Research, normaler Bericht, geplanter Task und Phase-1/2-`codex_cli` bleiben unverändert.
- Die Web-AI-Empfehlungsseite unterstützt das bestätigende Speichern von Entscheidungsstil-Signalen, die auf Basis von Schnappschüssen historischer Berichte neu berechnet wurden, unterscheidet über created/existing/refreshed zwischen neu erstellt, unverändert wiederverwendet und Verlängerung bzw. Dimensionalitätsergänzung bestehender Datensätze und nutzt die profile-aware Deduplikations- und Verfallssemantik erneut.
- Die erste Version der strukturierten Ausgabe für Mehrstrategien-Meinungen ergänzt Meinungsnormalisierung, grundlegende Konflikterkennung und Aggregations-Metadaten als phasenweise Grundlage für #1964; diese Version beansprucht nicht, die parallele Ausführung, das vollständige Strategie-Scheduling-MVP oder die vollständige mehrsprachige Frontend-Anzeige fertigzustellen.

### Verbesserungen

- Die Codex-Einstellungsseite prüft nur, ob Konfiguration, Befehl und erforderliches Protokoll einen Versuch zulassen; nach dem Speichern kann der Benutzer direkt fragen; Chat übermittelt die Frage über das serverseitige `accepted`-Ereignis und stoppt nach dem tatsächlichen Backend.
- Der Eingabedatenblock der Web-Berichtsseite übernimmt die Felder Status, Quelle, Alarm und Erklärung, ergänzt in der Erklärung Auswirkung von Anomalien, Behandlungsvorschläge und Diagnosecode und unterscheidet Seiteninformationen des Berichts von den Eingaben dieser Analyse.
- Aktualisiert die Projektanzeigeinformationen der Anspire-Datenquelle und korrigiert die Beschreibung des Tools `get_stock_info` von der Beschränkung auf A-Aktien auf die Abdeckung von A-Aktien, Hongkong-Aktien und US-Aktien.

### Behobene Probleme

- Behebung, dass MiniMax-Analyse und Kanaltests nach dem Zusammenfügen von Reasoning-Inhalten und finalem Text das Ergebnis unparsbar und nicht persistierbar machten; bei String-Antworten wird nur der vollständige führende `<think>`-Wrapper entfernt, identische Literal-Labels im JSON-Inhalt bleiben erhalten.
- Korrigiert die Timeout-Zuordnung der internen runtime facts von Multi Agent und lässt die Dashboard-Entscheidungsfelder sowie die Ein-Satz-Kernschlussfolgerung nach der risk-application-Abdeckung auf Basis des post-risk-Signals finalisieren.
- Konvergiert die Semantik des Mehrstrategien-Synthesizers: korrekte Behandlung von Signal-Enum, fehlendem Signal, gültiger opinion_count und deterministischer Synthese sowie Kompatibilität mit den lockeren Feldformen historischer und externer Dashboards.
- Der Codex-Fragedienst akzeptiert nur finale Antworten im Terminalzustand, die der App Server ausdrücklich abgeschlossen hat, und vereinheitlicht die Grenzen für Gesamtzeitlimit, kumulative Ausgabe, Ereignisse, Tool-Budget und Prozessrecycling.
- `codex_cli` fixiert für normale Analysen explizit die Unattended-Genehmigungsstrategie und die schreibgeschützte Sandbox, damit neuere Codex-Versionen bei nicht-interaktiven Aufgaben nicht wegen einer Anfrage zur menschlichen Genehmigung unterbrochen werden.
- Die US-Echtzeit-Kursdaten von yfinance ergänzen `pe_ratio` und `pb_ratio` für Bewertungsanalysen und nachgelagerte Berichte.

### Dokumentation

- Ergänzt Architekturwahl, Sicherheitsanalyse und temporäre Freigabeschritte für die offizielle Installation, wenn ein unsigniertes, nicht notarisiertes DMG von macOS Gatekeeper blockiert wird.

### Dokumentation

- Im Schnellstart des README wird die Konfiguration der Kursdatenquelle ergänzt (`TUSHARE_TOKEN` / Longbridge), klargestellt, dass ohne Konfiguration weiterhin die kostenlosen Fallback-Quellen AkShare, Baostock, YFinance usw. genutzt werden können, und der vollständige Leitfaden wird auf Chinesisch und Englisch synchronisiert.

## [3.25.0] - 2026-07-03

### Release-Highlights

- feat: Neue generation-only lokale CLI-Backends `claude_code_cli` und `opencode_cli` sowie Statusdiagnose, Vorschau, Smoke-Test-API und Web-Statuspanel für Generation-Backends.
- feat: Der Taiwan-Aktienbericht bindet die Daten der drei großen Institutionen vollständig ein und deckt Berichts-Rendering, LLM-Prompt, TWD-Währungsauszeichnung, Erkennung des Schlussauktionskurs und Fetcher-Härtung ab.
- feat: Neu DingTalk-Gruppenbot-Benachrichtigungen, koreanische Berichtsausgabe und die Vorschau der Entscheidungsstil-Neubewertung für AI-Empfehlungen.
- feat: Agent `/chat/stream` standardisiert das progress-Ereignis mit neuer Semantik für Phasenstart/-abschluss, Pipeline-Timeout und Budgetüberspringung.
- fix: Behebt Stabilitätsprobleme bei WebUI-Host/Port-Bindung auf dem Desktop, der macOS-Homebrew-CLI-PATH-Diagnose, der Aufteilung langer Discord-Berichte, AlphaSift-Timeouts, der yfinance-Dividendenparsing und der Normalisierung von A-Aktien-Codes im Backtest.

### Neue Funktionen

- DingTalk-Gruppenbot-Benachrichtigungen unterstützen `DINGTALK_WEBHOOK_URL` und `DINGTALK_SECRET` und teilen lange Texte automatisch auf, um das 20-KB-Limit einzuhalten.
- Neue Berichtssprache Koreanisch (`REPORT_LANGUAGE=ko`), abgedeckt sind Einzelaktienberichte, Marktreview, Prompt-Ausgabesprache, Entscheidungs-Guardrails, Benachrichtigungsvorlagen-Labels und die Texte der Web-Berichtsdetailseite.
- Neue generation-only lokale CLI-Backends `claude_code_cli` und `opencode_cli`, die den LiteLLM-Standardpfad, die Agent-Tool-Call-Grenzen, per-preset extractor, die minimale env allowlist und strukturierte Fehler beibehalten.
- Neue APIs für Generation-Backend-Status, Vorschau und Smoke-Test sowie das Web-Generation-Backend-Statuspanel, das leichte Prüfung von JSON-Smoke-Tests unterscheidet und die Grenze „nur generieren, keine Werkzeugaufrufe für Fragedienst" der lokalen CLI beibehält.
- Das progress-Ereignis von Agent `/chat/stream` ergänzt `stage_start`, `stage_done`, `pipeline_timeout` und `pipeline_budget_skipped` und vervollständigt die Semantik von Phasenfortschritt, Timeout und Budgetüberspringung.
- Der institution-Block des Taiwan-Einzelaktienberichts zeigt die Nettokauf-/Verkaufsüberhänge der drei großen Institutionen von TWSE T86 / TPEx und speist die Tabelle der Nettokauf-/Verkaufsüberhänge der drei großen Institutionen als Filter für Taiwan-Aktien-Chips in den LLM-Analyse-Prompt ein.
- Neu Vorschau-Schnittstelle und Seitenvorschau für die Entscheidungsstil-Neubewertung von AI-Empfehlungen.

### Verbesserungen

- Der Fetcher der drei großen Taiwan-Institutionen ergänzt Concurrent-Cache gegen Zusammenbruch, die Trennung der Märkte TWSE/TPEx, TPEx-Datumschutz und die Wiederverwendung des restlichen Stage-Budgets, um die Degradationswahrscheinlichkeit durch Rate-Limits, Endpunktausfälle und Cold-Fetch-Timeouts zu senken.
- Der AlphaSift-Standard-Pin wird auf `9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf` aktualisiert; angebunden sind Caller-seitiges Timeout der Wrapper-Datenquelle, Geschwindigkeitsbegrenzung/Jitter der EastMoney-Direktverbindung, Strategieverzeichnis-Metadaten und defensive Strategien.
- Beim Polling des Auswahlaufgabenstatus wird bei behebbaren Timeouts darauf hingewiesen, dass der Hintergrundtask automatisch erneut versucht; `.env.example` ergänzt zugehörige Timeout-Abstimmungspunkte.
- Konvergiert den Score der Einzelaktienanalyse und die DecisionSignal-Aktion auf einen einheitlichen Konsens, vereinheitlicht die Segmente 80/60/40/20 und protokolliert bei Risikodegradation raw/adjusted score, final action und Grund.
- Beim Wechsel der linken Kategorie der Web-Einstellungsseite werden die Erststartprüfung und die AlphaSift-Hilfskarte nur in den relevanten Kategorien angezeigt, um Reste über Kategorien hinweg zu reduzieren.

### Behobene Probleme

- Behebt, dass die Windows-Desktop-Startseite beim Start des Backends fest `--host 127.0.0.1` übergab, wodurch `WEBUI_HOST=0.0.0.0` in `.env` wirkungslos blieb und das WebUI im LAN nicht erreichbar war; die Desktop-Version verwendet weiterhin standardmäßig `127.0.0.1` und bindet nur nach expliziter Konfiguration von `WEBUI_HOST` entsprechend.
- Behebt, dass beim Desktop-Start die `WEBUI_PORT` aus `.env` nicht mit dem automatisch gewählten Electron-Port übereinstimmte, sodass das Fenster weiterhin auf den alten Port wartete und die Verbindung timeoutete.
- Behebt, dass die macOS-Desktop-Version beim Start über Finder/Dock den Homebrew-Codex-CLI-Pfad im Backend-PATH nicht sah, und klärt die Diagnose zur Trennung zwischen Codex-CLI-Hauptanalyse und Agent-LiteLLM-Tool-Aufrufen.
- Behebt, dass Discord-Langberichts-Push nach dem 2000-Zeichen-Limit segmentweise sendet und bei 429-Rate-Limits gemäß `retry_after`/`Retry-After` begrenzt wiederholt, damit nach einem Abbruch nicht nur die erste Berichtshälfte eintrifft.
- Behebt die Erkennung der `market_phase`-Schlussauktion für japanische, koreanische und taiwanesische Aktien, damit Phasen kurz vor Handelsschluss nicht mehr fälschlich als normales `intraday` markiert werden.
- Behebt, dass die A-Aktien-Einzelaktienanalyse bei leeren `belong_boards`-Platzhaltern nicht mehr die zugehörigen Branchen nachschlägt und der zugehörige Branchenmodul-Block instabil angezeigt wird.
- Behebt, dass die Marktreview bei LLM-Titel-Drift oder fehlenden Branchenabschnitten im Text gelegentlich ohne Branchen-Hauptlinien in Web- und Push-Berichten angezeigt wird.
- Behebt die Formatierung der strukturierten Marktreview-Daten im Web für Handelsvolumen, Indexpunkte, prozentuale Veränderung und Hoch/Tief-Werte, damit Gleitkomma-Langtails oder fehlende Werte nicht direkt als `0.00` angezeigt werden.
- Behebt, dass die Aktienleiste der Web-Startseite bei fehlenden stock-bar-Zusammenfassungsfeldern oder nicht klassifizierbaren Aktionsempfehlungen die Stimmungspunktzahl und die Empfehlungsmarkierung verbirgt.
- Behebt, dass der Hintergrundthread „Sofort einmal ausführen" des geplanten Tasks auf der Web-Einstellungsseite kein `stock_codes` übergab und der Task dadurch abstürzte.
- Behebt die statische Anweisung von `opencode_cli`, damit die globale JSON-only-Einschränkung nicht `generate_text()` und die Freitextausgabe der Marktreview beeinflusst.
- Behebt, dass bei yfinance 1.2.x, das `Ticker.dividends` als einspaltiges DataFrame zurückgibt, die Dividendenparsing verworfen wurde; die Berechnung von TTM-Dividende pro Aktie und Dividendenhäufigkeit wird wiederhergestellt.
- Behebt die Währungsauszeichnung der taiwanesischen Finanzbeträge, die TWD-Beträge als „Neue Taiwan-Dollar" kennzeichnet, damit sie im A-Aktien-Kontext nicht als Renminbi fehlgelesen werden.
- Behebt, dass die Tagesvervollständigung des Backtests bei gleichwertigen A-Aktien-Codes wie `605066.SH`, `SS605066`, `SS.605066` fälschlich `SS605066` an die Datenquelle anfragte und der Backtest dadurch zu wenig Daten hatte.

### Dokumentation

- Neues Vertragsdokument für das progress-Ereignis von Agent `/chat/stream`, das die Semantik der neuen Ereignisfelder, die Web-Kompatibilitätsgrenzen, Verifikations- und Rollback-Verfahren erläutert.
- Synchronisiert die Datenschutz-/Bereitstellungsgrenzen des lokalen CLI-Backends: klargestellt, dass die lokale CLI kein Offline-Modell ist, Docker/CI/Remote selbst installieren und einloggen müssen und DSA keine Claude/OpenCode-Credential-Dateien liest.
- Aktualisiert den dreisprachigen Einstieg und die Marktunterstützungsgrenzen des README und erläutert die Grenzen von Taiwan `.TW` / `.TWO`, der Berichtsblöcke der drei großen Institutionen, der TWD-Kennzeichnung und der Erkennung der Schlussauktion.

### Tests

- Der Fetcher der drei großen Taiwan-Institutionen ergänzt ein Live-Smoke-Skript und einen Drift-Erkennungstest mit `@pytest.mark.network`, damit nicht blockierende network-smoke-Tasks die Kernfelder von TWSE T86 / TPEx und die Parsingergebnisse abgleichen.

## [3.24.1] - 2026-06-28

### Behobene Probleme

- Die Longbridge-SDK-Versionseinschränkung wird korrigiert, sodass je nach Plattform eine installierbare Version gewählt wird; damit schlägt die Desktop- und Docker-Veröffentlichung bei `pip install -r requirements.txt` nicht mehr wegen der nicht existierenden Version `0.2.75` fehl.

## [3.24.0] - 2026-06-28

### Release-Highlights

- feat: Erweiterte Marktunterstützung für taiwanesische, japanische und koreanische Aktien, abgedeckt sind Taiwan-suffix-only-Analyse, die Datenschicht der drei großen Taiwan-Institutionen, JP/KR-Marktreview und marktübergreifende Service-Enumerationen.
- feat: Neue GenerationBackend-Abstraktion, `codex_cli`-lokales CLI-Backend, reservierter Hermes-lokaler HTTP-Kanal und prompt cache capability registry.
- feat: Web/API/Desktop unterstützen geplante Push-Benachrichtigungen zu mehreren Zeitpunkten und den Heißwiederaufbau des Runtime-Schedulers; die Web-Einstellungsseite ergänzt Erststartprüfung und Geplanter-Task-Panel.
- feat: Die Berichtskette ergänzt Signalzuordnung, Einzelaktien-Signalzeitleiste, Konzeptbranchen-Ranking und die zugehörige Branchenanzeige von Benachrichtigung/Bericht.
- fix: Behebt Stabilitätsprobleme bei Docker/Startprobe, statischem Ressourcen-MIME, leeren Backtest-Ergebnissen, Kombinationsbewertung, Benachrichtigungs-Markdown, AlphaSift-Datenquelle und Testumgebungsisolierung.

### Neue Funktionen

- Neue Taiwan-suffix-only-Einzelaktienanalyse-MVP: `.TW`/`.TWO`-Codes können über YFinance-Tageslinien und nahezu Echtzeit-Kursdaten laufen, ergänzt um Markterkennung, Handelskalender und Prompt-Fähigkeitsgrenzen.
- Taiwan `tw` wird in DecisionSignal, Portfolio, Intelligence-Service-Schicht, API-Enumerationen und Web-Filter aufgenommen, damit Taiwan-Analysesignale nicht durch die Marktnormalisierung stillschweigend verworfen werden.
- Neue Datenschicht-Fetcher `TwInstitutionalFetcher` für die drei großen Taiwan-Institutionen mit Unterstützung für TWSE/TPEx-Quellen, Datumskonvertierung, Ein-Tages-Cache und fail-open-Degradation.
- Die Marktreview ergänzt die Märkte `jp`/`kr` mit Index-Reviews von Nikkei 225/TOPIX und KOSPI/KOSDAQ sowie die Erweiterung von `MARKET_REVIEW_REGION`, Handelstagsfilterung und Web-Einstellungs-Enumerationen.
- Neue GenerationBackend-Phase-1-Abstraktion und ein explizit opt-in `codex_cli`-lokales CLI-Generation-Backend mit strukturierten Fehlern, Fallback, Stream-Degradation und usage-unavailable-Vertrag.
- Neuer reservierter Hermes-lokaler HTTP-Generierungskanal mit JSON-Generierung, no-proxy-lokalen Aufrufen und Bindung an den saved-secret-Endpunkt.
- Neue Provider Cache Capability Registry, die prompt-cache-Fähigkeiten nach provider, API surface, gateway und Verifizierungsstatus modelliert.
- Unterstützung für geplante Push-Benachrichtigungen mit `SCHEDULE_TIMES` zu mehreren Zeitpunkten; langlebige Web/API/Desktop-Prozesse können nach dem Speichern der Planungskonfiguration den Runtime-Scheduler heiß starten/stoppen oder neu aufbauen.
- Neue Signalzuordnungsanalyse und Einzelaktien-Signalzeitleiste auf der Web-AI-Empfehlungsseite, und automatisch generierte sowie aus der Historie rückgefüllte DecisionSignals erhalten das Standard-`decision_profile`-Metadatum.
- Marktreview, Web-Berichtsseite und zugehörige Branchen von Benachrichtigungen ergänzen Konzeptbranchen-Ranking und Konzeptsignal-Anzeige.

### Verbesserungen

- TickFlow wird zu einer optionalen Datenquelle für A-Aktien-Tages-K, Echtzeit-Kursdaten und Aktienliste/-namen erweitert, mit count, Integritätsprüfung und Schutz durch Batch-Prefetch-Cache.
- Härtet die suffix-Erkennung von JP/KR/TW, den japanisch/koreanischen Aktien-Seed-Index, den YFinance-Quoten-/Fundamental-Kontext sowie die JP/KR-Portfolio- und Market-Light-Grenzen.
- Die Web-Einstellungsseite ergänzt eine Karte für die Erststart-Konfigurationsprüfung und ein Geplanter-Task-Panel, verbirgt den internen `SCHEDULE_TIMES`-Schlüssel und verbessert das Schließen und automatische Verschwinden von Hinweisen zu doppelten Tasks.
- Die Web-Historie-Berichtsdetails betten keine AI-Empfehlungskarte mehr ein; strukturierte Entscheidungssignale werden auf der AI-Empfehlungsseite konzentriert, und die Quell-Berichts-ID/URL-Parameter zur präzisen Lokalisierung bleiben erhalten.
- Unter `GENERATION_BACKEND=codex_cli` werden normale Analyse und Marktreview nicht mehr fälschlich als nicht verfügbar eingestuft, weil der LiteLLM-API-Key fehlt, und die finale Antwort wird über `--output-last-message` aus der Datei gelesen.
- Das lokale CLI-Backend führt für stdout/stderr-Diagnosevorschau und finale Antwort ein Gesamtlimit während der Ausführung ein und ergänzt die Maximumwertprüfung der numerischen Konfiguration neuer Generation-Backends.
- Der AlphaSift-Standard-Pin wird auf `0a7b9cd59e81718f851890535241bc105d4ddc64` aktualisiert, nutzt standardmäßig den DSA-EastMoney-Fallback-Provider und macht die source-health-Diagnose zugänglich.
- Die Standard-Speicherempfehlung von Docker Compose wird auf 1G erhöht; der Tagesanalyse-Workflow verträgt fälschlich in gleichnamige Environment variables gesetztes `STOCK_LIST`.
- Der Agent-Pfad synchronisiert die signal-attribution-Prompt; die Zusammenfassung der Benachrichtigungsberichte expandiert AI-Entscheidungssignaldetails nicht mehr, vollständige Signale bleiben in Einzelaktien-Details und Einzelaktienberichten.

### Behobene Probleme

- Die API-Asynchron-Batch-Analyse teilt den Cache des Konzeptbranchen-Rankings, damit nicht für mehrere Aktien derselben Charge wiederholt das Konzept-Ranking des gesamten Markts abgerufen wird.
- Behebt, dass die Benachrichtigungs-Markdown-Tabellenkonvertierung nach leeren Zellen Folgeinhalte fälschlich falschen Tabellenköpfen zuordnete.
- Behebt, dass die Market-Light-Regionsnormalisierung `jp`/`kr` ablehnte, die Marktphasenzusammenfassung japanischer/koreanischer Verlaufslisten fälschlich `analysis_phase` übertrug und Standard-Benachrichtigungsberichten `dashboard.phase_decision` fehlte.
- Fixiert die installierbare Longbridge-SDK-Version für Docker auf 0.2.75 und behebt, dass der Besitzer des efinance-Cache-Verzeichnisses im Docker-Image die A-Aktien-Datenquelle degradierte.
- Die heutige Bewertung des Positions-Schnappschusses verwendet begrenzten Concurrent-Prefetch der Echtzeitkurse, um die Aktualisierungs-Timeouts der Web-Portfolio-Seite bei vielen Positionen zu verringern.
- Die Web-Startseite wechselt nach abgeschlossener erneuter Analyse automatisch zum neuesten Bericht derselben Aktie und behebt, dass statische Web/Desktop-JS-Ressourcen unter Windows als `text/plain` zurückgegeben werden konnten und einen Black Screen verursachten.
- Behebt, dass `--serve --schedule` und der Web/API-Runtime-Scheduler auseinanderdrifteten, der „sofort ausführen"-Beschäftigungsstatus falsch angezeigt wurde, der Neuaufbau geplanter Tasks doppelt lauschte und die Bedeutung der Startparameter verloren ging.
- Behebt, dass `main.py --serve-only` auf schwach ausgestatteten Hosts wegen der trägen Import-Anwendung das uvicorn-Startselbsttest-Fenster überschritt und wiederholt neu startete.
- Behebt, dass der Web-Backtest ohne Analyse-Datumsbereich und ohne normalisierte Aktiencodes erfolgreiche Antworten, aber leere Ergebnisse lieferte, und ergänzt Diagnoseinformationen für leere Kandidaten, unzureichende Kursdaten und ungültige Suffixe.
- Behebt, dass unsupported `GENERATION_BACKEND` als leere Antwort/Template-Fallback behandelt wurde, `codex_cli`-stdout doppelt in das Ausgabelimit zählte und die JSON-Schema-Fallback-Semantik der Hauptanalyse zurückrollte.
- In der Docker-Bereitstellung maskiert die Web-Einstellungsseite beim Speichern benutzerdefinierter Webhook-Vorlagen Platzhalter wie `$content_json` und stellt sie zur Laufzeit wieder her, damit die Compose-Wiederbereitstellung sie nicht leer expandiert.

### Dokumentation

- Ergänzt den Feldvertrag des Konzeptbranchen-Rankings, die Branchen-/Konzepttyp-Spaltenanzeige der Benachrichtigungsberichte sowie Diagramme zu Datenquellenstabilität und Fehlerbehandlung.
- Ergänzt JP/KR/TW-suffix-only-MVP, die Speicher-/Prüf-/Fallback-Matrix von `MARKET_REVIEW_REGION`, die Market-Light-Grenzen und die PR-Commit-Workflow-Einschränkungen.
- Ergänzt Datenschutzgrenzen des lokalen CLI-Backends, die Erläuterung, dass es kein Offline-Modell ist, die Login-Zustandseinschränkungen von Docker/CI und den experimentellen/begrenzten Status von `codex_cli`.
- Ergänzt die Erläuterung der Backtest-Anfragekette und aktualisiert synchron die Beispiele von `docs/full-guide.md` und `docs/full-guide_EN.md`.

### Tests

- Neue/aktualisierte Regressionstests für Taiwan-Aktien, JP/KR-Marktreview, GenerationBackend, `codex_cli`, Hermes, lokale CLI, Runtime-Scheduler, Backtest und Konzeptbranchen-Ranking.
- Verstärkt die temporäre `.env`-Isolierung von `tests/test_analysis_api_contract.py`, `tests/test_analysis_history.py` und `tests/test_backtest_service.py`, damit lokale echte `.env`-Dateien die Systemkonfigurationstests nicht verschmutzen.

## [3.23.0] - 2026-06-20

### Release-Highlights

- feat: DecisionSignal verbindet Berichtsextraktion, Web-Anzeige, Feedback/Posterior, Alarmbenachrichtigung und Portfolio-Risiko durchgängig; die AI-Empfehlungssignale gelangen in eine nachverfolgbare geschlossene Schleife.
- feat: Neuer konformer RSS/Atom- und NewsNow-Intelligenzpool als Nachrichtenquelle; Analyse, Agent und Marktreview können lokal gespeicherte Intelligenz-Evidence fail-open wiederverwenden.
- feat: Neue Japan-/Korea-suffix-only-Einzelaktienanalyse-MVP, die `.T`, `.KS`, `.KQ`-Codes über YFinance mit Kurs- und Technikkontext versorgt.
- feat: Neues Token-Nutzungs-Monitoring-Dashboard, legacy LLM usage telemetry und message stability audit für bessere Beobachtbarkeit von LLM-Aufrufen.
- fix: Behebt Stabilitätsprobleme bei Live-Status des Ausführungsstroms, AlphaSift-Cache/Feldkompatibilität, Release-Notes-Diagnose und der Eingabe/Historie-Anzeige japanischer/koreanischer Aktien.

### Neue Funktionen

- Nach erfolgreichem Speichern der Einzelaktienanalyse-Historie wird aus dem finalen Bericht best-effort das `DecisionSignal`-Entscheidungssignal extrahiert; die bestehenden Verträge für Signaleduplizierung, Planqualitätsberechnung und Maskierung werden wiederverwendet.
- Neue Web-AI-Empfehlungsseite, latest-active-Signalzusammenfassung auf der Positionsseite, Signal-Anzeige in Historienberichten und vollständigere Signaldetailkarten mit Score, Konfidenz, Preisplan, Katalysator, Risiko und Verfallbedingungen.
- Neue DecisionSignal-Benutzerfeedback, signalstufenbezogene Posterior-Tagesbewertung, Statistik-API und Web-Anzeige, die outcome/feedback-sidecar-Tabellen nutzt und den Vertrag der Hauptsignaltabelle beibehält.
- DecisionSignal wird auf Alarm, Benachrichtigung und Portfolio-Risiko wiederverwendet: Beim Alarmauslösen wird das latest active Signal verknüpft oder ein minimales Alert-Signal erstellt, Benachrichtigungen ergänzen eine wenig sensible Signalzusammenfassung, und das Positionsrisiko aggregiert aktive sell/reduce/alert-Signale mit fail-open.
- Neue konforme RSS/Atom-Nachrichtenquellen-Konfiguration, Abruf, Deduplikation, Speicherung, Abfrage, Retention und grundlegende Sicherheitsprüf-API als Baseline für den Aktien-/Marktnachrichten-Intelligenzpool.
- Die Nachrichtenquelle ergänzt den Typ `newsnow`, die Konfiguration `NEWSNOW_BASE_URL` und die API `/api/v1/intelligence/sources/defaults` zur Initialisierung der Standardsourcen, mit integrierten Finanz-Hot-Quellen wie CLS-Hot-Themen, Xueqiu-Hot-Aktien, WallstreetCN-Schnellmeldungen, Jin10-Daten und Gelunhui-Ereignissen.
- Einzelaktienanalyse, Agent-Analyse und Marktreview lesen fail-open den lokalen Nachrichten-/Intelligenzpool und speisen Quelllinks als Nachrichtenkontext und Evidence ein.
- Neue Japan-/Korea-suffix-only-Einzelaktienanalyse-MVP: manuell eingegebene `.T` / `.KS` / `.KQ`-Codes können über YFinance-Tageslinien und nahezu Echtzeit-Kursdaten laufen, ergänzt um Markterkennung, Handelskalender, Prompt-Semantik, Web/API-Typen und Fähigkeitsgrenzen-Dokumentation.
- Neues Token-Nutzungs-Monitoring-Dashboard und die Schnittstelle `/api/v1/usage/dashboard` mit Anzeige der Gesamtzahl der LLM-Aufrufe, der Aufteilung Prompt/Completion, der Modellnutzung, der Verteilung der Aufrufarten und der Details der letzten Aufrufe.

### Verbesserungen

- Vervollständigt für `DecisionSignal` den Standard-Lebenszyklus, die enge relaxed-Deduplizierung gleicher Quelle, die automatische Invalidierung gegensätzlicher aktiver Signale, die Unfähigkeit, terminale Zustände per PATCH wiederzubeleben, und die Extraktion wenig sensibler market-phase-Hinweise.
- Ergänzt den typisierten Web-decision-signals-API-Wrapper und Vertragsisolationstests und konzentriert die AI-Empfehlungsabfrage historischer Berichte auf die präzise lazy-Extraktion des Berichts.
- Die DSA-Datenquellenkette ergänzt den Tencent-Tages-K-Direkt-Fetcher, die kurzfristige daily-source-health-Unterbrechung und aktualisiert AlphaSift-Standard-pin/runtime bridge.
- Aktiviert standardmäßig `DAILY_SOURCE=auto`, die Sina-Snapshot-Priorität, candidate-level quote context und die Grenzen für LLM-ranking-timeout/max tokens.
- Ergänzt legacy LLM usage provider/cache telemetry, message-HMAC-Diagnosefelder und ein message stability audit für normale Einzelaktienanalysen der legacy-Pfade, ohne die öffentliche Usage API, Prompts oder provider-Parameter zu ändern.
- Die Strategieauswahl der Fragedienst-Seite auf Mobilgeräten wird zu einem standardmäßig eingeklappten Button-Einstieg; nach dem Aufklappen können weiterhin mehrere Strategien ausgewählt werden und klappen nach dem Senden automatisch zusammen, um die Überdeckung des Dialoginhalts zu verringern.

### Behobene Probleme

- Behebt die Maskierung des Live-SSE des Ausführungsstroms, doppelte späte LLM-/Benachrichtigungskarten, das verfrühte Erfolgsmarkieren der Datenquellen-Aggregationskarte, das Zusammenpressen der Aktieninformationen durch die schmale Seitenleiste der Web-Startseite sowie die gegenseitige Störung der Laufzeitdiagnosen bei automatisch generiertem Marktkontext der Einzelaktienanalyse.
- Behebt den Leerzustand bei transientem Ausfall der EastMoney-Hotspot-Themen von AlphaSift ohne Cache, das Beibehalten des Hotspot-Caches beim Desktop-Update sowie die Kompatibilität der Doppelfelder `leader_stocks` / `stocks`.
- Behebt Probleme der Web-AI-Empfehlungsseite mit Filter-/Statusaktualisierungs-Paginierung, der Anzeige einseitiger Einstiegspreise des Preisplans, der Aktualisierung des latest-Positionssignals, der sicheren JSON-Rendering von Details und der Semantik der Karteninteraktion.
- Nur wenn ein Historienbericht eine eindeutige `action` oder eine parsbare Aktion besitzt, wird die Lazy-Rückfüllung des Entscheidungssignals ausgelöst, damit statistische Definitionen wie `decision_type=hold` in unklaren Empfehlungsszenarien nicht fälschlich rückgefüllt werden.
- Behebt die Lücke von #1390 P6 DecisionSignal in der Semantik des Portfolio-Risiko-Schnappschusses und der Standardaggregat-Benachrichtigungsanzeige.
- Deaktiviert standardmäßig das Anlegen neuer Quellen über `/api/v1/intelligence/sources/defaults`, damit öffentliche Beispiel-NewsNow-Instanzen nicht standardmäßig aktiviert werden, und vereinheitlicht zugleich, dass Details von 500-Antworten nur ins Log gelangen und die Antwort eine generische Fehlermeldung zurückgibt.
- Web-Aktien-Autovervollständigung, Eingabevalidierung, Historie/Task-Anzeige und Filter vervollständigen die Yahoo-Suffix-Codes für Japan/Korea, gängige japanische/koreanische Aktienindizes und die Bare-Code-Auflösung des Aktienpools, damit Szenarien wie `000660`, `005930`, `7203.T`, `005930.KS`, `035720.KQ` nicht abstürzen, in die A-Aktien-Semantik geraten oder die Historie gespalten anzeigen.
- Wenn bei der Analyse japanischer/koreanischer Aktien der lokale Historienkontext fehlt, wird mit YFinance-Tageslinien ein Fallback für K-Linien- und Technikindikatoren-Kontext aufgebaut, damit Berichte nicht fälschlich behaupten, Kernkurse und technische Daten japanischer/koreanischer Aktien seien nicht verfügbar.
- Schlägt die Abfrage des PR-Autors bei der Release-Notes-Generierung fehl, bleibt die Degradation erhalten und eine Warnung mit PR-Nummer und Ausnahmetyp wird ausgegeben, um Token-, Berechtigungs-, Netzwerk- oder GitHub-API-Anomalien zu untersuchen.

### Dokumentation

- README, vollständiger Leitfaden und Marktunterstützungsdokumente ergänzen Beispiele für japanische/koreanische Aktien (`7203.T`, `005930.KS`) und stellen klar, dass `.T/.KS/.KQ` aktuell ein YFinance-only-MVP sind.
- Neues Fachdokument für das DecisionSignal-Entscheidungssignal, das Felder/API/Web/Alarmbenachrichtigung/Portfolio-Risiko/Posterior-Bewertung, Maskierung, Migration und Rollback erläutert und die i18n-Anzeigegrenzen im Web abschließt.
- Ergänzt AlphaSift-Migrations- und Rollback-Grenzen: klargestellt die explizite Übersetzungssemantik von `ALPHASIFT_INSTALL_SPEC`, `requirements.txt + DEFAULT_ALPHASIFT_INSTALL_SPEC` und die Laufzeitkompatibilitätsgrenzen.
- Ergänzt das Basisdokument der Nachrichtenquelle, das `NEWS_INTEL_*`-Konfiguration, NewsNow-Selbsthosting-Empfehlungen, die Grenze „Modell/provider/base URL unverändert" und den Rollback-Pfad beim Deaktivieren oder Entfernen der Intelligenzpool-Variablen erläutert.

### Tests

- Neue/aktualisierte Regressionsabdeckung für DecisionSignal-Dienst, -Extraktion, -Feedback/Posterior, -Zusammenfassung, -Dokumentation, -Benachrichtigung, -Alarm, -Positionsrisiko, -Web-Anzeige und -Labels.
- Neue/aktualisierte Tests für RSS/Atom-/NewsNow-Intelligenzquellen-Dienst, -API, -Sicherheitsprüfung, -Analyseanbindung und -Konfigurationskompatibilität.
- Neue/aktualisierte Tests für japanisch/koreanische Markterkennung, Aktienindex, YFinance-Kurs-Fallback, Web-Autovervollständigung und Eingabevalidierung.
- Neue/aktualisierte Regressionen für LLM usage, Ausführungsstrom, AlphaSift, Release-Notes-Generierung und mobile Interaktionen.

## [3.22.0] - 2026-06-13

### Release-Highlights

- feat: Neue unabhängige DecisionSignal-Speicherung und -API, Ausführungsstrom-Snapshot-API und Web-Ausführungsstrom-Ansicht; die strukturierten Felder der Empfehlungsaktionen und die Historie-/Backtest-Anzeigekette werden vervollständigt.
- feat: Die AlphaSift-Hotspot-Themenkette wird auf den neuen Vertrag hochgestuft und unterstützt Hotspot-Rankings, Themen-Details, Gärungsrouten, Konzeptaktien-Details, Cache und Fallback-Datenquellen.
- feat: Die Einzelaktienanalyse injiziert standardmäßig die Marktumgebungsübersicht des Tages und schwächt aggressive Kaufempfehlungen in Hochrisiko-/Abflutphasen ab.
- fix: Behebt Stabilitätsprobleme bei Folgefragen mit Zielkontext, der Äquivalenzcode-Zuordnung von Watchlist-Aktien, der Filterung minderwertiger Nachrichten, der Ausführungsstrom-Maskierung und der Anzeige von AlphaSift-Hotspot-Details.

### Neue Funktionen

- Neue unabhängige `DecisionSignal`-Speicherung, Repository, Service und `/api/v1/decision-signals`-API mit Deduplizierung, Abfrage, Verlängerung, Statusaktualisierung, Lazy-Verfall, Positionsfilterung und Maskierung sensibler Informationen nach Quelle/Markt/Aktie/Aktion/Frist/Phase.
- Neue Ausführungsstrom-Snapshot-API für Analysetasks und Historienberichte mit einheitlichem Vertrag für lanes, nodes, edges, events, summary, aufgebaut aus der Task-Warteschlange, der Laufzeitdiagnose und dem AnalysisContextPack-Überblick als maskierte Daten-/Informationsströme.
- Das Web ergänzt für aktive Tasks, Historienberichte und Marktreview-Berichte Einstiege in die Ausführungsstrom-Ansicht mit Laufzeitzusammenfassung, topologischen Knoten, Ereignisstrom und grundlegenden Fehlerbehebungsdetails.
- Neue AlphaSift-Hotspot-Themenkette: das Backend stellt die APIs `/api/v1/alphasift/hotspots` und `/api/v1/alphasift/hotspots/{topic}` bereit, die Web-Auswahlseite ergänzt einen Hotspot-Themenbereich mit Ansicht für Gärungsroute und Konzeptaktien.

### Verbesserungen

- Die Einzelaktienanalyse ergänzt eine pro Tag/Markt wiederverwendete Marktumgebungsübersicht; die normale Pipeline und die Agent-Analyse-Prompts können den wenig sensiblen Markt-Hintergrund lesen; neu die standardmäßig aktivierte Konfiguration `DAILY_MARKET_CONTEXT_ENABLED`, die Benutzer weiterhin explizit deaktivieren können.
- Die Einzelaktienanalyse sowie die Historie-/Backtest-Anzeige ergänzen optionale Acht-Zustands-`action` / `action_label`-Empfehlungsaktionsfelder; der Freitext `operation_advice` und die statistische Definition `decision_type=buy|hold|sell` bleiben erhalten.
- Ergänzt den typisierten Web-decision-signals-API-Wrapper und Vertragsisolationstests; die UI wird vorerst nicht angebunden.
- Vervollständigt den Laufzeitlog-Kontext mit logger-Name, Auslösequelle, Marktstatistik und Status der Echtzeit-Kurs-Prefetch-Kette, um die Fehlersuche in Scheduling-, API-, Bot- und Datenquellen-Degradationspfaden zu erleichtern.
- Die Positionsverwaltungsseite ergänzt das Löschen von Positionskonten, das die bestehende Soft-Delete-Schnittstelle von Konten wiederverwendet; fälschlich angelegte Konten werden aus Standardliste, Schnappschuss, Risiko, Erfassungseinstieg und Ereignisliste verborgen, ohne die historische Kontobewegung physisch zu löschen.
- Die AlphaSift-Abhängigkeitssperre wird auf `d038c52c468543726fc1fd830b53c27d3f09d6da` aktualisiert und für den neuen last-good-Snapshot, die Tageshistorie, den Branchen-/Konzept-Provider-Cache, das Hotspot-Ranking, die Themen-Gärungsroute, die Konzeptaktien-Details, den Cache des letzten erfolgreichen Hotspots und die post-analysis-Metainformationen die DSA-Laufzeit- und Web-Anpassung vervollständigt.
- Der AlphaSift-Hotspot-Themenabruf verwendet standardmäßig zuerst den Cache des letzten erfolgreichen Abrufs; nur die manuelle Aktualisierung ruft in Echtzeit ab und überschreibt den Cache, bei fehlgeschlagenem Echtzeitabruf wird möglichst auf den alten Cache zurückgegriffen.
- Der AlphaSift-Hotspot-Themenbereich wird standardmäßig eingeklappt und liest Details erst nach dem Aufklappen und Auswählen eines konkreten Themas; die Gärungsroute wird als Zeitlinie mit Zeitstempeln angezeigt, Konzeptaktien können angeklickt werden, um zur Startseite zu gelangen und direkt eine Analyse zu starten.
- Die AlphaSift-Hotspot-Themendatenkette nutzt denselben EastMoney-Branchenänderungs-Snapshot wieder und leitet Trend-Score, Fortbestehens-Score, Phase und Leader-Stichproben aus echten Prozentänderungen, Änderungshäufigkeit und Hochfrequenzaktien ab.
- Bei der Aktualisierung des AlphaSift-Hotspot-Themas wird bei wenigen oder fehlenden Kernfeldern auf der Vertragsebene auf die direkte DSA-EastMoney-Branchenänderungs-Rankingliste zurückgegriffen, lokale Hotspot-Caches mit weniger als 3 Einträgen werden ignoriert und Fallback-Felder der Branche ergänzt.
- Die AlphaSift-Hotspot-Themenkarte wird zu einem kompakteren Mehrspalten-Layout; die Konzeptaktienliste ergänzt eine separate Schaltfläche „Analysieren" zum Auslösen der Einzelaktienanalyse; Details bevorzugen die Zusammenführung von EastMoney-Komponentenaktien, THS-Parsing und dem Fallback des Branchenänderungs-Leaders, aggregiert nach Tagen in einer Gärungszeitlinie.
- Die AlphaSift-Hotspot-Themendetails ergänzen einen 30-Minuten-Disk-Cache auf DSA-Seite; beim erneuten Öffnen desselben Themas werden Gärungszeitlinie und Konzeptaktien-Details wiederverwendet; Themenereignisse zeigen nur echte Quellen wie die AlphaSift-Vertragszeitlinie, die THS-Zusammenfassung, die konfigurierte Nachrichtensuche oder die EastMoney-Branchenänderung.
- Die Nachrichtenkatalyse der AlphaSift-Hotspot-Themen wird als Zusammenfassung angezeigt: ist LLM konfiguriert, wird zuerst zu einer Ein-Satz-Themenkatalyse-Zusammenfassung komprimiert; ohne Konfiguration oder bei fehlgeschlagenem Aufruf fällt sie auf eine lokale Kurzzusammenfassung zurück.
- Die AlphaSift-Hotspot-Themenliste ergänzt optional den Detail-Prefetch `include_details`; das Web bringt standardmäßig mit der Hotspot-Liste die Top-Themen-Gärungsrouten und Konzeptaktien in einer Charge mit und nutzt den Frontend-Speichercache erneut; Nachrichtenkatalyse wird bei nicht verfügbarem LLM zur lokalen Ereignisinduktion.
- Umbau des Startverhaltens von `main.py --webui-only`: Ist der FastAPI-Überwachungsport bereits belegt, schlägt der Start sofort fail-fast mit einer klaren Fehlermeldung fehl und beendet sich.

### Behobene Probleme

- Folgefragen nach dem Einstieg über einen Historienbericht tragen ständig das aktuelle Ziel; beim Zurückwechseln oder Neuladen einer vorhandenen Sitzung kann der Basis-Ziel aus den Historienmeldungen wiederhergestellt werden, und das Backend blockiert falsche Aktien-Tool-Aufrufe, Börsenfragmente und die Fehlroutung von Indikatorabkürzungen, wenn nicht ausdrücklich gewechselt wurde.
- Das Hinzufügen und Entfernen von Watchlist-Aktien gleicht äquivalente Aktiencodes für Hongkong-Aktien und Groß-/Kleinschreibungsvarianten von US-Aktien ab, damit `00700`, `HK00700`, `00700.HK` oder `aapl`, `AAPL` nicht als verschiedene Ziele fehlinterpretiert werden.
- Strafft den legacy-Fallback der Empfehlungsaktion: Negations-/Vermeidungsausdrücke, chinesische Finanzkontexte, `buy or sell`, mehrdeutige Guard-Texte und englische Komposita werden nicht mehr fälschlich als action-Badge gerendert; bei strukturierter `action` zeigen Backtest-/Historientrend-Einstiege das action-Label in der UI-Sprache.
- Aktiennachrichten und mehrdimensionale Intelligenzsuche ergänzen nach der Relevanzsortierung einen domänenunabhängigen Zulassungsfilter, der Download-/Installationspaket-/App-Bewertungsseiten sowie Erwachsenen-/Begleitservice-Spam-Seiten entfernt und bei bereits vorhandenen gültigen Ziel-/Branchenkandidaten derselben Charge Einträge mit `score=0` als Hintergrundfüllung entfernt.
- Behebt, dass der Ausführungsstrom-Snapshot von Historienberichten bei Zeitstempeln mit gemischten Zeitzonen 500 zurückgab.
- Behebt, dass Live-SSE-Ereignisse des Ausführungsstroms nicht die rekursiven Maskierungsregeln der Snapshot-Ebene wiederverwendeten, sodass sensible Diagnosefelder wie lokale Pfade, prompt/raw response und Proxy-Header vor dem Refetch kurzzeitig offengelegt wurden.
- Die Standardlast der AlphaSift-Hotspot-Themen gibt bei fehlendem Cache und fehlendem `alphasift.hotspot`-Modul der alten Adapterebene einen Leerzustand zurück, statt beim Öffnen der Auswahlseite sofort „AlphaSift nicht bereit" anzuzeigen; die manuelle Aktualisierung weist weiterhin auf den benötigten Abhängigkeitsupdate hin.
- Ergänzt den Spaltennamen-Fallback für die THS-Gärungsroute: Wenn `stock_board_concept_summary_ths` fehlende Spalten zurückgibt, wird nur die Anreicherung dieser Quelle übersprungen, ohne die API-Antwort der Hotspot-Themendetails zu beeinträchtigen.
- Die Desktop-Veröffentlichungspaketierung prüft das `alphasift.dsa_adapter` über den Laufzeit-Probefinder des eingefrorenen ausführbaren Programms, damit macOS PyInstaller das Modul nicht als fehlend fehlinterpretiert, wenn es in die ausführbare Datei eingebettet ist.
- Die Anzeige der AlphaSift-Hotspot-Themendetails bevorzugt die vom Backend fusionierte `route`, damit die alte `timeline` die Nachrichten-/LLM-Zusammenfassung nicht überschreibt; beim manuellen Aktualisieren des Hotspot-Rankings wird zugleich der Details-Cache desselben Themas umgangen.

### Dokumentation

- Der Schnellstart-Einstieg des README und des traditionellen chinesischen README ergänzt Video-Tutorial-Links, und der Desktop-Client-Einstiegstext wird auf das Client-Konfigurationstutorial angepasst.
- Ergänzt `docs/alphasift-integration.md`: klargestellt die AlphaSift-gesperrte Commit-Quelle, die Hotspot-Vertragsgrenzen, die LLM/LiteLLM-Kompatibilitätssemantik und den Rollback-Pfad bei deaktiviertem Schalter.
- Ergänzt die Laufzeitreichweite, Kompatibilitätsgrenzen, offizielle semantische Grundlage und reguläre Release-Rollback-Erläuterungen von #1381.

### Tests

- Abdeckung der #1381-Backend-Laufzeit- und Kompatibilitätsverifikation: `tests/test_main_schedule_mode.py`, `tests/test_pipeline_daily_market_context.py`, `tests/test_daily_market_context.py`, `tests/test_daily_market_context_guardrail.py`, `tests/test_agent_executor.py`, `tests/test_config_env_compat.py`, `tests/test_config_registry.py` und `apps/dsa-web/tests/system_config_i18n.test.ts`.
- Neue/aktualisierte AlphaSift-Backend-Regressionen: `python -m pytest tests/test_alphasift_api.py -q`, `python -m pytest tests/test_docker_entrypoint.py -q`, `python -m pytest tests/test_main_schedule_mode.py -q -k "start_api_server_fails_before_thread_when_port_is_busy"`.

## [3.21.0] - 2026-06-07

### Release-Highlights

- feat: Neue Sprachumschaltung der Web-UI zwischen Chinesisch und Englisch sowie der Feishu-App-Bot-Benachrichtigungsmodus für bessere Erfahrungen bei Mehrbenutzer-Deployments und Unternehmensbenachrichtigungen.
- feat: Marktreview-Berichte, Historieneinstiege und die Aktienleiste werden weiterhin auf strukturierte Daten und einheitliches Markdown/GFM-Rendering konzentriert; manuelle Web/API-Trigger werden nicht mehr vom Handelstags-Gate kurzgeschlossen.
- feat: Marktreview-Berichte, Historieneinstiege und die Aktienleiste werden weiterhin auf strukturierte Daten und einheitliches Markdown/GFM-Rendering konzentriert; manuelle Web/API-Trigger werden nicht mehr vom Handelstags-Gate kurzgeschlossen.
- feat: Die AlphaSift-Auswahlkette wird zu wiederherstellbaren Hintergrundtasks umgestellt, ergänzt um die DSA-LLM-runtime-bridge, die Vorbereitung der Standard-Adapterebene und Kompatibilitätsregressionen.
- fix: Behebt verbliebenes Chinesisch in der englischen Oberfläche, Diagnoseanzeige, Anzeige von Laufzeitumgebungsvariablen, Health-Check, Desktop-Update-Pfad, Workflow-Variablenlesen und mehrere Probleme schmaler Web-Layouts.

### Neue Funktionen

- Die WebUI erhält einen unabhängigen UI-Sprachstatus und einen Umschalter für Chinesisch/Englisch, der Hauptnavigation, Startseite, Login, Einstellungsseite und allgemeine Steuerelementtexte abdeckt; die UI-Sprache ist von `report_language` entkoppelt und schreibt die Berichtssprachkette nicht um.
- Feishu-Benachrichtigungen ergänzen den App-Bot-Modus, der über `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` konfigurierbar ist, ohne einen zusätzlichen benutzerdefinierten Bot erstellen zu müssen.
- Die Web-Marktreview-Berichte erhalten eine spezielle Anzeigeansicht; Historieneinstiege und Sofortergebnisse der Startseite nutzen einheitlich Markdown/GFM-Rendering und blenden einzelaktien-spezifische Module aus.
- Die Marktreview ergänzt das strukturierte `market_review_payload`; Web, Historie-Details und Push rendern einheitlich auf Basis der strukturierten Daten und behalten die Markdown-kompatible Anzeige bei.
- Neuer standardmäßig deaktivierter AlphaSift-Auswahl-Tab, explizit gesteuert über `ALPHASIFT_ENABLED`, mit `/install` als explizitem Reparaturpfad.

### Verbesserungen

- Manuelle Web/API-Trigger der Marktreview werden nicht mehr durch die Handelstagsprüfung oder Marktschluss des betreffenden Markts kurzgeschlossen und übersprungen; Geplante Tasks, manuelle GitHub-Actions-Ausführungen und der CLI-Standardeinstieg behalten das ursprüngliche Handelstags-Gate.
- Die AlphaSift-Web-Auswahl wird auf Hintergrundtask-Übermittlung und Status-Polling umgestellt und zeigt wiederherstellbare Taskstatus, damit Browser-Langanfragen nicht timeouten, wenn externe Snapshots, Kursdaten oder LLM langsam werden.
- Die AlphaSift-Auswahl-API und die Dienstschicht konvergieren auf `AlphaSiftService`; Endpunkte übernehmen nur Routenparameter und Fehlerzuordnung.
- Die Laufzeit-LLM-Kompatibilitätsbrücke zwischen AlphaSift und DSA wird auf Aufrufzeit-Injektion umgestellt, behält die semantische Kette `provider/model/base_url/custom headers/fallback` bei und führt keine persistente Migration durch.
- Die Seitenleiste der Web-Startseite zeigt die Marktreview-Verlaufssammlung nicht mehr separat; die neueste Marktreview wird als `MARKET` in die Aktienleiste aufgenommen, sortiert nach der letzten Analysezeit, und nutzt die Auswahl-, Lösch-, Vollbericht- und Historientrend-Anzeigefähigkeiten der Aktienleiste wieder.
- Mehrfachaktien-Benachrichtigungsberichte fassen die Marktphase in einer einzelnen Zeile `Marktstatus` unter der Übersicht zusammen und zeigen Datenqualität und Limit-Details nicht mehr unter jeder Aktienzusammenfassung wiederholt an.
- Der Aufbau von API-Fehlerantworten konvergiert auf einen gemeinsamen Helper, behält die bisherige Fehler-Envelope-Form bei und reduziert Endpunkt-Wiederholungscode.
- Die WebUI gibt eine neue Laufzeitwarnung aus, wenn eine öffentliche Adresse gebunden ist oder CORS vollständig geöffnet ist und die Admin-Authentifizierung nicht aktiviert ist; dies erhöht nur die Beobachtbarkeit, blockiert den Start nicht und schreibt keine Konfiguration um.
- Die Datenbankinitialisierung ergänzt die `schema_migrations`-Baseline-Markierungstabelle und idempotente Aufzeichnungen für die spätere Schema-Entwicklungsverfolgung; keine Migration, keine Bereinigung, kein Umschreiben bestehender Geschäftstabellendaten.
- #1386 P6 nutzt Marktphase und die öffentliche AnalysisContextPack-Zusammenfassung für verknüpfte Alarme, manuelle Positionsanalysen, Historie, Backtest und Benachrichtigungsanzeige erneut, ohne neue Datenbankmigrationen.

### Behobene Probleme

- Die englische Web-Oberfläche vervollständigt die Lokalisierung von Texten für Backtest, Portfolio-Risiko und Alarmregeln, damit im englischen Modus keine chinesischen Filter, Schaltflächen und Enum-Labels zurückbleiben.
- Die Dimensionen Institutionsanalyse und Ertragserwartung der integrierten Intelligenzsuche verwenden ein 180-Tage-provider-Anfragefenster, damit der standardmäßige kurze Nachrichtenzeitraum keine periodischen Finanzmaterialien wie Finanzberichte und Research-Reports verpasst.
- In schmalen Layouts verdecken die Marktphasen-Labels der Web-Aktienleiste und Historienkarten den Aktiennamen nicht mehr.
- Freitext-Folgefragen im Fragedienst erkennen Finanzabkürzungen wie TTM, PE, YOY nicht mehr fälschlich als neue Aktiencodes.
- [Fix] Der Tagesanalyse-Workflow von GitHub Actions bevorzugt beim Lesen der selbst gehosteten SearXNG-Instanzadresse Variables und fällt auf Secrets zurück; behebt das Problem, dass die URL bei nur konfigurierten Variables nicht wirkt.
- Der Auswahlzustand der linken Navigation von Web/Desktop wird über border umgesetzt, damit der blaue vertikale Indikator nicht über den Seitenrand hinausragt; die aufgeklappte Seitenbreite ändert sich von 116px auf 136px, neu mit kompaktem Rail-Modus.
- Das Installationsverzeichnis der Windows-Desktop-Automatikupdates wird nicht mehr vorab in Anführungszeichen gesetzt, damit Pfade mit Leerzeichen beim automatischen Installieren nicht die Systemdialoge „Verknüpfung fehlt / Daily Stock Analysis.exe nicht gefunden" auslösen.
- Der Agent-Analysepfad nutzt vor der Erzeugung der AnalysisContextPack-Übersicht den bereits gespeicherten Tagesanalysekontext erneut, damit `daily_bars_missing` nicht mehr angezeigt wird, obwohl die Tagesdaten erfolgreich abgerufen wurden.
- Korrigiert die Verfügbarkeitsprüfung des strukturierten `breadth` der Marktreview: Wenn der Markt nicht unterstützt wird oder der Abruf fehlschlägt, wird `breadth` nicht gesendet und das Frontend zeigt „Keine Daten", um irreführende 0-Werte zu vermeiden.
- Das Sprachverhalten der Marktreview folgt dem globalen `report_language` und lokalisiert im chinesischen US-Aktien-Szenario Markt-Labels und Strategie-Blueprints, damit keine englischen Strategieabsätze hineingemischt werden.
- Beim Lesen der Konfiguration auf der Docker-Web-Einstellungsseite wird bei fehlenden Einträgen in der aktiven `.env`-Datei auf die beim Start injizierten gleichnamigen Umgebungsvariablen zurückgegriffen, und die Dokumentation der zugehörigen Mount-Grenzen wird vervollständigt.
- Die Laufzeitdiagnose der Berichtsseite unterscheidet zwischen erfolgreichem Datenquellen-Abruf und dem Eingang in die LLM-Analyse; der zugehörige Nachrichtenbereich wird als ergänzende/spätere Suche des Berichts gekennzeichnet, damit er nicht mit dem Status des Eingabedatenblocks verwechselt wird.
- Der Health-Check des `/health`-Wurzelpfads gibt jetzt immer JSON zurück, damit der statische Web-Fallback die Health-Probe nicht verschluckt; `/api/health` und `/api/v1/health` bleiben kompatibel.
- Bei deaktiviertem `ALPHASIFT_ENABLED` wird keine `alphasift`-Laufzeitinjektion ausgelöst; nach dem Aktivieren werden zuerst die konfigurierten DSA/provider-Einstellungen wiederverwendet und `LITELLM_*`- und `LLM_*`-Laufzeitvariablen injiziert.
- Vervollständigt die Kompatibilitätspfade und die Verifikation der Fallback-Kette für base URL, `extra_headers` und `LITELLM_FALLBACK_MODELS` im openai-compatible-Szenario.
- Die Desktop-/Image-Paketierungskette behält die mit der Laufzeit konsistente Vorbereitung der AlphaSift-Adapterebene bei, damit `pip install` nicht als Online-Reparaturabhängigkeit dient.

### Dokumentation

- Klargestellt, dass die Issue-#777-UI-Sprachumschaltung im Repository über `UiLanguageContext` + `uiText` umgesetzt wird, der Persistierungsschlüssel `dsa.uiLanguage` ist, und die zugehörigen visuellen Abnahmehinweise ergänzt.
- Klargestellt die Anzeigekette der Marktreview, die strukturierte Payload, das Sprachverhalten, die Unterschiede des Handelstags-Gates und die Rollback-Grenzen.
- Ergänzt die Fallback-Grenzen der LLM-/LiteLLM-Kompatibilitätsschlüssel im Anzeige- und Prüfkontext der Settings und erläutert, dass bestehende persistente provider/model/base-URL-Konfigurationen der Benutzer weder umgeschrieben, migriert noch bereinigt werden.
- Vervollständigt den Abdeckungsbereich des #1602-Fixes zur Laufzeitdiagnose-Definition; klargestellt, dass nur die Eingabe- und Anzeigedefinition vereinheitlicht wird, der Rollback erfolgt über den regulären Release-Rollback.
- Klargestellt die Dokumentation, Migrations- und Rollback-Grenzen von AnalysisContextPack P6 und synchronisiert das bestehende `SAVE_CONTEXT_SNAPSHOT` in `.env.example`, Konfigurationsregister, Web-Einstellungshilfe und vollständigen Leitfaden.
- Vervollständigt die Einstiege, Migration, Rollback und benutzersichtbaren Erläuterungen der #1386 P7-Analyse für Vorbörse/Mittag/Nachbörse.
- Ergänzt offizielle Kompatibilitätsbelege für die AlphaSift-runtime-bridge und stellt provider/model/base_url/extra_headers/fallback und die Rückfallgrenzen klar.

### Tests

- Im Web-Bereich werden `npm run lint`, `npm run build`, zugehörige Vitest- und Smoke-Befehle ausgeführt; ohne gesetztes `DSA_WEB_SMOKE_PASSWORD` werden Smoke-Fälle wie vorgesehen übersprungen.
- Die Web-Testlaufzeit deklariert Node `>=20.19.0 <27` und npm `>=10` und ergänzt einen localStorage-Test-Fallback zur Stabilisierung von Vitest.
- Ergänzt die statische Verifikation der AlphaSift-runtime-bridge und der Paketierskripte, abgedeckt sind `LLM_CHANNELS`, `LITELLM_FALLBACK_MODELS`, `alphasift.dsa_adapter` und `--collect-all alphasift`.

### chore

- Entfernt Screenshot-Assets, die versehentlich über den Issue-/PR-Abnahmeprozess ins Repository gelangt sind, und stellt klar, dass einmalige Screenshot-Nachweise in PR-Beschreibung, Kommentaren, Anhängen oder Artifacts verbleiben und nicht als Repository-Dateien eingepflegt werden.

## [3.20.0] - 2026-06-03

### Release-Highlights

- feat: Neuer AlphaSift-Auswahl-Einstieg, automatische Installation und stabile Adapterebene mit Unterstützung für Web-Strategieausführung, LLM-Reordering-Anzeige und eine standardmäßig deaktivierte, kontrollierte Aktivierung.
- feat: Vervollständigt die Sichtbarkeit von Einzelaktien-Historie, Watchlist-Warteschlange, Marktphase und AnalysisContextPack und stärkt die strukturierten Kontextfähigkeiten von Web-Bericht und API.
- feat: Das MiniMax-Standardmodell wird auf `MiniMax-M3` aktualisiert, ergänzt um zugehörige Preise, Presets und Testabdeckung.
- fix: Behebt Stabilitätsprobleme bei Health-Check, Windows-Desktop-Update und Erstlauf-Kodierung, ETF-Tages-secid, LLM-base_url-Prüfung und der Fehlbeurteilung des Agent-Tageskontexts.

### Neue Funktionen

- Neuer standardmäßig deaktivierter AlphaSift-Auswahl-Tab, der nach dem Aktivieren über `ALPHASIFT_ENABLED` über die stabile Adapterebene Strategien liest und die Aktienauswahl ausführt.
- Die linke Seitenleiste der Web-Startseite wird zu einer Aktienleiste, die nach Aktien dedupliziert anzeigt, Marktreview oben, beim Klick auf eine Einzelaktie wird der neueste Bericht geladen, und Varianten (.SZ/.SH/.SS) werden über Normalisierung dedupliziert und zusammengeführt. Die Einstiege für Alles auswählen, Batch-Löschen und Löschbestätigung bleiben erhalten; neu die Batch-Lösch-API nach Aktiencode `DELETE /api/v1/history/by-code/{stock_code}`.
- Die rechte Seitenleiste der Berichtsdetails ergänzt einen Watchlist-Aktions-Einstieg, der prüft, ob die aktuelle Aktie in der Watchlist ist, und Ein-Klick-Hinzufügen oder -Entfernen unterstützt; Marktreview-Berichte zeigen diese Aktion nicht.
- Die Fragedienst-Seite ergänzt oberhalb des Eingabebereichs eine Watchlist-Aktionsschaltfläche; nach dem Senden einer Nachricht mit Aktiencode werden die Einstiege „Zur Watchlist hinzufügen / Aus der Watchlist entfernen" automatisch angezeigt.
- Die Web-Berichtsseite ergänzt einen Drawer-Einstieg für den Historien-Trend derselben Aktie; die Historienlisten-Zusammenfassung ergänzt Felder für Trend, Zusammenfassung, Modell und Kursdaten zur Analysezeit und unterstützt das Anzeigen historischer Analysen der aktuellen Aktie mit „Mehr laden".
- Die wenig sensible AnalysisContextPack-P4-Übersicht wird in Historie-Details, synchrone Analyseantworten, completed-Taskstatus und die Web-Berichtsseite eingebunden und zeigt Datenblockstatus, Quelle, Fehlergrund und Degradationszusammenfassung.
- #1386 P5 ergänzt für Einzelaktien-Analyseberichte den `dashboard.phase_decision`-Entscheidungs-Guardrail während des Handels und beschränkt Hochkonfidenz-Kauf-/Verkaufs-Schlussfolgerungen während des Handels vor dem Speichern der Historie nach Marktphase und Datenqualität.
- #1386 P4a ergänzt den API-Parameter `analysis_phase=auto|premarket|intraday|postmarket` und reicht die angeforderte Phase in accepted asynchroner Aufgabe, In-Memory-Status, list, SSE und Analyse-Pipeline durch.
- #1386 P4b ergänzt auf der Web-Berichtsseite ein Label für die finale Marktphase, das Task-Panel zeigt die angeforderte Phase, und die wenig sensible AnalysisContextPack-Datenqualitätszusammenfassung wird wiederverwendet.
- Die MiniMax-Kanalmodellliste wird hochgestuft: Neu `MiniMax-M3` als Standardmodell, das laut offizieller OpenAI-compatible-Dokumentation einen 1M-Eingabekontext unterstützt (konservativ im `<=512K`-Preisband registriert: context_window 512K, `max_tokens` 128K, entsprechend $0.6/M Eingabe, $2.4/M Ausgabe; das Preisband >512K Eingabe ist nicht modelliert); `MiniMax-M2.7` und `MiniMax-M2.7-highspeed` bleiben erhalten, und der legacy-Preiseintrag `MiniMax-M2.5` bleibt zur Kostenschätzung für bestehende Benutzerkonfigurationen erhalten. Die MiniMax-Preset-Modelle und Preise der Web-Einstellungsseite werden auf M3 aktualisiert.
- Neue interne Vertrags- und Maskierungs-Serialisierungstests für AnalysisContextPack P1.
- Die wenig sensible Marktphasen-Zusammenfassung wird in die report-Metadaten von Historie-Details, synchronen Analyseantworten und completed-Taskstatus eingebunden.

### Verbesserungen

- Die Erstlauf-Konfigurationsprüfung ergänzt Diagnosen für fehlende AI-Keys, leere STOCK_LIST, gepaarte Telegram-/E-Mail-Felder und Webhook-URL-Präfixe.
- Der AlphaSift-Auswahl-Einstieg wird in der Web-Seitenleiste unter „Fragedienst" platziert, näher am Agent-/Recherche-Workflow.
- Die Docker-Image-Buildphase bereitet die Standard-AlphaSift-Adapterebene vor, um wie beim Desktop-Release-Paket eine zusätzliche Laufzeitinstallation zu vermeiden.
- Die AlphaSift-Auswahl hängt nun von der stabilen Schnittstelle `alphasift.dsa_adapter` ab; die Web-Strategieliste wird dynamisch von AlphaSift bereitgestellt und ist nicht mehr im Frontend hartkodiert.
- Die AlphaSift-Auswahlseite ergänzt Run ID, Snapshot-Anzahl, gefilterte Anzahl, Faktoren und Risikodetails, zeigt beim Aufklappen von Kandidaten echte Details und öffnet vorerst nur den aktuell unterstützten A-Aktien-Markt.
- Die Web-Einstellungsseite ergänzt eine AlphaSift-Auswahl-Schalterkarte zum direkten Aktivieren oder Deaktivieren des Auswahl-Tabs.
- Beim Aktivieren der AlphaSift-Auswahl wird zuerst `ALPHASIFT_ENABLED` umgeschaltet und die Verfügbarkeit der Adapterebene geprüft; fehlt sie, wird automatisch die kontrollierte Installationsschnittstelle aufgerufen, ohne dass der Benutzer zusätzlich auf Installation klicken muss.
- Ist AlphaSift aktiviert, die Adapterebene aber nicht vorhanden, serialisieren Strategieliste und Auswahl-Schnittstelle die automatische Installation mit gesperrter Quelle und erzwingen eine Neuinstallation, um alte `alphasift`-Pakete zu überschreiben.
- Die AlphaSift-Auswahlseite fasst wiederholte Snapshot-Quellen-Fallback-Hinweise zusammen und behält die Tushare-erst-Snapshot-Quellenlogik von AlphaSift selbst bei.
- Die AlphaSift-Auswahlseite zeigt bei LLM-Reordering-Degradation warning/source error/parse error und vermeidet, lokale Faktorbewertungen fälschlich als LLM-Urteil anzuzeigen.
- Die Web-Einstellungsseite zeigt `ALPHASIFT_ENABLED` nicht mehr als normalen Datenquellen-Konfigurationseintrag doppelt an; der Wert dient nur als persistierter Zustand hinter der Schaltfläche „Aktienauswahl aktivieren".
- Bei deaktiviertem AlphaSift wird der Navigations-Einstieg „Aktienauswahl" links im Web ausgeblendet, um Benutzer ohne Aktivierung nicht irrezuführen.
- Ergänzt die Anzeigelogik für benutzerdefinierte AlphaSift-Strategien, damit bei nicht übereinstimmenden Presets nicht fälschlich „Balanced Multi-Factor" angezeigt wird.
- Neuer Endpunkt GET /api/v1/history/stocks, der nach code gruppiert eine deduplizierte Einzelaktienliste zurückgibt; neue Endpunkte GET /api/v1/stocks/watchlist, POST /api/v1/stocks/watchlist/add und POST /api/v1/stocks/watchlist/remove unterstützen das Hinzufügen, Entfernen und Abfragen der Watchlist. Das Lesen/Schreiben von STOCK_LIST bleibt unverändert, keine automatische Normalisierung; bei add/remove wird per Normalisierung auf äquivalente Codevarianten verglichen.
- Neuer Hook useWatchlist verwaltet den Frontend-Zustand der Watchlist einheitlich und nutzt den STOCK_LIST-Konfigurationseintrag des SystemConfigService für die Persistierung.
- AnalysisContextPack P5 ergänzt Datenqualitäts-Score, den `fetch_failed`-Status, einen Prompt-Datenlimit-Block und die wenig sensible Qualitätsanzeige im Web.
- #1386 P2-full ergänzt in den AnalysisContextPack-Prompt-Datenlimits die Kreuzbeschränkungen zwischen Marktphase und degradierten Daten und korrigiert die phasenbezogenen Kursdaten-Labels des chinesischen Analyse-Prompts.
- Der Standard-Sendepfad von Benachrichtigungsberichten stellt die bestehende Kanal-Kompatibilitätskonvertierung und Aufteilungslogik wieder her; die neuen Renderer-Fähigkeiten bleiben nur als Basis für künftige Erweiterungen.
- Fehlen Typdaten bei zugehörigen Branchen, wird der Branchenname einzeilig angezeigt, um Branchentabellen mit einer ganzen `N/A`-Spalte zu vermeiden.
- Optimiert die Informationsebenen der Web-Berichtsdetailseite und verschiebt Eingabedatenblock und Laufzeitdiagnose in einklappbare Zusatzinformationen unter dem Hauptinhalt.
- Die Intraday-Analyse ergänzt die Abrufzeit der Echtzeit-Kursdaten, provider-Zeit, stale-, fallback- und partial/estimated-Markierungen für die Zuordnung der Eingabedatenlimits durch AnalysisContextPack.

### Behobene Probleme

- Der Agent-Analysepfad nutzt vor der Erzeugung der AnalysisContextPack-Übersicht den bereits gespeicherten Tagesanalysekontext erneut, damit `daily_bars_missing` nicht mehr angezeigt wird, obwohl die Tagesdaten erfolgreich abgerufen wurden.
- Registriert die Route /api/v1/health und nimmt sie von der Authentifizierung aus; behebt, dass dieser Pfad 404 zurückgab und Health-Proben nach Aktivierung von ADMIN_AUTH_ENABLED 401 erhielten.
- Die Windows-Erstlauf-Umgebungsprüfung ist kompatibel mit Nicht-UTF-8-Konsolenausgabe und wandelt die `requirements.txt`-Kommentare in ASCII, um die Ausfallwahrscheinlichkeit der Abhängigkeitsinstallation unter der Standard-Codepage zu senken.
- Die AlphaSift-DSA-Adapterebene aktiviert das LLM-Reordering standardmäßig, das Backend fordert explizit `use_llm=True` an, und die Auswahlseite zeigt LLM-Score, Urteil, Abdeckung und Beobachtungspunkte.
- Bei der Einbettung in DSA nutzt AlphaSift die bereits aufgelösten LLM-Modelle, Kanäle und Schlüsselkonfigurationen von DSA erneut, damit das Auswahl-LLM-Reordering trotz im Web konfiguriertem LLM nicht wegen fehlender provider keys degradiert.
- Beim Wiederverwenden des DSA-LLM-Routings filtert die AlphaSift-Auswahl nicht deklarierte Fallback-Modelle gehosteter provider und ergänzt die deklarierten Kanalmodelle in die Fallback-Kette, damit ein verbliebenes Gemini-Fallback keine verfügbaren DSA-Kanäle überschreibt.
- Die Standard-Installationsquelle von AlphaSift wird auf eine vertrauenswürdige, auf einen Commit gesperrte GitHub-Adresse umgestellt; die automatische Installation im Desktop-Modus erfordert keine Administrator-Sitzung, nicht-desktop-Bereitstellungen erfordern eine authentifizierte Administrator-Sitzung, und die Installationsquelle bleibt weiterhin eingeschränkt.
- Behebt, dass beim Aktivieren von AlphaSift im Web erst installiert und dann konfiguriert wurde, wodurch der standardmäßig deaktivierte Zustand nicht aktiviert werden konnte.
- Die AlphaSift-Status- und Installationsschnittstellen geben `install_spec` nicht mehr im Klartext zurück, sondern nur nicht sensible Statusfelder wie `install_spec_is_default`.
- Die AlphaSift-Statuserkennung unterscheidet fehlende optionale Abhängigkeiten von unerwarteten Ausnahmen; im Ausnahmefall wird eine Warnung protokolliert und nicht sensible Diagnoseinformationen werden zurückgegeben.
- Passt die Kompatibilität der AlphaSift-Screening-Aufrufe an: `screen` verwendet primär `max_results` und unterstützt das historische Keyword `max_output`, und die Strategie kann durchgereicht werden, um die manuellen Strategieparameter des Frontends auszurichten.
- AlphaSift-Web-Auswahlanfragen verwenden ein eigenes langes Timeout, damit sie nach dem Aktivieren des LLM-Reorderings nicht durch das generische 30-Sekunden-API-Timeout vorzeitig unterbrochen werden.
- Die Desktop-Paketierungsphase bereitet AlphaSift vor und sammelt die Adapterebene, damit das Release-Paket zur Laufzeit keine automatische Administratorinstallation mehr anfordert.
- Die automatische AlphaSift-Installation wird nur ausgelöst, wenn `status` als `missing_module` diagnostiziert wird (nur bei fehlendem Modul); ist die Adapterebene importierbar, aber die Laufzeit fehlerhaft, wird nicht mehr automatisch `pip install` ausgeführt, sondern `424` zurückgegeben und die Diagnose beibehalten, damit echte Laufzeitfehler nicht als Neuinstallation getarnt werden.
- Schließt verbliebene englische Texte in der chinesischen Web-Oberfläche und Lücken in der Einstellungshilfe; die Backtest-Seite zeigt auf Chinesisch an, und die Web-Einstellungsseite zeigt nur registrierte Konfigurationseinträge mit Beschreibung.
- Die Windows-Desktop-Automatikupdates verwenden bei der stillen Installation explizit das aktuelle Installationsverzeichnis wieder, damit das Entfernen alter Versionsdateien bei benutzerdefinierten Installationsverzeichnissen nicht fehlschlägt.
- Beim erneuten Versuch des Windows-Installers mit dem alten Uninstaller wird der `_?=`-Installationsverzeichnisparameter in Anführungszeichen gesetzt; behebt, dass bei auf einem Pfad mit Leerzeichen installierten alten Versionen 2 zurückgegeben wurde und das automatische Update scheiterte.
- Der an NSIS übergebene `/D=`-Verzeichnisparameter der Windows-Desktop-Automatikupdates wird bei Leerzeichen automatisch in Anführungszeichen gesetzt, damit die Installationsort-Registrierung nicht abgeschnitten wird.
- Härtet die base_url-Prüfung von LLM-Kanälen, damit Parsing-Unterschiede kein SSRF umgehen.
- Korrigiert das Eastmoney-secid-Routing der efinance-ETF-Tagesdaten, damit Shanghai-ETFs nicht mit der Shenzhen-Quote-ID abgefragt werden und die Tagesdaten leer bleiben.

### Dokumentation

- Klargestellt die Kompatibilitätsgrenzen von AlphaSift und LiteLLM: Nur die von DSA deklarierten provider/model/base-URL-Werte werden als Aufrufzeit-Injektion überbrückt, keine provider/model-Routing-Migration für `.env`; Rollback durch Deaktivieren von AlphaSift und Wiederherstellen der ursprünglichen `LITELLM_*`/`LLM_*`-Konfiguration.
- Klargestellt, dass AlphaSift nur die bestehende LLM/LiteLLM-Konfigurationssemantik von DSA wiederverwendet und keine Modellsemantikmigration für `LITELLM_MODEL`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, `LLM_TIMEOUT_SEC` usw. einführt; Fehlerhinweise und Fallback-Pfade folgen einheitlich der bestehenden Systemkonfigurationskette und betreffen nur die AlphaSift-Auswahlfähigkeit selbst.
- Klargestellt die Quellensperre der automatischen AlphaSift-Installation, die Grenzen von `missing_module` und Laufzeitausnahme-Verhalten sowie die Fallback-Pfade von LLM/provider/base URL und benutzerdefinierten Kanälen, um die Problemanalyse und den Rollback auf die ursprüngliche LLM-Konfiguration zu erleichtern.
- Klargestellt, dass die neuen Modellfelder der Historien-Trends derselben Aktie Metadaten der historischen Snapshot-Anzeige sind und weder das Laufzeit-LLM-Provider/Model/Base-URL-Routing noch die Konfigurationsmigrations-Bereinigung beeinflussen; Rollback durch den regulären Release-Rollback dieser Änderung.
- Klargestellt die Kompatibilitätsgrenzen von #1311: Die Rendering-Ebene konsumiert nur das Anzeigefeld `model_used` des Analyseergebnisses, die Sende-Kette der `wechat/slack/feishu/telegram`-Sender bleibt unverändert und es wird keine provider/model/base_url-Kompatibilitätsmigration ausgelöst.
- Klargestellt die Vertragsgrundlage von `alphasift.dsa_adapter` bei gesperrtem AlphaSift-Commit sowie die Kompatibilitätsgrenzen der aktuellen DSA-API/Web-Aufrufstruktur.
- Klargestellt, dass die Settings-Seite LLM-Konfigurationen nur in Anzeigegruppen und Feldzusammenführungen darstellt und weder LLM-Migrations-/Rollback-Pfade umschreibt noch auslöst; kompatibel mit der bestehenden `LLM`-Konfigurationsspeicherung und -Rückfallsemantik.
- Neue Kontextinventur für AnalysisContextPack P0.
- Vervollständigt die P8-Dokumentation des Alarmzentrums und die Konfigurationsabschluss-Erläuterungen; klargestellt die Grenzen von legacy JSON, erweiterten Regeln, Web/API, Docker, GitHub Actions und Desktop.

### Tests

- Aktualisiert synchron die Unit-Tests zu `llmProviderTemplates`, LiteLLM-fallback-pricing und MiniMax-Presets und prüft das neue Standardmodell.
- Ergänzt Regressionsabdeckung für ETF-Tagesdatenquellen-Routing, Eingabevarianten, Fallback und MA-Felder.

### chore

- Neue Kanal-Fähigkeitsprofile für Benachrichtigungsberichte, PreparedMessage und die strukturbewusste Markdown-Aufteilungs-Infrastruktur als Grundlage für die #1311-Kanalübergreifende Render-Adaption.
- Bereitet Renderer-Metadaten für WeCom, Feishu, Telegram, DingTalk und Slack vor, ohne den Standard-Push-Berichtseinstieg und das sichtbare Layout vorerst zu ändern.

## [3.19.0] - 2026-05-29

### Neue Funktionen

- Setzt die minimale Laufzeitdiagnose-Kette von #1391 Phase 1 um: task/SSE ergänzen trace_id und zeichnen ProviderRun-Snapshots für Tagesdaten und Echtzeit-Kursdaten auf.
- Das Alarmzentrum ergänzt P7 strukturierte Regeln für die Markt-Ampel, unterstützt `market_light_status` und `market_light_score_drop` und nutzt den bestehenden worker, die Auslösehistorie, Benachrichtigungen und die Cooling-Kette erneut.
- Setzt die Laufzeitdiagnose-Zusammenfassung von #1391 Phase 2 um: generiert eine benutzerlesbare RunDiagnosticSummary, stellt die Diagnose-API für Historienberichte und maskierten Kopiertext bereit.
- Setzt die Laufzeitdiagnose-Sichtbarkeit von #1391 Phase 3 um: Berichtsdetails und Task-Panel zeigen standardmäßig eingeklappt Laufzeitstatus, trace und kopierbare Fehlerbehebungsinformationen; das Backend stellt über `api/v1/history/{record_id}/diagnostics` und `context_snapshot.diagnostics` die Historien-Rückfüllung bereit.
- Neue interne Vertrags- und Maskierungs-Serialisierungstests für AnalysisContextPack P1.
- Neuer AnalysisContextPack-P2-Builder, der aus den vorhandenen Artefakten der normalen Analyse-Pipeline ein internes Kontextpaket zusammenstellt.
- Der Fragedienst ergänzt eine standardmäßig deaktivierte sichtbare Dialogkontext-Kompression mit Web-Schalter, erweiterten Agent-Presets, scrollender Zusammenfassung und Schutz der Originaltexte der letzten Runden, um den Tokenverbrauch langer Sitzungen zu senken.
- Der Index für die Aktien-Autovervollständigung unterstützt standardmäßig das Aktualisieren vom GitHub-main-Remote mit lokalem Cache; schlägt der Web/CLI-Analyseeinstieg fehl, wird automatisch auf den integrierten Index degradiert, um die Verschmutzung der Analyse durch alte Kurznamen nach Delisting und Umbenennung zu senken.
- Normale Analyse und Agent-Laufzeit-Prompts binden die wenig sensible AnalysisContextPack-Zusammenfassung ein und bleiben kompatibel mit der history/API/Web-Ausgabe.

### Verbesserungen

- `scripts/fetch_tushare_stock_list.py` kann Namen von A-Aktien mit den Präfixen `XD`/`XR`/`DR`/`N`/`C` per Rückfüllung korrigieren und wird vom Aktualisierungsablauf der Autovervollständigung standardmäßig verwendet.
- Die Web-Routenseite wird auf Bedarfsladung umgestellt, senkt das erste Paketvolumen und ergänzt einen Wiederherstellungshinweis bei fehlgeschlagenem Routenladen.
- Der Markdown-Drawer des vollständigen Web-Berichts wird auf Bedarfsladung umgestellt.
- Neue Marktphasen-Inferenz-Baseline mit klarer Semantik für Vorbörse, Handel, Mittagspause, nahe Handelsschluss, Nachbörse und Nicht-Handelstage.
- Neue Tests für Laufzeit-Marktphasen-Kontextaufbau und -Degradation.
- Die Konfigurationshilfe der Einstellungsseite vervollständigt phasenweise die chinesischen und englischen Texte der tatsächlich angezeigten/konfigurierbaren Felder der Web-Einstellungsseite, abgedeckt sind Agent, Backtest, Bericht, Benachrichtigungs-Routing, System-Laufzeit, AI-legacy, Datenquellen und erweiterte Benachrichtigungskonfiguration.
- P2-min: Der LLM-Prompt injiziert den Marktphasen-Kontext.

### Behobene Probleme

- Die Indexgenerierung der Aktien-Autovervollständigung schlägt ohne `pypinyin` jetzt direkt fehl, statt einen degradierten Index mit fehlenden Pinyin-Feldern zu schreiben.
- Normalisiert das Handelsvolumen der Tencent-Echtzeit-Kursdaten auf die Aktien-Definition, damit Verstärkungsfaktoren der Volumenveränderung nicht überhöht werden und Analyseberichte nicht irreführen.
- Die Docker-Standardbereitstellung entfernt das Einzeldatei-Mount von `.env`, damit das Speichern der Konfiguration in der WebUI über `os.replace` am Mount-Punkt nicht `Device or resource busy` auslöst.
- Konvergiert die A-Aktien-Code-Zuordnung von #1391 Phase 0: vervollständigt die Zuordnungskonsistenz für die `SH`/`SZ`-Präfixe und stellt den Reparaturumfang dieser Runde für `data_provider/baostock_fetcher.py`, `data_provider/pytdx_fetcher.py` und `data_provider/tushare_fetcher.py` klar.
- Behebt die interne Formatkonvertierung der Fallbacks von Datenquellen wie Baostock bei nackten A-Aktien-Codes in `STOCK_LIST`, damit die Benutzerkonfiguration weiterhin 6-stellige Aktiennummern verwendet.
- Die Windows-Desktop-Automatikupdates führen den Installer nach bestätigtem Neustart-Installieren still aus und bereinigen nach dem Stoppen des eingebetteten Backends die Prozessreferenzen, um die Wahrscheinlichkeit der Installer-Meldung „Daily Stock Analysis kann nicht geschlossen werden" zu senken.
- Die macOS-Desktop-Version migriert die Laufzeitkonfiguration in das Benutzerdatenverzeichnis und migriert `.env`, Datenbank und Logs, solange die Dateien im alten `.app`-Paket noch zugänglich sind, damit nach der Ersatz-Upgrades keine Neukonfiguration nötig ist.
- Stellt die Extraktion der zugehörigen Branchen und Branchenverknüpfungsfelder in den Agent-/Historie-Kompatibilitätssnapshots wieder her und behebt die Regression, dass der neuen Startseite der Berichte der Abschnitt „Branchenverknüpfung" fehlte.
- Korrigiert die Feldnamen des legacy-Alarm-JSON und die Zustellsemantik des Stummzeitraums in der Web-Einstellungshilfe.
- Behebt fehlende Übersetzungen von Konfigurationstiteln, Erläuterungen und wichtigen Dropdown-Optionen der chinesischen Web-Einstellungsseite in den Bereichen Datenquelle, Benachrichtigung, System und Agent.
- Behebt, dass nach dem Sitzungswechsel im Fragedienst und dem Wiederverbinden von Startseiten-Tasks ein verbleibender „Agent/Analysetask läuft"-Status auftreten kann.
- Der single-agent des Fragediensts ergänzt eine provider-aware trace-Trennung und behält über Runden hinweg `reasoning_content` und Tool-Protokollmaterial von DeepSeek-V4-thinking + Tool-Aufrufen.
- Fügt den Sina/Tencent-A-Aktien-Historie-Fallback-Schnittstellen von Akshare ein Aufruf-Timeout hinzu und ergänzt Regressionsumd tests für die Shanghai-Coderoute `605xxx` von Tushare, damit geplante Analysen nicht wegen nicht reagierender Datenquellen hängen bleiben.
- Hebt die Untergrenze der `exchange-calendars`-Abhängigkeit auf `4.13.0`, damit der Import des Handelskalenders in pandas-3-Umgebungen nicht wegen der ungültigen Timedelta-Einheit `T` fehlschlägt und die Analyse scheitert.
- Analyseergebnisse, die von interaktiven Befehlen (DingTalk-Sitzungen, Feishu-Sitzungen, Telegram) ausgelöst wurden, gehen nur an die Quellsitzung zurück und werden nicht mehr gleichzeitig an statische Benachrichtigungskanäle übertragen.
- Passt die Longbridge-OAuth-2.0-Authentifizierung und die Token-Cache-Wiederherstellung an, damit die Langbridge-Datenquelle ohne Legacy Access Token in neuen Backends nicht fälschlich als nicht konfiguriert eingestuft wird.
- Der Longbridge-OAuth-Pfad protokolliert bei aktuellen SDKs ohne Unterstützung von `OAuthBuilder` / `Config.from_oauth` eine klare Degradierung, damit der Build auf Linux/Docker mit nur installierbarem alten SDK nicht fehlschlägt.
- Kompatibel mit dem Szenario, in dem YFinance-Tagesdaten einen unbenannten Datumsindex zurückgeben, damit nach der Normalisierung eine fehlende `date`-Spalte den US-Aktien-Tages-Fallback nicht unterbricht.

### Dokumentation

- Neues Vertragsdokument für die #1391-Phase-0-Laufzeitdiagnose, das trace_id, Diagnosezusammenfassung, Umfang der Schlüsselpipelines sowie die Grenzen von Maskierung/fail-open/Retention klarstellt.
- Vervollständigt die P8-Dokumentation des Alarmzentrums und die Konfigurationsabschluss-Erläuterungen; klargestellt die Grenzen von legacy JSON, erweiterten Regeln, Web/API, Docker, GitHub Actions und Desktop.
- Erläutert, dass dieser Desktop-Fix nur die Windows-NSIS-Update-Installationskette und die Bereinigung des Backend-Prozesslebenszyklus abdeckt; die Speichersemantik der Einstellungseinträge und die Laufzeitbereinigung der Modelle bleiben unverändert. Entfernt die versehentlich eingefügte `npm registry`-Änderung in `docker/Dockerfile` und stellt die Verantwortungstrennung zwischen Bereitstellungs-Build und Update-Fix wieder her.
- Neue Kontextinventur für AnalysisContextPack P0 mit klarem Feldqualitätsstatus, bestehendem Statusmapping und den Grenzen des Pakets der ersten Version.
- Klargestellt, dass die strukturierten Erkennungswarnungen von #1391 Phase 2 kein Konfigurationsmigrationssignal sind: ungültige Werte von `agent_max_steps`/`agent_orchestrator_timeout_s` fallen auf den Standard zurück und erzeugen eine Log-Warnung, die neue Diagnosekette ergänzt nur die Lese-/Schreibfelder `context_snapshot`/`RunDiagnosticSummary` und schreibt weder `litellm_model`, `agent_litellm_model`, `openai_base_url`, das LLM-Kanal-Routing noch die Konfigurationsmigrationssemantik um.
- Ergänzt die Kompatibilitätserläuterung von #1391 Phase 3: protokolliert die Änderungsgrenzen und die Rollback-Strategie der Backend-Diagnose-Persistierung, der Historienabfrage und der Benachrichtigungs-Rückkette und vervollständigt die Gate-Verifikationsanforderungen des Backends.

### Tests

- Konvergiert die Backend-/API- und Web-Regressionsprüfungen von #1391 Phase 3: `./scripts/ci_gate.sh`, `test_pipeline_market_phase_context.py`, `test_analysis_api_contract.py`, `test_analysis_history.py`, `npm run lint`, `npm run build`.
- Ausführen von `python -c "import exchange_calendars as xcals; xcals.get_calendar('XSHG'); print('ok')"`, das erfolgreich durchläuft, um die Import- und Handelskalender-Initialisierungskompatibilität abzudecken.

## [3.18.0] - 2026-05-21

### Release-Highlights

- feat: Das Alarmzentrum wird auf P2-P6 erweitert und vervollständigt Hintergrundbewertung, echte Benachrichtigungsergebnisse, Geschäftskühlung, Technische-Indikatoren-Regeln sowie verknüpfte Regeln für Watchlist / Position / Konto.
- feat: Die Einzelaktienanalyse unterstützt die Strategiewahl, ergänzt die Strategien Hotspot-Themen, Ereignisgetrieben, Wachstumsqualität und Erwartungs-Neubewertung und fügt für HK/US-Berichte Fundamentaldaten, Finanzzusammenfassung, Aktionärsrendite und zugehörige Branchen hinzu.
- feat: Neue Adapter für die US-Aktien-Datenquellen Finnhub / AlphaVantage, erweitert die US-Aktien-Tages-Failover-Kette und erhöht die Robustheit des US-Kursabrufs.
- fix: Behebt Stabilitätsprobleme bei der Desktop-Release-Paketierung, der Analyse-Status-Schnittstelle, der AlphaVantage-Prozentänderung, der Echtzeitbewertung von Positionen, der Deduplizierung der Alarmhistorie, dem Datenbank-Kaltstart und der Registrierung des fallback pricing.

### What's Changed

- feat: Add alert-center P2-P6, Web strategy selection, HK/US fundamental context, static-report financial sections, and Finnhub / AlphaVantage US-market fallback.
- improve: Refine LiteLLM parameter recovery, yfinance currency/dividend handling, RSI calculation, market-review presentation, stock-news relevance ranking, and report table rendering.
- fix: Harden desktop packaging/update assets, completed analysis-status responses, AlphaVantage pct_chg routing, portfolio realtime snapshots, alert trigger dedupe, DatabaseManager cold start, and fallback pricing registration.
- docs/tests: Add beginner setup and settings-help docs, document compatibility/rollback boundaries, and extend regression coverage for API, alert, packaging, and release paths.

## [3.17.1] - 2026-05-16

### Release-Highlights

- fix: Die Windows-/macOS-Paketierskripte des Desktops deaktivieren explizit die automatische electron-builder-Veröffentlichung, damit Tag-Builds nach dem lokalen Paketieren nicht wegen fehlender `GH_TOKEN` fehlschlagen; der Release-Workflow ist weiterhin für Upload und Veröffentlichung der Artefakte zuständig.

### What's Changed

- fix: Add `--publish never` to the Windows and macOS Electron packaging scripts so tag builds only create local artifacts and GitHub Actions handles release upload/publish.

## [3.17.0] - 2026-05-16

### Release-Highlights

- feat: Neues Alert-API-MVP mit CRUD für Alarmregeln, Aktivieren/Deaktivieren, einmaligem Test sowie Abfrage von Auslöse-/Benachrichtigungsergebnissen; die erste Version deckt `price_cross` / `price_change_percent` / `volume_spike` ab und bleibt kompatibel zur legacy-Konfiguration.
- feat: Der Benachrichtigungs-Gateway ergänzt ntfy und Gotify als erstklassige Kanäle sowie Benachrichtigungs-Entrauschung, statische Kanalisolation, Diagnose, Web-Tests und die Abgleichprüfung der GitHub-Actions-env.
- feat: Die Windows-Desktop-Installationsversion bindet die automatische Update-Installationskette an, mit Hintergrund-Download, bestätigtem Neustart-Installieren, Laufzeitdatei-Backup/-Wiederherstellung und Metadatenprüfung der Release-Artefakte.
- improve: Die Marktreview ergänzt Basisdatenquellen wie Konzept-Ranking, beliebte Aktien und Limit-up-Pool, unterstützt die Konfiguration der Farb-Semantik für Indexanstiege/-rückgänge und schreibt die Review-Ergebnisse in die Historienaufzeichnungen.
- improve: Die Web-Einstellungsseite unterstützt Backup-Import/-Export der `.env`-Konfiguration und lokale Fehlerfallbacks der Bereiche Benachrichtigung/Agent; Berichte ergänzen den Schalter `REPORT_SHOW_LLM_MODEL` zur Steuerung der Modellinformationsanzeige.
- improve: Der Docker-Starteinstieg repariert automatisch die Berechtigungen der gemounteten Verzeichnisse und degradiert bei nicht beschreibbarem Log-Verzeichnis auf die Konsole, um manuelle Reparaturschritte normaler Bereitstellungen zu reduzieren.
- fix: Sanftere Degradierung bei fehlenden Credentials oder Verbindungsfehlern der Datenquelle, Longbridge / Pytdx werden gekühlt, und bei fehlendem Kapitalfluss werden keine Hochkonfidenz-Kauf-Schlussfolgerungen ausgegeben.
- fix: Die Analyse- und Berichtskette ist kompatibel mit OpenAI-compatible-`content_blocks`-Antworten, normalisiert die Preis-Felder der Strategie und behebt Probleme beim Scrollen der Marktreview und beim Verlust von Historienaufzeichnungen.
- docs: Vervollständigt Benachrichtigung, Alarmzentrum, Desktop-Paketierung, README / Leitfaden und die Governance-Erläuterungen für PR-Titel; stellt mehrere Konfigurationskompatibilitätsgrenzen und Rollback-Pfade klar.
- test: Erhöht die Regressionsabdeckung für Alert-API, Benachrichtigungs-Entrauschung/-Routing, Docker-Entrypoint, Datenquellen-Prefetch, Desktop-Update-Kette und Analysehistorie.

### What's Changed

- feat: Add an Alert API MVP with rule CRUD, enable/disable, one-shot testing, trigger history, notification results, and legacy config compatibility.
- feat: Promote ntfy and Gotify to first-class notification channels with Web tests, routing, Actions integration, diagnostics, and noise control.
- feat: Add the Windows desktop auto-update install flow with runtime state backup/restore and release artifact metadata verification.
- improve: Extend market review data sources, add configurable index color semantics, and persist market review results into analysis history.
- improve: Add Web `.env` backup import/export, local settings panel error boundaries, and a report model visibility toggle.
- improve: Harden Docker startup by repairing mounted directory permissions and falling back to console logging when mounted logs are not writable.
- fix: Cool down unavailable optional fetchers, reduce noisy Longbridge/Pytdx retries, and downgrade buy advice when capital flow data is missing.
- fix: Handle OpenAI-compatible `content_blocks`, normalize strategy price fields, and recover market review scrolling/history behavior.
- docs/tests: Update notification, alert, desktop packaging, README/guide, and governance docs; add focused regression coverage for the new release paths.

## [3.16.0] - 2026-05-10

### Release-Highlights

- feat: Die Web-Startseite ergänzt den Auslöse-Einstieg „Marktreview", Task-Polling und die direkte Berichtsausgabe nach Abschluss; der Konfigurationsstatus beim ersten Start weist auf Lücken hin und leitet zur Systemeinstellung.
- feat: Neue Benachrichtigungs-Routingstrategie, die Benachrichtigungen nach report, alert, system_error auf festgelegte Kanäle einschränkt; die Web-Einstellungsseite unterstützt Ein-Klick-Tests der Benachrichtigungskanäle.
- feat: Die Systemeinstellungsseite ergänzt einen Hilfe-Einstieg für Konfigurationseinträge und die mehrsprachige Hilfe-Text-Infrastruktur; die erste Charge deckt Watchlist, LLM-Hauptmodell, LLM-Kanal, Feishu-Webhook und die WebUI-Lauschadresse ab.
- improve: Marktreview-API, CLI und Bot teilen den Assembly-Pfad `build_market_review_runtime` und vervollständigen die Erläuterungen zum Fallback von `litellm_model` / `llm_model_list` und legacy keys.
- improve: Die Aktionsempfehlungen des Einzelaktienberichts kalibrieren mit Unterstützung/Widerstand, Volumen, Chips und Hauptkraft-Kapitalfluss, reduzieren heftige Kauf-/Verkaufswechsel und stärken den Agent-Entscheidungs-Fallback.
- improve: Docker-Images unterstützen den Betrieb als Nicht-root-Benutzer, und die LiteLLM-Abhängigkeitsbeschränkung wird auf spätere sichere 1.x-Reparaturversionen gelockert.
- fix: Korrigiert die Fehlerklassifizierung von `Model disabled`, provider blocked usw. in LLM-Kanaltests, damit sie nicht fälschlich als Netzwerkanomalien gemeldet werden.
- fix: Die Hongkong-Tagesdaten überspringen eingebaute Historien-Datenquellen, die Hongkong-Aktien nicht unterstützen; die `BJ`-Präfix- und `.BJ`-Suffix-Codeprüfung der Pekinger Börse wird konsistent gehalten.
- fix: Die Beobachtbarkeit des Web-Marktreview-Buttons, die Windows-Fallback-Sperrprozesserkennung und die Anzeige von Katalysator-Hinweisen werden robuster.
- docs: Neue Wartungshinweise für das Dokumentationszentrum und die Konfigurationshilfe; bereinigt temporäre PR-/Dokumentationssynchronisations-Hinweise in README, vollständigem Leitfaden und Konfigurationsleitfaden.

### What's Changed

- feat: Add a Web home market-review trigger with task polling and inline report display; setup status now points users to missing configuration.
- feat: Add notification routing by report, alert, and system_error; add one-click notification channel testing in Web settings.
- feat: Add settings field help infrastructure with multilingual help text for the first batch of core configuration fields.
- improve: Share `build_market_review_runtime` across API, CLI, and Bot market review paths; document `litellm_model` / `llm_model_list` and legacy key fallback behavior.
- improve: Calibrate stock advice with support/resistance, volume, chips, and main-force capital flow; strengthen Agent decision fallback behavior.
- improve: Run Docker images as a non-root user and relax LiteLLM constraints to allow safe future 1.x fixes.
- fix: Classify `Model disabled`, provider blocked, and related LLM channel test errors more accurately instead of reporting them as generic network failures.
- fix: Avoid unsupported built-in historical providers for Hong Kong daily data; align Beijing Stock Exchange `BJ` prefix and `.BJ` suffix validation.
- fix: Improve Web market-review observability, Windows fallback lock probing, and market catalyst snippet rendering.
- docs: Add the documentation index and settings-help maintenance guide; remove temporary PR/doc-sync notes from README and user-facing guides.

## [3.15.0] - 2026-05-05

### Release-Highlights

- Die LLM-Kanal-Konfigurationserfahrung wird weiter aufgewertet: neue Anbindung des Anspire-OpenAI-compatible-Gateways sowie vollständige Presets gängiger Anbieter, offizielle Quellen, Fähigkeitslabels, Konfigurationshinweise und explizite GitHub-Actions-Zuordnungen.
- Die Web-LLM-Konfigurationserkennung ist besser diagnostizierbar: verfeinerte Fehler-reasons und Benutzer-ausgelöste Laufzeit-Smokes für JSON, tools, vision und stream.
- Die Bereinigung der LLM-Laufzeitkonfiguration wird robuster: nur ungültige Laufzeitauswahlen gehosteter provider werden bereinigt, die Kompatibilitätssemantik von Direktverbindungs-providern wie `cohere/*`, `google/*`, `xai/*` bleibt erhalten.
- Erhöhte Beobachtbarkeit von Benachrichtigung und Bot-Status: Benutzerdefinierte Webhooks unterstützen JSON-body-Vorlagen, Bot `/status` zeigt vollständigere LLM-, Agent- und Benachrichtigungskanal-Status.
- Marktreview, Echtzeit-Alarme, Agent-weak-Fallback und Positionsbewertung werden weiter gestärkt, um Kosten für Standardwert-Überschreibungen, Fehlpreis-Verschmutzung und Konfigurations-Fehlerbehebung zu senken.

### Neue Funktionen

- Unterstützt über `ANSPIRE_API_KEYS` die Standardanbindung des Anspire-OpenAI-compatible-LLM-Gateways und ergänzt im LLM-Kanal-Editor das Anspire-Open-Preset.
- Benutzerdefinierte Webhooks unterstützen die JSON-body-Vorlage `CUSTOM_WEBHOOK_BODY_TEMPLATE` für die Anpassung an AstrBot, NapCat und selbst gehostete Push-Dienste.
- Der strukturierte Marktreview-Block ergänzt die Markt-Ampel-Schlussfolgerung, die basierend auf der Markttemperatur green/yellow/red, Kernursachen und Aktionsempfehlungen ausgibt.
- EventMonitor unterstützt die Schwellenregel `price_change_percent` für Prozentänderungen und kann Echtzeit-Alarme nach Anstiegs- oder Rückgangsrichtung auslösen.
- Der Web-LLM-Kanal-Editor ergänzt Konfigurationsvorlagen und Presets gängiger Anbieter, abgedeckt sind Einstiege wie MiniMax, Volcano Ark, OpenAI, Claude, Gemini, Kimi, Qwen, GLM und Doubao.

### Verbesserungen

- Die Web-LLM-Konfigurationserkennung ergänzt verfeinerte Fehlerklassifikationen und neu explizit ausgelöste Laufzeit-Smokes für JSON/tools/vision/stream; Standardtest- und Speicherablauf bleiben unverändert, das Erkennungsergebnis dient nur als einmalige best-effort-Diagnose der aktuellen Konfiguration.
- Bot `/status` zeigt das einheitliche LLM-Hauptmodell, das Agent-Modell, den Kanalmodus, die YAML-Konfiguration und weitere Benachrichtigungskanal-Status.
- Der Web-LLM-Kanal-Editor zeigt provider-Fähigkeitslabels, offizielle Quelllinks und Konfigurationshinweise; diese Labels dienen nur als Konfigurationsreferenz und bedeuten nicht, dass die Laufzeitfähigkeit verifiziert ist.
- Extrahiert die einzige Vorlagen-Datenquelle der Web-LLM-provider-Presets und behält die bestehende Speichersemantik der Konfiguration bei.
- Vervollständigt die explizite Zuordnung der LLM-provider-Kanäle in GitHub Actions und synchronisiert das `.env`-Beispiel und die Konfigurationsdokumentation.

### Behobene Probleme

- Der Agent-weak-Integritäts-Fallback behält bei fehlendem Score, Trend, Aktionsempfehlung oder Schlüsselblöcken des Dashboards im Modell zuerst die lokalen Trendanalyseergebnisse bei und ergänzt nur wirklich fehlende Dashboard-Felder, damit der Startseiten-Score nicht vom Standardwert 50 überschrieben wird.
- Vereinheitlicht die Ausgabe von Aktuellpreis, Marktwert, unrealisierter Gewinn/Verlust, Rendite und Preis-Metainformationen des Positions-Schnappschusses, damit fehlende Preise oder stale Preise die Positionsbewertung nicht verschmutzen.
- LLM-Kanaltests ergänzen strukturierte Diagnosen und Fehlerbehebungshinweise der Einstellungsseite, um Probleme bei provider, Modell, Base URL und Authentifizierungskonfiguration zu lokalisieren.
- Klargestellt die Kompatibilitätsgrenzen der Laufzeitbereinigung: Die Bereinigung ungültiger Werte vor dem Speichern wird nur für gehostete provider (`gemini`, `vertex_ai`, `anthropic`, `openai`, `deepseek`) ausgelöst; Direktverbindungswerte von `cohere/*`, `google/*`, `xai/*` bleiben über den legacy-Kompatibilitätspfad erhalten, keine stillschweigende Migration oder Überschreibung.
- Passt das MiniMax-Preset an die offizielle OpenAI-compatible-Base-URL und aktuelle Modellbeispiele an und ergänzt Kompatibilitätsquellen und Fallback-Erläuterungen für MiniMax, Volcano Ark und LiteLLM.
- Entfernt die veraltete Degradationslogik der Screenshot-Erkennung für das Gemini-3-Vision-Modell; die Standard-Inferenz verwendet die aktuelle Gemini-Modellkonfiguration.

### Dokumentation

- Vervollständigt die LLM-provider-Konfigurationsdokumentation und ergänzt die Auswahl der Konfigurationsweise, den Actions-Variablen-Abgleich, die Laufzeiterkennungsgrenzen, die Fehlerbehebung per error reason und den Rollback-Pfad (#1180).
- Ergänzt für den LLM-Kanal-Editor offizielle Quellen, das Abhängigkeitskompatibilitätsfenster, die Laufzeitmodell-Bereinigungsregeln beim Speichern und die Erläuterung des Rollback-Pfads für alte Konfigurationen.
- Ergänzt für die Direktverbindungssemantik von `cohere/*`, `google/*`, `xai/*` offizielle provider/model-Erläuterungen und den Kompatibilitätsbeleg `litellm>=1.80.10,<1.82.7` und stellt klar, dass Beispielmodellnamen nur das Konfigurations-Erhaltungsverhalten erläutern und keine Verfügbarkeitsempfehlung darstellen.
- Klargestellt, dass die `price_change_percent`-Ereignisalarme nur eine Erweiterung der Konfigurations- und Laufzeitregeln sind und die Modell-/provider-/base-URL-/LiteLLM-Kompatibilitätssemantik unverändert bleibt; Rollback durch Deaktivieren/Entfernen der Event-Monitor-Konfiguration.
- Synchronisiert die zugehörigen Hinweise von README, DEPLOY, full-guide, Anspire, AIHubMix und SerpAPI und vereinheitlicht externe Links, die Konfigurationsdefinition und die Konsistenzerläuterungen der Review.

### Tests

- Vervollständigt die Regressionsnachweise der LLM-Laufzeitbereinigung/-synchronisation der AI-Konfigurationsseite und von `task_queue`: beim Wiederherstellen von Kanalmodellen bleibt fallback erhalten, beim Bearbeiten der Modellliste wird die Laufzeitauswahl nicht stillschweigend geleert, bei Kanälen ohne verfügbares Modell werden ungültige Laufzeitreferenzen bereinigt, und die Erhaltungssemantik von legacy keys und Direktverbindungs-providern `cohere/*`, `google/*`, `xai/*` ist abgedeckt.
- Abgedeckt sind die verfeinerten Fehlerklassifikationen der Web-LLM-Konfigurationserkennung und die expliziten Auslösepfade der Laufzeit-Smokes für JSON, tools, vision und stream.

## [3.14.2] - 2026-04-30

### Release-Highlights

- Die Marktreview wird auf Hongkong-Aktien erweitert und lässt Bot `/market` sowie CLI-/Scheduling-Einstiege dieselbe Handelstagsfilter-Semantik verwenden.
- Der Fragedienst- und Agent-Pfad verbessern die Erfahrung bei fehlender Konfiguration, Entscheidungs-Fallback und Mehrstrategie-Auswahl.
- Die LLM- und Analyseberichtskette erhöht die Stabilität: Bei ungültigen JSON-Antworten werden weiterhin Ersatzmodelle versucht, LiteLLM-DEBUG-Logs werden standardmäßig entrauscht.
- Neue schreibgeschützte Schnittstelle für den Erststart-Konfigurationsstatus als Grundlage für den späteren Konfigurationsassistenten und Smoke-Run.

### Neue Funktionen

- Die Marktreview unterstützt den Hongkong-Markt: `MARKET_REVIEW_REGION` erhält die Option `hk`; `both` wird auf A-Aktien + Hongkong-Aktien + US-Aktien erweitert, und neu die Review-Kette für Hongkong-Indizes (HSI/HSTECH/HSCEI).
- Neue schreibgeschützte Erststart-Konfigurationsstatus-Schnittstelle `GET /api/v1/system/config/setup/status` zur Erkennung von Konfigurationslücken bei LLM, Agent, Watchlist, Benachrichtigung und lokalem Speicher; die Schnittstelle lädt die Laufzeit nicht neu, schreibt kein `.env` und erstellt keine Datenbankdateien.

### Verbesserungen

- Die Fragedienst-Seite unterstützt die kombinierte Auswahl mehrerer Agent-Strategien.

### Behobene Probleme

- Der Bot-`/market`-Befehl nutzt `get_open_markets_today()` / `compute_effective_region()` für die Handelstagsfilterung: Das Ergebnis wird als `override_region` an `run_market_review` durchgereicht; ist das Ergebnis eine leere Zeichenkette, wird die Review übersprungen und „Die betreffenden Märkte sind heute geschlossen" gepusht, konsistent mit dem Verhalten der CLI-/Scheduling-Einstiege.
- Der Fragedienst-Agent behält bei fehlendem verfügbarem LLM die echten Backend-Fehlergründe und die Fehlersemantik `done.success=false` bei, damit das Frontend fehlende Konfiguration nicht als erfolgreiche Antwort missversteht.
- Im Agent-Modus werden ohne erzeugtes gültiges Entscheidungs-Dashboard die Score-, Trend- und Aktionsempfehlungen der lokalen Trendanalyse beibehalten, und die Kauf-/Verkaufs-Fallbacks werden auf die kompatiblen Entscheidungstypen `buy`/`sell` normalisiert, damit Startseiten-Ergebnisse nicht von den Standardwerten `50 / abwarten / unbekannt` überschrieben werden.
- Der Positions-Schnappschuss fällt bei fehlendem Aktuellpreis nicht mehr stillschweigend auf die Anschaffungskosten zurück; der Tages-Schnappschuss verwendet vorrangig den historischen Schlusskurs und nur bei Fehlen den Echtzeitpreis als Fallback; Positionen ohne Preis verschmutzen nicht mehr Marktwert und unrealisierte Gewinn-/Verlust-Zusammenfassung, und die Positionsdetails geben Preisquelle, Datum, stale- und Fehlpreisstatus zurück.
- Der Analyse-Prompt bereinigt vor der Injektion von `trend_analysis` gemäß dem finalen `trend_status` / `ma_alignment` sich gegenseitig ausschließende Begründungen: Bei bärischer Struktur werden die bullischen Gründe entfernt, bei bullischer Struktur das Risiko der bärischen Struktur, und bei Ereignis-/Technik-Konflikten und anomalem Volumen (>10-fach) wird „Ereignis zuerst, Technik noch bestätigen" und die Volumen-Gewichtsabsenkung erzwungen.
- Auch bei nicht-JSON-Antworten des LLM wird der Ersatzmodellwechsel ausgelöst: Gibt das Hauptmodell erfolgreich zurück, lässt sich die Antwort aber nicht als JSON parsen, wird nicht sofort auf den reinen Text-Fallback degradiert, sondern die Ersatzmodelle aus `LITELLM_FALLBACK_MODELS` werden nacheinander versucht; erst wenn alle Modelle kein gültiges JSON liefern, wird auf den Text-Fallback degradiert.
- Die internen LiteLLM-DEBUG-Logs werden standardmäßig auf WARNING gesenkt, damit token-bezogene Logs beim Streaming `stock_analysis_debug_*.log` nicht verschmutzen; für die Untersuchung interner LiteLLM-Details kann vorübergehend `LITELLM_LOG_LEVEL=DEBUG` gesetzt werden (Fixes #1156).

### Dokumentation

- Ergänzt den LLM-Konfigurationsleitfaden und die FAQ; klargestellt die Kompatibilitätspriorität, Fallback-Pfade und die Schlussfolgerung „Alte Konfigurationen werden nicht stillschweigend migriert" des Fragedienst-Agents für `LITELLM_CONFIG` / `LLM_CHANNELS` / legacy `GEMINI_*` `OPENAI_*` `ANTHROPIC_*`.

### Tests

- Neues `tests/test_bot_market_command.py`, das die `override_region`-Durchreichung für `MARKET_REVIEW_REGION=both` + offene Märkte `{"cn","us"}` / `{"cn","hk"}` abdeckt sowie die Pfade Markt-weit geschlossen überspringen und Handelstagsprüfung deaktiviert; neues `tests/test_yfinance_hk_indices.py` deckt die Symbolzuordnung der Hongkong-Indizes und die Degradationspfade bei teilweisem/vollem Ausfall ab.
- Vervollständigt die Funktion zur Normalisierung von Aktiencodes des Lightweight-Import-Stubs von `task_queue` und stellt Sammlung und Ausführung von `tests/test_task_queue_config_sync.py` wieder her.

## [3.14.1] - 2026-04-26
- [Tests] Korrigiert die Assertion des Marktreview-Prompt-Tests für den Titel „Handelsplan für morgen" und synchronisiert die Desktop-Versionsnummer, um das Release-Gate wiederherzustellen.

## [3.14.0] - 2026-04-26

### Release-Highlights

- 📊 **Die Marktreview wird auf eine Nachbörsen-Workbench-Struktur hochgestuft** — Die A-Aktien-Review gibt fest Markttemperatur, Indexdetails, Branchen-Top-Tabelle, Nachrichtenkatalyse, Handelsplan für morgen und Risikohinweise aus und reduziert Wiederholung und Inhaltsleere reiner Text-Reviews.
- 🖥️ **Neue GitHub-Release-Update-Erinnerung auf dem Desktop** — Die Windows/macOS-Desktop-Version erkennt nach dem Start automatisch neue Versionen, kann aber auch manuell über die Einstellungsseite geprüft werden und zur Download-Seite springen.
- 🤖 **Deutlich weniger Datenladegeräusch im Pipeline-Agent** — Das K-Linien-Tool wird auf DB-first umgestellt und wärmt 240 Tage historischer Daten vor, um wiederholte HTTP-Anfragen für dieselbe Aktie zu vermeiden.
- 🐳 **Aufgeräumte Docker-Release-Kette** — Der Release-Workflow wird auf zwei Pfade, offizielle Veröffentlichung und manuelle Nachveröffentlichung, konvergiert; der offizielle Docker-Hub-Imagename ist einheitlich `zhulinsen/daily_stock_analysis`.
- 🔧 **Gestärkte LLM-Kanal- und DeepSeek-V4-Konfiguration** — Die GitHub-Actions-Plananalyse vervollständigt die Variablendurchreichung über mehrere Kanäle, und die offiziellen DeepSeek-Kanal-Presets und -Beispiele werden auf V4 synchronisiert.
- 🧩 **Konsistenzprüfung der statischen Ressourcen auf dem Desktop** — Paketierungskette und Laufzeit können Fehlzuordnungen statischer Ressourcen früher erkennen und senken die Kosten der Fehlersuche bei leeren Release-Paketen.

### Neue Funktionen

- 🏠 **Neuer Einstieg für die erneute Analyse im Historienberichtsbereich der Web-Startseite** — Unterstützt das erneute Durchführen der Analyse derselben Aktie am selben Datum auf Basis des ursprünglichen Prompts.
- 🖥️ **Neue GitHub-Release-Update-Erinnerung auf Windows/macOS-Desktop** — Erkennt nach dem Start automatisch neue Versionen und unterstützt die manuelle Prüfung über die Einstellungsseite mit Sprung zur Download-Seite.

### Verbesserungen

- 📊 **A-Aktien-Markt-Review-Bericht auf strukturiertes Post-Market-Workbench-Format umgestellt** — fester Output von Markt-Temperatur, Indexdetails, Sektor-Top-Tabelle, News-Katalysatoren und dem Handelsplan für den nächsten Tag.
- 🐳 **Docker-Release-Workflow konsolidiert** — offizielle Releases und manuelle Nachlieferungen werden klarer getrennt und der offizielle Docker-Hub-Imagename wird auf `zhulinsen/daily_stock_analysis` vereinheitlicht.
- 🤖 **Agent-Tageslinien-Tools nutzen bevorzugt lokale Caches** — neu abgerufene Tageslinien und News-Informationen werden zugleich persistiert, um wiederholte Datenquellen-Aufrufe zu reduzieren.

### Behobene Probleme

- 🤖 **Pipeline-Agent-Kerzenstrick-Tools mit DB-first-Laden** — `get_daily_history` / `analyze_trend` / `calculate_ma` / `get_volume_analysis` / `analyze_pattern` lesen bevorzugt aus der lokalen DB, wodurch 9x5=45 wiederholte HTTP-Requests pro Aktie entfallen (Fixes #1066).
- 🤖 **Pipeline-Agent wärmt vor der Ausführung bedarfsweise 240 Tage K-Linien-Historie in die DB** — normalerweise benötigen Kerzenstrick-Tool-Aufrufe keine wiederholten Netzwerkrequests.
- 🕒 **`target_date` wird eingefroren und über ContextVar an die K-Linien-Tool-Threads des Pipeline-Agents weitergereicht** — beseitigt Zeitdrift über Handelsgrenzen hinweg.
- 🪟 **Encoding-Fix für die Backend-Log-Übertragung im Windows-Desktop-Client** — beim Übertragen von stdout/stderr wird bevorzugt UTF-8 verwendet, mit Fallback auf die lokale Codepage, um fehlerhafte Anzeige chinesischer Logs zu vermeiden.
- ⚙️ **Der GitHub-Actions-Tagesanalyse-Workflow vervollständigt die Durchreichung der LLM-Kanal-Variablen** — unterstützt `LLM_CHANNELS`, mehrere Keys und gängige `LLM_<NAME>_*`, damit lokal verfügbare Multi-Modell-Konfigurationen in Cloud-Scheduled-Tasks nicht wirkungslos werden (Fixes #1063, #872).
- 📈 **Die Historienbericht-Detail-API korrigiert die Ermittlung von `change_pct`** — eine `is None`-Prüfung verhindert, dass 0.0 (unverändert) als fehlender Wert verworfen wird; der fehlerhafte `change_60d`-Fallback wird entfernt und bei fehlenden Werten auf das ursprüngliche Echtzeit-Kursfeld zurückgegriffen (Fixes #1084).
- 🔧 **DeepSeek-Offizialkanal-Presets und Beispielkonfiguration auf V4 synchronisiert** — der legacy `deepseek-chat`-Standardwert bleibt erhalten und erhält einen Deprecation-Hinweis; zugleich wird das Problem behoben, dass die Auswahl eines alten Runtimes nach der Modellermittlung das Speichern scheitern ließ (Fixes #1108, #1109).
- 🧩 **Neuer Konsistenzcheck für statische Ressourcen in der Desktop-Packaging-Pipeline** — `scripts/check_static_assets.py` prüft, ob die von `index.html` referenzierten Ressourcen im Quell-`static/` und im PyInstaller-Artefakt tatsächlich existieren; auch zur Laufzeit wird bei Abweichungen eine eindeutige Logmeldung geschrieben, um erneute weiße Bildschirme nach dem Öffnen von Release-Paketen zu vermeiden (Refs #1064 / #1065 / #1050).
- 🧩 **Backend `/assets/*` auf explizites Routing umgestellt** — bei fehlenden Ressourcen wird ein zum angefragten Dateityp passender `text/javascript` / `text/css` 404 zurückgegeben, wodurch die standardmäßige JSON-Fehlerantwort weniger in die Irre führt (Refs #1064).
- 🌙 **`kimi-k2.6` verwendet automatisch eine feste Temperatur** — bei Hauptanalyse, Markt-Review und Agent-Aufrufen wird automatisch `temperature=1.0` verwendet, um zu vermeiden, dass das Modell Requests mit Standardtemperatur ablehnt (Fixes #1102).

### Dokumentation

- 🐳 **Offizielle Docker-Image-Verwendung dokumentiert** — ergänzt Image-Pull, `docker run`-Verwendung sowie `.env` / Datenverzeichnis-Mapping; nicht mehr nur der Compose-Deployment-Pfad wird abgedeckt.
- 📨 **Feishu-Custom-Bot-Webhook-Beispiel korrigiert** — das Beispiel in `feishu_sender.py` wird auf interactive-card-JSON umgestellt und ein Tutorial zur Konfiguration des Feishu-Automations-Webhook-Triggers ergänzt.
- 📚 **Root-README-Struktur optimiert** — Einstiegspunkte wie Features auf Startseiten-Niveau, Technologie-Stack, Schnellstart, Push-Wirkung, Web, Agent, Sponsoren und News-Quellen bleiben erhalten; Feinkonfiguration, Trading-Disziplin und Fundamental-Semantik werden im vollständigen Leitfaden konsolidiert, und das Docker-Badge verweist auf die offizielle Image-Seite.
- 🌐 **Schlanke Einstiegsstruktur der englischen und traditionell-chinesischen README synchronisiert** — zugleich werden LLM-Nutzungs-API und Positionsverwaltung im vollständigen Leitfaden ergänzt.
- 🤝 **README-Pflegeregeln in AI-Kollaborations- und PR-Vorlagen angepasst** — klargestellt, dass die README nur bei Bedarf aktualisiert wird und Details vorrangig in spezifische Dokumente gehören.

### Tests

- 🧪 **LiteLLM-Stub-Verhalten der Markt-Review-Tests stabilisiert** — verhindert, dass ein lokal installiertes LiteLLM die Markt-Review-Unit-Tests bei veränderter Test-Collect-Reihenfolge beeinflusst.
- 🧪 **pytest überspringt standardmäßig Frontend-Abhängigkeitsverzeichnisse** — bei lokal vorhandenem `apps/dsa-web/node_modules` wird dieses nicht mehr rekursiv von Backend-Tests durchsucht, damit der Pre-Release-Gate nicht durch irrelevante Verzeichnisse ausgebremst wird.

## [3.13.0] - 2026-04-21

### Release-Highlights

- 🌉 **Longbridge-OpenAPI-Datenquelle angebunden** — US-/Hongkong-Kurse bevorzugen Longbridge, YFinance / AkShare greifen automatisch als Fallback ein; ohne Konfiguration bleibt das Verhalten unverändert.
- 📈 **Tushare-Vollstreckenerweiterung für Hongkong-Aktien** — Hongkong-Tageslinien werden über `hk_daily` abgerufen; die Chip-Verteilung liefert für Hongkong-Aktien `None`; die Umrechnungseinheiten folgen der Hongkong-Definition und wenden nicht mehr die A-Aktien-Regeln für Lot/Kilo-Renminbi an.
- 🔍 **Anspire Search semantische Suche angebunden** — nach Konfiguration von `ANSPIRE_*` liefert Anspire Search Echtzeitkurse und Nachrichten; ohne Konfiguration bleibt sie völlig transparent.
- 🚀 **Normale Analyse-Pipeline unterstützt LLM-Streaming** — das SSE der Homepage-Aufgaben erhält ein neues `task_progress`-Ereignis für feinere Fortschrittsmeldungen; Provider ohne Streaming-Unterstützung fallen automatisch auf Nicht-Streaming-Aufrufe zurück.
- 🤖 **Web-Kanal-Editor unterstützt bedarfsweises Abrufen verfügbarer Modelllisten** — `/v1/models` dient als vereinheitlichter Modell-Erkennungs-Einstieg; Mehrfachauswahl wird nach `LLM_{CHANNEL}_MODELS` zurückgeschrieben; bei fehlgeschlagenem Abruf bleibt die manuelle Eingabe als Fallback erhalten.
- 🛡️ **Stabilität und Budget-Guardrails des Agents umfassend gestärkt** — einheitliche `AGENT_MAX_STEPS`-Semantik, Skill-Degradation ohne Pipeline-Abbruch, SSE-Ausnahme-Weitergabe und vervollständigte warning-Logs für Skill-Ladevorgänge.
- 🛠️ **SQLite-Schreibpfad atomarisiert** — atomares Batch-Upsert + WAL + `busy_timeout` + begrenzte Schreib-Wiederholungen senken die Sperrenkonkurrenz bei parallelen Batch-Analysen deutlich.

### Neue Funktionen

- 🌉 **Longbridge OpenAPI als optionale Datenquelle für US-/Hongkong-Aktien integriert** (fixes #981) — nach Konfiguration von `LONGBRIDGE_*` werden Tageslinien und Echtzeitkurse bevorzugt über Longbridge bezogen, mit YFinance / AkShare als Fallback; ohne Konfiguration bleibt das Verhalten wie bisher. Für die Verbindungstests wird `tests/longbridge_live_smoke.py` verwendet (manuelles Skript, nimmt nicht an der pytest-Sammlung teil).
- 📈 **Tushare unterstützt Hongkong-Tageslinienabfragen** — nach Konfiguration der Tushare-Anmeldedaten werden Hongkong-Daten über die `hk_daily`-Schnittstelle abgerufen; bei fehlenden Berechtigungen wird wie im bisherigen Ablauf eine Ausnahme geworfen.
- 🔍 **Anspire Search als optionales semantisches Such-Backend integriert** — mit `ANSPIRE_*`-Konfiguration liefert Anspire Search Echtzeitkurse und Nachrichten; ohne Konfiguration bleibt das Verhalten wie bisher. Für die Verbindungstests wird `tests/test_anspire_search.py` verwendet (manuelles Skript).
- 🚀 **Normale Analyse-Pipeline unterstützt LiteLLM-Streaming und feinere Aufgabenfortschritte** — die Aktienanalyse versucht in der LLM-Phase zuerst `stream=True` und akkumuliert die Chunks serverseitig; das SSE der Homepage-Aufgaben erhält ein neues `task_progress`-Ereignis und feinere `message/progress`-Updates; der Historienbericht wird erst nach erfolgreichem Parsen des finalen JSON persistiert; Provider ohne Streaming-Unterstützung fallen automatisch auf Nicht-Streaming-Aufrufe zurück.
- 🤖 **Web-AI-Modellkonfiguration unterstützt das Abrufen verfügbarer Modelllisten pro Kanal** — der Kanal-Editor kann über `/v1/models` verfügbare Modelle abrufen und als Mehrfachauswahl nach `LLM_{CHANNEL}_MODELS` zurückschreiben; bei fehlgeschlagenem Abruf bleibt die manuelle Eingabe als Degradationspfad erhalten.

### Verbesserungen

- 🔎 **SerpAPI-Bodynachlieferung eingegrenzt** — natürliche Suchergebnisse werden nicht mehr einzeln synchron um Webseiten-Texte ergänzt; nur für sehr wenige hochrangige Ergebnisse mit unzureichender Zusammenfassung wird verzögert nachgeliefert, wobei die bereits von SerpAPI gelieferten strukturierten Zusammenfassungen bevorzugt werden, um Tail-Latenz und Verstärkung langsamer Seiten zu senken.
- 🤖 **LLM-Anbindung vereinfacht** — die benutzerorientierten Texte zur AI-Modellanbindung werden auf „Hauptmodell / Agent-Hauptmodell / Alternativmodell / Modellkanal“ vereinheitlicht; LiteLLM wird nicht mehr als für Normalnutzer zwingendes Konzept dargestellt; bestehende `LITELLM_*` / `LLM_CHANNELS`-Konfigurationsschlüssel bleiben kompatibel.
- 🧠 **IntelAgent erhält Unternehmensankündigungssuche und Hauptkapitalfluss-Tool** — es kommen die Ankündigungssuche-Dimensionen für Börse Shanghai / Börse Shenzhen / cninfo sowie das `get_capital_flow`-Tool hinzu, um das häufige Fehlen von Ankündigungs- und Kapitalflussdaten im Agent-Modus zu beheben.
- 📦 **Backend-Aktiennamenauflösung bevorzugt Wiederverwendung von `stocks.index.json`** — der statische Frontend-Index wird lazy gecacht; in reinen Backend-/fehlenden-Statikressourcen-Szenarien wird still auf `STOCK_NAME_MAP` und den bisherigen Datenquellen-Fallback zurückgefallen.
- 📊 **Einheitenanpassung des TushareFetcher für Hongkong-Aktien** — `get_chip_distribution` liefert für Hongkong-Aktien direkt `None` (Chip-Verteilung wird für Hongkong vorerst nicht unterstützt); `_normalize_data` wendet für Hongkong-Aktien (`hk_daily`) nicht mehr die A-Aktien-Skalierung Lot→Aktie bzw. Kilo-Renminbi→Renminbi an, passend zur Feld-Semantik von Tushare für Hongkong.
- ⏱️ **Fehler bei überschrittenen Agent-Schritten erhalten einen `AGENT_MAX_STEPS`-Anpassungshinweis** — hilft Nutzern, Schrittlimit-Probleme selbst zu beheben.
- ⚙️ **GitHub-Actions-Analyseaufgaben unterstützen `vars`-Konfiguration für das Timeout** — die Aufgaben-Timeoutwerte in `daily_analysis.yml` werden aus repository variables gelesen, sodass das Laufzeit-Timeout ohne Codeänderungen angepasst werden kann (fixes #1014).

### Behobene Probleme

- 📣 **Markt-Review-Pipeline an `REPORT_LANGUAGE` angebunden** — bei `REPORT_LANGUAGE=en` werden Prompt, Kapitelüberschriften, Template-Fallback-Texte und Benachrichtigungs-Titel der A-Aktien-/kombinierten Reviews einheitlich auf Englisch ausgegeben, um gemischte Ausgaben mit englischem Text und chinesischen Überschriften zu vermeiden.
- 📈 **Kompatibles Eröffnungskurs-Mapping des EfinanceFetcher für Indizes** (fixes #1043) — das Eröffnungskurs-Mapping von `get_main_indices()` wird auf „Offen (heute) → Eröffnung → open“ umgestellt, wodurch behoben wird, dass der Index-Eröffnungskurs in manchen efinance-Versionen als fehlender Wert gelesen wurde.
- 🤖 **`AGENT_MAX_STEPS`-Semantik vereinheitlicht** (fixes #1026) — im Orchestrator-Mehr-Agenten-Modus gilt es nun eindeutig als „Schrittlimit pro Unter-Agent, nicht als hartes Überschreiben“; Agenten mit hohen Standardwerten wie TechnicalAgent werden gedeckelt, Agenten mit niedrigen Standardwerten behalten ihre Werte; eine bewusste Erhöhung durch den Nutzer (>10) überschreibt einheitlich alle Unter-Agenten. Behoben wird, dass bei einer Einstellung von 12 TechnicalAgent dennoch mit den standardmäßigen 6 Schritten lief und „Agent exceeded max steps“ meldete.
- 🛡️ **Fehlschläge des Specialist-(Skill-)Agents auf elegante Degradation umgestellt** — ein fehlgeschlagener Skill-Agent unterbricht die Analyse-Pipeline nicht mehr und folgt der gleichen Degradationsstrategie wie intel/risk.
- 🔧 **MiniMax-M2.7-Verbindungstest-Fix** — behebt, dass der LLM-Kanal-Verbindungstest unter MiniMax-M2.7 „Empty response“ zurückgab; das `max_tokens`-Limit wird von 8 auf 256 angehoben, um Denkprozesse aufzunehmen, und eine Parse-Logik für das `content_blocks`-Format wird ergänzt.
- 📊 **Bereichsbegrenzung von `sentiment_score` entfernt** (fixes #942) — die `ge=0/le=100`-Begrenzung für `sentiment_score` in den Response-Schemas `HistoryItem` und `ReportSummary` wird entfernt, sodass in der Historie gespeicherte Werte außerhalb des Bereichs keine Pydantic-ValidationError mehr auslösen.
- 🖥️ **WebUI warnt explizit bei fehlenden Frontend-Ressourcen** — `webui_frontend.py` gibt eine warning aus, wenn `static/index.html` existiert, aber `static/assets/` fehlt, damit fehlende CSS/JS-Ressourcen, die die Seite anormal aufblähen, nicht mehr unauffindbar bleiben (fixes #944).
- 🔗 **Degradationsinitialisierung optionaler Dienste der Analyse-Pipeline** — bei Initialisierungsfehlern von Suchdienst oder Social-Sentiment-Dienst der `StockAnalysisPipeline` wird eine warning protokolliert und der Betrieb im deaktivierten Zustand fortgesetzt, damit wackelnde externe Abhängigkeiten die Hauptanalyse nicht blockieren.
- 🖥️ **Desktop-Versionsanzeige liest einheitlich `package.json`** — einheitliches Lesen von `apps/dsa-desktop/package.json`, Entfernen des hartcodierten `0.1.0` im preload und Anzeige der echten Desktop-Version auf der Einstellungsseite; behebt die fehlerhafte Versionsanzeige (fixes #1048).
- 🐋 **Fix für fehlgeschlagenes Abrufen von Hongkong-Aktiennamen** (fixes #940) — behebt, dass bei fehlenden Feldern der Hauptdatenquelle nicht korrekt auf Alternativfelder zurückgegriffen wurde, um den Hongkong-Aktiennamen zu ermitteln.
- 🔄 **`CancelledError` bei getrennter SSE-Aufgabenverbindung korrekt re-raised** (fixes #967) — behebt, dass Ausnahmen beim Abbruch des SSE-Streams still verschluckt wurden und Störungen dadurch ohne protokollierte Spur blieben.
- 🔄 **Hintergrundaufgaben-Ausnahmen in der SSE-Bereinigungsphase des Agents korrekt gemeldet** (fixes #969) — Ausnahmen des Hintergrund-Executors am Stream-Ende werden jetzt korrekt protokolliert und gemeldet, damit Fehler nicht unbemerkt bleiben.
- 🔇 **Logs für Skill-Ladeausnahmen ergänzt** (fixes #970) — in den stillen except-Blöcken von `ask.py`, `skills/aggregator.py`, `skills/router.py` werden Logs ergänzt, damit bei leerer Skill-Liste eine protokollierte Spur existiert.
- 🛠️ **SQLite-Schreibpfad atomarisiert** (fixes #878) — `stock_daily(code,date)` verwendet ein atomares Batch-Upsert; dateibasierte SQLite-Verbindungen aktivieren standardmäßig WAL + `busy_timeout` + begrenzte Schreib-Wiederholungen; die „Anzahl neuer Einträge“ wird anhand des tatsächlich eingefügten Fensters berechnet.
- 💰 **Budget-Guardrail-Semantik für Multi-Agent / Single-Agent vereinheitlicht** — sinkt das verbleibende Budget unter den Mindestschwellwert, wird aktiv übersprungen und degradiert; ist für eine abgeschlossene Phase ein Degradationsbericht baubar, wird `success=True` mit nicht leerem Inhalt zurückgegeben, sonst `success=False`.
- ⚙️ **GitHub-Actions-`daily_analysis.yml` ergänzt `REPORT_LANGUAGE`-Injektion** (fixes #1013) — behebt, dass ein in Secrets/Variables konfiguriertes `REPORT_LANGUAGE` nicht wirkte.
- 📊 **Aufgabenstatus-API ergänzt Echtzeit-Kursfelder** (fixes #983) — `GET /api/v1/analysis/status/{task_id}` ergänzt beim Zurückfüllen abgeschlossener Aufgaben aus der Datenbank `current_price` / `change_pct`, wodurch auf der Startseite neben dem Aktiennamen im Bericht wieder der Echtzeitkurs angezeigt wird.
- 📅 **An Nicht-Handelstagen werden die Daten des letzten Handelstags zurückgegeben** (fixes #1009) — behebt, dass an Nicht-Handelstagen (Wochenenden/Feiertagen) Chip-Verteilung und Sektor-Ranglisten Daten des vorletzten Handelstags lieferten; jetzt werden korrekt die Daten des letzten Handelstags geliefert.
- 🔍 **Chinesisch-Priorität der A-Aktien-Nachrichtensuche wiederhergestellt** — `search_stock_news()` versucht nachfolgende Engines, wenn der erste Provider überwiegend englische Nachrichten liefert, und sortiert chinesische Nachrichten derselben Ergebnismenge nach vorn; nicht-US-Aktien-Anfragen übernehmen nicht mehr standardmäßig die `en/US`-Regionssprache von Brave.
- 📨 **Feishu-Gruppenbot-Benachrichtigungen unterstützen Signaturprüfung** — Feishu-Benachrichtigungen unterstützen jetzt `FEISHU_WEBHOOK_SECRET` / `FEISHU_WEBHOOK_KEYWORD`; Web-Einstellungen und Dokumentation trennen den Webhook-Push-Modus klar vom `FEISHU_APP_ID` / `FEISHU_APP_SECRET`-App-Modus, um Fehlkonfigurationen zu reduzieren.
- ⚡ **LLM-Adapterlage erkennt `RateLimitError` und `ContextWindowExceeded`** — Rate-Limit- und Kontextfenster-Überschreitungsfehler werden erkannt und behandelt, was die Robustheit der Analyse-Pipeline unter hoher Last oder bei langen Texten erhöht (fixes #1002).

### Tests

- 🧪 **TushareFetcher-Unit-Tests für Hongkong-Aktien** — neue Unit-Tests für `get_chip_distribution` (Chip-Verteilungsabruf) und die Hongkong-/A-Aktien-/ETF-Einheitenbehandlung von `_normalize_data`, die die Sonderpfade für Hongkong abdecken.

### Dokumentation

- 📘 **DEPLOY.md ergänzt Schritte zum Beheben anormal vergrößerter UI-Elemente** — neu ist eine Anleitung zum Neuerstellen des Docker-Images oder zum manuellen Ausführen von `npm run build`; `deploy-webui-cloud.md` wird synchron aktualisiert.
- 📨 **Feishu-Webhook-Konfigurationsanleitung vervollständigt** — hervorgehoben wird, dass `FEISHU_WEBHOOK_URL` für Gruppenbenachrichtigungen Pflicht ist, die Signaturprüfung auf beiden Seiten gleichzeitig aktiviert bzw. deaktiviert sein muss und `FEISHU_APP_SECRET` nur im App-/Stream-Bot-Modus verwendet wird; `.env.example` erhält Inline-Kommentare; die englische Anleitung wird synchronisiert.
- 🤝 **FAQ ergänzt Eintrag zur Ollama-Verbindungsfehlerbehebung (Q12c)** — deckt 5 Prüfpunkte ab: Dienst nicht gestartet, fehlerhafte URL-Konfiguration, fehlendes Modellpräfix, Modell nicht heruntergeladen, entfernte Firewall (fixes #854).
- 🌉 **README ergänzt Nutzungsanleitung für die Longbridge-Datenquelle** — die chinesische/englische/traditionell-chinesische README klärt die Grenzen „bevorzugt / Fallback / ohne Konfiguration nicht aufgerufen“ von Longbridge; relative Pfadlinks in `docs/` werden repariert; die Konfiguration `LONGBRIDGE_PRINT_QUOTE_PACKAGES` wird mit Code und `.env.example` abgeglichen.
- 🐋 **Versionshinweis für Docker-Installationen** — ein minimales Dokument wird ergänzt, das klärt, dass in Docker-Installationsszenarien die Version anhand von Git-Tag / Image-Tag bestimmt werden sollte (fixes #1091).

## [3.12.0] - 2026-04-01

### Release-Highlights

- 📊 **Neue „Nächster-Tag-Verifikation“-Ansicht auf der Backtest-Seite** — zeigt für Aktien und Datumsbereiche die AI-Prognose vs. die tatsächliche Kursbewegung am nächsten Tag, nutzt historische Analysen und 1-Tage-Backtest-Ergebnisse zur schnellen Verifikation der Analysegenauigkeit.
- 🔧 **LLM-Anbindung vereinfacht** — die nutzerseitigen Texte werden auf „Hauptmodell / Alternativmodell / Modellkanal“ vereinheitlicht; LiteLLM wird nicht mehr als für Normalnutzer zwingendes Konzept dargestellt; bestehende Konfigurationsschlüssel bleiben kompatibel.
- 🐳 **Laufzeit-Stabilität von Docker / WebUI gestärkt** — behoben werden Probleme wie nicht wirksame Konfiguration nach Speichern der Systemeinstellungen, fehlende Logs in der frühen Startphase und Wiederverwendung vorgebauter statischer Ressourcen, um den Betriebsaufwand containerisierter Deployments zu senken.
- 🔒 **Sicherheit und Parallelitätsstabilität zugleich gestärkt** — der Discord-Eingangs-Webhook erhält die Ed25519-Signaturprüfung; behoben werden u. a. ungelockter gemeinsamer Zustand bei paralleler Ausführung und die gleichzeitige Wiederverwendung von Benachrichtigungsinstanzen im Einzelaktien-Push-Modus.
- 🖥️ **Feinschliff für Desktop-Client und geplante Aufgaben** — der Windows-Installer unterstützt ein frei wählbares Installationsverzeichnis, der eingebaute Scheduler erkennt laufende `SCHEDULE_TIME`-Änderungen, und die Wiederaufnahme unterbrochener Downloads wird anhand der Marktzeitzone beurteilt.

### Neue Funktionen

- 📊 **Neue „Nächster-Tag-Verifikation / 1-Tage-Fenster“-Ansicht auf der Backtest-Seite** — für Aktiencodes und Analyse-Datumsbereiche werden AI-Prognose, tatsächliche Kursbewegung am nächsten Tag und die Genauigkeit im gefilterten Zeitraum angezeigt; realisiert durch Wiederverwendung historischer Analysen und 1-Tage-Backtest-Ergebnisse.
- 🏷️ **Neue Versionsinformations-Karte auf der Web-Einstellungsseite** — `apps/dsa-web` injiziert jetzt zur Build-Zeit die Frontend-Paketversion und die Build-Zeit; die Systemeinstellungsseite erhält einen schreibgeschützten Bereich „Versionsinformation“ mit `WebUI-Version / Build-Kennung / Build-Zeit`; steht in `package.json` weiterhin die Platzhalterversion `0.0.0`, wird automatisch auf die Build-Kennung zurückgefallen, sodass nach einem Docker-Rebuild schnell bestätigt werden kann, ob die aktuellen statischen Ressourcen wirksam sind.
- 🪟 **Windows-Desktop-Installer unterstützt frei wählbares Installationsverzeichnis** — der Installer erlaubt im Installationsassistenten ein benutzerdefiniertes Verzeichnis; nach Installation auf einem nicht standardmäßigen Laufwerk bleibt die bestehende Paketverzeichnislogik erhalten und `.env`, `data/stock_analysis.db` sowie `logs/desktop.log` werden weiterhin neben dem Installationsverzeichnis gelesen und geschrieben; zusätzlich bleibt die portable `win-unpacked`-Verteilung erhalten. Der Installer unterstützt nur die Installation für den aktuellen Benutzer, die Admin-Erhöhung ist deaktiviert (`allowElevation: false`), und über NSIS `.onVerifyInstDir` wird die Auswahl systemgeschützter Verzeichnisse verhindert.

### Verbesserungen

- 🔎 **SerpAPI-Bodynachlieferung eingegrenzt** — natürliche Suchergebnisse werden nicht mehr einzeln synchron um Webseiten-Texte ergänzt; nur für sehr wenige hochrangige Ergebnisse mit klar unzureichender Zusammenfassung wird innerhalb eines kürzeren Timeout-Budgets verzögert nachgeliefert, wobei die bereits von SerpAPI gelieferten strukturierten Zusammenfassungen bevorzugt werden, um Tail-Latenz und Verstärkung langsamer Seiten zu senken.
- 🤖 **LLM-Anbindung vereinfacht** — die benutzerorientierten Texte zur AI-Modellanbindung sind auf „Hauptmodell / Agent-Hauptmodell / Alternativmodell / Modellkanal / Erweiterte Modell-Routing-Konfiguration“ vereinheitlicht; Web-Einstellungsseite, Konfigurationsmetadaten, Validierungshinweise sowie chinesische und englische Dokumentation behandeln LiteLLM nicht mehr als für Normalnutzer zwingendes Konzept; bestehende `LITELLM_*` / `LLM_CHANNELS`-Konfigurationsschlüssel bleiben kompatibel.

### Behobene Probleme

- 🚀 **Bei frühen Startfehlern wird die echte Ursache offengelegt** — `python main.py` legt die echte Ursache jetzt über stderr offen; die Bootstrap-Phase schreibt keine Dateilogs mehr in das hartcodierte `logs/`-Verzeichnis, die Dateilogs werden erst erstellt, wenn `config.log_dir` verfügbar ist, sodass ein gesunder Start keine Logdateien an unerwarteten Pfaden hinterlässt.
- 🐳 **Docker-WebUI-Laufzeit bevorzugt Wiederverwendung vorgebauter statischer Ressourcen** — `prepare_webui_frontend_assets()` prüft jetzt zuerst, ob das im Image vorhandene `static/index.html` direkt wiederverwendet werden kann; enthält die Containerlaufzeit kein `apps/dsa-web`-Quellverzeichnis und ist `npm` nicht installiert, wird auch nicht mehr fälschlich „Frontend-Projekt nicht gefunden, automatischer Build nicht möglich“ gemeldet, wodurch das Öffnen der WebUI nach Docker-Deployment wieder funktioniert.
- 🐳 **Docker-WebUI-Konfiguration wirkt nach dem Speichern der Systemeinstellungen** — im Docker-Szenario liest `Config` nach dem Speichern von `STOCK_LIST`, `SCHEDULE_ENABLED`, `SCHEDULE_TIME`, `SCHEDULE_RUN_IMMEDIATELY` und `RUN_IMMEDIATELY` über die WebUI zuerst die neuen Werte aus der persistierten `.env`, sodass diese nicht von beim Containerstart injizierten alten Umgebungsvariablen überschrieben werden.
- 📈 **Markt-Review-`max_tokens` erhöht** — die Markt-Review-Generierung hebt LLM-`max_tokens` von `2048` auf `8192`, wodurch die Wahrscheinlichkeit sinkt, dass lange Review-Ausgaben durch vorzeitiges Abschneiden bei `MAX_TOKENS` unvollständig bleiben.
- ⏰ **Eingebauter Scheduler erkennt `SCHEDULE_TIME`-Änderungen zur Laufzeit** — der Scheduler erkennt jetzt während des Betriebs nach dem Speichern in der WebUI geänderte `SCHEDULE_TIME`-Werte und bindet den daily job beim nächsten Prüfzyklus neu.
- 🪟 **Windows-Release-Kanal-Editor erhält das MiniMax-Modellpräfix** — bei `minimax/<Modellname>` im Kanalmodus behalten sowohl die Backend-Normalisierung als auch die Laufzeit-Modellliste der Web-Einstellungsseite den Wert unverändert bei, statt ihn fälschlich in `openai/minimax/<Modellname>` umzuschreiben.
- 🤖 **Discord-Eingangs-Webhook erhält die Ed25519-Signaturprüfung** — `DiscordPlatform` validiert die Discord-Interaction-Signatur jetzt anhand von `X-Signature-Ed25519`, `X-Signature-Timestamp` und dem rohen Request-Body; bei fehlendem Signatur-Header, ungültigem Public-Key-Format oder nicht übereinstimmender Signatur wird die Anfrage direkt abgelehnt; zusätzlich wird der Timestamp in einem ±5-Minuten-Fenster geprüft, um Replay-Angriffe abzuwehren.
- ⚙️ **`STOCK_GROUP_N` / `EMAIL_GROUP_N`-Konfigurationsverhältnis klargestellt** — das Verhältnis zu `STOCK_LIST` wird verdeutlicht, und die Konfigurationsvalidierung gibt für E-Mail-Gruppen, die `STOCK_LIST` übersteigen, eine warning aus.
- 🗓️ **Wiederaufnahme unterbrochener Downloads nutzt Marktzeitzonen und Handelskalender** (fixes #880) — die Existenzprüfung von Aktiendaten verwendet nicht mehr direkt den Server-Kalendertag, sondern ermittelt den „zuletzt wiederverwendbaren Handelstag“ anhand der jeweiligen Marktzeitzone für A-Aktien / Hongkong-Aktien / US-Aktien.
- 📨 **Einzelaktien-Push-Modus nutzt keine gemeinsame Benachrichtigungsinstanz mehr parallel** — `StockAnalysisPipeline.run()` behält die parallele Einzelaktienanalyse bei, sendet die Sofortbenachrichtigungen unter `SINGLE_STOCK_NOTIFY=true` aber nun seriell auf der Ergebnisse-Erfassungsseite.
- 🔇 **Echtzeitkurs-Degradationshinweis auf eine einzelne Warnung eingegrenzt** — der Analyse-Hauptablauf löst beim Abrufen des Aktiennamens keine vorzeitige Echtzeitkurs-Abfrage mehr aus; nur wenn alle Datenquellen nicht verfügbar sind, wird darauf hingewiesen, dass auf historische Schlusskurse degradiert wird.
- 🔍 **Chinesisch-Priorität der A-Aktien-Nachrichtensuche wiederhergestellt** — `search_stock_news()` versucht jetzt nachfolgende Engines, wenn der erste Provider überwiegend englische Nachrichten liefert, und sortiert chinesische Nachrichten derselben Ergebnismenge nach vorn.
- 🔒 **Einheitliches Locking für gemeinsamen Zustand bei paralleler Ausführung ergänzt** — behebt das fehlende einheitliche Locking des gemeinsamen Zustands bei paralleler Ausführung, um Datenwettläufe in Multithread-Szenarien zu vermeiden.

### Tests

- 🧪 **Regressions-Tests für die Versionsinformation der Einstellungsseite ergänzt** — neue Assertions zur Versionsinformations-Darstellung der Web-Einstellungsseite; abgedeckt wird auch die Logik, bei Platzhalterversion `0.0.0` automatisch auf die Build-Kennung zurückzufallen.
- 🧪 **UI-Governance und Regressionsabdeckung kritischer Pfade gestärkt** — Komponententests für `SidebarNav`, `ChatPage`, `BacktestPage` u. a. werden ergänzt, und ein UI-Governance-Guard verhindert dauerhaft, dass interaktive Elemente wieder native `title`-Attribute oder alte `input-terminal`-Styles zurückerhalten. Smoke-/Markdown-Drawer-Verifikationen werden synchron aktualisiert und decken die kritischen Hauptpfade nach dem Theme-Upgrade ab.

## [3.11.0] - 2026-03-27

### Release-Highlights

- 🎨 **Web-Workbench schließt eine Runde UI-Vereinheitlichung und Dual-Theme-Upgrade ab** — Startseite, Aktienfrage, Backtest, Positionen und Einstellungsseite werden weiter auf einheitliche Design-Tokens, Eingabeoberflächen und Zustandsdarstellungen konsolidiert; ein vollständiges helles Theme ist neu, mit Ein-Klick-Umschaltung zwischen Hell/Dunkel und persistierter Speicherung.
- 🤖 **Bot-/Agent-Fähigkeiten wieder in den Hauptzweig übernommen** — Befehle wie `/history`, `/strategies` und `/research` werden wiederhergestellt; `/ask` unterstützt weiterhin Mehr-Aktien-Vergleich und Portfoliosicht; Deep Research, Ereignisüberwachung und die schedule-Polling-Kette sind wieder an die Hauptfunktionen angebunden.
- 🔒 **Sicherheit und Laufzeitstabilität zugleich gestärkt** — das Rate-Limit-Umgehungsrisiko über `X-Forwarded-For` wird behoben, der offizielle PyPI-Installationspfad von LiteLLM wird wiederhergestellt, die Tushare-Initialisierung hängt nicht mehr vom lokalen SDK ab, was die Schwachstellen bei Docker, Desktop-Packaging und Umgebungs-Neuaufbau reduziert.
- 🖥️ **Alltägliche Bedienungsdetails weiter verfeinert** — behoben werden u. a. das Einreichen der Hongkong-Autovervollständigung auf der Startseite, das Theme-Flackern beim Erstaufruf der Login-Seite, überlappende lange Aktiennamen in der Historie sowie abgebrochene Benachrichtigungen bei fehlgeschlagenem Telegram-Markdown-Parsing.

### Neue Funktionen

- 🎨 **Neues vollständiges helles Theme und Dual-Theme-Umschaltung veröffentlicht** — die Web-Workbench erhält ein vollständiges helles Theme und unterstützt das Ein-Klick-Umschalten zwischen Hell/Dunkel in der Seitenleiste; die Theme-Auswahl wird persistent gespeichert und bleibt nach dem Neuladen der Seite erhalten. Dieses Upgrade ist keine lokale Farbanpassung, sondern eine vollständige Neuzeichnung des light themes für Kartenhierarchie, Kantenkontrast, Eingabeoberflächen, Statushinweise und Seitenhintergründe.
- 🤖 **Im Hauptzweig fehlende Agent-/Bot-Fähigkeiten wieder ergänzt** — `#648` / `#649` sind wieder in `main`: Der Bot stellt `/history`, `/strategies`, `/research` wieder her, `/ask` behält Mehr-Aktien-Vergleich und Portfoliosicht; die Konfigurationen von Deep Research und Event Monitor sind auf der Web-Einstellungsseite wieder sichtbar und editierbar, und der schedule-Modus ist wieder an die Ereigniswarnungs-Polling angebunden.

### Verbesserungen

- 🖥️ **Kernseiten auf eine gemeinsame Workbench-Visualsprache vereinheitlicht** — `Home / Chat / Backtest / Portfolio / Settings` werden weiter auf gemeinsame Design-Tokens, das `input-surface`-Eingabesystem, Leer-/Fehlerzustandsdarstellungen und die Drawer-Masken-Semantik konsolidiert, wodurch visuelle Brüche zwischen Seiten und lokale private Style-Abweichungen reduziert werden.
- 💬 **Barrierefreiheit und Feedback der Aktienfrage-Interaktion gestärkt** — die Aktienfrageseite erhält verstärkt Sitzungsexport, Benachrichtigungsversand, Nachrichtenkopieren, Verlaufslöschung und Kontexthinweise für Rückfragen; AI-Antwortaktionen sind nicht mehr übermäßig vom Hover abhängig, sodass wichtige Schaltflächen auch auf Touch-Geräten und kleinen Bildschirmen direkt erreichbar sind.
- 📊 **Oberflächen- und Zustandsdarstellungen der Backtest- und Positionsseite weiter standardisiert** — Filtersteuerelemente, Boolesche Zustände, Ergebnistabellen und Zusammenfassungskarten der Backtest-Seite werden auf gemeinsame Eingabe-/Zustands-Primitive vereinheitlicht; Import-Feedback, Wechselkurs-Refresh-Hinweise, Leerzustände und Warnungen der Positionsseite werden weiter in gemeinsame Komponenten konsolidiert, wodurch seitenbezogene Doppelimplementierungen reduziert werden.
- 🧭 **Abgestimmte Optimierung von Navigation und Seitenhülle** — Theme-Umschaltung in der Seitenleiste, Abschluss-Badge der Aktienfrage, mobile Drawer-Maske und der Scroll-Vertrag des Hauptinhalts werden weiter vereinheitlicht, wodurch der Seitenwechsel von Startseite, Aktienfrage und Backtest auf Desktop und Mobil stabiler wird.

### Tests

- 🧪 **UI-Governance und Regressionsabdeckung kritischer Pfade gestärkt** — Komponententests für `SidebarNav`, `ChatPage`, `BacktestPage` u. a. werden ergänzt, und ein UI-Governance-Guard verhindert dauerhaft, dass interaktive Elemente wieder native `title`-Attribute oder alte `input-terminal`-Styles zurückerhalten. Smoke-/Markdown-Drawer-Verifikationen werden synchron aktualisiert und decken die kritischen Hauptpfade nach dem Theme-Upgrade ab.

### Behobene Probleme

- 🌗 **Web-Standardtheme beim ersten Aufruf auf Dunkel voreingestellt** — `apps/dsa-web/index.html` liest jetzt vor dem React-Mount die lokal gespeicherte Theme-Präferenz; gibt es keinen gespeicherten Wert, wird dem `<html>` sofort `dark` vorgegeben und `color-scheme` synchron gesetzt, damit Start- und Login-Seite beim ersten Aufruf nicht kurz ein helles Theme aufblitzen lassen.
- 🔐 **Eigene Theme-Schicht für die Login-Seite konsolidiert** — Eingabefelder, Labels, Umschaltknopf und Schaltflächentexte der Login-Seite verwenden jetzt eigene `--login-*`-Visual-Tokens und erben nicht mehr die globale Hell-/Dunkel-Textfarbe; selbst wenn der Browser ein helles Theme gecacht hat, behält die Login-Seite die stabile dunkle Optik und die türkisfarbene Passworteingabe, sodass Passwortpunkte und Texte nicht schwarz werden.
- 🖥️ **Eingabe von Hongkong-Aktiencodes auf der Startseite repariert** — das Analyse-Eingabefeld der Web-Startseite akzeptiert jetzt korrekt Hongkong-Aktiencodes und aus der Autovervollständigung gewählte Hongkong-Einträge; die Erkennung von Formaten wie `00700.HK` / `HK00700` wird ergänzt, damit beim Einreichen nicht fälschlich „Bitte einen gültigen Aktiencode oder Aktiennamen eingeben“ gemeldet wird.

- 🔒 **Fix für den `X-Forwarded-For`-Wert bei der Auth-Rate-Limitierung (CWE-345)** (#841 / #842) — `get_client_ip()` liest nun den rechtesten statt des linkesten Werts aus `X-Forwarded-For`, um zu verhindern, dass Angreifer durch gefälschte Header die Rate-Limit-Eimer rotieren und den Brute-Force-Schutz umgehen; betrifft nur Deployment-Szenarien mit `TRUST_X_FORWARDED_FOR=true` und einstufigem vertrauenswürdigem Reverse-Proxy; in Mehrstufen-Proxy-Umgebungen ist die Konfiguration gemäß der Deployment-Dokumentation zu bewerten.
- 📦 **Offizieller LiteLLM-PyPI-Installationspfad wiederhergestellt und sicheres Obergrenzen-Locking ergänzt** — `requirements.txt` verwendet wieder den offiziellen PyPI-Installationspfad von `pip install litellm` und erhält zusätzlich zur beibehaltenen Mindestanforderung `>=1.80.10` eine Sicherheits-Obergrenze `<1.82.7`, um ein versehentliches Installieren der entfernten Risiko-Versionen `1.82.7` / `1.82.8` zu vermeiden; auch das Windows-Desktop-Packingskript fällt synchron auf die standardmäßige `pip install -r requirements.txt`-Kette zurück, was die Wartungskosten spezieller Download-Branches senkt.
- 📨 **Telegram fällt bei fehlgeschlagenem Markdown-Parsing auf reinen Text zurück** (fixes #850) — `src/notification_sender/telegram_sender.py` entfernt bei `HTTP 400` von Telegram mit `can't parse entities` / Markdown-Parsefehler automatisch `parse_mode` und wiederholt den Versand als reinen Text, sodass Inhalte wie `*ST` nicht mehr die gesamte Benachrichtigung scheitern lassen.
- 🔢 **Echtzeitkurse A-Aktien mit gleichem Code behalten Börsenhinweis** (fixes #852) — `DataFetcherManager` und `TushareFetcher` behalten jetzt explizite Shanghai-/Shenzhen-Hinweise wie `SZ000001` / `000001.SZ`; der Degradationszweig der alten Tushare-Echtzeitkurse verwechselt Shenzhen-`000001` nicht mehr mit dem Shanghaier `sh000001`-Index.
- 🎯 **Multi-Agent-Zweiter-Kaufpunkt kopiert den Ideal-Kaufpunkt nicht mehr blind** (fixes #851) — fehlt in Multi-Agent-Ergebnissen ein eigenständiger `secondary_buy`, zeigt das Dashboard jetzt vorrangig `N/A` statt den Fallback-Wert hart auf exakt `ideal_buy` zu kopieren, wodurch irreführende Doppel-Kaufpunkte reduziert werden.
- 🧩 **Tushare-Initialisierung hängt nicht mehr zwingend vom lokalen SDK-Paket ab** — `TushareFetcher` greift jetzt direkt über den eingebauten HTTP-Client auf Tushare Pro zu und muss zur Initialisierung nicht mehr erst `import tushare` ausführen; behoben wird, dass nach Docker, Desktop-Packaging oder Umgebungs-Neuaufbau ohne `tushare`-Paket vorzeitig `No module named 'tushare'` gemeldet wurde; dazu kommt ein entsprechender Regressionstest.
- ⚙️ **`daily_analysis`-Workflow ergänzt `DEEPSEEK_API_KEY`-Mapping** — der GitHub-Actions-Tagesanalyse-Workflow reicht `DEEPSEEK_API_KEY` jetzt korrekt durch, sodass ein in der Cloud konfigurierter Schlüssel zur Laufzeit nicht mehr ohne die entsprechende Umgebungsvariable dasteht.
- 🖥️ **Abschneiden und Hover-Anzeige überlanger Aktiennamen in der Verlaufsliste** (fixes #815) — zu lange Aktiennamen in der Verlaufsliste werden jetzt automatisch nach Zeichentyp abgeschnitten (Englisch 15 / Chinesisch 8 / Gemischt 10 Zeichen); standardmäßig wird das abgeschnittene Ergebnis angezeigt, beim Hover der vollständige Name; gelöst wird die Überlappung von Aktiennamen und Statuslabel rechts bei 1920x1080-Auflösung. Dazu kommt die neue Hilfsfunktion `stockName.ts` samt Tests.

### Dokumentation

- 🧾 **README-Spenden-Einstieg auf Xiaohongshu-QR-Code aktualisiert** — der Sponsoring-Einstieg in README sowie chinesisch- und englischsprachigen Anleitungen wird auf den Xiaohongshu-QR-Code umgestellt, um die Darstellung einheitlich zu halten.

## [3.10.1] - 2026-03-24

### Neue Funktionen

- 🔔 **Schalter für Push-Benachrichtigungen bei Web-Analysen** (#808) — neben dem Analyseknopf der Startseite gibt es ein neues Kontrollkästchen „Push-Benachrichtigung“, standardmäßig aktiviert; wird es abgewählt, sendet diese Analyse keine Pushes wie Telegram/WeCom. Die API `POST /api/v1/analysis/analyze` erhält ein `notify`-Feld (`bool`, Standard `true`); ohne Angabe bleibt das Verhalten wie zuvor; Bot und geplante Aufgaben sind nicht betroffen.

### Verbesserungen

- 🖥️ **Abgestimmte Optimierung von Layout und Hülle der Seiten Aktienfrage / Backtest** — die Container von Chat / Backtest, gemeinsamer UI-Zustand und der der Frage-Antwort-Interaktion folgende Pfad werden vereinheitlicht; einige hartcodierte Höhenbegrenzungen werden entfernt, sodass Füllung und Scrollverhalten im Navigationsrahmen zusammenhängender sind.
- 🎨 **Globale Optik und gemeinsame Komponenten weiter konsolidiert** — das Light theme erhält ein dynamisches HSL-Schatten-System; Aktivzustand der Seitenleiste, Kontrast von Alarmkomponenten und Chat-Bubble-Styles werden vereinheitlicht, und verstreute Inline-Styles werden in semantische CSS-Variablen überführt, was Konsistenz und Wartbarkeit verbessert.

### Behobene Probleme

- 🖼️ **Dateiauswahl des intelligenten Imports in den Systemeinstellungen wiederhergestellt** — behoben wird, dass die beiden Schaltflächen „Bild auswählen / Datei auswählen“ im Modul „Systemeinstellungen > Grundeinstellungen > Intelligenter Import“ auf Klicks nicht reagierten.
- 🖥️ **Mobiles Scrollen und Interaktions-Ebenen repariert** — der z-index-Konflikt wird gelöst, bei dem das Theme-Umschaltmenü auf Mobilgeräten vom Hauptinhalt verdeckt wurde; zudem wird das normale vertikale Scrollen bei langen Berichten auf der Startseite wiederhergestellt, ohne das bisherige Scrollverhalten anderer Seiten zu beeinträchtigen.
- 🧾 **Bereinigung beim Kopieren von Markdown als reinen Text verbessert** — der Export-Algorithmus für reinen Text wird verbessert, sodass beim Kopieren von Analyseberichten Markdown-Spuren wie Tabellentrennzeichen zuverlässiger entfernt werden, was die Reinheit geteilter und archivierter Inhalte erhöht.
- 🧠 **Trading-Philosophy-Injection deckt legacy + gesamte Agent-Kette ab** (#810) — `GeminiAnalyzer`, Single-Agent-Modus und skill-aware Prompt teilen jetzt denselben Strategie-Injektionszustand; nur beim impliziten Rückfall auf die eingebaute Standard-Strategie `bull_trend` bleibt der alte Trend-Prompt erhalten; explizite Strategiewahl oder ein benutzerdefinierter Standard-Skill bekommt keine heimlich aufgesetzte `MA5>MA10>MA20`-Long-Baseline mehr.
- 🛠️ **Backend-CI-Abhängigkeitsinstallation stabilisiert** (#835) — die backend-gate-Phase wird aufgeteilt, die Abhängigkeitsinstallation erhält Wiederholungsversuche, und die für CI verwendete `litellm`-Installationsquelle wird auf die stabilere GitHub-Quelle umgestellt, wodurch sporadische backend-gate-Fehler durch Abhängigkeitsauflösungs-Schwankungen reduziert werden.
- 🪟 **Windows-Desktop-Release-Build stellt die LiteLLM-Installationskompatibilität wieder her** — `scripts/build-backend.ps1` filtert zuerst das LiteLLM-GitHub-Quellpaket aus `requirements.txt`, lädt dann das Zipball des entsprechenden Tags herunter, entfernt vor der Installation das optionale `enterprise/`-Verzeichnis upstream und umgeht damit Fehler, die auf Windows-Runner entstehen, wenn Poetry beim Wheehlbau ein Verzeichnis fälschlich als Datei packt; zusätzlich wird die Exit-Code-Prüfung von `pip install` ergänzt, damit fehlgeschlagene Abhängigkeitsinstallationen nicht erst in der späteren `python-multipart`-Validierungsphase als sekundärer Fehler sichtbar werden.

### Tests

- 🧪 **Regressionsabdeckung für Aktienfrage / Backtest / intelligenter Import vervollständigt** — die E2E-Smoke-Erwartungen werden synchron aktualisiert und Regressions-Assertions für `DashboardStateBlock`, Chat-Seite, Dateiauswahl des intelligenten Imports und zugehörige Interaktionen ergänzt, damit die kritischen Pfade nach den jüngsten UI-Anpassungen weiterhin stabil bestehen.

## [3.10.0] - 2026-03-24

### Release-Highlights

- 🔎 **Autovervollständigung und Index-Tools auf drei Märkte erweitert** — die Erzeugungskette des Vervollständigungs-Index deckt jetzt A-Aktien, Hongkong-Aktien und US-Aktien ab; dazu kommen ein neues Tushare-Aktienlisten-Abruftool und vollständigere statische Indexdaten, wodurch der Sucheinstieg auf der Startseite von „nutzbar“ zu „vollständiger und stabiler“ wird.
- 🖥️ **Dashboard- und Berichtsansicht weiter konsolidiert** — Dashboard-Panels der Startseite, Statusgrenzen, Schriftebenen und die Tabellendichte vollständiger Berichte werden in einer Runde vereinheitlicht; die Berichtsdetails erhalten zusätzlich Markdown-/Reintext-Kopieren und zuverlässigere Schaltflächen-Interaktionen, wodurch Ansehen und Teilen historischer Berichte reibungsloser wird.
- 🤖 **Agent-Skill- und Markt-Semantikgrenzen klarer** — Skill-Bundle, Standardstrategie, Backtest-Summariesemantik und Kompatibilitätsschnittstellen werden weiter konsolidiert; zugleich wird der A-Aktien-Kontext nicht mehr standardmäßig im Analyse-Prompt festgeschrieben, sodass US- und Hongkong-Analysen passgenauere Inhalte nach ihren jeweiligen Marktregeln erzeugen.
- ⏰ **Zeitplan- und Desktop-Konfiguration näher am echten Einsatz** — der Desktop-Client unterstützt `.env`-Export und -Import; `python main.py --schedule --stocks ...` schleppt die beim Start erstellte Aktiensnapshot nicht mehr fälschlich in spätere Planausführungen, und geplante Aufgaben folgen der jeweils zuletzt gespeicherten `STOCK_LIST`.
### Neue Funktionen

- 💾 **`.env`-Sicherung/Wiederherstellung im Desktop-Client** (#754) — die Systemeinstellungsseite im Desktop-Modus erhält neue Schaltflächen `Export .env` / `Import .env`, mit denen die aktuell gespeicherte Konfiguration gesichert oder Schlüssel-Wert-Paare aus einer Sicherungsdatei in das aktuelle Desktop-`.env` übernommen werden können; der Import nutzt weiterhin den bestehenden `config_version`-Konflikt- und Laufzeit-Reload-Pfad und verändert den bestehenden portablen Desktop-Modus-Pfad nicht.
- 📊 **Tushare-Aktienlisten-Abruftool** — neu ist `scripts/fetch_tushare_stock_list.py`, das Listeninformationen für A-Aktien, Hongkong-Aktien und US-Aktien von Tushare Pro abruft und als CSV speichert, ausgestattet mit Paginierung, intelligenter Rate-Limitierung, Fehlerbehandlung und Fortschrittsanzeige; dazu kommt die Nutzungsdokumentation `docs/TUSHARE_STOCK_LIST_GUIDE.md`.
- 🔎 **Index-Erzeugungsskript unterstützt mehrere Märkte** — `generate_index_from_csv.py` wird so umgebaut, dass es Tushare und AkShare als doppelte Datenquelle unterstützt und zugleich die drei Märkte A-Aktien, Hongkong-Aktien und US-Aktien abdeckt; neu sind marktbezogene Alias-Mappings (gängige Aliasse für A-Aktien und Hongkong-Aktien, übliche englische Abkürzungen für US-Aktien); ein `--source`-Parameter wechselt die Datenquelle, `--test` aktiviert den Validierungsmodus; US-DUMMY-Datensätze werden streng gefiltert.
- 🔎 **Index-Erzeugungsskript erweitert** — `generate_stock_index.py` erhält die Modi `--test`/`-t` (Test) und `--verbose`/`-v` (detaillierte Ausgabe), Marktverteilungsstatistiken und ein optimiertes JSON-Ausgabeformat.
- 📋 **Vollständige Berichte auf der Startseite unterstützen Zwei-Modus-Kopieren** — im Kopf der Historienbericht-Details gibt es neue Werkzeugschaltflächen „Markdown-Quelltext kopieren“ und „Reinen Text kopieren“; Ersteres erhält die originale Markdown-Struktur, Letzteres entfernt gängige Markdown-Formatierungszeichen, was Teilen, Archivieren und Vergleichen über Berichte hinweg erleichtert. Die Schaltflächenbeschriftung folgt `REPORT_LANGUAGE` und bleibt damit in Chinesisch/Englisch konsistent, sodass in englischen Berichtsseiten keine chinesischen festen Texte erscheinen.
- 🧩 **Einzelaktien-Analyseseite zeigt zugehörige Sektoren** (#669) — der A-Aktien-Analyseschreibpfad schreibt `belong_boards` jetzt in einem Zug in `fundamental_context` / `fundamental_snapshot`; die strukturierten Berichtsdetails erhalten die Felder `belong_boards` und `sector_rankings`; die Web-Einzelaktien-Analyseseite kann auf dem ersten Bildschirm direkt die zugehörigen Sektoren sowie anzeigen, ob diese die Tages-Sektor-Rangliste erreichten; ohne Daten bleibt die Anzeige fail-open verborgen und beeinträchtigt den bestehenden Analyse-Hauptablauf nicht.

### Verbesserungen

- 🖥️ **Dashboard-Panels vereinheitlicht (PR7-2)** — `DashboardPanelHeader` und `DashboardStateBlock` werden als gemeinsame Komponenten für Panels wie Historie, Bericht, Nachrichten, Aufgaben und Transparenz eingeführt; Titel-Hierarchie, Lade-/Leer-/Fehlerzustände und CSS-Variablen-Tokens aller Panels werden vereinheitlicht.
- 🖥️ **HomePage-Zustandsgrenzen konsolidiert (PR7-2)** — der Hook `useHomeDashboardState` bündelt die Zustandsauswahl des `stockPoolStore` und entfernt doppelte lokale Zustandsableitungen und Callback-Definitionen in `HomePage`.
- 🧭 **Agent-Skill auf eine einheitliche Konfigurationssemantik zusammengeführt** — Multi-Agent-Runtime, API, Web-Chat und Konfigurationsmetadaten werden einheitlich um das `skill`-Konzept konsolidiert; `/api/v1/agent/skills` wird zum primären Erkennungseinstieg, `AGENT_SKILL_*` zur primären Konfigurationsfläche; die eingebauten Skill-Metadaten beginnen damit, standardmäßig aktiviert zu sein sowie Prioritäten und market-regime-Tags zu deklarieren, wodurch implizite Kopplungen verstreuter Standardstrategien im Code reduziert werden.
- 🔎 **Vervollständigungs-Indexdaten aktualisiert** — `stocks.index.json` wird neu erzeugt und deckt die drei Märkte A-Aktien, Hongkong-Aktien und US-Aktien ab, was die Abdeckung der Autovervollständigung verbessert.
- 🧾 **Dashboard-Schrift und Tabellendichte vollständiger Berichte feinjustiert** — Schriftebenen der Startseiten-Sidebar, Leerzustände und des Verlaufsbedienbereichs werden konsolidiert und die Innenabstände von `th/td` in vollständigen Markdown-Berichtstabellen auf ein kompakteres 4-6px-Band angepasst, sodass die Informationsdichte besser zum visuellen Rhythmus des bestehenden Dashboards passt.

### Behobene Probleme

- ⏰ **Zeitplanmodus sperrt die CLI-Aktiensnapshot vom Start nicht mehr ein** — `python main.py --schedule --stocks ...` lässt nachfolgende Planausführungen nicht mehr die alte Aktienliste vom Start übernehmen; geplante Aufgaben lesen vor jedem Auslösen erneut die zuletzt gespeicherte `STOCK_LIST`, sodass nach WebUI- oder `.env`-Aktualisierungen konfigurierte Watchlists an späteren Pushes teilnehmen.
- 🌍 **LLM-Prompt injiziert Kontext dynamisch nach Aktienmarkt** — die Analyse-Pipeline schreibt die Marktregeln nicht mehr fest auf A-Aktien; das System-Prompt erkennt anhand des Aktiencodes, ob es sich um A-Aktien, Hongkong-Aktien oder US-Aktien handelt, und injiziert entsprechende Rollenbeschreibung und Trading-Regelhinweise, wodurch Marktverwechslungen oder verzerrte Schlussfolgerungen bei marktübergreifenden Analysen reduziert werden.
- 🔎 **US-Autovervollständigung dedupliziert wiederverwendete Ticker** — `generate_index_from_csv.py` faltet beim Import der Tushare-`us_basic`-CSV wiederverwendete US-Ticker zuerst über `ts_code` zusammen, wobei vorzugsweise weiterhin wahrscheinlich genutzte Datensätze erhalten bleiben; so zeigen weder doppelte `canonicalCode` in `stocks.index.json` alte Namen in der Web-Autovervollständigung an noch reicht die Einreichung mehrdeutige Codes ein.
- 🧾 **Kopier-Interaktionsstabilität in der Web-Berichtsdetailansicht repariert** (#749) — die Kopierknöpfe für „Original-Analyseergebnis / Analyseschritt“ in `ReportDetails` erhalten eine anklickbare Ebene, sodass sie nicht mehr vom darunterliegenden JSON-Inhalt überdeckt werden; die Kopierhinweise der beiden Panels sind nun getrennt, sodass nicht mehr nach dem Kopieren eines Panels beide Knöpfe gleichzeitig „Kopiert“ anzeigen.
- 📊 **Agent-Skill-Backtest- und Kompatibilitätsschnittstellen-Semantik konsolidiert** — `get_skill_backtest_summary` verlangt jetzt eine explizite Übergabe von `skill_id` und liefert bei fehlendem Wert einen klaren Validierungshinweis; sofern das Repository noch keine echten skill-bezogenen Zusammenfassungen persistiert hat, wird eine eindeutige unsupported/info-Antwort zurückgegeben, mit beibehaltenen `normalized`- und `*_pct`-Kompatibilitätsfeldern, damit Agent oder Nutzer nicht durch overall-Kennzahlen in die Irre geführt werden.
- 🔧 **Standard-Skillauswahl und Kompatibilitätsschicht gehärtet** — `allowed-tools` bleibt weiterhin nur als `SKILL.md`-Bundle-Metadaten erhalten und wird nicht mehr in die Laufzeit-Toolauswahl durchgereicht; `/api/v1/agent/strategies` stellt die alte Payload-Form wieder her; ein explizit übergebenes `skills: []` leert veralteten Kontext; wählt der Nutzer eine Strategie-Skill explizit, wird kein Standard-bull-trend mehr heimlich aufgesetzt, während bei leerem `AGENT_SKILLS` einheitlich auf einen einzigen primären Standard-Skill zurückgefallen wird.

### Tests

- 🧪 **Testabdeckung der Dashboard-Komponenten erweitert (PR7-2)** — neue Tests für `ReportNews` und `TaskPanel`; für `HistoryList`, `ReportDetails`, `HomePage`, `useDashboardLifecycle` und `stockPoolStore` werden die Assertions ausgebaut, inklusive Szenarien wie Lösch-Rückfall, mobile Drawer und Aufgabenlebenszyklen.
- 🧪 **Multi-Markt-Index-Erzeugungstests ergänzt** — neu ist `tests/test_generate_index_from_csv.py`, das zentrale Pfade wie Doppel-Datenquellen-Parsing von Tushare/AkShare, Multi-Markt-Erkennung, US-DUMMY-Filter und Duplikat-Ticker-Deduplizierung abdeckt.
- 🧪 **Regressions-Tests für zugehörige Sektoren und API-Verträge** — neu ist `tests/test_pipeline_related_boards.py`; zusätzlich werden Analyse-Historie- und Analyse-API-Vertragstests ergänzt, um sicherzustellen, dass `belong_boards` / `sector_rankings` nur inkrementell erweitert werden und fail-open bleiben.
- 🧪 **Regressions-Tests für die Aktienlisten-Semantik im Zeitplanmodus** — neu ist `tests/test_main_schedule_mode.py`, das die Randfälle abdeckt, dass der Zeitplanmodus die Start-`--stocks`-Snapshot ignoriert und Einzelausführungen die CLI-Aktienüberschreibung beibehalten.

### Dokumentation

- 📘 **Neue Dokumentation für das Tushare-Aktienlisten-Tool** — neu ist `docs/TUSHARE_STOCK_LIST_GUIDE.md`, das Nutzung, Datenformat und häufige Probleme des Aktienlisten-Abruftools beschreibt.
- 🌍 **Zweisprachige Erläuterungen zu Zeitplanmodus und zugehörigen Sektoren ergänzt** — `docs/full-guide.md` / `docs/full-guide_EN.md` stellen jetzt klar, dass der scheduled mode vor jeder Ausführung erneut die `STOCK_LIST` liest, und ergänzen zugleich die Erläuterung der Einzelaktien-Sektor-Anzeige, um Fehl-Erwartungen an die Konfiguration zu reduzieren.
- 🧭 **Agent-Terminologie-Kompatibilitätstexte angepasst** — README, zweisprachige Dokumente, Einstellungsseite und Aktienfrage-Oberfläche verwenden weiterhin „Strategie“ als primären Nutzereinstieg, ergänzen aber `skill` als interne einheitliche Benennung, um die Verständniskosten während der Migration zu senken.

## [3.9.0] - 2026-03-20

### Release-Highlights

- 🤖 **Modell-Pipeline und Berichtssprache flexibler** — der Agent kann über `AGENT_LITELLM_MODEL` nun eine eigene Modell-Pipeline wählen, und normale Analysen wie Agent-Berichte können über `REPORT_LANGUAGE=zh|en` eine einheitliche Sprache ausgeben, wodurch gemischte Ausgaben wie „englischer Inhalt + chinesische Hülle“ reduziert werden und Teams Kosten, Geschwindigkeit und Fähigkeiten von Hauptanalyse und Agent getrennt abwägen können.
- 🔎 **Startseiten-Analyseerlebnis schließt eine Runde End-to-End-Optimierung ab** — die Startseite erhält A-Aktien-Autovervollständigung mit Suche über Code, chinesischen Namen, Pinyin und Aliasse; zugleich wird der Dashboard-Zustand in einem gemeinsamen Store konsolidiert; Interaktionen von Historie, Bericht, Nachrichten und Markdown-Drawer sind stabiler, und „Ask AI“-Rückfragen transportieren bevorzugt den aktuellen Berichtskontext mit.
- 💬 **Benachrichtigungs- und Retrieval-Fähigkeiten weiter ausgebaut** — neu ist Slack als erstklassiger Benachrichtigungskanal; SearXNG kann ohne konfigurierte eigene Instanz automatisch öffentliche Instanzen entdecken und mit gesteuerter Rotation degradieren; nach dem Fix der Tavily-Zeitnachrichten-Kette werden strikte Zeitfilter nicht mehr fälschlich alle gültigen Ergebnisse verwerfen.
- 💼 **Positionen- und Markt-Review-Kette stabiler** — A-Aktien-Markt-Review kann optional TickFlow zur Verstärkung von Index- und Kursbewegungsstatistiken anbinden; Positionsbuch-Schreibvorgänge werden serialisiert, um das gleichzeitige Überverkaufsfenster zu verkleinern; Wechselkurs-Refresh-Einstieg und Deaktivierungs-Hinweise sind klarer, wodurch Fehlbeurteilungen der Nutzer reduziert werden.

### Neue Funktionen

- 🔎 **Web-Aktien-Autovervollständigung MVP** — das Analyse-Eingabefeld der Startseite erhält eine lokale, indexgetriebene Autovervollständigung mit Abgleich über Aktiencode, chinesischen Namen, Pinyin und Aliasse; nach Auswahl eines Kandidaten wird der canonical code eingereicht und `stock_name`, `original_query`, `selection_source` an Analyseanfrage, Aufgabenstatus und SSE-Ereignis durchgereicht; schlägt das Laden des Index fehl, wird automatisch auf den alten Eingabemodus zurückgefallen, ohne den bisherigen Einreichungsablauf zu blockieren. Synchron werden statischer Index-Loader, Index-Erzeugungsskript und Frontend-/Backend-Vertragstests ergänzt. Die Entwicklung läuft phasenweise; die erste Phase unterstützt nur A-Aktien.
- 💬 **Slack als erstklassiger Benachrichtigungskanal** — native Slack-Benachrichtigungen werden unterstützt, mit beiden Anbindungswegen Bot Token und Incoming Webhook; bei gleichzeitiger Konfiguration wird die Bot-API bevorzugt, damit Text und Bilder im selben Kanal landen; der Bot-Token-Modus unterstützt Bild-Upload (raw body POST, ohne multipart); neu sind `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`, `SLACK_WEBHOOK_URL` als Konfigurationsoptionen, und der GitHub-Actions-Workflow reicht die entsprechenden Secrets durch.
- 🌍 **Berichtsausgabesprache konfigurierbar** (Issue #758) — neu ist `REPORT_LANGUAGE=zh|en`, Standard `zh`; die Spracheinstellung wird synchron in normale Analysen und Agent-Prompts injiziert und deckt Markdown/Jinja-Vorlagen, Benachrichtigungs-Fallback, `report_language`-Metadaten von Historie/API sowie feste Web-Berichtsseitentexte ab, wodurch gemischte Ausgaben wie „englischer Inhalt + chinesische Hülle“ vermieden werden.
- 🚀 **Agent und normale Analyse-Modelle entkoppelt** (Issue #692) — neu ist `AGENT_LITELLM_MODEL` (leer lässt `LITELLM_MODEL` erben, ohne Präfix wird als `openai/<model>` normalisiert); die `is_primary`/`is_fallback`-Kennzeichen von Agent-Ausführungskette und `/api/v1/agent/models` basieren auf der tatsächlichen Agent-Modellkette; Systemkonfiguration und Startvalidierung ergänzen die Prüfungen `unknown_model/missing_runtime_source` für `AGENT_LITELLM_MODEL`; die Web-Einstellungsseite erhält eine Agent-Hauptmodellauswahl, die mit der Laufzeitkonfiguration im Kanalmodus synchronisiert wird.
- 🔎 **SearXNG-öffentliche-Instanz-Autodiscovery und gesteuerte Rotation** (#752) — neu ist `SEARXNG_PUBLIC_INSTANCES_ENABLED`, das bei nicht konfigurierten `SEARXNG_BASE_URLS` standardmäßig die Liste öffentlicher Instanzen von `searx.space` lädt und Instanzen in gesteuerter Rotationsreihenfolge auswählt; innerhalb derselben Anfrage wird bei Timeout, Verbindungsfehler, HTTP ungleich 200 oder ungültigem JSON automatisch zur nächsten Instanz gewechselt. Nutzer mit konfigurierter eigener Instanz behalten Priorität und Semantik unverändert; der GitHub-Actions-Workflow `daily_analysis` unterstützt ebenfalls die explizite Durchreichung des Schalters und zeigt den aktuellen Status im Startlog an.
- 📈 **TickFlow-Markt-Review-Erweiterung** (#632) — neu ist die optionale `TICKFLOW_API_KEY`; nach Konfiguration versucht die Hauptindex-Kurskette des A-Aktien-Markt-Reviews bevorzugt TickFlow; unterstützt der aktuelle TickFlow-Tarif die Zielpool-Abfrage, versuchen auch Markt-Kursbewegungsstatistiken bevorzugt TickFlow. Bei Fehlern oder fehlenden Berechtigungen wird sofort auf die bestehende `AkShare / Tushare / efinance`-Kette zurückgefallen; die Fallback-Reihenfolge der Sektor-Rangliste bleibt unverändert. Die Anbindungsschicht passt sich zugleich an den echten SDK-Vertrag an: Die Hauptindex-Abfrage lädt in Chargen innerhalb des Einzelrequest-Limits und die von TickFlow gelieferten proportionalen `change_pct` / `amplitude` werden einheitlich in die prozentuale Maßgabe des Projekts umgerechnet.

### Verbesserungen

- **Dashboard-Zustandsausschnitt und Workbench-Abschluss** — der Home-/Dashboard-Zustand wurde in `stockPoolStore` verschoben; Historie-Auswahl, Berichts-Laden, Aufgaben-Sync, Polling-Refresh und Markdown-Drawer-Verarbeitung werden unter einem einzigen Zustandsausschnitt konsolidiert.
- **Dashboard-Panel-Standardisierung** — der bestehende Dashboard-Layout-Vertrag bleibt stabil, während Historie, Bericht, Nachrichten und Markdown-Darstellung mit gemeinsamen Tokens vereinheitlicht, Zustände standardisiert und das Scrollen innerhalb der Panels für die Historie begrenzt wird.
- **Dashboard-zu-Chat-Rückfrage-Brücke** — „Ask AI“-Rückfragen werden über die Hydration des Berichtskontexts geleitet statt über direkte Seiten-zu-Seiten-Zustandskopplung, während das Absenden im Chat nutzbar bleibt, wenn der angereicherte Historienkontext noch lädt.
- 💼 **Positionsbuch-Schreibvorgänge parallel serialisiert** (#742) — Schreib-/Löschvorgänge von Positionsquellen-Ereignissen holen unter SQLite zuerst eine Serialisierungs-Schreibsperre, was das Fenster verkleinert, in dem parallele Verkäufe Überverkaufs-Transaktionen ins Buch schreiben; die direkte Positions-Schreibschnittstelle liefert bei Sperrenkonkurrenz `409 portfolio_busy`, CSV-Import bleibt Transaktion-für-Transaktion und zählt busy in `failed_count`.
- 💱 **Manueller Wechselkurs-Refresh-Einstieg auf der Positionsseite ergänzt** (#748) — die Web-Seite `/portfolio` zeigt jetzt in der „Wechselkursstatus“-Karte einen „Wechselkurse aktualisieren“-Knopf, der die bestehende Schnittstelle `POST /api/v1/portfolio/fx/refresh` aufruft; nach dem Refresh werden nur Snapshot und Risikodaten neu geladen und das Ergebnis über eine Inline-Zusammenfassung „Aktualisiert / weiterhin stale / Aktualisierung fehlgeschlagen“ zurückgemeldet, wodurch Fehldeutungen über längeren `fxStale`-Aufenthalt reduziert werden.

### Behobene Probleme

- 🔎 **Enter-Einreichungssemantik der Web-Autovervollständigung korrigiert** — die Aktien-Autovervollständigung hebt bei Suchtreffern nicht mehr standardmäßig den ersten Eintrag hervor; ist die Kandidatenliste geöffnet, aber vom Nutzer noch keine Pfeiltaste oder Mausauswahl erfolgt, wird beim Drücken von Enter die ursprüngliche Eingabe eingereicht, sodass manuelle Eingaben nicht still vom ersten Kandidaten überschrieben werden.
- 🌍 **Start-Parsing von `REPORT_LANGUAGE` und Lokalisierungsgrenzen der Historienanzeige ergänzt** — `Config` folgt beim Start weiterhin der bestehenden Semantik „echte Umgebungsvariable zuerst, `.env` als Fallback“ und gibt bei Konflikten eine explizite Warnung aus, wodurch Fehlbeurteilungen über die Quelle von `REPORT_LANGUAGE` reduziert werden; zugleich lokalisiert die englische Detailantwort von `/api/v1/history/{id}` `sentiment_label` synchron, und historische Markdowns erkennen das Risikoniveau-Emoji von `bias_status` auf Englisch korrekt, sodass gemischte oder fehlgemeldete Anzeigen wie `Optimistisch` oder `🚨Safe` vermieden werden.
- 📰 **Veröffentlichungszeit-Mapping der Tavily-Zeitnachrichten-Recherche repariert** (#782) — Tavily nutzt in den Nachrichten- und strikt-zeitkritischen Informationsdimensionen von Aktien jetzt explizit `topic="news"` und ist mit den beiden Veröffentlichungszeitfeldern `published_date` / `publishedDate` kompatibel; behoben wird, dass Tavily zwar Ergebnisse lieferte, diese aber im späteren Hartfilter-Zyklus alle als `drop_unknown` verworfen wurden; zugleich werden analytische Dimensionen wie Institutsanalysen, Ergebnis-Erwartungen und Branchenanalysen wieder als breite Quellsuche behandelt und nicht mehr einheitlich in den Nachrichtenmodus gepresst.
- 💱 **Deaktivierungssemantik des Wechselkurs-Refresh auf der Positionsseite korrigiert** (#772) — bei `PORTFOLIO_FX_UPDATE_ENABLED=false` liefert `POST /api/v1/portfolio/fx/refresh` jetzt explizit `refresh_enabled=false` und `disabled_reason`, und die Web-Seite `/portfolio` weist klar auf „Online-Wechselkursaktualisierung ist deaktiviert“ hin, statt fälschlich „Keine aktualisierbaren Wechselkurspaare im aktuellen Bereich“ zu melden.
- 🤖 **Agent-Timeout- und Konfigurationshärtung** — `AGENT_ORCHESTRATOR_TIMEOUT_S` schützt jetzt auch die Legacy-Single-Agent-ReAct-Schleife; parallele Tool-Chargen stoppen das Warten, sobald das verbleibende Budget erschöpft ist; ungültige numerische `.env`-Werte fallen mit Warnungen auf sichere Standardwerte zurück, statt den Start abstürzen zu lassen.
- 🌐 **CORS-Wildcard + Credentials-Kompatibilität** — `CORS_ALLOW_ALL=true` kombiniert `allow_origins=["*"]` nicht mehr mit credentialisierten Requests und vermeidet damit Browser-seitige Cross-Origin-Fehler in Demo-/Entwicklungssetups.
- 🧭 **Nicht verfügbare Agent-Einstellungen aus der Web-UI ausgeblendet** — Deep-Research-/Event-Monitor-Steuerelemente werden im aktuellen Zweig nur noch als Kompatibilitäts-Metadaten behandelt und aus der Einstellungsseite entfernt, um nicht funktionsfähige Schalter nicht mehr zu exponieren.

### Dokumentation

- Neue Erläuterung zur Konfiguration lokaler Ollama-Modelle, synchron aktualisiert in `README.md` und `docs/README_EN.md` (Fixes #690)
- Ollama-Konfigurationsanleitung vervollständigt: In den Umgebungsvariablen-Tabellen und Notizen von `docs/full-guide.md` / `docs/full-guide_EN.md` wird `OLLAMA_API_BASE` ergänzt, damit englischsprachige Nutzer nicht annehmen, Ollama sei kein eigenständiger Konfigurationseinstieg; doppelte `OLLAMA_API_BASE`-Einträge werden zu einem einzigen zusammengeführt
- Governance-Grenzen der Dokumentsynchronisation klargestellt: Standard-Synchronisationsregeln zwischen README, Themen-Dokumenten, zweisprachigen Dokumenten und Lieferhinweisen werden ergänzt, um künftige Dokumentabdrift zu reduzieren

## [3.8.0] - 2026-03-17

### Release-Highlights

- 🎨 **Web-Oberfläche schließt eine Runde Skelett-Upgrade ab** — neue App Shell, Seitennavigation, Theme-Fähigkeiten sowie Login- und Systemeinstellungs-Abläufe sind zu einer einheitlichen Erfahrung verbunden; der Desktop-Ladehintergrund ist ebenfalls angeglichen.
- 📈 **Analysekontext weiter gestärkt** — US-Aktien erhalten Social-Sentiment-Intelligenz, A-Aktien vervollständigen strukturierte Kontexte für Finanzberichte und Dividenden, und Tushare bindet neu Chip-Verteilung sowie Sektor-/Branchen-Kursbewegungsdaten an.
- 🔒 **Laufzeitstabilität und Konfigurationskompatibilität erhöht** — Abmelden macht alte Sitzungen sofort ungültig, zeitgesteuerter Start ist mit alter Konfiguration kompatibel, und laufende `MAX_WORKERS`-Anpassungen sowie das Nachrichten-Zeitfenster-Feedback sind klarer.
- 💼 **Positions-Korrekturkette vollständiger** — Überverkäufe werden vorab blockiert; fehlerhafte Transaktionen/Kapitalflüsse/Unternehmensereignisse können direkt gelöscht und zurückgerollt werden, um Dreckdaten zu reparieren.

### Neue Funktionen

- 📱 **Social-Sentiment-Intelligenz für US-Aktien** — neu sind die Social-Media-Stimmungsdatenquellen Reddit / X / Polymarket, die US-Analysen ergänzende Kennzahlen wie Echtzeit-Social-Hitze, Stimmungswerte und Erwähnungszahlen liefern; vollständig optional und nur nach Konfiguration von `SOCIAL_SENTIMENT_API_KEY` für US-Aktien wirksam.
- 📊 **Strukturierte A-Aktien-Erweiterung für Finanzberichte und Dividenden** (Issue #710) — `fundamental_context.earnings.data` erhält die Felder `financial_report` und `dividend`; Dividenden werden einheitlich als „nur Bardividende, vor Steuern“ berechnet, ergänzt um `ttm_cash_dividend_per_share` und `ttm_dividend_yield_pct`; die Analyse-/Historie-APIs erhalten in `details` die optionalen Felder `financial_report`, `dividend_metrics`, mit beibehaltenem fail-open und Rückwärtskompatibilität.
- 🔍 **Tushare-Chip- und Branchen-Sektorschnittstellen angebunden** — neue Fähigkeiten zum Abrufen der Chip-Verteilung und von Branchen-Sektor-Kursbewegungsdaten, einheitlich in die konfigurierbare Datenquellen-Priorität eingegliedert; standardmäßig wird anhand der Shanghaier Zeit zwischen Intraday-/Post-Market-Handelstagen unterschieden, bevorzugt die Tushare-Tonghuashun-Schnittstelle und degradiert bei Bedarf auf Eastmoney.
- 🧱 **Web-UI-Basisskelett-Upgrade** — gemeinsame Design-Tokens und generische Komponenten werden neu aufgebaut, App Shell, Theme Provider und Seitennavigation ergänzt sowie der Electron-Ladehintergrund angepasst, als Grundlage für eine einheitliche Web-/Desktop-Erfahrung.
- 🔐 **Login- und Systemeinstellungsabläufe neu gemacht** — Login-, Settings- und Auth-Verwaltungsabläufe werden umgebaut, eine explizite Behandlung des Authentifizierungs-Setup-Zustands ergänzt und die Web-Seite an die Laufzeit-Authentifizierungskonfigurations-API angeglichen.
- 🧪 **Frontend-Regressions- und Smoke-Abdeckung gestärkt** — Komponententests für kritische Pfade wie Login, Startseite, Chat, mobiles Shell, Einstellungsseite und Backtest-Einstieg werden neu hinzugefügt und erweitert, dazu Playwright-Smoke-Abdeckung.

### Änderungen

- 🧭 **Seiten an den neuen Shell-Layout-Vertrag angebunden** — Home, Chat, Settings und Backtest sind einheitlich an die neuen Seitencontainer, Drawer und Scroll-Konventionen angeschlossen, wodurch inkonsistentes Seitenverhalten während der UI-Migration reduziert wird.
- 💾 **Zustandssynchronisation der Einstellungsseite stabiler** — Entwurfs-Speicherung, Direkt-Speichersynchronisation und Konfliktbehandlung werden optimiert, sodass nach modulbezogenem Speichern weniger Frontend-/Backend-Konfigurationszustands-Diskrepanzen auftreten.
- 🎭 **Login-Seiten-Visualbaseline zurückgeführt** — die Login-Seite kehrt zur etablierten Visualbaseline des `006`-Zweigs zurück, während die neue Authentifizierungs-Zustandslogik und das einheitliche Formular-Interaktionsmodell erhalten bleiben.
- 🏛️ **AI-Kollaborations-Governance-Assets gehärtet** — Konsistenzbeschränkungen von `AGENTS.md`, `CLAUDE.md`, Copilot-Anweisungen und Validierungsskripten werden konsolidiert und gestärkt, um langfristige Abdrift der Governance-Assets zu reduzieren.

### Added

- **Web UI foundation refresh** — rebuilt shared design tokens and common primitives, introduced the app shell, theme provider, sidebar navigation, and Electron loading background alignment for the upgraded desktop/web experience
- **Settings and auth workflow overhaul** — rebuilt the Login, Settings, and Auth management flows, added explicit auth setup-state handling, and aligned the Web UI with the runtime auth configuration APIs
- **UI regression coverage and smoke checks** — expanded targeted frontend tests and added Playwright smoke coverage for login, home, chat, mobile shell, settings, and backtest entry flows

### Changed

- **Shell-driven page integration** — aligned Home, Chat, Settings, and Backtest with the new shell layout contract so routing, drawer behavior, and page-level scrolling are consistent during the UI migration
- **Settings state consistency** — refined draft preservation, direct-save synchronization, and conflict handling so module-level saves no longer leave the page out of sync with backend config state
- **Login visual baseline** — restored the login page visual treatment to the established `006` branch baseline while keeping the newer auth-state logic and unified form interaction model

### Behobene Probleme

- ⏰ **Zeitgesteuerter Start mit Sofortausführung kompatibel mit alter Konfiguration** (Issue #726) — ist `SCHEDULE_RUN_IMMEDIATELY` nicht gesetzt, wird auf `RUN_IMMEDIATELY` zurückgefallen, was Kompatibilitätsprobleme alter `.env`-Dateien im Zeitplanmodus nach Upgrades behebt; zugleich wird der Anwendungsbereich der beiden Konfigurationsoptionen in `.env.example` / README geklärt und darauf hingewiesen, dass Outlook / Exchange erzwungenes OAuth2 vorerst nicht unterstützen.
- 🧵 **Laufzeit-`MAX_WORKERS`-Konfiguration wirksam und erklärbar** (#633) — behoben wird, dass die asynchrone Analyse-Warteschlange nicht gemäß `MAX_WORKERS` synchronisiert wurde; eine neue In-place-Synchronisationsmechanik für die Aufgabenwarteschlangen-Parallelität wird ergänzt (sofort bei Leerlauf, verzögert bei Auslastung), und `profile/max/effective` werden im Speicher-Rückmeldung und Laufzeit-Log klar ausgegeben, wodurch „Parameter wirkungslos“-Missverständnisse reduziert werden.
- 🔐 **Abmelden macht bestehende Sitzungen sofort ungültig** — `POST /api/v1/auth/logout` rotiert jetzt das session secret, sodass alte Cookies nach dem Abmelden nicht mehr auf geschützte Schnittstellen zugreifen können; gleiche Browser-Tabs und parallele Seiten werden synchron abgemeldet. Bei aktivierter Authentifizierung gehört die Schnittstelle nicht mehr zur anonymen Whitelist, und nicht angemeldete Anfragen erhalten `401`, sodass anonyme Anfragen keine globale Sitzungs-Invalidierung auslösen.
- 🧮 **Rate-Limit und Tagesübergreifende-Cache-Fix für Tushare-Sektoren/Chips** — die neuen Ketten `trade_cal`, Branchen-Sektor-Ranglisten und Chip-Verteilung werden einheitlich an `_check_rate_limit()` angeschlossen; der Handelstag-Cache wird nach Kalendertag aufgefrischt, damit über Tage laufende Dienste nicht weiter mit alten Handelstags-Entscheidungen das Datum bestimmen.
- 💼 **Überverkaufs-Blockierung und Wiederherstellung fehlerhafter Flüsse bei Positionen** (#718) — `POST /api/v1/portfolio/trades` validiert jetzt vor dem Schreiben die verkaufbare Menge und liefert bei Überverkauf `409 portfolio_oversell`; die Positionsseite erhält Löschfähigkeit für Transaktionen / Kapitalflüsse / Unternehmensereignisse; nach dem Löschen werden Positions-Cache und Zukunfts-Snapshots synchron invalidisiert, sodass aus fehlerhaften Flüssen direkt wiederhergestellt werden kann.
- 📧 **Encoding des chinesischen Absendernamens in E-Mails** (#708) — E-Mail-Benachrichtigungen encodieren einen chinesisch enthaltenden `EMAIL_SENDER_NAME` jetzt automatisch nach RFC 2047 und ergänzen in Fehlerpfaden eine SMTP-Verbindungsbereinigung, wodurch Sendefehler durch `'ascii' codec can't encode characters` unter GitHub Actions / QQ-SMTP behoben werden.
- 🐛 **Deduplizierung und schnelles Routing der Hongkong-Agent-Echtzeitkurse** — Normalisierungsregeln für Hongkong-Codes wie `HK01810` / `1810.HK` / `01810` werden vereinheitlicht; Hongkong-Echtzeitkurse laufen direkt über den einmaligen `akshare_hk`-Pfad statt über A-Aktien-Source-Priorität denselben fehlschlagenden Endpunkt wiederholt auszulösen; zur Laufzeit erhält der Agent für explizit `retriable=false` gescheiterte Tools einen Kurzschluss-Cache, um wiederholte Fehlaufrufe in derselben Analyse zu reduzieren.
- 📰 **Harter Zeitfilter für Nachrichten und strategische Zeitfenster** (#697) — neu ist `NEWS_STRATEGY_PROFILE` (`ultra_short/short/medium/long`), das zusammen mit `NEWS_MAX_AGE_DAYS` das effektive Fenster berechnet; Suchergebnisse werden nach Rückkehr einem harten Veröffentlichungszeitfilter unterzogen (Zeit unbekannt verwerfen, Fensterüberschreitung verwerfen, Zukunft nur 1 Tag tolerieren), und derselbe Filter gilt in der historischen Fallback-Kette, sodass alte Nachrichten nicht erneut in „Neueste Entwicklungen / Risikoalarme“ gelangen.

### Dokumentation

- ☁️ **Neues Tutorial für Deployment und Zugriff der Web-Oberfläche auf Cloud-Servern** (Fixes #686) — ergänzt die konkrete Anleitung vom Cloud-Deployment bis zum externen Zugriff, was die Schwelle für Remote-Selfhosting senkt.
- 🌍 **Englische Dokumentindex- und Kollaborationsdokumente ergänzt** — englischer Dokumentindex, Beitragsleitfaden und Bot-Befehlsdokumentation sind neu, dazu zweisprachige Issue-/PR-Vorlagen, um englisch-chinesische Kollaboration und den Einstieg externer Beitragender zu erleichtern.
- 🏷️ **Lokalisierte README ergänzt Trendshift-Badge** — in mehrsprachigen README-Dateien wird das Badge des neuen Fähigkeitseinstiegs synchron ergänzt, um Unterschiede zwischen chinesischer und englischer Darstellung zu reduzieren.

## [3.7.0] - 2026-03-15

### Neue Funktionen

- 💼 **Positionsverwaltung P0 vollständig veröffentlicht** (#677, entspricht Issue #627)
  - **Kernbuch- und Snapshot-Kreislauf geschlossen**: Kernmodelle und API-Endpunkte für Konten, Transaktionen, Kapitalflüsse, Unternehmensereignisse, Positions-Cache und Tages-Snapshots; Unterstützung der FIFO-/AVG-Doppel-Kostenmethode-Wiedergabe; Ereignisreihenfolge am selben Tag fest als `Kapital → Unternehmensereignis → Transaktion`; Positions-Snapshot-Schreiben erfolgt in atomaren Transaktionen.
  - **Broker-CSV-Import**: unterstützt zuerst Huatai / CITIC / China Merchants, inklusive Spaltenname-Alias-Kompatibilität; zweistufige Schnittstelle (Parse-Vorschau + Bestätigungs-Einreichung); idempotente Deduplizierung mit `trade_uid`-Priorität und key-field-hash-Fallback; führende Nullen bei Aktiencodes bleiben vollständig erhalten.
  - **Portfolio-Risikobericht**: Konzentrationsrisiko (Top Positions + A-Aktien-Sektordefinition), historische Drawdown-Überwachung (mit Nachfüllen fehlender Snapshots), Stop-Loss-Nähewarnung; multiwährungsweise einheitliche Umrechnung in CNY; bei fehlgeschlagenem Abruf Rückfall auf den zuletzt erfolgreichen Wechselkurs und Markierung als stale.
  - **Web-Positionsseite** (`/portfolio`): Portfolio-Übersicht, Positionsdetails, Konzentrations-Pie-Chart, Risikozusammenfassung, Gesamtportfolio-/Einzelkonto-Umschaltung; manuelle Erfassung von Transaktionen / Kapitalflüssen / Unternehmensereignissen; eingebetteter Kontoerstellungs-Einstieg; CSV-Parse + Einreichungs-Kreislauf mit Broker-Auswahl.
  - **Agent-Positionstool**: neu ist das Datentool `get_portfolio_snapshot` mit standardmäßig kompakter Zusammenfassung und optionalen Positionsdetails und Risikodaten.
  - **Ereignisabfrage-APIs**: neu sind `GET /portfolio/trades`, `GET /portfolio/cash-ledger`, `GET /portfolio/corporate-actions`, mit Datumsfilter und Paginierung.
  - **Erweiterbarer Parser-Registry**: Anwendungsbezogene gemeinsame Registrierung mit Laufzeit-Registrierung neuer Broker; neu ist die Erkennungsschnittstelle `GET /portfolio/imports/csv/brokers`.

- 🎨 **Frontend-Designsystem und atomare Komponentenbibliothek** (#662)
  - Einführung einer progressiven Dual-Theme-Architektur (HSL-variabilisierte Design-Tokens), Bereinigung historischer Legacy-CSS; Umbau von 20+ Kernkomponenten wie Button / Card / Badge / Collapsible / Input / Select; neue `clsx` + `tailwind-merge`-Klassen-Zusammenführungstools; Verbesserung der Lesbarkeit von Seiten wie Historienlog und LLM-Konfiguration.

- ⚡ **Asynchroner Vertrag der Analyse-API und Startoptimierung** (#656)
  - Normierung des Rückgabevertrags für asynchrone Anfragen von `POST /api/v1/analysis/analyze`; Optimierung der Hilfslogik beim Dienststart; Behebung der Abweichung zwischen der Frontend-Union-Type-Definition für Berichte und der Backend-Antwort.

### Behobene Probleme

- 🔔 **Discord-Umgebungsvariablen rückwärtskompatibel** (#659): zur Laufzeit wird der Fallback-Lesezugriff `DISCORD_CHANNEL_ID` → `DISCORD_MAIN_CHANNEL_ID` ergänzt; Nutzer mit historischer Konfiguration müssen nichts ändern, um Discord-Bot-Benachrichtigungen wiederherzustellen; alle zugehörigen Dokumente und `.env.example` werden angeglichen.
- 🔧 **GitHub-Actions-Node-24-Upgrade** (#665): alle offiziellen GitHub-Actions werden auf Node-24-kompatible Versionen aktualisiert, wodurch die Node.js-20-Deprecation-Warnung in CI-Logs beseitigt wird (betrifft das erzwungene Upgrade-Fenster am 2026-06-02).
- 📅 **Standarddatum der Positionsseite lokalisiert**: das Standarddatum der manuellen Erfassungsformulare verwendet jetzt die lokale Zeit (`getFullYear/Month/Date`), wodurch die Datumsverschiebung für Nutzer in UTC-N-Zeitzonen am Abend des Tages behoben wird.
- 🔁 **Deduplizierungslogik des CSV-Imports gehärtet**: der dedup-hash bezieht die Zeilennummer als Unterscheidungsfaktor ein, sodass legale, über mehrere Zeilen verteilte Abschlüsse derselben Felder nicht fälschlich zusammengefaltet werden; zugleich wird der hash auch bei vorhandenem `trade_uid` persistiert, um doppelte Schreibvorgänge aus gemischten Quellen zu verhindern.

### Änderungen

- `POST /api/v1/portfolio/trades` gibt bei `trade_uid`-Konflikt innerhalb desselben Kontos `409` zurück.
- Die Positions-Risikoantwort erhält das Feld `sector_concentration` (inkrementelle Erweiterung); das bisherige `concentration`-Feld bleibt unverändert.
- Das asynchrone Verhaltensmuster der `analyze`-Schnittstelle der Analyse-API wird dokumentiert; die Frontend-Berichts-Union-Type wird aktualisiert.

### Tests

- Neue Tests für den Positions-Kerndienst (FIFO / AVG Teilverkäufe, Ereignisreihenfolge am selben Tag, doppelter `trade_uid` gibt 409, Snapshot-API-Vertrag).
- Neue Tests für CSV-Import-Idempotenz, legale Teilabschlüsse ohne Fehldeduplizierung, Deduplizierungsgrenzen, Risiko-Schwellwertgrenzen und Wechselkurs-Degradationsverhalten.
- Neue Tests für den Agent-Toolaufruf `get_portfolio_snapshot`.
- Neue Regressions-Tests für den asynchronen Vertrag der Analyse-API.

## [3.6.0] - 2026-03-14

### Added
- 📊 **Web UI Design System** — implemented dual-theme architecture and terminal-inspired atomic UI components
- 📊 **UI Components Refactoring** — integrated `clsx` and `tailwind-merge` for robust class composition across Web UI

- 🗑️ **History batch deletion** — Web UI now supports multi-selection and batch deletion of analysis history; added `POST /api/v1/history/batch-delete` endpoint and `ConfirmDialog` component.
- 🔐 **Auth settings API** — new `POST /api/v1/auth/settings` endpoint to enable or disable Web authentication at runtime and set the initial admin password when needed
- openclaw-Skill-Integrationsleitfaden — neu ist [docs/openclaw-skill-integration.md](openclaw-skill-integration.md), das erklärt, wie die DSA-API über einen openclaw Skill aufgerufen wird
- ⚙️ **LLM channel protocol/test UX** — `.env` and Web settings now share the same channel shape (`LLM_CHANNELS` + `LLM_<NAME>_PROTOCOL/BASE_URL/API_KEY/MODELS/ENABLED`); settings page adds per-channel connection testing, primary/fallback/vision model selection, and protocol-aware model prefixing
- 🤖 **Agent architecture Phase 0+1** — shared protocols (`AgentContext`, `AgentOpinion`, `StageResult`), extracted `run_agent_loop()` runner, `AGENT_ARCH` switch (`single`/`multi`), config registry entries
- 🔍 **Bot NL routing** — two-layer natural-language routing: cheap regex pre-filter (stock codes + finance keywords) → lightweight LLM intent parsing; controlled by `AGENT_NL_ROUTING=true`; supports multi-stock and strategy extraction
- 💬 **`/ask` multi-stock analysis** — comma or `vs` separated codes (max 5), parallel thread execution with 150s timeout (preserves partial results), Markdown comparison summary table at top
- 📋 **`/history` command** — per-user session isolation via `{platform}_{user_id}:{scope}` format (colon delimiter prevents prefix collision); lists both `/chat` and `/ask` sessions; view detail or clear
- 📊 **`/strategies` command** — lists available strategy YAML files grouped by category (Trend/Formation/Umkehr/Framework) with ✅/⬜ activation status
- 🔧 **Backtest summary tools** — `get_strategy_backtest_summary` and `get_stock_backtest_summary` registered as read-only Agent tools
- ⚙️ **Agent auto-detection** — `is_agent_available()` auto-detects from `LITELLM_MODEL`; explicit `AGENT_MODE=true/false` takes full precedence
- 🏗️ **Multi-Agent orchestrator (Phase 2)** — `AgentOrchestrator` with 4 modes (`quick`/`standard`/`full`/`strategy`); drop-in replacement for `AgentExecutor` via `AGENT_ARCH=multi`; `BaseAgent` ABC with tool subset filtering, cached data injection, and structured `AgentOpinion` output
- 🧩 **Specialised agents (Phase 2-4)** — `TechnicalAgent` (8 tools, trend/MA/MACD/volume/pattern analysis), `IntelAgent` (news & sentiment, risk flag propagation), `DecisionAgent` (synthesis into Decision Dashboard JSON), `RiskAgent` (7 risk categories, two-level severity with soft/hard override)
- 📈 **Strategy system (Phase 3)** — `StrategyAgent` (per-strategy evaluation from YAML skills), `StrategyRouter` (rule-based regime detection → strategy selection), `StrategyAggregator` (weighted consensus with backtest performance factor)
- 🔬 **Deep Research agent (Phase 5)** — `ResearchAgent` with 3-phase approach (decompose → research sub-questions → synthesise report); token budget tracking; new `/research` bot command with aliases (`/深研`, `/deepsearch`)
- 🧠 **Memory & calibration (Phase 6)** — `AgentMemory` with prediction accuracy tracking, confidence calibration (activates after minimum sample threshold), strategy auto-weighting based on historical win rate
- 📊 **Portfolio Agent (Phase 7)** — `PortfolioAgent` for multi-stock portfolio analysis (position sizing, sector concentration, correlation risk, cross-market linkage, rebalance suggestions)
- 🔔 **Event-driven alerts (Phase 7)** — `EventMonitor` with `PriceAlert`, `VolumeAlert`, `SentimentAlert` rules; async checking, callback notifications, serializable persistence
- ⚙️ **New config entries** — `AGENT_ORCHESTRATOR_MODE`, `AGENT_RISK_OVERRIDE`, `AGENT_DEEP_RESEARCH_BUDGET`, `AGENT_MEMORY_ENABLED`, `AGENT_STRATEGY_AUTOWEIGHT`, `AGENT_STRATEGY_ROUTING` — all registered in `config.py` + `config_registry.py` (WebUI-configurable)

### Changed
- 🔐 **Auth password state semantics** — stored password existence is now tracked independently from auth enablement; when auth is disabled, `/api/v1/auth/status` returns `passwordSet=false` while preserving the saved password for future re-enable
- 🔐 **Auth settings re-enable hardening** — re-enabling auth with a stored password now requires `currentPassword`, and failed session creation rolls back the auth toggle to avoid lockout
- ♻️ **AgentExecutor refactored** — `_run_loop` delegates to shared `runner.run_agent_loop()`; removed duplicated serialization/parsing/thinking-label code
- ♻️ **Unified agent switch** — Bot, API, and Pipeline all use `config.is_agent_available()` instead of divergent `config.agent_mode` checks
- 📖 **README.md** — expanded Bot commands section (ask/chat/strategies/history), added NL routing note, updated agent mode description
- 📖 **.env.example** — added `AGENT_ARCH` and `AGENT_NL_ROUTING` configuration documentation
- 🔌 **Analysis API async contract** — `POST /api/v1/analysis/analyze` now documents distinct async `202` payloads for single-stock vs batch requests, and `report_type=full` is treated consistently with the existing full-report behavior

### Fixed
- 🐛 **Analysis API blank-code guardrails** — `POST /api/v1/analysis/analyze` now drops whitespace-only entries before batch enqueue and returns `400` when no valid stock code remains
- 🐛 **Bare `/api` SPA fallback** — unknown API paths now return JSON `404` consistently for both `/api/...` and the exact `/api` path
- 🎮 **Discord channel env compatibility** — runtime now accepts legacy `DISCORD_CHANNEL_ID` as a fallback for `DISCORD_MAIN_CHANNEL_ID`, and the docs/examples now use the same variable name as the actual workflow/config implementation
- 🐛 **Session secret rotation on Windows** — use atomic replace so auth toggles invalidate existing sessions even when `.session_secret` already exists
- 🐛 **Auth toggle atomicity** — persist `ADMIN_AUTH_ENABLED` before rotating session secret; on rotation failure, roll back to the previous auth state
- 🔧 **LLM runtime selection guardrails** — im YAML-Modus überschreibt der Kanal-Editor nicht mehr `LITELLM_MODEL` / fallback / Vision; die Systemkonfigurationsvalidierung ergänzt eine Laufzeit-Quellprüfung, wenn alle Kanäle deaktiviert sind, und behebt, dass Protokoll-Alias-Modelle wie `vertexai/...` doppelt mit Präfixen versehen wurden
- 🐛 **Multi-stock `/ask` follow-up regressions** — portfolio overlay now shares the same timeout budget as the per-stock phase and is skipped on timeout instead of blocking the bot reply; `/history` now stores the readable per-stock summary instead of raw dashboard JSON; condensed multi-stock output now renders numeric `sniper_points` values
- 🐛 **Decision dashboard enum compatibility** — multi-agent `DecisionAgent` now keeps `decision_type` within the legacy `buy|hold|sell` contract and normalizes stray `strong_*` outputs before risk override, pipeline conversion, and downstream statistics/notification aggregation
- 🛟 **Multi-Agent partial-result fallback** — `IntelAgent` now caches parsed intel for downstream reuse, shared JSON parsing tolerates lightly malformed model output, and the orchestrator preserves/synthesizes a minimal dashboard on timeout or mid-pipeline parse failure instead of always collapsing to `50/Abwarten/Unbekannt`
- 🐛 **Shared LiteLLM routing restored** — bot NL intent parsing and `ResearchAgent` planning/synthesis now reuse the same LiteLLM adapter / Router / fallback / `api_base` injection path as the main Agent flow, so `LLM_CHANNELS` / `LITELLM_CONFIG` / OpenAI-compatible deployments behave consistently
- 🐛 **Bot chat session backward compatibility** — `/chat` now keeps using the legacy `{platform}_{user_id}` session id when old history already exists, and `/history` can still list / view / clear those pre-migration sessions alongside the new `{platform}_{user_id}:chat` format
- 🐛 **EventMonitor unsupported rule rejection** — config validation/runtime loading now reject or skip alert types the monitor cannot actually evaluate yet, so schedule mode no longer silently accepts permanent no-op rules
- 🐛 **P0-Stabilitätsfix für die Fundamentaldaten-Aggregation** (#614) — behebt die Sektorsemantik-Regression von `get_stock_info` (neu `belong_boards`, mit beibehaltenem `boards`-Kompatibilitätsalias), führt kompakte Rückgaben für Fundamentalkontext zur Token-Kontrolle ein, ergänzt maximale Eintrags-Eviction für den Fundamentaldaten-Cache und vervollständigt die ETF-Gesamtstatus-Aggregation sowie das Filtern von NaN-Sektorfeldern, mit fail-open und minimaler Invasivität.
- 🔧 **GitHub-Actions-Suchmaschinen-Umgebungsvariablen ergänzt** — der Workflow erhält neue Umgebungsvariablen-Mappings für `MINIMAX_API_KEYS`, `BRAVE_API_KEYS`, `SEARXNG_BASE_URLS`, damit GitHub-Actions-Nutzer die Suchdienste MiniMax, Brave und SearXNG konfigurieren können (v3.5.0 fügte zwar die Provider-Implementierung hinzu, aber die Workflow-Konfiguration fehlte)
- 🤖 **Multi-Agent runtime consistency** — `AGENT_MAX_STEPS` now propagates to each orchestrated sub-agent; added cooperative `AGENT_ORCHESTRATOR_TIMEOUT_S` budget to stop overlong pipelines before they cascade further
- 🔌 **Multi-Agent feature wiring** — `AGENT_RISK_OVERRIDE` now actively downgrades final dashboards on hard risk findings; `AGENT_MEMORY_ENABLED` now injects recent analysis memory + confidence calibration into specialised agents; multi-stock `/ask` now runs `PortfolioAgent` to add portfolio-level allocation and concentration guidance
- 🔔 **EventMonitor runtime wiring** — schedule mode can now load alert rules from `AGENT_EVENT_ALERT_RULES_JSON`, poll them at `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, and send triggered alerts through the existing notification service
- 🛠️ **Follow-up stability fixes** — multi-stock `/ask` now falls back to usable text output when dashboard JSON parsing fails; EventMonitor skips semantically invalid rules instead of aborting schedule startup; background alert polling now runs independently of the main scheduled analysis loop
- 🧪 **Multi-Agent regression coverage** — added orchestrator execution tests for `run()`, `chat()`, critical-stage failure, graceful degradation, and timeout handling
- 🧹 **PortfolioAgent cleanup** — `post_process()` now reuses shared JSON parsing and removed stale unused imports
- 🚦 **Bot async dispatch** — `CommandDispatcher` now exposes `dispatch_async()`; NL intent parsing and default command execution are offloaded from the event loop, DingTalk stream awaits async handlers directly, and Feishu stream processing is moved off the SDK callback thread
- 🌐 **Async webhook handler** — new `handle_webhook_async()` function in `bot/handler.py` for use from async contexts (e.g. FastAPI); calls `dispatch_async()` directly without thread bridging
- 🧵 **Feishu stream ThreadPoolExecutor** — replaced unbounded per-message `Thread` spawning with a capped `ThreadPoolExecutor(max_workers=8)` to prevent thread explosion under message bursts
- 🔒 **EventMonitor safety** — `_check_volume()` now safely handles `get_daily_data` returning `None` (no tuple-unpacking crash); `on_trigger` callbacks support both sync and async callables via `asyncio.to_thread`/`await`
- 🧹 **ResearchAgent dedup** — `_filtered_registry()` now delegates to `BaseAgent._filtered_registry()` instead of duplicating the filtering logic
- 🧹 **Bot trailing whitespace cleanup** — removed W291/W293 whitespace issues across `bot/handler.py`, `bot/dispatcher.py`, `bot/commands/base.py`, `bot/platforms/feishu_stream.py`, `bot/platforms/dingtalk_stream.py`
- 🐛 **Dispatcher `_parse_intent_via_llm` safety** — replaced fragile `'raw' in dir()` with `'raw' in locals()` for undefined-variable guard in `JSONDecodeError` handler
- 🐛 **Fallback-Vervollständigung, wenn die LLM die Chip-Struktur nicht ausfüllt** (#589) — wenn Modelle wie DeepSeek `chip_structure` nicht korrekt ausfüllen, wird automatisch mit den bereits abgerufenen Chip-Daten der Datenquelle vervollständigt, damit alle Modelle konsistent anzeigen; gilt für normale Analyse und Agent-Modus
- 🐛 **Historienberichte zeigen Sniper-Punkte als Originaltext** (#452) — die Historien-Detailseite zeigt jetzt vorrangig die ursprünglichen Strings aus `raw_result.dashboard.battle_plan.sniper_points`, damit die numerische `analysis_history`-Spalte Bereiche, Beschreibungstexte oder komplexe Punkte nicht zu einer einzelnen Zahl komprimiert; die ursprüngliche numerische Spalte bleibt als Rückfall erhalten
- 🐛 **Session prefix collision** — user ID `123` could see sessions of user `1234` via `startswith`; fixed with colon delimiter in session_id format
- 🐛 **NL pre-filter false positives** — `re.IGNORECASE` caused `[A-Z]{2,5}` to match common English words like "hello"; removed global flag, use inline `(?i:...)` only for English finance keywords
- 🐛 **Dotted ticker in strategy args** — `_get_strategy_args()` didn't recognize `BRK.B` as a stock code, leaving it in strategy text; now accepts `TICKER.CLASS` format
- ⏱️ **Fix für hängende lange efinance-Aufrufe** (#660) — alle efinance-API-Aufrufe werden mit `_ef_call_with_timeout()` umschlossen (Standard 30 Sekunden, konfigurierbar über `EFINANCE_CALL_TIMEOUT`); `executor.shutdown(wait=False)` stellt sicher, dass der Hauptthread nach einem Timeout nicht mehr blockiert wird, wodurch das 81-Minuten-Hängen vollständig beseitigt wird
- 🛡️ **Typsichere Inhaltsintegritätsprüfung** (#660) — `check_content_integrity()` behandelt `operation_advice` / `analysis_summary` mit nicht-String-Typen jetzt als fehlende Felder, um einen Absturz von `get_emoji()` durch `dict.strip()` downstream zu vermeiden
- 📄 **Berichtsspeicherung und Benachrichtigung entkoppelt** (#660) — `_save_local_report()` hängt nicht mehr vom `send_notification`-Flag ab; im `--no-notify`-Modus wird der lokale Bericht weiterhin normal gespeichert
- 🔄 **operation_advice-Dictionary-Normalisierung** (#660) — Pipeline und BacktestEngine mappen jetzt das von der LLM zurückgegebene `dict`-Format `operation_advice` über `decision_type` (case-insensitive) auf Standard-Strings, um Abstürze durch wechselnde Modellausgabeformate zu verhindern
- 🛡️ **None-Schutz für usage in runner.py** (#660) — bei `response.usage` gleich `None` wird kein `AttributeError` mehr geworfen, sondern auf 0 Token-Zählung zurückgefallen
- 📋 **Stille Fehler im Orchestrator als Log-Warnung** (#660) — Fehlschläge in den Phasen `IntelAgent` / `RiskAgent` werden jetzt als `WARNING` protokolliert statt still übersprungen, zur besseren Diagnose

### Notes
- ⚠️ **Multi-worker auth toggles** — runtime auth updates are process-local; multi-worker deployments must restart/roll workers to keep auth state consistent

## [3.5.0] - 2026-03-12

### Added
- 📊 **Web UI full report drawer** (Fixes #214) — history page adds "Full Report" button to display the complete Markdown analysis report in a side drawer; new `GET /api/v1/history/{record_id}/markdown` endpoint
- 📊 **LLM cost tracking** — all LLM calls (analysis, agent, market review) recorded in `llm_usage` table; new `GET /api/v1/usage/summary?period=today|month|all` endpoint returns aggregated token usage by call type and model
- 🔍 **SearXNG search provider** (Fixes #550) — quota-free self-hosted search fallback; priority: Bocha > Tavily > Brave > SerpAPI > MiniMax > SearXNG
- 🔍 **MiniMax web search provider** — `MiniMaxSearchProvider` with circuit breaker (3 failures → 300s cooldown) and dual time-filtering; configured via `MINIMAX_API_KEYS`
- 🤖 **Agent models discovery API** — `GET /api/v1/agent/models` returns available model deployments (primary/fallback/source/api_base) for Web UI model selector
- 🤖 **Agent chat export & send** (#495) — export conversation to .md file; send to configured notification channels; new `POST /api/v1/agent/chat/send`
- 🤖 **Agent background execution** (#495) — analysis continues when switching pages; badge notification on completion; auto-cancel in-progress stream on session switch
- 📝 **Report Engine P0** — Pydantic schema validation for LLM JSON; Jinja2 templates (markdown/wechat/brief) with legacy fallback; content integrity checks with retry; brief mode (`REPORT_TYPE=brief`); history signal comparison
- 📦 **Smart import** — multi-source import from image/CSV/Excel/clipboard; Vision LLM extracts code+name+confidence; name→code resolver (local map + pinyin + AkShare); confidence-tiered confirmation
- ⚙️ **GitHub Actions LiteLLM config** — workflow supports `LITELLM_CONFIG`/`LITELLM_CONFIG_YAML` for flexible AI provider configuration
- ⚙️ **Config engine refactor & system API** (#602) — unified config registry, validation and API exposure
- 📖 **LLM configuration guide** — new `docs/LLM_CONFIG_GUIDE.md` covering 3-tier config, quick start, Vision/Agent/troubleshooting

### Fixed
- 🐛 **analyze_trend always reports No historical data** (#600) — now fetches from DB/DataFetcher instead of broken `get_analysis_context`
- 🐛 **Chip structure fallback when LLM omits it** (#589) — auto-fills from data source chip data for consistent display across models
- 🐛 **History sniper points show raw text** (#452) — prioritizes original strings over compressed numeric values
- 🐛 **GitHub Actions ENABLE_CHIP_DISTRIBUTION configurable** (#617) — no longer hardcoded, supports vars/secrets override
- 🐛 **`.env` save preserves comments and blank lines** — Web settings no longer destroys `.env` formatting
- 🐛 **Agent model discovery fixes** — legacy mode includes LiteLLM-native providers; source detection aligned with runtime; fallback deployments no longer expanded per-key
- 🐛 **Stooq US stock previous close semantics** — no longer misuses open price as previous close
- 🐛 **Stock name prefetch regression** — prioritizes local `STOCK_NAME_MAP` before remote queries
- 🐛 **AkShare limit-up/down calculation** (#555) — fixed market analysis statistics
- 🐛 **AkShare Tencent source field index & ETF quote mapping** (#579)
- 🐛 **Pytdx stock name cache pagination** (#573) — prevents cache overflow
- 🐛 **PushPlus oversized report chunking** (#489) — auto-segments long content
- 🐛 **Agent chat cancel & switch** (#495) — cancel no longer misreports as failure; fast switch no longer overwrites stream state
- 🐛 **MiniMax search status in `/status` command** (#587)
- 🐛 **config_registry duplicate BOCHA_API_KEYS** — removed duplicate dict entry that silently overwrote config

### Changed
- 🔎 **Fetcher failure observability** — logs record start/success/failure with elapsed time, failover transitions; Efinance/Akshare include upstream endpoint and classified failure categories
- ♻️ **Data source resilience & cleanup** (#602) — fallback chain optimization
- ♻️ **Image extract API response extension** — new `items` field (code/name/confidence); `codes` preserved for backward compatibility
- ♻️ **Import parse error messages** — specific failure reasons for Excel/CSV; improved logging with file type and size

### Docs
- 📖 LLM config guide refactored for clarity (#583)
- 📖 `image-extract-prompt.md` with full prompt documentation
- 📖 AkShare fallback cache TTL documentation
## [3.4.10] - 2026-03-07

### Fixed
- 🐛 **EfinanceFetcher ETF OHLCV data** (#541, #527) — switch `_fetch_etf_data` from `ef.fund.get_quote_history` (NAV-only, no OHLCV, no `beg`/`end` params) to `ef.stock.get_quote_history`; ETFs now return proper open/high/low/close/volume/amount instead of zeros; remove obsolete NAV column mappings from `_normalize_data`
- 🐛 **tiktoken 0.12.0 `Unknown encoding cl100k_base`** (#537) — pin `tiktoken>=0.8.0,<0.12.0` in requirements.txt to avoid plugin-registration regression introduced in 0.12.0
- 🐛 **Web UI API error classification** (#540) — frontend no longer treats every HTTP 400 as the same "server/network" failure; now distinguishes Agent disabled / missing params / model-tool incompatibility / upstream LLM errors / local connection failures
- 🐛 **Erkennung fehlgeschlagener Beijing Stock Exchange-Codes** (#491, #533) — 6-stellige Codes, die mit 8/4/92 beginnen, werden jetzt korrekt als BSE erkannt; Datenquellen wie Tushare/Akshare/Yfinance unterstützen den .BJ- oder bj-Präfix; Baostock/Pytdx wechseln bei BSE-Codes explizit die Datenquelle; Fehlklassifizierung der Shanghai-B-Aktien 900xxx wird vermieden
- 🐛 **Parse-Fehler bei Sniper-Punkten** (#488, #532) — Felder wie idealer Kauf/zweiter Kauf extrahierten ohne das Zeichen „元“ fälschlich die Zahlen technischer Indikatoren in Klammern; jetzt wird zuerst der Inhalt nach der ersten Klammer abgeschnitten und dann extrahiert

### Added
- **Markdown-to-image for dashboard report** (#455, #535) — die Einzelaktien-Tagesbericht-Zusammenfassung unterstützt Markdown-zu-Bild-Pushes (Telegram, WeChat, Custom, Email), konsistent mit dem Verhalten des Markt-Reviews
- **markdown-to-file engine** (#455) — `MD2IMG_ENGINE=markdown-to-file` ist optional und unterstützt Emojis besser; erfordert `npm i -g markdown-to-file`
- **PREFETCH_REALTIME_QUOTES** (#455) — setzen auf `false` deaktiviert das Vorabrufen von Echtzeitkursen, um den marktweiten Abruf über efinance/akshare_em zu vermeiden
- **Stock name prefetch** (#455) — ruft Aktiennamen vor der Analyse vorab ab und reduziert Platzhalter wie „Aktie xxxxx“ im Bericht
- 📊 **Modell-Kennzeichnung in Analyseberichten** (#528, #534) — zeigt `model_used` (voller LLM-Modellname) im Meta des Analyseberichts, am Berichtsende und im Push-Inhalt; bei mehrrundigen Agent-Aufrufen wird das in jeder Runde tatsächlich verwendete Modell protokolliert und angezeigt (mit Fallback-Umschaltung)

### Changed
- **Enhanced markdown-to-image failure warning** (#455) — bei fehlgeschlagener Bildkonvertierung wird auf die konkrete Abhängigkeit hingewiesen (wkhtmltopdf oder m2f)
- **WeChat-only image routing optimization** (#455) — wenn nur WeCom-Bilder konfiguriert sind, wird für den vollständigen Bericht keine redundante Bildkonvertierung mehr durchgeführt, wodurch irreführende Fehler-Logs vermieden werden
- **Stock name prefetch lightweight mode** (#455) — die Namens-Vorabrufphase überspringt die Echtzeitkurs-Abfrage und reduziert zusätzliche Netzwerkkosten

## [3.4.9] - 2026-03-06

### Added
- 🧠 **Structured config validation** — `ConfigIssue` dataclass and `validate_structured()` with severity-aware logging; `CONFIG_VALIDATE_MODE=strict` aborts startup on errors
- 🖼️ **Vision model config** — `VISION_MODEL` and `VISION_PROVIDER_PRIORITY` for image stock extraction; provider fallback (Gemini → Anthropic → OpenAI → DeepSeek) when primary fails
- 🚀 **CLI init wizard** — `python -m dsa init` 3-Schritte-interaktiver Bootstrap (Modell → Datenquelle → Benachrichtigung), 9 Provider-Presets, standardmäßig inkrementelles Zusammenführen
- 🔧 **Multi-channel LLM support** with visual channel editor (#494)

### Changed
- ♻️ **Vision extraction** — migrated from gemini-3 hardcode to `litellm.completion()` with configurable model and provider fallback; `OPENAI_VISION_MODEL` deprecated in favor of `VISION_MODEL`
- ♻️ **Market analyzer** — uses `Analyzer.generate_text()` for LLM calls; fixes bypass and Anthropic `AttributeError` when using non-Router path
- ♻️ **Config validation refinements** — test_env output format syncs with `validate_structured` (severity-aware ✓/✗/⚠/·); Vision key warning when `VISION_MODEL` set but no provider API key; market_analyzer test covers `generate_market_review` fallback when `generate_text` returns None
- ⚙️ **Auto-tag workflow defaults to NO tag** — only tags when commit message explicitly contains `#patch`, `#minor`, or `#major`
- ♻️ **Formatter and notification refactor** (#516)

### Fixed
- 🐛 **STOCK_LIST not refreshed on scheduled runs** — `.env` or WebUI changes to `STOCK_LIST` now hot-reload before each scheduled analysis (#529)
- 🐛 **WebUI fails to load with MIME type error** — SPA fallback route now resolves correct `Content-Type` for JS/CSS files (#520)
- 🐛 **AstrBot sender docstring misplaced** — `import time` placed before docstring in `_send_astrbot`, causing it to become dead code
- 🐛 **Telegram Markdown link escaping** — `_convert_to_telegram_markdown` escaped `[]()` characters, breaking all Markdown links in reports
- 🐛 **Duplicate `discord_bot_status` field** in Config dataclass — second declaration silently shadowed the first
- 🧹 **Unused imports** — removed `shutil`/`subprocess` from `main.py`
- 🔧 **Config validation and Vision key check** (#525)

### Docs
- 📝 Clarified GitHub Actions non-trading-day manual run controls (`TRADING_DAY_CHECK_ENABLED` + `force_run`) for Issue #461 / PR #466

## [3.4.8] - 2026-03-02

### Fixed
- 🐛 **Desktop exe crashes on startup with `FileNotFoundError`** — PyInstaller build was missing litellm's JSON data files (e.g. `model_prices_and_context_window_backup.json`). Added `--collect-data litellm` to both Windows and macOS build scripts so the files are correctly bundled in the executable.

### CI
- 🔧 Cache Electron binaries on macOS CI runners to prevent intermittent EOF download failures when fetching `electron-vX.Y.Z-darwin-*.zip` from GitHub CDN
- 🔧 Fix macOS DMG `hdiutil Resource busy` error during desktop packaging

### Docs
- 📝 Clarify non-trading-day manual run controls for GitHub Actions (`TRADING_DAY_CHECK_ENABLED` + `force_run`) (#474)

## [3.4.7] - 2026-02-28

### Added
- 🧠 **CN/US Market Strategy Blueprint System** (#395) — market review prompt injects region-specific strategy blueprints with position sizing and risk trigger recommendations

### Fixed
- 🐛 **`TRADING_DAY_CHECK_ENABLED` env var and `--force-run` for GitHub Actions** (#466)
- 🐛 **Agent pipeline preserved resolved stock names** (#464) — placeholder names no longer leak into reports
- 🐛 **Code cleanup** (#462, Fixes #422)
- 🐛 **WebUI auto-build on startup** (#460)
- 🐛 **ARCH_ARGS unbound variable** (#458)
- 🐛 **Time zone inconsistency & right panel flash** (#439)

### Docs
- 📝 Clarify potential ambiguities in code (#343)
- 📝 ENABLE_EASTMONEY_PATCH guidance for Issue #453 (#456)
## [3.4.0] - 2026-02-27

### Added
- 📡 **LiteLLM Direct Integration + Multi API Key Support** (#454, Fixes #421 #428)
  - Removed native SDKs (google-generativeai, google-genai, anthropic); unified through `litellm>=1.80.10`
  - New config: `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`
  - Multi-key auto-builds LiteLLM Router (simple-shuffle) with 429 cooldown
  - **Breaking**: `.env` `GEMINI_MODEL` (no prefix) only for fallback; explicit config must include provider prefix

### Changed
- ♻️ **Notification Refactoring** (#435) — extracted 10 sender classes into `src/notification_sender/`

### Fixed
- 🐛 LLM NoneType crash, history API 422, sniper points extraction
- 🐛 Auto-build frontend on WebUI startup — `WEBUI_AUTO_BUILD` env var (default `true`)
- 🐛 Docker explicit project name (#448)
- 🐛 Bocha search SSL retry (#445, #446) — transient errors retry up to 3 times
- 🐛 Gemini google-genai SDK migration (Fixes #440, #444)
- 🐛 Mobile home page scrolling (Fixes #419, #433)
- 🐛 History list scroll reset (#431)
- 🐛 Settings save button false positive (fixes #417, #430)

## [3.3.22] - 2026-02-26

### Added
- 💬 **Chat History Persistence** (Fixes #400, #414) — `/chat` page survives refresh, sidebar session list
- 🎨 Project VI Assets — logo icon set, PSD, vector, banner (#425)
- 🚀 Desktop CI Auto-Release (#426) — Windows + macOS parallel builds

### Fixed
- 🐛 Agent Reasoning 400 & LiteLLM Proxy (fixes #409, #427)
- 🐛 Discord chunked sending (#413) — `DISCORD_MAX_WORDS` config
- 🐛 yfinance shared DataFrame (#412)
- 🐛 sniper_points parsing (#408)
- 🐛 Agent framework category missing (#406)
- 🐛 Date inconsistency & query id (fixes #322, #363)

## [3.3.12] - 2026-02-24

### Added
- 📈 **Intraday Realtime Technical Indicators** (Issue #234, #397) — MA calculated from realtime price, config: `ENABLE_REALTIME_TECHNICAL_INDICATORS`
- 🤖 **Agent Strategy Chat** (#367) — full ReAct pipeline, 11 YAML strategies, SSE streaming, multi-turn chat
- 📢 PushPlus Group Push — `PUSHPLUS_TOPIC` (#402)
- 📅 Trading Day Check (Issue #373, #375) — `TRADING_DAY_CHECK_ENABLED`, `--force-run`

### Fixed
- 🐛 DeepSeek reasoning mode (Issue #379, #386)
- 🐛 Agent news intel persistence (Fixes #396, #405)
- 🐛 Bare except clauses replaced with `except Exception` (#398)
- 🐛 UUID fallback for HTTP non-secure context (fixes #377, #381)
- 🐛 Docker DNS resolution (Fixes #372, #374)
- 🐛 Agent session/strategy bugs — multiple follow-up fixes for #367
- 🐛 yfinance parallel download data filtering

### Changed
- Market review strategy consistency — unified cn/us template
- Agent test assertions updated (`6 -> 11`)


## [3.2.11] - 2026-02-23

### Behobene Probleme (#patch)
- 🐛 **StockTrendAnalyzer wurde nie ausgeführt** (Issue #357)
  - Grundursache: `get_analysis_context` liefert nur 2 Tage Daten und kein `raw_data`; in der Pipeline ist `raw_data in context` stets False
  - Fix: Schritt 3 ruft direkt `get_data_range` auf, um 90 Kalendertage (ca. 60 Handelstage) historische Daten für die Trendanalyse zu beziehen
  - Verbesserung: bei fehlgeschlagener Trendanalyse wird mit `logger.warning(..., exc_info=True)` der vollständige Traceback protokolliert

## [3.2.10] - 2026-02-22

### Neue Funktionen
- ⚙️ Unterstützt die Konfigurationsoption `RUN_IMMEDIATELY`; bei `true` führt ein ausgelöster Zeitplan sofort eine Analyse aus, ohne auf den ersten Zeitplanpunkt zu warten

### Behobene Probleme
- 🐛 Behebt das Zentrierungsproblem der Web-UI-Seite
- 🐛 Behebt den 500-Fehler der Einstellungen

## [3.2.9] - 2026-02-22

### Behobene Probleme
- 🐛 **ETF-Analyse beachtet nur die Indexbewegung** (Issue #274)
  - US-/Hongkong-ETFs (z. B. VOO, QQQ) und A-Aktien-ETFs fließen nicht mehr in Risiken auf Fondsebene (Rechtsstreitigkeiten, Reputation usw.) ein
  - Suchdimensionen: ETF-/Index-spezifische risk_check-, earnings- und industry-Abfragen, um Nachrichten über den Fondsverwalter zu vermeiden
  - AI-Hinweis: Analysierestriktion für indexartige Basiswerte; `risk_alerts` dürfen keine Betriebsrisiken des Fondsverwalters enthalten

## [3.2.8] - 2026-02-21

### Behobene Probleme
- 🐛 **Groß-/Kleinschreibung von Aktiencodes in BOT und WEB UI vereinheitlicht** (Issue #355)
  - Aktiencodes, die über BOT `/analyze` und WEB UI Analysen auslösen, werden einheitlich in Großbuchstaben umgewandelt (z. B. `aapl` → `AAPL`)
  - Neu ist `canonical_stock_code()`, das an den Einstiegen BOT, API, Config, CLI und task_queue normalisiert
  - Historien- und Aufgaben-Deduplizierungslogik kann dieselbe Aktie korrekt erkennen (Groß-/Kleinschreibung hat keinen Einfluss mehr)

## [3.2.7] - 2026-02-20

### Neue Funktionen
- 🔐 **Passwortprüfung der Web-Seite** (Issue #320, #349)
  - `ADMIN_AUTH_ENABLED=true` aktiviert den Web-Login-Schutz
  - Beim ersten Zugriff wird das anfängliche Passwort in der Web-Seite gesetzt; unterstützt das Zurücksetzen über „Systemeinstellungen > Passwort ändern“ und CLI `python -m src.auth reset_password`

## [3.2.6] - 2026-02-20
### ⚠️ Destruktive Änderungen (Breaking Changes)

- **Änderung der Historien-API (Issue #322)**
  - Routenänderung: `GET /api/v1/history/{query_id}` → `GET /api/v1/history/{record_id}`
  - Parameteränderung: `query_id` (String) → `record_id` (Integer)
  - Nachrichten-Schnittstellenänderung: `GET /api/v1/history/{query_id}/news` → `GET /api/v1/history/{record_id}/news`
  - Grund: `query_id` kann bei Batch-Analysen doppelt auftreten und einen einzelnen Historieneintrag nicht eindeutig identifizieren. Die Datenbank-Primärschlüssel `id` wird verwendet, um die Eindeutigkeit sicherzustellen
  - Auswirkung: Alle Clients, die die alte Historien-Detail-API verwenden, müssen synchron aktualisiert werden

### Behobene Probleme
- Behebt widersprüchliche technische Indikatoren für US-Aktien (z. B. ADBE): Die adjusierten Daten von akshare für US-Aktien sind anormal; die US-Historiendatenquelle wird einheitlich auf YFinance umgestellt (Issue #311)
- 🐛 **Abfrage- und Anzeigeprobleme der Historieneinträge (Issue #322)**
  - Behebt die Datumsinkonsistenz in den Historienlisten-Abfragen: morgen wird als endDate verwendet, um sicherzustellen, dass alle heutigen Daten enthalten sind
  - Behebt das Berichtsauswahlproblem der Server-UI: Mehrere Einträge teilten sich dieselbe `query_id`, wodurch immer der erste angezeigt wurde. Jetzt wird `analysis_history.id` als eindeutige Kennung verwendet
  - Historien-Details, Nachrichten-Schnittstellen und Frontend-Komponenten sind vollständig auf `record_id` umgestellt
  - Neuer Hintergrund-Polling (alle 30 s) und stille Aktualisierung der Historienliste bei Seiten-Sichtbarkeitsänderungen sorgen dafür, dass das Frontend nach Abschluss CLI-gestarteter Analysen rechtzeitig synchronisiert; der `silent`-Modus vermeidet das Auslösen eines Ladezustands
- 🐛 **Echtzeitkurse und Tagesdaten für US-Indizes** (Issue #273)
  - Behebt, dass Echtzeitkurse für US-Indizes wie SPX, DJI, IXIC, NDX, VIX und RUT nicht abgerufen werden konnten
  - Neu ist das Modul `us_index_mapping`, das Nutzereingaben (z. B. SPX) auf Yahoo-Finance-Symbole (z. B. ^GSPC) abbildet
  - Tagesdaten von US-Indizes und US-Aktien werden direkt an YfinanceFetcher geroutet, um nicht unterstützte Datenquellen zu durchlaufen
  - Beseitigt die doppelte US-Aktien-Erkennungslogik und verwendet einheitlich die Funktion `is_us_stock_code()`

### Optimierungen
- 🎨 **Layout-Ausrichtung von Eingabezeile der Startseite und Market Sentiment optimiert**
  - Die linke Kante des Aktiencode-Eingabefelds ist linksbündig mit dem Glass-Card-Rahmen der Historie
  - Die rechte Kante des Analyseknopfs ist rechtsbündig mit dem äußeren Rahmen von Market Sentiment
  - Die Market-Sentiment-Karte wird nach unten gedehnt, um das Raster zu füllen, wodurch die Lücke zu STRATEGY POINTS beseitigt wird
  - Auf schmalen Bildschirmen füllt die Eingabezeile die volle Breite; das responsive Alignment bleibt konsistent

## [3.2.5] - 2026-02-19

### Neue Funktionen
- 🌍 **Optionale Regionen für den Markt-Review** (Issue #299)
  - Unterstützt die Umgebungsvariable `MARKET_REVIEW_REGION`: `cn` (A-Aktien), `us` (US-Aktien), `both` (beide)
  - Der us-Modus verwendet Indizes wie SPX/Nasdaq/Dow/VIX; der both-Modus kann A-Aktien und US-Aktien zugleich reviewen
  - Standard `cn`, rückwärtskompatibel

## [3.2.4] - 2026-02-18

### Behobene Probleme
- 🐛 **US-Datenquelle einheitlich auf YFinance umgestellt** (Issue #311)
  - Die adjusierten Daten von akshare für US-Aktien sind anormal; die US-Historiendatenquelle wird einheitlich auf YFinance umgestellt
  - Behebt widersprüchliche technische Indikatoren für US-Aktien wie ADBE

## [3.2.3] - 2026-02-18

### Behobene Probleme
- 🐛 **Fehlende Echtzeitdaten für S&P 500** (Issue #273)
  - Behebt, dass Echtzeitkurse für US-Indizes wie SPX, DJI, IXIC, NDX, VIX und RUT nicht abgerufen werden konnten
  - Neu ist das Modul `us_index_mapping`, das Nutzereingaben (z. B. SPX) auf Yahoo-Finance-Symbole (z. B. `^GSPC`) abbildet
  - Tagesdaten von US-Indizes und US-Aktien werden direkt an YfinanceFetcher geroutet, um nicht unterstützte Datenquellen zu durchlaufen

## [3.2.2] - 2026-02-16

### Neue Funktionen
- 📊 **PE-Kennzahl unterstützt** (Issue #296)
  - Das AI-System-Prompt erhält einen Fokus auf die PE-Bewertung
- 📰 **Nachrichten-Zeitnähe-Filter** (Issue #296)
  - `NEWS_MAX_AGE_DAYS`: maximale Nachrichten-Zeitnähe (Tage), Standard 3, um veraltete Informationen zu vermeiden
- 📈 **Bias-Erweiterung für starke Trendaktien** (Issue #296)
  - `BIAS_THRESHOLD`: Schwellwert für die Bias-Rate (%), Standard 5.0, konfigurierbar
  - Starke Trendaktien (Long-Anordnung und Trendstärke ≥70) weiten die Bias-Rate automatisch auf das 1,5-Fache

## [3.2.1] - 2026-02-16

### Neue Funktionen
- 🔧 **Konfigurierbarer Schalter für den Eastmoney-Schnittstellen-Patch**
  - Die Umgebungsvariable `EFINANCE_PATCH_ENABLED` schaltet den Eastmoney-Schnittstellen-Patch um (Standard `true`)
  - Ist der Patch nicht verfügbar, kann er degradierend deaktiviert werden, um den Hauptablauf nicht zu beeinträchtigen

## [3.2.0] - 2026-02-15

### Neue Funktionen
- 🔒 **CI-Gate vereinheitlicht (P0)**
  - Neu ist `scripts/ci_gate.sh` als einziger Einstieg des Backend-Gates
  - Das Haupt-CI wird in drei Phasen aufgeteilt: `backend-gate`, `docker-build`, `web-gate`
  - CI wird für alle PRs ausgelöst, damit Required Checks Merges nicht wegen fehlender Pfadfilter blockieren
  - `web-gate` unterstützt bedarfsweises Auslösen bei Frontend-Pfadänderungen
  - Neu ist der `network-smoke`-Workflow für Regressions nicht blockierender Netzwerkszenarien
- 📦 **Release-Pipeline konsolidiert (P0)**
  - `docker-publish` wird auf Tag-basierte Hauptauslösung umgestellt und erhält eine Pre-Release-Gate-Prüfung
  - Manuelle Releases erhalten einen `release_tag`-Input und strikte semver/changelog-Validierung
  - Vor dem Release wird ein Docker-Smoke-Test ergänzt (Import kritischer Module)
- 📝 **PR-Vorlage aktualisiert (P0)**
  - Pflichtfelder wie Hintergrund, Umfang, Validierungsbefehle und -ergebnisse, Rollback-Plan und Issue-Zuordnung werden ergänzt
- 🤖 **AI-Review-Abdeckung gestärkt (P0)**
  - `pr-review` wird in den Geltungsbereich `.github/workflows/**` aufgenommen
  - Neu ist der Schalter `AI_REVIEW_STRICT`, der AI-Review-Fehlschläge optional zu Blocker-Stufe aufwerten kann

## [3.1.13] - 2026-02-15

### Neue Funktionen
- 📊 **Nur Zusammenfassung der Analyseergebnisse** (Issue #262)
  - Die Umgebungsvariable `REPORT_SUMMARY_ONLY` unterstützt; bei `true` wird nur die Zusammenfassung gepusht, ohne Einzelaktien-Details
  - Standard `false`; bei mehreren Aktien für schnelles Überfliegen geeignet

## [3.1.12] - 2026-02-15

### Neue Funktionen
- 📧 **Zusammengeführter Push von Einzelaktien und Markt-Review** (Issue #190)
  - Die Umgebungsvariable `MERGE_EMAIL_NOTIFICATION` unterstützt; bei `true` werden Einzelaktien-Analyse und Markt-Review zu einem einzigen Push zusammengeführt
  - Standard `false`; reduziert die Anzahl der E-Mails und senkt das Risiko, als Spam erkannt zu werden

## [3.1.11] - 2026-02-15

### Neue Funktionen
- 🤖 **Anthropic-Claude-API unterstützt** (Issue #257)
  - Unterstützt `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_TEMPERATURE`, `ANTHROPIC_MAX_TOKENS`
  - AI-Analysepriorität: Gemini > Anthropic > OpenAI
- 📷 **Aktiencodes aus Bildern erkennen** (Issue #257)
  - Hochladen eines Watchlist-Screenshots; Aktiencodes werden automatisch über die Vision-LLM extrahiert
  - API: `POST /api/v1/stocks/extract-from-image`; unterstützt JPEG/PNG/WebP/GIF, maximal 5MB
  - Unterstützt die separate Konfiguration des Bilderkennungsmodells über `OPENAI_VISION_MODEL`
- ⚙️ **Manuelle Konfiguration der Tongdaxin-Datenquelle** (Issue #257)
  - Unterstützt die Konfiguration selbst gehosteter Tongdaxin-Server über `PYTDX_HOST`, `PYTDX_PORT` oder `PYTDX_SERVERS`

## [3.1.10] - 2026-02-15

### Neue Funktionen
- ⚙️ **Konfiguration für Sofortausführung** (Issue #332)
  - Unterstützt die Umgebungsvariable `RUN_IMMEDIATELY`; bei `true` führt der Zeitplan beim Start sofort eine Ausführung durch
- 🐛 Behebt Docker-Build-Probleme

## [3.1.9] - 2026-02-14

### Neue Funktionen
- 🔌 **Eastmoney-Schnittstellen-Patch-Mechanismus**
  - Neu ist `patch/eastmoney_patch.py`, das Änderungen der efinance-Upstream-Schnittstelle repariert
  - Beeinträchtigt den Normalbetrieb anderer Datenquellen nicht

## [3.1.8] - 2026-02-14

### Neue Funktionen
- 🔐 **Schalter für die Webhook-Zertifikatsprüfung** (Issue #265)
  - Die Umgebungsvariable `WEBHOOK_VERIFY_SSL` kann die HTTPS-Zertifikatsprüfung deaktivieren, um selbstsignierte Zertifikate zu unterstützen
  - Standardmäßig bleibt die Prüfung aktiv; ein Deaktivieren birgt ein MITM-Risiko und wird nur im vertrauenswürdigen Intranet empfohlen

## [3.1.7] - 2026-02-14

### Behobene Probleme
- 🐛 Behebt den Paket-Importfehler (package import error)

## [3.1.6] - 2026-02-13

### Behobene Probleme
- 🐛 Behebt die Inkonsistenz von `query_id` in `news_intel`

## [3.1.5] - 2026-02-13

### Neue Funktionen
- 📷 **Markdown-zu-Bild-Benachrichtigung** (Issue #289)
  - Die Konfiguration `MARKDOWN_TO_IMAGE_CHANNELS` unterstützt das Senden von Berichten im Bildformat an Telegram, WeCom, Custom-Webhook (Discord) und E-Mail
  - E-Mails verwenden Inline-Anhänge und verbessern die Kompatibilität mit Clients, die kein HTML unterstützen
  - Erfordert die Installation von `wkhtmltopdf` und `imgkit`

## [3.1.4] - 2026-02-12

### Neue Funktionen
- 📧 **Aktiengruppen an verschiedene E-Mail-Adressen senden** (Issue #268)
  - Die Konfiguration `STOCK_GROUP_N` + `EMAIL_GROUP_N` unterstützt; Berichte verschiedener Aktiengruppen werden an die jeweiligen E-Mail-Adressen gesendet
  - Der Markt-Review wird an alle konfigurierten E-Mail-Adressen gesendet

## [3.1.3] - 2026-02-12

### Behobene Probleme
- 🐛 Behebt den Fehler `[Errno 16] Device or resource busy` beim Ändern der Konfiguration über die Seite innerhalb von Docker

## [3.1.2] - 2026-02-11

### Behobene Probleme
- 🐛 Behebt Docker-Konsistenzprobleme und löst kritische Batch-Verarbeitungs- und Benachrichtigungs-Bugs

## [3.1.1] - 2026-02-11

### Änderungen
- ♻️ `API_HOST` → `WEBUI_HOST`: Docker-Compose-Konfiguration vereinheitlicht

## [3.1.0] - 2026-02-11

### Neue Funktionen
- 📊 **ETF-Unterstützung gestärkt und Codes normalisiert**
  - Vereinheitlicht die ETF-Code-Verarbeitungslogik aller Datenquellen
  - Neu ist `canonical_stock_code()`, das das Codeformat vereinheitlicht und korrektes Datenquellen-Routing sicherstellt

## [3.0.5] - 2026-02-08

### Behobene Probleme
- 🐛 Behebt die Inkonsistenz zwischen Signal-Emoji und Empfehlung (komposite Empfehlungen wie „Verkaufen/Abwarten“ wurden nicht korrekt zugeordnet)
- 🐛 Behebt das Markdown-Escaping-Problem von `*ST`-Aktiennamen in WeCom/Dashboard
- 🐛 Behebt den TypeError des Markt-Reviews, wenn `idx.amount` None ist
- 🐛 Behebt, dass die Analyse-API `report=None` zurückgibt, sowie die Typ-Inkonsistenz von ReportStrategy
- 🐛 Behebt den falschen Tushare-Rückgabetyp (dict → UnifiedRealtimeQuote) und die API-Endpunkt-Zuordnung

### Neue Funktionen
- 📊 Markt-Review-Berichte injizieren strukturierte Daten (Kursbewegungsstatistiken, Indextabellen, Sektor-Ranglisten)
- 🔍 TTL-Cache für Suchergebnisse (maximal 500 Einträge, FIFO-Eviction)
- 🔧 Bei vorhandenem Tushare-Token wird die Echtzeitkurs-Priorität automatisch injiziert
- 📰 Trunkierungslänge der Nachrichtenzusammenfassungen von 50 auf 200 Zeichen

### Optimierungen
- ⚡ Anfragen für ergänzende Kursfelder auf maximal 1 begrenzt, um nutzlose Requests zu reduzieren

## [3.0.4] - 2026-02-07

### Neue Funktionen
- 📈 **Backtest-Engine** (PR #269)
  - Neues Backtest-System auf Basis historischer Analyseaufzeichnungen, das Kennzahlen wie Rendite, Trefferquote und maximalen Drawdown bewertet
  - WebUI integriert die Anzeige von Backtest-Ergebnissen

## [3.0.3] - 2026-02-07

### Behobene Probleme
- 🐛 Behebt den Datenparse-Fehler der Sniper-Punkte (PR #271)

## [3.0.2] - 2026-02-06

### Neue Funktionen
- ✉️ Konfigurierbarer E-Mail-Absendername (PR #272)
- 🌐 Ausländische Aktien unterstützen die Suche mit englischen Schlüsselwörtern

## [3.0.1] - 2026-02-06

### Behobene Probleme
- 🐛 Behebt das Abrufen von ETF-Echtzeitkursen, den Marktdaten-Rückfall und das Chunking von WeCom-Nachrichten
- 🔧 CI-Ablauf vereinfacht

## [3.0.0] - 2026-02-06

### Entfernt
- 🗑️ **Alte WebUI entfernt**
  - Die auf `http.server.ThreadingHTTPServer` basierende alte WebUI (Paket `web/`) wird gelöscht
  - Die Funktionen der alten WebUI sind vollständig durch FastAPI (`api/`) + React-Frontend ersetzt
  - Die Befehlszeilenparameter `--webui` / `--webui-only` sind als veraltet markiert und werden automatisch auf `--serve` / `--serve-only` umgeleitet
  - Die Umgebungsvariablen `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` bleiben kompatibel und werden automatisch an den FastAPI-Dienst weitergeleitet
  - `webui.py` bleibt als Kompatibilitätseinstieg erhalten und ruft beim Start direkt das FastAPI-Backend auf
  - In Docker Compose wird die Service-Definition `webui` entfernt; einheitlich wird der Dienst `server` verwendet

### Änderungen
- ♻️ **Service-Schicht umgebaut**
  - Der asynchrone Aufgabendienst aus `web/services.py` wird nach `src/services/task_service.py` verschoben
  - Die Bot-Analysebefehle (`bot/commands/analyze.py`) verwenden jetzt `src.services.task_service`
  - Die Docker-Umgebungsvariablen `WEBUI_HOST`/`WEBUI_PORT` werden in `API_HOST`/`API_PORT` umbenannt (alte Namen bleiben kompatibel)

## [2.3.0] - 2026-02-01

### Neue Funktionen
- 🇺🇸 **US-Aktien-Unterstützung gestärkt** (Issue #153)
  - Abruf von US-Historiendaten auf Basis von Akshare (`ak.stock_us_daily()`) implementiert
  - Abruf von US-Echtzeitkursen auf Basis von Yfinance implementiert (Prioritätsstrategie)
  - Filterung und schnelle Degradierung von US-Codes für nicht unterstützende Datenquellen (Tushare/Baostock/Pytdx/Efinance) ergänzt

### Behobene Probleme
- 🐛 Behebt, dass US-Codes wie AMD fälschlich als A-Aktien erkannt wurden (Issue #153)

## [2.2.5] - 2026-02-01

### Neue Funktionen
- 🤖 **AstrBot-Nachrichten-Push** (PR #217)
  - Neuer AstrBot-Benachrichtigungskanal mit Push an QQ und WeChat
  - Unterstützt die HMAC-SHA256-Signaturprüfung zur Sicherung der Kommunikation
  - Konfiguriert über `ASTRBOT_URL` und `ASTRBOT_TOKEN`

## [2.2.4] - 2026-02-01

### Neue Funktionen
- ⚙️ **Konfigurierbare Datenquellen-Priorität** (PR #215)
  - Unterstützt das dynamische Anpassen der Datenquellen-Priorität über Umgebungsvariablen (z. B. `YFINANCE_PRIORITY=0`)
  - Eine bestimmte Datenquelle (z. B. Yahoo Finance) kann ohne Codeänderungen bevorzugt werden

## [2.2.3] - 2026-01-31

### Behobene Probleme
- 📦 requirements.txt aktualisiert und die Abhängigkeit `lxml_html_clean` ergänzt, um Kompatibilitätsprobleme zu lösen

## [2.2.2] - 2026-01-31

### Behobene Probleme
- 🐛 Behebt das Groß-/Kleinschreibungsproblem der Proxy-Konfiguration (fixes #211)

## [2.2.1] - 2026-01-31

### Behobene Probleme
- 🐛 **YFinance-Kompatibilitätsfix** (PR #210, fixes #209)
  - Behebt den Datenparse-Fehler, der durch MultiIndex-Spaltennamen in neueren yfinance-Versionen verursacht wird

## [2.2.0] - 2026-01-31

### Neue Funktionen
- 🔄 **Multi-Quellen-Fallback-Strategie gestärkt**
  - Robustere Fallback-Mechanik für den Datenabruf implementiert (feat: multi-source fallback strategy)
  - Automatische Umschaltlogik bei Datenquellen-Ausfällen optimiert

### Behobene Probleme
- 🐛 Behebt, dass nach dem Lauf des Analyzers die getrackten Aktien nicht mehr über den stock_list-Inhalt der .env-Datei angepasst werden konnten

## [2.1.14] - 2026-01-31

### Dokumentation
- 📝 README aktualisiert und auto-tag-Regeln optimiert

## [2.1.13] - 2026-01-31

### Behobene Probleme
- 🐛 **Tushare-Priorität und Echtzeitkurse** (Fixed #185)
  - Behebt das Problem der Prioritätseinstellung der Tushare-Datenquelle
  - Behebt das Abrufen von Tushare-Echtzeitkursen

## [2.1.12] - 2026-01-30

### Behobene Probleme
- 🌐 Behebt das Groß-/Kleinschreibungsproblem der Proxy-Konfiguration in bestimmten Fällen
- 🌐 Behebt die Logik zum Deaktivieren des Proxys in lokalen Umgebungen
## [2.1.11] - 2026-01-30

### Optimierungen
- 🚀 **Feishu-Nachrichtenfluss optimiert** (PR #192)
  - Verarbeitung der Nachrichtentypen im Feishu-Stream-Modus optimiert
  - Der Stream-Nachrichtenmodus ist standardmäßig deaktiviert, um Laufzeitfehler bei falscher Konfiguration zu vermeiden

## [2.1.10] - 2026-01-30

### Zusammengeführt
- 📦 Beitrag von PR #154 zusammengeführt

## [2.1.9] - 2026-01-30

### Neue Funktionen
- 💬 **Unterstützung für WeChat-Textnachrichten** (PR #137)
  - Unterstützung für reine Textnachrichtentypen beim WeChat-Push ergänzt
  - Konfigurationsoption `WECHAT_MSG_TYPE` hinzugefügt

## [2.1.8] - 2026-01-30

### Behobene Probleme
- 🐛 Falsche Anzeige des API-Anbieters in den Logs korrigiert (PR #197)

## [2.1.7] - 2026-01-30

### Behobene Probleme
- 🌐 Proxy-Einstellungen für lokale Umgebungen deaktiviert, um Netzwerkverbindungsprobleme zu vermeiden

## [2.1.6] - 2026-01-29

### Neue Funktionen
- 📡 **Pytdx-Datenquelle (Priorität 2)**
  - Neue Tongdaxin-Datenquelle, kostenlos und ohne Registrierung
  - Automatische Umschaltung zwischen mehreren Servern
  - Unterstützt Echtzeitkurse und historische Daten
- 🏷️ **Mehrquellen-Aktiennamenauflösung**
  - `get_stock_name()`-Methode zu DataFetcherManager hinzugefügt
  - Neue `batch_get_stock_names()`-Massenabfrage
  - Automatischer Fallback zwischen mehreren Datenquellen
  - Tushare und Baostock um Aktiennamen-/Listenmethoden ergänzt
- 🔍 **Verbesserter Such-Fallback**
  - Neue `search_stock_price_fallback()`-Funktion für den Fall, dass alle Datenquellen ausfallen
  - Neue Suchdimensionen: Marktanalyse, Branchenanalyse
  - Maximale Suchanzahl von 3 auf 5 erhöht
  - Suchresultat-Format verbessert (4 Ergebnisse pro Dimension)

### Verbesserungen
- Suchabfragevorlagen aktualisiert, um die Relevanz zu erhöhen
- Ausgabestruktur von `format_intel_report()` verbessert

## [2.1.5] - 2026-01-29

### Neue Funktionen
- 📡 Neue Pytdx-Datenquelle und Mehrquellen-Aktiennamenauflösung hinzugefügt

## [2.1.4] - 2026-01-29

### Dokumentation
- 📝 Sponsoreninformationen aktualisiert

## [2.1.3] - 2026-01-28

### Dokumentation
- 📝 README-Layout umgebaut
- 🌐 Neue traditionelle chinesische Übersetzung (README_CHT.md)

### Behobene Probleme
- 🐛 Problem behoben, dass in der WebUI keine US-Aktiencodes eingegeben werden konnten
  - Eingabefeld-Logik geändert, sodass alle Buchstaben in Großbuchstaben umgewandelt werden
  - Eingabe von `.` unterstützt (z. B. `BRK.B`)

## [2.1.2] - 2026-01-27

### Behobene Probleme
- 🐛 Fehler beim Push der Einzelaktien-Analyse und Problem mit dem Berichtspfad behoben (fixes #166)
- 🐛 CR-Fehler korrigiert, sodass die maximale Byte-Größe der WeChat-Nachrichten wirksam wird

## [2.1.1] - 2026-01-26

### Neue Funktionen
- 🔧 GitHub-Actions-Auto-Tag-Workflow hinzugefügt
- 📡 yfinance-Fallback-Datenquelle und Warnung bei fehlenden Daten hinzugefügt

### Behobene Probleme
- 🐳 docker-compose-Pfade und Dokumentationsbefehle korrigiert
- 🐳 Dockerfile um das Kopieren des src-Ordners ergänzt (fixes #145)

## [2.1.0] - 2026-01-25

### Neue Funktionen
- 🇺🇸 **US-Aktien-Analyse unterstützt**
  - Direkte Eingabe von US-Aktiencodes unterstützt (z. B. `AAPL`, `TSLA`)
  - YFinance als Datenquelle für US-Aktien verwendet
- 📈 **MACD- und RSI-Technische Indikatoren**
  - MACD: Trendbestätigung, Goldenes-Kreuz/Todeskreuz-Signale (Goldenes Kreuz über der Nulllinie ⭐, Goldenes Kreuz ✅, Todeskreuz ❌)
  - RSI: Überkauft-/Überverkauft-Beurteilung (Überverkauft ⭐, stark ✅, überkauft ⚠️)
  - Indikatorsignale fließen in das Gesamtbewertungssystem ein
- 🎮 **Discord-Push-Unterstützung** (PR #124, #125, #144)
  - Unterstützt Discord-Webhook- und Bot-API-Varianten
  - Konfiguration über `DISCORD_WEBHOOK_URL` oder `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID`
- 🤖 **Bot-Befehlsinteraktion**
  - DingTalk-Bot unterstützt das Auslösen einer Analyse über den Befehl `/分析 股票代码`
  - Unterstützt den Stream-Langverbindungsmodus
- 🌡️ **AI-Temperaturparameter konfigurierbar** (PR #142)
  - Benutzerdefinierte Temperaturparameter für AI-Modelle unterstützt
- 🐳 **Zeabur-Deployment-Unterstützung**
  - Zeabur-Image-Deployment-Workflow hinzugefügt
  - Unterstützt Commit-Hash- und latest-Doppeltags

### Umgebaut
- 🏗️ **Projektstruktur optimiert**
  - Kerncode nach `src/` verschoben, Wurzelverzeichnis aufgeräumt
  - Dokumente nach `docs/` verschoben
  - Docker-Konfiguration nach `docker/` verschoben
  - Alle Importpfade korrigiert, Abwärtskompatibilität beibehalten
- 🔄 **Datenquellen-Architektur aktualisiert**
  - Neuer Datenquellen-Circuit-Breaker: automatische Umschaltung bei wiederholten Fehlern einer Quelle
  - Echtzeitkurs-Cache optimiert, Massenvorabruf reduziert API-Aufrufe
  - Intelligenter Netzwerk-Proxy-Split: Inlands-Schnittstellen automatisch direkt verbunden
- 🤖 Discord-Roboter zur Plattform-Adapter-Architektur umgebaut

### Behobene Probleme
- 🌐 **Netzwerkstabilität erhöht**
  - Proxy-Konfiguration automatisch erkannt, Inlands-Kurs-Schnittstellen zwangsweise direkt verbunden
  - Gelegentlichen `ProtocolError` von EfinanceFetcher behoben
  - Erfassung und Wiederholungsmechanismus für zugrunde liegende Netzwerkfehler ergänzt
- 📧 **E-Mail-Rendering optimiert**
  - Problem der nicht gerenderten Tabellen in E-Mails behoben (#134)
  - E-Mail-Layout optimiert, kompakter und schöner
- 📢 **WeCom-Push repariert**
  - Problem des unvollständigen Markt-Review-Pushs behoben
  - Nachrichtenaufteilung erweitert, mehr Titelformate unterstützt
  - Batch-Sendeintervalle erhöht, um Limitierungen und Nachrichtenverlust zu vermeiden
- 👷 **CI/CD-Fixes**
  - Fehler bei Pfadreferenzen in GitHub Actions korrigiert

## [2.0.0] - 2026-01-24

### Neue Funktionen
- 🇺🇸 **US-Aktien-Analyse unterstützt**
  - Direkte Eingabe von US-Aktiencodes unterstützt (z. B. `AAPL`, `TSLA`)
  - YFinance als Datenquelle für US-Aktien verwendet
- 🤖 **Bot-Befehlsinteraktion** (PR #113)
  - DingTalk-Bot unterstützt das Auslösen einer Analyse über den Befehl `/分析 股票代码`
  - Unterstützt den Stream-Langverbindungsmodus
  - Unterstützt die Auswahl von Kurzbericht oder Vollbericht
- 🎮 **Discord-Push-Unterstützung** (PR #124)
  - Unterstützt Discord-Webhook-Push
  - Discord-Umgebungsvariablen zum Workflow hinzugefügt

### Behobene Probleme
- 🐳 Behebt, dass die WebUI in Docker an 0.0.0.0 bindet (fixed #118)
- 🔔 Feishu-Langverbindungsbenachrichtigungsproblem behoben
- 🐛 Fehler `analysis_delay` nicht definiert behoben
- 🔧 config.py erkennt beim Start die Benachrichtigungskanäle und behebt, dass bei bereits konfigurierten benutzerdefinierten Kanälen dennoch eine Fehlermeldung erscheint

### Verbesserungen
- 🔧 Tushare-Prioritätslogik optimiert, Kapselung verbessert
- 🔧 Problem behoben, dass Tushare trotz erhöhter Priorität weiterhin hinter Efinance eingestuft wurde
- ⚙️ Bei Konfiguration von `TUSHARE_TOKEN` wird die Tushare-Datenquellen-Priorität automatisch erhöht
- ⚙️ 4 User-Feedback-Issues umgesetzt (#112, #128, #38, #119)

## [1.6.0] - 2026-01-19

### Neue Funktionen
- 🖥️ WebUI-Verwaltungsoberfläche und API-Unterstützung (PR #72)
  - Neue Web-Architektur: Schichtenaufbau (Server/Router/Handler/Service)
  - Kern-APIs: `/analysis` (Analyse auslösen), `/tasks` (Fortschritt abfragen), `/health` (Health-Check)
  - Interaktionsoberfläche: Codes direkt auf der Seite eingeben und Analyse auslösen, Fortschritt in Echtzeit anzeigen
  - Laufmodus: neuer `--webui-only`-Modus, startet nur den Web-Dienst
  - Löst die Kernanforderung von [#70](https://github.com/ZhuLinsen/daily_stock_analysis/issues/70) (Schnittstelle zum Auslösen von Analysen)
- ⚙️ Erhöhte Flexibilität der GitHub-Actions-Konfiguration ([#79](https://github.com/ZhuLinsen/daily_stock_analysis/issues/79))
  - Unterstützt das Lesen nicht sensibler Konfiguration aus Repository Variables (z. B. STOCK_LIST, GEMINI_MODEL)
  - Abwärtskompatibilität mit Secrets beibehalten

### Behobene Probleme
- 🐛 Problem der abgeschnittenen WeCom-/Feishu-Berichte behoben ([#73](https://github.com/ZhuLinsen/daily_stock_analysis/issues/73))
  - Unnötige Längen-Hartabschneidung in notification.py entfernt
  - Verlässt sich auf den zugrunde liegenden automatischen Chunking-Mechanismus für lange Nachrichten
- 🐛 Fehlende GitHub-Workflow-Umgebungsvariablen behoben ([#80](https://github.com/ZhuLinsen/daily_stock_analysis/issues/80))
  - Problem behoben, dass `CUSTOM_WEBHOOK_BEARER_TOKEN` nicht korrekt an den Runner übergeben wurde

## [1.5.0] - 2026-01-17

### Neue Funktionen
- 📲 Einzelaktien-Push-Modus ([#55](https://github.com/ZhuLinsen/daily_stock_analysis/issues/55))
  - Nach jeder analysierten Aktie sofort pushen, ohne auf das Ende aller Analysen zu warten
  - Befehlszeilenargument: `--single-notify`
  - Umgebungsvariable: `SINGLE_STOCK_NOTIFY=true`
- 🔐 Benutzerdefinierte Webhook-Bearer-Token-Authentifizierung ([#51](https://github.com/ZhuLinsen/daily_stock_analysis/issues/51))
  - Unterstützt Webhook-Endpunkte, die eine Token-Authentifizierung erfordern
  - Umgebungsvariable: `CUSTOM_WEBHOOK_BEARER_TOKEN`

## [1.4.0] - 2026-01-17

### Neue Funktionen
- 📱 Pushover-Push unterstützt (PR #26)
  - Unterstützt iOS/Android-geräteübergreifenden Push
  - Konfiguration über `PUSHOVER_USER_KEY` und `PUSHOVER_API_TOKEN`
- 🔍 Bocha-Such-API-Integration (PR #27)
  - Chinesische Suche optimiert, unterstützt AI-Zusammenfassungen
  - Konfiguration über `BOCHA_API_KEYS`
- 📊 Efinance-Datenquellen-Unterstützung (PR #59)
  - efinance als Datenquellenoption hinzugefügt
- 🇭🇰 Hongkong-Aktien-Unterstützung (PR #17)
  - Unterstützt 5-stellige Codes oder HK-Präfix (z. B. `hk00700`, `hk1810`)

### Behobene Probleme
- 🔧 Feishu-Markdown-Rendering optimiert (PR #34)
  - Rendering-Probleme mit interaktiven Karten und Formatierern behoben
- ♻️ Hot-Reload der Aktienliste (PR #42 Fix)
  - `STOCK_LIST`-Konfiguration wird vor der Analyse automatisch neu geladen
- 🐛 Behandlung des 20-KB-Limits des DingTalk-Webhooks
  - Lange Nachrichten werden automatisch in Blöcken gesendet, um Abschneiden zu vermeiden
- 🔄 AkShare-API-Wiederholungsmechanismus verstärkt
  - Fehlercache hinzugefügt, um wiederholte Anfragen an fehlgeschlagene Schnittstellen zu vermeiden

### Verbesserungen
- 📝 README vereinfacht und optimiert
  - Erweiterte Konfiguration nach `docs/full-guide.md` verschoben


## [1.3.0] - 2026-01-12

### Neue Funktionen
- 🔗 Benutzerdefinierte Webhook-Unterstützung
  - Unterstützt beliebige Webhook-Endpunkte mit POST-JSON
  - Erkennt automatisch gängige Service-Formate wie DingTalk, Discord, Slack, Bark
  - Unterstützt die Konfiguration mehrerer Webhooks (durch Komma getrennt)
  - Konfiguration über die Umgebungsvariable `CUSTOM_WEBHOOK_URLS`

### Behobene Probleme
- 📝 WeCom-Langnachrichten in Batches senden
  - Behebt das Problem, dass bei zu vielen Watchlist-Aktien der Inhalt das 4096-Zeichen-Limit überschreitet und der Push fehlschlägt
  - Intelligent nach Aktien-Analyseblöcken aufgeteilt, mit Paginierungsmarkierungen pro Batch (z. B. 1/3, 2/3)
  - Batch-Intervall von 1 Sekunde, um Frequenzbegrenzungen zu vermeiden

## [1.2.0] - 2026-01-11

### Neue Funktionen
- 📢 Mehrkanal-Push-Unterstützung
  - WeCom-Webhook
  - Feishu-Webhook (neu)
  - E-Mail-SMTP (neu)
  - Automatische Erkennung des Kanaltyps, einfachere Konfiguration

### Verbesserungen
- Einheitliche Verwendung der `NOTIFICATION_URL`-Konfiguration, kompatibel mit altem `WECHAT_WEBHOOK_URL`
- E-Mail unterstützt Markdown-zu-HTML-Rendering

## [1.1.0] - 2026-01-11

### Neue Funktionen
- 🤖 OpenAI-kompatible API-Unterstützung
  - Unterstützt DeepSeek, Qwen, Moonshot, Zhipu GLM usw.
  - Gemini- oder OpenAI-Format, eines von beiden
  - Automatischer Degradations-Wiederholungsmechanismus

## [1.0.0] - 2026-01-10

### Neue Funktionen
- 🎯 AI-Entscheidungs-Dashboard-Analyse
  - Kernaussage in einem Satz
  - Präzise Kauf-/Stop-Loss-/Ziel-Punkte
  - Checkliste (✅⚠️❌)
  - Positionsempfehlungen nach Situation (ohne Position vs. mit Position)
- 📊 Markt-Review-Funktion
  - Kursverläufe der Hauptindizes
  - Auf-/Abwärts-Statistiken
  - Sektor-Gewinner-/Verlierer-Rangliste
  - AI-generierter Review-Bericht
- 🔍 Mehrdatenquellen-Unterstützung
  - AkShare (Hauptdatenquelle, kostenlos)
  - Tushare Pro
  - Baostock
  - YFinance
- 📰 Nachrichten-Suchdienst
  - Tavily-API
  - SerpAPI
- 💬 WeCom-Roboter-Push
- ⏰ Zeitplan-Task-Scheduler
- 🐳 Docker-Deployment-Unterstützung
- 🚀 GitHub-Actions-Bereitstellung zu null Kosten

### Technische Eigenschaften
- Gemini-AI-Modell (gemini-3-flash-preview)
- 429-Rate-Limit-Autowiederholung + Modellumschaltung
- Verzögerung zwischen Anfragen zur Vermeidung von Sperren
- Multi-API-Key-Lastverteilung
- SQLite-lokale Datenspeicherung

---

[Unreleased]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.28.0...HEAD
[3.28.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.27.0...v3.28.0
[3.27.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.26.1...v3.27.0
[3.26.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.25.0...v3.26.1
[3.25.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.1...v3.25.0
[3.24.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.0...v3.24.1
[3.24.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.23.0...v3.24.0
[3.23.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.22.0...v3.23.0
[3.22.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.1...v3.22.0
[3.21.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.0...v3.21.1
[3.21.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.20.0...v3.21.0
[3.20.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.19.0...v3.20.0
[3.19.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.18.0...v3.19.0
[3.18.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.1...v3.18.0
[3.17.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.0...v3.17.1
[3.17.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.16.0...v3.17.0
[3.16.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.15.0...v3.16.0
[3.15.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.2...v3.15.0
[3.14.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.12.0...v3.13.0
[3.12.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.11.0...v3.12.0
[3.11.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.1...v3.11.0
[3.10.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.0...v3.10.1
[3.10.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.9.0...v3.10.0
[3.9.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.10...v3.5.0
[3.4.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.9...v3.4.10
[3.4.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.8...v3.4.9
[3.4.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.7...v3.4.8
[3.4.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.0...v3.4.7
[3.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.22...v3.4.0
[3.3.22]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.12...v3.3.22
[3.3.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.11...v3.3.12
[3.2.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.10...v3.2.11
[2.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.5...v2.3.0
[2.2.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.4...v2.2.5
[2.2.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.14...v2.2.0
[2.1.14]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.13...v2.1.14
[2.1.13]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.12...v2.1.13
[2.1.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.11...v2.1.12
[2.1.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.9...v2.1.10
[2.1.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.8...v2.1.9
[2.1.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.7...v2.1.8
[2.1.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.6...v2.1.7
[2.1.6]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.5...v2.1.6
[2.1.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.6.0...v2.0.0
[1.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v1.0.0
