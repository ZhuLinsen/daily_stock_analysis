# 文档中心

> [!TIP]
> 第一次使用请从 [3 分钟快速上手指南](QUICKSTART.md) 选择桌面客户端、GitHub Actions、本地命令行或 Docker。

---

<a name="按场景选择"></a>
<a name="快速开始"></a>

## 新手入门

| 目标 | 推荐入口 | 说明 |
| --- | --- | --- |
| 跑通首次分析 | [3 分钟快速上手指南](QUICKSTART.md) | 从配置模型密钥到查看第一份报告 |
| **图形化桌面端小白教程** | [小白客户端安装与配置](beginner-client-setup.md) | 零命令行安装与常见问题 |
| **项目概览与核心功能** | [README](../README.md) | 项目定位、支持市场、快速开始 |
| **排查报错与运行问题** | [FAQ](FAQ.md) | 常见配置、行情源与运行故障排查 |

---

<a name="配置"></a>

## 日常运行与推送

| 我想要 | 先看 | 延伸阅读 |
| --- | --- | --- |
| 配置大模型和备用渠道 | [LLM 配置指南](LLM_CONFIG_GUIDE.md) | [服务商配置](llm-providers.md) · [LiteLLM YAML 示例](examples/litellm_config.example.yaml) |
| 配置推送通知 | [通知渠道配置](notifications.md) | [完整配置与部署指南](full-guide.md) |
| 定时运行分析 | [GitHub Actions 配置](full-guide.md#github-actions-详细配置) | [定时任务配置](full-guide.md#定时任务配置) |
| 处理数据源失败 / 确认市场支持边界 | [市场支持与边界](market-support.md) | [数据源稳定性图示](data-source-stability.md) · [数据中心](data-center-diagnostics.md) |
| 查询特定数据源 / 宏观工具配置 | [TickPlus 接入](tickplus.md) · [FXMacroData 说明](FXMACRODATA.md) | [Tushare 股票列表](TUSHARE_STOCK_LIST_GUIDE.md) |

---

<a name="使用专题"></a>

## 进阶投研能力

| 功能专题 | 文档 | 内容 |
| --- | --- | --- |
| **持仓风险与自选状态** | [组合风险与暴露看板](portfolio-risk-exposure-dashboard.md) · [自选股状态与下一步](watchlist-next-action.md) | 持仓风险、市场与币种暴露、首页自选股信号 |
| **智能选股与 ETF 轮动** | [智能选股引擎](screening-engine.md) · [ETF 轮动](etf-rotation.md) | 多因子/自然语言选股与 `--etf-rotation` 双动量策略 |
| **决策信号与实时告警** | [DecisionSignal 决策信号专题](decision-signals.md) · [实时告警中心](alerts.md) | AI 建议池、止损/观点盯盘规则与推送尝试 |
| **资讯与报告分享** | [资讯情报源](intelligence-sources.md) · [分享长图](share-images.md) | 资讯源配置、报告与分享图 |

---

<a name="部署与打包"></a>

## 部署与运维

- [完整配置与部署指南](full-guide.md)
- [部署指南](DEPLOY.md) · [云端 WebUI 部署](deploy-webui-cloud.md) · [Zeabur 部署](docker/zeabur-deployment.md)
- [桌面端打包](desktop-package.md)

---

<a name="参考与开发"></a>

## 集成与参考

- [Bot 命令与接入](bot-command.md) · [Bot 平台配置](bot/)
- [Grok Bot 集成](grok-bot-integration.md) · [Grok Bot Skill 示例](examples/grok_bot/README.md) · [OpenClaw 集成](openclaw-skill-integration.md)

<details>
<summary>展开查看 P0–P7 内部架构契约、API 规格与贡献指南</summary>

| 文档 | 说明 |
| --- | --- |
| [贡献指南](CONTRIBUTING.md) | Issue、PR、测试、文档同步和协作要求 |
| [API 规格](architecture/api_spec.json) | FastAPI OpenAPI 规格产物 |
| [个股研究聚合 API](stock-profile-api.md) | stock-profile 契约、分块质量状态与代码归一 |
| [ResearchArtifact 结构化产物](research-artifact.md) | structured_report 字段与旧报告兼容边界 |
| [选股解释契约](screening-explanations.md) | Why Selected / Why Now 的确定性解释边界 |
| [分析上下文包契约、运行态消费与可见性](analysis-context-pack.md) | P1/P2 内部契约、P3 Prompt 摘要消费、P4 历史/API/Web 低敏可见性、P5 数据质量评分、P6 迁移回滚。另含 #1386 阶段感知分析、迁移与回滚入口 |
| [Agent 流式事件与多策略契约](agent-stream-events.md) | 流式事件契约 · [多策略协同契约](multi-strategy-contract.md) · [轨迹评估](agent-trajectory-eval.md) |
| [运行诊断与可观测规范](run-diagnostics-p0.md) | [P0](run-diagnostics-p0.md) · [P1](run-diagnostics-p1.md) · [P2](run-diagnostics-p2.md) · [P3](run-diagnostics-p3.md) |
| [Web 设置草稿保护](settings-draft-protection.md) | 草稿保护机制与 [设置帮助维护](settings-help.md) |
| [图片识别 Prompt](image-extract-prompt.md) | 图片识别股票信息的 Prompt 与使用边界 |

</details>

[更新日志](CHANGELOG.md)

---

<a name="多语言"></a>

## 🌐 多语言文档

| 文档 | 内容 |
| --- | --- |
| [英文文档索引](INDEX_EN.md) | English documentation index |
| [英文 README](README_EN.md) | English project overview and quick start |
| [繁中 README](README_CHT.md) | 繁體中文項目概覽與快速開始 |
