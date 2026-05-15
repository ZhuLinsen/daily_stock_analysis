# 文档中心

这里是项目文档入口。README 负责项目概览和快速开始；更完整的配置、部署、功能说明和排障内容从这里进入。

## 按场景选择

| 我想要 | 先看 | 继续看 |
| --- | --- | --- |
| 快速了解项目能做什么 | [README](../README.md) | [完整配置与部署指南](full-guide.md) |
| 第一次把项目跑起来 | [README](../README.md) | [完整配置与部署指南](full-guide.md) |
| 配置大模型渠道 | [LLM 配置指南](LLM_CONFIG_GUIDE.md) | [LLM 服务商配置指南](llm-providers.md) |
| 配置推送通知 | [通知能力基线](notifications.md) | [完整配置与部署指南](full-guide.md) |
| 部署到服务器或云平台 | [部署指南](DEPLOY.md) | [云端 WebUI 部署](deploy-webui-cloud.md)、[Zeabur 部署](docker/zeabur-deployment.md) |
| 使用 Bot / IM 接入 | [Bot 命令与接入](bot-command.md) | [Bot 平台配置](bot/) |
| 排查运行问题 | [FAQ](FAQ.md) | [更新日志](CHANGELOG.md) |
| 参与开发或提交 PR | [贡献指南](CONTRIBUTING.md) | [API 规格](architecture/api_spec.json) |

## 快速开始

| 文档 | 内容 |
| --- | --- |
| [README](../README.md) | 项目定位、核心能力、快速开始、推送效果 |
| [完整配置与部署指南](full-guide.md) | 环境准备、运行方式、配置说明、部署路径和常见问题 |
| [FAQ](FAQ.md) | 常见配置、模型、通知、部署和运行问题 |
| [更新日志](CHANGELOG.md) | 版本变化、能力调整和迁移说明 |

## 配置

| 文档 | 内容 |
| --- | --- |
| [LLM 配置指南](LLM_CONFIG_GUIDE.md) | 大模型渠道、三层配置、Web 设置页和常见模型配置 |
| [LLM 服务商配置指南](llm-providers.md) | Provider 预设、Actions 映射、错误分类和诊断建议 |
| [LiteLLM YAML 示例](examples/litellm_config.example.yaml) | LiteLLM 多渠道配置示例 |
| [通知能力基线](notifications.md) | 企业微信、飞书、Telegram、Discord、Slack、邮件等通知渠道配置 |
| [Tushare 股票列表指南](TUSHARE_STOCK_LIST_GUIDE.md) | Tushare 股票列表相关配置和使用说明 |

## 使用专题

| 文档 | 内容 |
| --- | --- |
| [Bot 命令与接入](bot-command.md) | Bot 命令、Webhook、平台接入和回调说明 |
| [Bot 平台配置](bot/) | 飞书、钉钉、Discord 等 Bot 配置截图和补充说明 |
| [图片识别 Prompt](image-extract-prompt.md) | 图片识别股票信息的 Prompt 与使用边界 |
| [OpenClaw Skill 集成](openclaw-skill-integration.md) | OpenClaw / Skill 外部集成说明 |

## 部署与打包

| 文档 | 内容 |
| --- | --- |
| [部署指南](DEPLOY.md) | 服务器部署、Docker、systemd、Supervisor 等部署方式 |
| [云端 WebUI 部署](deploy-webui-cloud.md) | 云服务器访问 WebUI 的部署说明 |
| [Zeabur 部署](docker/zeabur-deployment.md) | Zeabur 平台部署说明 |
| [桌面端打包说明](desktop-package.md) | Electron 桌面端和 Web 构建产物打包说明 |

## 参考与开发

| 文档 | 内容 |
| --- | --- |
| [API 规格](architecture/api_spec.json) | FastAPI OpenAPI 规格产物 |
| [贡献指南](CONTRIBUTING.md) | Issue、PR、测试、文档同步和协作要求 |

## 多语言

| 文档 | 内容 |
| --- | --- |
| [英文文档索引](INDEX_EN.md) | English documentation index |
| [英文 README](README_EN.md) | English project overview and quick start |
| [繁中 README](README_CHT.md) | 繁體中文項目概覽與快速開始 |
