# -*- coding: utf-8 -*-
"""
Agent Executor — ReAct loop with tool calling.

Orchestrates the LLM + tools interaction loop:
1. Build system prompt (persona + tools + skills)
2. Send to LLM with tool declarations
3. If tool_call → execute tool → feed result back
4. If text → parse as final answer
5. Loop until final answer or max_steps

The core execution loop is delegated to :mod:`src.agent.runner` so that
both the legacy single-agent path and future multi-agent runners share the
same implementation.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.config import get_config
from src.agent.chat_context import build_agent_chat_context_bundle
from src.agent.llm_adapter import LLMToolAdapter
from src.agent.provider_trace import extract_provider_trace_turns
from src.agent.runner import run_agent_loop, parse_dashboard_json
from src.agent.stock_scope import StockScope, resolve_stock_scope
from src.storage import get_db
from src.agent.tools.registry import ToolRegistry
from src.report_language import normalize_report_language
from src.market_context import get_market_role, get_market_guidelines
from src.market_phase_prompt import format_market_phase_prompt_section
from src.market_structure_prompt import format_market_structure_prompt_section
from src.services.daily_market_context import format_daily_market_context_prompt_section

logger = logging.getLogger(__name__)


# ============================================================
# Agent result
# ============================================================

@dataclass
class AgentResult:
    """Result from an agent execution run."""
    success: bool = False
    content: str = ""                          # final text answer from agent
    dashboard: Optional[Dict[str, Any]] = None  # parsed dashboard JSON
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)  # execution trace
    total_steps: int = 0
    total_tokens: int = 0
    provider: str = ""
    model: str = ""                            # comma-separated models used (supports fallback)
    error: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================
# System prompt builder
# ============================================================

LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT = """你是一位专注于趋势交易的{market_role}投资分析 Agent，拥有数据工具和交易技能，负责生成专业的【决策仪表盘】分析报告。

{market_guidelines}

## 工作流程（必须严格按阶段顺序执行，每阶段等工具结果返回后再进入下一阶段）

**第一阶段 · 行情与K线**（首先执行）
- `get_realtime_quote` 获取实时行情
- `get_daily_history` 获取历史K线

**第二阶段 · 技术与筹码**（等第一阶段结果返回后执行）
- `analyze_trend` 获取技术指标
- `get_chip_distribution` 获取筹码分布

**第三阶段 · 情报搜索**（等前两阶段完成后执行）
- `search_stock_news` 搜索最新资讯、减持、业绩预告等风险信号

**第四阶段 · 生成报告**（所有数据就绪后，输出完整决策仪表盘 JSON）

> ⚠️ 每阶段的工具调用必须完整返回结果后，才能进入下一阶段。禁止将不同阶段的工具合并到同一次调用中。
{default_skill_policy_section}

## 规则

1. **必须调用工具获取真实数据** — 绝不编造数字，所有数据必须来自工具返回结果。
2. **系统化分析** — 严格按工作流程分阶段执行，每阶段完整返回后再进入下一阶段，**禁止**将不同阶段的工具合并到同一次调用中。
3. **应用交易技能** — 评估每个激活技能的条件，在报告中体现技能判断结果。
4. **输出格式** — 最终响应必须是有效的决策仪表盘 JSON。
5. **风险优先** — 必须排查风险（股东减持、业绩预警、监管问题）。
6. **工具失败处理** — 记录失败原因，使用已有数据继续分析，不重复调用失败工具。

{skills_section}

## 输出格式：决策仪表盘 JSON

你的最终响应必须是以下结构的有效 JSON 对象：

