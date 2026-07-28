# Personal Mainland Demo Status

更新时间：2026-07-28

## 基线

- 基线分支：`main`，工作分支：`feature/personal-mainland-demo`。
- 仓库已有 A 股、港股、美股、自选股、新闻搜索、SQLite、LiteLLM、企业微信、飞书、FastAPI、React WebUI、历史记录和调度能力。
- 初始离线测试命令在收集阶段被本机缺失的 `newspaper3k` 阻断：`tests/test_news_intel.py` 导入 `src.search_service` 时出现 `ModuleNotFoundError: newspaper`；不是断言失败。
- 完整 `requirements.txt` 安装在 Windows 上被 LiteLLM 源码构建/Rust 环境阻断。随后使用现有 Python 3.11 与最小测试依赖完成本功能的确定性验证。
- `python main.py --help` 的入口 smoke 同样因不完整依赖中的 `fake_useragent` 缺失而在原有 Futu/data-provider 顶层导入处停止；`main.py` 与全部新增 Python 文件已通过 `py_compile`。

## 已完成

- 同一 SQLite/SQLAlchemy 基础上的 `personal_news_articles`、`personal_news_hashes`、`personal_news_analyses`、`personal_news_push_records`、`personal_news_settings` 与 `personal_news_provider_status`。
- URL、规范标题和股票/标题/六小时时间窗三层持久去重。
- 确定性 0–100 重要性评分；LLM 不参与打分。
- 复用现有 SearchService、LiteLLM、企业微信、飞书、FastAPI 与 React WebUI 的专用编排。
- 严格 Pydantic JSON 输出、一次修复重试、无来源拒绝和无效分析禁止推送。
- `python main.py --news-watch` 单进程轮询、非重入、单轮失败隔离、结构化日志和优雅 Ctrl+C 停止。
- `/api/v1/personal-news` 列表、详情、Provider 状态和手动运行 API。
- `/news` 移动端列表、`/news/{id}` 详情、Provider 状态、原始来源链接。
- manifest、192/512 SVG 图标、standalone PWA 和历史新闻简单离线缓存。

## 验证结果

- `pytest tests/test_personal_news_monitor.py -q`：11 passed。
- `npm run lint`：通过。
- `npm run build`：通过，生成 `static/`，包含 `NewsPage` 独立 chunk 与 PWA 公共文件。
- 初始仓库新闻测试未重跑完整套件，原因见“基线”。

## 外部阻挡与限制

- 未提供真实新闻搜索、LLM API Key、企业微信或飞书 Webhook，因此在线抓取、真实模型响应和真实推送未执行；测试使用 Fake Provider。
- 未生成 Capacitor/APK：第一阶段明确以 PWA 为交付目标，且未配置 Android SDK/Java 签名环境。
- `npm install` 报告依赖树有 16 个漏洞（1 low、2 moderate、13 high）；未执行可能引入破坏性升级的 `npm audit fix`。
- 这是 15 分钟级个人新闻雷达，不是交易所级实时行情系统，不提供自动交易、确定性买卖建议或目标价。
