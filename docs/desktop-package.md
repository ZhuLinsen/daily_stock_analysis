# 桌面端打包说明 (Electron + React UI)

本项目可打包为桌面应用，使用 Electron 作为桌面壳，`apps/dsa-web` 的 React UI 作为界面。

## 架构说明

- React UI（Vite 构建）由本地 FastAPI 服务托管
- Electron 启动时自动拉起后端服务，等待 `/api/health` 就绪后加载 UI
- 用户配置文件 `.env` 和数据库放在 exe 同级目录（便携模式）

## 本地开发

一键启动（开发模式）：

```bash
powershell -ExecutionPolicy Bypass -File scripts\run-desktop.ps1
```

或手动执行：

1) 构建 React UI（输出到 `static/`）

```bash
cd apps/dsa-web
npm install
npm run build
```

2) 启动 Electron 应用（自动拉起后端）

```bash
cd apps/dsa-desktop
npm install
npm run dev
```

首次运行时会自动从 `.env.example` 复制生成 `.env`。

## 打包 (Windows)

### 前置条件

- Node.js 18+
- Python 3.10+
- 开启 Windows 开发者模式（electron-builder 需要创建符号链接）
  - 设置 -> 隐私和安全性 -> 开发者选项 -> 开发者模式

### 一键打包

```bash
powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
```

该脚本会依次执行：
1. 构建 React UI
2. 安装 Python 依赖
3. PyInstaller 打包后端
4. electron-builder 打包桌面应用

当前 Windows 安装包使用 NSIS 向导式安装流程，仅支持当前用户安装且已禁用管理员提权，安装时可手动选择目标目录（例如非 C 盘）。安装器通过 NSIS `.onVerifyInstDir` 回调在安装器层面阻止选择 `Program Files`、`Windows` 等系统保护目录——选择这些路径时"下一步"按钮会被自动禁用。安装完成后，桌面端仍会按现有逻辑在安装目录旁生成/读取 `.env`、`data/stock_analysis.db` 和 `logs/desktop.log`。推荐使用默认的 per-user 安装目录。如果不想安装，仍可继续分发 `win-unpacked` 免安装包。

## GitHub CI 自动打包并发布 Release

仓库已支持通过 GitHub Actions 自动构建桌面端并上传到 GitHub Releases：

- 工作流：`.github/workflows/desktop-release.yml`
- 触发方式：
  - 推送语义化 tag（如 `v3.2.12`）后自动触发
  - 在 Actions 页面手动触发并指定 `release_tag`
- 产物：
  - Windows 安装包：Release 附件会整理为 `daily-stock-analysis-windows-installer-<tag>.exe`，本地 `apps/dsa-desktop/dist/` 中仍是 `*Setup*.exe`
  - Windows 免安装包：`daily-stock-analysis-windows-noinstall-<tag>.zip`
  - macOS Intel：`daily-stock-analysis-macos-x64-<tag>.dmg`
  - macOS Apple Silicon：`daily-stock-analysis-macos-arm64-<tag>.dmg`

建议发布流程：

1. 合并代码到 `main`
2. 由自动打 tag 工作流生成版本（或手动创建 tag）
3. `desktop-release` 工作流自动构建并把两个平台安装包附加到对应 GitHub Release

### 分步打包

1) 构建 React UI

```bash
cd apps/dsa-web
npm install
npm run build
```

2) 打包 Python 后端

```bash
pip install pyinstaller
pip install -r requirements.txt
python -m PyInstaller --name stock_analysis --onefile --noconsole --add-data "static;static" --hidden-import=multipart --hidden-import=multipart.multipart main.py
```

将生成的 exe 复制到 `dist/backend/`：

```bash
mkdir dist\backend
copy dist\stock_analysis.exe dist\backend\stock_analysis.exe
```

3) 打包 Electron 桌面应用

```bash
cd apps/dsa-desktop
npm install
npm run build
```

打包产物位于 `apps/dsa-desktop/dist/`。Windows 安装器会生成 `*Setup*.exe`，安装向导中可选择安装目录。

## 目录结构

Windows 安装包模式下，安装器仅支持当前用户安装且已禁用管理员提权，用户可在安装向导中选择安装目录；安装器会在安装器层面阻止选择 `Program Files`、`Windows` 等系统保护目录（选择时"下一步"按钮自动禁用），安装完成后，应用会在安装目录旁生成/读取 `.env`、`data/stock_analysis.db` 和 `logs/desktop.log`。请保留默认的 per-user 安装位置或选择其他用户可写目录。

`win-unpacked` 免安装模式下，目录结构如下：

