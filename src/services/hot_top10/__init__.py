# -*- coding: utf-8 -*-
"""Daily hot-top10 light analysis (Issue #1936, default OFF). Four layers:
datasource (hot-list fetch/normalize), analysis (LLM prompt/parse/render),
idempotency (per-day dedup marker, delivery-grade write semantics),
service (facade ``run_hot_top10_analysis`` + delivery contract).
Switch ``HOT_TOP10_ENABLED`` (default false): unset means zero behavior."""

from src.services.hot_top10.service import HotTop10RunResult, run_hot_top10_analysis  # noqa: F401
