# -*- coding: utf-8 -*-
"""CLI environment helpers (`DSA_HOME`, stdio isolation for `--json` / MCP)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict


def apply_dsa_home_env(environ: Dict[str, str] | None = None) -> None:
    """Apply ``DSA_HOME`` defaults without overriding explicit env settings.

    When ``DSA_HOME`` is set, only populates ``ENV_FILE`` and ``DATABASE_PATH``
    if they are not already explicitly set in the environment. Never alters
    behavior when ``DSA_HOME`` is unset.
    """
    env = os.environ if environ is None else environ
    raw_home = (env.get("DSA_HOME") or "").strip()
    if not raw_home:
        return

    home_dir = Path(raw_home).expanduser()
    home_dir.mkdir(parents=True, exist_ok=True)

    if not (env.get("ENV_FILE") or "").strip():
        env["ENV_FILE"] = str(home_dir / ".env")
    if not (env.get("DATABASE_PATH") or "").strip():
        env["DATABASE_PATH"] = str(home_dir / "stock_analysis.db")


def configure_cli_stderr_logging(*, quiet: bool = False) -> None:
    """Ensure all Python logging goes to ``stderr`` so ``stdout`` stays clean."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.ERROR if quiet else logging.WARNING)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(stream_handler)
    root.setLevel(logging.ERROR if quiet else logging.WARNING)
