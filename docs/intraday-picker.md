# 盘中实时 AI 选股

盘中选股是一个独立、无 UI 依赖的后台流程。它不会改变原有 DSA 单股分析、AlphaSift Web 选股或桌面端交互。

## 流程

```text
09:35 / 09:45 / 09:55
        ↓
AlphaSift deterministic screen
capital_heat + volume_breakout
balanced_alpha 仅作为质量参考
        ↓
stock_analysis 风格确认规则
        ↓
通达信 5 分钟数据
        ↓
过去 20 个交易日同一时点 RVOL_TIME
        ↓
透明盘中评分
        ↓
Top10 立即推送
        ↓
DSA TaskQueue 后台 brief / intraday 分析
notify=false，避免 10 条个股推送
        ↓
65% 盘中分 + 35% DSA 分
        ↓
Top5 汇总推送
```

## 模块边界

业务层在 `src/services/intraday_picker/`：

- `models.py`：纯数据结构。
- `metrics.py`：RVOL、价格强度、日内位置等纯计算。
- `scoring.py`：透明评分与惩罚。
- `stock_analysis_rules.py`：候选确认规则，不做第二次全市场扫描。
- `orchestrator.py`：只编排 Port，不直接 import AlphaSift/Pytdx/TaskQueue/通知实现。
- `final_ranker.py`：盘中分与 DSA 分合成。

现有系统只能通过 `adapters/` 接入：

- `alphasift_adapter.py`
- `tdx_intraday_adapter.py`
- `sqlite_history_repository.py`
- `dsa_task_queue_adapter.py`
- `notification_adapter.py`
- `run_state_repository.py`

修改某个 concrete provider 时，不应修改 `metrics.py` / `scoring.py` / `orchestrator.py`。

## 配置

将以下内容加入本地 `.env`：

```bash
INTRADAY_PICKER_ENABLED=true
INTRADAY_PICKER_PROFILE=strong_start
INTRADAY_PICKER_TIMES=09:35,09:45,09:55
INTRADAY_PICKER_TOP_N=10
INTRADAY_FINAL_TOP_N=5
INTRADAY_BASELINE_DAYS=20
INTRADAY_DSA_ENABLED=true
INTRADAY_DSA_REPORT_TYPE=brief
INTRADAY_DSA_CACHE_MINUTES=20
INTRADAY_NOTIFY_PRELIMINARY=true
INTRADAY_NOTIFY_FINAL=true
```

AlphaSift 仍需按原项目方式启用：

```bash
ALPHASIFT_ENABLED=true
```

## 手动验证

只跑选股，不发送通知、不提交 DSA：

```bash
python scripts/intraday_picker_runner.py --once --at 09:45 --dry-run
```

真实执行一轮并将 Top10 送入 DSA：

```bash
python scripts/intraday_picker_runner.py --once --at 09:45
```

强制重跑同一个 run id：

```bash
python scripts/intraday_picker_runner.py --once --at 09:45 --force
```

## 自动运行

常驻早盘 worker：

```bash
python scripts/intraday_picker_runner.py
```

Runner 使用 `Asia/Shanghai` 判断 09:35 / 09:45 / 09:55，不依赖 DSA App 是否打开。

Windows 可安装计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_intraday_picker_task.ps1
```

卸载：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_intraday_picker_task.ps1
```

当前安装脚本的启动时钟使用 Windows 本机时间；如果 Windows 时区不是中国标准时间，请通过 `-StartTime` 指定与上海 09:24 对应的本地时间。真正的三次选股仍由 runner 使用 `Asia/Shanghai` 二次校验。

## RVOL_TIME

V1 不为 5200+ 股票建立分钟数据库。AlphaSift 先把全市场压缩到候选池，再仅为候选拉取通达信 5 分钟数据。

```text
RVOL_TIME =
今天 09:30 至当前触发时点累计成交额
÷
过去交易日同一时点累计成交额中位数
```

- 历史 >= 10 日：正常置信度。
- 历史 5–9 日：降置信度。
- 历史 < 5 日：RVOL 缺失，流程继续，按中性分处理。

缓存位于：

```text
data/intraday_picker/intraday_history.sqlite3
```

## 失败降级

- 单个 AlphaSift 策略失败：其他策略继续。
- 通达信失败：该候选没有 RVOL，但仍可排名。
- 板块字段缺失：使用中性分。
- 通知失败：不阻断 DSA。
- 单个 DSA 分析失败：其他候选继续。
- DSA 全部未完成：Top5 回退为盘中分排序。

## 注意

盘中 Top10 是量价/策略候选，不等于买入信号。Top5 也只是研究与策略验证输出，不构成投资建议。
