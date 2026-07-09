# -*- coding: utf-8 -*-
"""四大師視角補充（Phase 25.6）：驗證與 Markdown 渲染。

定位：個股完整報告的**點評式補充段**，以四個具名投資框架（巴菲特/蒙格/段永平/李錄）
對原始報告做多視角評論。它只能支持、質疑或補充原始報告，
不輸出任何買賣/加減碼行動，也不覆蓋 operation_advice / trend_prediction /
sentiment_score / 買賣區間等原始欄位。

安全邊界（在驗證器強制）：
- 白名單欄位：LLM 夾帶的任何行動類欄位（action/operation_advice/buy...）一律剝除。
- supports_original_view / confidence_adjustment 枚舉強制收斂。
- synthesis.does_not_override_original_action 恆為 True。
- 字串去除 HTML 標籤與角括號、裁剪長度，渲染不引入不安全 HTML。
- 缺失或畸形時整段返回 None，報告渲染安全降級（不出現該段）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_MAX_TEXT_LEN = 600
_MAX_RED_LINES = 5

_SUPPORT_ENUM = ("support", "challenge", "mixed")
_CONFIDENCE_ENUM = ("raise", "lower", "unchanged")

# 每個視角允許的欄位白名單（title 由渲染端固定，不信任 LLM 提供的 title）
_MASTER_FIELDS: Dict[str, tuple] = {
    "buffett": (
        "summary", "supports_original_view", "key_question",
        "blind_spot_in_original_report", "margin_of_safety_comment",
        "what_would_change_this_view",
    ),
    "munger": (
        "summary", "supports_original_view", "inversion_question",
        "biggest_failure_mode", "psychological_bias_warning",
        "what_would_change_this_view",
    ),
    "duan_yongping": (
        "summary", "supports_original_view", "business_quality_comment",
        "product_or_customer_value_comment", "long_term_holding_condition",
        "what_would_change_this_view",
    ),
    "li_lu": (
        "summary", "supports_original_view", "certainty_comment",
        "downside_risk_comment", "red_lines", "what_would_change_this_view",
    ),
}

_SYNTHESIS_FIELDS = (
    "main_disagreement", "most_useful_supplement_to_original_report",
    "confidence_adjustment", "does_not_override_original_action",
)

_MASTER_TITLES = {
    "buffett": "巴菲特視角：價值與安全邊際",
    "munger": "蒙格視角：反向思考與誤判檢查",
    "duan_yongping": "段永平視角：生意模式與用戶價值",
    "li_lu": "李錄視角：長期確定性與風險紅線",
}

_MASTER_TITLES_EN = {
    "buffett": "Buffett Lens: Value and Margin of Safety",
    "munger": "Munger Lens: Inversion and Misjudgment Check",
    "duan_yongping": "Duan Yongping Lens: Business Model and Customer Value",
    "li_lu": "Li Lu Lens: Long-term Certainty and Risk Red Lines",
}

_FIELD_LABELS = {
    "supports_original_view": "與原始報告觀點",
    "key_question": "關鍵問題",
    "blind_spot_in_original_report": "原始報告可能的盲點",
    "margin_of_safety_comment": "安全邊際點評",
    "inversion_question": "反向問題",
    "biggest_failure_mode": "最大失效模式",
    "psychological_bias_warning": "心理偏誤警示",
    "business_quality_comment": "生意品質點評",
    "product_or_customer_value_comment": "產品/用戶價值點評",
    "long_term_holding_condition": "長期持有條件",
    "certainty_comment": "長期確定性點評",
    "downside_risk_comment": "下行風險點評",
    "red_lines": "風險紅線",
    "what_would_change_this_view": "何種情況會改變此看法",
}

_SUPPORT_LABELS = {"support": "支持", "challenge": "質疑", "mixed": "部分支持、部分質疑"}
_CONFIDENCE_LABELS = {"raise": "建議提高", "lower": "建議降低", "unchanged": "維持不變"}

DISCLAIMER_ZH = "本段為投資框架模擬點評，不代表任何人物本人觀點，且不覆蓋原始操作建議。"
DISCLAIMER_EN = (
    "This section is a simulated framework-based commentary. It does not represent "
    "any person's actual opinion and does not override the original recommendation."
)


def build_four_masters_prompt_sections(enabled: bool) -> tuple:
    """回傳 (schema_field, instruction_section)；未啟用時皆為空字串。

    analyzer 直呼叫路徑與 Agent 模式（src/agent/executor.py）共用，
    對齊 value_network_mermaid 的雙路徑注入方式。
    """
    if not enabled:
        return "", ""
    schema_field = (
        ',\n    "four_masters_commentary": "物件；啟用時必須出現此鍵，'
        '結構與規則見後方「附錄：四大師視角補充」"'
    )
    instruction_section = """
