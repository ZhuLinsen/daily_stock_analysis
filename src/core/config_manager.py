"""Configuration file manager with atomic read/write behavior."""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import re
import stat
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional, Set, Tuple

from dotenv import dotenv_values

_ASSIGNMENT_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_FALLBACK_REWRITE_ERRNOS = {errno.EBUSY, errno.EXDEV}
# Warning code returned by apply_updates when the atomic replace had to be
# skipped so the original owner and group keep their access to `.env`.
ENV_OWNERSHIP_NOT_PRESERVED_WARNING = "env_ownership_not_preserved"
_COMPOSE_ESCAPED_ENV_VALUE_KEYS = frozenset({"CUSTOM_WEBHOOK_BODY_TEMPLATE"})
_APPLICATION_TEMPLATE_PLACEHOLDER_PATTERN = re.compile(
    r"(?<!\$)\$(?:"
    r"\{(content_json|title_json|content|title)\}"
    r"|(content_json|title_json|content|title)\b"
    r")"
)
_ESCAPED_APPLICATION_TEMPLATE_PLACEHOLDER_PATTERN = re.compile(
    r"\$\$(?:"
    r"\{(content_json|title_json|content|title)\}"
    r"|(content_json|title_json|content|title)\b"
    r")"
)

logger = logging.getLogger(__name__)


def escape_compose_sensitive_env_value(key: str, value: str) -> str:
    """Escape app template placeholders that Docker Compose would interpolate."""
    if key.upper() not in _COMPOSE_ESCAPED_ENV_VALUE_KEYS:
        return value

    def _replace(match: re.Match[str]) -> str:
        braced_name = match.group(1)
        plain_name = match.group(2)
        if braced_name is not None:
            return f"$${{{braced_name}}}"
        return f"$${plain_name}"

    return _APPLICATION_TEMPLATE_PLACEHOLDER_PATTERN.sub(_replace, value)


def unescape_compose_sensitive_env_value(key: str, value: str) -> str:
    """Restore app template placeholders escaped for Docker Compose storage."""
    if key.upper() not in _COMPOSE_ESCAPED_ENV_VALUE_KEYS:
        return value

    def _replace(match: re.Match[str]) -> str:
        braced_name = match.group(1)
        plain_name = match.group(2)
        if braced_name is not None:
            return f"${{{braced_name}}}"
        return f"${plain_name}"

    return _ESCAPED_APPLICATION_TEMPLATE_PLACEHOLDER_PATTERN.sub(_replace, value)


@dataclass
class ConfigLineEntry:
    """Structured representation of a single `.env` line."""

    kind: Literal["assignment", "comment", "blank", "raw"]
    raw_line: str
    key: Optional[str] = None
    value: str = ""
    updated: bool = False

    @classmethod
    def parse(cls, raw_line: str) -> "ConfigLineEntry":
        stripped = raw_line.strip()
        if not stripped:
            return cls(kind="blank", raw_line=raw_line)
        if stripped.startswith("#"):
            return cls(kind="comment", raw_line=raw_line)

        matched = _ASSIGNMENT_PATTERN.match(raw_line)
        if matched:
            return cls(
                kind="assignment",
                raw_line=raw_line,
                key=matched.group(1),
                value=matched.group(2),
            )

        return cls(kind="raw", raw_line=raw_line)

    @classmethod
    def assignment(cls, key: str, value: str) -> "ConfigLineEntry":
        return cls(
            kind="assignment",
            raw_line=f"{key}={value}",
            key=key,
            value=value,
            updated=True,
        )

    def render(self) -> str:
        if self.kind == "assignment" and self.updated and self.key is not None:
            return f"{self.key}={self.value}"
        return self.raw_line


