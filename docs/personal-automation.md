# Fork 自动更新与 Telegram 推送说明

本仓库在上游 `ZhuLinsen/daily_stock_analysis` 基础上保留盘中动态选股和 Telegram 推送定制，并通过 GitHub Actions 实现自动运行、自动更新和本地随时触发。

## 运行时间

所有时间均为北京时间，仅在周一至周五由 GitHub Actions 唤醒；主程序仍会检查 A 股交易日，节假日不执行分析和推送。为降低 GitHub 共享 Runner 的调度漂移，每次提前 5 分钟唤醒，并在工作流内等待到目标时刻。

| 推送时点 | 运行模式 | 内容 |
| --- | --- | --- |
| 09:47 | `stocks-only` | 全市场动态筛选约 10 支候选股，完成个股分析并推送 |
| 14:07 | `stocks-only` | 重新获取盘中行情、重新筛选候选股并推送 |
| 15:20 | `market-only` | 使用收盘后数据生成当日大盘复盘并推送 |

工作流文件为 `.github/workflows/00-daily-analysis.yml`，手动运行时仍可选择 `full`、`stocks-only` 或 `market-only`，并可用 `force_run` 跳过交易日检查进行联调。

## 本地随时触发

macOS 双击仓库根目录的 `trigger_daily_stock_analysis.command`，默认触发 `full` 模式并打开仓库 Actions 页面。该脚本只负责触发云端 GitHub Actions，不依赖本机 Python 环境，因此本机无需安装项目依赖；仅需安装并登录 GitHub CLI。

也可在终端中指定模式：

```bash
./trigger_daily_stock_analysis.command stocks-only
./trigger_daily_stock_analysis.command market-only
./trigger_daily_stock_analysis.command full --force
```

## 自动保持最新

- `Sync Upstream` 每日北京时间 05:17 检查上游 `main`。发现新提交后，先合并并校验本仓库的三时点推送、动态选股和启动器契约，校验通过后更新本仓库 `main`；发生冲突、校验失败或推送失败时停止更新并创建维护 Issue。
- Dependabot 每周检查 Python、Web、桌面端、GitHub Actions 和 Docker 依赖。非主版本更新在仓库 CI 通过后自动合并；主版本更新保留人工兼容性审查。
- `.github/scripts/validate_personal_automation.py` 是上游同步的失效保护，防止上游更新静默覆盖本仓库关键定制。

## 前置设置

仓库需要在 `Settings -> Actions -> General` 中允许工作流具有读写权限，并启用自动合并。Telegram 继续使用现有 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 和可选的 `TELEGRAM_MESSAGE_THREAD_ID` Secrets。

## 回滚

如自动更新导致异常，可在 GitHub 上回退对应的上游合并提交；若仅需暂停自动更新或定时推送，可在 Actions 中临时禁用 `Sync Upstream` 或 `每日股票分析` 工作流。不要删除 Telegram Secrets，以便恢复后继续使用。
