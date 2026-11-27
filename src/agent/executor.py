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
from src.agent.chat_context import build_agent_chat_context_bundle, build_visible_chat_history
from src.agent.llm_adapter import LLMToolAdapter
from src.agent.provider_trace import persist_provider_trace_turns
from src.agent.runner import run_agent_loop, parse_dashboard_json
from src.agent.runtime_facts import AgentRuntimeFacts
from src.agent.skills.base import resolve_skill_instructions_for_language
from src.agent.skills.defaults import CORE_TRADING_SKILL_POLICY_EN, CORE_TRADING_SKILL_POLICY_ZH
from src.agent.stock_scope import StockScope, StockScopeResolution, resolve_stock_scope
from src.storage import get_db
from src.agent.tools.registry import ToolRegistry
from src.report_language import format_chat_failure_message, normalize_report_language
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
    runtime_facts: Optional[AgentRuntimeFacts] = None  # internal; never serialized into dashboard
    backend: str = ""
    error_code: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    # Optional whitelisted snapshots for multi-agent trajectory evaluation.
    # Single-agent callers continue to receive the historical empty list.
    stage_trajectories: List[Dict[str, Any]] = field(default_factory=list)


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

_ENGLISH_DASHBOARD_JSON_FORMAT_SECTION = """## Output Format: Decision Dashboard JSON

Your final response must be a valid JSON object following this structure:

```json
{{
    "stock_name": "Stock display name",
    "sentiment_score": 0-100 integer,
    "trend_prediction": "Strong Bullish / Bullish / Sideways / Bearish / Strong Bearish",
    "operation_advice": "Buy / Add Position / Hold / Reduce / Sell / Watch",
    "decision_type": "buy/hold/sell",
    "confidence_level": "High/Medium/Low",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "One-sentence core conclusion (<= 30 words)",
            "signal_type": "🟢 Buy Signal / 🟡 Hold / Watch / 🔴 Sell Signal / ⚠️ Risk Warning",
            "time_sensitivity": "Immediate / Today / This week / Not urgent",
            "position_advice": {{
                "no_position": "Advice for flat accounts",
                "has_position": "Advice for current holders"
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
            "action_window": "Pre-market plan / Intraday tracking / Midday check / Pre-close control / Post-market review / Non-trading watch",
            "immediate_action": "Act now / Wait for confirmation / Watch / Stop or target alert / Avoid chasing / No intraday action",
            "watch_conditions": ["Watch condition 1", "Watch condition 2"],
            "next_check_time": "Next check point or local market time",
            "confidence_reason": "Reason for confidence noting phase and data quality limits",
            "data_limitations": ["Phase or data limitation 1", "Phase or data limitation 2"]
        }},
        "signal_attribution": {{
            "technical_indicators": 0-100 contribution (non-zero valid contributions sum to 100; all zero means no effective signal),
            "news_sentiment": 0-100 contribution (non-zero valid contributions sum to 100; all zero means no effective signal),
            "fundamentals": 0-100 contribution (non-zero valid contributions sum to 100; all zero means no effective signal),
            "market_conditions": 0-100 contribution (non-zero valid contributions sum to 100; all zero means no effective signal),
            "strongest_bullish_signal": "Strongest bullish signal name",
            "strongest_bearish_signal": "Strongest bearish signal name"
        }}
    }},
    "analysis_summary": "Concise overall synthesis summary",
    "key_points": "3-5 key takeaways, comma-separated",
    "risk_warning": "Risk warning",
    "buy_reason": "Decision rationale referencing the active skills or risk framework",
    "trend_analysis": "Price action and trend structure analysis",
    "short_term_outlook": "Short-term 1-3 day outlook",
    "medium_term_outlook": "Medium-term 1-2 week outlook",
    "technical_analysis": "Comprehensive technical analysis",
    "ma_analysis": "Moving average analysis",
    "volume_analysis": "Volume analysis",
    "pattern_analysis": "Candlestick pattern analysis",
    "fundamental_analysis": "Fundamental analysis",
    "sector_position": "Sector and industry positioning",
    "company_highlights": "Company highlights and risks",
    "news_summary": "News summary",
    "market_sentiment": "Market sentiment",
    "hot_topics": "Related themes"
}}
```"""

