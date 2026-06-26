# 资讯 / 情报源 MVP

Issue #1707 的首版能力聚焦“合规资讯源采集、本地沉淀、可查询证据”，不把 RSS/Atom 混入按需搜索语义，也不默认新增独立舆情页。

## 能力范围

- 支持配置 RSS / Atom HTTP(S) 资讯源。
- 支持 NewsNow HTTP JSON 源，默认内置财联社热门、雪球热门股票、华尔街见闻快讯、金十数据和格隆汇事件等主流财经源。
- 支持查询内置 RSS/Atom/NewsNow 模板，并可从模板创建可测试、可启停的资讯源；也可以一键创建全部内置默认源。
- 保存资讯源配置、启用状态、作用域和最近一次拉取状态。
- 拉取条目落库到 `intelligence_items`，保存标题、摘要、URL、来源、发布时间、拉取时间、市场与作用域。
- 按 URL 去重；无 URL 条目使用 `no-url:intel:<hash>` 兜底键。
- 支持 `symbol` / `market` / `sector` 作用域，以及 `cn` / `hk` / `us` / `jp` / `kr` / `tw` / `global` 市场标记。
- 拉取批处理采用 fail-open：单个源失败不会阻塞其他源或主分析链路。
- 支持 retention 清理，避免资讯池无限增长。

## 安全边界

自定义 URL 会做基础校验：

- 只允许绝对 `http` / `https` URL；
- 禁止 URL 中携带 username/password；
- 禁止 `localhost`、`.local`、回环地址、内网地址、链路本地地址、保留地址、共享地址段和组播地址；
- 解析与拉取阶段显式禁用环境代理（如 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`），避免通过环境代理绕过校验边界；
- 实际连接阶段会再次校验目标主机 DNS 解析结果，避免校验后解析漂移到受限地址；
- 重定向后的最终 URL 也会再次校验；
- 错误消息会脱敏常见 `token` / `key` / `secret` 查询参数。

明确非目标：不做反爬、模拟登录、Cookie 抓取或非授权门户直抓。

## 配置项

```env
NEWS_INTEL_RETENTION_DAYS=30
NEWS_INTEL_FETCH_TIMEOUT_SEC=8
NEWS_INTEL_MAX_ITEMS_PER_SOURCE=50
NEWSNOW_BASE_URL=https://newsnow.busiyi.world
```

`NEWSNOW_BASE_URL` 用于拼出 `GET {NEWSNOW_BASE_URL}/api/s?id=<source_id>`。

**外部依赖兼容性说明：**

- **官方项目与部署指南**：https://github.com/qqhann/newsnow
- **当前默认值** `https://newsnow.busiyi.world` 是公开示例实例，**非官方部署**，存在以下风险：
  - 可能因官方维护、限流或停止服务而不可用
  - 不保证稳定性、可靠性或数据准确性，仅用于演示和测试
  - 每个用户都指向同一公开实例，可能遭遇限流
- **生产环境强烈建议**：自建 NewsNow 实例或接入已确认可控的私有/企业部署，以确保稳定性和数据可靠性

**API 契约兼容性核验（部署前必做）：**

- 验证基础可达性和返回格式：
  ```bash
  curl -sS "${NEWSNOW_BASE_URL}/api/s?id=cls-hot" | python -c "import sys, json; data=json.load(sys.stdin); assert isinstance(data, dict) and isinstance(data.get('items'), list); print('OK')"
  ```
- 详细字段兼容性可参考自动化测试：`test_newsnow_source_fetches_json_items`，涵盖 `status`、`id`、`items[].title`、`items[].url`/`mobileUrl`、`items[].pubDate`/`items[].extra.date` 等字段
- **部署实例不在自动化上线保障范围内**；如果依赖公开示例实例，部署前务必在实际生产环境执行上述验证

## API

所有接口位于 `/api/v1/intelligence`。