```json
{{
    "stock_name": "股票中文名称",
    "sentiment_score": 0-100整数,
    "trend_prediction": "强烈看多/看多/震荡/看空/强烈看空",
    "operation_advice": "买入/加仓/持有/减仓/卖出/观望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "一句话核心结论（30字以内）",
            "signal_type": "🟢买入信号/🟡持有观望/🔴卖出信号/⚠️风险警告",
            "time_sensitivity": "立即行动/今日内/本周内/不急",
            "position_advice": {{
                "no_position": "空仓者建议",
                "has_position": "持仓者建议"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}},
            "chip_structure": {{"profit_ratio": 0, "avg_cost": 0, "concentration": 0, "chip_health": ""}}
        }},
        "intelligence": {{
            "latest_news": "",
            "risk_alerts": [],
            "positive_catalysts": [],
            "earnings_outlook": "",
            "sentiment_summary": ""
        }},
        "battle_plan": {{
            "sniper_points": {{"ideal_buy": "", "secondary_buy": "", "stop_loss": "", "take_profit": ""}},
            "position_strategy": {{"suggested_position": "", "entry_plan": "", "risk_control": ""}},
            "action_checklist": []
        }},
        "phase_decision": {{
            "phase_context": {{"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"}},
            "action_window": "盘前计划/盘中跟踪/午间确认/收盘前风控/盘后复盘/非交易日观察",
            "immediate_action": "立即行动/等待确认/观察/止损止盈预警/禁止追高/无盘中动作",
            "watch_conditions": ["观察条件1", "观察条件2"],
            "next_check_time": "下一次检查点或市场本地时间",
            "confidence_reason": "置信度理由，说明阶段和数据质量限制",
            "data_limitations": ["阶段或数据质量限制1", "阶段或数据质量限制2"]
        }},
        "signal_attribution": {{
            "technical_indicators": 技术指标贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "news_sentiment": 新闻舆情贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "fundamentals": 基本面贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "market_conditions": 市场环境贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "strongest_bullish_signal": "最强看多信号名称",
            "strongest_bearish_signal": "最强看空信号名称"
        }}
    }},
    "analysis_summary": "100字综合分析摘要",
    "key_points": "3-5个核心看点，逗号分隔",
    "risk_warning": "风险提示",
    "buy_reason": "操作理由，引用交易理念",
    "trend_analysis": "走势形态分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技术面综合分析",
    "ma_analysis": "均线系统分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K线形态分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板块行业分析",
    "company_highlights": "公司亮点/风险",
    "news_summary": "新闻摘要",
    "market_sentiment": "市场情绪",
    "hot_topics": "相关热点"
}}
```

## 评分标准

### 强烈买入（80-100分）：
- ✅ 多头排列：MA5 > MA10 > MA20
- ✅ 低乖离率：<2%，最佳买点
- ✅ 缩量回调或放量突破
- ✅ 筹码集中健康
- ✅ 消息面有利好催化

### 买入（60-79分）：
- ✅ 多头排列或弱势多头
- ✅ 乖离率 <5%
- ✅ 量能正常
- ⚪ 允许一项次要条件不满足

### 观望（40-59分）：
- ⚠️ 乖离率 >5%（追高风险）
- ⚠️ 均线缠绕趋势不明
- ⚠️ 有风险事件

### 卖出/减仓（0-39分）：
- ❌ 空头排列
- ❌ 跌破MA20
- ❌ 放量下跌
- ❌ 重大利空

## 决策仪表盘核心原则

1. **核心结论先行**：一句话说清该买该卖
2. **分持仓建议**：空仓者和持仓者给不同建议
3. **精确狙击点**：必须给出具体价格，不说模糊的话
4. **检查清单可视化**：用 ✅⚠️❌ 明确显示每项检查结果
5. **风险优先级**：舆情中的风险点要醒目标出

## 可操作性与稳定性约束

- 不得仅因为单日涨跌或评分跨线就在“买入/卖出”之间剧烈切换。
- 操作建议必须同时参考价格位置（支撑/压力位）、量能/筹码、主力资金流向和风险事件。
- 股价位于支撑与压力之间、资金流不明确时，优先输出“持有/震荡/观望/洗盘观察”等可执行的中性建议；`decision_type` 仍保持 `hold`。
- 只有在接近支撑确认或有效突破压力，且资金流/量价配合时，才能给出买入；接近压力且资金流出时不得追买。
- 只有在跌破关键支撑、主力资金持续流出或风险显著放大时，才能给出卖出/减仓。
- 必须输出 `dashboard.phase_decision` 七字段；盘中/午休/临近收盘要给出当前动作、观察条件和下一次检查点。
- 建议输出可选展示字段 `dashboard.signal_attribution` 六字段；解释推荐理由的构成，包括技术指标、新闻舆情、基本面、市场环境的贡献度，以及最强看多/看空信号。
- 盘前、非交易日或未知阶段不得伪造今日盘中走势；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 时，`confidence_level` 不得为高。

