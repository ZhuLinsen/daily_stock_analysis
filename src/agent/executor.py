# -*- coding: utf-8 -*-
"""
Agent Executor — ReAct loop with tool calling.

Orchestrates the LLM + tools interaction loop:
1. Build system prompt (persona + tools + skills)
2. Send to LLM with tool declarations
3. If tool_call → execute tool → feed result back
4. If text → parse as final answer
5. Loop until final answer or max_steps
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from json_repair import repair_json

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# Tool name → short label used to build contextual thinking messages
_THINKING_TOOL_LABELS: Dict[str, str] = {
    "get_realtime_quote": "行情获取",
    "get_daily_history": "K线数据获取",
    "analyze_trend": "技术指标分析",
    "get_chip_distribution": "筹码分布分析",
    "search_stock_news": "新闻搜索",
    "search_comprehensive_intel": "综合情报搜索",
    "get_market_indices": "市场概览获取",
    "get_sector_rankings": "行业板块分析",
    "get_analysis_context": "历史分析上下文",
    "get_stock_info": "基本信息获取",
    "analyze_pattern": "K线形态识别",
    "get_volume_analysis": "量能分析",
    "calculate_ma": "均线计算",
}


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
    error: Optional[str] = None


# ============================================================
# System prompt builder
# ============================================================

AGENT_SYSTEM_PROMPT = """你是一位专注于趋势交易的 A 股投资分析 Agent，拥有数据工具和交易策略，负责生成专业的【决策仪表盘】分析报告。

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

## 核心交易理念（必须严格遵守）

### 1. 严进策略（不追高）
- **绝对不追高**：当股价偏离 MA5 超过 5% 时，坚决不买入
- 乖离率 < 2%：最佳买点区间
- 乖离率 2-5%：可小仓介入
- 乖离率 > 5%：严禁追高！直接判定为"观望"

### 2. 趋势交易（顺势而为）
- **多头排列必须条件**：MA5 > MA10 > MA20
- 只做多头排列的股票，空头排列坚决不碰
- 均线发散上行优于均线粘合

### 3. 效率优先（筹码结构）
- 关注筹码集中度：90%集中度 < 15% 表示筹码集中
- 获利比例分析：70-90% 获利盘时需警惕获利回吐
- 平均成本与现价关系：现价高于平均成本 5-15% 为健康

### 4. 买点偏好（回踩支撑）
- **最佳买点**：缩量回踩 MA5 获得支撑
- **次优买点**：回踩 MA10 获得支撑
- **观望情况**：跌破 MA20 时观望

### 5. 风险排查重点
- 减持公告、业绩预亏、监管处罚、行业政策利空、大额解禁

### 6. 估值关注（PE/PB）
- PE 明显偏高时需在风险点中说明

### 7. 强势趋势股放宽
- 强势趋势股可适当放宽乖离率要求，轻仓追踪但需设止损

## 规则

1. **必须调用工具获取真实数据** — 绝不编造数字，所有数据必须来自工具返回结果。
2. **系统化分析** — 严格按工作流程分阶段执行，每阶段完整返回后再进入下一阶段，**禁止**将不同阶段的工具合并到同一次调用中。
3. **应用交易策略** — 评估每个激活策略的条件，在报告中体现策略判断结果。
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
"""

CHAT_SYSTEM_PROMPT = """你是一位专注于趋势交易的 A 股投资分析 Agent，拥有数据工具和交易策略，负责解答用户的股票投资问题。

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
- 基于上述真实数据，结合激活策略进行综合研判，输出投资建议

> ⚠️ 禁止将不同阶段的工具合并到同一次调用中（例如禁止在第一次调用中同时请求行情、技术指标和新闻）。

## 核心交易理念（必须严格遵守）

### 1. 严进策略（不追高）
- **绝对不追高**：当股价偏离 MA5 超过 5% 时，坚决不买入
- 乖离率 < 2%：最佳买点区间
- 乖离率 2-5%：可小仓介入
- 乖离率 > 5%：严禁追高！直接判定为"观望"

