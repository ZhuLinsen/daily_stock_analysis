# -*- coding: utf-8 -*-
"""Assemble ResearchProviders for scheduled and interactive runs."""

from __future__ import annotations

import os
from typing import List, Optional, Sequence

from src.agent.providers.ai_berkshire import DEFAULT_ROOT as BERKSHIRE_DEFAULT_ROOT
from src.agent.providers.ai_berkshire import AiBerkshireProvider
from src.agent.providers.dsa_technical import DsaTechnicalProvider, TechnicalMarketFetcher
from src.agent.providers.xiaolonglong import (
    DEFAULT_ROOT as XIAOLONGLONG_DEFAULT_ROOT,
    GrantStore,
    StaticGrantStore,
    XiaolonglongProvider,
)
from src.agent.research_provider import ResearchProvider


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_research_providers(
    *,
    include_mock: bool = False,
    include_technical: bool = True,
    include_berkshire: bool = False,
    include_xiaolonglong: bool = False,
    technical_fetcher: Optional[TechnicalMarketFetcher] = None,
    berkshire_root: Optional[str] = None,
    berkshire_pinned_sha: Optional[str] = None,
    xiaolonglong_root: Optional[str] = None,
    xiaolonglong_grants: Optional[GrantStore] = None,
) -> List[ResearchProvider]:
    """Return providers. Live checkouts are opt-in so CI stays offline."""
    providers: List[ResearchProvider] = []
    if include_mock:
        from tests.research.mock_provider import MockResearchProvider

        providers.append(MockResearchProvider())
    if include_technical:
        providers.append(DsaTechnicalProvider(fetcher=technical_fetcher))
    if include_berkshire:
        kwargs = {"root": berkshire_root} if berkshire_root else {}
        if berkshire_pinned_sha:
            kwargs["pinned_sha"] = berkshire_pinned_sha
        providers.append(AiBerkshireProvider(**kwargs))
    if include_xiaolonglong and xiaolonglong_grants is not None:
        providers.append(
            XiaolonglongProvider(
                root=xiaolonglong_root,
                grants=xiaolonglong_grants,
            )
        )
    return providers


def build_scheduled_providers() -> Sequence[ResearchProvider]:
    """Production-ish assembly. Berkshire/XLL only if local roots and grants exist."""
    grants_raw = os.environ.get("DSA_XIAOLONGLONG_GRANTS", "")
    grant_ids = tuple(item.strip() for item in grants_raw.split(",") if item.strip())
    berkshire_root = os.environ.get("DSA_AI_BERKSHIRE_ROOT", BERKSHIRE_DEFAULT_ROOT)
    xll_root = os.environ.get("DSA_XIAOLONGLONG_ROOT", XIAOLONGLONG_DEFAULT_ROOT)
    return build_research_providers(
        include_technical=True,
        include_berkshire=os.path.isdir(berkshire_root),
        include_xiaolonglong=bool(grant_ids) and os.path.isdir(xll_root),
        berkshire_root=berkshire_root if os.path.isdir(berkshire_root) else None,
        xiaolonglong_root=xll_root if os.path.isdir(xll_root) else None,
        xiaolonglong_grants=StaticGrantStore(grant_ids) if grant_ids else None,
    )


def research_schedule_enabled() -> bool:
    return _truthy(os.environ.get("DSA_RESEARCH_OS_SCHEDULE", ""))
