"""Configuration file manager with atomic read/write behavior."""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from dotenv import dotenv_values

_ASSIGNMENT_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_FALLBACK_REWRITE_ERRNOS = {errno.EBUSY, errno.EXDEV}

logger = logging.getLogger(__name__)


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
        if not self._env_path.exists():
            return {}

        values = dotenv_values(self._env_path)
        return {
            str(key): "" if value is None else str(value)
            for key, value in values.items()
            if key is not None
        }

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
    ) -> Tuple[List[str], List[str], str]:
        """Apply updates into `.env` file using atomic replace when possible."""
        with self._lock:
            current_values = self.read_config_map()
            mutable_updates: Dict[str, str] = {}
            skipped_masked: List[str] = []

            for key, value in updates:
                key_upper = key.upper()
                current_value = current_values.get(key_upper)

                if key_upper in sensitive_keys and value == mask_token:
                    if current_value not in (None, ""):
                        skipped_masked.append(key_upper)
                    continue

                if current_value == value:
                    continue

                mutable_updates[key_upper] = value

            if mutable_updates:
                self._atomic_upsert(mutable_updates)

            return list(mutable_updates.keys()), skipped_masked, self.get_config_version()

    def _atomic_upsert(self, updates: Dict[str, str]) -> None:
        """Write updates with atomic rename and in-place fallback for mounted files."""
        lines = self._read_lines()
        key_to_index = self._find_last_key_indexes(lines)

        for key, value in updates.items():
            line_value = value.replace("\n", "")
            new_line = f"{key}={line_value}"
            if key in key_to_index:
                lines[key_to_index[key]] = new_line
            else:
                lines.append(new_line)

        if not self._env_path.parent.exists():
            self._env_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = self._env_path.with_suffix(self._env_path.suffix + ".tmp")
        content = "\n".join(lines)
        if content and not content.endswith("\n"):
            content += "\n"

        with temp_path.open("w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())

        try:
            os.replace(temp_path, self._env_path)
        except OSError as exc:
            if exc.errno not in _FALLBACK_REWRITE_ERRNOS:
                raise

            logger.warning(
                "Atomic replace for .env failed with errno=%s, falling back to in-place rewrite",
                exc.errno,
            )
            self._rewrite_in_place(content)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _rewrite_in_place(self, content: str) -> None:
        """Rewrite `.env` content in place when rename is unsupported by mount type."""
        with self._env_path.open("w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())

    def _read_lines(self) -> List[str]:
        if not self._env_path.exists():
            return []
        return self._env_path.read_text(encoding="utf-8").splitlines()

    @staticmethod
    def _find_last_key_indexes(lines: List[str]) -> Dict[str, int]:
        key_to_index: Dict[str, int] = {}
        for index, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            matched = _ASSIGNMENT_PATTERN.match(raw_line)
            if not matched:
                continue

            key_to_index[matched.group(1).upper()] = index

        return key_to_index

    @staticmethod
    def _resolve_env_path() -> Path:
        env_file = os.getenv("ENV_FILE")
        if env_file:
            return Path(env_file).resolve()

        return (Path(__file__).resolve().parent.parent.parent / ".env").resolve()