### 2. 趋势交易（顺势而为）
- **多头排列必须条件**：MA5 > MA10 > MA20
- 只做多头排列的股票，空头排列坚决不碰
- 均线发散上行优于均线粘合

### 3. 效率优先（筹码结构）
- 关注筹码集中度：90%集中度 < 15% 表示筹码集中
- 获利比例分析：70-90% 获利盘时需警惕获利回吐
- 平均成本与现价关系：现价高于平均成本 5-15% 为健康

### 4. 买点偏好（回踩支撑）
- **最佳买点**：缩量回踩 MA5 获得支撑
- **次优买点**：回踩 MA10 获得支撑
- **观望情况**：跌破 MA20 时观望

### 5. 风险排查重点
- 减持公告、业绩预亏、监管处罚、行业政策利空、大额解禁

### 6. 估值关注（PE/PB）
- PE 明显偏高时需在风险点中说明

### 7. 强势趋势股放宽
- 强势趋势股可适当放宽乖离率要求，轻仓追踪但需设止损

## 规则

1. **必须调用工具获取真实数据** — 绝不编造数字，所有数据必须来自工具返回结果。
2. **应用交易策略** — 评估每个激活策略的条件，在回答中体现策略判断结果。
3. **自由对话** — 根据用户的问题，自由组织语言回答，不需要输出 JSON。
4. **风险优先** — 必须排查风险（股东减持、业绩预警、监管问题）。
5. **工具失败处理** — 记录失败原因，使用已有数据继续分析，不重复调用失败工具。

