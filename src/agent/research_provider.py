# -*- coding: utf-8 -*-
"""DSA Research OS — ResearchProvider protocol interface.

Uses ``typing.Protocol`` (structural subtyping) following the DSA codebase
convention established by ``src/llm/generation_backend.py``.  Implementations
are checked structurally, not by inheritance.
"""

from __future__ import annotations

from typing import Dict, Optional, Protocol, Union, runtime_checkable

from src.schemas.research_contracts import (
    FrameworkOpinion,
    ProviderCapabilities,
    ProviderError,
    ResearchRequest,
)


@runtime_checkable
class ResearchProvider(Protocol):
    """Protocol implemented by research providers.

    A provider receives a validated ``ResearchRequest`` and returns either
    a ``FrameworkOpinion`` or a ``ProviderError``.  Providers must not
    self-expand the request scope or make unauthorised external calls.
    """

    provider_id: str
    provider_version: str

    def capabilities(self) -> ProviderCapabilities:
        """Return this provider's capability declaration."""
        ...

    def validate(self, request: ResearchRequest) -> None:
        """Validate the request against this provider's capabilities.

        Raises ``ProviderError`` if the request is invalid.
        """
        ...

    def research(
        self,
        request: ResearchRequest,
        context: Optional[Dict] = None,
    ) -> Union[FrameworkOpinion, ProviderError]:
        """Execute the research and return an opinion or error."""
        ...

    def cancel(self, task_id: str) -> bool:
        """Cancel a running background task.  Returns True if cancelled."""
        ...

    def health(self) -> bool:
        """Check provider health without network or secret side-effects."""
        ...
