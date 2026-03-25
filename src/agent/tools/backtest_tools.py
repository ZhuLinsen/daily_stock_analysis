# -*- coding: utf-8 -*-
"""
Backtest tools — read-only tools exposing backtest summaries to the agent.

Tools:
- get_skill_backtest_summary: skill-scoped stats when available, otherwise an explicit unsupported/info response
- get_strategy_backtest_summary: legacy alias of the overall summary tool
- get_stock_backtest_summary: backtest results for a specific stock
"""

import logging

from src.agent.tools.registry import ToolParameter, ToolDefinition

logger = logging.getLogger(__name__)

_backtest_service = None


def _get_backtest_service():
    """Lazy import + singleton to avoid circular deps and repeated instantiation."""
    global _backtest_service
    if _backtest_service is None:
        from src.services.backtest_service import BacktestService
        _backtest_service = BacktestService()
    return _backtest_service


# ============================================================
# get_skill_backtest_summary / get_strategy_backtest_summary
# ============================================================

def _serialize_overall_backtest_summary(summary: dict, eval_window_days: int) -> dict:
    """Return the public overall-summary payload exposed to the agent."""
    return {
        "scope": summary.get("scope", "overall"),
        "eval_window_days": summary.get("eval_window_days", eval_window_days),
        "total_evaluations": summary.get("total_evaluations", 0),
        "completed_count": summary.get("completed_count", 0),
        "win_rate_pct": summary.get("win_rate_pct"),
        "direction_accuracy_pct": summary.get("direction_accuracy_pct"),
        "avg_stock_return_pct": summary.get("avg_stock_return_pct"),
        "avg_simulated_return_pct": summary.get("avg_simulated_return_pct"),
        "stop_loss_trigger_rate": summary.get("stop_loss_trigger_rate"),
        "take_profit_trigger_rate": summary.get("take_profit_trigger_rate"),
        "advice_breakdown": summary.get("advice_breakdown"),
        "computed_at": summary.get("computed_at"),
    }


def _handle_get_overall_backtest_summary(eval_window_days: int = 30) -> dict:
    """Get the overall backtest summary for the full analysis corpus."""
    try:
        svc = _get_backtest_service()
        summary = svc.get_summary(scope="overall", code=None, eval_window_days=eval_window_days)
        if summary is None:
            return {"info": "No backtest summary available. Backtest may not have been run yet."}
        return _serialize_overall_backtest_summary(summary, eval_window_days)
    except Exception:
        logger.warning("[backtest_tools] get_overall_backtest_summary error", exc_info=True)
        return {"error": "Failed to retrieve backtest summary."}


def _handle_get_skill_backtest_summary(skill_id: str = "", eval_window_days: int = 30) -> dict:
    """Get a skill-scoped backtest summary when real per-skill stats exist."""
    if not skill_id:
        return {
            "supported": False,
            "error": "skill_id is required. Use get_strategy_backtest_summary for overall metrics.",
        }

    try:
        svc = _get_backtest_service()
        summary = svc.get_skill_summary(skill_id, eval_window_days=eval_window_days)
        if summary is None:
            return {
                "skill_id": skill_id,
                "supported": False,
                "info": "Skill-scoped backtest summaries are not available yet.",
            }
        return {
            "scope": "skill",
            "skill_id": skill_id,
            "supported": True,
            "eval_window_days": summary.get("eval_window_days", eval_window_days),
            "total_evaluations": summary.get("total_evaluations", 0),
            "completed_count": summary.get("completed_count", 0),
            "win_rate": summary.get("win_rate"),
            "direction_accuracy": summary.get("direction_accuracy"),
            "avg_return": summary.get("avg_return"),
            "win_rate_pct": summary.get("win_rate_pct"),
            "direction_accuracy_pct": summary.get("direction_accuracy_pct"),
            "avg_stock_return_pct": summary.get("avg_stock_return_pct"),
            "avg_simulated_return_pct": summary.get("avg_simulated_return_pct"),
            "computed_at": summary.get("computed_at"),
        }
    except Exception:
        logger.warning("[backtest_tools] get_skill_backtest_summary error", exc_info=True)
        return {"error": "Failed to retrieve backtest summary."}


