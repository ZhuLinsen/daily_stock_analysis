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

## GitHub CI 自动打包并发布 Release

仓库已支持通过 GitHub Actions 自动构建桌面端并上传到 GitHub Releases：

- 工作流：`.github/workflows/desktop-release.yml`
- 触发方式：
  - 推送语义化 tag（如 `v3.2.12`）后自动触发
  - 在 Actions 页面手动触发并指定 `release_tag`
- 产物：
  - Windows 安装包：`daily-stock-analysis-windows-installer-<tag>.exe`
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

打包产物位于 `apps/dsa-desktop/dist/`。

## 目录结构

打包后用户拿到的目录结构（便携模式）：

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
- 用户需要编辑 `.env` 配置以下内容：
  - `GEMINI_API_KEY` 或 `OPENAI_API_KEY`：AI 分析必需
  - `STOCK_LIST`：自选股列表（逗号分隔）
  - 其他可选配置参考 `.env.example`

## 常见问题

### 启动后一直显示 "Preparing backend..."

1. 检查 `logs/desktop.log` 查看错误信息
2. 确认 `.env` 文件存在且配置正确
3. 确认端口 8000-8100 未被占用

### 后端启动报 ModuleNotFoundError

PyInstaller 打包时缺少模块，需要在 `scripts/build-backend.ps1` 中增加 `--hidden-import`。

### UI 加载空白

确认 `static/index.html` 存在，如不存在需重新构建 React UI。

## 分发给用户

将 `apps/dsa-desktop/dist/win-unpacked/` 整个文件夹打包发给用户即可。用户只需：

1. 解压文件夹
2. 编辑 `.env` 配置 API Key 和股票列表
3. 双击 `Daily Stock Analysis.exe` 启动