{language_section}
"""

AGENT_SYSTEM_PROMPT = """你是一位{market_role}投资分析 Agent，拥有数据工具和可切换交易技能，负责生成专业的【决策仪表盘】分析报告。

{market_guidelines}

## 工作流程（必须严格按阶段顺序执行，每阶段等工具结果返回后再进入下一阶段）

**第一阶段 · 行情与K线**（首先执行）
- `get_realtime_quote` 获取实时行情
- `get_daily_history` 获取历史K线

**第二阶段 · 技术与筹码**（等第一阶段结果返回后执行）
- `analyze_trend` 获取技术指标
- `get_chip_distribution` 获取筹码分布

**第三阶段 · 情报搜索**（等前两阶段完成后执行）
- `search_stock_news` 搜索最新资讯、减持、业绩预告等风险信号

**第四阶段 · 生成报告**（所有数据就绪后，输出完整决策仪表盘 JSON）

> ⚠️ 每阶段的工具调用必须完整返回结果后，才能进入下一阶段。禁止将不同阶段的工具合并到同一次调用中。
{default_skill_policy_section}

## 规则

1. **必须调用工具获取真实数据** — 绝不编造数字，所有数据必须来自工具返回结果。
2. **系统化分析** — 严格按工作流程分阶段执行，每阶段完整返回后再进入下一阶段，**禁止**将不同阶段的工具合并到同一次调用中。
3. **应用交易技能** — 评估每个激活技能的条件，在报告中体现技能判断结果。
4. **输出格式** — 最终响应必须是有效的决策仪表盘 JSON。
5. **风险优先** — 必须排查风险（股东减持、业绩预警、监管问题）。
6. **工具失败处理** — 记录失败原因，使用已有数据继续分析，不重复调用失败工具。

{skills_section}

## 输出格式：决策仪表盘 JSON

你的最终响应必须是以下结构的有效 JSON 对象：

```json
{{
    "stock_name": "股票中文名称",
    "sentiment_score": 0-100整数,
    "trend_prediction": "强烈看多/看多/震荡/看空/强烈看空",
    "operation_advice": "买入/加仓/持有/减仓/卖出/观望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "一句话核心结论（30字以内）",
            "signal_type": "🟢买入信号/🟡持有观望/🔴卖出信号/⚠️风险警告",
            "time_sensitivity": "立即行动/今日内/本周内/不急",
            "position_advice": {{
                "no_position": "空仓者建议",
                "has_position": "持仓者建议"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}},
            "chip_structure": {{"profit_ratio": 0, "avg_cost": 0, "concentration": 0, "chip_health": ""}}
        }},
        "intelligence": {{
            "latest_news": "",
            "risk_alerts": [],
            "positive_catalysts": [],
            "earnings_outlook": "",
            "sentiment_summary": ""
        }},
        "battle_plan": {{
            "sniper_points": {{"ideal_buy": "", "secondary_buy": "", "stop_loss": "", "take_profit": ""}},
            "position_strategy": {{"suggested_position": "", "entry_plan": "", "risk_control": ""}},
            "action_checklist": []
        }},
        "phase_decision": {{
            "phase_context": {{"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"}},
            "action_window": "盘前计划/盘中跟踪/午间确认/收盘前风控/盘后复盘/非交易日观察",
            "immediate_action": "立即行动/等待确认/观察/止损止盈预警/禁止追高/无盘中动作",
            "watch_conditions": ["观察条件1", "观察条件2"],
            "next_check_time": "下一次检查点或市场本地时间",
            "confidence_reason": "置信度理由，说明阶段和数据质量限制",
            "data_limitations": ["阶段或数据质量限制1", "阶段或数据质量限制2"]
        }},
        "signal_attribution": {{
            "technical_indicators": 技术指标贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "news_sentiment": 新闻舆情贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "fundamentals": 基本面贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "market_conditions": 市场环境贡献度(0-100；有效非零贡献度之和应为100；全零表示无有效信号),
            "strongest_bullish_signal": "最强看多信号名称",
            "strongest_bearish_signal": "最强看空信号名称"
        }}
    }},
    "analysis_summary": "100字综合分析摘要",
    "key_points": "3-5个核心看点，逗号分隔",
    "risk_warning": "风险提示",
    "buy_reason": "操作理由，引用激活技能或风险框架",
    "trend_analysis": "走势形态分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技术面综合分析",
    "ma_analysis": "均线系统分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K线形态分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板块行业分析",
    "company_highlights": "公司亮点/风险",
    "news_summary": "新闻摘要",
    "market_sentiment": "市场情绪",
    "hot_topics": "相关热点"
}}
```