_ENGLISH_DASHBOARD_RULES_FOOTER = """## Core Decision Dashboard Principles

1. **Core conclusion first**: summarize the buy/hold/sell stance in one sentence.
2. **Split position advice**: provide distinct guidance for flat vs. holding positions.
3. **Precise sniper levels**: state concrete price levels without vague hedging.
4. **Visual checklist**: clearly mark checks with ✅⚠️❌.
5. **Risk priority**: surface risk alerts prominently.

## Actionability & Stability Guardrails

- Do not swing sharply between Buy and Sell on a single day's move or score boundary crossing.
- Anchor operation_advice in price location (support/resistance), volume/chip context, main-force capital flow, and risk events.
- When price is mid-range between support and resistance and flows are unclear, prefer actionable neutral stances (Hold / Range-bound / Watch / Shakeout Watch) with `decision_type` kept as `hold`.
- Recommend Buy only near confirmed support or on a valid resistance breakout backed by volume/capital flow; never chase near resistance amid outflows.
- Recommend Sell/Reduce only on key support breakdown, sustained main-force outflows, or materially elevated risk.
- Always output all seven `dashboard.phase_decision` fields with immediate action, watch conditions, and next check time when intraday/midday/near-close.
- Include the optional six `dashboard.signal_attribution` fields explaining contributions from technicals, news sentiment, fundamentals, and market conditions alongside strongest bullish/bearish signals.
- During pre-market, non-trading, or unknown phases, never fabricate today's intraday tape; when quote, daily bars, or technicals are stale, fallback, missing, fetch_failed, partial, or estimated, `confidence_level` must not be High.

{language_section}
"""

LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT_EN = (
    """You are a trend-trading {market_role} investment analysis Agent equipped with data tools and trading skills, responsible for producing a professional Decision Dashboard report.

{market_guidelines}

## Workflow (execute stages strictly in order; wait for each stage's tool outputs before starting the next)

**Stage 1 · Quote & K-lines** (execute first)
- `get_realtime_quote` to fetch the live quote
- `get_daily_history` to fetch historical daily bars

**Stage 2 · Technicals & Chips** (after Stage 1 completes)
- `analyze_trend` to compute technical indicators
- `get_chip_distribution` to fetch chip distribution

**Stage 3 · Intelligence Search** (after Stages 1 & 2 complete)
- `search_stock_news` to search latest news, shareholder sell-downs, earnings warnings, and risk signals

**Stage 4 · Generate Report** (once all data is ready, output the complete Decision Dashboard JSON)

> ⚠️ Every stage's tool calls must finish before entering the next stage. Do not combine tools from different stages into a single batch.
{default_skill_policy_section}

## Rules

1. **Always ground in real tool data** — never fabricate numbers; all figures must trace to tool outputs.
2. **Systematic analysis** — follow stages strictly in order and never mix tools across stages in one turn.
3. **Apply trading skills** — evaluate every active skill's conditions and reflect them in the report.
4. **Output format** — your final response must be a valid Decision Dashboard JSON object.
5. **Risk first** — screen for insider sell-downs, earnings warnings, and regulatory risks.
6. **Tool failures** — note failed tools, continue with available data, and do not retry broken tools blindly.

{skills_section}

"""
    + _ENGLISH_DASHBOARD_JSON_FORMAT_SECTION
    + """

## Scoring Guide

### Strong Buy (80-100):
- ✅ Bullish MA alignment: MA5 > MA10 > MA20
- ✅ Low bias (<2%), optimal entry window
- ✅ Contracting-volume pullback or volume breakout
- ✅ Healthy chip concentration
- ✅ Positive news catalysts

### Buy (60-79):
- ✅ Bullish or early bullish MA alignment
- ✅ Bias < 5%
- ✅ Healthy volume behavior
- ⚪ Allows one secondary condition unmet

### Watch (40-59):
- ⚠️ Bias > 5% (chasing risk)
- ⚠️ Tangled moving averages / unclear trend
- ⚠️ Active risk events

### Sell / Reduce (0-39):
- ❌ Bearish MA alignment
- ❌ Breakdown below MA20
- ❌ High-volume decline
- ❌ Material negative catalysts

"""
    + _ENGLISH_DASHBOARD_RULES_FOOTER
)

