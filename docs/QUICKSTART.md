# 3 分钟快速上手（极简路径）

> 第一次使用 **不需要** 看懂 `.env.example` 的 1,100+ 行参数，也 **不需要** 配置复杂的推送、数据源或 Agent 选项。
> 跑通首次分析**只需 2 样东西**：① 1 个 AI API Key　② 自选股列表 `STOCK_LIST`（免费行情源内置兜底）。

---

## 选一条最适合你的入口

| 你是谁 | 推荐方式 | 前置要求 | 下一步 |
|---|---|---|---|
| **不想写代码 / 个人投资** | **桌面客户端**（Windows / macOS） | 1 个 AI Key | 下载 [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases)，或看 [小白教程](beginner-client-setup.md) |
| **零服务器自动跑日报** | **GitHub Actions** | 1 个 Repository Secret | Fork 仓库 → 添加 `MODELFLARE_KEY` / `GEMINI_API_KEY` → 开启 Workflows |
| **本地终端 / WebUI** | **极简配置 + Web 工作台** | Python 3.10+ | 运行下方 **3 条步骤** |
| **容器部署** | **Docker Compose** | Docker | 参考 [部署指南](DEPLOY.md) |

---

## 本地 3 步快速起步

```bash
# 1. 复制配置模板并仅填写 AI Key 与自选股（见下方 3 行示例）
cp .env.example .env

# 2. 不耗费 AI 配额测试行情抓取链路是否畅通
python main.py --dry-run

# 3. 启动 WebUI 工作台（或运行单只分析：python main.py --stocks 600519）
python main.py --serve-only
```

启动后访问 `http://127.0.0.1:8000` 查看分析任务与历史决策报告。

---

## 最简 `.env` 核心项示例（其余参数均留默认即可）

```ini
STOCK_LIST=600519,hk00700,AAPL
GEMINI_API_KEY=
# 如需推送到微信/飞书，再填 1 行 WECHAT_WEBHOOK_URL= 或 FEISHU_WEBHOOK_URL=
```

---

## 按需进阶（跑通后再看）

- **配置与推送**：[LLM 配置指南](LLM_CONFIG_GUIDE.md) · [通知渠道配置](notifications.md) · [常见故障 FAQ](FAQ.md)
- **进阶能力**：[组合风控与压力测试](portfolio-risk-exposure-dashboard.md) · [智能选股](screening-engine.md) · [决策信号](decision-signals.md)
- **全部文档**：[完整文档索引](INDEX.md) · [完整配置与部署指南](full-guide.md)