```
win-unpacked/
  Daily Stock Analysis.exe    <- 双击启动
  .env                        <- 用户配置文件（首次启动自动生成）
  data/
    stock_analysis.db         <- 数据库
  logs/
    desktop.log               <- 运行日志
  resources/
    .env.example              <- 配置模板
    backend/
      stock_analysis.exe      <- 后端服务
```

## 配置文件说明

- `.env` 放在 exe 同目录下
- 首次启动时自动从 `.env.example` 复制生成
- macOS 打包态下，`exe` 实际位于 `.app` 包内部，因此 `.env`、`data/`、`logs/` 也会跟着落在应用包内容器里；替换新的 DMG / `.app` 时，旧配置会随旧应用包一起被覆盖
- 用户需要编辑 `.env` 配置以下内容：
  - `GEMINI_API_KEY` 或 `OPENAI_API_KEY`：AI 分析必需
  - `STOCK_LIST`：自选股列表（逗号分隔）
  - 其他可选配置参考 `.env.example`

### 桌面端备份 / 恢复 `.env`

- 从 `系统设置 -> 配置备份` 可以直接看到 `导出 .env` 和 `导入 .env` 按钮
- `导出 .env` 会导出当前**已保存**的 `.env` 备份文件；页面上尚未点击“保存配置”的本地草稿不会被导出
- `导入 .env` 会读取备份文件中的键值并合并到当前桌面端配置中，导入后会立即触发配置重载
- 导入是“键级覆盖”而不是整文件替换：备份文件中出现的键会覆盖当前值，未出现的键保持不变
- 如果当前页面还有未保存草稿，导入前会先提示确认，避免把本地草稿和已保存配置混在一起

> 建议：macOS 用户在升级 DMG 前先执行一次 `导出 .env`，这样即使旧 `.app` 被整体替换，也能在新版本里直接恢复配置

### 设置页版本信息

- `系统设置 -> 版本信息` 中的“桌面端版本”由 Electron 主进程的 `app.getVersion()` 提供，并通过 preload bridge 暴露给前端
- 开发态 `npm run dev` 与打包态 `npm run build` / 安装包都会复用同一条版本注入链路，不再在 `preload.js` 里维护独立硬编码版本号
- `README.md` 继续保留安装和运行入口说明；这类桌面端运行时细节统一落在本专题文档维护，避免入门文档膨胀

### 桌面端更新提醒

- 应用在主界面加载完成后会后台请求 GitHub Releases 的最新正式版（`/releases/latest`），并与当前 `app.getVersion()` 做语义化版本比较
- 检测到新版本时，会弹出一次性提醒对话框，主操作为“前往下载”，点击后直接打开对应 Release 页面
- `系统设置 -> 版本信息` 中新增“桌面端更新”区域，可手动点击“检查更新”查看状态并再次跳转下载页
- 当前实现仅做“提醒 + 跳转下载页”，不会静默下载、自动替换安装包，也不会因为网络失败而阻断桌面端启动
- 版本检查失败、GitHub API 超时或返回异常时，只会记录到 `logs/desktop.log`，设置页手动检查时才会展示错误状态

## 常见问题

### 启动后一直显示 "Preparing backend..."

1. 检查 `logs/desktop.log` 查看错误信息
2. 确认 `.env` 文件存在且配置正确
3. 确认端口 8000-8100 未被占用

### 后端启动报 ModuleNotFoundError

PyInstaller 打包时缺少模块，需要在 `scripts/build-backend.ps1` 中增加 `--hidden-import`。

### UI 加载空白

确认 `static/index.html` 存在，如不存在需重新构建 React UI。

### macOS 升级后配置看起来“被清空”

这是当前桌面端便携模式的已知行为：`.env` 放在打包后的应用目录旁，而 macOS 中这个目录通常位于 `.app` 包内部。升级或替换新的 DMG / `.app` 后，旧 `.env` 不会自动迁移，所以看起来像“配置丢了”。

处理方式：

1. 升级前在桌面端设置页执行一次 `导出 .env`
2. 安装新版本后，在同一位置点击 `导入 .env`
3. 导入完成后等待设置页重新加载即可

## 分发给用户

Windows 分发现在有两种方式：

1. 安装包：分发 `apps/dsa-desktop/dist/` 下的 `*Setup*.exe`，用户安装时可自行选择目标目录
2. 免安装包：将 `apps/dsa-desktop/dist/win-unpacked/` 整个文件夹打包发给用户

使用 `win-unpacked` 免安装包时，用户只需：

1. 解压文件夹
2. 编辑 `.env` 配置 API Key 和股票列表
3. 双击 `Daily Stock Analysis.exe` 启动