## 评分标准

### 强烈买入（80-100分）：
- ✅ 多个激活技能同时支持积极结论
- ✅ 上行空间、触发条件与风险回报清晰
- ✅ 关键风险已排查，仓位与止损计划明确
- ✅ 重要数据和情报结论彼此一致

### 买入（60-79分）：
- ✅ 主信号偏积极，但仍有少量待确认项
- ✅ 允许存在可控风险或次优入场点
- ✅ 需要在报告中明确补充观察条件

### 观望（40-59分）：
- ⚠️ 信号分歧较大，或缺乏足够确认
- ⚠️ 风险与机会大致均衡
- ⚠️ 更适合等待触发条件或回避不确定性

### 卖出/减仓（0-39分）：
- ❌ 主要结论转弱，风险明显高于收益
- ❌ 触发了止损/失效条件或重大利空
- ❌ 现有仓位更需要保护而不是进攻

## 决策仪表盘核心原则

1. **核心结论先行**：一句话说清该买该卖
2. **分持仓建议**：空仓者和持仓者给不同建议
3. **精确狙击点**：必须给出具体价格，不说模糊的话
4. **检查清单可视化**：用 ✅⚠️❌ 明确显示每项检查结果
5. **风险优先级**：舆情中的风险点要醒目标出

## 可操作性与稳定性约束

- 不得仅因为单日涨跌或评分跨线就在“买入/卖出”之间剧烈切换。
- 操作建议必须同时参考价格位置（支撑/压力位）、量能/筹码、主力资金流向和风险事件。
- 股价位于支撑与压力之间、资金流不明确时，优先输出“持有/震荡/观望/洗盘观察”等可执行的中性建议；`decision_type` 仍保持 `hold`。
- 只有在接近支撑确认或有效突破压力，且资金流/量价配合时，才能给出买入；接近压力且资金流出时不得追买。
- 只有在跌破关键支撑、主力资金持续流出或风险显著放大时，才能给出卖出/减仓。
- 必须输出 `dashboard.phase_decision` 七字段；盘中/午休/临近收盘要给出当前动作、观察条件和下一次检查点。
- 建议输出可选展示字段 `dashboard.signal_attribution` 六字段；解释推荐理由的构成，包括技术指标、新闻舆情、基本面、市场环境的贡献度，以及最强看多/看空信号。
- 盘前、非交易日或未知阶段不得伪造今日盘中走势；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 时，`confidence_level` 不得为高。

{language_section}
"""

LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT = """你是一位专注于趋势交易的{market_role}投资分析 Agent，拥有数据工具和交易技能，负责解答用户的股票投资问题。

{market_guidelines}

## 分析工作流程（必须严格按阶段执行，禁止跳步或合并阶段）

当用户询问某支股票时，必须按以下四个阶段顺序调用工具，每阶段等工具结果全部返回后再进入下一阶段：

