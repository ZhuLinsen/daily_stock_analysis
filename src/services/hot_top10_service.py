# -*- coding: utf-8 -*-
"""Daily hot-top10 light analysis service (Issue #1936).

Every trading day, fetch the top-N market theme hot list from DSA's existing
industry/concept ranking providers (``MarketHotspotService``), generate ONE
lightweight LLM summary (per-theme driver / strength / entry advice / risk),
render a bilingual markdown report and push it through the existing report
notification channel.

Design rules:

- Fail-open everywhere: hotspot fetch failure, LLM failure and notification
  failure are logged and degraded, never raised into the scheduler loop.
- One LLM call produces the whole report (a T10 overview), NOT ten
  full per-stock analyses. This is a theme hot-list overview; users who need
  a deep single-stock report should use the existing analysis entry points.
- Daily dedup via a persisted JSON marker next to the SQLite database
  (same directory pattern as ``src/core/analysis_run_marker.py``): missing /
  corrupt / unreadable markers fail open (the run executes again). The marker
  is recorded only after the report was produced AND delivered — the push
  succeeded, or the push was intentionally skipped/disabled AND the local
  save succeeded (OR-COR-8c2d195e: a failed save with no successful push
  delivers nothing and leaves the marker open for the next retry).
- Trading-day gate reuses ``src/core/trading_calendar.get_open_markets_today``
  (fail-open: when the calendar library is unavailable every market counts as
  open). ``force_run`` bypasses both the gate and the dedup marker.
- Cross-slot in-flight mutex (OR-COR-9a41d2ce): the primary and data-ready
  occurrences register under different scheduler job names, so the
  scheduler's per-name guard does not mutually exclude them. A process-wide
  non-reentrant mutex covers each whole run (dedup checks -> LLM -> save ->
  deliver -> marker); a trigger arriving while another run holds it exits
  immediately with ``already_running`` — no push, no marker — and retries on
  the next occurrence.
- Cross-process claim ownership protocol (OR-COR-5c51e8d7 r7): independent
  scheduler processes sharing the same DATABASE_PATH arbitrate delivery per
  data date through ``hot_top10_claim_<data_date>.lock`` plus an OS advisory
  LOCK held for the whole delivery (review #11: user-space read-compare-
  write can never make read and replace atomic — three CAS probe rounds
  were each defeated — so the protocol now uses a real mutex). The claim
  file keeps its serialization: line 1 is the legacy ISO timestamp, then
  the owner token (uuid4 hex) and the pid. Publication is an atomic
  no-replace link of a fully written temp file. Takeover = LOCK ACQUIRED on
  the stale claim (process death releases the lock, which is the liveness
  oracle); the holder keeps the lock until the run ends. Release (r12,
  review #14) NEVER deletes the file: it rewrites the claim, while the lock
  is still held, to the RELEASED state — ``flock`` protects the open inode,
  not the path name, so the old unlock→delete window let a successor take
  the lock and then be clobbered BY PATH by the departing holder. The claim
  file is lifecycle-stable: first publication creates it, after that every
  handover is an in-place rewrite under the lock. The r5/r6 owner-token
  checks, the per-side-effect re-verification (save/notify/marker) and the
  release ownership verdict are all kept as defence in depth inside the lock.
  Platforms without OS locking degrade EXPLICITLY to the r6 compare-and-
  set path with a loud warning (never silent). ``force_run`` stays
  unclaimed; the in-process mutex stays the fast path.
- Cross-date dedup isolation (OR-COR-341d7b5a r7): dedup markers are one
  file per data date (``hot_top10_state_<YYYY-MM-DD>.json``), so a late
  stale delivery can never overwrite today's record and the retained
  pending follow-up can never re-push a data date that was already
  delivered today. Expired markers are pruned lazily after each write.
- Default OFF: with ``HOT_TOP10_ENABLED`` unset the feature registers nothing
  and changes zero behavior.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid

try:  # POSIX advisory whole-file locking (Linux/macOS CI runners)
    import fcntl

    _POSIX_LOCKING = True
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    _POSIX_LOCKING = False
try:  # Windows mandatory byte-range locking
    import msvcrt

    _WINDOWS_LOCKING = True
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None
    _WINDOWS_LOCKING = False

_CLAIM_LOCKING_AVAILABLE = _POSIX_LOCKING or _WINDOWS_LOCKING
# r12 (review #14): a claim file released by its owner keeps existing with
# this first-line marker; a released claim is immediately claimable by the
# next acquirer. The file itself is never deleted.
_CLAIM_RELEASED_MARKER = "RELEASED"
# The lock is a single byte FAR beyond any claim content (~1 MiB offset):
# on Windows LockFile ranges are mandatory for OTHER handles, so keeping
# the locked byte away from the content leaves every plain-content reader
# (owner-token verification, staleness parsing) unaffected. POSIX flock is
# advisory whole-file and does not disturb readers either.
_CLAIM_LOCK_OFFSET = 1 << 20
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_HOT_TOP10_COUNT = 10
MAX_HOT_TOP10_COUNT = 30
DEFAULT_HOT_TOP10_SCHEDULE_TIME = "15:10"
# Data-ready follow-up slot (OR-COR-3e7f490e, narrowed): the primary slot
# sits before the 15:30 Tushare ranking cut, so on default deployments its
# delivery covers the previous trading day and cannot consume today's dedup
# marker. A second daily occurrence shortly after the cut delivers today's
# list once the provider serves it (and idles when the primary slot already
# delivered today's data).
DEFAULT_HOT_TOP10_DATA_READY_SCHEDULE_TIME = "15:35"
# r7 (OR-COR-341d7b5a, review #11): one marker file per DATA DATE — a late
# stale delivery can no longer overwrite today's dedup record, and the
# retained pending follow-up can no longer re-push a data date that was
# already delivered today. Expired files are pruned lazily after writes.
MARKER_FILE_PREFIX = "hot_top10_state_"
MARKER_RETENTION_DAYS = 7
# v2 adds ``data_date`` (the ranking date the delivered report actually
# covers, OR-COR-3e7f490e). v1 markers fail open and re-deliver once.
MARKER_SCHEMA_VERSION = 2
LLM_MAX_TOKENS = 3000
LLM_TEMPERATURE = 0.3

# OR-COR-9a41d2ce: process-wide non-reentrant mutex held for the whole run
# (dedup checks -> LLM -> save -> deliver -> marker). The two schedule slots
# register under different job names, so only this service-level guard
# mutually excludes overlapping occurrences.
_HOT_TOP10_RUN_MUTEX = threading.Lock()

# OR-COR-7c92a610: one-shot pending follow-up request. Both schedule slots
# are daily-only, so a trigger that loses the mutex race must not be
# dropped outright — that would lose the day's follow-up opportunity when
# the primary run is slow. The in-flight holder consumes the flag right
# after finishing its own run: fresh data is fetched and the full dedup
# semantics decide whether anything ships.
_HOT_TOP10_PENDING_FOLLOWUP = threading.Event()

# OR-COR-5c51e8d7: the process mutex above cannot exclude two INDEPENDENT
# scheduler processes sharing the same DATABASE_PATH (CLI --schedule next to
# the Web/API/desktop runtime scheduler, or two replicas). Delivery is
# therefore arbitrated per data date through an ownership-protocol file next
# to the marker: ``hot_top10_claim_<data_date>.lock`` (protocol v3, r7):
#
# - Serialization (backward compatible): line 1 is the ISO claim timestamp
#   exactly as r4 wrote it; r5 appends the owner token (uuid4 hex) and the
#   pid on the following lines. r4 content (``{ts}\\n{pid}``) parses
#   unchanged: no token line means an UNOWNED claim, handled with r4
#   semantics (stale takeover; release deletes only while the first line is
#   still the timestamp we wrote).
# - Publishing is atomic: the full content is written to a same-directory
#   temp file first, then published with ``os.link`` (atomic no-replace on
#   Windows NTFS and POSIX alike). Filesystems without hardlink support
#   degrade to exclusive-create + immediate write, made safe by the reader
#   rule below.
# - Reader rule: an empty/unparseable claim file is LIVE (initialization in
#   progress, or an external occupant) — it is never deleted. Staleness is
#   the first-line timestamp past the TTL, falling to file mtime when the
#   first line cannot be parsed.
# - REAL MUTEX (r7, review #11): user-space read-compare-write can never
#   make read and replace atomic (review #10's CAS was defeated by pausing
#   after the re-read), so the delivery is now guarded by an OS advisory
#   lock on the claim file itself. The holder takes the lock at takeover /
#   publication and holds it for the WHOLE delivery; a contender's takeover
#   succeeds ONLY when the lock is acquired — which means the previous
#   holder is dead (the OS released the lock) or never held one. Process
#   death releasing the lock is the safety property crash-residue takeover
#   relies on. The locked byte sits at a 1 MiB offset, far beyond any
#   content, so Windows' mandatory ranges never block plain content reads.
# - Defence in depth kept inside the lock (r5/r6): owner token, per-side-
#   effect ownership re-verification (save/notify/marker), release verdict
#   before the unlink, and the compare-and-set for platforms without OS
#   locking (explicit, loud degradation — never silent).
HOT_TOP10_CLAIM_STALE_AFTER = timedelta(hours=2)
_HOT_TOP10_CLAIM_FILE_PREFIX = "hot_top10_claim_"
_OWNER_TOKEN_LENGTH = 32  # uuid4().hex


def hot_top10_claim_path(config: Any, data_date: str) -> Path:
    """Cross-process delivery claim file for ``data_date`` (marker's dir)."""
    return hot_top10_marker_path(config).parent / (
        f"{_HOT_TOP10_CLAIM_FILE_PREFIX}{data_date}.lock"
    )


def _new_owner_token() -> str:
    return uuid.uuid4().hex


def _render_claim_content(created_line: str, token: str) -> str:
    """Line 1: ISO timestamp (r4 first-line semantics preserved verbatim);
    line 2: owner token; line 3: pid."""
    return f"{created_line}\n{token}\n{os.getpid()}\n"


def _looks_like_owner_token(value: str) -> bool:
    """uuid4 hex tokens are exactly 32 lowercase hex chars; an r4 pid line
    is decimal digits and far shorter, so the two can never collide."""
    return len(value) == _OWNER_TOKEN_LENGTH and all(
        c in "0123456789abcdef" for c in value
    )


def _parse_claim_text(text: str) -> Tuple[Optional[datetime], Optional[str]]:
    """Parse claim content into ``(claimed_at, owner_token)``.

    Old r4 content (``{ts}\\n{pid}`` and anything without a token line)
    parses its first-line timestamp with ``owner_token=None`` — an UNOWNED
    claim handled with r4 semantics. Unparseable content yields
    ``(None, None)`` and counts as live via the mtime fallback."""
    lines = text.strip().splitlines()
    if not lines:
        return None, None
    try:
        claimed_at = datetime.fromisoformat(lines[0].strip())
    except ValueError:
        return None, None
    token: Optional[str] = None
    if len(lines) >= 2:
        candidate = lines[1].strip()
        if _looks_like_owner_token(candidate):
            token = candidate
    return claimed_at, token


def _read_claim_text(path: Path) -> Optional[str]:
    """Claim file content; ``None`` when missing/unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _claim_is_stale(path: Path, text: Optional[str]) -> bool:
    """Staleness: first-line timestamp past the TTL; for empty/unparseable
    content fall back to the file mtime (fresh mtime = live: an occupant
    mid-initialization is never treated stale and never deleted). A
    RELEASED claim is never stale — it is CLAIMABLE (see
    :func:`_claim_is_released`), which is a strictly stronger verdict."""
    if text and _claim_is_released(text):
        return False
    if text:
        claimed_at, _token = _parse_claim_text(text)
        if claimed_at is not None:
            return datetime.now() - claimed_at >= HOT_TOP10_CLAIM_STALE_AFTER
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    return (
        datetime.now() - datetime.fromtimestamp(mtime)
        >= HOT_TOP10_CLAIM_STALE_AFTER
    )


def _claim_is_released(text: str) -> bool:
    """r12 (review #14): whether the claim has been voluntarily released
    by its owner (first line is the RELEASED marker). Such a claim is
    immediately claimable — the takeover rewrites the existing file under
    its lock instead of waiting for a TTL or recreating the path."""
    lines = text.strip().splitlines()
    return bool(lines) and lines[0].strip() == _CLAIM_RELEASED_MARKER


def _render_released_content(
    created_line: Optional[str], token: Optional[str]
) -> str:
    """Released-state serialization: marker line, then the original
    timestamp and owner token for auditability."""
    return (
        f"{_CLAIM_RELEASED_MARKER}\n{created_line or ''}\n{token or ''}\n"
    )


def _write_claim_tmp(path: Path, content: str) -> Path:
    """Write the FULL claim content to a unique same-directory temp file."""
    tmp_path = path.with_name(
        f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return tmp_path


def _discard_claim_tmp(tmp_path: Path) -> None:
    try:
        tmp_path.unlink()
    except OSError:
        pass


def _publish_claim_exclusive(path: Path, content: str) -> bool:
    """Fallback for filesystems without hardlink support: exclusive-create
    then write immediately. A crash in between would leave a short-lived
    empty file, which the reader rule counts as live (never deleted)."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return True


def _publish_claim_atomically(path: Path, content: str) -> bool:
    """Create ``path`` with the FULL ``content`` in one atomic no-replace
    step; True when THIS process published it. ``os.link`` is atomic
    no-replace on Windows NTFS and POSIX alike; ``FileExistsError`` means
    another process already owns the claim."""
    tmp_path = _write_claim_tmp(path, content)
    try:
        try:
            os.link(str(tmp_path), str(path))
            return True
        except FileExistsError:
            return False
        except OSError:
            # No hardlink support on this filesystem: degrade to
            # exclusive-create + immediate write (the reader rule keeps the
            # would-be initialization window safe).
            return _publish_claim_exclusive(path, content)
    finally:
        _discard_claim_tmp(tmp_path)


def _steal_claim_atomically(
    path: Path, content: str, expected_text: str
) -> bool:
    """Replace a stale claim with our full content in one atomic rename,
    guarded by a compare-and-set. This is the EXPLICIT DEGRADATION path for
    platforms without OS locking (review #11: with the lock available the
    takeover goes through :func:`_take_over_stale_claim` instead). The
    residual read→replace window of this path is exactly what the review
    showed cannot be closed in user space; it is healed by the notify-time
    ownership re-verification (exactly-once invariant)."""
    tmp_path = _write_claim_tmp(path, content)
    try:
        observed = _read_claim_text(path)
        if observed != expected_text:
            return False
        os.replace(str(tmp_path), str(path))
        return True
    finally:
        _discard_claim_tmp(tmp_path)


def _lock_claim_file(file_obj: Any) -> bool:
    """Try a non-blocking exclusive advisory lock on the open claim file.
    True when THIS handle holds it; False when someone else does. The lock
    applies to one byte at ``_CLAIM_LOCK_OFFSET`` (far beyond any content —
    see the module comment). Process death releases it automatically."""
    if not _CLAIM_LOCKING_AVAILABLE:
        return False
    try:
        if _POSIX_LOCKING:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        file_obj.seek(_CLAIM_LOCK_OFFSET)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _unlock_claim_file(file_obj: Any) -> None:
    """Release the advisory lock; best-effort (closing also releases)."""
    try:
        if _POSIX_LOCKING:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
        elif _WINDOWS_LOCKING:
            file_obj.seek(_CLAIM_LOCK_OFFSET)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
    except (OSError, ValueError):
        pass


def _rewrite_locked_claim(file_obj: Any, content: str) -> None:
    """Replace the whole content through the already-locked handle."""
    file_obj.seek(0)
    file_obj.truncate(0)
    file_obj.write(content.encode("utf-8"))
    file_obj.flush()
    os.fsync(file_obj.fileno())


_CLAIM_VANISHED = object()


def _take_over_stale_claim(
    path: Path, content: str, expected_text: str
) -> Tuple[str, Optional[Any]]:
    """Protocol v3 takeover (review #11 blocker 1): open the stale claim
    and attempt the exclusive advisory lock.

    - Lock ACQUIRED ⇒ the previous holder is DEAD (the OS released the
      lock) or never held one — the claim is rewritten as ours through the
      locked handle and the lock stays held for the whole delivery. From
      this instant no other process can lock the file, so a parked
      contender resuming after us is refused at the lock instead of
      clobbering us — the r6 CAS read→replace window is closed at the root.
    - Lock REFUSED ⇒ the holder is ALIVE: back off (``"busy"``).
    - Platforms without OS locking degrade EXPLICITLY to the r6
      compare-and-set replace (loud warning; ``("cas", None)``).

    Returns ``(status, lock_file)`` with status ``"locked"`` / ``"cas"`` /
    ``"busy"`` / ``"vanished"``.
    """
    if not _CLAIM_LOCKING_AVAILABLE:
        # Explicit degradation — and deliberately WITHOUT holding any open
        # handle: on Windows an open handle would block our own os.replace.
        logger.warning(
            "[HotTop10] 本平台不可用 OS 文件锁，认领接管退化为 CAS "
            "用户态协议（互斥强度受限，仅供降级环境；不静默假成功）"
        )
        if _steal_claim_atomically(path, content, expected_text):
            return "cas", None
        return "busy", None
    try:
        file_obj = open(path, "r+b")
    except FileNotFoundError:
        return "vanished", None
    except OSError:
        return "busy", None
    try:
        if not _lock_claim_file(file_obj):
            file_obj.close()
            return "busy", None  # the holder is alive — the lock says so
        # Locked. A content change since the staleness verdict can only
        # mean another takeover finished and its process then died (the
        # OS released its lock) — we legitimately succeed it; log only.
        observed = file_obj.read()
        if observed.decode("utf-8", "replace") != expected_text:
            logger.info(
                "[HotTop10] 接管锁成功但认领内容已变化"
                "（前一接管者进程已死亡），按崩溃残留继承接管"
            )
        _rewrite_locked_claim(file_obj, content)
        return "locked", file_obj
    except OSError:
        _unlock_claim_file(file_obj)
        try:
            file_obj.close()
        except OSError:
            pass
        return "busy", None


def _open_and_lock_claim(path: Path) -> Optional[Any]:
    """Open the freshly published claim and take the delivery lock; ``None``
    on any failure (the caller then falls back to token verification).
    Degraded platforms publish without a lock (explicit fallback)."""
    try:
        file_obj = open(path, "r+b")
    except OSError:
        return None
    if not _CLAIM_LOCKING_AVAILABLE:
        return None
    if not _lock_claim_file(file_obj):
        file_obj.close()
        return None
    return file_obj


class _HotTop10DeliveryClaim:
    """A held cross-process delivery claim (protocol v4, r12).

    The mutual exclusion is the OS advisory lock held on the open claim
    file for the WHOLE delivery (``_lock_file``); the owner token recorded
    in the file stays as defence in depth. ``verify_owner`` re-reads the
    file; ``release`` (r12, review #14) rewrites the claim to the RELEASED
    state UNDER the still-held lock and never deletes the file — the claim
    path is lifecycle-stable, so a successor taking over in the handover
    window can never be clobbered by path (``flock`` protects the inode,
    not the name). Lock-less handles (platforms without OS locking —
    explicit degradation — or the microsecond first-publication window)
    fall back to the verify-then-rewrite path with the same never-delete
    rule. A disarmed claim (claim directory unavailable) verifies
    trivially: the run proceeds fail-open without cross-process exclusion,
    exactly as before."""

    __slots__ = (
        "_path",
        "_token",
        "_created_line",
        "_released",
        "_armed",
        "_lock_file",
    )

    def __init__(
        self,
        path: Path,
        token: Optional[str] = None,
        created_line: Optional[str] = None,
        armed: bool = True,
        lock_file: Optional[Any] = None,
    ) -> None:
        self._path = path
        self._token = token
        self._created_line = created_line
        self._released = False
        self._armed = armed
        self._lock_file = lock_file

    @classmethod
    def disarmed(cls, path: Path) -> "_HotTop10DeliveryClaim":
        return cls(path, armed=False)

    def verify_owner(self) -> bool:
        """Whether the claim file still records THIS process's ownership."""
        if not self._armed:
            return True
        text = _read_claim_text(self._path)
        if text is None:
            return False
        return self._text_is_ours(text)

    def _text_is_ours(self, text: str) -> bool:
        """Ownership verdict on already-read content: token match; legacy
        token-less content matches only while its first line is still the
        timestamp we wrote (path + first-line double check)."""
        _claimed_at, token = _parse_claim_text(text)
        if token is not None:
            return token == self._token
        lines = text.strip().splitlines()
        return (
            bool(self._created_line)
            and bool(lines)
            and lines[0].strip() == self._created_line
        )

    def release(self) -> None:
        """Protocol v4 (r12, review #14): surrender the claim WITHOUT ever
        deleting the file. Fixed order: verify -> rewrite-to-RELEASED ->
        unlock -> close, all while the delivery lock is still held — so the
        old unlock→delete window (a successor takes the lock, rewrites its
        own token, and the departing holder then deletes the claim BY PATH;
        ``flock`` protects the inode, not the name) cannot exist. The file
        is lifecycle-stable: it survives with the RELEASED marker and is
        immediately claimable by the next acquirer. A foreign claim (the
        ownership verdict failed — this handle was superseded) is left
        byte-identical: no rewrite, no delete. The lock-less handle path
        (:meth:`_release_without_lock`) keeps the same never-delete rule."""
        if self._released:
            return
        self._released = True
        if not self._armed:
            return
        file_obj = self._lock_file
        self._lock_file = None
        if file_obj is None:
            self._release_without_lock()
            return
        released_content = _render_released_content(
            self._created_line, self._token
        )
        foreign = False
        try:
            text = _read_claim_text(self._path)
            if text is not None and not self._text_is_ours(text):
                foreign = True
                logger.warning(
                    "[HotTop10] 投递认领已易主（所有权校验不匹配），"
                    "不重写也不删除其他进程的认领文件"
                )
        finally:
            # Rewrite while STILL holding the lock, before unlocking — the
            # successor can only start after we unlock, and it then finds
            # the RELEASED marker, never a stale-looking live claim.
            if not foreign:
                try:
                    _rewrite_locked_claim(file_obj, released_content)
                except OSError as exc:
                    logger.warning(
                        "[HotTop10] 认领释放重写失败（保留原内容，文件不删除）: %s",
                        exc,
                    )
            _unlock_claim_file(file_obj)
            try:
                file_obj.close()
            except OSError:
                pass
        # r12: no unlink — ever. The claim file keeps existing in the
        # RELEASED state; the next acquirer takes it over in place.

    def _release_without_lock(self) -> None:
        """r12 release path for the explicit no-OS-locking degradation and
        for lock-less handles: verify once, then overwrite the content with
        the RELEASED state — NEVER delete. (The old r6 verify→unlink pair
        had the same by-path clobber window the review reopened.)"""
        text = _read_claim_text(self._path)
        if text is None:
            return
        if not self._text_is_ours(text):
            logger.warning(
                "[HotTop10] 投递认领已易主（所有权校验不匹配），"
                "不重写也不删除其他进程的认领文件"
            )
            return
        try:
            with open(self._path, "w", encoding="utf-8") as handle:
                handle.write(
                    _render_released_content(
                        self._created_line, self._token
                    )
                )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            logger.warning(
                "[HotTop10] 认领释放重写失败（保留原内容，文件不删除）: %s", exc
            )


def acquire_hot_top10_delivery_claim(
    config: Any, data_date: str
) -> Optional[_HotTop10DeliveryClaim]:
    """Atomically claim the right to deliver ``data_date`` across processes.

    Returns the claim handle, or ``None`` when another live owner holds the
    claim (caller reports ``already_claimed``: no push, no marker, retry on
    the next trigger).

    Protocol v3 (r7, review #11): the first publication is an atomic
    no-replace ``os.link`` of a fully written temp file and takes the
    delivery LOCK immediately; a claim past ``HOT_TOP10_CLAIM_STALE_AFTER``
    (first-line timestamp; mtime fallback for empty/unparseable files) is
    crash residue and is taken over by LOCKING the existing file — success
    means the previous holder is dead (the OS released the lock) or never
    held one, and the lock stays held for the whole delivery. Old r4 files
    (timestamp + pid, no token) take over the same way. When several
    processes race the takeover, the lock serializes them: exactly one
    wins, every other contender is refused (``already_claimed``) no matter
    where it was parked. Owner tokens, per-side-effect re-verification and
    the release verdict remain as defence in depth; platforms without OS
    locking degrade explicitly to the r6 compare-and-set path."""
    claim_path = hot_top10_claim_path(config, data_date)
    try:
        claim_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "[HotTop10] 认领目录创建失败，本次退化为无跨进程互斥: %s", exc
        )
        return _HotTop10DeliveryClaim.disarmed(claim_path)
    for _ in range(3):
        token = _new_owner_token()
        created_line = datetime.now().isoformat(timespec="seconds")
        content = _render_claim_content(created_line, token)
        if _publish_claim_atomically(claim_path, content):
            lock_file = None
            if _CLAIM_LOCKING_AVAILABLE:
                lock_file = _open_and_lock_claim(claim_path)
                if lock_file is None:
                    # Microsecond window: someone raced the lock (or the
                    # file vanished). A foreign file means we lost.
                    current = _read_claim_text(claim_path)
                    _ca, current_token = (
                        _parse_claim_text(current)
                        if current is not None
                        else (None, None)
                    )
                    if current_token != token:
                        continue
                    logger.warning(
                        "[HotTop10] 认领发布后加锁失败但内容仍为本进程所有，"
                        "以无锁句柄继续（副作用点复验为纵深防御）"
                    )
            return _HotTop10DeliveryClaim(
                claim_path,
                token=token,
                created_line=created_line,
                lock_file=lock_file,
            )
        # Lost the create race: someone else owns the file — inspect it.
        text = _read_claim_text(claim_path)
        if text is None:
            continue  # vanished in between: try publishing again
        released = _claim_is_released(text)
        if not released and not _claim_is_stale(claim_path, text):
            return None  # live (owner / initializing / occupant): never delete
        # RELEASED (r12 — immediately claimable) or stale crash residue
        # (r4/r5/r6 format): protocol takeover — lock the existing file.
        # Success ⇒ the previous holder released or is dead; refusal ⇒
        # holder alive; no user-space window can clobber a survivor. The
        # rewrite happens IN PLACE — the claim file's lifecycle is stable.
        status, lock_file = _take_over_stale_claim(claim_path, content, text)
        if status == "vanished":
            continue
        if status == "busy":
            return None
        return _HotTop10DeliveryClaim(
            claim_path,
            token=token,
            created_line=created_line,
            lock_file=lock_file,
        )
    return None


_ADVICE_VALUES = {"观望", "轻仓介入", "积极介入"}


@dataclass
class HotTop10RunResult:
    """Outcome of one hot-top10 run (never raises)."""

    delivered: bool
    skipped: bool
    reason: str
    report_markdown: Optional[str] = None
    llm_completed: bool = False
    notification_status: str = "not_attempted"
    # The trading-day date the delivered list actually covers; ``None`` when
    # the provider did not expose one (treated as current-day data).
    ranking_date: Optional[str] = None


# --------------------------------------------------------------------------
# Daily dedup marker (JSON file next to the SQLite database)
# --------------------------------------------------------------------------


def hot_top10_marker_path(config: Any, data_date: Optional[str] = None) -> Path:
    """Per-data-date marker location next to the SQLite database (data/ in
    deployments). ``None`` means today (OR-COR-341d7b5a r7: each ranking
    date owns its own state file, so a late stale delivery can never
    overwrite today's dedup record)."""
    marker_date = data_date or date.today().isoformat()
    database_path = getattr(config, "database_path", "./data/stock_analysis.db")
    return Path(database_path).parent / (
        f"{MARKER_FILE_PREFIX}{marker_date}.json"
    )


def hot_top10_already_delivered_today(config: Any) -> tuple:
    """Return ``(skip, reason)``. Missing/corrupt markers always fail open."""
    try:
        marker_path = hot_top10_marker_path(config)
        try:
            raw = marker_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, "no hot-top10 marker file (first run of the day)"
        except OSError as exc:
            return False, f"hot-top10 marker unreadable, fail-open ({exc})"
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            return False, f"hot-top10 marker corrupt, fail-open ({exc})"
        if not isinstance(payload, dict):
            return False, "hot-top10 marker is not a JSON object, fail-open"
        if payload.get("schema_version") != MARKER_SCHEMA_VERSION:
            return (
                False,
                "unknown hot-top10 marker schema version, fail-open",
            )
        marker_date = str(payload.get("run_date") or "")
        today = date.today().isoformat()
        if marker_date != today:
            return False, f"marker run_date {marker_date!r} is not today ({today})"
        # OR-COR-3e7f490e: a delivered report only consumes the dedup slot
        # of the data date it actually covers. A marker left by a stale
        # (previous-trading-day) delivery must NOT block a later run, so
        # today's fresh data can still be delivered through the regular
        # entry once the provider serves it. A missing data_date only
        # happens on v1 markers, which already failed open above.
        data_date = str(payload.get("data_date") or "")
        if data_date != today:
            return False, (
                f"marker data_date {data_date!r} is not today ({today}); "
                "today's data has not been delivered yet"
            )
        if payload.get("delivered") is not True:
            return False, "marker recorded an undelivered run, fail-open"
        return True, f"today's hot-top10 report already delivered ({marker_date})"
    except Exception as exc:  # pragma: no cover - defensive fail-open
        return False, f"hot-top10 dedup gate error, fail-open: {exc}"


def record_hot_top10_marker(
    config: Any,
    *,
    llm_completed: bool,
    notification_status: str,
    data_date: Optional[str] = None,
) -> None:
    """Persist today's delivery marker atomically; errors are swallowed.

    ``data_date`` records the ranking date the delivered report actually
    covers (OR-COR-3e7f490e) — and since r7 it also selects the marker
    FILE, so a late stale delivery writes its own file instead of
    overwriting today's record (OR-COR-341d7b5a). It defaults to today: an
    unknown provider date is treated as current-day data, so the daily
    dedup keeps working exactly as before for realtime providers.
    """
    try:
        marker_date = data_date or date.today().isoformat()
        marker_path = hot_top10_marker_path(config, marker_date)
        payload = {
            "schema_version": MARKER_SCHEMA_VERSION,
            "run_date": date.today().isoformat(),
            "data_date": marker_date,
            "delivered": True,
            "llm_completed": bool(llm_completed),
            "notification_status": str(notification_status or "unknown"),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(),
        }
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = marker_path.with_name(f"{marker_path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, marker_path)
        _prune_old_hot_top10_markers(marker_path.parent)
        logger.info(
            "[HotTop10] 已记录投递标记（按数据日期分文件）: %s", marker_path
        )
    except Exception as exc:
        logger.warning("[HotTop10] 写入当日投递标记失败（忽略）: %s", exc)


def _prune_old_hot_top10_markers(
    directory: Path, *, keep_days: int = MARKER_RETENTION_DAYS
) -> None:
    """Lazy cleanup of per-date marker files older than ``keep_days`` —
    runs best-effort after each successful marker write; errors swallowed.
    The legacy single-blob ``hot_top10_state.json`` does not match the
    per-date pattern and is simply left alone (ignored by all readers)."""
    try:
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        for entry in directory.glob(f"{MARKER_FILE_PREFIX}*.json"):
            suffix = entry.stem[len(MARKER_FILE_PREFIX) :]
            if suffix <= cutoff:  # ISO dates sort lexicographically
                entry.unlink()
    except OSError:
        pass


def _load_delivered_marker_payload(
    config: Any, data_date: str
) -> Optional[Dict[str, Any]]:
    """Read a v2 delivered marker of ``data_date``; ``None`` on any
    problem (fail-open)."""
    try:
        raw = hot_top10_marker_path(config, data_date).read_text(
            encoding="utf-8"
        )
        payload = json.loads(raw)
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != MARKER_SCHEMA_VERSION:
        return None
    if payload.get("delivered") is not True:
        return None
    return payload


def hot_top10_data_date_delivered_today(config: Any, data_date: str) -> tuple:
    """Return ``(skip, reason)`` for a SAME-DAY re-delivery of ``data_date``.

    OR-COR-3e7f490e (narrowed): the data-ready follow-up occurrence must not
    push the same ranking date twice in one day. If today's marker already
    records a successful delivery covering exactly ``data_date`` (whether
    that is today's fresh data or the previous trading day's stale list),
    the follow-up run skips. Since r7 the marker lives in its OWN per-date
    file, so a late stale delivery can never mask it. Markers from earlier
    run dates never block (same-day semantics only); any marker problem
    fails open.
    """
    payload = _load_delivered_marker_payload(config, data_date)
    if payload is None:
        return False, "no usable delivered marker, fail-open"
    marker_date = str(payload.get("run_date") or "")
    if marker_date != date.today().isoformat():
        return False, f"marker run_date {marker_date!r} is not today"
    delivered_date = str(payload.get("data_date") or "")
    if delivered_date != data_date:
        return False, (
            f"marker data_date {delivered_date!r} differs from {data_date!r}"
        )
    return True, (
        f"data date {data_date} already delivered today ({marker_date})"
    )


# --------------------------------------------------------------------------
# Trading-day gate
# --------------------------------------------------------------------------


def is_cn_trading_day_today() -> bool:
    """Whether the CN market is open today (fail-open when unsure)."""
    try:
        from src.core.trading_calendar import get_open_markets_today

        return "cn" in get_open_markets_today()
    except Exception as exc:
        logger.warning(
            "[HotTop10] 交易日判断失败，fail-open 视为交易日: %s", exc
        )
        return True


# --------------------------------------------------------------------------
# Hot-list collection (DSA-native theme rankings)
# --------------------------------------------------------------------------


def _normalize_ranking_date(value: Any) -> Optional[str]:
    """Normalize a provider ranking date to ISO ``YYYY-MM-DD``; ``None`` unknown.

    Tushare board rankings carry ``YYYYMMDD`` dates; the hotspot payload uses
    ISO. Anything unparseable counts as "date unknown" (fail-open semantics:
    the report falls back to the current behavior of not labeling a date).
    """
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _collect_hot_list_items(
    count: int,
    hotspot_service: Any = None,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Fetch and normalize the theme hot list; ``items is None`` when unusable.

    Returns ``(items, ranking_date)``.

    Selection (OR-COR-a7e7c3a3): candidates from ALL buckets compete after
    name de-duplication — they are sorted by change_pct descending (entries
    without a number keep bucket order at the end) and only then truncated
    to ``count``. The old sequential fill stopped at ``count`` inside
    ``active_themes``/``leading_industries`` and wrongly evicted
    small-negative concepts on negative-industry days.

    ``ranking_date`` (OR-COR-3e7f490e) is the payload trade date, falling
    back to the first per-item trade date, so downstream stages can label
    the report with the real list date even when the provider serves the
    previous trading day's rankings.
    """
    if hotspot_service is None:
        from src.services.market_hotspot_service import MarketHotspotService

        hotspot_service = MarketHotspotService()

    payload = hotspot_service.get_hotspots(market="cn", limit=count)
    if not isinstance(payload, dict):
        return None, None

    candidates: List[Dict[str, Any]] = []
    seen_names = set()
    buckets = [
        ("active_themes", None),
        ("leading_industries", "industry"),
        ("leading_concepts", "concept"),
    ]
    for bucket, default_kind in buckets:
        raw_items = payload.get(bucket)
        if not isinstance(raw_items, list):
            continue
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            kind = entry.get("source") or default_kind or "theme"
            candidates.append(
                {
                    "name": name,
                    "code": str(entry.get("code") or "").strip(),
                    "change_pct": entry.get("change_pct"),
                    "kind": str(kind),
                    "phase": str(entry.get("phase") or "unknown"),
                    "strength_score": entry.get("strength_score"),
                    "reason": str(entry.get("reason") or "").strip(),
                    "trade_date": _normalize_ranking_date(entry.get("trade_date")),
                }
            )
    if not candidates:
        return None, None

    def _change_sort_key(item: Dict[str, Any]) -> Tuple[int, float]:
        value = item.get("change_pct")
        if isinstance(value, (int, float)):
            return (0, -float(value))
        return (1, 0.0)

    candidates.sort(key=_change_sort_key)
    items = candidates[:count]
    for index, item in enumerate(items, 1):
        item["rank"] = index

    ranking_date = _normalize_ranking_date(payload.get("trade_date"))
    if ranking_date is None:
        for item in candidates:
            if item.get("trade_date"):
                ranking_date = item["trade_date"]
                break
    return items, ranking_date


def _format_change_pct(value: Any, language: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A" if language == "en" else "无数据"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


# --------------------------------------------------------------------------
# Prompt assembly / LLM summary
# --------------------------------------------------------------------------


def _build_analyzer(config: Any):
    from src.analyzer import GeminiAnalyzer

    return GeminiAnalyzer(config=config)


def build_hot_top10_prompt(
    items: List[Dict[str, Any]],
    language: str,
    ranking_date: Optional[str] = None,
) -> str:
    """Assemble the single-call summary prompt (bilingual).

    ``ranking_date`` labels the trading day the list data actually covers
    (OR-COR-3e7f490e); when it is not today the model is told explicitly so
    it never presents previous-day rankings as today's market.
    """
    today = date.today().isoformat()
    date_note_en = ""
    date_note_zh = ""
    if ranking_date:
        if ranking_date != today:
            date_note_en = (
                f"Ranking date: {ranking_date}. NOTE: this list is data from "
                "that trading day, NOT today's market; do not describe it as "
                "today's action."
            )
            date_note_zh = (
                f"榜单日期：{ranking_date}。注意：该榜单为上述交易日数据，"
                "并非今日实时行情，请勿当作今日盘面描述。"
            )
        else:
            date_note_en = f"Ranking date: {ranking_date} (today)."
            date_note_zh = f"榜单日期：{ranking_date}（今日）。"

    if language == "en":
        lines = [
            "You are an A-share market hotspot analyst. Below is the market",
            "theme hot list ranked by gain (from DSA industry/concept rankings):",
            "",
        ]
        if date_note_en:
            lines += [date_note_en, ""]
        for item in items:
            lines.append(
                f"{item['rank']}. {item['name']} ({item['kind']}) "
                f"change {_format_change_pct(item['change_pct'], 'en')}, "
                f"phase {item['phase']}"
            )
        lines += [
            "",
            "For EACH theme output: the likely driver (news/funds/event",
            "attribution; mark speculation explicitly), a strength assessment",
            "(strong/medium/weak), an entry advice (wait/light position/",
            "active entry) and the key risk.",
            "Reply with STRICT JSON only (no extra text):",
            '{"summary": "one paragraph on the hotspot mainline of the ranking date above", '
            '"items": [{"rank": 1, "name": "...", "driver": "...", '
            '"strength": "strong|medium|weak", '
            '"advice": "wait|light position|active entry", "risk": "..."}]}',
        ]
        return "\n".join(lines)

    lines = [
        "你是 A 股市场热点分析助手。以下是市场主题热榜"
        "（按涨跌幅排名，来自 DSA 行业/概念排名数据）：",
        "",
    ]
    if date_note_zh:
        lines += [date_note_zh, ""]
    for item in items:
        lines.append(
            f"{item['rank']}. {item['name']}（{item['kind']}）"
            f"涨跌幅 {_format_change_pct(item['change_pct'], 'zh')}，"
            f"阶段 {item['phase']}"
        )
    lines += [
        "",
        "请针对每个主题输出：热榜动因（新闻/资金/事件归因，无明确信息来源时"
        "请标注“推测”）、强度评估（强/中/弱）、介入建议（观望/轻仓介入/积极介入）、"
        "风险提示。",
        "严格只输出以下 JSON，不要输出任何多余文本：",
        '{"summary": "一段话总结上述榜单日期的热点主线与整体参与度", '
        '"items": [{"rank": 1, "name": "主题名", "driver": "动因", '
        '"strength": "强|中|弱", "advice": "观望|轻仓介入|积极介入", '
        '"risk": "风险提示"}]}',
    ]
    return "\n".join(lines)


def parse_llm_summary(text: Any) -> Optional[Dict[str, Any]]:
    """Robustly extract the summary JSON object; ``None`` when unusable."""
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            return None
        cleaned = cleaned[start : end + 1]
    try:
        payload = json.loads(cleaned)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("items"), list):
        payload["items"] = []
    return payload


def _summary_items_by_name(payload: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    if not isinstance(payload, dict):
        return indexed
    for entry in payload.get("items") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if name:
                indexed[name] = entry
    return indexed


# --------------------------------------------------------------------------
# Report rendering (bilingual)
# --------------------------------------------------------------------------


def render_hot_top10_report(
    items: List[Dict[str, Any]],
    summary: Optional[Dict[str, Any]],
    llm_completed: bool,
    language: str,
    ranking_date: Optional[str] = None,
) -> str:
    """Render the markdown report; degraded to data-only when LLM failed.

    ``ranking_date`` (OR-COR-3e7f490e) is shown in the title and header as
    the 榜单日期 the list data actually covers. When the provider served a
    previous trading day's rankings (default trigger 15:10 sits before the
    15:30 data cut), the report says so explicitly instead of presenting
    the list as today's market.
    """
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = date.today().isoformat()
    title_date = ranking_date or today
    stale = bool(ranking_date) and ranking_date != today
    if language == "en":
        title = f"# Market Hot Themes Top {len(items)} — {title_date}"
        ranking_date_note = (
            f"Ranking date: {ranking_date}"
            + (
                " (NOT today; previous trading day data — today's list will be "
                "delivered separately once the data cut is available)"
                if stale
                else " (today)"
            )
            if ranking_date
            else "Ranking date: unknown (provider did not report one)"
        )
        header_note = (
            f"> Generated at: {now_text} | {ranking_date_note} | "
            "Data source: DSA industry/concept rankings (MarketHotspotService), "
            "a theme-level hot list. This is a light overview, NOT per-stock "
            "deep analysis; use the existing stock analysis entry points for that."
        )
        overview_title = "## Hotspot Overview"
        per_item_title = "## Theme Breakdown"
        data_title = "## Hot List Data"
        labels = {
            "driver": "Driver",
            "strength": "Strength",
            "advice": "Entry advice",
            "risk": "Risk",
            "rank": "Rank",
            "theme": "Theme",
            "type": "Type",
            "change": "Change",
            "phase": "Phase",
        }
        llm_failed_note = (
            "> AI summary generation failed this run; the data overview below "
            "is still delivered."
        )
        raw_note_prefix = "> AI summary could not be parsed as structured JSON; raw model output:\n\n"
    else:
        title = f"# 市场热榜 Top {len(items)} 分析 — {title_date}"
        if ranking_date:
            ranking_date_note = (
                f"榜单日期：{ranking_date}"
                + (
                    "（非今日：为上一交易日榜单数据，当日数据就绪后将按当日榜单另行生成）"
                    if stale
                    else "（今日）"
                )
            )
        else:
            ranking_date_note = "榜单日期：未知（数据源未提供日期）"
        header_note = (
            f"> 生成时间：{now_text} ｜ {ranking_date_note} ｜ "
            "数据来源：DSA 行业/概念排名（MarketHotspotService），为主题级热榜。"
            "本报告为热榜轻量概览，非个股深度报告；个股深度分析请使用既有个股分析入口。"
        )
        overview_title = "## 热点总览"
        per_item_title = "## 逐项分析"
        data_title = "## 热榜数据"
        labels = {
            "driver": "热榜动因",
            "strength": "强度评估",
            "advice": "介入建议",
            "risk": "风险提示",
            "rank": "排名",
            "theme": "主题",
            "type": "类型",
            "change": "涨跌幅",
            "phase": "阶段",
        }
        llm_failed_note = (
            "> 本次 AI 摘要生成失败，以下为数据概览（降级交付）。"
        )
        raw_note_prefix = "> AI 摘要未能解析为结构化 JSON，原始模型输出如下：\n\n"

    indexed = _summary_items_by_name(summary)
    lines = [title, "", header_note, "", overview_title, ""]
    if isinstance(summary, dict) and str(summary.get("summary") or "").strip():
        lines.append(str(summary["summary"]).strip())
    elif llm_completed:
        lines.append(raw_note_prefix)
        lines.append("```")
        raw_text = str(summary.get("raw") or "").strip() if summary else ""
        lines.append(raw_text or ("-"))
        lines.append("```")
    else:
        lines.append(llm_failed_note)

    lines += ["", per_item_title, ""]
    for item in items:
        entry = indexed.get(item["name"], {})
        lines.append(
            f"### {item['rank']}. {item['name']}"
            f"（{item['kind']}）｜ {_format_change_pct(item['change_pct'], language)}"
        )
        driver = str(entry.get("driver") or "").strip()
        if not driver:
            driver = item.get("reason") or (
                "AI 摘要缺失" if language != "en" else "AI summary unavailable"
            )
        strength = str(entry.get("strength") or "").strip() or "-"
        advice = str(entry.get("advice") or "").strip() or (
            "观望" if language != "en" else "wait"
        )
        risk = str(entry.get("risk") or "").strip() or (
            "动因不明确，注意追高风险" if language != "en" else "Unclear driver; avoid chasing"
        )
        lines += [
            f"- {labels['driver']}：{driver}",
            f"- {labels['strength']}：{strength}",
            f"- {labels['advice']}：{advice}",
            f"- {labels['risk']}：{risk}",
            "",
        ]

    lines += [data_title, ""]
    lines.append(
        f"| {labels['rank']} | {labels['theme']} | {labels['type']} | "
        f"{labels['change']} | {labels['phase']} |"
    )
    lines.append("| --- | --- | --- | --- | --- |")
    for item in items:
        lines.append(
            f"| {item['rank']} | {item['name']} | {item['kind']} | "
            f"{_format_change_pct(item['change_pct'], language)} | {item['phase']} |"
        )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Delivery (report file + notification channel)
# --------------------------------------------------------------------------


def _hot_top10_report_filename(data_date: Optional[str]) -> str:
    """r9 (review #13 OR-COR-hot-top10-report-overwrite): name the LOCAL
    report file by the DATA date, not the wall clock.

    Same-day back-to-back deliveries of DIFFERENT data dates are legitimate
    (15:10 primary slot ships the previous trading day's list; the 15:35
    data-ready catch-up ships today's list — both allowed by the r7
    per-data-date dedup semantics). Wall-clock naming collapsed both into
    one path and the 'w'-mode save silently overwrote the earlier report
    after its marker was already recorded — an unrecoverable loss. Keying
    the file name on the data date aligns each report with its
    ``hot_top10_state_<data_date>.json`` marker (one artifact per delivered
    data date). An unknown data date degrades to the legacy wall-clock
    name (fail-open).
    """
    stamp: Optional[str] = None
    if data_date:
        text = str(data_date).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                stamp = datetime.strptime(text, fmt).strftime("%Y%m%d")
                break
            except ValueError:
                continue
    if stamp is None:
        stamp = date.today().strftime("%Y%m%d")
    return f"hot_top10_{stamp}.md"


def _deliver(
    report_markdown: str,
    send_notification: bool,
    notifier: Any,
    ownership_verifier: Optional[Any] = None,
    data_date: Optional[str] = None,
) -> Tuple[str, bool]:
    """Save + push the report. Returns ``(status, report_saved)``; never raises.

    ``report_saved`` (OR-COR-8c2d195e) tells the caller whether the local
    report file actually landed. With no successful notification push it is
    the ONLY delivery that counts, so a failed save must propagate into the
    delivery decision instead of being swallowed here.

    ``ownership_verifier`` (OR-COR-5c51e8d7 r6, review #10 probe 2): a
    callable re-checked immediately before EACH side effect — once before
    the report save and again before the notification push (the save can
    take time; the claim must still be ours the instant before we push).
    When it reports the claim lost, that side effect and everything after
    it is skipped (``lost_claim_before_save`` / ``lost_claim_before_notify``),
    so a mid-save takeover can never turn into a second push.

    ``data_date`` (r9, review #13 OR-COR-hot-top10-report-overwrite): the
    ISO date of the list actually being delivered; the local report file is
    named after it so same-day deliveries of different data dates never
    overwrite each other. See :func:`_hot_top10_report_filename`.
    """

    def _claim_lost() -> bool:
        return ownership_verifier is not None and not ownership_verifier()

    try:
        if notifier is None:
            from src.notification import NotificationService

            notifier = NotificationService()
    except Exception as exc:
        logger.warning(
            "[HotTop10] 通知服务初始化失败，报告未保存也未推送: %s\n%s", exc, report_markdown
        )
        return "notifier_init_failed", False

    report_saved = False
    filename = _hot_top10_report_filename(data_date)
    # r6 save-side check: the previous single verdict before the whole
    # delivery left the save→notify stretch unprotected.
    if _claim_lost():
        logger.warning(
            "[HotTop10] 投递认领已被接管（保存前所有权复验失败），不保存报告"
        )
        return "lost_claim_before_save", False
    try:
        path = notifier.save_report_to_file(report_markdown, filename)
        logger.info("[HotTop10] 报告已保存: %s", path)
        report_saved = True
    except Exception as exc:
        # OR-COR-8c2d195e: do NOT swallow silently — the caller must know
        # the report exists nowhere (no save, no push) and retry.
        logger.warning("[HotTop10] 报告保存失败: %s\n%s", exc, report_markdown)

    if not send_notification:
        logger.info("[HotTop10] 通知推送已禁用（--no-notify）")
        return "disabled", report_saved
    # r6 notify-side check (the load-bearing one): re-verify the instant
    # before the push so a takeover during the save aborts here instead of
    # producing a second delivery.
    if _claim_lost():
        logger.warning(
            "[HotTop10] 投递认领已被接管（通知前所有权复验失败），"
            "不推送已保存的报告"
        )
        return "lost_claim_before_notify", report_saved
    try:
        if not notifier.is_available():
            logger.info("[HotTop10] 未配置通知渠道，跳过推送（报告仅落盘）")
            return "no_channel", report_saved
        if notifier.send(report_markdown, route_type="report"):
            logger.info("[HotTop10] 通知推送成功")
            return "sent", report_saved
        logger.warning("[HotTop10] 通知推送失败")
        return "failed", report_saved
    except Exception as exc:
        logger.warning("[HotTop10] 通知推送异常: %s", exc)
        return "failed", report_saved


# --------------------------------------------------------------------------
# Run entry (CLI + scheduler)
# --------------------------------------------------------------------------


def run_hot_top10_analysis(
    config: Any,
    *,
    send_notification: bool = True,
    notifier: Any = None,
    analyzer: Any = None,
    hotspot_service: Any = None,
    respect_dedup: bool = True,
    force_run: bool = False,
) -> HotTop10RunResult:
    """One hot-top10 run, guarded by the cross-slot in-flight mutex.

    OR-COR-9a41d2ce: the primary and data-ready schedule slots register
    under different job names, so the scheduler's per-name in-flight guard
    does not mutually exclude them, and both dedup checks happen before the
    LLM/save/push stages — two overlapping occurrences could both pass the
    checks and push the same list twice. This wrapper takes a process-wide
    non-reentrant mutex around the entire critical section (dedup checks ->
    LLM -> save -> deliver -> marker). A trigger arriving while another run
    holds the mutex exits immediately with ``skipped=True`` and
    ``reason="already_running"`` — nothing is pushed and the day's dedup
    marker is left untouched (OR-COR-8c2d195e recovery semantics).

    OR-COR-7c92a610: that losing trigger is not dropped. Both slots are
    daily-only, so the wrapper retains a ONE-SHOT pending follow-up request
    and the in-flight holder re-executes the run once right after finishing
    (fresh fetch -> full dedup semantics; a same-data-date delivery
    dedup-skips, a new data date ships). The follow-up calls the locked body
    directly and cannot recurse; the primary run's result stays the caller's
    return value and the follow-up outcome is logged.

    Never raises: every stage degrades and logs; see
    :func:`_run_hot_top10_analysis_locked` for the run itself.
    """
    if not _HOT_TOP10_RUN_MUTEX.acquire(blocking=False):
        # OR-COR-7c92a610: the in-flight holder will consume this one-shot
        # request right after finishing, so the overlapping trigger is not
        # lost for the day (both slots fire daily; there is no later slot).
        _HOT_TOP10_PENDING_FOLLOWUP.set()
        logger.warning(
            "[HotTop10] 上一轮热榜分析仍在执行中，本次触发跳过"
            "（已登记一次性待补投请求：不投递、不落当日标记，"
            "首轮完成后自动补执行并重新走完整去重）"
        )
        return HotTop10RunResult(
            delivered=False,
            skipped=True,
            reason="already_running",
        )
    try:
        result = _run_hot_top10_analysis_locked(
            config,
            send_notification=send_notification,
            notifier=notifier,
            analyzer=analyzer,
            hotspot_service=hotspot_service,
            respect_dedup=respect_dedup,
            force_run=force_run,
        )
        # OR-COR-7c92a610: consume the pending follow-up exactly once per
        # entry, while still holding the mutex. The follow-up calls the
        # locked body DIRECTLY, so it can never recurse into itself; a
        # trigger arriving during the follow-up returns already_running and
        # (re)registers the flag for the next run entry.
        if _HOT_TOP10_PENDING_FOLLOWUP.is_set():
            _HOT_TOP10_PENDING_FOLLOWUP.clear()
            logger.info(
                "[HotTop10] 首轮执行期间有触发被互斥跳过：执行一次性补投"
                "（重新取数 → 去重 → 生成 → 保存 → 投递 → 落标记）"
            )
            followup_result = _run_hot_top10_analysis_locked(
                config,
                send_notification=send_notification,
                notifier=notifier,
                analyzer=analyzer,
                hotspot_service=hotspot_service,
                respect_dedup=respect_dedup,
                force_run=force_run,
            )
            logger.info(
                "[HotTop10] 补投完成: delivered=%s skipped=%s reason=%s "
                "llm_completed=%s notification=%s",
                followup_result.delivered,
                followup_result.skipped,
                followup_result.reason,
                followup_result.llm_completed,
                followup_result.notification_status,
            )
        # The primary run's result stays the caller's return value; the
        # follow-up outcome is logged and observable via the marker.
        return result
    finally:
        _HOT_TOP10_RUN_MUTEX.release()


def _run_hot_top10_analysis_locked(
    config: Any,
    *,
    send_notification: bool = True,
    notifier: Any = None,
    analyzer: Any = None,
    hotspot_service: Any = None,
    respect_dedup: bool = True,
    force_run: bool = False,
) -> HotTop10RunResult:
    """Run body executed while holding ``_HOT_TOP10_RUN_MUTEX``.

    One run: fetch -> summarize -> render -> deliver. Never raises: every
    stage degrades and logs. The daily marker is recorded only when the
    report was produced AND delivered — the push succeeded, or the push was
    intentionally skipped/disabled AND the local save succeeded
    (OR-COR-8c2d195e) — so a failed push or save retries later.
    """
    count = getattr(config, "hot_top10_count", DEFAULT_HOT_TOP10_COUNT) or DEFAULT_HOT_TOP10_COUNT
    try:
        count = max(1, min(MAX_HOT_TOP10_COUNT, int(count)))
    except (TypeError, ValueError):
        count = DEFAULT_HOT_TOP10_COUNT
    language = str(getattr(config, "report_language", "zh") or "zh").strip().lower()
    if language not in {"zh", "en"}:
        language = "zh"

    if respect_dedup and not force_run:
        skip, reason = hot_top10_already_delivered_today(config)
        if skip:
            logger.info("[HotTop10] 当日报告已投递，跳过: %s", reason)
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason=f"already_delivered_today: {reason}",
            )

    if not force_run and getattr(config, "trading_day_check_enabled", True):
        if not is_cn_trading_day_today():
            logger.info("[HotTop10] 今日 A 股非交易日，跳过热榜分析")
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason="non_trading_day",
            )

    items, ranking_date = _collect_hot_list_items(count, hotspot_service=hotspot_service)
    if not items:
        logger.warning("[HotTop10] 热榜数据获取失败，本轮不生成报告")
        return HotTop10RunResult(
            delivered=False,
            skipped=True,
            reason="hotspot_data_unavailable",
        )
    effective_data_date = ranking_date or date.today().isoformat()
    if respect_dedup and not force_run:
        # Same-day re-delivery guard (OR-COR-3e7f490e, narrowed): the
        # data-ready follow-up occurrence may fire while the provider still
        # serves the previous trading day's rankings — the very list the
        # primary slot already delivered. Pushing it again would duplicate
        # the stale report, so a delivery covering the exact same data date
        # recorded today skips instead.
        same_date_skip, same_date_reason = hot_top10_data_date_delivered_today(
            config, effective_data_date
        )
        if same_date_skip:
            logger.info(
                "[HotTop10] 该榜单数据日期今日已投递，跳过重复推送: %s",
                same_date_reason,
            )
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason=f"same_data_date_delivered_today: {same_date_reason}",
            )
    if ranking_date and ranking_date != date.today().isoformat():
        logger.info(
            "[HotTop10] 榜单日期为 %s（非今日）：报告将按该日期标注，"
            "且不占用今日投递标记，当日数据就绪后可再投",
            ranking_date,
        )

    # OR-COR-5c51e8d7: atomic cross-process claim for this data date. The
    # run mutex above cannot exclude two INDEPENDENT processes sharing the
    # same DATABASE_PATH (CLI --schedule beside the Web/API/desktop runtime
    # scheduler), and the dedup checks above all happen BEFORE the
    # LLM/save/push stages — two processes could both pass them and push
    # the same list. The token-based ownership claim below makes check ->
    # generate -> save -> push -> marker exclusive per data date: the token
    # is re-verified before the delivery side effects and before the
    # marker, so a lost steal race aborts with reason=lost_claim.
    # force_run (explicit human override) stays unclaimed.
    delivery_claim = None
    if not force_run:
        delivery_claim = acquire_hot_top10_delivery_claim(
            config, effective_data_date
        )
        if delivery_claim is None:
            logger.warning(
                "[HotTop10] 该榜单数据日期（%s）已被其他进程认领投递，本次跳过："
                "不推送、不落当日标记，等待下次触发重试",
                effective_data_date,
            )
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason="already_claimed",
            )
        if respect_dedup:
            # Close the check->claim window: the other process may have
            # finished its whole delivery between the marker reads above and
            # this claim being won. Its marker landed BEFORE it released the
            # claim, so a fresh read here settles the race.
            claimed_skip, claimed_reason = hot_top10_data_date_delivered_today(
                config, effective_data_date
            )
            if claimed_skip:
                delivery_claim.release()
                logger.info(
                    "[HotTop10] 认领后发现该数据日期已被投递，跳过: %s",
                    claimed_reason,
                )
                return HotTop10RunResult(
                    delivered=False,
                    skipped=True,
                    reason=f"same_data_date_delivered_today: {claimed_reason}",
                )

    try:
        llm_completed = False
        summary: Optional[Dict[str, Any]] = None
        try:
            if analyzer is None:
                analyzer = _build_analyzer(config)
            prompt = build_hot_top10_prompt(items, language, ranking_date=ranking_date)
            llm_text = analyzer.generate_text(
                prompt,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )
            if isinstance(llm_text, str) and llm_text.strip():
                summary = parse_llm_summary(llm_text)
                if summary is not None:
                    llm_completed = True
                else:
                    summary = {"raw": llm_text}
                    logger.warning("[HotTop10] AI 摘要 JSON 解析失败，按原文降级渲染")
            else:
                logger.warning("[HotTop10] AI 摘要生成失败（返回空），降级为数据概览")
        except Exception as exc:
            logger.warning("[HotTop10] AI 摘要生成异常，降级为数据概览: %s", exc)

        report_markdown = render_hot_top10_report(
            items, summary, llm_completed, language, ranking_date=ranking_date
        )
        # OR-COR-5c51e8d7 r6 (review #10 probe 2): ownership is re-verified
        # inside _deliver before EACH side effect (save, then notify, then
        # the marker below) — a steal race lost at ANY point aborts with all
        # remaining side effects suppressed (reason=lost_claim), so among
        # processes racing the same data date exactly one ever delivers.
        notification_status, report_saved = _deliver(
            report_markdown,
            send_notification,
            notifier,
            ownership_verifier=(
                delivery_claim.verify_owner
                if delivery_claim is not None
                else None
            ),
            data_date=effective_data_date,
        )
        if notification_status.startswith("lost_claim"):
            logger.warning(
                "[HotTop10] 投递认领在副作用间隙被接管（%s），"
                "本次中止投递：不推送、不落当日标记",
                notification_status,
            )
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason="lost_claim",
                notification_status=notification_status,
            )
        if notification_status in {"failed", "notifier_init_failed"}:
            # Push failed: leave the marker unset so the next occurrence retries.
            logger.warning(
                "[HotTop10] 推送未成功（status=%s），不记录当日标记，等待下次重试",
                notification_status,
            )
        elif not report_saved and notification_status != "sent":
            # OR-COR-8c2d195e: no successful notification push AND the local
            # save failed, so nothing was actually delivered. The day's dedup
            # marker must stay open, otherwise a recoverable storage failure
            # would silently swallow the whole day's report. (A successful push
            # with a failed save still counts as delivered and records below.)
            logger.warning(
                "[HotTop10] 报告保存失败且无成功通知交付（status=%s），"
                "不记录当日标记，等待下次重试",
                notification_status,
            )
        else:
            # OR-COR-5c51e8d7 r6: final re-verification before recording
            # the marker too. If the claim was stolen in the residual window
            # since the push, the true owner records the marker — we must
            # not (our push, if any, is the documented residual duplicate;
            # the marker and the dedup slot stay with the rightful owner).
            if (
                delivery_claim is not None
                and not delivery_claim.verify_owner()
            ):
                logger.warning(
                    "[HotTop10] 落当日标记前发现认领已被接管"
                    "（所有权校验失败），不记录当日标记"
                )
                return HotTop10RunResult(
                    delivered=False,
                    skipped=True,
                    reason="lost_claim",
                    report_markdown=report_markdown,
                    llm_completed=llm_completed,
                    notification_status=notification_status,
                    ranking_date=ranking_date,
                )
            record_hot_top10_marker(
                config,
                llm_completed=llm_completed,
                notification_status=notification_status,
                # The dedup slot belongs to the data date the report covers; a
                # stale (previous-day) delivery therefore leaves today's slot
                # open for the fresh data (OR-COR-3e7f490e).
                data_date=ranking_date,
            )

        # The run only counts as delivered when the report reached somewhere:
        # a successful push, or a successful local save (for the disabled /
        # no-channel paths that rely on the file).
        delivery_completed = report_saved or notification_status == "sent"
        return HotTop10RunResult(
            delivered=delivery_completed,
            skipped=False,
            reason="ok" if delivery_completed else f"delivery_failed: {notification_status}",
            report_markdown=report_markdown,
            llm_completed=llm_completed,
            notification_status=notification_status,
            ranking_date=ranking_date,
        )
    finally:
        # Release the claim on EVERY path: push/save failure leaves the
        # MARKER open for retry (OR-COR-8c2d195e) and the released claim
        # lets that retry proceed; after a recorded marker the claim has
        # served its purpose (the next data date claims a fresh file).
        # The ownership check inside release only ever deletes a claim this
        # process still owns (OR-COR-5c51e8d7 r5).
        if delivery_claim is not None:
            delivery_claim.release()