{skills_section}
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
        max_steps: int = 10,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions
        self.max_steps = max_steps

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a given task.

        Args:
            task: The user task / analysis request.
            context: Optional context dict (e.g., {"stock_code": "600519"}).

        Returns:
            AgentResult with parsed dashboard or error.
        """
        start_time = time.time()
        tool_calls_log: List[Dict[str, Any]] = []
        total_tokens = 0

        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 激活的交易策略\n\n{self.skill_instructions}"
        system_prompt = AGENT_SYSTEM_PROMPT.format(skills_section=skills_section)

        # Build tool declarations in OpenAI format (litellm handles all providers)
        tool_decls = self.tool_registry.to_openai_tools()

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._build_user_message(task, context)},
        ]

        return self._run_loop(messages, tool_decls, start_time, tool_calls_log, total_tokens, parse_dashboard=True)

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
        
        start_time = time.time()
        tool_calls_log: List[Dict[str, Any]] = []
        total_tokens = 0

        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 激活的交易策略\n\n{self.skill_instructions}"
        system_prompt = CHAT_SYSTEM_PROMPT.format(skills_section=skills_section)

        # Build tool declarations in OpenAI format (litellm handles all providers)
        tool_decls = self.tool_registry.to_openai_tools()

        # Get conversation history
        session = conversation_manager.get_or_create(session_id)
        history = session.get_history()

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(history)

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
            if context_parts:
                context_msg = "[系统提供的历史分析上下文，可供参考对比]\n" + "\n".join(context_parts)
                messages.append({"role": "user", "content": context_msg})
                messages.append({"role": "assistant", "content": "好的，我已了解该股票的历史分析数据。请告诉我你想了解什么？"})

        messages.append({"role": "user", "content": message})

        # Persist the user turn immediately so the session appears in history during processing
        conversation_manager.add_message(session_id, "user", message)

        result = self._run_loop(messages, tool_decls, start_time, tool_calls_log, total_tokens, parse_dashboard=False, progress_callback=progress_callback)

        # Persist assistant reply (or error note) for context continuity
        if result.success:
            conversation_manager.add_message(session_id, "assistant", result.content)
        else:
            error_note = f"[分析失败] {result.error or '未知错误'}"
            conversation_manager.add_message(session_id, "assistant", error_note)

        return result

    def _run_loop(self, messages: List[Dict[str, Any]], tool_decls: List[Dict[str, Any]], start_time: float, tool_calls_log: List[Dict[str, Any]], total_tokens: int, parse_dashboard: bool, progress_callback: Optional[Callable] = None) -> AgentResult:
        provider_used = ""

        for step in range(self.max_steps):
            logger.info(f"Agent step {step + 1}/{self.max_steps}")

            if progress_callback:
                if not tool_calls_log:
                    thinking_msg = "正在制定分析路径..."
                else:
                    last_tool = tool_calls_log[-1].get("tool", "")
                    label = _THINKING_TOOL_LABELS.get(last_tool, last_tool)
                    thinking_msg = f"「{label}」已完成，继续深入分析..."
                progress_callback({"type": "thinking", "step": step + 1, "message": thinking_msg})

            response = self.llm_adapter.call_with_tools(messages, tool_decls)
            provider_used = response.provider
            total_tokens += response.usage.get("total_tokens", 0)

            if response.tool_calls:
                # LLM wants to call tools
                logger.info(f"Agent requesting {len(response.tool_calls)} tool call(s): "
                          f"{[tc.name for tc in response.tool_calls]}")

                # Add assistant message with tool calls to history
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                            **({"thought_signature": tc.thought_signature} if tc.thought_signature is not None else {}),
                        }
                        for tc in response.tool_calls
                    ],
                }
                # Only present for DeepSeek thinking mode; None for all other providers
                if response.reasoning_content is not None:
                    assistant_msg["reasoning_content"] = response.reasoning_content
                messages.append(assistant_msg)

                # Execute tool calls — parallel when multiple, sequential when single
                tool_results: List[Dict[str, Any]] = []

                def _exec_single_tool(tc_item):
                    """Execute one tool and return (tc, result_str, success, duration)."""
                    t0 = time.time()
                    try:
                        res = self.tool_registry.execute(tc_item.name, **tc_item.arguments)
                        res_str = self._serialize_tool_result(res)
                        ok = True
                    except Exception as e:
                        res_str = json.dumps({"error": str(e)})
                        ok = False
                        logger.warning(f"Tool '{tc_item.name}' failed: {e}")
                    dur = time.time() - t0
                    return tc_item, res_str, ok, round(dur, 2)

                if len(response.tool_calls) == 1:
                    # Single tool — run inline (no thread overhead)
                    tc = response.tool_calls[0]
                    if progress_callback:
                        progress_callback({"type": "tool_start", "step": step + 1, "tool": tc.name})
                    _, result_str, success, tool_duration = _exec_single_tool(tc)
                    if progress_callback:
                        progress_callback({"type": "tool_done", "step": step + 1, "tool": tc.name, "success": success, "duration": tool_duration})
                    tool_calls_log.append({
                        "step": step + 1, "tool": tc.name, "arguments": tc.arguments,
                        "success": success, "duration": tool_duration, "result_length": len(result_str),
                    })
                    tool_results.append({"tc": tc, "result_str": result_str})
                else:
                    # Multiple tools — run in parallel threads
                    for tc in response.tool_calls:
                        if progress_callback:
                            progress_callback({"type": "tool_start", "step": step + 1, "tool": tc.name})

                    with ThreadPoolExecutor(max_workers=min(len(response.tool_calls), 5)) as pool:
                        futures = {pool.submit(_exec_single_tool, tc): tc for tc in response.tool_calls}
                        for future in as_completed(futures):
                            tc_item, result_str, success, tool_duration = future.result()
                            if progress_callback:
                                progress_callback({"type": "tool_done", "step": step + 1, "tool": tc_item.name, "success": success, "duration": tool_duration})
                            tool_calls_log.append({
                                "step": step + 1, "tool": tc_item.name, "arguments": tc_item.arguments,
                                "success": success, "duration": tool_duration, "result_length": len(result_str),
                            })
                            tool_results.append({"tc": tc_item, "result_str": result_str})

                # Append tool results to messages (ordered by original tool_calls order)
                tc_order = {tc.id: i for i, tc in enumerate(response.tool_calls)}
                tool_results.sort(key=lambda x: tc_order.get(x["tc"].id, 0))
                for tr in tool_results:
                    messages.append({
                        "role": "tool",
                        "name": tr["tc"].name,
                        "tool_call_id": tr["tc"].id,
                        "content": tr["result_str"],
                    })

            else:
                # LLM returned text — this is the final answer
                logger.info(f"Agent completed in {step + 1} steps "
                          f"({time.time() - start_time:.1f}s, {total_tokens} tokens)")
                if progress_callback:
                    progress_callback({"type": "generating", "step": step + 1, "message": "正在生成最终分析..."})

                final_content = response.content or ""
                
                if parse_dashboard:
                    dashboard = self._parse_dashboard(final_content)
                    return AgentResult(
                        success=dashboard is not None,
                        content=final_content,
                        dashboard=dashboard,
                        tool_calls_log=tool_calls_log,
                        total_steps=step + 1,
                        total_tokens=total_tokens,
                        provider=provider_used,
                        error=None if dashboard else "Failed to parse dashboard JSON from agent response",
                    )
                else:
                    if response.provider == "error":
                        return AgentResult(
                            success=False,
                            content="",
                            dashboard=None,
                            tool_calls_log=tool_calls_log,
                            total_steps=step + 1,
                            total_tokens=total_tokens,
                            provider=provider_used,
                            error=final_content,
                        )
                    return AgentResult(
                        success=True,
                        content=final_content,
                        dashboard=None,
                        tool_calls_log=tool_calls_log,
                        total_steps=step + 1,
                        total_tokens=total_tokens,
                        provider=provider_used,
                        error=None,
                    )

        # Max steps exceeded
        logger.warning(f"Agent hit max steps ({self.max_steps})")
        return AgentResult(
            success=False,
            content="",
            tool_calls_log=tool_calls_log,
            total_steps=self.max_steps,
            total_tokens=total_tokens,
            provider=provider_used,
            error=f"Agent exceeded max steps ({self.max_steps})",
        )

    def _build_user_message(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Build the initial user message."""
        parts = [task]
        if context:
            if context.get("stock_code"):
                parts.append(f"\n股票代码: {context['stock_code']}")
            if context.get("report_type"):
                parts.append(f"报告类型: {context['report_type']}")
            
            # 注入已有的上下文数据，避免重复获取
            if context.get("realtime_quote"):
                parts.append(f"\n[系统已获取的实时行情]\n{json.dumps(context['realtime_quote'], ensure_ascii=False)}")
            if context.get("chip_distribution"):
                parts.append(f"\n[系统已获取的筹码分布]\n{json.dumps(context['chip_distribution'], ensure_ascii=False)}")
                
        parts.append("\n请使用可用工具获取缺失的数据（如历史K线、新闻等），然后以决策仪表盘 JSON 格式输出分析结果。")
        return "\n".join(parts)

    def _serialize_tool_result(self, result: Any) -> str:
        """Serialize a tool result to a JSON string for the LLM."""
        if result is None:
            return json.dumps({"result": None})
        if isinstance(result, str):
            return result
        if isinstance(result, (dict, list)):
            try:
                return json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                return str(result)
        # Dataclass or object with __dict__
        if hasattr(result, '__dict__'):
            try:
                d = {k: v for k, v in result.__dict__.items() if not k.startswith('_')}
                return json.dumps(d, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                return str(result)
        return str(result)

    def _parse_dashboard(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract and parse the Decision Dashboard JSON from agent response."""
        if not content:
            return None

        # Try to extract JSON from markdown code blocks
        json_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if json_blocks:
            for block in json_blocks:
                try:
                    parsed = json.loads(block)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    try:
                        repaired = repair_json(block)
                        parsed = json.loads(repaired)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        continue

        # Try raw JSON parse
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try json_repair
        try:
            repaired = repair_json(content)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Try to find JSON object in text
        brace_start = content.find('{')
        brace_end = content.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            candidate = content[brace_start:brace_end + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                try:
                    repaired = repair_json(candidate)
                    parsed = json.loads(repaired)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass

        logger.warning("Failed to parse dashboard JSON from agent response")
        return None