**第一阶段 · 行情与K线**（必须先执行）
- 调用 `get_realtime_quote` 获取实时行情和当前价格
- 调用 `get_daily_history` 获取近期历史K线数据

**第二阶段 · 技术与筹码**（等第一阶段结果返回后再执行）
- 调用 `analyze_trend` 获取 MA/MACD/RSI 等技术指标
- 调用 `get_chip_distribution` 获取筹码分布结构

**第三阶段 · 情报搜索**（等前两阶段完成后再执行）
- 调用 `search_stock_news` 搜索最新新闻公告、减持、业绩预告等风险信号

**第四阶段 · 综合分析**（所有工具数据就绪后生成回答）
- 基于上述真实数据，结合激活技能进行综合研判，输出投资建议

> ⚠️ 禁止将不同阶段的工具合并到同一次调用中（例如禁止在第一次调用中同时请求行情、技术指标和新闻）。
{default_skill_policy_section}

## 规则

1. **必须调用工具获取真实数据** — 绝不编造数字，所有数据必须来自工具返回结果。
2. **应用交易技能** — 评估每个激活技能的条件，在回答中体现技能判断结果。
3. **自由对话** — 根据用户的问题，自由组织语言回答，不需要输出 JSON。
4. **风险优先** — 必须排查风险（股东减持、业绩预警、监管问题）。
5. **工具失败处理** — 记录失败原因，使用已有数据继续分析，不重复调用失败工具。

{skills_section}
{language_section}
"""

CHAT_SYSTEM_PROMPT = """你是一位{market_role}投资分析 Agent，拥有数据工具和可切换交易技能，负责解答用户的股票投资问题。

{market_guidelines}

## 分析工作流程（必须严格按阶段执行，禁止跳步或合并阶段）

当用户询问某支股票时，必须按以下四个阶段顺序调用工具，每阶段等工具结果全部返回后再进入下一阶段：

**第一阶段 · 行情与K线**（必须先执行）
- 调用 `get_realtime_quote` 获取实时行情和当前价格
- 调用 `get_daily_history` 获取近期历史K线数据

**第二阶段 · 技术与筹码**（等第一阶段结果返回后再执行）
- 调用 `analyze_trend` 获取 MA/MACD/RSI 等技术指标
- 调用 `get_chip_distribution` 获取筹码分布结构

**第三阶段 · 情报搜索**（等前两阶段完成后再执行）
- 调用 `search_stock_news` 搜索最新新闻公告、减持、业绩预告等风险信号

**第四阶段 · 综合分析**（所有工具数据就绪后生成回答）
- 基于上述真实数据，结合激活技能进行综合研判，输出投资建议

> ⚠️ 禁止将不同阶段的工具合并到同一次调用中（例如禁止在第一次调用中同时请求行情、技术指标和新闻）。
{default_skill_policy_section}

## 规则

1. **必须调用工具获取真实数据** — 绝不编造数字，所有数据必须来自工具返回结果。
2. **应用交易技能** — 评估每个激活技能的条件，在回答中体现技能判断结果。
3. **自由对话** — 根据用户的问题，自由组织语言回答，不需要输出 JSON。
4. **风险优先** — 必须排查风险（股东减持、业绩预警、监管问题）。
5. **工具失败处理** — 记录失败原因，使用已有数据继续分析，不重复调用失败工具。

{skills_section}
{language_section}
"""


def _build_language_section(report_language: str, *, chat_mode: bool = False) -> str:
    """Build output-language guidance for the agent prompt."""
    normalized = normalize_report_language(report_language)
    if chat_mode:
        if normalized == "en":
            return """
## Output Language

- Reply in English.
- If you output JSON, keep the keys unchanged and write every human-readable value in English.
"""
        return """
## 输出语言

- 默认使用中文回答。
- 若输出 JSON，键名保持不变，所有面向用户的文本值使用中文。
"""

    if normalized == "en":
        return """
## Output Language

- Keep every JSON key unchanged.
- `decision_type` must remain `buy|hold|sell`.
- All human-readable JSON values must be written in English.
- This includes `stock_name`, `trend_prediction`, `operation_advice`, `confidence_level`, all dashboard text, checklist items, and summaries.
"""

    return """
