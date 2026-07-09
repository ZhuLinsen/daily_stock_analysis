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
from src.storage import get_db
from src.agent.tools.registry import ToolRegistry
from src.report_language import normalize_report_language
from src.market_context import get_market_role, get_market_guidelines
from src.market_phase_prompt import format_market_phase_prompt_section

logger = logging.getLogger(__name__)

_PREBUILT_RESULT_FIELDS = (
    "code",
    "name",
    "operation_advice",
    "trend_prediction",
    "sentiment_score",
    "confidence_level",
    "analysis_summary",
    "risk_warning",
    "news_summary",
    "report_language",
)
_PREBUILT_SNAPSHOT_FIELDS = (
    "code",
    "name",
    "market",
    "today",
    "yesterday",
    "realtime",
    "trend",
    "fundamental",
    "market_phase_context",
    "news_context",
)
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "token",
    "secret",
    "authorization",
    "webhook",
    "password",
)
_PREBUILT_VALUE_CHAR_CAP = 800
_PREBUILT_SECTION_CHAR_CAP = 4000


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _get_payload_field(payload: Any, field: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(field)
    return getattr(payload, field, None)


def _sanitize_prebuilt_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_prebuilt_obj(val)
            for key, val in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_prebuilt_obj(item) for item in list(value)[:20]]
    return value


def _safe_prebuilt_value(value: Any, *, max_chars: int = _PREBUILT_VALUE_CHAR_CAP) -> str:
    if isinstance(value, dict):
        text = json.dumps(_sanitize_prebuilt_obj(value), ensure_ascii=False, default=str)
    elif isinstance(value, (list, tuple)):
        text = json.dumps(_sanitize_prebuilt_obj(value), ensure_ascii=False, default=str)
    else:
        text = str(value)
    if len(text) > max_chars:
        return text[:max_chars] + "...[TRUNCATED]"
    return text


def _cap_prebuilt_section(text: str) -> str:
    if len(text) <= _PREBUILT_SECTION_CHAR_CAP:
        return text
    return text[:_PREBUILT_SECTION_CHAR_CAP] + "...[TRUNCATED: prebuilt context capped]"


def build_prebuilt_context_summary(context: Optional[Dict[str, Any]]) -> str:
    """Return a low-sensitivity read-only summary for QA prompt context."""
    if not context:
        return ""

    result = context.get("pre_built_result")
    if result:
        lines = ["[系統提供的只讀預構建分析結果]"]
        for field in _PREBUILT_RESULT_FIELDS:
            value = _get_payload_field(result, field)
            if value is None or value == "":
                continue
            lines.append(f"- {field}: {_safe_prebuilt_value(value)}")
        return _cap_prebuilt_section("\n".join(lines))

    snapshot = context.get("pre_built_context")
    if isinstance(snapshot, dict) and snapshot:
        lines = ["[系統提供的只讀 pre_built_context 快照摘要]"]
        for field in _PREBUILT_SNAPSHOT_FIELDS:
            if field not in snapshot or _is_sensitive_key(field):
                continue
            value = snapshot.get(field)
            if value is None or value == "":
                continue
            lines.append(f"- {field}: {_safe_prebuilt_value(value)}")
        return _cap_prebuilt_section("\n".join(lines))

    return ""


