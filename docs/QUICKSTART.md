# 3 分钟快速上手（极简路径）

> 本地首次分析只需配置一个 AI API Key 和自选股 `STOCK_LIST`。行情可使用内置的免费数据源，通知可稍后配置。

---

## 选一条最适合你的入口

| 你是谁 | 推荐方式 | 前置要求 | 下一步 |
|---|---|---|---|
| 想用图形界面 | 桌面客户端（Windows / macOS） | 1 个 AI Key | [下载客户端](https://github.com/ZhuLinsen/daily_stock_analysis/releases) · [安装教程](beginner-client-setup.md) |
| 想定时跑日报 | GitHub Actions | 1 个 AI Key | [配置并运行每日股票分析](full-guide.md#github-actions-详细配置) |
| 想在本地运行 | 命令行 | Git、Python 3.11+（使用下面的默认模型） | [本地三步](#本地-3-步快速起步) |
| 想自托管 Web 工作台 | Docker Compose | Docker、1 个 AI Key | [部署指南](DEPLOY.md) |

---

## 本地 3 步快速起步

1. 获取代码并安装 Python 依赖。下方的 Modelflare 默认模型 `gpt-6.1-sol` 通过 Chat Completions 调用，使用 LiteLLM 1.98.1 或更新版本。

   ```bash
   git clone --depth 1 https://github.com/ZhuLinsen/daily_stock_analysis.git
   cd daily_stock_analysis
   python -m pip install -r requirements.txt "litellm>=1.98.1"
   ```

2. 运行 `cp .env.example .env`，编辑 `.env` 中的两项。将示例值替换为你的自选股和 [Modelflare](https://modelflare.dev/sign-up?utm_source=github&utm_campaign=daily_stock_analysis) API Key。

   ```dotenv
   STOCK_LIST=600519
   MODELFLARE_KEY=your_api_key
   ```

3. 手动运行一次个股分析。`--force-run` 允许在非交易日试跑。

   ```bash
   python main.py --no-market-review --no-notify --force-run
   ```

   成功后在 `reports/` 查看报告。只想先检查行情拉取（不触发大盘复盘与 LLM 调用）时，可运行 `python main.py --dry-run --no-market-review --force-run`。

---

## 按需进阶（跑通后再看）

- **Python 3.10 与其他模型**：[源码安装与模型配置](full-guide.md#安装依赖) · [LLM 配置指南](LLM_CONFIG_GUIDE.md)
- **推送与排障**：[通知渠道配置](notifications.md) · [常见故障 FAQ](FAQ.md)
- **Web 工作台**：[本地构建与启动](../README.md#方式二客户端配置教程--本地运行--docker-部署)
- **进阶能力**：[组合风险与暴露](portfolio-risk-exposure-dashboard.md) · [智能选股](screening-engine.md) · [决策信号](decision-signals.md)
- **全部文档**：[完整文档索引](INDEX.md) · [完整配置与部署指南](full-guide.md)