## 输出语言

- 所有 JSON 键名保持不变。
- `decision_type` 必须保持为 `buy|hold|sell`。
- 所有面向用户的人类可读文本值必须使用中文。
"""


# ============================================================
# Agent Executor
# ============================================================

class AgentExecutor:
    """ReAct agent loop with tool calling.

    Usage::

        executor = AgentExecutor(tool_registry, llm_adapter)
        result = executor.run("Analyze stock 600519")
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMToolAdapter,
        skill_instructions: str = "",
        default_skill_policy: str = "",
        use_legacy_default_prompt: bool = False,
        max_steps: int = 10,
        timeout_seconds: Optional[float] = None,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions
        self.default_skill_policy = default_skill_policy
        self.use_legacy_default_prompt = use_legacy_default_prompt
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a given task.

        Args:
            task: The user task / analysis request.
            context: Optional context dict (e.g., {"stock_code": "600519"}).

        Returns:
            AgentResult with parsed dashboard or error.
        """
        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 激活的交易技能\n\n{self.skill_instructions}"
        default_skill_policy_section = ""
        if self.default_skill_policy:
            default_skill_policy_section = f"\n{self.default_skill_policy}\n"
        report_language = normalize_report_language((context or {}).get("report_language", "zh"))
        stock_code = (context or {}).get("stock_code", "")
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)
        prompt_template = (
            LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT
            if self.use_legacy_default_prompt
            else AGENT_SYSTEM_PROMPT
        )
        system_prompt = prompt_template.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            default_skill_policy_section=default_skill_policy_section,
            skills_section=skills_section,
            language_section=_build_language_section(report_language),
        )

        # Build tool declarations in OpenAI format (litellm handles all providers)
        tool_decls = self.tool_registry.to_openai_tools()

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._build_user_message(task, context)},
        ]

        return self._run_loop(messages, tool_decls, parse_dashboard=True)

    def chat(self, message: str, session_id: str, progress_callback: Optional[Callable] = None, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a free-form chat message.

        Args:
            message: The user's chat message.
            session_id: The conversation session ID.
            progress_callback: Optional callback for streaming progress events.
            context: Optional context dict from previous analysis for data reuse.

        Returns:
            AgentResult with the text response.
        """
        from src.agent.conversation import conversation_manager

        scope_resolution = resolve_stock_scope(message, context)
        context = scope_resolution.effective_context

        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 激活的交易技能\n\n{self.skill_instructions}"
        default_skill_policy_section = ""
        if self.default_skill_policy:
            default_skill_policy_section = f"\n{self.default_skill_policy}\n"
        report_language = normalize_report_language((context or {}).get("report_language", "zh"))
        stock_code = (context or {}).get("stock_code", "")
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)
        prompt_template = (
            LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT
            if self.use_legacy_default_prompt
            else CHAT_SYSTEM_PROMPT
        )
        system_prompt = prompt_template.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            default_skill_policy_section=default_skill_policy_section,
            skills_section=skills_section,
            language_section=_build_language_section(report_language, chat_mode=True),
        )

        # Build tool declarations in OpenAI format (litellm handles all providers)
        tool_decls = self.tool_registry.to_openai_tools()

        # Get conversation history
        conversation_manager.get_or_create(session_id)
        config = getattr(self.llm_adapter, "_config", None) or get_config()
        bundle = build_agent_chat_context_bundle(session_id, self.llm_adapter, config)

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(bundle.context_messages)

        # Inject previous analysis context if provided (data reuse from report follow-up)
        if context:
            context_parts = []
            if context.get("stock_code"):
                context_parts.append(f"股票代码: {context['stock_code']}")
            if context.get("stock_name"):
                context_parts.append(f"股票名称: {context['stock_name']}")
            if context.get("previous_price"):
                context_parts.append(f"上次分析价格: {context['previous_price']}")
            if context.get("previous_change_pct"):
                context_parts.append(f"上次涨跌幅: {context['previous_change_pct']}%")
            if context.get("previous_analysis_summary"):
                summary = context["previous_analysis_summary"]
                summary_text = json.dumps(summary, ensure_ascii=False) if isinstance(summary, dict) else str(summary)
                context_parts.append(f"上次分析摘要:\n{summary_text}")
            if context.get("previous_strategy"):
                strategy = context["previous_strategy"]
                strategy_text = json.dumps(strategy, ensure_ascii=False) if isinstance(strategy, dict) else str(strategy)
                context_parts.append(f"上次策略分析:\n{strategy_text}")
            daily_market_context_section = format_daily_market_context_prompt_section(
                context.get("daily_market_context"),
                report_language=report_language,
            )
            if daily_market_context_section:
                context_parts.append(daily_market_context_section.strip())
            market_structure_section = format_market_structure_prompt_section(
                context.get("market_structure_context"),
                report_language=report_language,
            )
            if market_structure_section:
                context_parts.append(market_structure_section.strip())
            if context_parts:
                context_msg = "[系统提供的历史分析上下文，可供参考对比]\n" + "\n".join(context_parts)
                messages.append({"role": "user", "content": context_msg})
                messages.append({"role": "assistant", "content": "好的，我已了解该股票的历史分析数据。请告诉我你想了解什么？"})

        messages.append({"role": "user", "content": message})
        baseline_len = len(messages)
        run_id = str(uuid.uuid4())

        # Persist the user turn immediately so the session appears in history during processing
        user_message_id = conversation_manager.add_message(session_id, "user", message)

        result = self._run_loop(
            messages,
            tool_decls,
            parse_dashboard=False,
            progress_callback=progress_callback,
            stock_scope=scope_resolution.stock_scope,
        )

        # Persist assistant reply (or error note) for context continuity
        if result.success:
            assistant_message_id = conversation_manager.add_message(session_id, "assistant", result.content)
            self._persist_provider_trace(
                session_id=session_id,
                run_id=run_id,
                messages=result.messages,
                baseline_len=baseline_len,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
            )
        else:
            error_note = f"[分析失败] {result.error or '未知错误'}"
            conversation_manager.add_message(session_id, "assistant", error_note)

        return result

    def _persist_provider_trace(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: List[Dict[str, Any]],
        baseline_len: int,
        user_message_id: int,
        assistant_message_id: int,
    ) -> None:
        try:
            turns, diagnostics = extract_provider_trace_turns(
                messages,
                baseline_len=baseline_len,
                run_id=run_id,
                anchor_user_message_id=user_message_id,
                anchor_assistant_message_id=assistant_message_id,
            )
        except Exception:
            logger.warning(
                "Provider trace extraction failed for session %s run %s",
                session_id,
                run_id,
                exc_info=True,
            )
            return

        if diagnostics.trace_dropped_reason:
            logger.debug(
                "Provider trace skipped for session %s run %s: %s",
                session_id,
                run_id,
                diagnostics.trace_dropped_reason,
            )
        if not turns:
            return

        try:
            db = get_db()
        except Exception:
            logger.warning(
                "Provider trace storage unavailable for session %s run %s",
                session_id,
                run_id,
                exc_info=True,
            )
            return

        for turn in turns:
            try:
                db.save_agent_provider_turn(
                    session_id=session_id,
                    run_id=run_id,
                    provider=turn.provider,
                    model=turn.model,
                    anchor_user_message_id=user_message_id,
                    anchor_assistant_message_id=assistant_message_id,
                    messages=turn.messages,
                    contains_reasoning=turn.contains_reasoning,
                    contains_tool_calls=turn.contains_tool_calls,
                    contains_thinking_blocks=turn.contains_thinking_blocks,
                    must_roundtrip=turn.must_roundtrip,
                    estimated_tokens=turn.estimated_tokens,
                )
            except Exception:
                logger.warning(
                    "Provider trace persistence failed for session %s run %s provider=%s model=%s",
                    session_id,
                    run_id,
                    turn.provider,
                    turn.model,
                    exc_info=True,
                )

    def _run_loop(
        self,
        messages: List[Dict[str, Any]],
        tool_decls: List[Dict[str, Any]],
        parse_dashboard: bool,
        progress_callback: Optional[Callable] = None,
        stock_scope: Optional[StockScope] = None,
    ) -> AgentResult:
        """Delegate to the shared runner and adapt the result.

        This preserves the exact same observable behaviour as the original
        inline implementation while sharing the single authoritative loop
        in :mod:`src.agent.runner`.
        """
        loop_result = run_agent_loop(
            messages=messages,
            tool_registry=self.tool_registry,
            llm_adapter=self.llm_adapter,
            max_steps=self.max_steps,
            progress_callback=progress_callback,
            max_wall_clock_seconds=self.timeout_seconds,
            stock_scope=stock_scope,
        )

        model_str = loop_result.model

        if parse_dashboard and loop_result.success:
            dashboard = parse_dashboard_json(loop_result.content)
            return AgentResult(
                success=dashboard is not None,
                content=loop_result.content,
                dashboard=dashboard,
                tool_calls_log=loop_result.tool_calls_log,
                total_steps=loop_result.total_steps,
                total_tokens=loop_result.total_tokens,
                provider=loop_result.provider,
                model=model_str,
                error=None if dashboard else "Failed to parse dashboard JSON from agent response",
                messages=loop_result.messages,
            )

        return AgentResult(
            success=loop_result.success,
            content=loop_result.content,
            dashboard=None,
            tool_calls_log=loop_result.tool_calls_log,
            total_steps=loop_result.total_steps,
            total_tokens=loop_result.total_tokens,
            provider=loop_result.provider,
            model=model_str,
            error=loop_result.error,
            messages=loop_result.messages,
        )

    def _build_user_message(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Build the initial user message."""
        parts = [task]
        if context:
            report_language = normalize_report_language(context.get("report_language", "zh"))
            if context.get("stock_code"):
                parts.append(f"\n股票代码: {context['stock_code']}")
            if context.get("report_type"):
                parts.append(f"报告类型: {context['report_type']}")
            if report_language == "en":
                parts.append("输出语言: English（所有 JSON 键名保持不变，所有面向用户的文本值使用英文）")
            elif report_language == "ko":
                parts.append("출력 언어: 한국어（모든 JSON 키는 그대로 유지하고, 사용자 노출 텍스트 값은 한국어로 작성）")
            else:
                parts.append("输出语言: 中文（所有 JSON 键名保持不变，所有面向用户的文本值使用中文）")

            market_phase_section = format_market_phase_prompt_section(
                context.get("market_phase_context"),
                report_language=report_language,
            )
            if market_phase_section:
                parts.append(market_phase_section)

            daily_market_context_section = format_daily_market_context_prompt_section(
                context.get("daily_market_context"),
                report_language=report_language,
            )
            if daily_market_context_section:
                parts.append(daily_market_context_section)

            market_structure_section = format_market_structure_prompt_section(
                context.get("market_structure_context"),
                report_language=report_language,
            )
            if market_structure_section:
                parts.append(market_structure_section)

            analysis_context_pack_summary = context.get("analysis_context_pack_summary")
            if isinstance(analysis_context_pack_summary, str) and analysis_context_pack_summary:
                parts.append(analysis_context_pack_summary)

            # Inject pre-fetched context data to avoid redundant fetches
            if context.get("realtime_quote"):
                parts.append(f"\n[系统已获取的实时行情]\n{json.dumps(context['realtime_quote'], ensure_ascii=False)}")
            if context.get("chip_distribution"):
                parts.append(f"\n[系统已获取的筹码分布]\n{json.dumps(context['chip_distribution'], ensure_ascii=False)}")
            if context.get("news_context"):
                parts.append(f"\n[系统已获取的新闻与舆情情报]\n{context['news_context']}")

        parts.append("\n请使用可用工具获取缺失的数据（如历史K线、新闻等），然后以决策仪表盘 JSON 格式输出分析结果。")
        return "\n".join(parts)
