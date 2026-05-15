---
name: "stock_analyzer"
description: "分析股票和市场。当用户想要分析单个或多个股票，或进行市场复盘时调用。"
---

# 股票分析器

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

**参考:** [`Config`](src/config.py)

## 函数

### 1. 分析单只股票

**描述:** 分析单只股票并返回分析结果。

**何时使用:** 当用户要求分析特定股票时。

**输入:**
- `stock_code` (str): 要分析的股票代码。
- `config` (Config, 可选): 配置对象。默认为 `None`。
- `full_report` (bool, 可选): 是否生成完整报告。默认为 `False`。
- `notifier` (NotificationService, 可选): 通知服务对象。默认为 `None`。

**输出:** `Optional[AnalysisResult]`
一个包含分析结果的 `AnalysisResult` 对象，如果分析失败则为 `None`。

**示例:**

```python
from src.services.analyzer_service import analyze_stock

# 分析单只股票
result = analyze_stock("600989")
if result:
    print(f"股票: {result.name} ({result.code})")
    print(f"情绪得分: {result.sentiment_score}")
    print(f"操作建议: {result.operation_advice}")
```

**参考:** [`analyze_stock`](src/services/analyzer_service.py)

### 2. 分析多只股票

**描述:** 分析一个股票列表并返回分析结果列表。

**何时使用:** 当用户想要一次分析多只股票时。

**输入:**
- `stock_codes` (List[str]): 要分析的股票代码列表。
- `config` (Config, 可选): 配置对象。默认为 `None`。
- `full_report` (bool, 可选): 是否为每只股票生成完整报告。默认为 `False`。
- `notifier` (NotificationService, 可选): 通知服务对象。默认为 `None`。

**输出:** `List[AnalysisResult]`
一个 `AnalysisResult` 对象列表。

**示例:**

```python
from src.services.analyzer_service import analyze_stocks

# 分析多只股票
results = analyze_stocks(["600989", "000001"])
for result in results:
    print(f"股票: {result.name}, 操作建议: {result.operation_advice}")
```

**参考:** [`analyze_stocks`](src/services/analyzer_service.py)


### 3. 执行大盘复盘

**描述:** 对整体市场进行复盘并返回一份报告。

**何时使用:** 当用户要求市场概览、摘要或复盘时。

**输入:**
- `config` (Config, 可选): 配置对象。默认为 `None`。
- `notifier` (NotificationService, 可选): 通知服务对象。默认为 `None`。

**输出:** `Optional[str]`
一个包含市场复盘报告的字符串，如果失败则为 `None`。

**示例:**

```python
from src.services.analyzer_service import perform_market_review

# 执行大盘复盘
report = perform_market_review()
if report:
    print(report)
```

**参考:** [`perform_market_review`](src/services/analyzer_service.py)