AGENT_SYSTEM_PROMPT_EN = (
    """You are a {market_role} investment analysis Agent equipped with data tools and switchable trading skills, responsible for producing a professional Decision Dashboard report.

{market_guidelines}

## Workflow (execute stages strictly in order; wait for each stage's tool outputs before starting the next)

**Stage 1 · Quote & K-lines** (execute first)
- `get_realtime_quote` to fetch the live quote
- `get_daily_history` to fetch historical daily bars

**Stage 2 · Technicals & Chips** (after Stage 1 completes)
- `analyze_trend` to compute technical indicators
- `get_chip_distribution` to fetch chip distribution

**Stage 3 · Intelligence Search** (after Stages 1 & 2 complete)
- `search_stock_news` to search latest news, shareholder sell-downs, earnings warnings, and risk signals

**Stage 4 · Generate Report** (once all data is ready, output the complete Decision Dashboard JSON)

> ⚠️ Every stage's tool calls must finish before entering the next stage. Do not combine tools from different stages into a single batch.
{default_skill_policy_section}

## Rules

1. **Always ground in real tool data** — never fabricate numbers; all figures must trace to tool outputs.
2. **Systematic analysis** — follow stages strictly in order and never mix tools across stages in one turn.
3. **Apply trading skills** — evaluate every active skill's conditions and reflect them in the report.
4. **Output format** — your final response must be a valid Decision Dashboard JSON object.
5. **Risk first** — screen for insider sell-downs, earnings warnings, and regulatory risks.
6. **Tool failures** — note failed tools, continue with available data, and do not retry broken tools blindly.

{skills_section}

"""
    + _ENGLISH_DASHBOARD_JSON_FORMAT_SECTION
    + """

## Scoring Guide

### Strong Buy (80-100):
- ✅ Multiple active skills align on a positive conclusion
- ✅ Upside, trigger levels, and risk/reward are clearly defined
- ✅ Key risks checked; sizing and stop-loss plans are explicit
- ✅ Market data and intelligence agree

### Buy (60-79):
- ✅ Primary signal leans positive with minor items pending confirmation
- ✅ Manageable risks or secondary entry levels remain
- ✅ State watch conditions clearly in the report

### Watch (40-59):
- ⚠️ Signals conflict or lack confirmation
- ⚠️ Risks and opportunities remain roughly balanced
- ⚠️ Better suited to waiting for triggers or staying sidelined

### Sell / Reduce (0-39):
- ❌ Primary thesis deteriorated; risk clearly outweighs reward
- ❌ Stop-loss/invalidation levels breached or severe negative catalysts
- ❌ Existing exposure prioritizes capital preservation

"""
    + _ENGLISH_DASHBOARD_RULES_FOOTER
)

LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT_EN = """You are a trend-trading {market_role} investment analysis Agent with data tools and trading skills, answering the user's stock analysis questions.

{market_guidelines}

## Workflow (execute stages strictly in order; never skip or merge stages)

When the user asks about a stock, call tools across these four sequential stages and wait for each stage to finish before starting the next:

**Stage 1 · Quote & K-lines** (run first)
- Call `get_realtime_quote` for live quote and current price
- Call `get_daily_history` for recent daily K-line bars

**Stage 2 · Technicals & Chips** (after Stage 1 completes)
- Call `analyze_trend` for MA/MACD/RSI indicators
- Call `get_chip_distribution` for chip distribution structure

**Stage 3 · Intelligence Search** (after Stages 1 & 2 complete)
- Call `search_stock_news` for recent news, filings, insider sell-downs, and earnings warnings

**Stage 4 · Synthesise Response** (after all tool outputs are ready)
- Combine the verified data and active skills into a practical answer and investment guidance

> ⚠️ Never merge tools from different stages into a single turn.
{default_skill_policy_section}

## Rules

1. **Always ground in real tool data** — never fabricate numbers; all figures must trace to tool outputs.
2. **Apply trading skills** — evaluate every active skill's conditions in your answer.
3. **Natural conversation** — answer directly in natural language without outputting JSON unless asked.
4. **Risk first** — always check insider sell-downs, earnings warnings, and regulatory risks.
5. **Tool failures** — note failed tools, continue with available data, and do not retry broken tools.

{skills_section}
{language_section}
"""

