# -*- coding: utf-8 -*-
"""Allow `python -m src.cli` invocation."""

from __future__ import annotations

from src.cli.app import main

if __name__ == "__main__":
    raise SystemExit(main())