### 附錄：四大師視角補充（啟用時必須輸出此欄位）
請在最上層 JSON 額外輸出 `four_masters_commentary` **物件**欄位。此功能已啟用，該鍵必須出現在 JSON 中。
- 定位：以四個投資框架對上方主報告做**點評式補充**，可以支持（support）、質疑（challenge）或部分支持（mixed）主報告結論。
- **硬限制**：此欄位內不得出現任何買進/賣出/加倉/減倉/觀望等操作指令、目標價、買進區間或部位比例；操作建議一律以主報告原始欄位為準，本欄位僅為觀點評論。
- 這是投資框架的**模擬點評**，不代表任何人物本人觀點；不要以第一人稱自稱本人，不要杜撰引言。
- 各視角聚焦：buffett=價值/護城河/安全邊際/股價波動是否被誤當成價值受損；munger=反向思考/誤判心理/最強失效模式/主報告是否被近期價格行為驅動；duan_yongping=生意模式/產品與用戶價值/長期持有條件/生意品質是否真的改變；li_lu=長期確定性/下行保護/風險紅線/論點失效條件。
- 結構固定如下（不要增減鍵）：
```json
"four_masters_commentary": {
  "buffett": {"summary": "...", "supports_original_view": "support|challenge|mixed", "key_question": "...", "blind_spot_in_original_report": "...", "margin_of_safety_comment": "...", "what_would_change_this_view": "..."},
  "munger": {"summary": "...", "supports_original_view": "support|challenge|mixed", "inversion_question": "...", "biggest_failure_mode": "...", "psychological_bias_warning": "...", "what_would_change_this_view": "..."},
  "duan_yongping": {"summary": "...", "supports_original_view": "support|challenge|mixed", "business_quality_comment": "...", "product_or_customer_value_comment": "...", "long_term_holding_condition": "...", "what_would_change_this_view": "..."},
  "li_lu": {"summary": "...", "supports_original_view": "support|challenge|mixed", "certainty_comment": "...", "downside_risk_comment": "...", "red_lines": ["..."], "what_would_change_this_view": "..."},
  "synthesis": {"main_disagreement": "...", "most_useful_supplement_to_original_report": "...", "confidence_adjustment": "raise|lower|unchanged", "does_not_override_original_action": true}
}
```
- ETF/槓桿型 ETF 標的：各視角改以「工具屬性」評論（追蹤標的品質、費用/折溢價、槓桿工具的複利偏移與波動衰減、是否適合長期持有），不要杜撰不存在的個別公司經營細節。
"""
    return schema_field, instruction_section


def _sanitize_text(value: Any) -> Optional[str]:
    """字串化 + 去 HTML 標籤/角括號/控制字元 + 長度裁剪；空值返回 None。"""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value)
    text = re.sub(r"<[^>]*>", "", text)
    text = text.replace("<", "").replace(">", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:_MAX_TEXT_LEN]


def validate_four_masters_commentary(raw: Any) -> Optional[Dict[str, Any]]:
    """驗證/淨化 LLM 產出的 four_masters_commentary；不可修復時返回 None。"""
    if not isinstance(raw, dict):
        return None

    cleaned: Dict[str, Any] = {}
    has_content = False
    for master, fields in _MASTER_FIELDS.items():
        block = raw.get(master)
        if not isinstance(block, dict):
            continue
        out: Dict[str, Any] = {}
        for field in fields:
            value = block.get(field)
            if field == "supports_original_view":
                text = str(value).strip().lower() if isinstance(value, str) else ""
                out[field] = text if text in _SUPPORT_ENUM else "mixed"
            elif field == "red_lines":
                if isinstance(value, list):
                    lines = [t for t in (_sanitize_text(v) for v in value[:_MAX_RED_LINES]) if t]
                    if lines:
                        out[field] = lines
                elif isinstance(value, str):
                    text = _sanitize_text(value)
                    if text:
                        out[field] = [text]
            else:
                text = _sanitize_text(value)
                if text is not None:
                    out[field] = text
        if out.get("summary"):
            cleaned[master] = out
            has_content = True

    if not has_content:
        return None

    synthesis_raw = raw.get("synthesis")
    synthesis: Dict[str, Any] = {}
    if isinstance(synthesis_raw, dict):
        for field in _SYNTHESIS_FIELDS:
            if field == "confidence_adjustment":
                value = synthesis_raw.get(field)
                text = str(value).strip().lower() if isinstance(value, str) else ""
                synthesis[field] = text if text in _CONFIDENCE_ENUM else "unchanged"
            elif field == "does_not_override_original_action":
                continue  # 強制為 True，不信任 LLM 值
            else:
                text = _sanitize_text(synthesis_raw.get(field))
                if text is not None:
                    synthesis[field] = text
    synthesis["does_not_override_original_action"] = True
    cleaned["synthesis"] = synthesis
    return cleaned


def render_four_masters_markdown(raw: Any, report_language: str = "zh_TW") -> List[str]:
    """把（可能未驗證的）commentary 渲染成 Markdown 行；無效時返回空 list。"""
    commentary = validate_four_masters_commentary(raw)
    if not commentary:
        return []

    is_en = report_language == "en"
    titles = _MASTER_TITLES_EN if is_en else _MASTER_TITLES
    heading = "Four Masters Commentary" if is_en else "四大師視角補充"

    lines: List[str] = [f"## {heading}", ""]
    for master in ("buffett", "munger", "duan_yongping", "li_lu"):
        block = commentary.get(master)
        if not block:
            continue
        lines.extend([f"### {titles[master]}", ""])
        lines.extend([str(block["summary"]), ""])
        stance = _SUPPORT_LABELS.get(block.get("supports_original_view", "mixed"), "部分支持、部分質疑")
        stance_label = "Stance vs original report" if is_en else _FIELD_LABELS["supports_original_view"]
        lines.append(f"- **{stance_label}**：{block.get('supports_original_view') if is_en else stance}")
        for field in _MASTER_FIELDS[master]:
            if field in ("summary", "supports_original_view"):
                continue
            value = block.get(field)
            if value is None:
                continue
            label = _FIELD_LABELS.get(field, field)
            if field == "red_lines":
                lines.append(f"- **{label}**：")
                lines.extend([f"  - {item}" for item in value])
            else:
                lines.append(f"- **{label}**：{value}")
        lines.append("")

    synthesis = commentary.get("synthesis") or {}
    synth_parts: List[str] = []
    if synthesis.get("main_disagreement"):
        synth_parts.append(f"- **主要分歧**：{synthesis['main_disagreement']}")
    if synthesis.get("most_useful_supplement_to_original_report"):
        synth_parts.append(f"- **對原始報告最有用的補充**：{synthesis['most_useful_supplement_to_original_report']}")
    conf = synthesis.get("confidence_adjustment", "unchanged")
    synth_parts.append(
        f"- **對原結論信心的影響**：{conf if is_en else _CONFIDENCE_LABELS.get(conf, '維持不變')}（僅供參考，不改變原始操作建議）"
    )
    if synth_parts:
        lines.extend([("### Synthesis" if is_en else "### 綜合觀察"), "", *synth_parts, ""])

    lines.extend([f"> {DISCLAIMER_EN if is_en else DISCLAIMER_ZH}", ""])
    return lines
