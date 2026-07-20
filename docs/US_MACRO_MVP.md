# 美国宏观 MVP

## 运行

在项目根目录配置 `FRED_API_KEY` 后运行：

```bash
python3 main.py --us-macro --dry-run --no-notify
```

该命令不会发送通知，会生成 `reports/us_macro_report.md`，并保存到 `DATABASE_PATH`（默认 `./data/stock_analysis.db`）的 `analysis_history` 表，报告类型为 `global_macro`。

## 数据与降级

FRED 观测使用最近一个非空值；`observation_date` 是原始观测日期，`fetched_at` 是抓取时间，两者不混用。日频观测超过 7 个自然日标记为过期。Yahoo Finance 数据为空或受限流时，报告保留缺失状态并降低规则置信度，不填补或伪造数据。

同一自然日重复运行会更新同一 `us_macro_YYYY-MM-DD` 历史记录，而非创建重复记录。FRED 或 Yahoo 单源失败不会阻断基础报告；SQLite 写入失败会使本次命令失败，不会宣称已保存。

## 飞书展示预览

添加 `--us-macro-preview-notification --no-notify` 可只在本地日志预览三段美国宏观消息，不发送飞书。展示层会将方向、单位与指标名称中文化；政策利率上下限合并为区间，2Y–10Y 利差使用 `bp`。该适配不修改原始快照、规则分数、方向、置信度或历史记录。

## GitHub Actions 手动验证

`.github/workflows/us-macro-manual.yml` 只支持 `workflow_dispatch`，不包含定时触发。首次运行保持 `send_notification=false`；输入默认只分析 `600584,300255,000560`，并独立生成美国宏观报告。需要配置 Repository Secrets：`FRED_API_KEY`、`DEEPSEEK_API_KEY`、`FEISHU_WEBHOOK_URL`、`FEISHU_WEBHOOK_SECRET`；还需配置非敏感 Repository Variable `LITELLM_MODEL`。工作流上传 Markdown 报告、日志摘要和 SQLite 副本为 Artifact，绝不提交这些运行产物回仓库。

## 可选网络测试

默认 pytest 不访问网络。显式执行真实 FRED 冒烟测试：

```bash
RUN_NETWORK_TESTS=true python3 -m pytest -m network tests/test_us_macro_network.py
```

测试不会输出或快照 API Key，也不发送通知。
