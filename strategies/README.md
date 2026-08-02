# Verzeichnis für Handelsstrategien / Trading Strategies

Dieses Verzeichnis enthält **natürlichsprachliche Handelsstrategie-Dateien** (YAML-Format). Beim Systemstart werden automatisch alle `.yaml`-Dateien in diesem Verzeichnis geladen.

Gegenüber Nutzern und Dokumentation bezeichnen wir diese Fähigkeiten weiterhin als „Strategie"; in Code, Konfiguration und API-Feldern werden sie einheitlich `skill` genannt. Du kannst das als „wiederverwendbares Strategie-Fähigkeitspaket" verstehen.

## Wie du eine benutzerdefinierte Strategie schreibst (Strategy Skill)

Erstelle einfach eine `.yaml`-Datei und beschreibe deine Handelsstrategie auf Chinesisch (oder einer beliebigen Sprache). **Es ist kein Code erforderlich.**

### Minimalvorlage

```yaml
name: my_strategy          # Eindeutige Kennung (Englisch, mit Unterstrichen verbunden)
display_name: 我的策略      # Anzeigename (Chinesisch)
description: Kurze Beschreibung des Strategieverwendungszwecks

instructions: |
  Deine Strategiebeschreibung...
  Schreibe in natürlicher Sprache Kriterien für die Beurteilung, Einstiegsbedingungen, Ausstiegsbedingungen usw.
  Du kannst Tool-Namen (z. B. get_daily_history, analyze_trend) angeben, um der KI zu zeigen, welche Daten sie verwenden soll.
```

### Vollständige Vorlage

```yaml
name: my_strategy
display_name: 我的策略
description: Kurze Beschreibung des Marktszenarios, für das die Strategie geeignet ist

# Strategieklassifikation: trend (Trend), pattern (Formation), reversal (Umkehr), framework (Framework)
category: trend

# Zugehörige Kern-Handelsidee-Nummern (1-7), optional
core_rules: [1, 2]

# Liste der von der Strategie benötigten Tools, optional
# Verfügbare Tools: get_daily_history, analyze_trend, get_realtime_quote,
#                  get_sector_rankings, search_stock_news, get_stock_info
required_tools:
  - get_daily_history
  - analyze_trend

# Optionale Aliase (für die natürliche Sprachskill-Auswahl wie /ask usw.)
aliases: [我的战法, 我的模型]

# Die folgenden Metadaten steuern das Standardverhalten (optional)
# default_active: Ob sie zum standardmäßig aktivierten Skill-Set gehört
# default_router: Ob sie zum Router-Fallback-Skill-Set gehört
# default_priority: Standard-Anzeige-/Sortierpriorität, kleinere Werte weiter vorne
# market_regimes: Marktzustands-Labels, für die dieser Skill bevorzugt geeignet ist
default_active: true
default_router: false
default_priority: 100
market_regimes: [trending_up]

# Detaillierte Strategiebeschreibung (natürliche Sprache, unterstützt Markdown-Format)
instructions: |
  **Name meiner Strategie**

  Beurteilungskriterien:

  1. **Bedingung eins**:
     - Verwende `analyze_trend`, um die Gleitende-Mittelwert-Anordnung zu prüfen.
     - Beschreibe die Trendmerkmale, die du erwartest...

  2. **Bedingung zwei**:
     - Beschreibe die Volumenanforderungen...

  Score-Anpassung:
  - Empfohlene sentiment_score-Anpassung bei erfüllter Bedingung
  - Gib den Strategienamen in `buy_reason` an
```

### Referenz der Kern-Handelsideen

| Nummer | Idee |
|------|------|
| 1 | Strenge Einstiegsstrategie: erst bei einer Abweichungsrate < 5% einen Einstieg erwägen |
| 2 | Trend-Trading: MA5 > MA10 > MA20 bullische Anordnung |
| 3 | Effizienz vorrangig: Volumen bestätigt die Wirksamkeit des Trends |
| 4 | Kaufpunkt-Präferenz: bevorzugt Rückkehr zur MA-Unterstützung |
| 5 | Risikoprüfung: schlechte Nachrichten haben Vetorecht |
| 6 | Preis-Volumen-Abstimmung: Handelsvolumen bestätigt die Preisbewegung |
| 7 | Lockerung bei starken Trendaktien: Bei Spitzenreitern können die Kriterien angemessen gelockert werden |

## Verzeichnis für benutzerdefinierte Strategien

Neben diesem Verzeichnis (integrierte Strategien) kannst du über eine Umgebungsvariable ein zusätzliches Verzeichnis für benutzerdefinierte Strategien angeben:

```env
AGENT_SKILL_DIR=./my_skills
```

Das System lädt sowohl integrierte als auch benutzerdefinierte Strategien. Bei Namenskonflikten überschreiben die benutzerdefinierten Strategien die integrierten.

Der Umgebungsvariablenname bleibt `AGENT_SKILL_DIR` – das ist der nach der internen Vereinheitlichung verwendete Konfigurationseinstieg; produktseitig bedeutet er weiterhin „Verzeichnis für benutzerdefinierte Strategien".