class ConfigManager:
    """Manage `.env` read/write operations with optimistic versioning."""

    def __init__(self, env_path: Optional[Path] = None):
        self._env_path = env_path or self._resolve_env_path()
        self._lock = threading.RLock()

    @property
    def env_path(self) -> Path:
        """Return active `.env` path."""
        return self._env_path

    def read_config_map(self) -> Dict[str, str]:
        """Read key-value mapping from `.env` file."""
        return self._read_config_map(normalize_values=True)

    def _read_config_map(self, *, normalize_values: bool) -> Dict[str, str]:
        """Read key-value mapping from `.env` file."""
        if not self._env_path.exists():
            return {}

        raw_values = dotenv_values(self._env_path, interpolate=False)
        if normalize_values:
            values = dotenv_values(self._env_path)
            for raw_key, raw_value in raw_values.items():
                if (
                    raw_key is not None
                    and str(raw_key).upper() in _COMPOSE_ESCAPED_ENV_VALUE_KEYS
                ):
                    values[raw_key] = raw_value
        else:
            values = raw_values
        config_map: Dict[str, str] = {}
        for key, value in values.items():
            if key is None:
                continue
            normalized_key = str(key)
            normalized_value = "" if value is None else str(value)
            if normalize_values:
                normalized_value = unescape_compose_sensitive_env_value(
                    normalized_key,
                    normalized_value,
                )
            config_map[normalized_key] = normalized_value
        return config_map

    def get_config_version(self) -> str:
        """Return deterministic version string based on file state."""
        if not self._env_path.exists():
            return "missing:0"

        content = self._env_path.read_bytes()
        file_stat = self._env_path.stat()
        content_hash = hashlib.sha256(content).hexdigest()
        return f"{file_stat.st_mtime_ns}:{content_hash}"

    def get_updated_at(self) -> Optional[str]:
        """Return `.env` last update time in ISO8601 format."""
        if not self._env_path.exists():
            return None

        file_stat = self._env_path.stat()
        updated_at = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc)
        return updated_at.isoformat()

    def apply_updates(
        self,
        updates: Iterable[Tuple[str, str]],
        sensitive_keys: Set[str],
        mask_token: str,
    ) -> Tuple[List[str], List[str], str, List[str]]:
        """Apply updates into `.env` file using atomic replace when possible.

        Returns the updated keys, the masked keys that were skipped, the new
        config version, and warning codes for write conditions the operator
        should know about (see ``ENV_OWNERSHIP_NOT_PRESERVED_WARNING``).
        """
        with self._lock:
            current_values = self.read_config_map()
            stored_values = self._read_config_map(normalize_values=False)
            mutable_updates: Dict[str, str] = {}
            skipped_masked: List[str] = []

            for key, value in updates:
                key_upper = key.upper()
                current_value = current_values.get(key_upper)

                if key_upper in sensitive_keys and value == mask_token:
                    if current_value not in (None, ""):
                        skipped_masked.append(key_upper)
                    continue

                stored_value = stored_values.get(key_upper)
                canonical_stored_value = escape_compose_sensitive_env_value(
                    key_upper,
                    value.replace("\n", ""),
                )
                if current_value == value and (
                    key_upper not in _COMPOSE_ESCAPED_ENV_VALUE_KEYS
                    or stored_value == canonical_stored_value
                ):
                    continue

                mutable_updates[key_upper] = value

            write_warnings: List[str] = []
            if mutable_updates:
                write_warnings = self._atomic_upsert(mutable_updates)

            return (
                list(mutable_updates.keys()),
                skipped_masked,
                self.get_config_version(),
                write_warnings,
            )

    def _atomic_upsert(self, updates: Dict[str, str]) -> List[str]:
        """Write updates with atomic rename and in-place fallback for mounted files.

        Returns warning codes for conditions the operator should know about.
        """
        entries = self._read_entries()
        key_to_index = self._find_last_key_indexes(entries)

        for key, value in updates.items():
            line_value = value.replace("\n", "")
            line_value = escape_compose_sensitive_env_value(key, line_value)
            if key in key_to_index:
                entries[key_to_index[key]] = ConfigLineEntry.assignment(key, line_value)
            else:
                entries.append(ConfigLineEntry.assignment(key, line_value))

        if not self._env_path.parent.exists():
            self._env_path.parent.mkdir(parents=True, exist_ok=True)

        env_existed = self._env_path.exists()
        existing_stat = self._env_path.stat() if env_existed else None
        existing_mode = stat.S_IMODE(existing_stat.st_mode) if env_existed else 0o600
        # mkstemp creates the replacement under the process's own uid and
        # primary group, so the target's owner and group have to be carried
        # over explicitly.
        existing_uid = existing_stat.st_uid if env_existed else None
        existing_gid = existing_stat.st_gid if env_existed else None
        content = "\n".join(entry.render() for entry in entries)
        if content and not content.endswith("\n"):
            content += "\n"

        temp_fd, temp_name = tempfile.mkstemp(
            dir=self._env_path.parent, prefix=f".{self._env_path.name}.", suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8", newline="\n") as file_obj:
                file_obj.write(content)
                file_obj.flush()
                os.fsync(file_obj.fileno())
            warnings: List[str] = []
            replaced = False
            if self._preserve_env_ownership(temp_path, existing_uid, existing_gid):
                # chown clears the setuid/setgid bits, so the mode is applied
                # after the ownership has been carried over.
                temp_path.chmod(existing_mode)
                try:
                    os.replace(temp_path, self._env_path)
                    replaced = True
                except OSError as exc:
                    if exc.errno not in _FALLBACK_REWRITE_ERRNOS:
                        raise

                    logger.warning(
                        "Atomic replace for .env failed with errno=%s, falling back to in-place rewrite",
                        exc.errno,
                    )
            else:
                # Replacing anyway would move the file onto the replacement's
                # owner and strip the original owner's (or shared group's)
                # access, so keep the existing inode instead: the in-place
                # rewrite preserves the ownership and the mode.
                warnings.append(ENV_OWNERSHIP_NOT_PRESERVED_WARNING)
            if not replaced:
                self._rewrite_in_place(content)
                if not env_existed:
                    # open("w") created the file under the process umask, which
                    # is typically 0644. This is the bind-mount case the fallback
                    # exists for, so the new .env would ship its secrets
                    # world-readable.
                    self._env_path.chmod(existing_mode)
            return warnings
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _preserve_env_ownership(temp_path: Path, uid: Optional[int], gid: Optional[int]) -> bool:
        """Carry the target `.env` owner and group onto the replacement file.

        chmod only copies mode bits, and mkstemp creates the file under the
        process's own uid and primary group. Without this, an atomic replace
        moves the `.env` onto the saving process: a `.env` shared through a
        secondary group (owner:shared, 0640) loses that group's read access,
        and an owner-only `.env` (0600) locks out its original owner the
        moment a privileged process saves it -- previously the umask-derived
        0644 hid both problems behind world-read. The in-place fallback path
        needs no such step because it truncates the existing inode and keeps
        its ownership.

        Returns True when the replacement carries the target's owner and
        group (or the file is new). Returns False when the chown was
        refused; the caller must then keep the original file, because
        replacing it would move the `.env` onto the replacement's owner.
        """
        if uid is None and gid is None:
            return True
        try:
            temp_stat = temp_path.stat()
            if temp_stat.st_uid == uid and temp_stat.st_gid == gid:
                return True
            # -1 leaves that id unchanged, matching os.chown's convention.
            os.chown(temp_path, -1 if uid is None else uid, -1 if gid is None else gid)
        except (OSError, NotImplementedError, AttributeError) as exc:
            logger.warning(
                "Could not preserve .env ownership (uid=%s, gid=%s, %s); "
                "keeping the original file so its owner keeps access. "
                "Run the service as the file's owner and a member of its "
                "group to restore the atomic replace.",
                uid, gid, type(exc).__name__,
            )
            return False
        return True

    def _rewrite_in_place(self, content: str) -> None:
        """Rewrite `.env` content in place when rename is unsupported by mount type."""
        with self._env_path.open("w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())

    def _read_entries(self) -> List[ConfigLineEntry]:
        if not self._env_path.exists():
            return []
        return [
            ConfigLineEntry.parse(raw_line)
            for raw_line in self._env_path.read_text(encoding="utf-8").splitlines()
        ]

    @staticmethod
    def _find_last_key_indexes(entries: List[ConfigLineEntry]) -> Dict[str, int]:
        key_to_index: Dict[str, int] = {}
        for index, entry in enumerate(entries):
            if entry.kind != "assignment" or entry.key is None:
                continue
            key_to_index[entry.key.upper()] = index

        return key_to_index

    @staticmethod
    def _resolve_env_path() -> Path:
        env_file = os.getenv("ENV_FILE")
        if env_file:
            return Path(env_file).resolve()

        return (Path(__file__).resolve().parent.parent.parent / ".env").resolve()