- `POST /sources`：创建资讯源。
- `GET /sources`：查询资讯源。
- `GET /sources/templates?market=hk`：查询内置资讯源模板。
- `POST /sources/templates/{template_id}`：从内置模板创建资讯源，可覆盖名称、启用状态、作用域和说明。
- `POST /sources/defaults`：一键创建全部内置默认源；接口幂等，已存在的同名源会返回 `created=false`，不会重复插入。默认不传 `enabled` 时以 `false` 创建；如需默认启用可传 `{ "enabled": true }`。
- `POST /sources/test`：测试 payload，不落库。
- `POST /sources/{source_id}/fetch?dry_run=false`：拉取单个源。
- `POST /sources/fetch-enabled`：fail-open 拉取全部启用源。
- `GET /items?scope_type=market&market=cn&days=7`：查询资讯条目。

## NewsNow 默认源

NewsNow 不是 RSS，而是一个聚合热点平台。DSA 直接按 HTTP API 读取它的 JSON 返回，不需要 MCP：

```text
GET {NEWSNOW_BASE_URL}/api/s?id=cls-hot
```

本 PR 先接入以下财经相关默认源，保证流程能从“源配置 -> 拉取 -> 落库 -> 分析读取”跑通：

- `cls-hot`：财联社热门，偏 A 股和题材热点。
- `xueqiu-hotstock`：雪球热门股票，偏个股关注度。
- `wallstreetcn-quick`：华尔街见闻快讯，偏宏观、商品和市场事件。
- `jin10`：金十数据，偏全球宏观和外盘事件。
- `gelonghui`：格隆汇事件，偏港股和中概股上下文。

如果需要更多国内平台，可以继续通过 `POST /sources` 手动添加 NewsNow 源，`source_type=newsnow`，`url` 填 `https://<your-newsnow>/api/s?id=<source_id>`。如果更偏好 RSS，也可以用 RSSHub 等合规 RSS 源继续按 `source_type=rss` 接入。

## 后续接入建议

首版基线之上，分析链路会 best-effort 读取本地资讯池：

- 个股传统分析会优先读取 `symbol=<股票代码>` 的资讯，并补充同市场 `market` 级资讯；内容追加到既有 `news_context`，随 AnalysisContextPack 摘要和历史 `news_content` 保存。
- Agent 分析同样通过 `news_context` 注入本地资讯证据，避免 Agent 必须重新搜索才能看到已沉淀新闻。
- 大盘复盘会把同市场 `market` 级资讯合并到市场新闻列表，Prompt、结构化 payload 和报告 news 字段都能看到来源链接。
- 本次能力仅新增本地资讯消费路径，不改模型名、provider/base URL、默认模型策略、回退策略、`save_context_snapshot` 前清理逻辑或运行时配置语义；兼容现有部署配置，回滚方式为清退本地资讯接入入口或移除本地资讯源配置/数据。

后续 PR 可以继续完善 NewsNow HTTP provider、报告 evidence 展示和 Web 设置/报告查看入口。

## 兼容性与回滚说明（Issue #1707）

- 本功能不改动第三方 LLM provider 语义，不新增 provider/model/base URL/默认模型策略/运行时路由或配置迁移分支。
- 结构化检测提示中的模型/API 兼容风险在本次改动中不成立：`news_context` 注入链路仅复用现有 LLM 分析输入构造流程（`src/core/pipeline.py`、`src/market_analyzer.py`、`src/analyzer.py`），且不新增 `.env` 写入、保存前清理、清空/回填逻辑。
- 回滚方式：`revert` 本 PR；如需降级配置，仅需停用并移除本地资讯源配置（含 `sources` 表与 `intelligence_items` 存量）即可，不影响原有模型、provider 或其它历史分析链路。

## PR 描述可复用内容（Issue #1707）

- Refs: `#1707`
- 兼容性结论：本次仅新增本地资讯消费链路，不改模型名/provider/base URL/默认模型策略/回退策略/保存前清理逻辑/运行时配置迁移。`news_context` 与 `market_review_payload` 的扩展为 best-effort 追加，不影响既有契约与兼容性边界。
- 回滚方案：最小回滚路径为 `revert this PR`；如仅需降级接入，可在运行时停用并清理本地资讯源（`sources` 与 `intelligence_items`）。
