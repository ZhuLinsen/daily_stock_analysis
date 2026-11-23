---
name: "stock_analyzer"
description: "分析股票和市场。当用户想要分析单个或多个股票，或进行市场复盘时调用。"
---

# 股票分析器

本技能驱动**已部署并配置好的** [daily_stock_analysis (DSA)](https://github.com/ZhuLinsen/daily_stock_analysis) 检出或正在运行的 DSA 服务；它本身**不包含** `src/` 运行时。市场安装的插件缓存通常只有 `./plugin`，在普通项目目录直接 `import src...` 会得到 `ModuleNotFoundError`。

## 运行前提（调用前必做）

1. **确认存在可用的 DSA 环境**（完整仓库检出且已按指南配置 `.env`，或用户已有可调用的 DSA API 服务）。
2. **定位检出路径**（任选其一）：
   - 询问用户本机 DSA 仓库路径；
   - 读取环境变量 `DSA_REPO_ROOT`（指向仓库根目录，含 `src/` 与 `.env`）；
   - 若当前工作目录已是 DSA 根目录，可直接使用。
3. **再执行示例代码**：必须先 `os.chdir(repo_root)`（或等价地在该根目录启动进程），再将该根目录加入 `sys.path` / `PYTHONPATH`。仅改 `sys.path` 不够：默认相对 `DATABASE_PATH` 与大盘复盘锁按**进程工作目录**解析，不 `chdir` 会导致插件与 Web 锁住不同文件、写入不同 SQLite。
4. **对话内大盘复盘（不推送）**：需要检出已支持 `perform_market_review(..., send_notification=...)`（本仓库较新提交；例如 v3.35.0 尚不支持）。若不支持，先更新检出，**不要**回退为无该参数的调用（旧签名默认会推送）。
5. **若无法定位或未部署**：停止分析，向用户说明本技能只驱动现有 DSA 安装，并指向部署指南：
   - 中文：[完整配置与部署指南](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md)
   - English: [Full Guide](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide_EN.md)
6. **可选 HTTP**：若用户已启动 API（如 `python main.py --serve-only`），也可按 [OpenClaw / HTTP 对接](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/openclaw-skill-integration.md) 与 [Grok Bot 对接](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/grok-bot-integration.md) 通过 `DSA_BASE_URL` 调用 REST。对话内**不要推送**时：个股 `POST /api/v1/analysis/analyze` 须显式传 `"notify": false`（该接口默认 `notify: true`）；大盘复盘 `POST /api/v1/analysis/market-review` 须显式传 `"send_notification": false`（该接口读 `send_notification`，默认 `true`，**忽略** `notify`）。省略对应字段会向已配置渠道推送。

本技能基于 `src/services/analyzer_service.py` 的逻辑，提供分析股票和整体市场的功能。

## 输出结构 (`AnalysisResult`)

分析函数返回一个 `AnalysisResult` 对象（或其列表），该对象具有丰富的结构。以下是其关键组件的简要概述，并附有真实的输出示例：

`dashboard` 属性包含核心分析，分为四个主要部分：
1.  **`core_conclusion`**: 一句话总结、信号类型和仓位建议。
2.  **`data_perspective`**: 技术数据，包括趋势状态、价格位置、量能分析和筹码结构。
3.  **`intelligence`**: 定性信息，如新闻、风险警报和积极催化剂。
4.  **`battle_plan`**: 可操作的策略，包括狙击点（买/卖目标）、仓位策略和风险控制清单。

## 配置 (`Config`)

所有分析函数都可以接受一个可选的 `config` 对象。该对象包含应用程序的所有配置，例如 API 密钥、通知设置和分析参数。

如果未提供 `config` 对象，函数将自动使用从 `.env` 文件加载的全局单例实例。

**参考:** [`Config`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/config.py)

## 函数

### 1. 分析单只股票

**描述:** 分析单只股票并返回分析结果。

**何时使用:** 当用户要求分析特定股票时。

**输入:**
- `stock_code` (str): 要分析的股票代码。
- `config` (Config, 可选): 配置对象。默认为 `None`。
- `full_report` (bool, 可选): 是否生成完整报告。默认为 `False`。
- `notifier` (NotificationService, 可选): 通知服务对象。默认为 `None`（对话场景不要传，避免外部推送）。

**输出:** `Optional[AnalysisResult]`
一个包含分析结果的 `AnalysisResult` 对象，如果分析失败则为 `None`。

**示例:**

```python
import os
import sys

# 先定位已配置的 DSA 检出，并切换到该根目录（见「运行前提」）
repo_root = os.path.abspath(os.environ.get("DSA_REPO_ROOT") or os.getcwd())
os.chdir(repo_root)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.services.analyzer_service import analyze_stock

# 分析单只股票（默认不向外部通知渠道推送）
result = analyze_stock("600989")
if result:
    print(f"股票: {result.name} ({result.code})")
    print(f"情绪得分: {result.sentiment_score}")
    print(f"操作建议: {result.operation_advice}")
```

**参考:** [`analyze_stock`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/services/analyzer_service.py)

### 2. 分析多只股票

**描述:** 分析一个股票列表并返回分析结果列表。

**何时使用:** 当用户想要一次分析多只股票时。

**输入:**
- `stock_codes` (List[str]): 要分析的股票代码列表。
- `config` (Config, 可选): 配置对象。默认为 `None`。
- `full_report` (bool, 可选): 是否为每只股票生成完整报告。默认为 `False`。
- `notifier` (NotificationService, 可选): 通知服务对象。默认为 `None`（对话场景不要传，避免外部推送）。

**输出:** `List[AnalysisResult]`
一个 `AnalysisResult` 对象列表。

**示例:**

```python
import os
import sys

repo_root = os.path.abspath(os.environ.get("DSA_REPO_ROOT") or os.getcwd())
os.chdir(repo_root)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.services.analyzer_service import analyze_stocks

results = analyze_stocks(["600989", "000001"])
for result in results:
    print(f"股票: {result.name}, 操作建议: {result.operation_advice}")
```

**参考:** [`analyze_stocks`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/services/analyzer_service.py)

### 3. 执行大盘复盘

**描述:** 对整体市场进行复盘并返回一份报告。服务层会获取与 Web/API/CLI/Bot 相同的同机防重锁；若复盘已在执行，函数返回 `None`，此时应告知用户「大盘复盘正在执行中，请稍后再试」，不要重试抢跑。

**何时使用:** 当用户要求市场概览、摘要或复盘时。

**输入:**
- `config` (Config, 可选): 配置对象。默认为 `None`。
- `notifier` (NotificationService, 可选): 通知服务对象。默认为 `None`。
- `send_notification` (bool, 可选): 是否向已配置的外部通知渠道推送。**对话场景默认传 `False`**；仅当用户明确要求「推送 / 发送到通知渠道」时才设为 `True`。旧检出若无此参数，须先升级，不可静默回退为会推送的旧调用。

**输出:** `Optional[str]`
一个包含市场复盘报告的字符串；失败或同机已有复盘在跑时为 `None`。

**示例:**

```python
import inspect
import os
import sys

repo_root = os.path.abspath(os.environ.get("DSA_REPO_ROOT") or os.getcwd())
os.chdir(repo_root)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.services.analyzer_service import perform_market_review

# 对话内查看复盘：禁用外部推送；需要推送时再传 send_notification=True
review_kwargs = {}
if "send_notification" in inspect.signature(perform_market_review).parameters:
    review_kwargs["send_notification"] = False
else:
    raise RuntimeError(
        "当前 DSA 检出的 perform_market_review 不支持 send_notification；"
        "请先更新检出后再在对话中复盘，避免意外推送到外部渠道。"
    )

report = perform_market_review(**review_kwargs)
if report:
    print(report)
else:
    print("大盘复盘未返回结果（可能正在执行中或分析失败），请稍后再试或查看 DSA 日志。")
```

**参考:** [`perform_market_review`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/services/analyzer_service.py)

## 模型与外部 Bot

- 若把 **xAI Grok** 当作 DSA 分析模型：配置 `XAI_API_KEY` + `LITELLM_MODEL=xai/<官方模型ID>`（LiteLLM 直连，非托管渠道），并用 `python scripts/check_env.py --llm` 验证。示例见 [`docs/LLM_CONFIG_GUIDE.md`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/LLM_CONFIG_GUIDE.md)。
- 2026-08-11 上线的 **[Grok Bot](https://x.ai/bot)** 是另一条路径：它是带 Skills / Routines / MCP / computer use 的 AI teammate，应通过 HTTP 调用本仓库的 `analyze_stock` / REST API，而不是把 Bot 本身配成 LiteLLM provider。对接说明见 [`docs/grok-bot-integration.md`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/grok-bot-integration.md)。