get_skill_backtest_summary_tool = ToolDefinition(
    name="get_skill_backtest_summary",
    description=(
        "Inspect backtest data for a specific skill when skill-scoped stats exist. "
        "Provide skill_id for a targeted lookup; use get_strategy_backtest_summary for overall metrics. "
        "When skill-scoped rollups are unavailable, returns an informational response instead of fabricating metrics."
    ),
    parameters=[
        ToolParameter(
            name="skill_id",
            type="string",
            description="Skill identifier, e.g. 'bull_trend'.",
            required=True,
        ),
        ToolParameter(
            name="eval_window_days",
            type="integer",
            description="Evaluation window in days (default: 30). How many trading days after signal to evaluate.",
            required=False,
            default=30,
        ),
    ],
    handler=_handle_get_skill_backtest_summary,
    category="data",
)


get_strategy_backtest_summary_tool = ToolDefinition(
    name="get_strategy_backtest_summary",
    description=(
        "Legacy alias returning the overall backtest performance summary without triggering new backtests."
    ),
    parameters=[
        ToolParameter(
            name="eval_window_days",
            type="integer",
            description="Evaluation window in days (default: 30). How many trading days after signal to evaluate.",
            required=False,
            default=30,
        ),
    ],
    handler=_handle_get_overall_backtest_summary,
    category="data",
)


# ============================================================
# get_stock_backtest_summary
# ============================================================

def _handle_get_stock_backtest_summary(stock_code: str, eval_window_days: int = 30, limit: int = 10) -> dict:
    """Get backtest results for a specific stock.

    Returns the summary plus recent evaluation items.
    """
    try:
        svc = _get_backtest_service()
        result = {}

        # Per-stock summary
        summary = svc.get_summary(scope="stock", code=stock_code, eval_window_days=eval_window_days)
        if summary:
            result["summary"] = {
                "code": summary.get("code", stock_code),
                "total_evaluations": summary.get("total_evaluations", 0),
                "completed_count": summary.get("completed_count", 0),
                "win_rate_pct": summary.get("win_rate_pct"),
                "direction_accuracy_pct": summary.get("direction_accuracy_pct"),
                "avg_stock_return_pct": summary.get("avg_stock_return_pct"),
                "avg_simulated_return_pct": summary.get("avg_simulated_return_pct"),
                "computed_at": summary.get("computed_at"),
            }
        else:
            result["summary"] = None

        # Recent evaluations
        evals = svc.get_recent_evaluations(code=stock_code, eval_window_days=eval_window_days, limit=limit)
        items = evals.get("items", [])
        # Slim down items to essential fields
        result["recent_evaluations"] = [
            {
                "analysis_date": item.get("analysis_date"),
                "operation_advice": item.get("operation_advice"),
                "stock_return_pct": item.get("stock_return_pct"),
                "direction_correct": item.get("direction_correct"),
                "outcome": item.get("outcome"),
                "simulated_return_pct": item.get("simulated_return_pct"),
                "hit_stop_loss": item.get("hit_stop_loss"),
                "hit_take_profit": item.get("hit_take_profit"),
            }
            for item in items
        ]
        result["total"] = evals.get("total", 0)

        if result["summary"] is None and not result["recent_evaluations"]:
            return {"info": f"No backtest data available for {stock_code}. Backtest may not have been run yet."}

        return result
    except Exception:
        logger.warning("[backtest_tools] get_stock_backtest_summary error", exc_info=True)
        return {"error": "Failed to retrieve backtest data."}


get_stock_backtest_summary_tool = ToolDefinition(
    name="get_stock_backtest_summary",
    description=(
        "Get backtest performance data for a specific stock: per-stock summary (win rate, "
        "accuracy, avg return) plus recent evaluation records. Read-only, does not trigger new backtests."
    ),
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519' (A-share), 'AAPL' (US), 'hk00700' (HK)",
        ),
        ToolParameter(
            name="eval_window_days",
            type="integer",
            description="Evaluation window in days (default: 30)",
            required=False,
            default=30,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Max number of recent evaluation records to return (default: 10)",
            required=False,
            default=10,
        ),
    ],
    handler=_handle_get_stock_backtest_summary,
    category="data",
)


# ============================================================
# Exported tool list
# ============================================================

ALL_BACKTEST_TOOLS = [
    get_skill_backtest_summary_tool,
    get_strategy_backtest_summary_tool,
    get_stock_backtest_summary_tool,
]
