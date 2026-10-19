# Zeabur 部署指南（2026-10-10 修订版）

本文是 [`zeabur-deployment.md`](zeabur-deployment.md) 的修订版。旧版以下三处与平台/仓库现状不符，照着做会在 Zeabur 控制台卡住：

1. 旧版写「新建项目 → 选择『从 GitHub 导入』」，当前控制台**没有这个入口**，GitHub 部署已并入「部署新服务 → GitHub」。
2. 旧版写「Zeabur 会自动检测 `.github/workflows/docker-publish.yml` 并使用 GitHub Actions 构建镜像」，这是**错误**的：Zeabur 用自带的 zbpack 构建器在自己的构建机上把源码打成镜像，不会读取或触发仓库里的任何 workflow。
3. 旧版写多服务「共享同一个 `/app/data` 存储卷」，这在 Zeabur 上**不可行**：卷属于单个服务，不能跨服务共享。

事实核验时间 2026-10-10。镜像可拉取性、CLI 参数、Dockerfile 与 `docker/docker-compose.yml` 行为为实测；Zeabur 控制台的按钮文案取自 Zeabur 官方文档，平台改版后可能变化。

## 目录

- [1. 部署前准备](#1-部署前准备)
- [2. 三种部署方式怎么选](#2-三种部署方式怎么选)
- [3. 方式 A：部署现成镜像](#3-方式-a部署现成镜像)
- [4. 方式 B：从 GitHub 源码构建](#4-方式-b从-github-源码构建)
- [5. 环境变量](#5-环境变量)
- [6. 持久化存储](#6-持久化存储)
- [7. 启动模式](#7-启动模式)
- [8. 端口与健康检查](#8-端口与健康检查)
- [9. 资源建议](#9-资源建议)
- [10. 更新部署](#10-更新部署)
- [11. 常见问题](#11-常见问题)
- [12. 本次修订相对旧版的变化](#12-本次修订相对旧版的变化)

## 1. 部署前准备

### 1.1 账号与权限

- Zeabur 账号。新项目需要可用的服务器资源；Zeabur 的共享集群已不再接受新服务，若控制台提示需要先添加服务器（Server）或绑定付款方式，按控制台引导处理，计费与可用区域以控制台为准。
- GitHub 账号，仅方式 B 需要。**一个 GitHub 账号只能绑定一个 Zeabur 账号**。
- 方式 A 直接使用公开镜像，不需要镜像仓库账号。
- 模型与搜索 API Key（至少配置一组，见第 5 节）。

### 1.2 本仓库的部署契约

这几项决定了部署能不能跑起来，先看清楚再动手：

| 项目 | 值 | 说明 |
| --- | --- | --- |
| 容器内监听端口 | `8000` | Dockerfile `EXPOSE 8000`，并内置 `WEBUI_HOST=0.0.0.0`、`API_PORT=8000` |
| 镜像默认启动命令 | `python main.py --schedule` | **只跑定时任务，不提供 HTTP 服务**，要 WebUI 必须覆盖启动命令 |
| Dockerfile 路径 | `docker/Dockerfile` | 不在仓库根目录，Zeabur 需要显式配置才能找到 |
| 容器入口脚本 | `docker/entrypoint.sh` | 先修复挂载目录属主，再用 `gosu` 降权到 `dsa` 用户运行 |
| 数据目录 | `/app/data` | `DATABASE_PATH` 默认为 `/app/data/stock_analysis.db`，必须挂持久卷 |
| 健康检查路径 | `/api/health` | 回退 `/health`，见 Dockerfile `HEALTHCHECK` |

### 1.3 公网暴露前先开认证

Zeabur 会给服务分配公网域名。系统绑定公网地址且未启用认证时会打印告警，提示服务裸露在公网。因此：

- 启动前设置 `ADMIN_AUTH_ENABLED=true`，首次访问 WebUI 时在页面设置初始密码；
- 忘记密码可在容器内执行 `python -m src.auth reset_password`。

## 2. 三种部署方式怎么选

| 方式 | 适用场景 | 代码版本 | 构建耗时 |
| --- | --- | --- | --- |
| A 现成镜像 | 想马上跑起来，不要求最新提交 | 上游发布镜像，当前为 `v3.31.0`（2026-08-23） | 无需构建，最快 |
| B GitHub 源码构建 | 要跟随你 fork 的 `main` 最新代码 | 你的仓库当前提交 | 需要构建（前端 + 后端依赖），首次较慢 |
| C 多服务拆分 | 想把 Web/API 与定时任务分开 | 同 A 或 B | 同 A / B |

单服务部署优先用方式 A 或 B，并把 WebUI 与定时任务放进同一个进程（见第 7 节），这样数据库自然共享；不要指望多服务共享存储卷。

## 3. 方式 A：部署现成镜像

1. 新建项目 → **部署新服务（Deploy New Service）** → 选择 **Docker Image**。
2. 镜像地址填其一：

   ```
   ghcr.io/zhulinsen/daily_stock_analysis:v3.31.0
   ghcr.io/zhulinsen/daily_stock_analysis:latest
   zhulinsen/daily_stock_analysis:v3.31.0
   ```

   > 这三个地址在 2026-10-10 实测可匿名拉取。建议固定版本 tag，便于确认当前跑的是哪个版本。
   >
   > 不要用 `ghcr.io/vincenman/daily_stock_analysis`：fork 自己的 GHCR 包当前不可匿名拉取（403），除非你到 GitHub 包设置里把它改为 public。

3. 端口填 `8000`。
4. 覆盖启动命令（Start Command）。镜像默认只跑定时任务，不覆盖就没有 Web 页面：

   ```bash
   /usr/local/bin/docker-entrypoint.sh python main.py --serve-only
   ```

   要让 WebUI 与定时分析共用一个进程，用：

   ```bash
   /usr/local/bin/docker-entrypoint.sh python main.py --serve --schedule
   ```

   为什么要带上 entrypoint 脚本：Zeabur 文档说明启动命令会覆盖镜像原本的 entrypoint 与参数，并默认用 `/bin/sh` 执行。显式调用 `/usr/local/bin/docker-entrypoint.sh` 才能保留挂载目录的权限修复与 `gosu` 降权；直接写 `python main.py ...` 会让进程以 root 运行，并跳过权限修复逻辑。

5. 添加持久卷并挂载到 `/app/data`（见第 6 节）。
6. 配置环境变量（见第 5 节），至少包含模型/搜索 Key 和 `ADMIN_AUTH_ENABLED=true`。
7. 部署完成后在「网络」里配置域名，访问 `https://<你的域名>/`。

### 3.1 版本说明

`latest` 与 `v3.31.0` 当前指向同一镜像。需要 2026-08-23 之后合入 `main` 的能力（例如 `--etf-rotation`）时，请改用方式 B 从源码构建，或等下一次正式发布。

## 4. 方式 B：从 GitHub 源码构建

### 4.1 关联 GitHub 账号

1. 控制台 → **设置 → 集成（Settings > Integrations）**，关联 GitHub 账号。
2. 用邮箱注册的 Zeabur 账号必须先完成这一步，否则控制台不会给出 GitHub 相关入口。

### 4.2 导入仓库

1. 新建项目 → **部署新服务（Deploy New Service）**。
2. 选择 **GitHub** → 点 **Configure GitHub**。
3. 在跳转到的 GitHub 页面把 **Zeabur App 安装到你的个人账号**（或组织），并授予目标仓库权限。
4. 回到 Zeabur，在搜索框中输入仓库名或 GitHub URL（例如 `vincenman/daily_stock_analysis`）→ **Deploy**。

### 4.3 搜不到仓库时的排查顺序

1. 是否已在「设置 → 集成」关联 GitHub 账号。
2. Zeabur App 是否已安装：GitHub → Settings → Applications → Installed GitHub Apps → Zeabur → Configure。
3. 安装时若选的是 “Only select repositories”，目标仓库不在授权列表里就搜不到；把仓库加进去，或改为 All repositories。
4. 组织仓库且你不是 Owner 时，可能没有权限安装/授权 App，需要组织管理员操作。
5. fork 仓库本身不受限制，但必须位于你有权限安装 App 的账号下。

### 4.4 让 Zeabur 找到 `docker/Dockerfile`

Zeabur 的 zbpack 只在**构建根目录**查找名为 `Dockerfile` 的文件。本仓库的 Dockerfile 在 `docker/Dockerfile`，所以仓库根目录已提供 `zbpack.json`：

```json
{
  "dockerfile": {
    "path": "docker/Dockerfile"
  }
}
```

如果想临时覆盖或在删除 `zbpack.json` 后恢复，可在服务环境变量里设置：

```bash
ZBPACK_DOCKERFILE_PATH=docker/Dockerfile
```

路径相对构建根目录（未设置 Root Directory 时即仓库根），因此 Dockerfile 里的 `COPY api/ ...`、`COPY apps/dsa-web/ ...` 等仍然成立。

不做这一步时，Zeabur 会退回 Python 自动识别：不会构建前端、不会执行容器 entrypoint，Web 页面会不可用。

### 4.5 启动命令

与方式 A 相同，在服务「设置」的启动命令（Start Command）中覆盖为：

```bash
/usr/local/bin/docker-entrypoint.sh python main.py --serve-only
```

或 WebUI 与定时分析共用进程：

```bash
/usr/local/bin/docker-entrypoint.sh python main.py --serve --schedule
```

> 如果你看到 `ZBPACK_START_COMMAND` 且必须带上 `_startup` 的说明，那是针对 Python buildpack 构建路径的；本仓库走 Dockerfile 构建，用服务设置里的启动命令即可。

### 4.6 构建行为与 GitHub Actions 的关系

- Zeabur 在自己的构建机上用 zbpack 把源码构建成镜像并推送到 Zeabur 的镜像仓库，**不会读取或触发 `.github/workflows/*`**。
- 仓库里的 `docker-publish.yml` 只在推送 `v*.*.*` tag 时发布 GHCR / Docker Hub 镜像，与 Zeabur 部署互不影响；因此「打个 tag 就能让 Zeabur 更新」是不成立的。
- Push 到 `main` 后由 GitHub 集成触发 Zeabur 重新构建部署。
- 构建包含前端 `npm ci && npm run build` 与后端 Python 依赖安装，首次构建耗时较长；失败时先看构建日志里出问题的是前端阶段还是依赖阶段。

## 5. 环境变量

在服务页面的「环境变量」中添加。敏感值只放在 Zeabur 环境变量里，不要提交 `.env` 到仓库。

### 5.1 基础配置

| 变量名 | 说明 | 默认值 |
| --- | --- | --- |
| `PYTHONUNBUFFERED` | Python 无缓冲输出 | 镜像已设 `1` |
| `LOG_DIR` | 日志目录 | 镜像已设 `/app/logs` |
| `DATABASE_PATH` | 数据库路径 | 镜像已设 `/app/data/stock_analysis.db` |
| `TZ` | 时区 | 镜像已设 `Asia/Shanghai` |

以上镜像内已有默认值，通常无需重复设置。

### 5.2 API 服务与认证

| 变量名 | 说明 | 默认值 |
| --- | --- | --- |
| `API_HOST` | API 监听地址 | `0.0.0.0` |
| `API_PORT` | API 监听端口 | `8000` |
| `ADMIN_AUTH_ENABLED` | 是否启用 Web 登录认证，公网部署应设为 `true` | `false` |
| `ADMIN_SESSION_MAX_AGE_HOURS` | 登录会话有效期（小时） | `24` |

> 旧版 `WEBUI_HOST` / `WEBUI_PORT` / `WEBUI_ENABLED` 仍兼容，会自动转发到 API 服务。

### 5.3 分析与搜索 Key

| 变量名 | 说明 |
| --- | --- |
| `ANSPIRE_API_KEYS` | Anspire Open API 密钥（大模型与搜索共用，推荐） |
| `AIHUBMIX_KEY` | AIHubMix API 密钥（一 Key 多模型，推荐） |
| `GEMINI_API_KEY` | Gemini API 密钥 |
| `OPENAI_API_KEY` | OpenAI 兼容 API 密钥 |
| `SERPAPI_API_KEYS` | SerpAPI 密钥（推荐） |
| `TAVILY_API_KEYS` | Tavily API 密钥（逗号分隔） |
| `BOCHA_API_KEYS` | Bocha API 密钥（逗号分隔） |
| `BRAVE_API_KEYS` | Brave Search API 密钥（逗号分隔） |
| `MINIMAX_API_KEYS` | MiniMax API 密钥（逗号分隔） |
| `SEARXNG_BASE_URLS` | SearXNG 实例地址（逗号分隔，无配额兜底，需在 settings.yml 启用 format: json） |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | 是否在 `SEARXNG_BASE_URLS` 为空时自动从 `searx.space` 获取公共实例（默认 `false`） |

### 5.4 通知与机器人

| 变量名 | 说明 |
| --- | --- |
| `DISCORD_WEBHOOK_URL` | Discord Webhook 通知地址 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token（配合频道 ID 通过 Bot 发送） |
| `DISCORD_MAIN_CHANNEL_ID` | Discord 主频道 ID |
| `DINGTALK_STREAM_ENABLED` | 钉钉 Stream 客户端（随 Web/API 服务启动） |
| `FEISHU_STREAM_ENABLED` | 飞书 Stream 客户端（随 Web/API 服务启动） |

> **Discord 现状**：当前版本支持的是 Discord **通知推送（出站）**，即上面的 Webhook / Bot Token + 频道 ID 组合。`DISCORD_INTERACTIONS_PUBLIC_KEY` 与 `bot/platforms/discord.py` 是入站交互适配层，但当前没有挂载对应的 HTTP 路由，因此不要按旧文档把它当成「部署完就能用 slash 命令」的机器人入口。
>
> 钉钉 / 飞书 Stream 客户端由 Web/API 服务进程在启动时拉起（`start_bot_stream_clients`），因此只在 `--serve` / `--serve-only` 模式下生效，`--schedule` 模式下不会启动。

## 6. 持久化存储

1. 进入服务页面，打开「硬盘（Volumes）」分页 → 点 **Mount Volumes**。
2. 选择持久化存储，挂载目录（Mount Directory）填 `/app/data`。
3. 保存后重启服务。

建议至少挂载 `/app/data` 保存数据库；`/app/logs`、`/app/reports` 按需挂载。

Zeabur 卷的已知限制（来自官方文档）：

- 卷只属于单个服务，**不能跨服务共享**；因此多服务部署时数据库无法共享，共享数据库只能通过单服务多模式实现。
- 挂载会先清空目标目录内容。
- 服务启用卷后不支持零停机重启。
- 删除卷会同时销毁数据且不可恢复，重要数据请自行备份。

## 7. 启动模式

| 模式 | 启动命令 | 说明 |
| --- | --- | --- |
| 仅 Web/API（推荐容器默认） | `python main.py --serve-only` | 只提供 Web/API；会恢复已保存的定时设置，但不会在启动时立即执行分析 |
| Web/API + 定时分析 | `python main.py --serve --schedule` | 单服务同时提供 WebUI 与定时分析，定时任务由 Web/API runtime scheduler 接管 |
| 仅定时任务 | `python main.py --schedule` | 不提供 HTTP 服务，无 Web 页面 |
| 仅大盘复盘 | `python main.py --market-review` | 执行一次大盘复盘后退出，不适合作为常驻服务启动命令 |
| ETF 轮动报告 | `python main.py --etf-rotation` | 输出最新信号与规则回测报告，不调用 LLM，执行完退出 |

容器里已被 `docker/docker-compose.yml` 采用的参考命令是：

```bash
python main.py --serve-only --host 0.0.0.0 --port 8000
```

镜像内已设 `WEBUI_HOST=0.0.0.0`、`API_PORT=8000`，所以 Zeabur 上通常不必再传 `--host` / `--port`。

## 8. 端口与健康检查

- 端口填 `8000`（与镜像 `EXPOSE 8000` 一致）。
- 健康检查路径为 `/api/health`，失败时回退 `/health`。
- Zeabur 的健康检查与域名在服务页面的「网络」相关配置中设置。

## 9. 资源建议

Zeabur 服务建议从 `1G` 内存起步；`512M` 仅适合轻量 Web/API、单股、低并发场景，并建议设置 `MAX_WORKERS=1`。

- 最低可尝试：`512M`，不要同时运行多个重型任务。
- 推荐：`1G`，适合单服务常规分析。
- 高负载：`2G+`，适合同时运行 Web/API 与定时分析、多股票、大盘复盘、新闻扩展、图片报告或选股。

如果只能使用 `512M`，请避免同时部署等价于 `server + analyzer` 的多服务组合，并关闭非必要的大盘复盘、新闻扩展和图片报告能力。

## 10. 更新部署

### 10.1 方式 A（镜像）

在服务「设置」的 Service Image 中修改镜像 tag 并保存，Zeabur 会用新镜像自动重启服务（该操作只对 Docker 镜像服务可用）。

### 10.2 方式 B（GitHub）

向被部署的分支（通常为 `main`）推送代码，GitHub 集成会触发 Zeabur 重新构建并部署。注意这与仓库的 tag 发布流程无关，不需要打 tag。

## 11. 常见问题

### 11.1 找不到「从 GitHub 导入」

当前控制台的 GitHub 入口是「部署新服务 → GitHub」，没有旧文档里的一级入口「从 GitHub 导入」。

### 11.2 GitHub 搜索框里搜不到仓库

按 4.3 的顺序排查，最常见原因是 Zeabur App 安装时选了 “Only select repositories” 且未包含该仓库。

### 11.3 部署成功但网页打不开

镜像默认启动命令是 `python main.py --schedule`，不监听端口。按第 3 或第 4 节覆盖启动命令为 `--serve-only` 或 `--serve --schedule`。

### 11.4 页面能开但已经是旧版本

方式 A 使用的 `latest` 对应上游最近一次正式发布（当前 `v3.31.0`），不等于你 fork 的 `main`。需要最新代码请用方式 B。

### 11.5 容器日志提示数据目录不可写

`/app/data` 等挂载目录属主异常时，entrypoint 会输出 `WARN: ... is still not writable by dsa`。确认启动命令通过 `/usr/local/bin/docker-entrypoint.sh` 调用（保留权限修复），并检查卷挂载路径是否为 `/app/data`。

### 11.6 构建失败提示找不到 `COPY` 的源文件

Zeabur 没找到 `docker/Dockerfile` 而退回 Python 构建，或构建根目录被改动。确认根目录 `zbpack.json` 存在，或设置了 `ZBPACK_DOCKERFILE_PATH=docker/Dockerfile`。

### 11.7 多服务之间数据不共享

Zeabur 卷不能跨服务共享，这是平台限制。改用单服务 `--serve --schedule`，或接受多服务各自独立数据库。

### 11.8 需要重启或进容器排查

在服务页面可重启服务；需要进入容器执行命令时，用 Zeabur 提供的容器命令入口（service Overview 的 Command）或本地 `zeabur` CLI。

```bash
# 查看日志目录
ls -l /app/logs

# 检查关键环境变量
printenv | grep -iE "admin_auth|api_port|database_path"
```

## 12. 本次修订相对旧版的变化

| 项目 | 旧版 | 本文 |
| --- | --- | --- |
| GitHub 导入入口 | 「新建项目 → 从 GitHub 导入」 | 「部署新服务 → GitHub → Configure GitHub」，并补充 GitHub App 授权排查 |
| 镜像构建方式 | 声称 Zeabur 检测 `docker-publish.yml` 并用 GitHub Actions 构建 | Zeabur 用 zbpack 自行构建，不读取 workflow |
| Dockerfile 路径 | 未提及 | 新增 `zbpack.json` / `ZBPACK_DOCKERFILE_PATH=docker/Dockerfile` |
| 启动命令 | 列出 4 种模式，未说明默认 CMD 不开 HTTP | 明确默认 `--schedule` 不开 HTTP，给出带 entrypoint 的覆盖命令 |
| 存储卷 | 声称多服务可共享同一卷 | 修正为卷仅属于单个服务，不能跨服务共享 |
| 认证 | 未提及 | 新增 `ADMIN_AUTH_ENABLED=true` 提示 |
| Discord | 描述为完整机器人部署流程 | 说明当前仅通知可用，入站交互未挂载 HTTP 路由 |

英文文档未同步：本文件是中文专题部署文档，与旧版 `zeabur-deployment.md` 保持一致的语言约定。
