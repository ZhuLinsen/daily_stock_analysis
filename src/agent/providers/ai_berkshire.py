# -*- coding: utf-8 -*-
"""DSA Research OS — AiBerkshireProvider.

Read-only adapter over a pinned AI Berkshire checkout. The provider never
copies that repository into DSA, never fetches remotes, and never enables
Berkshire tool networking. A revision / origin / dirty-tree mismatch is
fail-closed as ``REVISION_MISMATCH``. Missing theses abstain on the long
horizon instead of inventing a stance.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Protocol, Tuple, Union

from src.schemas.research_contracts import (
    Claim,
    ClaimKind,
    EvidenceFreshness,
    EvidenceRef,
    FailMode,
    FrameworkOpinion,
    Horizon,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorCode,
    ProviderRole,
    ResearchRequest,
    SensitiveLevel,
    Stance,
)

PROVIDER_ID = "ai-berkshire"
PROVIDER_VERSION = "0.1.0"
PINNED_SHA = "4ddc638fd5366e9779450e5685d7a2a3cdff5fd0"
DEFAULT_ROOT = "/Volumes/future/projects/DSA Research OS/ai-berkshire-reference"
ALLOWED_ORIGINS = (
    "https://github.com/xbtlin/ai-berkshire.git",
    "https://github.com/xbtlin/ai-berkshire",
)
# Compare as strings only. Never stat, open, or resolve this location.
_FORBIDDEN_ROOT_PREFIXES = (
    "/Volumes/future/projects/ai-berkshire-fork",
)
_STANCE_RE = re.compile(
    r"(?:^|\n)\s*(?:stance|立场)\s*[:=]\s*(bullish|bearish|neutral|abstain)\b",
    re.IGNORECASE,
)
_MAX_REPORT_BYTES = 2_000_000


@dataclass(frozen=True)
class CheckoutLock:
    root: str
    head: str
    origin: str
    clean: bool


@dataclass(frozen=True)
class ThesisHit:
    relative_path: str
    content_hash: str
    title: str
    stance: Optional[Stance]
    size_bytes: int


class CheckoutInspector(Protocol):
    def inspect(self, root: str) -> CheckoutLock:
        ...


class ThesisIndex(Protocol):
    def find(self, root: str, subject: str) -> Tuple[ThesisHit, ...]:
        ...


def _normalize_origin(url: str) -> str:
    value = url.strip()
    if value.endswith(".git"):
        value = value[:-4]
    return value.rstrip("/")


def _is_forbidden_root(root: str) -> bool:
    given = os.path.normpath(root)
    for prefix in _FORBIDDEN_ROOT_PREFIXES:
        if given == prefix or given.startswith(prefix + os.sep):
            return True
    return False


def _run_git(root: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", root, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "git command failed").strip()
        raise RuntimeError(message[:300])
    return result.stdout


class GitCheckoutInspector:
    """Local git metadata only — never fetch, pull, or checkout."""

    def inspect(self, root: str) -> CheckoutLock:
        if _is_forbidden_root(root):
            raise RuntimeError("forbidden checkout rejected")
        if not os.path.isdir(root):
            raise RuntimeError("berkshire checkout is not a directory")
        head = _run_git(root, "rev-parse", "HEAD").strip()
        origin = _run_git(root, "remote", "get-url", "origin").strip()
        porcelain = _run_git(root, "status", "--porcelain")
        return CheckoutLock(
            root=root,
            head=head,
            origin=origin,
            clean=porcelain.strip() == "",
        )


class FilesystemThesisIndex:
    """Read-only scan of ``reports/``; skips symlinks and path escapes."""

    def find(self, root: str, subject: str) -> Tuple[ThesisHit, ...]:
        if _is_forbidden_root(root):
            return ()
        reports = Path(root) / "reports"
        if not reports.is_dir() or reports.is_symlink():
            return ()
        try:
            reports_real = reports.resolve()
            root_real = Path(root).resolve()
        except OSError:
            return ()
        if not str(reports_real).startswith(str(root_real) + os.sep) and reports_real != root_real / "reports":
            if root_real not in reports_real.parents and reports_real != root_real:
                return ()
        needle = subject.casefold().strip()
        if not needle:
            return ()
        hits: list[ThesisHit] = []
        for dirpath, dirnames, filenames in os.walk(reports, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if not Path(dirpath, name).is_symlink()
            ]
            for name in filenames:
                path = Path(dirpath, name)
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if reports_real not in resolved.parents and resolved != reports_real:
                    continue
                rel = str(resolved.relative_to(reports_real)).replace(os.sep, "/")
                if needle not in rel.casefold() and needle not in name.casefold():
                    continue
                hit = _read_thesis(resolved, rel)
                if hit is not None:
                    hits.append(hit)
        hits.sort(key=lambda item: (len(item.relative_path), item.relative_path))
        return tuple(hits)


def _read_thesis(path: Path, relative_path: str) -> Optional[ThesisHit]:
    try:
        size = path.stat().st_size
        data = path.read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256(data).hexdigest()
    preview = data[:4096].decode("utf-8", errors="replace")
    stance = None
    match = _STANCE_RE.search(preview)
    if match:
        stance = Stance(match.group(1).lower())
    title = next(
        (line.strip("# ").strip() for line in preview.splitlines() if line.strip()),
        relative_path,
    )
    return ThesisHit(
        relative_path=relative_path,
        content_hash=digest,
        title=title[:180],
        stance=stance,
        size_bytes=size,
    )


class AiBerkshireProvider:
    """Required long-horizon provider locked to a pinned checkout."""

    provider_id = PROVIDER_ID
    provider_version = PROVIDER_VERSION

    def __init__(
        self,
        *,
        root: Optional[str] = None,
        pinned_sha: str = PINNED_SHA,
        inspector: Optional[CheckoutInspector] = None,
        thesis_index: Optional[ThesisIndex] = None,
    ) -> None:
        env_root = os.environ.get("DSA_AI_BERKSHIRE_ROOT", "").strip()
        self._root = root or env_root or DEFAULT_ROOT
        self._pinned_sha = pinned_sha
        self._inspector = inspector or GitCheckoutInspector()
        self._thesis_index = thesis_index or FilesystemThesisIndex()
        self._cancel_event = threading.Event()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            supported_markets=("cn", "hk", "us", "jp", "kr"),
            supported_horizons=(Horizon.LONG,),
            supported_evidence_types=("thesis", "file"),
            supports_sync=True,
            supports_background=False,
            supports_cancellation=True,
            max_output_bytes=65536,
            requires_network=False,
            reproducibility_level="revision-locked",
            role=ProviderRole.REQUIRED,
        )

    def validate(self, request: ResearchRequest) -> None:
        if not request.request_id:
            raise self._error(
                request,
                ProviderErrorCode.CONTRACT_VIOLATION,
                "validate",
                "request_id is required",
            )
        if not request.subject:
            raise self._error(
                request,
                ProviderErrorCode.CONTRACT_VIOLATION,
                "validate",
                "subject is required",
            )
        lock = self._require_lock(request)
        if isinstance(lock, ProviderError):
            raise lock

    def research(
        self,
        request: ResearchRequest,
        context: Optional[Dict] = None,
    ) -> Union[FrameworkOpinion, ProviderError]:
        del context
        if self._cancel_event.is_set():
            return self._error(
                request,
                ProviderErrorCode.CANCELLED,
                "research",
                "berkshire research cancelled",
                fail_mode=FailMode.FAIL_OPEN,
            )
        try:
            self.validate(request)
        except ProviderError as exc:
            return exc

        horizon = request.horizons[0] if request.horizons else Horizon.LONG
        if horizon != Horizon.LONG:
            return self._opinion(
                request,
                horizon,
                Stance.ABSTAIN,
                gaps=("AI Berkshire provider covers the 3-10 year horizon only",),
                warnings=("short/medium technical questions are out of scope",),
            )

        if self._cancel_event.is_set():
            return self._error(
                request,
                ProviderErrorCode.CANCELLED,
                "research",
                "berkshire research cancelled",
                fail_mode=FailMode.FAIL_OPEN,
            )

        hits = self._thesis_index.find(self._root, request.subject)
        if not hits:
            return self._opinion(
                request,
                Horizon.LONG,
                Stance.ABSTAIN,
                gaps=(f"no pinned thesis matched {request.subject}",),
                warnings=("missing report; long horizon abstains instead of inventing a stance",),
            )

        hit = hits[0]
        if hit.size_bytes > _MAX_REPORT_BYTES:
            return self._opinion(
                request,
                Horizon.LONG,
                Stance.ABSTAIN,
                gaps=(f"pinned thesis {hit.relative_path} exceeds read cap",),
            )

        stance = hit.stance or Stance.NEUTRAL
        evidence = EvidenceRef(
            evidence_id=f"berkshire-{hit.content_hash[:12]}",
            source_type="file",
            source_uri=f"berkshire://reports/{hit.relative_path}",
            title=hit.title,
            publisher="AI Berkshire pinned checkout",
            published_at="",
            observed_at="",
            as_of=request.as_of,
            content_hash=hit.content_hash,
            authorization="public",
            sensitive_level=SensitiveLevel.PUBLIC,
            license="MIT",
            freshness=EvidenceFreshness.FRESH,
            claim_ids=("berkshire-thesis-fact", "berkshire-thesis-opinion"),
            locator=f"reports/{hit.relative_path}#sha256:{hit.content_hash}",
        )
        fact = Claim(
            claim_id="berkshire-thesis-fact",
            claim_kind=ClaimKind.FACT,
            text=f"Pinned thesis reports/{hit.relative_path} matches {request.subject}",
            evidence_ids=(evidence.evidence_id,),
            confidence=0.9,
        )
        opinion = Claim(
            claim_id="berkshire-thesis-opinion",
            claim_kind=ClaimKind.OPINION,
            text=(
                f"Long-horizon stance from structured field is {stance.value}"
                if hit.stance
                else f"Pinned thesis exists for {request.subject}; no structured stance field"
            ),
            evidence_ids=(evidence.evidence_id,),
            dependent_fact_ids=(fact.claim_id,),
            confidence=0.7 if hit.stance else 0.4,
        )
        warnings = ()
        if hit.stance is None:
            warnings = ("no structured stance in pinned report; defaulting to neutral",)
        return self._opinion(
            request,
            Horizon.LONG,
            stance,
            confidence=opinion.confidence,
            data_quality=0.8,
            claims=(fact, opinion),
            evidence_refs=(evidence,),
            assumptions=("Checkout SHA, origin, and clean tree match the pinned revision",),
            warnings=warnings,
            invalidation_conditions=("Pinned SHA changes or the matching report is removed",),
        )

    def cancel(self, task_id: str) -> bool:
        del task_id
        self._cancel_event.set()
        return True

    def health(self) -> bool:
        if _is_forbidden_root(self._root):
            return False
        return os.path.isdir(self._root)

    def _require_lock(self, request: ResearchRequest) -> Union[CheckoutLock, ProviderError]:
        if _is_forbidden_root(self._root):
            return self._error(
                request,
                ProviderErrorCode.REVISION_MISMATCH,
                "validate",
                "forbidden checkout rejected",
            )
        try:
            lock = self._inspector.inspect(self._root)
        except Exception as exc:  # noqa: BLE001 - fail closed
            return self._error(
                request,
                ProviderErrorCode.DEPENDENCY_UNAVAILABLE,
                "validate",
                f"cannot inspect pinned checkout: {exc}"[:300],
            )
        if lock.head != self._pinned_sha:
            return self._error(
                request,
                ProviderErrorCode.REVISION_MISMATCH,
                "validate",
                "checkout HEAD is not the pinned SHA",
                details={"expected": self._pinned_sha, "actual": lock.head},
            )
        if _normalize_origin(lock.origin) not in {_normalize_origin(item) for item in ALLOWED_ORIGINS}:
            return self._error(
                request,
                ProviderErrorCode.REVISION_MISMATCH,
                "validate",
                "checkout origin is not the pinned AI Berkshire remote",
                details={"origin": lock.origin},
            )
        if not lock.clean:
            return self._error(
                request,
                ProviderErrorCode.REVISION_MISMATCH,
                "validate",
                "checkout is dirty; pinned revision must stay clean",
            )
        return lock

    def _error(
        self,
        request: ResearchRequest,
        code: ProviderErrorCode,
        stage: str,
        message: str,
        *,
        fail_mode: FailMode = FailMode.FAIL_CLOSED,
        details: Optional[Dict[str, str]] = None,
    ) -> ProviderError:
        return ProviderError(
            request_id=request.request_id,
            run_id=request.run_id,
            code=code,
            stage=stage,
            retryable=False,
            fallbackable=False,
            fail_mode=fail_mode,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            partial=False,
            details=details or {},
            message=message,
        )

    def _opinion(
        self,
        request: ResearchRequest,
        horizon: Horizon,
        stance: Stance,
        *,
        confidence: float = 0.0,
        data_quality: float = 0.0,
        claims: Tuple[Claim, ...] = (),
        evidence_refs: Tuple[EvidenceRef, ...] = (),
        gaps: Tuple[str, ...] = (),
        warnings: Tuple[str, ...] = (),
        assumptions: Tuple[str, ...] = (),
        invalidation_conditions: Tuple[str, ...] = (),
    ) -> FrameworkOpinion:
        return FrameworkOpinion(
            request_id=request.request_id,
            run_id=request.run_id,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            framework="ai-berkshire",
            framework_version=self.provider_version,
            as_of=request.as_of,
            horizon=horizon,
            stance=stance,
            confidence=confidence,
            data_quality=data_quality,
            claims=claims,
            evidence_refs=evidence_refs,
            gaps=gaps,
            warnings=warnings,
            assumptions=assumptions,
            data_cutoff=request.as_of,
            invalidation_conditions=invalidation_conditions,
        )

