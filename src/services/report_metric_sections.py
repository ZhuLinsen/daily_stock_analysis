from __future__ import annotations

from typing import Any, Dict, Optional


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "N/A"
    return f"{value}{suffix}"


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _relative_text(relative: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        item = relative.get(key)
        if isinstance(item, dict):
            text = item.get("text")
            if text and text != "数据不足":
                ratio = item.get("ratio")
                return f"{text}（{ratio}x）" if ratio else str(text)
    return "数据不足"


def render_daily_turnover_section(fundamental_context: Optional[Dict[str, Any]]) -> str:
    block = _dict(_dict(fundamental_context).get("daily_turnover"))
    if block.get("status") not in {"ok", "partial"}:
        return ""

    return f"""
### 📊 每日换手率

| 指标 | 数值 |
|------|------|
| 最新交易日 | {_fmt(block.get('latest_trade_date'))} |
| 最新换手率 | {_fmt(block.get('latest_turnover_rate'), '%')} |
| 5日均值 | {_fmt(block.get('avg_5d_turnover_rate'), '%')} |
| 20日均值 | {_fmt(block.get('avg_20d_turnover_rate'), '%')} |
| 相对20日 | {_fmt(block.get('latest_vs_20d_ratio'))} |
| 状态 | {_fmt(block.get('activity_status'))} |
| 计算口径 | {_fmt(block.get('calculation_method'))} |
""".strip()


def render_sector_valuation_section(fundamental_context: Optional[Dict[str, Any]]) -> str:
    block = _dict(_dict(fundamental_context).get("sector_valuation_comparison"))
    if block.get("status") != "ok":
        return ""

    current = _dict(block.get("current"))
    medians = _dict(block.get("peer_medians"))
    relative = _dict(block.get("relative"))

    return f"""
### 🏷️ 同板块估值比较

所属板块/行业：{_fmt(block.get('sector'))} / {_fmt(block.get('industry'))}；样本数：{_fmt(block.get('peer_count'))}

| 指标 | 当前股票 | 板块/同行中位数 | 相对位置 |
|------|----------|----------------|----------|
| PE(TTM) | {_fmt(current.get('trailing_pe') or current.get('pe_ratio'))} | {_fmt(medians.get('trailing_pe') or medians.get('pe_ratio'))} | {_relative_text(relative, 'trailing_pe', 'pe_ratio')} |
| Forward PE | {_fmt(current.get('forward_pe'))} | {_fmt(medians.get('forward_pe'))} | {_relative_text(relative, 'forward_pe')} |
| PB | {_fmt(current.get('pb_ratio'))} | {_fmt(medians.get('pb_ratio'))} | {_relative_text(relative, 'pb_ratio')} |
| PS | {_fmt(current.get('ps_ratio'))} | {_fmt(medians.get('ps_ratio'))} | {_relative_text(relative, 'ps_ratio')} |
""".strip()


def append_metric_sections_to_report(report: Any, fundamental_context: Optional[Dict[str, Any]]) -> Any:
    if not isinstance(report, str) or not report.strip():
        return report

    sections = [
        render_daily_turnover_section(fundamental_context),
        render_sector_valuation_section(fundamental_context),
    ]
    sections = [section for section in sections if section]

    if not sections:
        return report

    existing = report
    sections = [section for section in sections if section.splitlines()[0].strip() not in existing]
    if not sections:
        return report

    return existing.rstrip() + "\n\n" + "\n\n".join(sections) + "\n"
