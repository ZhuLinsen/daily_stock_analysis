# Zeabur 部署指南

本指南详细介绍如何在 Zeabur 上部署 A股自选股智能分析系统，包括 WebUI 和 Discord 机器人功能。

## 目录

- [1. 部署前准备](#1-部署前准备)
- [2. 在 Zeabur 上部署](#2-在-zeabur-上部署)
- [3. 配置启动命令](#3-配置启动命令)
- [4. Discord 机器人部署](#4-discord-机器人部署)
- [5. 环境变量配置](#5-环境变量配置)
- [6. 挂载配置](#6-挂载配置)
- [7. 健康检查](#7-健康检查)
- [8. 常见问题](#8-常见问题)

## 1. 部署前准备

### 1.1 必要条件

- Zeabur 账号
- GitHub 账号（用于连接仓库）
- Discord 开发者账号（如需部署机器人）
- 相关 API 密钥（如 Gemini API Key、搜索服务 API Key 等）

### 1.2 仓库准备

确保你的仓库包含以下文件：

- `.github/workflows/docker-publish.yml`（已自动创建）
- `docker/Dockerfile`（已存在）
- 完整的项目代码

## 2. 在 Zeabur 上部署

### 2.1 连接 GitHub 仓库

1. 登录 Zeabur 控制台
2. 点击「新建项目」
3. 选择「从 GitHub 导入」
4. 选择你的仓库和分支（推荐使用 `main` ）
5. 点击「导入」

### 2.2 配置构建规则

Zeabur 会自动检测 `.github/workflows/docker-publish.yml` 文件，并使用 GitHub Actions 构建镜像。

如果没有自动检测到，可以手动配置：

1. 在项目页面，点击「构建规则」
2. 选择「Dockerfile」
3. Dockerfile 路径填写：`docker/Dockerfile`
4. 点击「保存」

### 2.3 启动服务

1. 等待镜像构建完成
2. 点击「启动服务」
3. 服务启动后，你可以在「访问」标签页获取访问地址

### 2.4 前端构建与静态资源

FastAPI 会自动托管 `static/` 目录下的前端资源。前端打包输出位置由
`apps/dsa-web/vite.config.ts` 决定，默认输出到项目根目录 `static/`。

Dockerfile 已采用多阶段构建，前端会在镜像构建时自动打包。
如需覆盖默认静态资源，可在宿主机手动构建并挂载到容器内 `/app/static`。

## 3. 配置启动命令

### 3.1 支持的启动模式

系统支持多种启动模式，你可以根据需要配置不同的启动命令：

| 模式 | 启动命令 | 描述 |
|------|----------|------|
| 定时任务模式（默认） | `python main.py --schedule` | 按计划执行股票分析 |
| FastAPI 模式 | `python main.py --serve` | 启动 FastAPI 并执行分析 |
| 仅 FastAPI 模式 | `python main.py --serve-only` | 仅启动 FastAPI，不执行分析 |
| 仅大盘复盘 | `python main.py --market-review` | 仅执行大盘复盘分析 |

### 3.2 配置启动命令

1. 在 Zeabur 控制台，进入服务页面
2. 点击「设置」
3. 找到「启动命令」配置项
4. 输入你需要的启动命令，例如：
    - 启动 FastAPI：`python main.py --serve`
    - 仅启动 FastAPI：`python main.py --serve-only --host 0.0.0.0 --port 8000`
    - 启动定时任务：`python main.py --schedule`
5. 点击「保存」
6. 重启服务

## 4. Discord 机器人部署

### 4.1 准备工作

1. 创建 Discord 应用和机器人
   - 访问 [Discord 开发者平台](https://discord.com/developers/applications)
   - 点击「New Application」创建新应用
   - 在「Bot」标签页，点击「Add Bot」创建机器人
   - 复制机器人 Token

2. 配置机器人权限
   - 在「Bot」标签页，向下滚动到「Privileged Gateway Intents」
   - 启用「Server Members Intent」和「Message Content Intent」
   - 在「OAuth2」→「URL Generator」中，选择「bot」范围
   - 选择所需权限（如「Send Messages」、「Read Messages/View Channels」等）
   - 复制生成的邀请链接，将机器人添加到你的服务器

### 4.2 配置环境变量

在 Zeabur 控制台的「环境变量」配置中，添加以下变量：

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord 机器人 Token | `MTAxMjM0NTY3ODkwMTEyMzQ1Ng.GhIjKl.MnOpQrStUvWxYz1234567890` |
| `DISCORD_MAIN_CHANNEL_ID` | 主频道 ID | `123456789012345678` |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL（可选） | `https://discord.com/api/webhooks/...` |

### 4.3 启动机器人

机器人功能默认通过配置启用，无需特殊启动命令。确保你的配置文件中包含机器人相关配置，或通过环境变量设置。

## 5. 环境变量配置

### 5.1 基本环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `PYTHONUNBUFFERED` | 启用 Python 无缓冲输出 | `1` |
| `LOG_DIR` | 日志目录 | `/app/logs` |
| `DATABASE_PATH` | 数据库路径 | `/app/data/stock_analysis.db` |

### 5.2 API 服务配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `API_HOST` | API 服务监听地址 | `0.0.0.0` |
| `API_PORT` | API 服务端口 | `8000` |

> 旧版 `WEBUI_HOST`/`WEBUI_PORT`/`WEBUI_ENABLED` 环境变量仍兼容，会自动转发到 API 服务。

### 5.3 分析相关配置

| 变量名 | 说明 |
|--------|------|
| `GEMINI_API_KEY` | Gemini API 密钥 |
| `BOCHA_API_KEYS` | Bocha API 密钥（用逗号分隔） |
| `TAVILY_API_KEYS` | Tavily API 密钥（用逗号分隔） |
| `SERPAPI_KEYS` | SerpAPI 密钥（用逗号分隔） |

### 5.4 配置方法

在 Zeabur 控制台：

1. 进入服务页面
2. 点击「环境变量」
3. 点击「添加环境变量」
4. 输入变量名和值
5. 点击「保存」
6. 重启服务

## 6. 挂载配置

### 6.1 支持的挂载目录

| 目录 | 说明 |
|------|------|
| `/app/data` | 数据库和数据文件 |
| `/app/logs` | 日志文件 |
| `/app/reports` | 分析报告 |

### 6.2 配置挂载

1. 在 Zeabur 控制台，进入服务页面
2. 点击「存储」
3. 点击「添加存储卷」
4. 选择「持久化存储」
5. 配置挂载路径：
   - 存储卷路径：`/app/data`
   - 容器内路径：`/app/data`
6. 点击「保存」
7. 对其他需要挂载的目录重复上述步骤

### 6.3 注意事项

- 挂载后，数据会持久化保存，不会因容器重启而丢失
- 建议至少挂载 `/app/data` 目录，以保存数据库

## 7. 健康检查

系统内置了健康检查机制，默认检查：

- WebUI 模式：检查 `http://localhost:8000/health` 端点
- FastAPI 模式：检查 `http://localhost:8000/api/health` 端点
- 非服务模式：始终返回健康状态

健康检查配置如下：

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || curl -f http://localhost:8000/health \
    || python -c "import sys; sys.exit(0)"
```

## 8. 常见问题

### 8.1 API 服务无法访问

- 检查启动命令是否包含 `--serve` 或 `--serve-only` 参数
- 检查「访问」标签页是否已配置域名
- 检查防火墙设置

### 8.2 机器人不响应

- 检查 Discord 机器人 Token 是否正确
- 检查机器人是否已添加到服务器
- 检查机器人权限是否足够
- 检查日志文件，查看是否有错误信息

### 8.3 分析任务不执行

- 检查定时任务配置是否正确
- 检查 API 密钥是否有效
- 检查日志文件，查看是否有错误信息

### 8.4 数据丢失

- 确保已挂载 `/app/data` 目录
- 检查存储卷配置是否正确

## 9. 高级配置

### 9.1 多实例部署

你可以在 Zeabur 上部署多个实例，用于不同的功能：

1. 一个实例用于 API 服务（`python main.py --serve-only`）
2. 一个实例用于定时任务（`python main.py --schedule`）
3. 一个实例用于机器人（`python main.py --discord-bot`）

确保它们共享同一个 `/app/data` 存储卷，以共享数据库。

### 9.2 自定义域名

在 Zeabur 控制台的「访问」标签页，你可以：

1. 使用自动生成的域名
2. 绑定自定义域名
3. 配置 HTTPS

## 10. 更新部署

### 10.1 自动更新

当你向仓库推送新代码时：

1. GitHub Actions 会自动构建新镜像
2. Zeabur 会检测到新镜像
3. 你可以选择「自动部署」或手动触发部署

### 10.2 手动更新

1. 在 Zeabur 控制台，进入服务页面
2. 点击「部署历史」
3. 选择「重新部署」
4. 或点击「更新镜像」

## 11. 监控和日志

### 11.1 查看日志

在 Zeabur 控制台，进入服务页面，点击「日志」标签页，可以查看实时日志和历史日志。

### 11.2 监控指标

Zeabur 提供了基础的监控指标：

- CPU 使用率
- 内存使用率
- 网络流量
- 磁盘使用率

在「监控」标签页查看详细指标。

## 12. 故障排查

### 12.1 查看详细日志

```bash
# 进入容器
zeabur exec <服务名> bash

# 查看日志文件
cat /app/logs/stock_analysis_20260125.log
```

### 12.2 检查配置

```bash
# 进入容器
zeabur exec <服务名> bash

# 检查环境变量
printenv | grep -i discord
printenv | grep -i webui
```

### 12.3 测试连接

```bash
# 测试网络连接
zeabur exec <服务名> curl -I https://api.discord.com

# 测试 API 连接
zeabur exec <服务名> python -c "import requests; print(requests.get('https://api.discord.com').status_code)"
```

## 13. 最佳实践

1. **使用持久化存储**：始终挂载 `/app/data` 目录，以保存数据库
2. **配置合理的健康检查**：根据实际情况调整健康检查参数
3. **使用环境变量管理敏感信息**：不要将 API 密钥硬编码到代码中
4. **定期备份数据**：定期下载 `/app/data` 目录的内容进行备份
5. **使用合适的启动模式**：根据需求选择合适的启动命令
6. **监控服务状态**：定期检查服务状态和日志

## 14. 联系方式

如有问题，欢迎联系项目维护者或在 GitHub Issues 中提问。
