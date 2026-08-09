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
DISCORD_INTERACTIONS_PUBLIC_KEY=your-public-key (仅接收入站 Interaction/Webhook 回调时需要)
```

如果你配置了 Discord Interaction / Webhook 入站回调，务必在 Discord Developer Portal 的 `General Information -> Public Key` 复制公钥并填入 `DISCORD_INTERACTIONS_PUBLIC_KEY`；系统会使用该公钥校验每个入站请求的 Ed25519 签名，验签失败会直接拒绝请求。

## 配置 Interaction 回调

1. 使用仅启动服务的方式运行，避免服务器同时执行每日调度：

   ```bash
   python main.py --serve-only --host 0.0.0.0 --port 8000
   ```

2. 为服务配置稳定的公网 HTTPS 域名。在 Discord Developer Portal 的
   `General Information -> Interactions Endpoint URL` 填写：

   ```text
   https://你的域名/bot/discord
   ```

3. 保存时 Discord 会发送已签名的 PING。服务验签成功后返回 PONG；缺少或
   无效签名会返回 HTTP 401。该公开路由不使用管理员 Cookie，但
   `ADMIN_AUTH_ENABLED=true` 时 `/api/v1/*` 仍继续要求管理员登录。

Slash 命令会先收到 Discord 要求的延迟确认，分析结果完成后再更新原始回复。
因此云服务必须持续运行，不能使用会在请求结束后立即冻结后台工作的托管模式。

## 注册 Slash 命令

先在一个测试服务器注册，通常更适合首次验证：

```powershell
python scripts/register_discord_commands.py `
  --application-id "你的Application ID" `
  --guild-id "你的Server/Guild ID" `
  --dry-run
```

确认 JSON 载荷后，删除 `--dry-run` 执行真实 Guild 注册。脚本优先从进程环境变量
`DISCORD_BOT_TOKEN` 读取 Token；如果环境变量为空且当前是交互式终端，会使用
不回显的安全提示要求输入。正式全局注册使用：

```powershell
python scripts/register_discord_commands.py `
  --application-id "你的Application ID" `
  --global
```

脚本使用 Discord bulk overwrite 接口，使远端命令与当前列表一致。不要把真实
Token 写进脚本、文档、Git 或命令行参数；脚本不会从 argv 接收 Token，错误输出
也不会回显 Token。

## Webhook模式配置（可选）

如果你只想使用Webhook模式发送消息，不需要Bot Token，可以按照以下步骤配置：

1. 右键点击频道，选择"编辑频道"
2. 点击"集成" > "Webhooks" > "新建Webhook"
3. 配置Webhook名称和头像
4. 复制Webhook URL（这是你的`DISCORD_WEBHOOK_URL`）

可选配置发送身份：

```env
DISCORD_WEBHOOK_USERNAME=美股收盘助手
DISCORD_WEBHOOK_AVATAR_URL=https://example.com/bot-avatar.png
```

名称最长 80 字符；头像必须是 Discord 可从公网访问的 HTTPS 图片 URL。两项留空时继续使用现有默认值 `A股分析机器人` 与 `https://picsum.photos/200`。发送器会在每次 payload 中显式设置它们，因此会覆盖 Discord Webhook 页面里的默认名称和头像。

GitHub Actions 中这两项均使用 Repository Variables，而不是 Secrets。

## 支持的命令

Discord机器人支持以下Slash命令：

- `/help [command]`：查看帮助
- `/status`：查看系统状态
- `/analyze <stock_code> [full]`：分析单只股票
- `/market`：执行大盘复盘
- `/batch [count]`：批量分析自选股
- `/ask <stock_codes> [strategy]`：使用 Agent 技能分析股票
- `/chat <question>`：与 AI 助手自由对话
- `/research <topic> [question]`：深度研究股票或市场主题
- `/strategies [active]`：查看可用策略
- `/history [session]`：查看会话历史，参数也可使用 `clear`

## 测试机器人

1. 确保机器人已成功添加到你的服务器
2. 在频道中输入`/help`，机器人会返回帮助信息
3. 输入`/analyze 600519`测试股票分析功能
4. 输入`/market`测试大盘复盘功能

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
- **Slash命令不显示**：先使用 `--guild-id` 注册并确认应用已通过 `applications.commands` scope 加入服务器；全局命令同步可能需要等待
- **消息发送失败**：检查频道权限，确保机器人有发送消息的权限

## 相关链接

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Bot Documentation](https://discordpy.readthedocs.io/en/stable/)
- [Discord Slash Commands](https://discord.com/developers/docs/interactions/application-commands)
