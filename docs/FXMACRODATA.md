# FXMacroData 宏观数据工具

股票分析与聊天 Agent 的工具注册表已接入 FXMacroData。USD 数据目录、最近 90 天的指标历史与发布日历可免费使用，无需密钥、账户或信用卡。

如需可选的授权数据，在运行应用的环境中配置 `FXMACRODATA_API_KEY`；使用 GitHub Actions 定时分析时，将其保存为仓库 Secret `FXMACRODATA_API_KEY`，`00-daily-analysis.yml` 会把它映射到分析步骤环境。密钥不会进入工具参数、模型上下文或响应。启用 Agent 模式后，可查询 `fxmacrodata_data_catalogue`（`currency=USD`）、`fxmacrodata_indicator_history`（`currency=USD, indicator=policy_rate`）及 `fxmacrodata_release_calendar`。

多 Agent 模式下，情报 Agent 的原生工具允许列表提供固定客户端 v0.1.0 快照中的全部 72 个操作；风险和组合 Agent 提供与发布、宏观及跨市场风险相关的操作。各专业 Agent 仍遵守原有的工具访问限制。Codex 聊天后端只提供标记为可安全取消的工具，FXMacroData 工具不在其中，因此目前通过其他聊天后端和报告 Agent 使用。

集成保留公开 API 原始数据、发布时间、来源及推定时间标记。`records` 是用于展示的附加视图。市场共识、官方预测和 FXMacroData 生成的预测保持区分。数据不可用时返回明确状态，不填入模拟数据。

固定客户端 v0.1.0 内置快照中的 23 个 REST 操作及 49 个 MCP 工具的操作表、参数、安装及测试说明见 [English guide](FXMACRODATA_EN.md)。这两份文档同步介绍相同功能；完整操作名称保持英文。

[FXMacroData](https://fxmacrodata.com/?utm_source=github&utm_medium=referral&utm_campaign=open_source_integrations&utm_content=daily_stock_analysis_readme) · [API 文档](https://fxmacrodata.com/documentation/reference?utm_source=github&utm_medium=referral&utm_campaign=open_source_integrations&utm_content=daily_stock_analysis_docs)
