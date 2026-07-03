# -*- coding: utf-8 -*-
"""Backtest attribution service.

Computes Brinson performance attribution for a set of BacktestResult records.
The service queries results from the database, delegates to
``src.core.backtest_attribution.compute_brinson_attribution``, and optionally
persists the attribution result as JSON on the summary record.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from src.core.backtest_attribution import compute_brinson_attribution
from src.repositories.backtest_repo import BacktestRepository
from src.schemas.backtest_attribution import BacktestAttributionResult
from src.storage import BacktestResult, DatabaseManager

logger = logging.getLogger(__name__)


class BacktestAttributionService:
    """Compute and persist Brinson attribution for backtest results."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        self.repo = BacktestRepository(self.db)

    def compute_attribution(
        self,
        *,
        backtest_id: Optional[int] = None,
        code: Optional[str] = None,
        eval_window_days: Optional[int] = None,
        limit: int = 500,
    ) -> BacktestAttributionResult:
        """Compute attribution for a single backtest result or a batch.

        If ``backtest_id`` is provided, computes for that single result
        (returns empty if insufficient data). Otherwise, queries a batch
        of results filtered by ``code`` and/or ``eval_window_days``.
        """
        results = self._fetch_results(
            backtest_id=backtest_id,
            code=code,
            eval_window_days=eval_window_days,
            limit=limit,
        )

        attribution = compute_brinson_attribution(results)
        if backtest_id is not None and attribution.total_results > 0:
            self._persist_attribution(backtest_id, attribution)
        return attribution

    def _fetch_results(
        self,
        *,
        backtest_id: Optional[int],
        code: Optional[str],
        eval_window_days: Optional[int],
        limit: int,
    ) -> List[BacktestResult]:
        """Fetch backtest results from the repository."""
        try:
            if backtest_id is not None:
                with self.db.get_session() as session:
                    result = session.get(BacktestResult, backtest_id)
                    return [result] if result else []
            # Batch query via repository
            return self.repo.list_results(
                code=code,
                eval_window_days=eval_window_days,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("backtest_attribution: fetch failed: %s", exc)
            return []

    def _persist_attribution(
        self, backtest_id: int, attribution: BacktestAttributionResult
    ) -> None:
        """Persist the attribution result as JSON on the backtest result row."""
        try:
            with self.db.get_session() as session:
                result = session.get(BacktestResult, backtest_id)
                if result is not None:
                    result.attribution_json = json.dumps(
                        attribution.model_dump(), ensure_ascii=False
                    )
                    session.commit()
        except Exception as exc:
            logger.warning("backtest_attribution: persist failed for id=%s: %s", backtest_id, exc)

    def load_attribution(self, backtest_id: int) -> Optional[BacktestAttributionResult]:
        """Load a previously persisted attribution result."""
        try:
            with self.db.get_session() as session:
                result = session.get(BacktestResult, backtest_id)
                if result is None or not result.attribution_json:
                    return None
                data = json.loads(result.attribution_json)
                return BacktestAttributionResult.model_validate(data)
        except Exception as exc:
            logger.warning("backtest_attribution: load failed for id=%s: %s", backtest_id, exc)
            return None
