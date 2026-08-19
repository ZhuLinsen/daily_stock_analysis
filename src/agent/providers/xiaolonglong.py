# -*- coding: utf-8 -*-
"""DSA Research OS — XiaolonglongProvider.

Authorized private-knowledge retrieval. The on-disk index lives only under
the approved private root. Public outputs expose opaque ``private://`` IDs,
dates, grant status, and content hashes — never source paths, excerpts,
summaries, or vectors.

Authorization is compared against a server-side grant store. A request
cannot self-declare access by stuffing ``authorization_context``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Protocol, Tuple, Union

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

PROVIDER_ID = "xiaolonglong"
PROVIDER_VERSION = "0.1.0"
DEFAULT_ROOT = "/Volumes/future/projects/DSA Research OS/private-knowledge/xiaolonglong"
INDEX_DIR_NAME = ".research-index"
_STANCE_RE = re.compile(
    r"(?:^|\n)\s*(?:stance|立场)\s*[:=]\s*(bullish|bearish|neutral|abstain)\b",
    re.IGNORECASE,
)
_MAX_FILE_BYTES = 1_000_000


class GrantStore(Protocol):
    def active_grant(self, token: str) -> bool:
        ...


class StaticGrantStore:
    """Server-side issued grants. Empty token is never authorized."""

    def __init__(self, grants: Iterable[str] = ()) -> None:
        self._grants = {item for item in grants if item}

    def active_grant(self, token: str) -> bool:
        return bool(token) and token in self._grants

    def revoke(self, token: str) -> None:
        self._grants.discard(token)

    def issue(self, token: str) -> None:
        if token:
            self._grants.add(token)


@dataclass(frozen=True)
class IndexEntry:
    opaque_id: str
    content_hash: str
    as_of: str
    grant_ids: Tuple[str, ...]
    subjects: Tuple[str, ...]
    revoked: bool
    internal_relpath: str


class XiaolonglongProvider:
    provider_id = PROVIDER_ID
    provider_version = PROVIDER_VERSION

    def __init__(
        self,
        *,
        root: Optional[str] = None,
        grants: Optional[GrantStore] = None,
    ) -> None:
        env_root = os.environ.get("DSA_XIAOLONGLONG_ROOT", "").strip()
        self._root = Path(root or env_root or DEFAULT_ROOT)
        self._grants = grants or StaticGrantStore()
        self._cancel_event = threading.Event()
        self._index_lock = threading.Lock()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            supported_markets=("cn", "hk", "us", "jp", "kr"),
            supported_horizons=(Horizon.MEDIUM, Horizon.LONG),
            supported_evidence_types=("private",),
            supports_sync=True,
            supports_background=False,
            supports_cancellation=True,
            max_output_bytes=65536,
            requires_network=False,
            handles_private_data=True,
            reproducibility_level="authorized-index",
            role=ProviderRole.REQUIRED,
        )

    def validate(self, request: ResearchRequest) -> None:
        if not request.request_id:
            raise self._error(request, ProviderErrorCode.CONTRACT_VIOLATION, "request_id is required")
        if not request.subject:
            raise self._error(request, ProviderErrorCode.CONTRACT_VIOLATION, "subject is required")
        if not self._grants.active_grant(request.authorization_context):
            raise self._error(
                request,
                ProviderErrorCode.UNAUTHORIZED,
                "authorization grant is missing or revoked",
            )
        approved = self._approved_root()
        if approved is None:
            raise self._error(
                request,
                ProviderErrorCode.DEPENDENCY_UNAVAILABLE,
                "private knowledge root is not an approved directory",
            )

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
                "private knowledge research cancelled",
                fail_mode=FailMode.FAIL_OPEN,
            )
        try:
            self.validate(request)
        except ProviderError as exc:
            return exc

        horizon = request.horizons[0] if request.horizons else Horizon.MEDIUM
        if horizon == Horizon.SHORT:
            return self._opinion(
                request,
                horizon,
                Stance.ABSTAIN,
                gaps=("private industry notes are not used for 0-20 trading day calls",),
            )

        entries = [
            entry
            for entry in self._load_index()
            if not entry.revoked
            and request.authorization_context in entry.grant_ids
            and request.subject.casefold() in {item.casefold() for item in entry.subjects}
        ]
        if self._cancel_event.is_set():
            return self._error(
                request,
                ProviderErrorCode.CANCELLED,
                "private knowledge research cancelled",
                fail_mode=FailMode.FAIL_OPEN,
            )
        if not entries:
            return self._opinion(
                request,
                horizon,
                Stance.ABSTAIN,
                gaps=("no authorized private note matched this subject",),
            )

        entry = entries[0]
        stance = self._read_structured_stance(entry) or Stance.NEUTRAL
        evidence = EvidenceRef(
            evidence_id=f"private-{entry.opaque_id}",
            source_type="private",
            source_uri=f"private://{entry.opaque_id}",
            title="authorized private note",
            publisher="xiaolonglong",
            published_at=entry.as_of,
            observed_at=entry.as_of,
            as_of=entry.as_of,
            content_hash=entry.content_hash,
            authorization="granted",
            sensitive_level=SensitiveLevel.PRIVATE,
            license="private",
            freshness=EvidenceFreshness.FRESH,
            claim_ids=("xll-note-fact", "xll-note-opinion"),
            locator=f"private://{entry.opaque_id}",
        )
        fact = Claim(
            claim_id="xll-note-fact",
            claim_kind=ClaimKind.FACT,
            text=f"Authorized private note {entry.opaque_id} applies to {request.subject}",
            evidence_ids=(evidence.evidence_id,),
            confidence=0.8,
        )
        opinion = Claim(
            claim_id="xll-note-opinion",
            claim_kind=ClaimKind.OPINION,
            text=f"Authorized private stance for {request.subject} is {stance.value}",
            evidence_ids=(evidence.evidence_id,),
            dependent_fact_ids=(fact.claim_id,),
            confidence=0.55,
        )
        return self._opinion(
            request,
            horizon,
            stance,
            confidence=0.55,
            data_quality=0.7,
            claims=(fact, opinion),
            evidence_refs=(evidence,),
            assumptions=("Grant is still active and the private index entry is not revoked",),
            invalidation_conditions=("Grant revocation or index rebuild that drops this opaque ID",),
        )

    def cancel(self, task_id: str) -> bool:
        del task_id
        self._cancel_event.set()
        return True

    def health(self) -> bool:
        return self._approved_root() is not None

    def rebuild_index(self, *, as_of: str = "") -> Tuple[str, ...]:
        """Write a private index under the approved root. Returns opaque IDs only."""
        root = self._approved_root()
        if root is None:
            return ()
        key = self._hmac_key(root)
        entries = []
        for path in _iter_private_files(root):
            rel = _relative_to_root(root, path)
            if rel is None:
                continue
            data = path.read_bytes()
            if len(data) > _MAX_FILE_BYTES:
                continue
            opaque_id = hmac.new(key, rel.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
            preview = data[:2048].decode("utf-8", errors="replace")
            subjects = _subjects_from_preview(preview, path.stem)
            entries.append(
                {
                    "opaque_id": opaque_id,
                    "content_hash": hashlib.sha256(data).hexdigest(),
                    "as_of": as_of or "",
                    "grant_ids": [],
                    "subjects": subjects,
                    "revoked": False,
                    "internal_relpath": rel,
                }
            )
        self._write_index(root, entries)
        return tuple(item["opaque_id"] for item in entries)

    def grant_index_entry(self, opaque_id: str, grant_id: str, *, as_of: str = "") -> bool:
        root = self._approved_root()
        if root is None or not grant_id:
            return False
        entries = [dict(item.__dict__) for item in self._load_index()]
        changed = False
        for item in entries:
            if item["opaque_id"] == opaque_id:
                grants = list(item.get("grant_ids") or [])
                if grant_id not in grants:
                    grants.append(grant_id)
                item["grant_ids"] = grants
                if as_of:
                    item["as_of"] = as_of
                changed = True
        if changed:
            self._write_index(root, entries)
        return changed

    def revoke_index_entry(self, opaque_id: str) -> bool:
        root = self._approved_root()
        if root is None:
            return False
        entries = [dict(item.__dict__) for item in self._load_index()]
        changed = False
        for item in entries:
            if item["opaque_id"] == opaque_id:
                item["revoked"] = True
                changed = True
        if changed:
            self._write_index(root, entries)
        return changed

    def _approved_root(self) -> Optional[Path]:
        try:
            raw = self._root
            if ".." in raw.parts:
                return None
            if not raw.exists() or raw.is_symlink() or not raw.is_dir():
                return None
            resolved = raw.resolve()
        except OSError:
            return None
        if resolved.is_symlink():
            return None
        return resolved

    def _index_dir(self, root: Path) -> Path:
        path = root / INDEX_DIR_NAME
        if path.exists() and (path.is_symlink() or not path.is_dir()):
            raise RuntimeError("index path is not a directory")
        path.mkdir(mode=0o700, exist_ok=True)
        return path

    def _hmac_key(self, root: Path) -> bytes:
        key_path = self._index_dir(root) / "hmac.key"
        if key_path.exists():
            if key_path.is_symlink():
                raise RuntimeError("index key must not be a symlink")
            return key_path.read_bytes()
        key = os.urandom(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(key_path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key

    def _load_index(self) -> Tuple[IndexEntry, ...]:
        root = self._approved_root()
        if root is None:
            return ()
        index_path = root / INDEX_DIR_NAME / "index.json"
        if not index_path.is_file() or index_path.is_symlink():
            return ()
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        entries = []
        for raw in payload.get("entries") or []:
            if not isinstance(raw, dict):
                continue
            opaque_id = str(raw.get("opaque_id") or "")
            if not opaque_id:
                continue
            entries.append(
                IndexEntry(
                    opaque_id=opaque_id,
                    content_hash=str(raw.get("content_hash") or ""),
                    as_of=str(raw.get("as_of") or ""),
                    grant_ids=tuple(str(item) for item in raw.get("grant_ids") or () if item),
                    subjects=tuple(str(item) for item in raw.get("subjects") or () if item),
                    revoked=bool(raw.get("revoked")),
                    internal_relpath=str(raw.get("internal_relpath") or ""),
                )
            )
        return tuple(entries)

    def _write_index(self, root: Path, entries: list[dict]) -> None:
        index_dir = self._index_dir(root)
        path = index_dir / "index.json"
        payload = {"version": 1, "entries": entries}
        tmp = index_dir / "index.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _read_structured_stance(self, entry: IndexEntry) -> Optional[Stance]:
        root = self._approved_root()
        if root is None:
            return None
        path = _safe_join(root, entry.internal_relpath)
        if path is None or not path.is_file():
            return None
        try:
            preview = path.read_bytes()[:2048].decode("utf-8", errors="replace")
        except OSError:
            return None
        match = _STANCE_RE.search(preview)
        if not match:
            return None
        return Stance(match.group(1).lower())

    def _error(
        self,
        request: ResearchRequest,
        code: ProviderErrorCode,
        message: str,
        *,
        fail_mode: FailMode = FailMode.FAIL_CLOSED,
    ) -> ProviderError:
        return ProviderError(
            request_id=request.request_id,
            run_id=request.run_id,
            code=code,
            stage="validate" if code != ProviderErrorCode.CANCELLED else "research",
            retryable=False,
            fallbackable=False,
            fail_mode=fail_mode,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            partial=False,
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
        assumptions: Tuple[str, ...] = (),
        invalidation_conditions: Tuple[str, ...] = (),
    ) -> FrameworkOpinion:
        return FrameworkOpinion(
            request_id=request.request_id,
            run_id=request.run_id,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            framework="xiaolonglong",
            framework_version=self.provider_version,
            as_of=request.as_of,
            horizon=horizon,
            stance=stance,
            confidence=confidence,
            data_quality=data_quality,
            claims=claims,
            evidence_refs=evidence_refs,
            gaps=gaps,
            assumptions=assumptions,
            data_cutoff=request.as_of,
            invalidation_conditions=invalidation_conditions,
        )


def _iter_private_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        if current.is_symlink() or current.name == INDEX_DIR_NAME:
            dirnames[:] = []
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if name != INDEX_DIR_NAME and not (current / name).is_symlink()
        ]
        for name in filenames:
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            if _relative_to_root(root, path) is None:
                continue
            yield path


def _relative_to_root(root: Path, path: Path) -> Optional[str]:
    try:
        resolved = path.resolve()
        rel = resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if ".." in rel.parts:
        return None
    return rel.as_posix()


def _safe_join(root: Path, rel: str) -> Optional[Path]:
    if not rel or ".." in Path(rel).parts:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if candidate.is_symlink():
        return None
    return candidate


def _subjects_from_preview(preview: str, fallback: str) -> list[str]:
    match = re.search(r"(?:^|\n)\s*subjects?\s*[:=]\s*([A-Za-z0-9_,.\- ]+)", preview, re.IGNORECASE)
    if match:
        return [item.strip() for item in match.group(1).split(",") if item.strip()]
    return [fallback] if fallback else []
