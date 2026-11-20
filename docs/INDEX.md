# 文档中心

> [!TIP]
> **新手建议从 [3 分钟快速上手指南](QUICKSTART.md) 开始** —— 首次运行只需 `1 个 AI Key + STOCK_LIST` 即可跑通。无需通读 `.env.example` 全文。

---

## 🚀 第一步：3 分钟快速上手

| 目标 | 推荐入口 | 说明 |
| --- | --- | --- |
| **3 分钟极简跑通（强烈推荐）** | [3 分钟快速上手指南](QUICKSTART.md) | 只配 1 个 AI Key + 自选股的最小路径 |
| **图形化桌面端小白教程** | [小白客户端安装与配置](beginner-client-setup.md) | 零命令行安装与常见问题 |
| **项目概览与核心功能** | [README](../README.md) | 项目定位、支持市场、快速开始 |
| **排查报错与运行问题** | [FAQ](FAQ.md) | 常见配置、行情源与运行故障排查 |

---

## ⚙️ 第二步：常用配置与部署

| 我想要 | 先看 | 延伸阅读 |
| --- | --- | --- |
| 配置大模型 / 多渠道容灾 | [LLM 配置指南](LLM_CONFIG_GUIDE.md) | [LLM 服务商配置指南](llm-providers.md) |
| 配置推送通知（微信/飞书/TG/邮件） | [通知能力基线](notifications.md) | [完整配置与部署指南](full-guide.md) |
| 部署到云服务器 / Docker / Zeabur | [部署指南](DEPLOY.md) | [云端 WebUI 部署](deploy-webui-cloud.md) · [Zeabur 部署](docker/zeabur-deployment.md) |
| 处理数据源失败 / 确认市场支持边界 | [市场支持与边界](market-support.md) | [数据源稳定性图示](data-source-stability.md) · [数据中心](data-center-diagnostics.md) |
| 查询特定数据源 / 宏观工具配置 | [TickPlus 接入](tickplus.md) · [FXMacroData 说明](FXMACRODATA.md) | [Tushare 股票列表](TUSHARE_STOCK_LIST_GUIDE.md) |

---

## 📈 第三步：进阶投研、Agent 与可验证战绩

| 功能专题 | 文档 | 内容 |
| --- | --- | --- |
| **持仓风险与自选状态** | [组合风险与暴露看板](portfolio-risk-exposure-dashboard.md) · [自选股状态与下一步](watchlist-next-action.md) | 持仓暴露分析、相关性压力测试与首页三段信号 |
| **智能选股与 ETF 轮动** | [智能选股引擎](screening-engine.md) · [ETF 轮动](etf-rotation.md) | 多因子/自然语言选股与 `--etf-rotation` 双动量策略 |
| **决策信号与实时告警** | [DecisionSignal 决策信号专题](decision-signals.md) · [实时告警中心](alerts.md) | AI 建议池、止损/观点盯盘规则与推送尝试 |
| **Bot / 外部 Agent 集成** | [Bot 命令与接入](bot-command.md) · [Bot 平台配置](bot/) | 企业微信/飞书/TG/Discord/Slack 命令 · [Grok Bot](grok-bot-integration.md) · [OpenClaw](openclaw-skill-integration.md) · [Grok Skill](examples/grok_bot/README.md) |
| **完整指南与专项功能** | [完整配置与部署指南](full-guide.md) | 含 [分享长图](share-images.md) · [资讯情报源](intelligence-sources.md) · [桌面端打包](desktop-package.md) · [Web 设置草稿保护](settings-help.md) |

---

## 🛠️ 开发者参考与内部契约（普通用户可跳过）

<details>
<summary>展开查看 P0–P7 内部架构契约、API 规格、贡献指南与更新日志</summary>

| 文档 | 说明 |
| --- | --- |
| [贡献指南](CONTRIBUTING.md) | Issue、PR、测试、文档同步和协作要求 |
| [API 规格](architecture/api_spec.json) | FastAPI OpenAPI 规格产物 |
| [更新日志](CHANGELOG.md) | 版本变化、能力调整和迁移说明 |
| [LiteLLM YAML 示例](examples/litellm_config.example.yaml) | LiteLLM 多渠道配置示例 |
| [个股研究聚合 API](stock-profile-api.md) | stock-profile 契约、分块质量状态与代码归一 |
| [ResearchArtifact 结构化产物](research-artifact.md) | structured_report 字段与旧报告兼容边界 |
| [选股解释契约](screening-explanations.md) | Why Selected / Why Now 的确定性解释边界 |
| [分析上下文包契约](analysis-context-pack.md) | P1–P6 内部上下文包契约、评分与回滚锚点 |
| [Agent 流式事件与多策略契约](agent-stream-events.md) | 流式事件契约 · [多策略协同契约](multi-strategy-contract.md) · [轨迹评估](agent-trajectory-eval.md) |
| [运行诊断与可观测规范](run-diagnostics-p0.md) | [P0](run-diagnostics-p0.md) · [P1](run-diagnostics-p1.md) · [P2](run-diagnostics-p2.md) · [P3](run-diagnostics-p3.md) |
| [Web 设置帮助与草稿保护](settings-draft-protection.md) | Web 设置页草稿保护机制 |
| [图片识别 Prompt](image-extract-prompt.md) | 图片识别股票信息的 Prompt 与使用边界 |

</details>

---

## 🌐 多语言文档

| 文档 | 内容 |
| --- | --- |
| [英文文档索引](INDEX_EN.md) | English documentation index |
| [英文 README](README_EN.md) | English project overview and quick start |
| [繁中 README](README_CHT.md) | 繁體中文項目概覽與快速開始 |