CHAT_SYSTEM_PROMPT_EN = """You are a {market_role} investment analysis Agent with data tools and switchable trading skills, answering the user's stock analysis questions.

{market_guidelines}

## Workflow (execute stages strictly in order; never skip or merge stages)

When the user asks about a stock, call tools across these four sequential stages and wait for each stage to finish before starting the next:

**Stage 1 · Quote & K-lines** (run first)
- Call `get_realtime_quote` for live quote and current price
- Call `get_daily_history` for recent daily K-line bars

**Stage 2 · Technicals & Chips** (after Stage 1 completes)
- Call `analyze_trend` for MA/MACD/RSI indicators
- Call `get_chip_distribution` for chip distribution structure

**Stage 3 · Intelligence Search** (after Stages 1 & 2 complete)
- Call `search_stock_news` for recent news, filings, insider sell-downs, and earnings warnings

**Stage 4 · Synthesise Response** (after all tool outputs are ready)
- Combine the verified data and active skills into a practical answer and investment guidance

> ⚠️ Never merge tools from different stages into a single turn.
{default_skill_policy_section}

## Rules

1. **Always ground in real tool data** — never fabricate numbers; all figures must trace to tool outputs.
2. **Apply trading skills** — evaluate every active skill's conditions in your answer.
3. **Natural conversation** — answer directly in natural language without outputting JSON unless asked.
4. **Risk first** — always check insider sell-downs, earnings warnings, and regulatory risks.
5. **Tool failures** — note failed tools, continue with available data, and do not retry broken tools.

{skills_section}
{language_section}
"""


def _localize_default_skill_policy(policy: str, report_language: str) -> str:
    """Use the built-in English skill policy baseline for non-Chinese prompt scaffolding."""
    if report_language != "zh" and policy and policy.strip() == CORE_TRADING_SKILL_POLICY_ZH.strip():
        return CORE_TRADING_SKILL_POLICY_EN
    return policy


def _render_agent_system_prompt(
    *,
    stock_code: str,
    report_language: str,
    skill_instructions: str,
    default_skill_policy: str,
    use_legacy_default_prompt: bool,
    chat_mode: bool,
) -> str:
    """Render the single-agent system prompt in zh/en/ko."""
    if report_language == "zh":
        skills_section = f"## 激活的交易技能\n\n{skill_instructions}" if skill_instructions else ""
        if chat_mode:
            prompt_template = (
                LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT
                if use_legacy_default_prompt
                else CHAT_SYSTEM_PROMPT
            )
        else:
            prompt_template = (
                LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT
                if use_legacy_default_prompt
                else AGENT_SYSTEM_PROMPT
            )
    else:
        skills_section = f"## Active Trading Skills\n\n{skill_instructions}" if skill_instructions else ""
        if chat_mode:
            prompt_template = (
                LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT_EN
                if use_legacy_default_prompt
                else CHAT_SYSTEM_PROMPT_EN
            )
        else:
            prompt_template = (
                LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT_EN
                if use_legacy_default_prompt
                else AGENT_SYSTEM_PROMPT_EN
            )

    localized_policy = _localize_default_skill_policy(default_skill_policy, report_language)
    default_skill_policy_section = f"\n{localized_policy}\n" if localized_policy else ""
    return prompt_template.format(
        market_role=get_market_role(stock_code, report_language),
        market_guidelines=get_market_guidelines(stock_code, report_language),
        default_skill_policy_section=default_skill_policy_section,
        skills_section=skills_section,
        language_section=_build_language_section(report_language, chat_mode=chat_mode),
    )


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
        if normalized == "ko":
            return """
## Output Language

- Reply in Korean (한국어).
- If you output JSON, keep the keys unchanged and write every human-readable value in Korean (한국어).
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
    if normalized == "ko":
        return """
