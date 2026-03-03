# Discord机器人配置

## Discord机器人
Discord机器人接收消息需要使用Discord Developer Portal创建机器人应用
https://discord.com/developers/applications

Discord机器人支持两种消息发送方式：
1. **Webhook模式**：配置简单，权限低，适合只需要发送消息的场景
2. **Bot API模式**：权限高，支持接收命令，需要配置Bot Token和频道ID

## 创建Discord机器人

### 1. 登录Discord Developer Portal
访问 https://discord.com/developers/applications 并使用你的Discord账号登录

### 2. 创建应用
点击"New Application"按钮，输入应用名称（例如：A股智能分析机器人），然后点击"Create"

### 3. 配置机器人
在左侧导航栏中点击"Bot"，然后点击"Add Bot"按钮，确认添加

### 4. 获取Bot Token
在Bot页面，点击"Reset Token"按钮，然后复制生成的Token（这是你的`DISCORD_BOT_TOKEN`）

### 5. 配置权限
在Bot页面的"Privileged Gateway Intents"部分，开启以下选项：
- Presence Intent
- Server Members Intent
- Message Content Intent

### 6. 添加到服务器
1. 在左侧导航栏中点击"OAuth2" > "URL Generator"
2. 在"Scopes"中选择：
   - `bot`
   - `applications.commands`
3. 在"Bot Permissions"中选择：
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Use Slash Commands
4. 复制生成的URL，在浏览器中打开，选择要添加机器人的服务器

### 7. 获取频道ID
1. 在Discord客户端中，开启开发者模式：设置 > 高级 > 开发者模式
2. 右键点击你想要机器人发送消息的频道，选择"Copy ID"（这是你的`DISCORD_MAIN_CHANNEL_ID`）

## 配置环境变量

将以下配置添加到你的`.env`文件中：

```env
# Discord 机器人配置
DISCORD_BOT_TOKEN=your-discord-bot-token
DISCORD_MAIN_CHANNEL_ID=your-channel-id
DISCORD_WEBHOOK_URL=your-webhook-url (可选)
DISCORD_BOT_STATUS=A股智能分析 | /help
```

## Webhook模式配置（可选）

如果你只想使用Webhook模式发送消息，不需要Bot Token，可以按照以下步骤配置：

1. 右键点击频道，选择"编辑频道"
2. 点击"集成" > "Webhooks" > "新建Webhook"
3. 配置Webhook名称和头像
4. 复制Webhook URL（这是你的`DISCORD_WEBHOOK_URL`）

## 支持的命令

Discord机器人支持以下Slash命令：

1. `/analyze <stock_code> [full_report]` - 分析指定股票代码
   - `stock_code`: 股票代码，如 600519
   - `full_report`: 可选，是否生成完整报告（包含大盘）

2. `/market_review` - 获取大盘复盘报告

3. `/help` - 查看帮助信息

## 测试机器人

1. 确保机器人已成功添加到你的服务器
2. 在频道中输入`/help`，机器人会返回帮助信息
3. 输入`/analyze 600519`测试股票分析功能
4. 输入`/market_review`测试大盘复盘功能

## 注意事项

1. 确保你的机器人有足够的权限在频道中发送消息和使用Slash命令
2. 定期更新你的Bot Token，确保安全性
3. 不要将你的Bot Token分享给任何人
4. 如果机器人没有响应，检查：
   - Bot Token是否正确
   - 频道ID是否正确
   - 机器人是否在线
   - 机器人是否有消息发送权限

## 故障排除

- **机器人不响应命令**：检查Bot Token和频道ID是否正确，确保机器人已添加到服务器
- **Slash命令不显示**：等待一段时间（Discord需要同步命令），或重新添加机器人
- **消息发送失败**：检查频道权限，确保机器人有发送消息的权限

## 相关链接

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Bot Documentation](https://discordpy.readthedocs.io/en/stable/)
- [Discord Slash Commands](https://discord.com/developers/docs/interactions/application-commands)
