# -*- coding: utf-8 -*-
"""Alert-on-change: only notify for stocks whose signal materially changed.

Enabled with ``ALERT_ON_CHANGE=true``. Each analysis is compared with the most
recent earlier analysis of the same stock stored in the local database
(``analysis_history``). On GitHub Actions this needs the database to persist
between runs (see the cache steps in ``00-daily-analysis.yml``).

Stocks are always kept when there is no earlier analysis to compare with, so
the first run after enabling the mode still notifies everything.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.schemas.decision_action import display_action_fields_for_result

logger = logging.getLogger(__name__)


def should_alert(
    current: Dict[str, Any],
    previous: Optional[Dict[str, Any]],
    score_delta: int,
) -> bool:
    """Decide whether a stock's new signal is worth a notification.

    Args:
        current: ``{"sentiment_score": int | None, "action": str | None}`` for
            this run. ``action`` is one of buy/add/hold/reduce/sell/watch/
            avoid/alert.
        previous: the same shape for the latest earlier analysis, or ``None``
            when the stock has never been analyzed before.
        score_delta: minimum absolute score change (0-100 scale) that counts
            as material, from ``ALERT_SCORE_DELTA``.

    Returns:
        True to send the notification, False to stay quiet.
    """
    # First analysis of a stock: nothing to compare with, always notify.
    if previous is None:
        return True
    # Any change of recommended action (e.g. hold -> reduce) is material.
    if current.get("action") != previous.get("action"):
        return True
    # A missing score on either side can't prove "unchanged": notify (fail-open).
    cur_score, prev_score = current.get("sentiment_score"), previous.get("sentiment_score")
    if cur_score is None or prev_score is None:
        return True
    return abs(int(cur_score) - int(prev_score)) >= score_delta


def _current_signal(result: Any) -> Dict[str, Any]:
    action_fields = display_action_fields_for_result(result)
    return {
        "sentiment_score": getattr(result, "sentiment_score", None),
        "action": action_fields.get("action"),
    }


def _previous_signal(result: Any) -> Optional[Dict[str, Any]]:
    from src.services.history_comparison_service import get_signal_changes

    code = getattr(result, "code", None)
    if not code:
        return None
    try:
        history = get_signal_changes(code, limit=1, exclude_query_id=getattr(result, "query_id", None))
    except Exception as exc:  # history is best-effort; never block a notification on it
        logger.warning("alert-on-change: history lookup failed for %s: %s", code, exc)
        return None
    return history[0] if history else None


def filter_changed_results(results: List[Any], score_delta: int) -> List[Any]:
    """Return only the results whose signal changed enough to notify."""
    changed = []
    for result in results:
        current = _current_signal(result)
        previous = _previous_signal(result)
        if should_alert(current, previous, score_delta):
            changed.append(result)
        else:
            logger.info(
                "alert-on-change: %s unchanged (score %s, action %s), notification skipped",
                getattr(result, "code", "?"),
                current.get("sentiment_score"),
                current.get("action"),
            )
    return changed