## Output Language

- Keep every JSON key unchanged.
- `decision_type` must remain `buy|hold|sell`.
- All human-readable JSON values must be written in Korean (한국어).
- This includes `stock_name`, `trend_prediction`, `operation_advice`, `confidence_level`, all dashboard text, checklist items, and summaries.
"""

    return """
## 输出语言

- 所有 JSON 键名保持不变。
- `decision_type` 必须保持为 `buy|hold|sell`。
- 所有面向用户的人类可读文本值必须使用中文。
"""


# ============================================================
# Shared chat request preparation
# ============================================================


@dataclass(frozen=True)
class PreparedAgentChat:
    """System prompt, visible history, and scope shared by Agent backends."""

    system_prompt: str
    history_messages: List[Dict[str, Any]]
    stock_scope: Optional[StockScope]
    report_language: str = "zh"


def prepare_agent_chat(
    *,
    message: str,
    session_id: str,
    context: Optional[Dict[str, Any]],
    config: Any,
    context_llm_adapter: Any,
    skill_instructions: str,
    default_skill_policy: str,
    use_legacy_default_prompt: bool,
    include_provider_trace: bool,
    strict_initial_stock_scope: bool = False,
    scope_resolution: Optional[StockScopeResolution] = None,
    db_manager=None,
    source_snapshot: Optional[Dict[str, Any]] = None,
    skill_manager: Optional[Any] = None,
) -> PreparedAgentChat:
    """Build the existing Chat prompt order without choosing an Agent backend."""
    if scope_resolution is None:
        scope_resolution = resolve_stock_scope(
            message,
            context,
            strict_initial_scope=strict_initial_stock_scope,
        )
    effective_context = scope_resolution.effective_context

    report_language = normalize_report_language((effective_context or {}).get("report_language", "zh"))
    stock_code = (effective_context or {}).get("stock_code", "")
    effective_skill_instructions = resolve_skill_instructions_for_language(
        skill_instructions,
        skill_manager,
        report_language,
    )
    system_prompt = _render_agent_system_prompt(
        stock_code=stock_code,
        report_language=report_language,
        skill_instructions=effective_skill_instructions,
        default_skill_policy=default_skill_policy,
        use_legacy_default_prompt=use_legacy_default_prompt,
        chat_mode=True,
    )

    if include_provider_trace:
        history_messages = list(
            build_agent_chat_context_bundle(
                session_id, context_llm_adapter, config,
                **({"db_manager": db_manager, "source_snapshot": source_snapshot}
                   if source_snapshot is not None else {}),
            ).context_messages
        )
    else:
        history_messages = list(
            build_visible_chat_history(
                session_id,
                context_llm_adapter,
                config,
                allow_llm_compression=False,
                **({"db_manager": db_manager, "source_snapshot": source_snapshot}
                   if source_snapshot is not None else {}),
            )
        )

    if effective_context:
        context_parts = []
        if report_language == "zh":
            if effective_context.get("stock_code"):
                context_parts.append(f"股票代码: {effective_context['stock_code']}")
            if effective_context.get("stock_name"):
                context_parts.append(f"股票名称: {effective_context['stock_name']}")
            if effective_context.get("previous_price"):
                context_parts.append(f"上次分析价格: {effective_context['previous_price']}")
            if effective_context.get("previous_change_pct"):
                context_parts.append(f"上次涨跌幅: {effective_context['previous_change_pct']}%")
            if effective_context.get("previous_analysis_summary"):
                summary = effective_context["previous_analysis_summary"]
                summary_text = json.dumps(summary, ensure_ascii=False) if isinstance(summary, dict) else str(summary)
                context_parts.append(f"上次分析摘要:\n{summary_text}")
            if effective_context.get("previous_strategy"):
                strategy = effective_context["previous_strategy"]
                strategy_text = json.dumps(strategy, ensure_ascii=False) if isinstance(strategy, dict) else str(strategy)
                context_parts.append(f"上次策略分析:\n{strategy_text}")
        else:
            if effective_context.get("stock_code"):
                context_parts.append(f"Stock code: {effective_context['stock_code']}")
            if effective_context.get("stock_name"):
                context_parts.append(f"Stock name: {effective_context['stock_name']}")
            if effective_context.get("previous_price"):
                context_parts.append(f"Previous price: {effective_context['previous_price']}")
            if effective_context.get("previous_change_pct"):
                context_parts.append(f"Previous change %: {effective_context['previous_change_pct']}%")
            if effective_context.get("previous_analysis_summary"):
                summary = effective_context["previous_analysis_summary"]
                summary_text = json.dumps(summary, ensure_ascii=False) if isinstance(summary, dict) else str(summary)
                context_parts.append(f"Previous analysis summary:\n{summary_text}")
            if effective_context.get("previous_strategy"):
                strategy = effective_context["previous_strategy"]
                strategy_text = json.dumps(strategy, ensure_ascii=False) if isinstance(strategy, dict) else str(strategy)
                context_parts.append(f"Previous strategy analysis:\n{strategy_text}")
        daily_market_context_section = format_daily_market_context_prompt_section(
            effective_context.get("daily_market_context"),
            report_language=report_language,
        )
        if daily_market_context_section:
            context_parts.append(daily_market_context_section.strip())
        market_structure_section = format_market_structure_prompt_section(
            effective_context.get("market_structure_context"),
            report_language=report_language,
        )
        if market_structure_section:
            context_parts.append(market_structure_section.strip())
        if context_parts:
            if report_language == "zh":
                ctx_header = "[系统提供的历史分析上下文，可供参考对比]\n"
                ctx_ack = "好的，我已了解该股票的历史分析数据。请告诉我你想了解什么？"
            else:
                ctx_header = "[System-provided historical analysis context for reference]\n"
                ctx_ack = "Understood. I have reviewed the historical analysis context for this stock. How can I help?"
            history_messages.extend(
                [
                    {
                        "role": "user",
                        "content": ctx_header + "\n".join(context_parts),
                    },
                    {
                        "role": "assistant",
                        "content": ctx_ack,
                    },
                ]
            )

    return PreparedAgentChat(
        system_prompt=system_prompt,
        history_messages=history_messages,
        stock_scope=scope_resolution.stock_scope,
        report_language=report_language,
    )


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
        skill_manager: Optional[Any] = None,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions
        self.default_skill_policy = default_skill_policy
        self.use_legacy_default_prompt = use_legacy_default_prompt
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.skill_manager = skill_manager

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a given task.

        Args:
            task: The user task / analysis request.
            context: Optional context dict (e.g., {"stock_code": "600519"}).

        Returns:
            AgentResult with parsed dashboard or error.
        """
        report_language = normalize_report_language((context or {}).get("report_language", "zh"))
        stock_code = (context or {}).get("stock_code", "")
        effective_skill_instructions = resolve_skill_instructions_for_language(
            self.skill_instructions,
            self.skill_manager,
            report_language,
        )
        system_prompt = _render_agent_system_prompt(
            stock_code=stock_code,
            report_language=report_language,
            skill_instructions=effective_skill_instructions,
            default_skill_policy=self.default_skill_policy,
            use_legacy_default_prompt=self.use_legacy_default_prompt,
            chat_mode=False,
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
        from src.services.agent_chat_session_service import AgentChatSessionService

        db, snapshot = conversation_manager.prepare_turn(session_id)
        config = getattr(self.llm_adapter, "_config", None) or get_config()
        scope_resolution, disposition = AgentChatSessionService(db).prepare_compatibility_turn(
            config, snapshot, message, context=context,
        )
        prepared = prepare_agent_chat(
            message=message,
            session_id=session_id,
            context=context,
            config=config,
            context_llm_adapter=self.llm_adapter,
            skill_instructions=self.skill_instructions,
            default_skill_policy=self.default_skill_policy,
            use_legacy_default_prompt=self.use_legacy_default_prompt,
            include_provider_trace=True,
            db_manager=db,
            source_snapshot=snapshot,
            scope_resolution=scope_resolution,
            skill_manager=self.skill_manager,
        )
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": prepared.system_prompt},
            *prepared.history_messages,
        ]
        messages.append({"role": "user", "content": message})
        baseline_len = len(messages)
        run_id = str(uuid.uuid4())

        # Persist the user turn immediately so the session appears in history during processing
        accepted = conversation_manager.commit_user_turn(db, snapshot, message, state_disposition=disposition)
        user_message_id = accepted["user_message_id"]

        tool_decls = self.tool_registry.to_openai_tools()
        result = self._run_loop(
            messages,
            tool_decls,
            parse_dashboard=False,
            progress_callback=progress_callback,
            stock_scope=prepared.stock_scope,
        )

        # Persist assistant reply (or error note) for context continuity
        if result.success:
            assistant_message_id = conversation_manager.add_message(
                session_id, "assistant", result.content, accepted_turn=accepted, db_manager=db,
            )
            if assistant_message_id is not None:
                self._persist_provider_trace(
                    session_id=session_id,
                    run_id=run_id,
                    messages=result.messages,
                    baseline_len=baseline_len,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    accepted_turn=accepted,
                    db_factory=lambda: db,
                )
        else:
            error_note = format_chat_failure_message(result.error, prepared.report_language)
            conversation_manager.add_message(session_id, "assistant", error_note, accepted_turn=accepted, db_manager=db)

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
        accepted_turn=None,
        db_factory=None,
    ) -> None:
        persist_provider_trace_turns(
            session_id=session_id,
            run_id=run_id,
            messages=messages,
            baseline_len=baseline_len,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            db_factory=db_factory if db_factory is not None else get_db,
            accepted_turn=accepted_turn,
            log=logger,
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

        Dashboard mode exposes only the parsed canonical payload through both
        ``dashboard`` and ``content``; free-form mode preserves the raw text.
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
                content=(
                    json.dumps(dashboard, ensure_ascii=False, indent=2, allow_nan=False)
                    if dashboard is not None
                    else loop_result.content
                ),
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
        report_language = normalize_report_language((context or {}).get("report_language", "zh"))
        if context:
            if report_language == "zh":
                if context.get("stock_code"):
                    parts.append(f"\n股票代码: {context['stock_code']}")
                if context.get("report_type"):
                    parts.append(f"报告类型: {context['report_type']}")
            else:
                if context.get("stock_code"):
                    parts.append(f"\nStock code: {context['stock_code']}")
                if context.get("report_type"):
                    parts.append(f"Report type: {context['report_type']}")
            if report_language == "en":
                parts.append("Output language: English (keep every JSON key unchanged and write all human-readable values in English)")
            elif report_language == "ko":
                parts.append("출력 언어: 한국어 (모든 JSON 키는 그대로 유지하고, 사용자 노출 텍스트 값은 한국어로 작성)")
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
            if report_language == "zh":
                if context.get("realtime_quote"):
                    parts.append(f"\n[系统已获取的实时行情]\n{json.dumps(context['realtime_quote'], ensure_ascii=False)}")
                if context.get("chip_distribution"):
                    parts.append(f"\n[系统已获取的筹码分布]\n{json.dumps(context['chip_distribution'], ensure_ascii=False)}")
                if context.get("news_context"):
                    parts.append(f"\n[系统已获取的新闻与舆情情报]\n{context['news_context']}")
            else:
                if context.get("realtime_quote"):
                    parts.append(f"\n[System-fetched realtime quote]\n{json.dumps(context['realtime_quote'], ensure_ascii=False)}")
                if context.get("chip_distribution"):
                    parts.append(f"\n[System-fetched chip distribution]\n{json.dumps(context['chip_distribution'], ensure_ascii=False)}")
                if context.get("news_context"):
                    parts.append(f"\n[System-fetched news and sentiment intelligence]\n{context['news_context']}")

        if report_language == "zh":
            parts.append("\n请使用可用工具获取缺失的数据（如历史K线、新闻等），然后以决策仪表盘 JSON 格式输出分析结果。")
        else:
            parts.append(
                "\nUse the available tools to fetch any missing data (such as daily history or news), "
                "then output the Decision Dashboard JSON."
            )
        return "\n".join(parts)
