# -*- coding: utf-8 -*-
"""
ToolResultKeyStore — 工具结果关键数据持久化与重注入。

职责：
1. 从 Agent 工具调用结果中提取关键数据（股价、技术指标、筹码、新闻）
2. 按 session_id 存储提取的数据
3. 生成结构化上下文块，可在上下文压缩后重新注入消息列表

设计原则：
- 无侵入：不改变现有压缩算法，只增加提取和注入点
- 轻量级：使用模块级内存存储，与会话管理器生命周期一致
- 向后兼容：不影响未使用该功能的消费方
"""

from __future__ import annotations

import json
import logging
from threading import RLock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 工具结果摘要提取器
# ============================================================

# 工具名称 → 需要提取的关键字段映射（JSON path）
_TOOL_KEY_FIELDS: Dict[str, List[str]] = {
    "get_realtime_quote": ["latest_price", "change_pct", "volume", "turnover_rate", "amplitude"],
    "analyze_trend": ["rsi", "ma5", "ma10", "ma20", "ma_alignment", "trend_score", "volume_ratio"],
    "get_chip_distribution": ["concentration", "cost_distribution", "avg_cost"],
    "search_stock_news": [],  # 新闻提取单独处理
    "search_comprehensive_intel": [],
}

_NEWS_TOOLS = frozenset({"search_stock_news", "search_comprehensive_intel"})


def _safe_parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """安全解析 JSON 字符串，失败返回 None。"""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_fields(data: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
    """从嵌套 dict 中提取指定字段。"""
    extracted: Dict[str, Any] = {}
    for field in fields:
        value = data.get(field)
        if value is not None and value != "" and value != "N/A":
            extracted[field] = value
    return extracted


def _extract_news_title(data: Dict[str, Any]) -> str:
    """从新闻工具结果中提取最新新闻标题。"""
    key_news = data.get("key_news") or data.get("news") or []
    if isinstance(key_news, list):
        for item in key_news[:3]:
            if isinstance(item, dict):
                title = str(item.get("title", "") or "").strip()
                if title:
                    return title
    latest = data.get("latest_news", "")
    if isinstance(latest, str) and latest.strip():
        return latest.strip()
    return ""


def extract_tool_result_summary(tool_name: str, result_str: str) -> Dict[str, Any]:
    """从工具结果字符串中提取关键数据摘要。"""
    if not result_str:
        return {}

    data = _safe_parse_json(result_str)
    if not data:
        return {"_note": "unparseable"}

    summary: Dict[str, Any] = {}

    # 提取错误信息
    if isinstance(data, dict) and data.get("error"):
        summary["_error"] = str(data["error"])[:200]
        return summary

    # 提取关键字段
    if tool_name in _TOOL_KEY_FIELDS and isinstance(data, dict):
        fields = _TOOL_KEY_FIELDS[tool_name]
        extracted = _extract_fields(data, fields)
        if extracted:
            summary.update(extracted)

    # 提取新闻标题
    if tool_name in _NEWS_TOOLS and isinstance(data, dict):
        news_title = _extract_news_title(data)
        if news_title:
            summary["latest_news"] = news_title

    return summary


# ============================================================
# ToolResultKeyStore
# ============================================================

class ToolResultKeyStore:
    """线程安全的工具结果关键数据存储器。

    用法::

        # 存储
        summary = extract_tool_result_summary("get_realtime_quote", result_str)
        ToolResultKeyStore.store("session_xxx", summary)

        # 读取并生成上下文块
        block = ToolResultKeyStore.build_context_block("session_xxx")
    """

    _store: Dict[str, List[Dict[str, Any]]] = {}
    _lock = RLock()

    @classmethod
    def store(cls, session_id: str, tool_name: str, summary: Dict[str, Any]) -> None:
        """存储一次工具调用的关键数据摘要。"""
        if not summary:
            return
        with cls._lock:
            if session_id not in cls._store:
                cls._store[session_id] = []
            # 避免重复存储相同工具的数据（取最新一次）
            existing = [e for e in cls._store[session_id] if e.get("_tool") == tool_name]
            if existing:
                existing[0].update(summary)
                existing[0]["_count"] = existing[0].get("_count", 1) + 1
            else:
                entry: Dict[str, Any] = {"_tool": tool_name, "_count": 1}
                entry.update(summary)
                cls._store[session_id].append(entry)

    @classmethod
    def build_context_block(cls, session_id: str) -> str:
        """为指定会话构建结构化上下文块。

        返回一个 markdown 文本块，可注入到上下文压缩后的消息列表中。
        若无存储数据，返回空字符串。
        """
        with cls._lock:
            entries = cls._store.get(session_id, [])
            if not entries:
                return ""

        parts: List[str] = ["[系统保留的之前回合工具调用关键数据]"]

        for entry in entries:
            tool = entry.get("_tool", "unknown")

            if tool == "get_realtime_quote":
                price = entry.get("latest_price", "")
                change = entry.get("change_pct", "")
                vol = entry.get("volume", "")
                line = f"- 实时行情: 价格={price}"
                if change:
                    line += f" | 涨跌幅={change}%"
                if vol:
                    line += f" | 成交量={vol}"
                parts.append(line)

            elif tool == "analyze_trend":
                trend = entry.get("trend_score", "")
                alignment = entry.get("ma_alignment", "")
                rsi = entry.get("rsi", "")
                line = f"- 技术分析: "
                if trend:
                    line += f"趋势评分={trend}"
                if alignment:
                    line += f" | 均线排列={alignment}"
                if rsi:
                    line += f" | RSI={rsi}"
                parts.append(line)

            elif tool == "get_chip_distribution":
                conc = entry.get("concentration", "")
                avg_cost = entry.get("avg_cost", "")
                line = "- 筹码分析:"
                if conc:
                    line += f" 集中度={conc}"
                if avg_cost:
                    line += f" | 平均成本={avg_cost}"
                parts.append(line)

            elif tool in _NEWS_TOOLS:
                news = entry.get("latest_news", "")
                if news:
                    parts.append(f"- 最近舆情: {news}")

            else:
                # 通用兜底
                non_meta = {k: v for k, v in entry.items() if not k.startswith("_")}
                if non_meta:
                    parts.append(f"- {tool}: {json.dumps(non_meta, ensure_ascii=False)}")

        if len(parts) == 1:
            return ""  # 只有标题没有内容

        return "\n".join(parts)

    @classmethod
    def clear(cls, session_id: str) -> None:
        """清理指定会话的数据。"""
        with cls._lock:
            cls._store.pop(session_id, None)

    @classmethod
    def clear_all(cls) -> None:
        """清理所有会话的数据。"""
        with cls._lock:
            cls._store.clear()

    @classmethod
    def has_data(cls, session_id: str) -> bool:
        """检查会话是否有存储的数据。"""
        with cls._lock:
            return bool(cls._store.get(session_id))