def get_prebuilt_report_language(context: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return report_language embedded in the preferred prebuilt payload."""
    if not context:
        return None
    result = context.get("pre_built_result")
    if result:
        value = _get_payload_field(result, "report_language")
        if isinstance(value, str) and value.strip():
            return value
    snapshot = context.get("pre_built_context")
    if isinstance(snapshot, dict):
        value = snapshot.get("report_language")
        if isinstance(value, str) and value.strip():
            return value
    return None


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

LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT = """你是一位專注於趨勢交易的{market_role}投資分析 Agent，擁有資料工具和交易技能，負責生成專業的【決策儀表盤】分析報告。

{market_guidelines}

## 工作流程（必須嚴格按階段順序執行，每階段等工具結果返回後再進入下一階段）

**第一階段 · 行情與K線**（首先執行）
- `get_realtime_quote` 獲取實時行情
- `get_daily_history` 獲取歷史K線

**第二階段 · 技術指標**（等第一階段結果返回後執行）
- `analyze_trend` 獲取技術指標

**第三階段 · 情報搜尋**（等前兩階段完成後執行）
- `search_stock_news` 搜尋最新資訊、減持、業績預告等風險訊號

**第四階段 · 生成報告**（所有資料就緒後，輸出完整決策儀表盤 JSON）

> ⚠️ 每階段的工具呼叫必須完整返回結果後，才能進入下一階段。禁止將不同階段的工具合併到同一次呼叫中。
{default_skill_policy_section}

## 規則

1. **必須呼叫工具獲取真實資料** — 絕不編造數字，所有資料必須來自工具返回結果。
2. **系統化分析** — 嚴格按工作流程分階段執行，每階段完整返回後再進入下一階段，**禁止**將不同階段的工具合併到同一次呼叫中。
3. **應用交易技能** — 評估每個啟用技能的條件，在報告中體現技能判斷結果。
4. **輸出格式** — 最終響應必須是有效的決策儀表盤 JSON。
5. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
6. **工具失敗處理** — 記錄失敗原因，使用已有資料繼續分析，不重複呼叫失敗工具。

{skills_section}

## 輸出格式：決策儀表盤 JSON

你的最終響應必須是以下結構的有效 JSON 物件：

```json
{{
    "stock_name": "股票中文名稱",
    "sentiment_score": 0-100整數,
    "trend_prediction": "強烈看多/看多/震盪/看空/強烈看空",
    "operation_advice": "買進/加倉/持有/減倉/賣出/觀望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "一句話核心結論（30字以內）",
            "signal_type": "🟢買進訊號/🟡持有觀望/🔴賣出訊號/⚠️風險警告",
            "time_sensitivity": "立即行動/今日內/本週內/不急",
            "position_advice": {{
                "no_position": "空倉者建議",
                "has_position": "持股者建議"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}}
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
            "action_window": "盤前計劃/盤中跟蹤/午間確認/收盤前風控/盤後覆盤/非交易日觀察",
            "immediate_action": "立即行動/等待確認/觀察/止損止盈預警/禁止追高/無盤中動作",
            "watch_conditions": ["觀察條件1", "觀察條件2"],
            "next_check_time": "下一次檢查點或市場本地時間",
            "confidence_reason": "置信度理由，說明階段和資料質量限制",
            "data_limitations": ["階段或資料質量限制1", "階段或資料質量限制2"]
        }}
    }},
    "analysis_summary": "100字綜合分析摘要",
    "key_points": "3-5個核心看點，逗號分隔",
    "risk_warning": "風險提示",
    "buy_reason": "操作理由，引用交易理念",
    "trend_analysis": "走勢形態分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技術面綜合分析",
    "ma_analysis": "均線系統分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K線形態分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板塊行業分析",
    "company_highlights": "公司亮點/風險",
    "news_summary": "新聞摘要",
    "market_sentiment": "市場情緒",
    "hot_topics": "相關熱點"{value_network_schema_field}
}}
```

## 評分標準

### 強烈買進（80-100分）：
- ✅ 多頭排列：MA5 > MA10 > MA20
- ✅ 低乖離率：<2%，最佳買點
- ✅ 縮量回撥或放量突破
- ✅ 訊息面有利好催化

### 買進（60-79分）：
- ✅ 多頭排列或弱勢多頭
- ✅ 乖離率 <5%
- ✅ 量能正常
- ⚪ 允許一項次要條件不滿足

### 觀望（40-59分）：
- ⚠️ 乖離率 >5%（追高風險）
- ⚠️ 均線纏繞趨勢不明
- ⚠️ 有風險事件

### 賣出/減倉（0-39分）：
- ❌ 空頭排列
- ❌ 跌破MA20
- ❌ 放量下跌
- ❌ 重大利空

## 決策儀表盤核心原則

1. **核心結論先行**：一句話說清該買該賣
2. **分持股建議**：空倉者和持股者給不同建議
3. **精確狙擊點**：必須給出具體價格，不說模糊的話
4. **檢查清單視覺化**：用 ✅⚠️❌ 明確顯示每項檢查結果
5. **風險優先順序**：輿情中的風險點要醒目標出

## 可操作性與穩定性約束

- 不得僅因為單日漲跌或評分跨線就在“買進/賣出”之間劇烈切換。
- 操作建議必須同時參考價格位置（支撐/壓力位）、量能、主力資金流向和風險事件。
- 股價位於支撐與壓力之間、資金流不明確時，優先輸出“持有/震盪/觀望/洗盤觀察”等可執行的中性建議；`decision_type` 仍保持 `hold`。
- 只有在接近支撐確認或有效突破壓力，且資金流/量價配合時，才能給出買進；接近壓力且資金流出時不得追買。
- 只有在跌破關鍵支撐、主力資金持續流出或風險顯著放大時，才能給出賣出/減倉。
- 必須輸出 `dashboard.phase_decision` 七欄位；盤中/午休/臨近收盤要給出當前動作、觀察條件和下一次檢查點。
- 盤前、非交易日或未知階段不得偽造今日盤中走勢；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 時，`confidence_level` 不得為高。
{value_network_instruction_section}
{language_section}
"""

AGENT_SYSTEM_PROMPT = """你是一位{market_role}投資分析 Agent，擁有資料工具和可切換交易技能，負責生成專業的【決策儀表盤】分析報告。

{market_guidelines}

## 工作流程（必須嚴格按階段順序執行，每階段等工具結果返回後再進入下一階段）

**第一階段 · 行情與K線**（首先執行）
- `get_realtime_quote` 獲取實時行情
- `get_daily_history` 獲取歷史K線

**第二階段 · 技術指標**（等第一階段結果返回後執行）
- `analyze_trend` 獲取技術指標

**第三階段 · 情報搜尋**（等前兩階段完成後執行）
- `search_stock_news` 搜尋最新資訊、減持、業績預告等風險訊號

**第四階段 · 生成報告**（所有資料就緒後，輸出完整決策儀表盤 JSON）

> ⚠️ 每階段的工具呼叫必須完整返回結果後，才能進入下一階段。禁止將不同階段的工具合併到同一次呼叫中。
{default_skill_policy_section}

## 規則

1. **必須呼叫工具獲取真實資料** — 絕不編造數字，所有資料必須來自工具返回結果。
2. **系統化分析** — 嚴格按工作流程分階段執行，每階段完整返回後再進入下一階段，**禁止**將不同階段的工具合併到同一次呼叫中。
3. **應用交易技能** — 評估每個啟用技能的條件，在報告中體現技能判斷結果。
4. **輸出格式** — 最終響應必須是有效的決策儀表盤 JSON。
5. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
6. **工具失敗處理** — 記錄失敗原因，使用已有資料繼續分析，不重複呼叫失敗工具。

{skills_section}

## 輸出格式：決策儀表盤 JSON

你的最終響應必須是以下結構的有效 JSON 物件：

```json
{{
    "stock_name": "股票中文名稱",
    "sentiment_score": 0-100整數,
    "trend_prediction": "強烈看多/看多/震盪/看空/強烈看空",
    "operation_advice": "買進/加倉/持有/減倉/賣出/觀望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "一句話核心結論（30字以內）",
            "signal_type": "🟢買進訊號/🟡持有觀望/🔴賣出訊號/⚠️風險警告",
            "time_sensitivity": "立即行動/今日內/本週內/不急",
            "position_advice": {{
                "no_position": "空倉者建議",
                "has_position": "持股者建議"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}}
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
            "action_window": "盤前計劃/盤中跟蹤/午間確認/收盤前風控/盤後覆盤/非交易日觀察",
            "immediate_action": "立即行動/等待確認/觀察/止損止盈預警/禁止追高/無盤中動作",
            "watch_conditions": ["觀察條件1", "觀察條件2"],
            "next_check_time": "下一次檢查點或市場本地時間",
            "confidence_reason": "置信度理由，說明階段和資料質量限制",
            "data_limitations": ["階段或資料質量限制1", "階段或資料質量限制2"]
        }}
    }},
    "analysis_summary": "100字綜合分析摘要",
    "key_points": "3-5個核心看點，逗號分隔",
    "risk_warning": "風險提示",
    "buy_reason": "操作理由，引用啟用技能或風險框架",
    "trend_analysis": "走勢形態分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技術面綜合分析",
    "ma_analysis": "均線系統分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K線形態分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板塊行業分析",
    "company_highlights": "公司亮點/風險",
    "news_summary": "新聞摘要",
    "market_sentiment": "市場情緒",
    "hot_topics": "相關熱點"{value_network_schema_field}
}}
```

## 評分標準

### 強烈買進（80-100分）：
- ✅ 多個啟用技能同時支援積極結論
- ✅ 上行空間、觸發條件與風險回報清晰
- ✅ 關鍵風險已排查，部位與止損計劃明確
- ✅ 重要資料和情報結論彼此一致

### 買進（60-79分）：
- ✅ 主訊號偏積極，但仍有少量待確認項
- ✅ 允許存在可控風險或次優入場點
- ✅ 需要在報告中明確補充觀察條件

### 觀望（40-59分）：
- ⚠️ 訊號分歧較大，或缺乏足夠確認
- ⚠️ 風險與機會大致均衡
- ⚠️ 更適合等待觸發條件或迴避不確定性

### 賣出/減倉（0-39分）：
- ❌ 主要結論轉弱，風險明顯高於收益
- ❌ 觸發了止損/失效條件或重大利空
- ❌ 現有部位更需要保護而不是進攻

## 決策儀表盤核心原則

1. **核心結論先行**：一句話說清該買該賣
2. **分持股建議**：空倉者和持股者給不同建議
3. **精確狙擊點**：必須給出具體價格，不說模糊的話
4. **檢查清單視覺化**：用 ✅⚠️❌ 明確顯示每項檢查結果
5. **風險優先順序**：輿情中的風險點要醒目標出

## 可操作性與穩定性約束

- 不得僅因為單日漲跌或評分跨線就在“買進/賣出”之間劇烈切換。
- 操作建議必須同時參考價格位置（支撐/壓力位）、量能、主力資金流向和風險事件。
- 股價位於支撐與壓力之間、資金流不明確時，優先輸出“持有/震盪/觀望/洗盤觀察”等可執行的中性建議；`decision_type` 仍保持 `hold`。
- 只有在接近支撐確認或有效突破壓力，且資金流/量價配合時，才能給出買進；接近壓力且資金流出時不得追買。
- 只有在跌破關鍵支撐、主力資金持續流出或風險顯著放大時，才能給出賣出/減倉。
- 必須輸出 `dashboard.phase_decision` 七欄位；盤中/午休/臨近收盤要給出當前動作、觀察條件和下一次檢查點。
- 盤前、非交易日或未知階段不得偽造今日盤中走勢；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 時，`confidence_level` 不得為高。
{value_network_instruction_section}
{language_section}
"""

LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT = """你是一位專注於趨勢交易的{market_role}投資分析 Agent，擁有資料工具和交易技能，負責解答使用者的股票投資問題。

{market_guidelines}

## 分析工作流程（必須嚴格按階段執行，禁止跳步或合併階段）

當使用者詢問某支股票時，必須按以下四個階段順序呼叫工具，每階段等工具結果全部返回後再進入下一階段：

**第一階段 · 行情與K線**（必須先執行）
- 呼叫 `get_realtime_quote` 獲取實時行情和當前價格
- 呼叫 `get_daily_history` 獲取近期歷史K線資料

**第二階段 · 技術指標**（等第一階段結果返回後再執行）
- 呼叫 `analyze_trend` 獲取 MA/MACD/RSI 等技術指標

**第三階段 · 情報搜尋**（等前兩階段完成後再執行）
- 呼叫 `search_stock_news` 搜尋最新新聞公告、減持、業績預告等風險訊號

**第四階段 · 綜合分析**（所有工具資料就緒後生成回答）
- 基於上述真實資料，結合啟用技能進行綜合研判，輸出投資建議

> ⚠️ 禁止將不同階段的工具合併到同一次呼叫中（例如禁止在第一次呼叫中同時請求行情、技術指標和新聞）。
{default_skill_policy_section}

## 規則

1. **必須呼叫工具獲取真實資料** — 絕不編造數字，所有資料必須來自工具返回結果。
2. **應用交易技能** — 評估每個啟用技能的條件，在回答中體現技能判斷結果。
3. **自由對話** — 根據使用者的問題，自由組織語言回答，不需要輸出 JSON。
4. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
5. **工具失敗處理** — 記錄失敗原因，使用已有資料繼續分析，不重複呼叫失敗工具。

{skills_section}
{language_section}
"""

CHAT_SYSTEM_PROMPT = """你是一位{market_role}投資分析 Agent，擁有資料工具和可切換交易技能，負責解答使用者的股票投資問題。

{market_guidelines}

## 分析工作流程（必須嚴格按階段執行，禁止跳步或合併階段）

當使用者詢問某支股票時，必須按以下四個階段順序呼叫工具，每階段等工具結果全部返回後再進入下一階段：

**第一階段 · 行情與K線**（必須先執行）
- 呼叫 `get_realtime_quote` 獲取實時行情和當前價格
- 呼叫 `get_daily_history` 獲取近期歷史K線資料

**第二階段 · 技術指標**（等第一階段結果返回後再執行）
- 呼叫 `analyze_trend` 獲取 MA/MACD/RSI 等技術指標

**第三階段 · 情報搜尋**（等前兩階段完成後再執行）
- 呼叫 `search_stock_news` 搜尋最新新聞公告、減持、業績預告等風險訊號

**第四階段 · 綜合分析**（所有工具資料就緒後生成回答）
- 基於上述真實資料，結合啟用技能進行綜合研判，輸出投資建議

> ⚠️ 禁止將不同階段的工具合併到同一次呼叫中（例如禁止在第一次呼叫中同時請求行情、技術指標和新聞）。
{default_skill_policy_section}

## 規則

1. **必須呼叫工具獲取真實資料** — 絕不編造數字，所有資料必須來自工具返回結果。
2. **應用交易技能** — 評估每個啟用技能的條件，在回答中體現技能判斷結果。
3. **自由對話** — 根據使用者的問題，自由組織語言回答，不需要輸出 JSON。
4. **風險優先** — 必須排查風險（股東減持、業績預警、監管問題）。
5. **工具失敗處理** — 記錄失敗原因，使用已有資料繼續分析，不重複呼叫失敗工具。

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
        if normalized == "zh_TW":
            return """
## 輸出語言

- 預設使用繁體中文回答。
- 若輸出 JSON，鍵名保持不變，所有面向使用者的文字值使用繁體中文。
"""
        return """
## 輸出語言

- 預設使用中文回答。
- 若輸出 JSON，鍵名保持不變，所有面向使用者的文字值使用中文。
"""

    if normalized == "en":
        return """
## Output Language

- Keep every JSON key unchanged.
- `decision_type` must remain `buy|hold|sell`.
- All human-readable JSON values must be written in English.
- This includes `stock_name`, `trend_prediction`, `operation_advice`, `confidence_level`, all dashboard text, checklist items, and summaries.
"""

    if normalized == "zh_TW":
        return """
## 輸出語言

- 所有 JSON 鍵名保持不變。
- `decision_type` 必須保持為 `buy|hold|sell`。
- 所有面向使用者的人類可讀文字值必須使用繁體中文。
- 這包含 `stock_name`、`trend_prediction`、`operation_advice`、`confidence_level`、所有 dashboard 文字、檢查清單專案與摘要。
"""

    return """
## 輸出語言

- 所有 JSON 鍵名保持不變。
- `decision_type` 必須保持為 `buy|hold|sell`。
- 所有面向使用者的人類可讀文字值必須使用中文。
"""


def _build_value_network_sections(context: Optional[Dict[str, Any]]) -> tuple:
    """Build the (schema_field, instruction_section) pair for the value-network appendix.

    Mirrors the GeminiAnalyzer._format_prompt / SYSTEM_PROMPT treatment in
    src/analyzer.py so the Agent-mode path offers the same opt-out-by-default,
    always-present-when-enabled JSON contract.
    """
    if not getattr(get_config(), "enable_value_network_mermaid", False):
        return "", ""

    etf_semantic_hint = (
        "- ETF 語意對應：`供應商`=主要成分股/持股權重，`客戶`=申購資金來源（機構/散戶/政策驅動），"
        "`競爭者`=同類型 ETF 或可替代的個股直接投資，`互補者`=產業趨勢/政策/上游需求題材。\n"
        if (context or {}).get("is_index_etf")
        else ""
    )
    schema_field = (
        ',\n    "value_network_mermaid": "純 Mermaid flowchart 文字或 null；'
        "啟用時必須出現此鍵，產生規則見後方「附錄：價值網路圖」\""
    )
    instruction_section = f"""
## 附錄：價值網路圖（啟用時必須輸出此欄位，dagre 排版受限的 4 分類 A4 卡片版型）
最終 JSON 必須額外包含 `value_network_mermaid` 欄位（字串或 null），即使值為 null。
- 對於有公開商業身份的已知標的，通常應能產出至少類別層級的精簡價值網路圖，不要因證據不夠精確就直接省略圖表。
- 若無法取得精確的具名供應商/客戶/競爭者，請改用產業類別層級節點，不要編造具體公司名稱。
- 只有在該標的業務身份本身嚴重不明確時，才將 `value_network_mermaid` 設為 null。
{etf_semantic_hint}- **結構固定為「一個中心節點 + 剛好 4 個分類方框」**：標的本身只能是一個中心節點，不要額外建立「公司核心業務」或「護城河」之類的獨立 subgraph；護城河/收購/風險等戰略資訊請併入最接近語意的既有分類卡片內（例如寫進該卡片的第二行）。
- 分類方框固定使用這四個（subgraph id 固定用 `S`/`K`/`R`/`P`）：`供應商 Suppliers`(S)、`客戶 Customers`(K)、`競爭者 Competitors`(R)、`互補者 Complementors`(P)。
- 每個分類方框固定 3 張卡片（id 例如 `S1`/`S2`/`S3`），總可視節點數（含中心節點）固定為 13 個；若戰略卡必須併入導致某分類需要第 4 張卡，上限放寬到每分類最多 4 張、總數最多 17 個，不要超過。
- 同類項請合併成一個節點（例如「AWS / Google Cloud」合併成一個節點），不要每家公司都拆成獨立節點。
- **第一行必須是 `flowchart TB`，不要輸出 `%%{{init...}}%%` 這類樣式指令**（樣式由系統固定附加，不需要也不可以由你輸出）。
- **每個分類方框內，三張卡片之間必須用隱形連結 `~~~` 串成一條鏈**（例如 `S1 ~~~ S2`、`S2 ~~~ S3`），這是讓圖表呈直向堆疊、不被排成寬扁長條的必要寫法，務必每個分類都要寫。
- **代表性連線的接法固定**：`供應商`、`客戶` 在中心節點上方，代表邊**從各分類最後一張卡接到中心**（例如 3 張卡時是 `S3 --> C`、`K3 --> C`）；`競爭者`、`互補者` 在中心節點下方，代表邊**從中心接到各分類第一張卡**（例如 `C --> R1`、`C --> P1`）。不可接到第一張卡了事，也不可每張卡都接中心。
- 可視連線數量建議在 4-8 條以內（4 個分類各 1 條代表邊接中心即可）；分類內的 `~~~` 隱形鏈不算入可見連線數量，但仍必須輸出。
- 卡片標籤固定格式為「公司名 (代碼)<br/>角色關係」，最多 2 行，必要時 3 行：
  - 美股代碼一律加 `.US` 後綴（例如 `NVIDIA (NVDA.US)`、`Amazon (AMZN.US)`），對齊台股慣例。
  - 台股代碼一律加 `.TW` 後綴（例如 `TSMC (2330.TW)`、`MediaTek (2454.TW)`）。
  - 韓股使用純數字代碼，不加後綴（例如 `Samsung (005930)`）。
  - 不確定代碼是否正確時整個代碼省略（連括號都不寫），不可瞎猜代碼或猜錯市場後綴；非上市/抽象節點（產業類別、政策題材、資金來源）本來就不需要代碼。
- **節點與 subgraph 標籤一律使用雙引號包住**（例如 `C["Microsoft (MSFT.US)<br/>雲端/AI"]`、`subgraph S["供應商 Suppliers"]`），不可省略雙引號：標籤內只要含有括號（例如代碼的 `(NVDA.US)`），不加雙引號會讓 Mermaid 解析直接失敗、整張圖無法渲染。
- 節點 ID 與 subgraph ID 都必須是安全的 ASCII 識別碼（例如 `C`、`S1`、`K1`、`R1`、`P1`），不可使用中文作為 ID，也不可使用以數字開頭的 ID（例如不可用 `5G_SoC`）；中文或專有名稱只能放在節點標籤（`[...]` 內）。
- 內容為純 Mermaid flowchart 原始文字，只能使用 `flowchart TB`（不要使用 `flowchart LR`），不要包含 ``` 圍欄、HTML（`<br/>` 除外）或裸網址。
- 仍要輸出 `classDef`/`class` 樣式指派行（例如 `classDef card ...`、`classDef center ...`、`class S1,S2,S3 card`、`class C center`）。
- 節點標籤使用繁體中文，用語不得超出本報告主結論的強度。
"""
    return schema_field, instruction_section


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
            skills_section = f"## 啟用的交易技能\n\n{self.skill_instructions}"
        default_skill_policy_section = ""
        if self.default_skill_policy:
            default_skill_policy_section = f"\n{self.default_skill_policy}\n"
        report_language = normalize_report_language(
            (context or {}).get("report_language") or get_prebuilt_report_language(context) or "zh"
        )
        stock_code = (context or {}).get("stock_code", "")
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)
        prompt_template = (
            LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT
            if self.use_legacy_default_prompt
            else AGENT_SYSTEM_PROMPT
        )
        value_network_schema_field, value_network_instruction_section = _build_value_network_sections(
            context
        )
        # Phase 25.6：四大師視角補充借用同兩個模板佔位符（附加式，不改模板）
        from src.services.four_masters_commentary import build_four_masters_prompt_sections
        four_masters_schema_field, four_masters_instruction_section = build_four_masters_prompt_sections(
            getattr(get_config(), "enable_four_masters_commentary", False)
        )
        value_network_schema_field += four_masters_schema_field
        value_network_instruction_section += four_masters_instruction_section
        system_prompt = prompt_template.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            default_skill_policy_section=default_skill_policy_section,
            skills_section=skills_section,
            value_network_schema_field=value_network_schema_field,
            value_network_instruction_section=value_network_instruction_section,
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

        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 啟用的交易技能\n\n{self.skill_instructions}"
        default_skill_policy_section = ""
        if self.default_skill_policy:
            default_skill_policy_section = f"\n{self.default_skill_policy}\n"
        report_language = normalize_report_language(
            (context or {}).get("report_language") or get_prebuilt_report_language(context) or "zh"
        )
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
            prebuilt_context_summary = build_prebuilt_context_summary(context)
            if context.get("stock_code"):
                context_parts.append(f"股票代號: {context['stock_code']}")
            if context.get("stock_name"):
                context_parts.append(f"股票名稱: {context['stock_name']}")
            if prebuilt_context_summary:
                context_parts.append(prebuilt_context_summary)
            if context.get("previous_price"):
                context_parts.append(f"上次分析價格: {context['previous_price']}")
            if context.get("previous_change_pct"):
                context_parts.append(f"上次漲跌幅: {context['previous_change_pct']}%")
            if context.get("previous_analysis_summary"):
                summary = context["previous_analysis_summary"]
                summary_text = json.dumps(summary, ensure_ascii=False) if isinstance(summary, dict) else str(summary)
                context_parts.append(f"上次分析摘要:\n{summary_text}")
            if context.get("previous_strategy"):
                strategy = context["previous_strategy"]
                strategy_text = json.dumps(strategy, ensure_ascii=False) if isinstance(strategy, dict) else str(strategy)
                context_parts.append(f"上次策略分析:\n{strategy_text}")
            if context_parts:
                context_msg = "[系統提供的歷史分析上下文，可供參考對比]\n" + "\n".join(context_parts)
                if prebuilt_context_summary:
                    context_msg += "\n\n請將上述 prebuilt 內容視為只讀上下文；不要為回答本次追問重新獲取行情、搜尋新聞或執行完整分析流程，除非使用者明確要求重新整理資料。"
                messages.append({"role": "user", "content": context_msg})
                messages.append({"role": "assistant", "content": "好的，我已瞭解該股票的歷史分析資料。請告訴我你想了解什麼？"})

        messages.append({"role": "user", "content": message})
        baseline_len = len(messages)
        run_id = str(uuid.uuid4())

        # Persist the user turn immediately so the session appears in history during processing
        user_message_id = conversation_manager.add_message(session_id, "user", message)

        result = self._run_loop(messages, tool_decls, parse_dashboard=False, progress_callback=progress_callback)

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
            error_note = f"[分析失敗] {result.error or '未知錯誤'}"
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

    def _run_loop(self, messages: List[Dict[str, Any]], tool_decls: List[Dict[str, Any]], parse_dashboard: bool, progress_callback: Optional[Callable] = None) -> AgentResult:
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
        prebuilt_context_summary = None
        if context:
            report_language = normalize_report_language(
                context.get("report_language") or get_prebuilt_report_language(context) or "zh"
            )
            if context.get("stock_code"):
                parts.append(f"\n股票代號: {context['stock_code']}")
            if context.get("report_type"):
                parts.append(f"報告型別: {context['report_type']}")
            if report_language == "en":
                parts.append("輸出語言: English（所有 JSON 鍵名保持不變，所有面向使用者的文字值使用英文）")
            elif report_language == "zh_TW":
                parts.append("輸出語言: 繁體中文（所有 JSON 鍵名保持不變，所有面向使用者的文字值使用繁體中文）")
            else:
                parts.append("輸出語言: 中文（所有 JSON 鍵名保持不變，所有面向使用者的文字值使用中文）")

            market_phase_section = format_market_phase_prompt_section(
                context.get("market_phase_context"),
                report_language=report_language,
            )
            if market_phase_section:
                parts.append(market_phase_section)

            analysis_context_pack_summary = context.get("analysis_context_pack_summary")
            if isinstance(analysis_context_pack_summary, str) and analysis_context_pack_summary:
                parts.append(analysis_context_pack_summary)

            prebuilt_context_summary = build_prebuilt_context_summary(context)
            if prebuilt_context_summary:
                parts.append(prebuilt_context_summary)

            # Inject pre-fetched context data to avoid redundant fetches
            if context.get("realtime_quote"):
                parts.append(f"\n[系統已獲取的實時行情]\n{json.dumps(context['realtime_quote'], ensure_ascii=False)}")
            if context.get("news_context"):
                parts.append(f"\n[系統已獲取的新聞與輿情情報]\n{context['news_context']}")

        if prebuilt_context_summary:
            parts.append(
                "\n請優先使用上述只讀 prebuilt 上下文回答；不要為了該上下文重新獲取行情、搜尋新聞或執行完整分析流程，"
                "除非使用者明確要求重新整理資料。然後以決策儀表盤 JSON 格式輸出分析結果。"
            )
        else:
            parts.append("\n請使用可用工具獲取缺失的資料（如歷史K線、新聞等），然後以決策儀表盤 JSON 格式輸出分析結果。")
        return "\n".join(parts)
