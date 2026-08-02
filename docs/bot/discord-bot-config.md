# Discord-Bot-Konfiguration

## Discord-Bot
Damit der Discord-Bot Nachrichten empfangen kann, muss im Discord Developer Portal eine Bot-Anwendung erstellt werden.
https://discord.com/developers/applications

Der Discord-Bot unterstützt zwei Methoden zum Senden von Nachrichten:
1. **Webhook-Modus**: einfache Konfiguration, geringe Berechtigungen, geeignet für Szenarien, in denen nur Nachrichten gesendet werden müssen
2. **Bot-API-Modus**: hohe Berechtigungen, unterstützt den Empfang von Befehlen, benötigt einen Bot-Token und eine Kanal-ID

## Discord-Bot erstellen

### 1. Beim Discord Developer Portal anmelden
Öffne https://discord.com/developers/applications und melde dich mit deinem Discord-Konto an.

### 2. Anwendung erstellen
Klicke auf die Schaltfläche „New Application“, gib einen Anwendungsnamen ein (z. B. „Intelligenter A-Aktien-Analyse-Bot“) und klicke dann auf „Create“.

### 3. Bot konfigurieren
Klicke in der linken Navigationsleiste auf „Bot“ und dann auf die Schaltfläche „Add Bot“; bestätige das Hinzufügen.

### 4. Bot-Token abrufen
Klicke auf der Bot-Seite auf die Schaltfläche „Reset Token“ und kopiere das erzeugte Token (dies ist dein `DISCORD_BOT_TOKEN`).

### 5. Berechtigungen konfigurieren
Aktiviere im Abschnitt „Privileged Gateway Intents“ der Bot-Seite die folgenden Optionen:
- Presence Intent
- Server Members Intent
- Message Content Intent

### 6. Zum Server hinzufügen
1. Klicke in der linken Navigationsleiste auf „OAuth2“ > „URL Generator“
2. Wähle unter „Scopes“:
   - `bot`
   - `applications.commands`
3. Wähle unter „Bot Permissions“:
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Use Slash Commands
4. Kopiere die erzeugte URL, öffne sie im Browser und wähle den Server, zu dem der Bot hinzugefügt werden soll.

### 7. Kanal-ID abrufen
1. Aktiviere im Discord-Client den Entwicklermodus: Einstellungen > Erweitert > Entwicklermodus
2. Klicke mit der rechten Maustaste auf den Kanal, in den der Bot Nachrichten senden soll, und wähle „Copy ID“ (dies ist deine `DISCORD_MAIN_CHANNEL_ID`).

## Umgebungsvariablen konfigurieren

Füge die folgende Konfiguration zu deiner `.env`-Datei hinzu:

```env
# Discord 机器人配置
DISCORD_BOT_TOKEN=your-discord-bot-token
DISCORD_MAIN_CHANNEL_ID=your-channel-id
DISCORD_WEBHOOK_URL=your-webhook-url (可选)
DISCORD_INTERACTIONS_PUBLIC_KEY=your-public-key (仅接收入站 Interaction/Webhook 回调时需要)
DISCORD_BOT_STATUS=A股智能分析 | /help
```

Wenn du eingehende Callbacks für Discord Interaction / Webhook konfiguriert hast, kopiere unbedingt den öffentlichen Schlüssel unter `General Information -> Public Key` im Discord Developer Portal und trage ihn in `DISCORD_INTERACTIONS_PUBLIC_KEY` ein; das System prüft mit diesem Schlüssel die Ed25519-Signatur jedes eingehenden Anfangs und lehnt Anfragen mit fehlgeschlagener Signaturprüfung direkt ab.

## Webhook-Modus-Konfiguration (optional)

Wenn du Nachrichten nur im Webhook-Modus senden möchtest und keinen Bot-Token benötigst, kannst du die folgende Konfiguration vornehmen:

1. Klicke mit der rechten Maustaste auf den Kanal und wähle „Kanal bearbeiten“
2. Klicke auf „Integrationen“ > „Webhooks“ > „Neuen Webhook erstellen“
3. Konfiguriere den Namen und das Avatar des Webhooks
4. Kopiere die Webhook-URL (dies ist deine `DISCORD_WEBHOOK_URL`).

## Unterstützte Befehle

Der Discord-Bot unterstützt die folgenden Slash-Befehle:

1. `/analyze <stock_code> [full_report]` - Analysiert eine bestimmte Aktienkennzahl
   - `stock_code`: die Aktienkennzahl, z. B. 600519
   - `full_report`: optional, ob ein vollständiger Bericht erzeugt werden soll (einschließlich Markt)

2. `/market_review` - Ruft den Markt-Rückblickbericht ab

3. `/help` - Zeigt Hilfeinformationen an

## Bot testen

1. Stelle sicher, dass der Bot erfolgreich zu deinem Server hinzugefügt wurde.
2. Gib im Kanal `/help` ein; der Bot liefert die Hilfeinformationen zurück.
3. Gib `/analyze 600519` ein, um die Aktienanalyse zu testen.
4. Gib `/market_review` ein, um die Markt-Rückblickfunktion zu testen.

## Hinweise

1. Stelle sicher, dass dein Bot ausreichend Berechtigungen hat, um in Kanälen Nachrichten zu senden und Slash-Befehle zu verwenden.
2. Aktualisiere deinen Bot-Token regelmäßig, um die Sicherheit zu gewährleisten.
3. Gib deinen Bot-Token an niemanden weiter.
4. Wenn der Bot nicht reagiert, prüfe Folgendes:
   - ob der Bot-Token korrekt ist
   - ob die Kanal-ID korrekt ist
   - ob der Bot online ist
   - ob der Bot über die Berechtigung zum Senden von Nachrichten verfügt

## Fehlerbehebung

- **Bot reagiert nicht auf Befehle**: Prüfe, ob Bot-Token und Kanal-ID korrekt sind, und stelle sicher, dass der Bot zum Server hinzugefügt wurde.
- **Slash-Befehle werden nicht angezeigt**: Warte eine Weile (Discord muss die Befehle synchronisieren) oder füge den Bot erneut hinzu.
- **Nachrichtenversand fehlgeschlagen**: Prüfe die Kanalberechtigungen und stelle sicher, dass der Bot die Berechtigung zum Senden von Nachrichten hat.

## Verwandte Links

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Bot Documentation](https://discordpy.readthedocs.io/en/stable/)
- [Discord Slash Commands](https://discord.com/developers/docs/interactions/application-commands)
