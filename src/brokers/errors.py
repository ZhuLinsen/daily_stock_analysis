# -*- coding: utf-8 -*-
"""Shared error types for broker portfolio integrations."""

from __future__ import annotations


class BrokerPortfolioError(RuntimeError):
    """Raised when a broker portfolio cannot be resolved safely."""
